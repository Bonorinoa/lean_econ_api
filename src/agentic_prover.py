"""
agentic_prover.py

Leanstral + MCP agentic prover using Mistral's Conversations API (run_async).

Leanstral drives the proving loop autonomously via tool calls:
  - MCP tools (lean_diagnostic_messages, lean_goal, etc.) for reading Lean state
  - Custom Python functions (apply_tactic, get_current_proof_state) for writing
    tactics and querying the current state

The Python controller owns:
  - Working file management (via ProofFileController)
  - Checkpoint save/restore on tactic application
  - Final verification via the local Lean compiler (MCP is guidance, not truth)

Usage:
  from agentic_prover import prove_theorem_agentic
  result = prove_theorem_agentic(theorem_with_sorry)
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any, cast

from dotenv import load_dotenv

from lean_diagnostics import extract_json_payload, normalize_structured_diagnostics
from lean_verifier import verify
from mcp_runtime import PROJECT_ROOT, open_mistral_run_context
from model_config import LEANSTRAL_MODEL
from proof_file_controller import ProofFileController
from prover_backend import register_prover

load_dotenv(PROJECT_ROOT / ".env")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TIMEOUT_MS = 120_000  # 2 minutes for the full run_async conversation
DEFAULT_MAX_STEPS = 12  # not enforced directly — run_async manages its own loop

STOP_PROOF_COMPLETE = "proof_complete"
STOP_PROOF_INCOMPLETE = "proof_incomplete"
STOP_RUN_ERROR = "run_error"
STOP_TIMEOUT = "timeout"
PARTIAL_TIMEOUT_CLEANUP_WARNING = (
    "Agentic prover stopped during Lean/MCP cleanup after a timeout. "
    "Returning the latest proof state."
)
RETRYABLE_STATUS_CODES = {429, 503}
BACKOFF_DELAYS_SECONDS = (2, 4, 8, 16)
MAX_CONSECUTIVE_APPLY_WITHOUT_DIAGNOSTICS = 5
DEFAULT_MAX_TOTAL_TOOL_CALLS = 36
DEFAULT_MAX_SEARCH_TOOL_CALLS = 4
DEFAULT_MAX_CONSECUTIVE_READ_ONLY_CALLS = 6
LOCAL_FAST_PATH_MAX_CHARS = 1_400
LOCAL_FAST_PATH_MAX_LINES = 18
LOCAL_FAST_PATH_MAX_ATTEMPTS = 4
TRACE_SCHEMA_VERSION = 2
CIRCUIT_BREAKER_WARNING = (
    "CIRCUIT BREAKER TRIGGERED: You must use lean_diagnostic_messages to check your work "
    "before applying more tactics."
)
SEARCH_PRECONDITION_WARNING = (
    "SEARCH PRECONDITION NOT MET: First try a plausible tactic and inspect "
    "lean_diagnostic_messages before using search tools."
)
SEARCH_BUDGET_WARNING = (
    "SEARCH BUDGET EXHAUSTED: Stop using search/suggestion tools and either "
    "apply a tactic or inspect diagnostics."
)
DUPLICATE_READ_ONLY_WARNING = (
    "DUPLICATE READ-ONLY CALL BLOCKED: The proof state has not changed since "
    "the last identical query. Apply a tactic or choose a different tool."
)
AGENTIC_SEARCH_TOOLS = frozenset(
    {
        "lean_multi_attempt",
        "lean_code_actions",
        "lean_state_search",
        "lean_hammer_premise",
    }
)
AGENTIC_ALLOWED_TOOLS = frozenset(
    {
        "apply_tactic",
        "lean_goal",
        "lean_diagnostic_messages",
        *AGENTIC_SEARCH_TOOLS,
    }
)
LOCAL_FAST_PATH_BLOCKLIST = (
    "Real.rpow",
    "HasDerivAt",
    "HasFDerivAt",
    "Integrable",
    "Measure",
    "Filter",
    "Matrix",
    "LinearMap",
    "Submodule",
    "∫",
    "∑",
    "∏",
)
LOCAL_FAST_PATH_CORE_TACTICS = (
    "aesop",
    "simp",
    "simpa",
    "constructor <;> aesop",
)
LOCAL_FAST_PATH_DISCRETE_TACTICS = (
    "norm_num",
    "omega",
)
LOCAL_FAST_PATH_ALGEBRA_TACTICS = (
    "ring_nf",
    "ring",
    "linarith",
    "nlinarith",
)
LOCAL_FAST_PATH_FIELD_TACTICS = ("field_simp\nring",)
NUMERIC_LITERAL_RE = re.compile(r"\b\d+(?:\.\d+)?\b")
TACTIC_HYPOTHESIS_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_']*$")


class ToolBudgetExceededError(RuntimeError):
    """Raised when the prover burns through its tool-call budget."""


# ---------------------------------------------------------------------------
# Logging helper
# ---------------------------------------------------------------------------


def _log(
    on_log,
    stage: str,
    message: str,
    data: str | None = None,
    status: str = "done",
    elapsed_ms: float | None = None,
):
    """Emit a pipeline log entry."""
    if on_log:
        on_log({"stage": stage, "message": message, "data": data,
                "status": status, "elapsed_ms": elapsed_ms})
    else:
        print(f"[agentic] {stage}: {message}")


@dataclass
class AgenticToolTracker:
    """Track tool usage patterns to prevent runaway local-tool loops."""

    max_total_tool_calls: int = DEFAULT_MAX_TOTAL_TOOL_CALLS
    max_search_tool_calls: int = DEFAULT_MAX_SEARCH_TOOL_CALLS
    max_consecutive_read_only_calls: int = DEFAULT_MAX_CONSECUTIVE_READ_ONLY_CALLS
    consecutive_apply_without_diagnostics: int = 0
    consecutive_read_only_calls: int = 0
    total_tool_calls: int = 0
    total_apply_calls: int = 0
    total_diagnostic_calls: int = 0
    total_search_calls: int = 0
    circuit_breaker_hits: int = 0
    blocked_tool_calls: int = 0
    search_budget_hits: int = 0
    duplicate_read_only_hits: int = 0
    tool_budget_stop_hits: int = 0
    last_read_only_signature: tuple[str, str] | None = None

    def should_block_apply(self) -> bool:
        return (
            self.consecutive_apply_without_diagnostics >= MAX_CONSECUTIVE_APPLY_WITHOUT_DIAGNOSTICS
        )

    def note_apply_tactic_executed(self) -> None:
        self.total_tool_calls += 1
        self.total_apply_calls += 1
        self.consecutive_apply_without_diagnostics += 1
        self.consecutive_read_only_calls = 0
        self.last_read_only_signature = None

    def note_diagnostic_check(self, arguments: Any) -> None:
        self.total_tool_calls += 1
        self.total_diagnostic_calls += 1
        self.consecutive_apply_without_diagnostics = 0
        self.consecutive_read_only_calls += 1
        self.last_read_only_signature = _tool_signature("lean_diagnostic_messages", arguments)

    def note_read_only_tool(self, tool_name: str, arguments: Any) -> None:
        self.total_tool_calls += 1
        self.consecutive_read_only_calls += 1
        if tool_name in AGENTIC_SEARCH_TOOLS:
            self.total_search_calls += 1
        self.last_read_only_signature = _tool_signature(tool_name, arguments)

    def note_blocked_tool(
        self,
        tool_name: str,
        *,
        search_budget: bool = False,
        duplicate_read_only: bool = False,
    ) -> None:
        self.total_tool_calls += 1
        self.blocked_tool_calls += 1
        if search_budget:
            self.search_budget_hits += 1
        if duplicate_read_only:
            self.duplicate_read_only_hits += 1

    def note_circuit_breaker(self) -> None:
        self.circuit_breaker_hits += 1

    def has_exhausted_total_budget(self) -> bool:
        return self.total_tool_calls >= self.max_total_tool_calls

    def has_exhausted_search_budget(self) -> bool:
        return self.total_search_calls >= self.max_search_tool_calls

    def has_read_only_loop(self) -> bool:
        return self.consecutive_read_only_calls >= self.max_consecutive_read_only_calls

    def is_duplicate_read_only_call(self, tool_name: str, arguments: Any) -> bool:
        if tool_name == "apply_tactic":
            return False
        return self.last_read_only_signature == _tool_signature(tool_name, arguments)

    def note_budget_stop(self) -> None:
        self.tool_budget_stop_hits += 1


def _budget_limits(max_steps: int) -> tuple[int, int, int]:
    """Scale tool budgets from the advisory step budget."""
    safe_steps = max(1, max_steps)
    max_total_tool_calls = max(DEFAULT_MAX_TOTAL_TOOL_CALLS, safe_steps * 3)
    max_search_tool_calls = max(DEFAULT_MAX_SEARCH_TOOL_CALLS, safe_steps // 3)
    max_consecutive_read_only_calls = max(
        DEFAULT_MAX_CONSECUTIVE_READ_ONLY_CALLS,
        safe_steps // 2,
    )
    return (
        max_total_tool_calls,
        max_search_tool_calls,
        max_consecutive_read_only_calls,
    )


def _prune_agentic_tools(run_ctx) -> list[str]:
    """Restrict the prover to the smallest MCP surface that still helps proofs."""
    before = set(run_ctx._callable_tools)
    run_ctx._callable_tools = {
        name: tool
        for name, tool in run_ctx._callable_tools.items()
        if name in AGENTIC_ALLOWED_TOOLS
    }
    return sorted(before - set(run_ctx._callable_tools))


@dataclass
class TraceRecorder:
    """Capture rich tool-call traces and tactic-attempt outcomes."""

    entries: list[dict[str, Any]] = field(default_factory=list)
    sequence_id: int = 0
    latest_kernel_errors: list[str] = field(default_factory=list)
    latest_kernel_warnings: list[str] = field(default_factory=list)
    pending_tactic_log_index: int | None = None

    def append_message_output(self, *, request_index: int, content: Any) -> None:
        text = _truncate_text(content, limit=1000)
        if not text:
            return
        self.entries.append(
            {
                "sequence_id": self._next_sequence_id(),
                "request_index": request_index,
                "type": "message.output",
                "content": text,
            }
        )

    def append_tool_call(
        self,
        *,
        request_index: int,
        tool_call_id: str,
        tool_name: str,
        tool_kind: str,
        arguments: Any,
        result_text: Any,
        status: str,
        blocked: bool = False,
        diagnostic_payload: dict[str, Any] | None = None,
    ) -> None:
        entry = {
            "sequence_id": self._next_sequence_id(),
            "request_index": request_index,
            "type": "tool_call",
            "tool_call_id": tool_call_id,
            "tool_name": tool_name,
            "tool_kind": tool_kind,
            "arguments": _normalize_tool_arguments(arguments),
            "result_text": _truncate_text(result_text, limit=1500),
            "status": status,
            "blocked": blocked,
            "kernel_errors": [],
            "kernel_warnings": [],
        }
        if diagnostic_payload is not None:
            entry["diagnostic_payload"] = diagnostic_payload
            entry["kernel_errors"] = list(diagnostic_payload.get("errors", []))
            entry["kernel_warnings"] = list(diagnostic_payload.get("warnings", []))
        self.entries.append(entry)

    def note_tactic_attempt(self, tactic_call_log: list[dict[str, Any]], tactic: str) -> None:
        if self.pending_tactic_log_index is not None:
            previous = tactic_call_log[self.pending_tactic_log_index]
            if previous.get("successful") is None:
                previous["successful"] = False
                previous["resolution"] = "superseded_before_diagnostics"

        tactic_call_log.append(
            {
                "attempt_index": len(tactic_call_log) + 1,
                "tactic": tactic,
                "tactic_preview": _preview_tactic(tactic),
                "triggering_errors": list(self.latest_kernel_errors),
                "triggering_warnings": list(self.latest_kernel_warnings),
                "successful": None,
                "resolution": "pending_diagnostics",
            }
        )
        self.pending_tactic_log_index = len(tactic_call_log) - 1

    def resolve_from_diagnostics(
        self,
        tactic_call_log: list[dict[str, Any]],
        *,
        errors: list[str],
        warnings: list[str],
    ) -> None:
        self.latest_kernel_errors = list(errors)
        self.latest_kernel_warnings = list(warnings)

        if self.pending_tactic_log_index is None:
            return

        attempt = tactic_call_log[self.pending_tactic_log_index]
        attempt["post_diagnostic_errors"] = list(errors)
        attempt["post_diagnostic_warnings"] = list(warnings)
        attempt["successful"] = not errors
        attempt["resolution"] = "diagnostics_clean" if not errors else "diagnostics_error"
        self.pending_tactic_log_index = None

    def finalize_pending_attempt(self, tactic_call_log: list[dict[str, Any]]) -> None:
        if self.pending_tactic_log_index is None:
            return
        attempt = tactic_call_log[self.pending_tactic_log_index]
        if attempt.get("successful") is None:
            attempt["successful"] = False
            attempt["resolution"] = "unresolved_when_run_ended"
        self.pending_tactic_log_index = None

    def _next_sequence_id(self) -> int:
        self.sequence_id += 1
        return self.sequence_id


def _preview_tactic(tactic: str, limit: int = 120) -> str:
    """Collapse a tactic block to a short one-line preview for tool responses."""
    collapsed = " ".join(line.strip() for line in tactic.splitlines() if line.strip())
    if not collapsed:
        return "<empty tactic>"
    if len(collapsed) <= limit:
        return collapsed
    return f"{collapsed[:limit]}..."


def _empty_tool_result_message(tool_name: str) -> str:
    """Return a non-empty fallback message for tools that yielded no text."""
    return (
        f"WARNING: Tool `{tool_name}` returned an empty result. "
        f"Use lean_diagnostic_messages on the working file before continuing."
    )


def _unavailable_tool_message(tool_name: str) -> str:
    """Return a warning result when the model asks for an unregistered tool."""
    return (
        f"ERROR: Tool `{tool_name}` is not registered in this run context. "
        "Use one of the listed tools and call lean_diagnostic_messages "
        "to inspect the current proof state."
    )


def _truncate_text(value: Any, limit: int = 500) -> str:
    """Convert arbitrary tool payloads into bounded log text."""
    text = str(value).strip()
    if len(text) <= limit:
        return text
    return f"{text[:limit]}..."


def _normalize_tool_arguments(arguments: Any) -> dict[str, Any] | list[Any] | str:
    """Normalize tool-call arguments for JSONL logging."""
    if isinstance(arguments, (dict, list)):
        return arguments
    if isinstance(arguments, str):
        try:
            parsed = json.loads(arguments)
        except json.JSONDecodeError:
            return arguments
        if isinstance(parsed, (dict, list)):
            return parsed
        return arguments
    return str(arguments)


def _tool_signature(tool_name: str, arguments: Any) -> tuple[str, str]:
    """Normalize a read-only tool call so duplicate queries can be blocked."""
    normalized = _normalize_tool_arguments(arguments)
    if isinstance(normalized, dict):
        rendered_arguments = json.dumps(normalized, sort_keys=True, ensure_ascii=True)
    elif isinstance(normalized, list):
        rendered_arguments = json.dumps(normalized, ensure_ascii=True)
    else:
        rendered_arguments = str(normalized)
    return tool_name, rendered_arguments


def _has_failed_tactic_attempt(tactic_call_log: list[dict[str, Any]]) -> bool:
    """Allow search tools only after at least one verified failed tactic attempt."""
    return any(entry.get("successful") is False for entry in tactic_call_log)


def _should_try_local_fast_path(theorem_with_sorry: str) -> bool:
    """Only spend local verification cycles on compact, non-advanced statements."""
    stripped = theorem_with_sorry.strip()
    if stripped.count("sorry") != 1:
        return False
    if len(stripped) > LOCAL_FAST_PATH_MAX_CHARS:
        return False
    if len(stripped.splitlines()) > LOCAL_FAST_PATH_MAX_LINES:
        return False
    return not any(marker in stripped for marker in LOCAL_FAST_PATH_BLOCKLIST)


def _top_level_parenthesized_binders(theorem_surface: str) -> list[str]:
    binders: list[str] = []
    depth = 0
    start: int | None = None
    for index, char in enumerate(theorem_surface):
        if char == "(":
            if depth == 0:
                start = index + 1
            depth += 1
        elif char == ")" and depth > 0:
            depth -= 1
            if depth == 0 and start is not None:
                binders.append(theorem_surface[start:index].strip())
                start = None
    return binders


def _exact_hypothesis_names(theorem_surface: str) -> list[str]:
    if ":" not in theorem_surface:
        return []
    conclusion = " ".join(theorem_surface.rsplit(":", 1)[-1].split())
    if not conclusion:
        return []

    names: list[str] = []
    for binder in _top_level_parenthesized_binders(theorem_surface):
        if ":" not in binder:
            continue
        raw_names, raw_type = binder.split(":", 1)
        hypothesis_type = " ".join(raw_type.split())
        if hypothesis_type != conclusion:
            continue
        for candidate in raw_names.split():
            if TACTIC_HYPOTHESIS_NAME_RE.match(candidate):
                names.append(candidate)
    return names


def _local_fast_path_tactics(theorem_with_sorry: str) -> list[str]:
    """Choose a short deterministic tactic list from theorem surface features."""
    theorem_surface = theorem_with_sorry.split(":= by", 1)[0]
    tactics: list[str] = []
    exact_hypotheses = _exact_hypothesis_names(theorem_surface)
    for hypothesis_name in exact_hypotheses:
        tactics.append(f"exact {hypothesis_name}")
        tactics.append(f"simpa using {hypothesis_name}")
    if exact_hypotheses:
        tactics.append("assumption")
    looks_numeric_arithmetic = bool(NUMERIC_LITERAL_RE.search(theorem_surface)) and any(
        token in theorem_surface for token in ("=", "≤", "<", "≥", ">", "+", "-", "*", "/")
    )
    if looks_numeric_arithmetic:
        tactics.extend(LOCAL_FAST_PATH_DISCRETE_TACTICS)
        tactics.extend(("ring_nf", "ring"))
    elif any(token in theorem_surface for token in ("ℕ", "Nat", "ℤ", "Int", "Even", "Odd")):
        tactics.extend(LOCAL_FAST_PATH_DISCRETE_TACTICS)
    if any(
        token in theorem_surface
        for token in ("ℝ", "Real", "ℚ", "Rat", "≤", "<", "≥", ">", "+", "-", "*", "=")
    ):
        tactics.extend(LOCAL_FAST_PATH_ALGEBRA_TACTICS)
    if "/" in theorem_surface or "⁻¹" in theorem_surface:
        tactics.extend(LOCAL_FAST_PATH_FIELD_TACTICS)
    tactics.extend(LOCAL_FAST_PATH_CORE_TACTICS)
    return list(dict.fromkeys(tactics))


def _fast_path_attempt_record(
    *,
    attempt_index: int,
    tactic: str,
    verification: dict[str, Any],
) -> dict[str, Any]:
    """Record a local fast-path tactic attempt using the standard tactic-call shape."""
    return {
        "attempt_index": attempt_index,
        "tactic": tactic,
        "tactic_preview": _preview_tactic(tactic),
        "triggering_errors": [],
        "post_diagnostic_errors": list(verification.get("errors", [])),
        "post_diagnostic_warnings": list(verification.get("warnings", [])),
        "successful": verification.get("success", False),
        "resolution": (
            "local_fast_path_success"
            if verification.get("success", False)
            else "local_fast_path_failed"
        ),
        "local_fast_path": True,
    }


def _try_local_tactic_fast_path(
    theorem_with_sorry: str,
    controller: ProofFileController,
    *,
    on_log,
    start_time: float,
) -> dict[str, Any] | None:
    """Try a tiny deterministic tactic sweep before paying for Leanstral+MCP."""
    if not _should_try_local_fast_path(theorem_with_sorry):
        return None

    candidate_tactics = _local_fast_path_tactics(theorem_with_sorry)
    bounded_candidates = candidate_tactics[:LOCAL_FAST_PATH_MAX_ATTEMPTS]
    _log(
        on_log,
        "agentic_fast_path",
        (
            f"Trying up to {len(bounded_candidates)} local tactic candidates "
            f"before Leanstral ({len(candidate_tactics)} available)..."
        ),
        status="running",
    )

    tactic_call_log: list[dict[str, Any]] = []
    for attempt_index, tactic in enumerate(bounded_candidates, start=1):
        controller.replace_tactic_block(tactic)
        try:
            verification = verify(controller.current_lean_code, check_axioms=False)
        except Exception as exc:  # pragma: no cover - defensive fallback around local Lean
            verification = {
                "success": False,
                "errors": [str(exc)],
                "warnings": [],
                "output_lean": None,
                "axiom_info": None,
            }

        tactic_call_log.append(
            _fast_path_attempt_record(
                attempt_index=attempt_index,
                tactic=tactic,
                verification=verification,
            )
        )

        if verification.get("success"):
            elapsed = time.time() - start_time
            _log(
                on_log,
                "agentic_fast_path",
                f"Local fast path solved the theorem with `{_preview_tactic(tactic)}`",
                status="done",
                elapsed_ms=elapsed * 1000,
            )
            return {
                "success": True,
                "strategy": "Local deterministic tactic fast path",
                "proof_tactics": controller.current_tactic_block,
                "full_lean_code": controller.current_lean_code,
                "errors": verification.get("errors", []),
                "warnings": verification.get("warnings", []),
                "tool_trace": [],
                "tactic_calls": tactic_call_log,
                "trace_schema_version": TRACE_SCHEMA_VERSION,
                "steps_used": 0,
                "mcp_enabled": False,
                "agent_summary": (
                    "Local fast path solved the theorem without any remote "
                    "tool calls or Leanstral API round-trips."
                ),
                "stop_reason": STOP_PROOF_COMPLETE,
                "output_lean": verification.get("output_lean"),
                "axiom_info": verification.get("axiom_info"),
                "elapsed_seconds": elapsed,
                "partial": False,
            }

    controller.restore_last_good_checkpoint()
    fast_path_elapsed_ms = (time.time() - start_time) * 1000
    _log(
        on_log,
        "agentic_fast_path",
        "Local fast path exhausted its tactic shortlist; escalating to Leanstral.",
        status="done",
        elapsed_ms=fast_path_elapsed_ms,
    )
    return None


def _parse_diagnostic_payload(result_text: Any) -> dict[str, Any] | None:
    """Extract Lean kernel diagnostics from an MCP tool result."""
    payload = extract_json_payload(result_text)
    if not isinstance(payload, dict):
        return None
    return normalize_structured_diagnostics(payload)


def _status_code_from_exception(exc: Exception) -> int | None:
    """Extract an HTTP status code from Mistral SDK errors or fallback text."""
    status_code = getattr(exc, "status_code", None)
    if isinstance(status_code, int):
        return status_code

    match = re.search(r"\bStatus (\d{3})\b", str(exc))
    if match:
        return int(match.group(1))
    return None


def _is_retryable_run_error(exc: Exception) -> bool:
    """Return True for transient Mistral API failures that deserve backoff."""
    return _status_code_from_exception(exc) in RETRYABLE_STATUS_CODES


def _is_code_3001_error(exc: Exception) -> bool:
    """Detect the malformed empty-input/tool-confirmation Conversations error."""
    text = str(exc)
    return 'code":3001' in text or "Either inputs or tool_confirmations must be provided." in text


def _is_cancel_scope_error(exc: BaseException) -> bool:
    """Return True if the exception is an anyio cancel-scope task-mismatch error.

    This fires when asyncio's task cancellation propagates into anyio's cancel scopes
    (Python 3.12+), typically because the Mistral SDK's timeout_ms fires while the
    Lean LSP is still processing a long-running request (e.g. preamble compilation).
    The exception may be wrapped in an ExceptionGroup by anyio's task group.
    """
    if "cancel scope" in str(exc).lower() and "different task" in str(exc).lower():
        return True
    # Unwrap anyio/Python 3.11+ ExceptionGroup sub-exceptions
    if hasattr(exc, "exceptions"):
        return any(_is_cancel_scope_error(e) for e in exc.exceptions)
    return False


def _normalized_interruption_warning(kind: str) -> str:
    """Return a stable user-facing warning for partial-result interruptions."""
    if kind == "cancel_scope":
        return PARTIAL_TIMEOUT_CLEANUP_WARNING
    if kind == "timeout":
        return f"run_async timed out after {TIMEOUT_MS}ms"
    raise ValueError(f"Unknown interruption warning kind: {kind}")


async def _run_conversation_with_backoff(
    client,
    run_ctx,
    *,
    inputs: str,
    instructions: str,
    completion_args,
    timeout_ms: int,
    on_log: callable | None = None,
):
    """
    Run the Conversations API loop with exponential backoff on transient 429/503 failures.

    Performs one initial attempt plus four retries with delays 2s, 4s, 8s, and 16s
    around each Conversations start/append request.
    """
    from mistralai.client.beta import Beta
    from mistralai.extra.run.context import _validate_run
    from mistralai.extra.run.tools import get_function_calls

    async def request_with_backoff(request_factory, request_label: str):
        total_attempts = len(BACKOFF_DELAYS_SECONDS) + 1
        last_exc: Exception | None = None

        for attempt in range(1, total_attempts + 1):
            try:
                return await request_factory()
            except Exception as exc:
                last_exc = exc
                if not _is_retryable_run_error(exc) or attempt == total_attempts:
                    raise

                delay = BACKOFF_DELAYS_SECONDS[attempt - 1]
                status_code = _status_code_from_exception(exc)
                _log(
                    on_log,
                    "agentic_backoff",
                    (
                        f"Retryable Mistral API error ({status_code}) during "
                        f"conversation {request_label} "
                        f"attempt {attempt}/{total_attempts}; retrying in {delay}s"
                    ),
                    data=str(exc),
                    status="running",
                )
                await asyncio.sleep(delay)

        assert last_exc is not None
        raise last_exc

    req, run_result, input_entries = await _validate_run(
        beta_client=Beta(client.sdk_configuration),
        run_ctx=run_ctx,
        inputs=inputs,
        instructions=instructions,
        completion_args=completion_args,
    )

    while True:
        if run_ctx.conversation_id is None:
            res = await request_with_backoff(
                lambda: client.beta.conversations.start_async(
                    inputs=input_entries,
                    timeout_ms=timeout_ms,
                    **req,
                ),
                "start",
            )
            run_result.conversation_id = res.conversation_id
            run_ctx.conversation_id = res.conversation_id
        else:
            res = await request_with_backoff(
                lambda: client.beta.conversations.append_async(
                    conversation_id=run_ctx.conversation_id,
                    inputs=input_entries,
                    timeout_ms=timeout_ms,
                ),
                "append",
            )

        run_ctx.request_count += 1
        run_result.output_entries.extend(res.outputs)
        function_calls = get_function_calls(res.outputs)
        if not function_calls:
            break

        function_results = await run_ctx.execute_function_calls(function_calls)
        if not function_results:
            raise RuntimeError(
                "Empty tool-result cycle detected; no function results were produced."
            )

        run_result.output_entries.extend(function_results)
        input_entries = cast(list, function_results)

    return run_result


def _sanitize_tool_result_text(tool_name: str, result_text: Any) -> str:
    """Normalize a tool result to a non-empty string payload for Mistral."""
    if isinstance(result_text, str) and result_text.strip():
        return result_text
    return _empty_tool_result_message(tool_name)


def _build_interrupted_run_result(
    *,
    controller: ProofFileController,
    model_text: str,
    tool_trace_entries: list[dict[str, Any]],
    tactic_call_log: list[dict[str, Any]],
    steps_used: int,
    start_time: float,
    interruption_message: str,
    stop_reason: str,
    agent_summary: str,
    partial: bool,
) -> dict[str, Any]:
    """Build a graceful partial result after a timeout or external API interruption."""
    current_tactics = controller.current_tactic_block
    current_code = controller.current_lean_code
    partial_verification = None

    if current_tactics != "sorry":
        try:
            partial_verification = verify(current_code)
        except Exception:
            partial_verification = None

    elapsed = time.time() - start_time
    success = bool(partial_verification and partial_verification["success"])
    final_stop_reason = STOP_PROOF_COMPLETE if success else stop_reason

    if partial_verification:
        errors = list(partial_verification.get("errors", []))
        warnings = list(partial_verification.get("warnings", []))
        if interruption_message not in errors and interruption_message not in warnings:
            warnings.append(interruption_message)
        output_lean = partial_verification.get("output_lean")
    else:
        errors = [interruption_message]
        warnings = []
        output_lean = None

    return {
        "success": success,
        "strategy": model_text,
        "proof_tactics": current_tactics,
        "full_lean_code": current_code,
        "errors": errors,
        "warnings": warnings,
        "tool_trace": tool_trace_entries,
        "tactic_calls": tactic_call_log,
        "trace_schema_version": TRACE_SCHEMA_VERSION,
        "steps_used": steps_used,
        "mcp_enabled": True,
        "agent_summary": agent_summary,
        "stop_reason": final_stop_reason,
        "output_lean": output_lean,
        "elapsed_seconds": elapsed,
        "partial": partial,
    }


# ---------------------------------------------------------------------------
# System prompt for Leanstral
# ---------------------------------------------------------------------------

AGENTIC_INSTRUCTIONS_TEMPLATE = """\
You are Leanstral, an expert Lean 4 prover. You have access to lean-lsp-mcp
tools and a custom apply_tactic tool for writing proofs.

