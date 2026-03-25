"""
FastAPI service wrapper for the LeanEcon pipeline.

This module exposes a frontend-friendly, multi-step API:
  - GET  /health
  - POST /api/v1/classify
  - POST /api/v1/formalize
  - POST /api/v1/lean_compile
  - POST /api/v1/verify      (async, returns 202 + job_id)
  - GET  /api/v1/jobs/{job_id}
  - GET  /api/v1/jobs/{job_id}/stream
  - POST /api/v1/explain
  - GET  /api/v1/metrics
  - GET  /api/v1/benchmarks/latest
  - GET  /api/v1/cache/stats
  - DELETE /api/v1/cache

Legacy unversioned routes (/api/classify, /api/formalize, /api/verify) are
preserved as deprecated wrappers for backward compatibility.
"""

from __future__ import annotations

import json
import logging
import queue
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

# Allow sibling imports such as `from pipeline import ...` to resolve when the
# app is launched via `uvicorn src.api:app`.
sys.path.insert(0, str(Path(__file__).parent))

from benchmark_harness import latest_snapshot_summary
from error_codes import LeanEconErrorCode
from eval_logger import LOG_FILE
from explainer import explain_result
from formalizer import classify_claim
from job_store import JobStatus, job_store
from lean_verifier import LEAN_SOURCE_DIR, VERIFICATION_FILE_PREFIX, compile_lean_code
from outcome_codes import formalize_error_code, verify_error_code
from pipeline import formalize_claim, parse_claim, run_pipeline
from result_cache import result_cache

logger = logging.getLogger(__name__)
AGENTIC_TEMP_FILE_GLOB = f"{VERIFICATION_FILE_PREFIX}_*.lean"

SAMPLE_NATURAL_LANGUAGE_CLAIM = (
    "Under CRRA utility u(c) = c^(1-gamma)/(1-gamma), "
    "relative risk aversion is constant and equal to gamma."
)

SAMPLE_RAW_LEAN_THEOREM = """\
import Mathlib
open Real

theorem one_plus_one : 1 + 1 = 2 := by
  sorry
"""

API_DESCRIPTION = """
Headless API for classifying, formalizing, and verifying mathematical claims
with Lean 4.

Recommended client workflow:

1. `POST /api/v1/classify` to determine whether the claim is in scope.
2. `POST /api/v1/formalize` to obtain a Lean theorem containing `:= by sorry`.
3. Optional direct compile path: `POST /api/v1/lean_compile` to run a local
   Lean compile without invoking the prover.
4. Optionally let a user or agent edit the theorem text.
5. `POST /api/v1/verify` with the formalized theorem — returns HTTP 202 and a
   `job_id`. Poll `GET /api/v1/jobs/{job_id}` or stream
   `GET /api/v1/jobs/{job_id}/stream` until the job finishes. Polling also
   returns additive observability metadata such as queue/start/finish timestamps
   and the latest reported pipeline stage.
6. Use `POST /api/v1/explain` for natural-language summaries of outcomes.
7. Use `GET /api/v1/metrics`, `GET /api/v1/benchmarks/latest`, and
   `GET /api/v1/cache/stats` for operational insight.

Important behavior:

- `classify` short-circuits raw Lean input and marks it as `RAW_LEAN`.
- `formalize` is the claim-shaping step and preserves the current pipeline
  behavior, including raw-Lean bypass.
- `lean_compile` is the thin synchronous compile/debug primitive. It compiles
  Lean code directly with the local Lean toolchain and returns compiler
  diagnostics without using the prover.
- `verify` expects a formalized Lean theorem/lemma/example with a `sorry`
  placeholder and is the async agentic proving path.
- final Lean verification uses isolated per-run `AgenticProof_*.lean` files, so
  concurrent verify jobs do not clobber a shared `Proof.lean` module.
"""

OPENAPI_TAGS = [
    {
        "name": "v1",
        "description": (
            "Versioned endpoints used by frontend clients and agents to classify, "
            "formalize, verify, and explain a claim."
        ),
    },
    {
        "name": "meta",
        "description": "Operational endpoints such as liveness checks.",
    },
]


@asynccontextmanager
async def app_lifespan(_: FastAPI):
    """Remove orphaned agentic temp files before the API starts serving jobs."""
    cleaned = _cleanup_orphaned_agentic_temp_files()
    logger.info(
        "Startup cleanup removed %s orphaned agentic temp file(s) from %s",
        cleaned,
        LEAN_SOURCE_DIR,
    )
    yield


