"""Bounded retrieval helpers for compiler-grounded formalization."""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field
from typing import Any

from mcp_runtime import (
    FORMALIZATION_MCP_CAPABILITY_RETRIEVAL,
    formalization_mcp_available,
    mark_formalization_mcp_failure,
    mark_formalization_mcp_success,
    open_lean_mcp_session,
    prime_lean_mcp_session,
)
from preamble_library import (
    DEFAULT_AUTO_PREAMBLE_LIMIT,
    build_preamble_imports,
    build_preamble_prompt_block,
    normalize_preamble_names,
    select_preamble_plan,
    serialize_preamble_entry,
    validate_preamble_names,
)

FORMALIZATION_MCP_SEARCH_ENABLED = os.environ.get(
    "LEANECON_ENABLE_FORMALIZATION_MCP_SEARCH", "1"
).strip().lower() in {"1", "true", "yes", "on"}
FORMALIZATION_MCP_SEARCH_TIMEOUT_SECONDS = float(
    os.environ.get("LEANECON_FORMALIZATION_MCP_SEARCH_TIMEOUT_SECONDS", "5")
)
MAX_MCP_SEARCH_QUERIES = int(os.environ.get("LEANECON_FORMALIZATION_MCP_SEARCH_QUERIES", "2"))
FORMALIZATION_RUNTIME_MCP_RETRIEVAL_ENABLED = os.environ.get(
    "LEANECON_ENABLE_FORMALIZATION_MCP_SEARCH", "1"
).strip().lower() in {"1", "true", "yes", "on"}
MAX_AUTO_PREAMBLES = int(
    os.environ.get("LEANECON_FORMALIZATION_AUTO_PREAMBLES", str(DEFAULT_AUTO_PREAMBLE_LIMIT))
)
FORMALIZATION_MCP_SEARCH_CACHE_LIMIT = int(
    os.environ.get("LEANECON_FORMALIZATION_MCP_SEARCH_CACHE_LIMIT", "64")
)
_FORMALIZATION_MCP_SEARCH_CACHE: dict[tuple[str, ...], "CachedMcpSearchResult"] = {}


@dataclass(frozen=True)
class CuratedHint:
    """One curated retrieval mapping from concepts to Lean hints."""

    label: str
    keywords: tuple[str, ...]
    imports: tuple[str, ...] = ()
    identifiers: tuple[str, ...] = ()
    search_terms: tuple[str, ...] = ()
    shape_guidance: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class SearchHit:
    """One retrieval hit surfaced to the prompt builder."""

    source: str
    query: str
    text: str


@dataclass(frozen=True)
class CachedMcpSearchResult:
    """Cached formalization MCP result that preserves skip semantics."""

    hits: tuple[SearchHit, ...]
    skip_reason: str | None


@dataclass(frozen=True)
class RuntimeSearchDirective:
    """One structured search step suggested to the prover or runtime retrieval."""

    tool: str
    query: str
    reason: str