You are given a Lean 4 theorem with `sorry` as a placeholder proof.
Your task is to find a complete tactic proof that Lean accepts.

## Budget

- You have a hard budget of {max_total_tool_calls} total tool calls.
- You may use search/suggestion tools at most {max_search_tool_calls} times.
- More than {max_consecutive_read_only_calls} consecutive read-only tool calls ends the run.
- Prefer the cheap loop: lean_goal → apply_tactic → lean_diagnostic_messages.

## Available tools

- apply_tactic
- lean_goal
- lean_diagnostic_messages
- lean_multi_attempt
- lean_code_actions
- lean_state_search
- lean_hammer_premise

No generic build/import/search tools are available in this run.

## Workflow

1. Use lean_goal to inspect the initial goal at line {goal_line} of {file_path}.
2. Call apply_tactic with a tactic block to replace sorry.
3. Use lean_diagnostic_messages on {file_path} to check for errors.
4. If there are errors, call apply_tactic again with a corrected tactic.
5. If there are NO errors and NO "sorry" warnings, the proof is complete — STOP.

## Tactic guidance

- Simple arithmetic: norm_num or decide
- Field arithmetic (+, -, *, /, ⁻¹): field_simp [...] then ring
- Equalities from hypotheses: exact h or linarith
- Existential goals: use <witness> then prove