app = FastAPI(
    title="LeanEcon API",
    version="1.0.0",
    summary="Lean-backed theorem verification API",
    description=API_DESCRIPTION,
    openapi_tags=OPENAPI_TAGS,
    lifespan=app_lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

router = APIRouter(prefix="/api/v1", tags=["v1"])


def _cleanup_orphaned_agentic_temp_files() -> int:
    """Delete temp proof files left behind by interrupted verification runs."""
    cleaned = 0
    for temp_file in LEAN_SOURCE_DIR.glob(AGENTIC_TEMP_FILE_GLOB):
        try:
            temp_file.unlink()
            cleaned += 1
        except FileNotFoundError:
            continue
    return cleaned


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class ClaimRequest(BaseModel):
    """Request body for raw-claim endpoints."""

    model_config = ConfigDict(
        json_schema_extra={"example": {"raw_claim": SAMPLE_NATURAL_LANGUAGE_CLAIM}}
    )

    raw_claim: str = Field(
        ...,
        description="Plain text, LaTeX, or raw Lean 4 input.",
    )


class VerifyRequest(BaseModel):
    """Request body for proof verification."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "theorem_code": SAMPLE_RAW_LEAN_THEOREM,
                "explain": False,
            }
        }
    )

    theorem_code: str = Field(
        ...,
        description=("Formalized Lean theorem file content that still contains `sorry`."),
    )
    explain: bool = Field(
        default=False,
        description="Include a natural language explanation in the job result.",
    )


class LeanCompileRequest(BaseModel):
    """Request body for direct Lean compilation without proving."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "lean_code": (
                    "import Mathlib\n\ntheorem one_plus_one : 1 + 1 = 2 := by\n  norm_num\n"
                ),
                "filename": "one_plus_one.lean",
                "check_axioms": False,
            }
        }
    )

    lean_code: str = Field(
        ...,
        description="Complete Lean file content to compile directly with the local Lean toolchain.",
    )
    filename: str | None = Field(
        default=None,
        description="Optional file label used to derive the temporary Lean filename.",
    )
    check_axioms: bool = Field(
        default=False,
        description="If true, run a best-effort axiom check after a successful compile.",
    )


class ExplainRequest(BaseModel):
    """Request body for the explain endpoint."""

    original_claim: str = Field(..., description="The user's original input.")
    theorem_code: str | None = Field(default=None, description="Formalized theorem (if available).")
    verification_result: dict[str, Any] | None = Field(
        default=None, description="Output of verify (if available)."
    )
    classification_result: dict[str, Any] | None = Field(
        default=None, description="Output of classify (if available)."
    )
    formalization_result: dict[str, Any] | None = Field(
        default=None, description="Output of formalize (if available)."
    )


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class HealthResponse(BaseModel):
    """Liveness response."""

    model_config = ConfigDict(json_schema_extra={"example": {"status": "ok"}})

    status: Literal["ok"]


class ClassifyResponse(BaseModel):
    """Frontend-oriented claim classification response."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "cleaned_claim": SAMPLE_NATURAL_LANGUAGE_CLAIM,
                "category": "ALGEBRAIC",
                "formalizable": True,
                "reason": None,
                "is_raw_lean": False,
                "error_code": "none",
                "definitions_needed": None,
                "preamble_matches": [],
                "suggested_reformulation": None,
            }
        }
    )

    cleaned_claim: str = Field(description="Normalized claim text after lightweight cleaning.")
    category: Literal[
        "RAW_LEAN", "ALGEBRAIC", "MATHLIB_NATIVE", "DEFINABLE", "REQUIRES_DEFINITIONS"
    ] = Field(description="High-level claim class used to decide whether to continue.")
    formalizable: bool = Field(
        description="Whether the current claim appears in scope for formalization."
    )
    reason: str | None = Field(
        default=None,
        description="Reason for rejection when the claim needs missing definitions.",
    )
    is_raw_lean: bool = Field(description="Whether the input already looked like Lean code.")
    error_code: LeanEconErrorCode = Field(
        default=LeanEconErrorCode.NONE,
        description="Machine-readable error code.",
    )
    definitions_needed: str | None = Field(
        default=None,
        description="What definitions are needed (DEFINABLE claims only).",
    )
    preamble_matches: list[str] = Field(
        default_factory=list,
        description="Preamble library entries matching the claim.",
    )
    suggested_reformulation: str | None = Field(
        default=None,
        description="Reformulation hint for DEFINABLE claims.",
    )
    provider_telemetry: dict[str, Any] | None = Field(
        default=None,
        description="Optional provider usage telemetry for the classifier call.",
    )


class FormalizeRequest(BaseModel):
    """Request body for formalization with optional preamble."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "raw_claim": SAMPLE_NATURAL_LANGUAGE_CLAIM,
                "preamble_names": [],
            }
        }
    )

    raw_claim: str = Field(
        ...,
        description="Plain text, LaTeX, or raw Lean 4 input.",
    )
    preamble_names: list[str] = Field(
        default_factory=list,
        description=(
            "Optional list of preamble definition names to inject. "
            "If empty, the formalizer may auto-select matching preamble modules "
            "using bounded retrieval."
        ),
    )