@dataclass
class FormalizationContext:
    """Structured prompt context for theorem-stub generation."""

    claim_text: str
    claim_components: list[str]
    explicit_preamble_names: list[str] = field(default_factory=list)
    auto_preamble_names: list[str] = field(default_factory=list)
    preamble_names: list[str] = field(default_factory=list)
    advisory_preamble_names: list[str] = field(default_factory=list)
    selected_preamble_details: list[dict[str, Any]] = field(default_factory=list)
    advisory_preamble_details: list[dict[str, Any]] = field(default_factory=list)
    selection_mode: str = "none"
    preamble_block: str = ""
    preamble_imports: list[str] = field(default_factory=list)
    candidate_imports: list[str] = field(default_factory=list)
    candidate_identifiers: list[str] = field(default_factory=list)
    search_terms: list[str] = field(default_factory=list)
    shape_guidance: list[str] = field(default_factory=list)
    retrieval_notes: list[str] = field(default_factory=list)
    runtime_search_plan: list[RuntimeSearchDirective] = field(default_factory=list)
    mcp_hits: list[SearchHit] = field(default_factory=list)
    mcp_requested: bool = False
    mcp_enabled: bool = False
    mcp_skip_reason: str | None = None
    source_counts: dict[str, int] = field(
        default_factory=lambda: {"preamble": 0, "curated": 0, "mcp": 0}
    )

    def build_prompt_block(self) -> str:
        """Render a compact retrieval summary for the formalizer prompt."""
        lines = ["RETRIEVAL CONTEXT (bounded Lean-aware hints):"]
        if self.claim_components:
            lines.append(f"- Claim components: {', '.join(self.claim_components)}")
        if self.selected_preamble_details:
            preamble_label = (
                "Selected preambles"
                if self.selection_mode == "explicit"
                else "Auto-selected preambles"
            )
            rendered = [
                f"{detail['name']} [{detail['status']}]"
                for detail in self.selected_preamble_details[:8]
            ]
            lines.append(f"- {preamble_label}: {', '.join(rendered)}")
        elif self.preamble_names:
            lines.append(f"- Selected preambles: {', '.join(self.preamble_names)}")
        if (
            self.advisory_preamble_details
            and self.advisory_preamble_names != self.preamble_names
        ):
            rendered = [
                f"{detail['name']} [{detail['status']}]"
                for detail in self.advisory_preamble_details[:8]
            ]
            lines.append(f"- Other advisory preambles: {', '.join(rendered)}")
        elif (
            self.advisory_preamble_names
            and self.advisory_preamble_names != self.preamble_names
        ):
            lines.append(
                "- Other advisory preambles: "
                f"{', '.join(self.advisory_preamble_names[:8])}"
            )
        if self.candidate_imports:
            lines.append(f"- Candidate imports: {', '.join(self.candidate_imports[:8])}")
        if self.candidate_identifiers:
            lines.append(f"- Candidate identifiers: {', '.join(self.candidate_identifiers[:12])}")
        if self.search_terms:
            lines.append(f"- Search anchors: {', '.join(self.search_terms[:8])}")
        if self.shape_guidance:
            lines.append(f"- Theorem-shape guidance: {' | '.join(self.shape_guidance[:4])}")
        if self.retrieval_notes:
            lines.append(f"- Notes: {' | '.join(self.retrieval_notes[:4])}")
        if self.runtime_search_plan:
            rendered_plan = [
                f"{directive.tool} `{directive.query}` ({directive.reason})"
                for directive in self.runtime_search_plan[:3]
            ]
            lines.append(f"- Suggested runtime search: {' | '.join(rendered_plan)}")
        if self.mcp_hits:
            for hit in self.mcp_hits[:2]:
                lines.append(f"- MCP {hit.source} query `{hit.query}`: {hit.text}")
        elif self.mcp_skip_reason:
            lines.append(f"- MCP search skipped: {self.mcp_skip_reason}")
        return "\n".join(lines)

    def telemetry(self) -> dict[str, Any]:
        """Return a JSON-serializable retrieval summary."""
        return {
            "selected_preambles": list(self.preamble_names),
            "explicit_preambles": list(self.explicit_preamble_names),
            "auto_preambles": list(self.auto_preamble_names),
            "advisory_preambles": list(self.advisory_preamble_names),
            "selected_preamble_details": list(self.selected_preamble_details),
            "advisory_preamble_details": list(self.advisory_preamble_details),
            "selection_mode": self.selection_mode,
            "retrieval": {
                "source_counts": dict(self.source_counts),
                "candidate_imports": list(self.candidate_imports),
                "candidate_identifiers": list(self.candidate_identifiers),
                "search_terms": list(self.search_terms),
                "shape_guidance": list(self.shape_guidance),
                "notes": list(self.retrieval_notes),
                "runtime_search_plan": [
                    {
                        "tool": directive.tool,
                        "query": directive.query,
                        "reason": directive.reason,
                    }
                    for directive in self.runtime_search_plan
                ],
            },
            "mcp": {
                "requested": self.mcp_requested,
                "enabled": self.mcp_enabled,
                "skip_reason": self.mcp_skip_reason,
                "hits": [
                    {"source": hit.source, "query": hit.query, "text": hit.text}
                    for hit in self.mcp_hits
                ],
            },
        }

    def artifact(
        self,
        *,
        validation_method: str | None = None,
        validation_methods: list[str] | None = None,
        validation_fallback_reasons: list[str] | None = None,
        repair_buckets: list[str] | None = None,
        deterministic_repairs_applied: list[str] | None = None,
        cache_hit: bool = False,
        source: str = "formalizer",
    ) -> dict[str, Any]:
        """Build the structured handoff payload shared across API and prover stages."""
        return {
            "schema_version": 1,
            "cache_hit": cache_hit,
            "source": source,
            "claim_text": self.claim_text,
            "claim_components": list(self.claim_components),
            "selected_preambles": list(self.preamble_names),
            "explicit_preambles": list(self.explicit_preamble_names),
            "auto_preambles": list(self.auto_preamble_names),
            "advisory_preambles": list(self.advisory_preamble_names),
            "selected_preamble_details": list(self.selected_preamble_details),
            "advisory_preamble_details": list(self.advisory_preamble_details),
            "selection_mode": self.selection_mode,
            "preamble_imports": list(self.preamble_imports),
            "candidate_imports": list(self.candidate_imports),
            "candidate_identifiers": list(self.candidate_identifiers),
            "search_terms": list(self.search_terms),
            "shape_guidance": list(self.shape_guidance),
            "retrieval_notes": list(self.retrieval_notes),
            "runtime_search_plan": [
                {
                    "tool": directive.tool,
                    "query": directive.query,
                    "reason": directive.reason,
                }
                for directive in self.runtime_search_plan
            ],
            "retrieval": {
                "source_counts": dict(self.source_counts),
                "mcp_requested": self.mcp_requested,
                "mcp_enabled": self.mcp_enabled,
                "mcp_skip_reason": self.mcp_skip_reason,
                "mcp_hits": [
                    {"source": hit.source, "query": hit.query, "text": hit.text}
                    for hit in self.mcp_hits
                ],
            },
            "validation": {
                "method": validation_method,
                "methods": list(validation_methods or []),
                "fallback_reasons": list(validation_fallback_reasons or []),
            },
            "repairs": {
                "repair_buckets": list(repair_buckets or []),
                "deterministic_repairs_applied": list(deterministic_repairs_applied or []),
            },
        }