## Screening multiple tactics

When you are uncertain which tactic will work, use lean_multi_attempt
before apply_tactic. Pass the file path, the tactic line number, and a
list of 3-5 candidate tactic snippets. The tool returns which candidates
compiled successfully. Then call apply_tactic with the best candidate.

Use lean_multi_attempt when:
- You are choosing between field_simp, ring, simp, or norm_num
- The goal contains Real.rpow and you want to screen rpow lemmas
- A previous apply_tactic call failed and you need alternatives
- The goal structure is unfamiliar

Do NOT use lean_multi_attempt for trivial goals where you are confident
in the tactic (e.g., exact h, norm_num on arithmetic).

## Searching for Mathlib lemmas

When you are stuck, prefer the goal-local search tools:
- lean_state_search for lemmas that can close the current goal
- lean_hammer_premise for premise suggestions

Use search only after at least one tactic attempt has failed.
Do not spend the search budget before writing a plausible proof attempt.

## Discovering tactics with code actions

When you need the optimal tactic or want to resolve a "Try this:" suggestion:
1. Apply a discovery tactic via apply_tactic: simp?, exact?, or apply?
2. Call lean_code_actions on {file_path} at that line number
3. Read the resolved tactic from the returned edit suggestion
4. Call apply_tactic with the resolved tactic