class FormalizeResponse(BaseModel):
    """Direct API shape for the formalization stage."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "success": True,
                "theorem_code": SAMPLE_RAW_LEAN_THEOREM,
                "attempts": 1,
                "errors": [],
                "formalization_failed": False,
                "failure_reason": None,
                "error_code": "none",
                "preamble_used": [],
                "diagnosis": None,
                "suggested_fix": None,
                "fixable": None,
            }
        }
    )

    success: bool = Field(description="Whether the theorem compiled with `sorry`.")
    theorem_code: str = Field(
        description="Complete Lean theorem/file content returned by the formalizer."
    )
    attempts: int = Field(description="Number of formalization or repair attempts used.")
    errors: list[str] = Field(description="Lean errors from the last failed formalization attempt.")
    formalization_failed: bool = Field(
        description="Whether the claim was rejected as out of scope for Mathlib."
    )
    failure_reason: str | None = Field(
        default=None,
        description="Model-provided reason when formalization was rejected.",
    )
    error_code: LeanEconErrorCode = Field(
        default=LeanEconErrorCode.NONE,
        description="Machine-readable error code.",
    )
    preamble_used: list[str] = Field(
        default_factory=list,
        description="Names of preamble definitions injected into the theorem.",
    )
    diagnosis: str | None = Field(
        default=None,
        description="Failure analysis when repair attempts are exhausted.",
    )
    suggested_fix: str | None = Field(
        default=None,
        description="Concrete suggestion for fixing the formalization.",
    )
    fixable: bool | None = Field(
        default=None,
        description="Whether the failure is likely fixable by human editing.",
    )
    provider_telemetry: dict[str, Any] | None = Field(
        default=None,
        description="Optional provider usage telemetry for the formalizer call(s).",
    )


class VerifyResponse(BaseModel):
    """API response for the prove-and-verify stage."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "success": True,
                "lean_code": SAMPLE_RAW_LEAN_THEOREM.replace("sorry", "norm_num"),
                "errors": [],
                "warnings": [],
                "proof_strategy": "Use `norm_num` to close the arithmetic goal.",
                "proof_tactics": "norm_num",
                "theorem_statement": SAMPLE_RAW_LEAN_THEOREM,
                "formalization_attempts": 0,
                "formalization_failed": False,
                "failure_reason": None,
                "output_lean": None,
                "proof_generated": True,
                "phase": "verified",
                "elapsed_seconds": 1.23,
                "from_cache": False,
                "partial": False,
                "stop_reason": None,
                "error_code": "none",
                "explanation": None,
                "explanation_generated": None,
            }
        }
    )

    success: bool = Field(description="Whether Lean accepted the final proof.")
    lean_code: str = Field(description="Final Lean file content returned by the verification run.")
    errors: list[str] = Field(description="Lean verification errors, if any.")
    warnings: list[str] = Field(description="Lean warnings emitted during verification.")
    proof_strategy: str = Field(description="High-level proof plan reported by the proving stage.")
    proof_tactics: str = Field(
        description="Tactic script or tactics summary produced by the prover."
    )
    theorem_statement: str = Field(
        description="The theorem statement that entered the proving stage."
    )
    formalization_attempts: int = Field(
        description="Formalization attempts used before proving began."
    )
    formalization_failed: bool = Field(
        description="Whether the request failed during the formalization phase."
    )
    failure_reason: str | None = Field(
        default=None,
        description="Reason for an early formalization failure, when applicable.",
    )
    output_lean: str | None = Field(
        default=None,
        description="Optional path to an output Lean artifact produced by the verifier.",
    )
    proof_generated: bool = Field(
        description="Whether the prover produced at least one proof attempt."
    )
    phase: Literal["verified", "proved", "failed"] = Field(
        description=(
            "`verified` means Lean accepted the proof, `proved` means a proof was "
            "generated but Lean rejected it, and `failed` means the pipeline did "
            "not reach a valid proof."
        )
    )
    elapsed_seconds: float = Field(description="Total wall-clock time reported by the pipeline.")
    from_cache: bool = Field(
        default=False,
        description="True if the response was served from the verified-result cache.",
    )
    partial: bool = Field(
        default=False,
        description="True if the prover timed out and this response contains partial results.",
    )
    stop_reason: str | None = Field(
        default=None,
        description="Why the proving loop stopped, when reported by the prover.",
    )
    axiom_info: dict | None = Field(
        default=None,
        description=(
            "Axiom usage from lean_verify. Contains 'axioms' (list), "
            "'sound' (bool), 'has_sorry_ax' (bool). Only present on "
            "successful verifications when MCP is available."
        ),
    )
    error_code: LeanEconErrorCode = Field(
        default=LeanEconErrorCode.NONE,
        description="Machine-readable error code.",
    )
    explanation: str | None = Field(
        default=None,
        description="Natural language explanation (only present when explain=True).",
    )
    explanation_generated: bool | None = Field(
        default=None,
        description="True if LLM generated the explanation, False if fallback.",
    )
    provider_telemetry: dict[str, Any] | None = Field(
        default=None,
        description="Optional provider usage telemetry for the proving/formalization path.",
    )
    explanation_telemetry: dict[str, Any] | None = Field(
        default=None,
        description="Optional provider usage telemetry for the explanation step.",
    )


