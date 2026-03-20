"""
FastAPI service wrapper for the LeanEcon pipeline.

This module exposes a frontend-friendly, multi-step API:
  - POST /api/classify
  - POST /api/formalize
  - POST /api/verify
  - GET /health
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# Allow sibling imports such as `from pipeline import ...` to resolve when the
# app is launched via `uvicorn src.api:app`.
sys.path.insert(0, str(Path(__file__).parent))

from formalizer import classify_claim
from pipeline import formalize_claim, parse_claim, run_pipeline

app = FastAPI(
    title="LeanEcon API",
    version="0.1.0",
    description=(
        "Headless API for classifying, formalizing, and verifying mathematical "
        "claims with Lean 4."
    ),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class ClaimRequest(BaseModel):
    """Request body for raw-claim endpoints."""

    raw_claim: str = Field(..., description="Plain text, LaTeX, or raw Lean 4 input.")


class VerifyRequest(BaseModel):
    """Request body for proof verification."""

    theorem_code: str = Field(
        ...,
        description="Formalized Lean theorem file content that still contains `sorry`.",
    )
    prover_mode: Literal["batch", "agentic"] = Field(
        default="agentic",
        description="Proof backend to use for the proving stage.",
    )


class HealthResponse(BaseModel):
    """Liveness response."""

    status: Literal["ok"]


class ClassifyResponse(BaseModel):
    """Frontend-oriented claim classification response."""

    cleaned_claim: str
    category: str
    formalizable: bool
    reason: str | None = None
    is_raw_lean: bool


class FormalizeResponse(BaseModel):
    """Direct API shape for the formalization stage."""

    success: bool
    theorem_code: str
    attempts: int
    errors: list[str]
    formalization_failed: bool
    failure_reason: str | None = None


class VerifyResponse(BaseModel):
    """API response for the prove-and-verify stage."""

    success: bool
    lean_code: str
    errors: list[str]
    warnings: list[str]
    proof_strategy: str
    proof_tactics: str
    theorem_statement: str
    formalization_attempts: int
    formalization_failed: bool
    failure_reason: str | None = None
    output_lean: str | None = None
    proof_generated: bool
    phase: str
    elapsed_seconds: float
    prover_mode: Literal["batch", "agentic"]


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


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Simple liveness endpoint for local/dev tooling and container checks."""
    return HealthResponse(status="ok")


@app.post("/api/classify", response_model=ClassifyResponse)
def classify_endpoint(request: ClaimRequest) -> ClassifyResponse:
    """
    Determine whether the input looks formalizable before running the full pipeline.
    """
    raw_claim = _require_non_empty(request.raw_claim, "raw_claim")

    if _is_raw_lean_input(raw_claim):
        return ClassifyResponse(
            cleaned_claim=raw_claim,
            category="RAW_LEAN",
            formalizable=True,
            reason=None,
            is_raw_lean=True,
        )

    try:
        cleaned_claim = parse_claim(raw_claim)["text"]
        if not cleaned_claim:
            raise HTTPException(
                status_code=422,
                detail="`raw_claim` must contain non-empty content after cleaning.",
            )

        classification = classify_claim(cleaned_claim)
        return ClassifyResponse(
            cleaned_claim=cleaned_claim,
            category=classification["category"],
            formalizable=classification["category"] != "REQUIRES_DEFINITIONS",
            reason=classification["reason"],
            is_raw_lean=False,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise _server_error("Claim classification failed", exc) from exc


@app.post("/api/formalize", response_model=FormalizeResponse)
def formalize_endpoint(request: ClaimRequest) -> FormalizeResponse:
    """Formalize natural-language or LaTeX claims into Lean 4 theorem code."""
    raw_claim = _require_non_empty(request.raw_claim, "raw_claim")

    try:
        result = formalize_claim(raw_claim)
        return FormalizeResponse(**result)
    except HTTPException:
        raise
    except Exception as exc:
        raise _server_error("Claim formalization failed", exc) from exc


@app.post("/api/verify", response_model=VerifyResponse)
def verify_endpoint(request: VerifyRequest) -> VerifyResponse:
    """Prove and verify a pre-formalized Lean theorem using the selected backend."""
    theorem_code = _require_non_empty(request.theorem_code, "theorem_code")
    if not _looks_like_formalized_theorem(theorem_code):
        raise HTTPException(
            status_code=422,
            detail=(
                "`theorem_code` must be a Lean theorem/lemma/example with a "
                "`:= by sorry` proof stub."
            ),
        )

    try:
        result = run_pipeline(
            raw_input=theorem_code,
            preformalized_theorem=theorem_code,
            prover_mode=request.prover_mode,
        )
        return VerifyResponse(prover_mode=request.prover_mode, **result)
    except HTTPException:
        raise
    except Exception as exc:
        raise _server_error("Pipeline verification failed", exc) from exc