Use lean_code_actions when:
- You've tried 2+ tactics that failed
- lean_diagnostic_messages shows "Try this:" suggestions
- You want to replace simp with its minimal simp only [...] form

## Rules

- Do NOT use sorry.
- Keep tactic blocks concise.
- If you cannot find a proof after a few attempts, say so and stop.
- STOP as soon as lean_diagnostic_messages shows no errors and no sorry warnings.
"""


def _build_instructions(
    file_path: str,
    goal_line: int,
    *,
    max_total_tool_calls: int,
    max_search_tool_calls: int,
    max_consecutive_read_only_calls: int,
) -> str:
    """Inject runtime paths into the agent prompt without using format()."""
    return (
        AGENTIC_INSTRUCTIONS_TEMPLATE.replace("{file_path}", file_path)
        .replace("{goal_line}", str(goal_line))
        .replace("{max_total_tool_calls}", str(max_total_tool_calls))
        .replace("{max_search_tool_calls}", str(max_search_tool_calls))
        .replace(
            "{max_consecutive_read_only_calls}",
            str(max_consecutive_read_only_calls),
        )
    )


# ---------------------------------------------------------------------------
# Tool function factory
# ---------------------------------------------------------------------------


def _make_apply_tactic(controller: ProofFileController, trace_recorder: TraceRecorder):
    """
    Create the apply_tactic closure bound to a ProofFileController.

    The function writes the tactic to the working file and returns immediately.
    It does NOT query MCP — Leanstral should use its native lean-lsp-mcp tools
    (lean_diagnostic_messages, lean_goal) via the persistent RunContext session
    to check the result. This avoids spawning a new lean-lsp-mcp subprocess
    per tactic application.

    Returns (apply_tactic_fn, tactic_call_log).
    """
    tactic_call_log: list[dict[str, Any]] = []

    def apply_tactic(tactic: str) -> str:
        """Replace the proof tactic block in the working Lean file.

        Writes the tactic to the file. After calling this, use
        lean_diagnostic_messages to check for errors and lean_goal
        to inspect remaining goals.

        Args:
            tactic: A Lean 4 tactic or tactic block. Examples: "ring",
                    "field_simp [ne_of_gt hc]", "norm_num", "exact hspend"
        """
        trace_recorder.note_tactic_attempt(tactic_call_log, tactic)

        try:
            controller.replace_tactic_block(tactic)
        except ValueError as exc:
            return f"ERROR: Invalid tactic block — {exc}"

        tactic_preview = _preview_tactic(tactic)
        response = (
            f"OK: Tactic written to {controller.mcp_file_path}. "
            f"Preview: {tactic_preview}. "
            "Next step: use lean_diagnostic_messages on "
            f"{controller.mcp_file_path} to check for errors before applying "
            "more tactics."
        )
        return response if response.strip() else _empty_tool_result_message("apply_tactic")

    return apply_tactic, tactic_call_log


def _install_guarded_execute_function_calls(
    run_ctx,
    tracker: AgenticToolTracker,
    trace_recorder: TraceRecorder,
    tactic_call_log: list[dict[str, Any]],
):
    """
    Wrap RunContext.execute_function_calls so tool execution stays well-formed.

    This guard does three things:
    1. Prevents unknown tool calls from collapsing into `inputs=[]` on the next append.
    2. Enforces the apply_tactic circuit breaker after five unchecked writes.
    3. Guarantees that every function result fed back to Mistral is non-empty text.
    """
    from mistralai.client.models.functionresultentry import FunctionResultEntry
    from mistralai.extra.run.tools import create_function_result

    async def guarded_execute_function_calls(function_calls):
        results: list[FunctionResultEntry] = []

        for function_call in function_calls:
            tool_name = function_call.name
            run_tool = run_ctx._callable_tools.get(tool_name)
            tool_kind = "local" if tool_name == "apply_tactic" else "mcp"
            request_index = getattr(run_ctx, "request_count", 0) + 1
            arguments = getattr(function_call, "arguments", {})

            if tracker.has_exhausted_total_budget():
                tracker.note_budget_stop()
                raise ToolBudgetExceededError(
                    "Tool budget exhausted. Stop searching and return the best current proof state."
                )

            if tool_name != "apply_tactic" and tracker.has_read_only_loop():
                tracker.note_budget_stop()
                raise ToolBudgetExceededError(
                    "Read-only tool loop detected. "
                    "Stop querying tools and return the best current proof state."
                )

            if run_tool is None:
                unavailable_result = _unavailable_tool_message(tool_name)
                tracker.note_blocked_tool(tool_name)
                results.append(
                    FunctionResultEntry(
                        tool_call_id=function_call.tool_call_id,
                        result=unavailable_result,
                    )
                )
                trace_recorder.append_tool_call(
                    request_index=request_index,
                    tool_call_id=function_call.tool_call_id,
                    tool_name=tool_name,
                    tool_kind=tool_kind,
                    arguments=arguments,
                    result_text=unavailable_result,
                    status="unavailable",
                )
                continue

            if tracker.is_duplicate_read_only_call(tool_name, arguments):
                tracker.note_blocked_tool(tool_name, duplicate_read_only=True)
                results.append(
                    FunctionResultEntry(
                        tool_call_id=function_call.tool_call_id,
                        result=DUPLICATE_READ_ONLY_WARNING,
                    )
                )
                trace_recorder.append_tool_call(
                    request_index=request_index,
                    tool_call_id=function_call.tool_call_id,
                    tool_name=tool_name,
                    tool_kind=tool_kind,
                    arguments=arguments,
                    result_text=DUPLICATE_READ_ONLY_WARNING,
                    status="blocked",
                    blocked=True,
                )
                continue

            if tool_name in AGENTIC_SEARCH_TOOLS and not _has_failed_tactic_attempt(
                tactic_call_log
            ):
                tracker.note_blocked_tool(tool_name)
                results.append(
                    FunctionResultEntry(
                        tool_call_id=function_call.tool_call_id,
                        result=SEARCH_PRECONDITION_WARNING,
                    )
                )
                trace_recorder.append_tool_call(
                    request_index=request_index,
                    tool_call_id=function_call.tool_call_id,
                    tool_name=tool_name,
                    tool_kind=tool_kind,
                    arguments=arguments,
                    result_text=SEARCH_PRECONDITION_WARNING,
                    status="blocked",
                    blocked=True,
                )
                continue

            if tool_name in AGENTIC_SEARCH_TOOLS and tracker.has_exhausted_search_budget():
                tracker.note_blocked_tool(tool_name, search_budget=True)
                results.append(
                    FunctionResultEntry(
                        tool_call_id=function_call.tool_call_id,
                        result=SEARCH_BUDGET_WARNING,
                    )
                )
                trace_recorder.append_tool_call(
                    request_index=request_index,
                    tool_call_id=function_call.tool_call_id,
                    tool_name=tool_name,
                    tool_kind=tool_kind,
                    arguments=arguments,
                    result_text=SEARCH_BUDGET_WARNING,
                    status="blocked",
                    blocked=True,
                )
                continue

            if tool_name == "apply_tactic" and tracker.should_block_apply():
                tracker.note_circuit_breaker()
                tracker.note_blocked_tool(tool_name)
                blocked_result = CIRCUIT_BREAKER_WARNING
                results.append(
                    FunctionResultEntry(
                        tool_call_id=function_call.tool_call_id,
                        result=blocked_result,
                    )
                )
                trace_recorder.append_tool_call(
                    request_index=request_index,
                    tool_call_id=function_call.tool_call_id,
                    tool_name=tool_name,
                    tool_kind=tool_kind,
                    arguments=arguments,
                    result_text=blocked_result,
                    status="blocked",
                    blocked=True,
                )
                continue

            status = "ok"
            try:
                function_result = await create_function_result(
                    function_call=function_call,
                    run_tool=run_tool,
                    continue_on_fn_error=True,
                )
            except Exception as exc:  # pragma: no cover - defensive fallback over SDK helper
                status = "error"
                function_result = FunctionResultEntry(
                    tool_call_id=function_call.tool_call_id,
                    result=f"ERROR while executing {tool_name}: {exc}",
                )

            function_result.result = _sanitize_tool_result_text(
                tool_name,
                getattr(function_result, "result", ""),
            )
            results.append(function_result)

            diagnostic_payload = None
            if tool_name == "lean_diagnostic_messages":
                diagnostic_payload = _parse_diagnostic_payload(function_result.result)
                if diagnostic_payload is not None:
                    trace_recorder.resolve_from_diagnostics(
                        tactic_call_log,
                        errors=diagnostic_payload["errors"],
                        warnings=diagnostic_payload["warnings"],
                    )

            trace_recorder.append_tool_call(
                request_index=request_index,
                tool_call_id=function_call.tool_call_id,
                tool_name=tool_name,
                tool_kind=tool_kind,
                arguments=arguments,
                result_text=function_result.result,
                status=status,
                diagnostic_payload=diagnostic_payload,
            )

            if tool_name == "lean_diagnostic_messages":
                tracker.note_diagnostic_check(arguments)
            elif tool_name == "apply_tactic":
                tracker.note_apply_tactic_executed()
            else:
                tracker.note_read_only_tool(tool_name, arguments)

        if not results:
            for function_call in function_calls:
                results.append(
                    FunctionResultEntry(
                        tool_call_id=function_call.tool_call_id,
                        result=(
                            "WARNING: No executable tool results were produced. "
                            "Use lean_diagnostic_messages to inspect the "
                            "current proof state before continuing."
                        ),
                    )
                )

        return results

    run_ctx.execute_function_calls = guarded_execute_function_calls


# ---------------------------------------------------------------------------
# Core async implementation
# ---------------------------------------------------------------------------


async def _prove_theorem_agentic_async(
    theorem_with_sorry: str,
    on_log: callable | None = None,
    max_steps: int = DEFAULT_MAX_STEPS,
) -> dict[str, Any]:
    """
    Run the Leanstral+MCP agentic proving loop via Mistral's run_async.

    1. Initialize working file via ProofFileController
    2. Register custom tool functions + MCP tools via RunContext
    3. Let Leanstral drive the loop via run_async
    4. Final verification via the local Lean compiler
    """
    from mistralai.client import Mistral
    from mistralai.client.models.completionargs import CompletionArgs

    controller = ProofFileController()
    start_time = time.time()
    try:
        # --- Step 1: Initialize working file ---
        _log(on_log, "agentic_init", "Initializing working proof file...", status="running")
        t_agentic_init = time.time()
        controller.initialize(theorem_with_sorry)
        _log(
            on_log,
            "agentic_init",
            f"Working file: {controller.mcp_file_path}",
            data=controller.current_lean_code,
            status="done",
            elapsed_ms=(time.time() - t_agentic_init) * 1000,
        )

        fast_path_result = _try_local_tactic_fast_path(
            theorem_with_sorry,
            controller,
            on_log=on_log,
            start_time=start_time,
        )
        if fast_path_result is not None:
            return fast_path_result

        # --- Step 2: Set up Mistral RunContext with tools ---
        _log(on_log, "agentic_setup", "Setting up Leanstral + MCP tools...", status="running")
        t_agentic_setup = time.time()

        trace_recorder = TraceRecorder()
        apply_tactic_fn, tactic_call_log = _make_apply_tactic(controller, trace_recorder)
        (
            max_total_tool_calls,
            max_search_tool_calls,
            max_consecutive_read_only_calls,
        ) = _budget_limits(max_steps)
        tool_tracker = AgenticToolTracker(
            max_total_tool_calls=max_total_tool_calls,
            max_search_tool_calls=max_search_tool_calls,
            max_consecutive_read_only_calls=max_consecutive_read_only_calls,
        )
        client = Mistral(api_key=os.environ["MISTRAL_API_KEY"])

        instructions = _build_instructions(
            file_path=controller.mcp_file_path,
            goal_line=controller.goal_query_line,
            max_total_tool_calls=max_total_tool_calls,
            max_search_tool_calls=max_search_tool_calls,
            max_consecutive_read_only_calls=max_consecutive_read_only_calls,
        )

        user_prompt = (
            f"Prove this Lean 4 theorem:\n\n"
            f"```lean\n{theorem_with_sorry.strip()}\n```\n\n"
            f"The theorem is loaded in {controller.mcp_file_path}. "
            f"Use lean_goal at line {controller.goal_query_line} to see the initial goal, "
            "then prefer the cheap loop of apply_tactic followed by "
            "lean_diagnostic_messages. Use search/suggestion tools only as a fallback."
        )

        # --- Step 3: Run the agentic loop ---
        _log(on_log, "agentic_run", "Leanstral proving loop started...", status="running")
        t_agentic_run = time.time()
        stop_reason = STOP_PROOF_INCOMPLETE
        model_text = ""
        tool_trace_entries: list[dict[str, Any]] = trace_recorder.entries

        steps_used = 0
        run_ctx = None

        try:
            async with open_mistral_run_context(model=LEANSTRAL_MODEL) as run_ctx:
                run_ctx.agentic_tool_tracker = tool_tracker
                run_ctx.register_func(apply_tactic_fn)
                removed_tools = _prune_agentic_tools(run_ctx)
                _install_guarded_execute_function_calls(
                    run_ctx,
                    tool_tracker,
                    trace_recorder,
                    tactic_call_log,
                )

                _log(
                    on_log,
                    "agentic_setup",
                    (
                        f"Tools registered: {len(run_ctx.get_tools())} total "
                        f"(pruned {len(removed_tools)} low-ROI tools)"
                    ),
                    data=", ".join(removed_tools[:12]) if removed_tools else None,
                    status="done",
                    elapsed_ms=(time.time() - t_agentic_setup) * 1000,
                )

                result = await _run_conversation_with_backoff(
                    client,
                    run_ctx,
                    inputs=user_prompt,
                    instructions=instructions,
                    completion_args=CompletionArgs(
                        temperature=1.0,
                        max_tokens=32000,
                    ),
                    timeout_ms=TIMEOUT_MS,
                    on_log=on_log,
                )

                # Extract results
                steps_used = run_ctx.request_count

                for entry in result.output_entries:
                    if getattr(entry, "type", "") == "message.output":
                        trace_recorder.append_message_output(
                            request_index=getattr(run_ctx, "request_count", steps_used),
                            content=getattr(entry, "content", ""),
                        )

                try:
                    model_text = result.output_as_text
                except (ValueError, AttributeError):
                    model_text = ""

        except asyncio.TimeoutError:
            steps_used = getattr(run_ctx, "request_count", steps_used)
            error_message = _normalized_interruption_warning("timeout")
            trace_recorder.finalize_pending_attempt(tactic_call_log)
            return _build_interrupted_run_result(
                controller=controller,
                model_text=model_text,
                tool_trace_entries=tool_trace_entries,
                tactic_call_log=tactic_call_log,
                steps_used=steps_used,
                start_time=start_time,
                interruption_message=error_message,
                stop_reason=STOP_TIMEOUT,
                agent_summary=(
                    "Leanstral agentic prover timed out before finishing the proving loop. "
                    "Returning the latest proof state for inspection."
                ),
                partial=True,
            )
        except Exception as exc:
            _log(on_log, "agentic_run", f"run_async error: {exc}", status="error")
            steps_used = getattr(run_ctx, "request_count", steps_used)

            if isinstance(exc, ToolBudgetExceededError):
                trace_recorder.finalize_pending_attempt(tactic_call_log)
                return _build_interrupted_run_result(
                    controller=controller,
                    model_text=model_text,
                    tool_trace_entries=tool_trace_entries,
                    tactic_call_log=tactic_call_log,
                    steps_used=steps_used,
                    start_time=start_time,
                    interruption_message=str(exc),
                    stop_reason=STOP_PROOF_INCOMPLETE,
                    agent_summary=(
                        "Leanstral agentic prover halted early because the "
                        "tool budget detected a high-waste loop and returned "
                        "the latest proof state instead."
                    ),
                    partial=True,
                )

            if _is_retryable_run_error(exc):
                interruption_message = (
                    "Agentic run halted after exhausting retry backoff for a "
                    "transient Mistral API error."
                )
                trace_recorder.finalize_pending_attempt(tactic_call_log)
                return _build_interrupted_run_result(
                    controller=controller,
                    model_text=model_text,
                    tool_trace_entries=tool_trace_entries,
                    tactic_call_log=tactic_call_log,
                    steps_used=steps_used,
                    start_time=start_time,
                    interruption_message=interruption_message,
                    stop_reason=STOP_PROOF_INCOMPLETE,
                    agent_summary=(
                        "Leanstral agentic prover exhausted exponential backoff retries "
                        "for a transient API error and returned the latest proof state."
                    ),
                    partial=True,
                )

            if _is_code_3001_error(exc):
                interruption_message = (
                    "Agentic run halted after an empty tool-result cycle. "
                    "The current proof state was preserved so Leanstral can "
                    "resume from diagnostics."
                )
                trace_recorder.finalize_pending_attempt(tactic_call_log)
                return _build_interrupted_run_result(
                    controller=controller,
                    model_text=model_text,
                    tool_trace_entries=tool_trace_entries,
                    tactic_call_log=tactic_call_log,
                    steps_used=steps_used,
                    start_time=start_time,
                    interruption_message=interruption_message,
                    stop_reason=STOP_PROOF_INCOMPLETE,
                    agent_summary=(
                        "Leanstral agentic prover intercepted an empty tool-result cycle "
                        "and returned the latest proof state instead of "
                        "surfacing a raw API 3001 failure."
                    ),
                    partial=True,
                )

            if _is_cancel_scope_error(exc):
                # anyio raises this when asyncio's task cancellation propagates into
                # its cancel scopes during SDK timeout teardown (Python 3.12+). This
                # is semantically a timeout, not a hard failure — route to the graceful
                # partial-result path so any completed tactics are preserved.
                interruption_message = _normalized_interruption_warning("cancel_scope")
                trace_recorder.finalize_pending_attempt(tactic_call_log)
                return _build_interrupted_run_result(
                    controller=controller,
                    model_text=model_text,
                    tool_trace_entries=tool_trace_entries,
                    tactic_call_log=tactic_call_log,
                    steps_used=steps_used,
                    start_time=start_time,
                    interruption_message=interruption_message,
                    stop_reason=STOP_TIMEOUT,
                    agent_summary=(
                        "Leanstral agentic prover was interrupted during timeout "
                        "cleanup (underlying anyio cancel-scope task mismatch, "
                        "likely from Lean preamble compilation latency). "
                        "Returning the latest proof state."
                    ),
                    partial=True,
                )

            stop_reason = STOP_RUN_ERROR
            elapsed = time.time() - start_time
            trace_recorder.finalize_pending_attempt(tactic_call_log)
            return {
                "success": False,
                "strategy": model_text,
                "proof_tactics": controller.current_tactic_block,
                "full_lean_code": controller.current_lean_code,
                "errors": [str(exc)],
                "warnings": [],
                "tool_trace": tool_trace_entries,
                "tactic_calls": tactic_call_log,
                "trace_schema_version": TRACE_SCHEMA_VERSION,
                "steps_used": steps_used,
                "mcp_enabled": True,
                "agent_summary": f"run_async failed: {exc}",
                "stop_reason": stop_reason,
                "output_lean": None,
                "elapsed_seconds": elapsed,
                "partial": False,
            }

        _log(
            on_log,
            "agentic_run",
            "Leanstral loop completed "
            f"({steps_used} API round-trips, {len(tactic_call_log)} tactic calls)",
            status="done",
            elapsed_ms=(time.time() - t_agentic_run) * 1000,
        )
        trace_recorder.finalize_pending_attempt(tactic_call_log)

        # --- Step 4: Check if proof looks complete (pre-verification) ---
        current_tactics = controller.current_tactic_block
        if "sorry" in current_tactics:
            stop_reason = STOP_PROOF_INCOMPLETE
            _log(on_log, "agentic_check", "Proof still contains sorry", status="error")
        else:
            stop_reason = STOP_PROOF_COMPLETE
            _log(on_log, "agentic_check", "Proof appears complete (no sorry)", status="done")

        # --- Step 5: Final verification via the local Lean compiler ---
        _log(on_log, "agentic_verify", "Running final Lean verification...", status="running")
        t_agentic_verify = time.time()
        verification = verify(controller.current_lean_code)
        verify_elapsed_ms = (time.time() - t_agentic_verify) * 1000

        if verification["success"]:
            stop_reason = STOP_PROOF_COMPLETE
            _log(on_log, "agentic_verify", "Verified — Lean check passed", status="done",
                 elapsed_ms=verify_elapsed_ms)
        else:
            if stop_reason == STOP_PROOF_COMPLETE:
                stop_reason = (
                    STOP_PROOF_INCOMPLETE  # MCP said done but final verification disagreed
                )
            error_preview = str(verification["errors"][:2])
            _log(
                on_log,
                "agentic_verify",
                f"Verification failed: {error_preview}",
                data=str(verification["errors"]),
                status="error",
                elapsed_ms=verify_elapsed_ms,
            )

        elapsed = time.time() - start_time
        success = verification["success"]

        summary_parts = [
            f"Leanstral agentic prover: {steps_used} API round-trips, "
            f"{len(tactic_call_log)} tactic applications.",
            (
                f"Tool calls: {tool_tracker.total_tool_calls} total, "
                f"{tool_tracker.total_search_calls} search, "
                f"{tool_tracker.blocked_tool_calls} blocked."
            ),
        ]
        if tool_tracker.total_diagnostic_calls:
            summary_parts.append(
                f"Diagnostics checks observed: {tool_tracker.total_diagnostic_calls}."
            )
        if tool_tracker.circuit_breaker_hits:
            summary_parts.append(
                f"Circuit breaker triggered {tool_tracker.circuit_breaker_hits} time(s)."
            )
        if tool_tracker.search_budget_hits:
            summary_parts.append(
                f"Search budget blocked {tool_tracker.search_budget_hits} call(s)."
            )
        if tool_tracker.duplicate_read_only_hits:
            summary_parts.append(
                f"Duplicate read-only queries blocked "
                f"{tool_tracker.duplicate_read_only_hits} time(s)."
            )
        if success:
            summary_parts.append("Proof verified by the local Lean compiler.")
        else:
            summary_parts.append(f"Proof not verified. Stop reason: {stop_reason}.")

        return {
            "success": success,
            "strategy": model_text,
            "proof_tactics": current_tactics,
            "full_lean_code": controller.current_lean_code,
            "errors": verification["errors"],
            "warnings": verification["warnings"],
            "tool_trace": tool_trace_entries,
            "tactic_calls": tactic_call_log,
            "trace_schema_version": TRACE_SCHEMA_VERSION,
            "steps_used": steps_used,
            "mcp_enabled": True,
            "agent_summary": " ".join(summary_parts),
            "stop_reason": stop_reason,
            "output_lean": verification.get("output_lean"),
            "axiom_info": verification.get("axiom_info"),
            "elapsed_seconds": elapsed,
            "partial": False,
        }
    finally:
        controller.cleanup()


# ---------------------------------------------------------------------------
# Backend registration
# ---------------------------------------------------------------------------


@register_prover("leanstral")
class LeanstralProver:
    """Leanstral + lean-lsp-mcp agentic prover via Mistral's Conversations API."""

    @property
    def name(self) -> str:
        return "leanstral"

    def prove(
        self,
        theorem_with_sorry: str,
        on_log: Any | None = None,
    ) -> dict[str, Any]:
        return prove_theorem_agentic(
            theorem_with_sorry=theorem_with_sorry,
            on_log=on_log,
        )


# ---------------------------------------------------------------------------
# Public sync API
# ---------------------------------------------------------------------------


def prove_theorem_agentic(
    theorem_with_sorry: str,
    on_log: callable | None = None,
    max_steps: int = DEFAULT_MAX_STEPS,
) -> dict[str, Any]:
    """
    Agentic prover using Leanstral + MCP via Mistral's Conversations API.

    Leanstral autonomously calls lean-lsp-mcp tools and custom Python functions
    to build a proof interactively. Final verification is via the local Lean compiler.

    Args:
        theorem_with_sorry: Complete Lean 4 theorem with sorry placeholder.
        on_log: Optional callback for pipeline log entries.
        max_steps: Advisory step budget (actual loop is managed by run_async).

    Returns:
        dict with keys: success, strategy, proof_tactics, full_lean_code,
        errors, warnings, tool_trace, steps_used, mcp_enabled, agent_summary,
        stop_reason, output_lean, elapsed_seconds.
    """
    return asyncio.run(
        _prove_theorem_agentic_async(
            theorem_with_sorry=theorem_with_sorry,
            on_log=on_log,
            max_steps=max_steps,
        )
    )


if __name__ == "__main__":
    print("Run tests via: pytest -m live tests/test_agentic_examples.py")