class LeanCompileResponse(BaseModel):
    """Direct compiler response for Lean code that bypasses the prover."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "success": True,
                "errors": [],
                "warnings": [],
                "stdout": "",
                "stderr": "",
                "verification_method": "lake_env_lean",
                "elapsed_ms": 412.7,
                "axiom_info": None,
            }
        }
    )

    success: bool = Field(description="Whether Lean accepted the provided file as-is.")
    errors: list[str] = Field(description="Lean compiler errors, if any.")
    warnings: list[str] = Field(description="Lean compiler warnings emitted during the check.")
    stdout: str = Field(description="Captured stdout from the local Lean compiler invocation.")
    stderr: str = Field(description="Captured stderr from the local Lean compiler invocation.")
    verification_method: str = Field(description="Compiler path used for the direct check.")
    elapsed_ms: float = Field(description="Wall-clock compile time in milliseconds.")
    axiom_info: dict | None = Field(
        default=None,
        description=(
            "Best-effort axiom usage data for a successful theorem/lemma compile when "
            "`check_axioms=true`."
        ),
    )
    telemetry: dict[str, Any] | None = Field(
        default=None,
        description="Local-only telemetry for the direct Lean compile step.",
    )


class VerifyAcceptedResponse(BaseModel):
    """Returned immediately when a verify job is queued."""

    job_id: str = Field(description="Unique job identifier for polling.")
    status: Literal["queued"] = Field(description="Always 'queued' at submission time.")


class JobStatusResponse(BaseModel):
    """Status check for a queued/running/completed/failed job."""

    job_id: str
    status: str = Field(description="queued | running | completed | failed")
    result: VerifyResponse | None = None
    error: str | None = None
    queued_at: str | None = Field(
        default=None,
        description="UTC timestamp when the job was queued.",
    )
    started_at: str | None = Field(
        default=None, description="UTC timestamp when the job entered running state."
    )
    finished_at: str | None = Field(
        default=None, description="UTC timestamp when the job completed or failed."
    )
    last_progress_at: str | None = Field(
        default=None,
        description="UTC timestamp of the latest progress event observed for the job.",
    )
    current_stage: str | None = Field(
        default=None,
        description="Most recent pipeline stage reported for the job.",
    )
    stage_timings: dict[str, float] = Field(
        default_factory=dict,
        description="Per-stage elapsed time in milliseconds, keyed by stage name.",
    )


class ExplainResponse(BaseModel):
    """Natural language explanation of pipeline results."""

    explanation: str = Field(description="Markdown-formatted explanation.")
    generated: bool = Field(description="True if LLM generated, False if fallback.")
    provider_telemetry: dict[str, Any] | None = Field(
        default=None,
        description="Optional provider usage telemetry for the explanation call.",
    )
    error_code: LeanEconErrorCode = Field(
        default=LeanEconErrorCode.NONE,
        description="Machine-readable error code.",
    )


class MetricsResponse(BaseModel):
    """Aggregate metrics derived from the JSONL evaluation log."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "total_runs": 12,
                "verified": 9,
                "formalization_failures": 1,
                "proof_failures": 2,
                "cache_hits": 3,
                "partial_runs": 1,
                "avg_elapsed_seconds": 18.4,
                "verification_rate": 0.75,
                "cache_hit_rate": 0.25,
            }
        }
    )

    total_runs: int = Field(description="Number of JSONL eval-log entries parsed.")
    verified: int = Field(description="Runs whose verification stage succeeded.")
    formalization_failures: int = Field(
        description="Runs marked as formalization failures in the eval log."
    )
    proof_failures: int = Field(
        description="Runs that were not verified and were not formalization failures."
    )
    cache_hits: int = Field(description="Runs served from the verified-result cache.")
    partial_runs: int = Field(description="Runs that ended with partial prover output.")
    avg_elapsed_seconds: float = Field(
        description="Average elapsed wall-clock time across parsed runs."
    )
    verification_rate: float = Field(description="Verified runs divided by total runs.")
    cache_hit_rate: float = Field(description="Cache-hit runs divided by total runs.")


