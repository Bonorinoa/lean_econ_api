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
    build_preamble_block,
    build_preamble_imports,
    get_preamble_entries,
    rank_matching_preambles,
)

FORMALIZATION_MCP_SEARCH_ENABLED = os.environ.get(
    "LEANECON_ENABLE_FORMALIZATION_MCP_SEARCH", "0"
).strip().lower() in {"1", "true", "yes", "on"}
FORMALIZATION_MCP_SEARCH_TIMEOUT_SECONDS = float(
    os.environ.get("LEANECON_FORMALIZATION_MCP_SEARCH_TIMEOUT_SECONDS", "5")
)
MAX_MCP_SEARCH_QUERIES = int(os.environ.get("LEANECON_FORMALIZATION_MCP_SEARCH_QUERIES", "2"))
MAX_AUTO_PREAMBLES = int(os.environ.get("LEANECON_FORMALIZATION_AUTO_PREAMBLES", "2"))


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


@dataclass
class FormalizationContext:
    """Structured prompt context for theorem-stub generation."""

    claim_text: str
    claim_components: list[str]
    explicit_preamble_names: list[str] = field(default_factory=list)
    auto_preamble_names: list[str] = field(default_factory=list)
    preamble_names: list[str] = field(default_factory=list)
    preamble_block: str = ""
    preamble_imports: list[str] = field(default_factory=list)
    candidate_imports: list[str] = field(default_factory=list)
    candidate_identifiers: list[str] = field(default_factory=list)
    search_terms: list[str] = field(default_factory=list)
    shape_guidance: list[str] = field(default_factory=list)
    retrieval_notes: list[str] = field(default_factory=list)
    mcp_hits: list[SearchHit] = field(default_factory=list)
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
        if self.preamble_names:
            lines.append(f"- Matching preambles: {', '.join(self.preamble_names)}")
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
            "retrieval": {
                "source_counts": dict(self.source_counts),
                "candidate_imports": list(self.candidate_imports),
                "candidate_identifiers": list(self.candidate_identifiers),
                "search_terms": list(self.search_terms),
                "shape_guidance": list(self.shape_guidance),
                "notes": list(self.retrieval_notes),
            },
            "mcp": {
                "enabled": self.mcp_enabled,
                "skip_reason": self.mcp_skip_reason,
                "hits": [
                    {"source": hit.source, "query": hit.query, "text": hit.text}
                    for hit in self.mcp_hits
                ],
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
        keywords=("derivative", "deriv", "marginal product", "elasticity"),
        imports=("Mathlib.Analysis.Calculus.Deriv.Basic",),
        identifiers=("HasDerivAt", "deriv", "DifferentiableAt"),
        notes=("Prefer `HasDerivAt` for theorem statements over raw `deriv` when possible.",),
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
        imports=("Mathlib.Topology.ContinuousFunction.Basic",),
        identifiers=("Continuous", "ContinuousOn"),
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


async def _query_mcp_hits_async(search_terms: list[str]) -> list[SearchHit]:
    hits: list[SearchHit] = []
    async with open_lean_mcp_session() as session:
        await prime_lean_mcp_session(session)
        for query in search_terms[:MAX_MCP_SEARCH_QUERIES]:
            result = await session.call_tool("lean_local_search", {"query": query, "limit": 5})
            if getattr(result, "isError", False):
                raise RuntimeError(_parse_mcp_text(result))
            text = _parse_mcp_text(result)
            if text:
                hits.append(SearchHit(source="lean_local_search", query=query, text=text[:240]))
    return hits


def _query_mcp_hits(search_terms: list[str]) -> tuple[list[SearchHit], str | None]:
    allowed, reason = formalization_mcp_available(
        capability=FORMALIZATION_MCP_CAPABILITY_RETRIEVAL
    )
    if not allowed:
        return [], reason
    if not FORMALIZATION_MCP_SEARCH_ENABLED:
        return [], "disabled_by_config"
    if not search_terms:
        return [], "no_search_terms"

    try:
        hits = asyncio.run(
            asyncio.wait_for(
                _query_mcp_hits_async(search_terms),
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

    mark_formalization_mcp_success(capability=FORMALIZATION_MCP_CAPABILITY_RETRIEVAL)
    return hits, None


def build_formalization_context(
    claim_text: str,
    explicit_preamble_names: list[str] | None = None,
) -> FormalizationContext:
    """Build bounded retrieval context for one formalization request."""
    explicit_names = _dedupe_preserve(list(explicit_preamble_names or []))
    auto_names: list[str] = []
    if not explicit_names:
        ranked_auto_matches = rank_matching_preambles(claim_text, auto=True)
        auto_names = [entry.name for entry, _score in ranked_auto_matches[:MAX_AUTO_PREAMBLES]]
    preamble_names = explicit_names or auto_names
    preamble_entries = get_preamble_entries(preamble_names)

    curated_hints = _matching_curated_hints(claim_text)
    candidate_imports = _dedupe_preserve([item for hint in curated_hints for item in hint.imports])
    candidate_identifiers = _dedupe_preserve(
        [item for hint in curated_hints for item in hint.identifiers]
    )
    search_terms = _search_terms(curated_hints)
    shape_guidance = _dedupe_preserve(
        [item for hint in curated_hints for item in hint.shape_guidance]
    )
    retrieval_notes = _dedupe_preserve([item for hint in curated_hints for item in hint.notes])
    mcp_hits, mcp_skip_reason = _query_mcp_hits(search_terms)

    source_counts = {
        "preamble": len(preamble_entries),
        "curated": len(curated_hints),
        "mcp": len(mcp_hits),
    }
    return FormalizationContext(
        claim_text=claim_text,
        claim_components=_claim_components(curated_hints),
        explicit_preamble_names=explicit_names,
        auto_preamble_names=auto_names if not explicit_names else [],
        preamble_names=[entry.name for entry in preamble_entries],
        preamble_block=build_preamble_block(preamble_entries),
        preamble_imports=build_preamble_imports(preamble_entries),
        candidate_imports=candidate_imports,
        candidate_identifiers=candidate_identifiers,
        search_terms=search_terms,
        shape_guidance=shape_guidance,
        retrieval_notes=retrieval_notes,
        mcp_hits=mcp_hits,
        mcp_enabled=bool(FORMALIZATION_MCP_SEARCH_ENABLED and not mcp_skip_reason),
        mcp_skip_reason=mcp_skip_reason,
        source_counts=source_counts,
    )