CURATED_HINTS: tuple[CuratedHint, ...] = (
    CuratedHint(
        label="concavity",
        keywords=("concave", "strictly concave", "concavity", "convex", "strictly convex"),
        imports=("Mathlib.Analysis.Convex.Basic",),
        identifiers=("ConcaveOn", "StrictConcaveOn", "ConvexOn", "StrictConvexOn"),
        notes=("Use `StrictConcaveOn ℝ s f`, not bare `StrictConcave`.",),
    ),
    CuratedHint(
        label="derivatives",
        keywords=(
            "derivative",
            "deriv",
            "differentiable",
            "marginal product",
            "elasticity",
        ),
        imports=("Mathlib.Analysis.Calculus.Deriv.Basic",),
        identifiers=("HasDerivAt", "deriv", "DifferentiableAt"),
        search_terms=("HasDerivAt", "deriv", "DifferentiableAt"),
        shape_guidance=(
            "Prefer `HasDerivAt f f' x` in theorem statements when the claim is local.",
            "Use `deriv f x` when the English claim names the derivative value directly.",
        ),
        notes=("Prefer `HasDerivAt` for theorem statements over raw `deriv` when possible.",),
    ),
    CuratedHint(
        label="power_functions",
        keywords=("rpow", "power function", "real power", "exponent"),
        imports=(
            "Mathlib.Analysis.SpecialFunctions.Pow.Real",
            "Mathlib.Analysis.SpecialFunctions.Pow.Deriv",
        ),
        identifiers=(
            "Real.rpow",
            "Real.rpow_natCast",
            "Real.hasDerivAt_rpow_const",
        ),
        search_terms=(
            "Real.rpow_natCast",
            "Real.hasDerivAt_rpow_const",
        ),
        shape_guidance=(
            "If the exponent is a known natural number, prefer `x ^ n` over `Real.rpow x n`.",
            "Use `Real.rpow` only when the exponent is genuinely real-valued.",
        ),
        notes=(
            (
                "Power-function claims are less brittle when natural-number "
                "exponents stay in `x ^ n` form."
            ),
            (
                "For derivative lemmas about `Real.rpow`, keep the side "
                "condition such as `x ≠ 0 ∨ 1 ≤ p`."
            ),
        ),
    ),
    CuratedHint(
        label="frechet",
        keywords=("hessian", "frechet", "partial derivative", "gradient"),
        imports=("Mathlib.Analysis.Calculus.FDeriv.Basic",),
        identifiers=("HasFDerivAt", "fderiv"),
        notes=("There is no standalone `hessian`; use `fderiv ℝ (fderiv ℝ f)`.",),
    ),
    CuratedHint(
        label="extreme_value",
        keywords=("maximum", "minimum", "compact", "extreme value", "weierstrass"),
        imports=("Mathlib.Topology.Order.Basic",),
        identifiers=("IsCompact.exists_isMaxOn", "IsCompact.exists_isMinOn"),
        search_terms=("IsCompact.exists_isMaxOn", "IsCompact.exists_isMinOn"),
        shape_guidance=(
            "Use `∃ x ∈ s, IsMaxOn f s x` for maximum claims.",
            "Use `∃ x ∈ s, IsMinOn f s x` for minimum claims.",
        ),
        notes=(
            "Existence theorems usually need `IsCompact`, `ContinuousOn`, "
            "and `Set.Nonempty` hypotheses.",
        ),
    ),
    CuratedHint(
        label="continuity",
        keywords=("continuous", "continuity"),
        imports=("Mathlib.Topology.ContinuousOn",),
        identifiers=("Continuous", "ContinuousOn"),
    ),
    CuratedHint(
        label="compact_continuity",
        keywords=("continuous", "compact", "compact set", "continuous on"),
        imports=(
            "Mathlib.Topology.ContinuousOn",
            "Mathlib.Topology.Order.Basic",
        ),
        identifiers=("Continuous", "ContinuousOn", "IsCompact"),
        search_terms=("ContinuousOn", "IsCompact"),
        shape_guidance=(
            "Compact-set claims usually need both `IsCompact s` and `ContinuousOn f s`.",
            (
                "For existence claims on compact sets, pair continuity facts "
                "with `IsCompact.exists_isMaxOn` or `IsCompact.exists_isMinOn`."
            ),
        ),
        notes=(
            "Reach for `Mathlib.Topology.ContinuousOn` when the claim is local to a set.",
        ),
    ),
    CuratedHint(
        label="metric_fixed_point",
        keywords=("contraction", "fixed point", "complete metric space", "banach"),
        imports=("Mathlib.Topology.MetricSpace.Contracting",),
        identifiers=(
            "ContractingWith",
            "ContractingWith.fixedPoint_isFixedPt",
            "ContractingWith.fixedPoint_unique",
        ),
        search_terms=(
            "ContractingWith.fixedPoint_unique",
            "ContractingWith.fixedPoint_isFixedPt",
        ),
        shape_guidance=("Use `∃! x, f x = x` for unique fixed-point claims.",),
        notes=(
            "For Banach fixed point claims, start from `ContractingWith` and "
            "keep the contraction constant in `NNReal`.",
        ),
    ),
    CuratedHint(
        label="metric_spaces",
        keywords=("metric space", "complete space", "distance"),
        imports=("Mathlib.Topology.MetricSpace.Basic",),
        identifiers=("MetricSpace", "CompleteSpace", "dist"),
    ),
    CuratedHint(
        label="monotone_convergence",
        keywords=("monotone sequence", "bounded above", "converges", "monotone convergence"),
        imports=(
            "Mathlib.Topology.Order.MonotoneConvergence",
            "Mathlib.Topology.Instances.NNReal.Lemmas",
        ),
        identifiers=(
            "Monotone",
            "BddAbove",
            "Filter.Tendsto",
            "Real.tendsto_of_bddAbove_monotone",
            "tendsto_atTop_ciSup",
        ),
        search_terms=(
            "Real.tendsto_of_bddAbove_monotone",
            "tendsto_atTop_ciSup",
        ),
        shape_guidance=(
            "Use a convergence-shaped conclusion such as "
            "`∃ l, Filter.Tendsto u Filter.atTop (nhds l)`.",
        ),
        notes=(
            "Sequence claims usually model `u : ℕ → ℝ` with `Monotone u` "
            "and `BddAbove (Set.range u)` hypotheses.",
        ),
    ),
    CuratedHint(
        label="measure_theory",
        keywords=("measure", "probability", "expectation", "integral"),
        imports=("Mathlib.MeasureTheory.Measure.MeasureSpace",),
        identifiers=("MeasurableSpace", "MeasureSpace", "MeasureTheory.integral"),
        notes=(
            "Measure-theoretic claims are fragile; add `MeasurableSpace` before `MeasureSpace`.",
        ),
    ),
    CuratedHint(
        label="matrix_posdef",
        keywords=("positive definite", "posdef", "matrix"),
        imports=("Mathlib.LinearAlgebra.Matrix.PosDef",),
        identifiers=("Matrix.PosDef", "Matrix.PosSemidef"),
    ),
    CuratedHint(
        label="order_fixed_points",
        keywords=("lattice", "least fixed point", "greatest fixed point", "tarski"),
        imports=("Mathlib.Order.FixedPoints",),
        identifiers=("OrderHom.lfp", "OrderHom.gfp"),
    ),
)