class BenchmarkStatusResponse(BaseModel):
    """Summary-only view of the newest offline benchmark snapshot."""

    generated_at: str = Field(description="UTC timestamp of the newest benchmark snapshot.")
    benchmark_file: str = Field(description="Benchmark JSONL used to produce the snapshot.")
    config: dict[str, Any] = Field(
        description="Benchmark runner configuration for the latest snapshot."
    )
    summary: dict[str, Any] = Field(
        description="Aggregate benchmark results without per-claim internals."
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _require_non_empty(value: str, field_name: str) -> str:
    """Reject blank or whitespace-only text payloads."""
    cleaned = value.strip()
    if not cleaned:
        raise HTTPException(status_code=422, detail=f"`{field_name}` must not be blank.")
    return cleaned


def _is_raw_lean_input(raw_input: str) -> bool:
    """Mirror the raw-Lean detection logic used in the pipeline."""
    return "import Mathlib" in raw_input or (":= by" in raw_input and "sorry" in raw_input)


def _looks_like_formalized_theorem(theorem_code: str) -> bool:
    """Reject obvious non-Lean or non-proof-stub inputs at the API boundary."""
    normalized = theorem_code.strip()
    has_statement = any(keyword in normalized for keyword in ("theorem ", "lemma ", "example "))
    has_proof_stub = "sorry" in normalized and (":= by" in normalized or ":=by" in normalized)
    return has_statement and has_proof_stub


def _server_error(message: str, exc: Exception) -> HTTPException:
    """Standardize 500 responses across endpoints."""
    return HTTPException(status_code=500, detail=f"{message}: {exc}")


def _format_sse_event(event: dict[str, Any]) -> str:
    """Encode an SSE payload as a single JSON data frame."""
    return f"data: {json.dumps(event)}\n\n"


def _empty_metrics() -> MetricsResponse:
    """Return a zeroed metrics payload."""
    return MetricsResponse(
        total_runs=0,
        verified=0,
        formalization_failures=0,
        proof_failures=0,
        cache_hits=0,
        partial_runs=0,
        avg_elapsed_seconds=0.0,
        verification_rate=0.0,
        cache_hit_rate=0.0,
    )


# ---------------------------------------------------------------------------
# Background task
# ---------------------------------------------------------------------------


def _run_verify_job(job_id: str, theorem_code: str, explain: bool) -> None:
    """Background task that runs the full pipeline and stores the result."""
    job_store.update_status(job_id, JobStatus.RUNNING)

    def on_log(entry: dict[str, Any]) -> None:
        """Forward pipeline log entries to SSE subscribers."""
        stage = str(entry.get("stage", ""))
        status = str(entry.get("status", "done"))
        elapsed_ms = entry.get("elapsed_ms")
        job_store.record_progress(job_id, stage, status=status, elapsed_ms=elapsed_ms)
        job_store.publish(
            job_id,
            {
                "type": "progress",
                "stage": stage,
                "message": str(entry.get("message", "")),
                "status": status,
            },
        )

    try:
        result = run_pipeline(
            raw_input=theorem_code,
            preformalized_theorem=theorem_code,
            on_log=on_log,
        )
        error_code = verify_error_code(result)
        response_data: dict[str, Any] = {
            "error_code": error_code,
            **result,
        }
        if explain:
            explanation_calls: list[dict[str, Any]] = []
            expl = explain_result(
                original_claim=theorem_code,
                theorem_code=theorem_code,
                verification_result=result,
                on_log=on_log,
                telemetry_out=explanation_calls,
            )
            response_data["explanation"] = expl["explanation"]
            response_data["explanation_generated"] = expl["generated"]
            response_data["explanation_telemetry"] = expl.get("provider_telemetry")
        job_store.complete(job_id, response_data)
    except Exception as exc:
        job_store.fail(job_id, str(exc))


# ---------------------------------------------------------------------------
# Meta endpoint (unversioned)
# ---------------------------------------------------------------------------


@app.get(
    "/health",
    response_model=HealthResponse,
    tags=["meta"],
    summary="Service health",
    description="Returns a simple liveness payload for local checks and orchestration.",
)
def health() -> HealthResponse:
    """Simple liveness endpoint for local/dev tooling and container checks."""
    return HealthResponse(status="ok")


# ---------------------------------------------------------------------------
# v1 endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/classify",
    response_model=ClassifyResponse,
    summary="Classify a claim",
    description=(
        "Pre-screen a claim before formalization. Raw Lean input is detected "
        "immediately and returned as `RAW_LEAN`; other claims are cleaned with "
        "`parse_claim()` and then sent through the lightweight classifier."
    ),
    responses={
        422: {"description": "The claim was blank or empty after cleaning."},
        500: {"description": "Unexpected classifier failure."},
    },
)
def classify_endpoint(request: ClaimRequest) -> ClassifyResponse:
    """Determine whether the input looks formalizable before running the full pipeline."""
    raw_claim = _require_non_empty(request.raw_claim, "raw_claim")

    if _is_raw_lean_input(raw_claim):
        return ClassifyResponse(
            cleaned_claim=raw_claim,
            category="RAW_LEAN",
            formalizable=True,
            reason=None,
            is_raw_lean=True,
            error_code=LeanEconErrorCode.NONE,
            provider_telemetry=None,
        )

    try:
        cleaned_claim = parse_claim(raw_claim)["text"]
        if not cleaned_claim:
            raise HTTPException(
                status_code=422,
                detail="`raw_claim` must contain non-empty content after cleaning.",
            )

        provider_calls: list[dict[str, Any]] = []
        classification = classify_claim(cleaned_claim, telemetry_out=provider_calls)
        is_rejected = classification["category"] == "REQUIRES_DEFINITIONS"
        formalizable = not is_rejected  # ALGEBRAIC, DEFINABLE, and MATHLIB_NATIVE are formalizable
        return ClassifyResponse(
            cleaned_claim=cleaned_claim,
            category=classification["category"],
            formalizable=formalizable,
            reason=classification["reason"],
            is_raw_lean=False,
            error_code=LeanEconErrorCode.CLASSIFICATION_REJECTED
            if is_rejected
            else LeanEconErrorCode.NONE,
            definitions_needed=classification.get("definitions_needed"),
            preamble_matches=classification.get("preamble_matches", []),
            suggested_reformulation=classification.get("suggested_reformulation"),
            provider_telemetry=classification.get("provider_telemetry"),
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise _server_error("Claim classification failed", exc) from exc


@router.post(
    "/formalize",
    response_model=FormalizeResponse,
    summary="Formalize a claim",
    description=(
        "Convert natural language or LaTeX into a Lean theorem file that still "
        "contains `:= by sorry`. Raw Lean input is passed through unchanged. "
        "Optionally accepts `preamble_names` to inject known definitions; when "
        "omitted, the formalizer may auto-select matching preambles."
    ),
    responses={
        422: {"description": "The claim was blank."},
        500: {"description": "Unexpected formalization failure."},
    },
)
def formalize_endpoint(request: FormalizeRequest) -> FormalizeResponse:
    """Formalize natural-language or LaTeX claims into Lean 4 theorem code."""
    raw_claim = _require_non_empty(request.raw_claim, "raw_claim")

    try:
        preamble_names = request.preamble_names or None
        result = formalize_claim(raw_claim, preamble_names=preamble_names)
        error_code = formalize_error_code(result)
        provider_telemetry = result.get("formalizer_telemetry", {}).get("provider_telemetry")
        return FormalizeResponse(
            error_code=error_code, provider_telemetry=provider_telemetry, **result
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise _server_error("Claim formalization failed", exc) from exc


@router.post(
    "/lean_compile",
    response_model=LeanCompileResponse,
    summary="Compile Lean code directly",
    description=(
        "Compile a complete Lean file directly with the local Lean toolchain, "
        "without using the formalizer or agentic prover. This is useful for "
        "kernel-truth checks, API clients that already have Lean code, and "
        "debugging preformalized statements before verify."
    ),
    responses={
        422: {"description": "The Lean source payload was blank."},
        500: {"description": "Unexpected compiler failure."},
    },
)
def lean_compile_endpoint(request: LeanCompileRequest) -> LeanCompileResponse:
    """Compile Lean code directly without queueing a proving job."""
    lean_code = _require_non_empty(request.lean_code, "lean_code")

    try:
        result = compile_lean_code(
            lean_code,
            filename=request.filename,
            check_axioms=request.check_axioms,
        )
        return LeanCompileResponse(
            success=result["success"],
            errors=result["errors"],
            warnings=result["warnings"],
            stdout=result["stdout"],
            stderr=result["stderr"],
            verification_method=result.get("verification_method", "lake_env_lean"),
            elapsed_ms=float(result.get("elapsed_ms", 0.0)),
            axiom_info=result.get("axiom_info"),
            telemetry=result.get("telemetry"),
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise _server_error("Direct Lean compile failed", exc) from exc


@router.post(
    "/verify",
    response_model=VerifyAcceptedResponse,
    status_code=202,
    summary="Verify a formalized theorem (async)",
    description=(
        "Queue a proving and Lean verification job. Returns HTTP 202 with a `job_id` "
        "immediately. Poll `GET /api/v1/jobs/{job_id}` or stream "
        "`GET /api/v1/jobs/{job_id}/stream` until status is `completed` or "
        "`failed`. LeanEcon uses the agentic prover for all verify jobs."
    ),
    responses={
        202: {"description": "Job queued successfully."},
        422: {
            "description": ("The theorem payload was blank or did not look like a Lean proof stub.")
        },
    },
)
def verify_endpoint(
    request: VerifyRequest, background_tasks: BackgroundTasks
) -> VerifyAcceptedResponse:
    """Queue an async proof-and-verify job."""
    theorem_code = _require_non_empty(request.theorem_code, "theorem_code")
    if not _looks_like_formalized_theorem(theorem_code):
        raise HTTPException(
            status_code=422,
            detail=(
                "`theorem_code` must be a Lean theorem/lemma/example with a "
                "`:= by sorry` proof stub."
            ),
        )

    job_id = job_store.create({"theorem_code": theorem_code, "explain": request.explain})
    background_tasks.add_task(_run_verify_job, job_id, theorem_code, request.explain)
    return VerifyAcceptedResponse(job_id=job_id, status="queued")


@router.get(
    "/jobs/{job_id}",
    response_model=JobStatusResponse,
    summary="Poll a verify job",
    description="Get the current status and result of a queued or completed verify job.",
    responses={
        404: {"description": "Job not found or expired."},
    },
)
def get_job_status(job_id: str) -> JobStatusResponse:
    """Return the current status of a verify job."""
    job = job_store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found or expired.")
    result = None
    if job.get("result") is not None:
        result = VerifyResponse(**job["result"])
    return JobStatusResponse(
        job_id=job_id,
        status=job["status"],
        result=result,
        error=job.get("error"),
        queued_at=job.get("queued_at"),
        started_at=job.get("started_at"),
        finished_at=job.get("finished_at"),
        last_progress_at=job.get("last_progress_at"),
        current_stage=job.get("current_stage"),
        stage_timings=job.get("stage_timings", {}),
    )


@router.get(
    "/jobs/{job_id}/stream",
    summary="Stream verify job progress (SSE)",
    description=(
        "Returns a Server-Sent Events stream of job progress. Events use a JSON "
        "`data:` payload with `type` (`progress` or `complete`), `stage`, "
        "`message`, and `status`. The stream closes automatically after the job "
        "completes or fails."
    ),
    responses={
        200: {"description": "SSE event stream", "content": {"text/event-stream": {}}},
        404: {"description": "Job not found or expired."},
    },
)
def stream_job_events(job_id: str) -> StreamingResponse:
    """Stream real-time progress events for a verify job."""
    job = job_store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found or expired.")

    headers = {
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
    }

    if job["status"] in (JobStatus.COMPLETED, JobStatus.FAILED):

        def already_done():
            event = {
                "type": "complete",
                "status": job["status"],
            }
            if job.get("error"):
                event["error"] = job["error"]
            yield _format_sse_event(event)

        return StreamingResponse(
            already_done(),
            media_type="text/event-stream",
            headers=headers,
        )

    subscriber = job_store.subscribe(job_id)

    def event_generator():
        try:
            while True:
                try:
                    event = subscriber.get(timeout=1.0)
                    yield _format_sse_event(event)
                    if event.get("type") == "complete":
                        break
                except queue.Empty:
                    yield ": keepalive\n\n"
                    current = job_store.get(job_id)
                    if current and current["status"] in (JobStatus.COMPLETED, JobStatus.FAILED):
                        final_event = {
                            "type": "complete",
                            "status": current["status"],
                        }
                        if current.get("error"):
                            final_event["error"] = current["error"]
                        yield _format_sse_event(final_event)
                        break
        finally:
            job_store.unsubscribe(job_id, subscriber)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers=headers,
    )


@router.post(
    "/explain",
    response_model=ExplainResponse,
    summary="Explain a pipeline result",
    description=(
        "Generate a natural language explanation of any pipeline artifact. "
        "Pass whichever of `verification_result`, `formalization_result`, or "
        "`classification_result` you have available."
    ),
    responses={
        422: {"description": "original_claim was blank."},
        500: {"description": "Explanation generation failed."},
    },
)
def explain_endpoint(request: ExplainRequest) -> ExplainResponse:
    """Generate a natural language explanation of any pipeline result."""
    original_claim = _require_non_empty(request.original_claim, "original_claim")

    # Build the best available verification_result dict for the explainer
    v_result: dict[str, Any] = request.verification_result or {}

    if not v_result:
        if request.formalization_result:
            f = request.formalization_result
            v_result = {
                "success": False,
                "formalization_failed": f.get("formalization_failed", False),
                "failure_reason": f.get("failure_reason"),
                "errors": f.get("errors", []),
                "proof_generated": False,
            }
        elif request.classification_result:
            c = request.classification_result
            v_result = {
                "success": False,
                "formalization_failed": not c.get("formalizable", True),
                "failure_reason": c.get("reason"),
                "errors": [],
                "proof_generated": False,
            }

    try:
        explanation_calls: list[dict[str, Any]] = []
        result = explain_result(
            original_claim=original_claim,
            theorem_code=request.theorem_code or "",
            verification_result=v_result,
            telemetry_out=explanation_calls,
        )
        return ExplainResponse(
            explanation=result["explanation"],
            generated=result["generated"],
            provider_telemetry=result.get("provider_telemetry"),
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Explanation failed: {exc}") from exc


@router.get(
    "/metrics",
    response_model=MetricsResponse,
    summary="Pipeline run metrics",
    description=(
        "Aggregate verification metrics from the append-only JSONL evaluation "
        "log pointed to by `LEANECON_STATE_DIR/logs/runs.jsonl` when configured, "
        "or `logs/runs.jsonl` by default."
    ),
)
def metrics() -> MetricsResponse:
    """Aggregate counts and rates from the structured evaluation log."""
    if not LOG_FILE.is_file():
        return _empty_metrics()

    runs: list[dict[str, Any]] = []
    for line in LOG_FILE.read_text(encoding="utf-8").splitlines():
        try:
            runs.append(json.loads(line))
        except json.JSONDecodeError:
            continue

    total = len(runs)
    if total == 0:
        return _empty_metrics()

    verified = sum(1 for run in runs if run.get("verification", {}).get("success"))
    formalization_failures = sum(
        1 for run in runs if run.get("formalization", {}).get("formalization_failed")
    )
    cache_hits = sum(1 for run in runs if run.get("from_cache"))
    partial_runs = sum(1 for run in runs if run.get("partial"))
    avg_elapsed = sum(float(run.get("elapsed_seconds", 0.0)) for run in runs) / total
    proof_failures = max(total - verified - formalization_failures, 0)

    return MetricsResponse(
        total_runs=total,
        verified=verified,
        formalization_failures=formalization_failures,
        proof_failures=proof_failures,
        cache_hits=cache_hits,
        partial_runs=partial_runs,
        avg_elapsed_seconds=round(avg_elapsed, 1),
        verification_rate=round(verified / total, 3),
        cache_hit_rate=round(cache_hits / total, 3),
    )


@router.get(
    "/benchmarks/latest",
    response_model=BenchmarkStatusResponse,
    summary="Latest benchmark snapshot summary",
    description=(
        "Return the summary-only view of the newest offline benchmark snapshot "
        "under `${LEANECON_STATE_DIR}/benchmarks/snapshots/` when configured, "
        "or the bundled `benchmarks/snapshots/` fallback, without exposing "
        "per-claim internals."
    ),
    responses={
        404: {"description": "No benchmark snapshot has been generated yet."},
    },
)
def benchmark_status() -> BenchmarkStatusResponse:
    """Return the newest benchmark summary, if available."""
    summary = latest_snapshot_summary()
    if summary is None:
        raise HTTPException(status_code=404, detail="No benchmark snapshot found.")
    return BenchmarkStatusResponse(**summary)


@router.get(
    "/cache/stats",
    summary="Inspect cache state",
    description="Return the number of verified results currently stored in the cache.",
)
def cache_stats() -> dict[str, int]:
    """Return basic cache statistics."""
    return {"size": result_cache.size}


@router.delete(
    "/cache",
    summary="Clear the verified-result cache",
    description="Delete all cached verified results.",
)
def clear_cache() -> dict[str, str]:
    """Clear the verified-result cache."""
    result_cache.clear()
    return {"status": "cleared"}


# ---------------------------------------------------------------------------
# Legacy unversioned routes (deprecated, backward-compat)
# ---------------------------------------------------------------------------


@app.post("/api/classify", deprecated=True, include_in_schema=False)
def classify_legacy(request: ClaimRequest) -> ClassifyResponse:
    return classify_endpoint(request)


@app.post("/api/formalize", deprecated=True, include_in_schema=False)
def formalize_legacy(request: ClaimRequest) -> FormalizeResponse:
    return formalize_endpoint(FormalizeRequest(raw_claim=request.raw_claim))


@app.post("/api/verify", deprecated=True, include_in_schema=False, status_code=202)
def verify_legacy(
    request: VerifyRequest, background_tasks: BackgroundTasks
) -> VerifyAcceptedResponse:
    return verify_endpoint(request, background_tasks)


# ---------------------------------------------------------------------------
# Register router
# ---------------------------------------------------------------------------

app.include_router(router)