def _dedupe_preserve(values: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        cleaned = value.strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        output.append(cleaned)
    return output


def _matching_curated_hints(claim_text: str) -> list[CuratedHint]:
    normalized = claim_text.lower()
    return [
        hint for hint in CURATED_HINTS if any(keyword in normalized for keyword in hint.keywords)
    ]


def _claim_components(hints: list[CuratedHint]) -> list[str]:
    return [hint.label for hint in hints]


def _search_terms(hints: list[CuratedHint]) -> list[str]:
    anchored_terms = [item for hint in hints for item in hint.search_terms]
    identifier_fallbacks = [item for hint in hints for item in hint.identifiers[:2]]
    label_fallbacks = [hint.label.replace("_", " ") for hint in hints]
    return _dedupe_preserve(anchored_terms + identifier_fallbacks + label_fallbacks)


def _extract_inline_code_spans(text: str) -> list[str]:
    spans: list[str] = []
    current = ""
    in_code = False
    for char in text:
        if char == "`":
            if in_code and current.strip():
                spans.append(current.strip())
            current = ""
            in_code = not in_code
            continue
        if in_code:
            current += char
    return spans


def _build_runtime_search_plan(
    search_terms: list[str],
    candidate_identifiers: list[str],
    shape_guidance: list[str],
) -> list[RuntimeSearchDirective]:
    directives: list[RuntimeSearchDirective] = []
    seen: set[tuple[str, str]] = set()

    def _append(tool: str, query: str, reason: str) -> None:
        cleaned = query.strip()
        key = (tool, cleaned)
        if not cleaned or key in seen:
            return
        seen.add(key)
        directives.append(RuntimeSearchDirective(tool=tool, query=cleaned, reason=reason))

    for query in search_terms[:2]:
        _append(
            "lean_local_search",
            query,
            "Verify the exact declaration name or namespace before proving.",
        )
    for query in candidate_identifiers[:2]:
        _append(
            "lean_loogle",
            query,
            "Inspect theorem signatures or nearby declarations for this identifier.",
        )
    for guidance in shape_guidance[:2]:
        for query in _extract_inline_code_spans(guidance):
            _append(
                "lean_loogle",
                query,
                "Search for a theorem or goal shape matching the intended conclusion.",
            )
            break

    return directives


def _parse_mcp_text(result: Any) -> str:
    content = getattr(result, "content", None)
    if content is None:
        return str(result)
    parts: list[str] = []
    for item in content:
        text = getattr(item, "text", None)
        if text is not None:
            parts.append(text)
        elif isinstance(item, dict) and "text" in item:
            parts.append(str(item["text"]))
    return " ".join(part.strip() for part in parts if part).strip()


async def _query_mcp_hits_async(
    directives: list[RuntimeSearchDirective],
) -> tuple[list[SearchHit], list[str]]:
    hits: list[SearchHit] = []
    errors: list[str] = []
    async with open_lean_mcp_session() as session:
        await prime_lean_mcp_session(session)
        for directive in directives[:MAX_MCP_SEARCH_QUERIES]:
            arguments: dict[str, Any]
            if directive.tool == "lean_local_search":
                arguments = {"query": directive.query, "limit": 5}
            elif directive.tool == "lean_loogle":
                arguments = {"query": directive.query, "num_results": 5}
            else:
                errors.append(f"unsupported directive tool: {directive.tool}")
                continue
            result = await session.call_tool(directive.tool, arguments)
            if getattr(result, "isError", False):
                errors.append(
                    f"{directive.tool} `{directive.query}` failed: {_parse_mcp_text(result)}"
                )
                continue
            text = _parse_mcp_text(result)
            if text:
                hits.append(
                    SearchHit(
                        source=directive.tool,
                        query=directive.query,
                        text=text[:240],
                    )
                )
    return hits, errors


def _query_mcp_hits(
    directives: list[RuntimeSearchDirective],
    *,
    enable_mcp_retrieval: bool,
) -> tuple[list[SearchHit], str | None]:
    if not enable_mcp_retrieval:
        return [], "disabled_by_runtime_policy"
    allowed, reason = formalization_mcp_available(
        capability=FORMALIZATION_MCP_CAPABILITY_RETRIEVAL
    )
    if not allowed:
        return [], reason
    if not FORMALIZATION_MCP_SEARCH_ENABLED:
        return [], "disabled_by_config"
    if not directives:
        return [], "no_runtime_search_plan"

    cache_key = tuple(
        f"{directive.tool}:{directive.query}"
        for directive in directives[:MAX_MCP_SEARCH_QUERIES]
    )
    cached_result = _FORMALIZATION_MCP_SEARCH_CACHE.get(cache_key)
    if cached_result is not None:
        return list(cached_result.hits), cached_result.skip_reason

    try:
        hits, tool_errors = asyncio.run(
            asyncio.wait_for(
                _query_mcp_hits_async(directives),
                timeout=FORMALIZATION_MCP_SEARCH_TIMEOUT_SECONDS,
            )
        )
    except Exception as exc:
        message = str(exc) or exc.__class__.__name__
        mark_formalization_mcp_failure(
            f"MCP retrieval failed: {message}",
            capability=FORMALIZATION_MCP_CAPABILITY_RETRIEVAL,
        )
        return [], message

    if hits or not tool_errors:
        mark_formalization_mcp_success(capability=FORMALIZATION_MCP_CAPABILITY_RETRIEVAL)
    if len(_FORMALIZATION_MCP_SEARCH_CACHE) >= FORMALIZATION_MCP_SEARCH_CACHE_LIMIT:
        oldest_key = next(iter(_FORMALIZATION_MCP_SEARCH_CACHE))
        _FORMALIZATION_MCP_SEARCH_CACHE.pop(oldest_key, None)
    skip_reason = " | ".join(tool_errors[:2]) if tool_errors else None
    _FORMALIZATION_MCP_SEARCH_CACHE[cache_key] = CachedMcpSearchResult(
        hits=tuple(hits),
        skip_reason=skip_reason,
    )
    return hits, skip_reason


def _normalize_formalization_context_preamble_field(
    formalization_context: dict[str, Any],
    field_name: str,
) -> list[str] | None:
    """Validate one preamble-name field inside a pass-through formalization context."""
    if field_name not in formalization_context or formalization_context[field_name] is None:
        return None

    raw_value = formalization_context[field_name]
    if not isinstance(raw_value, list):
        raise ValueError(f"`formalization_context.{field_name}` must be a list of preamble names.")
    if any(not isinstance(item, str) for item in raw_value):
        raise ValueError(f"`formalization_context.{field_name}` must contain only strings.")
    return validate_preamble_names(raw_value)


def normalize_formalization_context_preambles(
    formalization_context: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Normalize only the routing-critical preamble fields inside a formalization context."""
    if formalization_context is None:
        return None

    normalized = dict(formalization_context)
    selected = _normalize_formalization_context_preamble_field(
        normalized,
        "selected_preambles",
    )
    explicit = _normalize_formalization_context_preamble_field(
        normalized,
        "explicit_preambles",
    )
    auto = _normalize_formalization_context_preamble_field(
        normalized,
        "auto_preambles",
    )

    if selected is not None:
        normalized["selected_preambles"] = selected
    if explicit is not None:
        normalized["explicit_preambles"] = explicit
    if auto is not None:
        normalized["auto_preambles"] = auto

    if selected is not None and explicit is not None and selected != explicit:
        raise ValueError(
            "`formalization_context.explicit_preambles` must exactly match "
            "`formalization_context.selected_preambles` when both are provided."
        )

    return normalized


def build_formalization_context(
    claim_text: str,
    explicit_preamble_names: list[str] | None = None,
    *,
    enable_mcp_retrieval: bool = False,
) -> FormalizationContext:
    """Build bounded retrieval context for one formalization request."""
    selection = select_preamble_plan(
        claim_text,
        explicit_preamble_names=explicit_preamble_names,
        auto_limit=MAX_AUTO_PREAMBLES,
    )
    preamble_entries = list(selection.selected_entries)
    selected_preamble_details = [
        serialize_preamble_entry(
            entry,
            selection_role=("explicit" if selection.selection_mode == "explicit" else "auto"),
        )
        for entry in preamble_entries
    ]
    advisory_preamble_details = [
        serialize_preamble_entry(entry, selection_role="advisory")
        for entry in selection.advisory_entries
    ]

    curated_hints = _matching_curated_hints(claim_text)
    preamble_candidate_imports = [
        item for entry in preamble_entries for item in entry.candidate_imports
    ]
    preamble_candidate_identifiers = [
        item for entry in preamble_entries for item in entry.candidate_identifiers
    ]
    preamble_search_terms = [
        item for entry in preamble_entries for item in entry.retrieval_anchors
    ]
    preamble_shape_guidance = [item for entry in preamble_entries for item in entry.theorem_shapes]
    preamble_notes = [item for entry in preamble_entries for item in entry.retrieval_notes]

    candidate_imports = _dedupe_preserve(
        preamble_candidate_imports + [item for hint in curated_hints for item in hint.imports]
    )
    candidate_identifiers = _dedupe_preserve(
        preamble_candidate_identifiers
        + [item for hint in curated_hints for item in hint.identifiers]
    )
    search_terms = _dedupe_preserve(preamble_search_terms + _search_terms(curated_hints))
    shape_guidance = _dedupe_preserve(
        preamble_shape_guidance + [item for hint in curated_hints for item in hint.shape_guidance]
    )
    retrieval_notes = _dedupe_preserve(
        preamble_notes + [item for hint in curated_hints for item in hint.notes]
    )
    runtime_search_plan = _build_runtime_search_plan(
        search_terms,
        candidate_identifiers,
        shape_guidance,
    )
    mcp_hits, mcp_skip_reason = _query_mcp_hits(
        runtime_search_plan,
        enable_mcp_retrieval=enable_mcp_retrieval,
    )

    source_counts = {
        "preamble": len(preamble_entries),
        "curated": len(curated_hints),
        "mcp": len(mcp_hits),
    }
    return FormalizationContext(
        claim_text=claim_text,
        claim_components=_claim_components(curated_hints),
        explicit_preamble_names=list(selection.explicit_preamble_names),
        auto_preamble_names=(
            selection.auto_preamble_names if not selection.explicit_preamble_names else []
        ),
        preamble_names=selection.selected_preamble_names,
        advisory_preamble_names=selection.advisory_preamble_names,
        selected_preamble_details=selected_preamble_details,
        advisory_preamble_details=advisory_preamble_details,
        selection_mode=selection.selection_mode,
        preamble_block=build_preamble_prompt_block(preamble_entries),
        preamble_imports=build_preamble_imports(preamble_entries),
        candidate_imports=candidate_imports,
        candidate_identifiers=candidate_identifiers,
        search_terms=search_terms,
        shape_guidance=shape_guidance,
        retrieval_notes=retrieval_notes,
        runtime_search_plan=runtime_search_plan,
        mcp_hits=mcp_hits,
        mcp_requested=bool(enable_mcp_retrieval),
        mcp_enabled=bool(
            enable_mcp_retrieval
            and FORMALIZATION_MCP_SEARCH_ENABLED
            and (bool(mcp_hits) or mcp_skip_reason is None)
        ),
        mcp_skip_reason=mcp_skip_reason,
        source_counts=source_counts,
    )


def build_explicit_preamble_artifact(
    explicit_preamble_names: list[str],
    *,
    claim_text: str = "",
    source: str = "verify_request",
) -> dict[str, Any]:
    """Build a minimal formalization artifact from explicit preamble intent alone."""
    selection = select_preamble_plan(
        claim_text,
        explicit_preamble_names=explicit_preamble_names,
        auto_limit=MAX_AUTO_PREAMBLES,
    )
    selected_entries = list(selection.selected_entries)
    context = FormalizationContext(
        claim_text=claim_text,
        claim_components=[],
        explicit_preamble_names=list(selection.explicit_preamble_names),
        auto_preamble_names=[],
        preamble_names=selection.selected_preamble_names,
        advisory_preamble_names=selection.advisory_preamble_names,
        selected_preamble_details=[
            serialize_preamble_entry(entry, selection_role="explicit") for entry in selected_entries
        ],
        advisory_preamble_details=[
            serialize_preamble_entry(entry, selection_role="advisory")
            for entry in selection.advisory_entries
        ],
        selection_mode=selection.selection_mode,
        preamble_block=build_preamble_prompt_block(selected_entries),
        preamble_imports=build_preamble_imports(selected_entries),
        candidate_imports=[],
        candidate_identifiers=[],
        search_terms=[],
        shape_guidance=[],
        retrieval_notes=[],
        runtime_search_plan=[],
        mcp_hits=[],
        mcp_requested=False,
        mcp_enabled=False,
        mcp_skip_reason=None,
        source_counts={"preamble": len(selected_entries), "curated": 0, "mcp": 0},
    )
    return context.artifact(source=source)


def merge_explicit_preamble_artifact(
    formalization_context: dict[str, Any] | None,
    *,
    explicit_preamble_names: list[str],
    source: str = "verify_request",
) -> dict[str, Any]:
    """Merge explicit preamble intent into a structured artifact without widening it."""
    explicit_names = validate_preamble_names(list(explicit_preamble_names or []))
    if not explicit_names:
        return dict(formalization_context or {})

    merged = dict(formalization_context or {})
    existing_selected = normalize_preamble_names(
        [
            str(item)
            for item in (
                merged.get("explicit_preambles") or merged.get("selected_preambles") or []
            )
        ]
    )
    if existing_selected and existing_selected != explicit_names:
        raise ValueError(
            "`preamble_names` must exactly match formalization_context.selected_preambles "
            "when both are provided."
        )

    merged.setdefault("schema_version", 1)
    merged.setdefault("source", source)
    merged.setdefault("claim_text", "")
    merged.setdefault("claim_components", [])
    selection = select_preamble_plan(
        merged.get("claim_text", ""),
        explicit_preamble_names=explicit_names,
        auto_limit=MAX_AUTO_PREAMBLES,
    )
    merged["selected_preambles"] = list(selection.selected_preamble_names)
    merged["explicit_preambles"] = list(selection.explicit_preamble_names)
    merged["selection_mode"] = selection.selection_mode
    merged["selected_preamble_details"] = [
        serialize_preamble_entry(entry, selection_role="explicit")
        for entry in selection.selected_entries
    ]
    merged["advisory_preamble_details"] = [
        serialize_preamble_entry(entry, selection_role="advisory")
        for entry in selection.advisory_entries
    ]
    merged.setdefault("candidate_imports", [])
    merged.setdefault("candidate_identifiers", [])
    merged.setdefault("search_terms", [])
    merged.setdefault("shape_guidance", [])
    merged.setdefault("retrieval_notes", [])
    merged.setdefault("runtime_search_plan", [])
    merged.setdefault(
        "retrieval",
        {
            "source_counts": {},
            "mcp_requested": False,
            "mcp_enabled": False,
            "mcp_skip_reason": None,
            "mcp_hits": [],
        },
    )
    merged.setdefault("validation", {"method": None, "methods": [], "fallback_reasons": []})
    merged.setdefault(
        "repairs",
        {"repair_buckets": [], "deterministic_repairs_applied": []},
    )

    artifact = build_explicit_preamble_artifact(
        explicit_names,
        claim_text=str(merged.get("claim_text") or ""),
        source=str(merged.get("source") or source),
    )
    merged["selected_preambles"] = artifact["selected_preambles"]
    merged["explicit_preambles"] = artifact["explicit_preambles"]
    merged["auto_preambles"] = []
    merged["advisory_preambles"] = artifact["advisory_preambles"]
    merged["selection_mode"] = "explicit"
    merged["preamble_imports"] = artifact["preamble_imports"]
    retrieval = dict(merged.get("retrieval") or {})
    source_counts = dict(retrieval.get("source_counts") or {})
    source_counts["preamble"] = len(explicit_names)
    retrieval["source_counts"] = source_counts
    merged["retrieval"] = retrieval
    return merged
