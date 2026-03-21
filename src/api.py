"""
FastAPI service wrapper for the LeanEcon pipeline.

This module exposes a frontend-friendly, multi-step API:
  - GET  /health
  - POST /api/v1/classify
  - POST /api/v1/formalize
  - POST /api/v1/verify      (async, returns 202 + job_id)
  - GET  /api/v1/jobs/{job_id}
  - POST /api/v1/explain

Legacy unversioned routes (/api/classify, /api/formalize, /api/verify) are
preserved as deprecated redirects for backward compatibility.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field

# Allow sibling imports such as `from pipeline import ...` to resolve when the
# app is launched via `uvicorn src.api:app`.
sys.path.insert(0, str(Path(__file__).parent))

from error_codes import LeanEconErrorCode
from explainer import explain_result
from formalizer import classify_claim
from job_store import JobStatus, job_store
from pipeline import formalize_claim, parse_claim, run_pipeline

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
3. Optionally let a user or agent edit the theorem text.
4. `POST /api/v1/verify` with the formalized theorem — returns HTTP 202 and a
   `job_id`. Poll `GET /api/v1/jobs/{job_id}` until status is `completed` or `failed`.

Important behavior:

- `classify` short-circuits raw Lean input and marks it as `RAW_LEAN`.
- `formalize` preserves the current pipeline behavior, including raw-Lean bypass.
- `verify` expects a formalized Lean theorem/lemma/example with a `sorry`
  placeholder so the prover has something to complete.
- `agentic` is the only supported prover mode.
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

app = FastAPI(
    title="LeanEcon API",
    version="1.0.0",
    summary="Lean-backed theorem verification API",
    description=API_DESCRIPTION,
    openapi_tags=OPENAPI_TAGS,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

router = APIRouter(prefix="/api/v1", tags=["v1"])


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
                "prover_mode": "agentic",
                "explain": False,
            }
        }
    )

    theorem_code: str = Field(
        ...,
        description=(
            "Formalized Lean theorem file content that still contains `sorry`."
        ),
    )
    prover_mode: Literal["agentic"] = Field(
        default="agentic",
        description="Proof backend to use. Currently only 'agentic' is supported.",
    )
    explain: bool = Field(
        default=False,
        description="Include a natural language explanation in the job result.",
    )


class ExplainRequest(BaseModel):
    """Request body for the explain endpoint."""

    original_claim: str = Field(..., description="The user's original input.")
    theorem_code: str | None = Field(
        default=None, description="Formalized theorem (if available)."
    )
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

    cleaned_claim: str = Field(
        description="Normalized claim text after lightweight cleaning."
    )
    category: Literal["RAW_LEAN", "ALGEBRAIC", "DEFINABLE", "REQUIRES_DEFINITIONS"] = Field(
        description="High-level claim class used to decide whether to continue."
    )
    formalizable: bool = Field(
        description="Whether the current claim appears in scope for formalization."
    )
    reason: str | None = Field(
        default=None,
        description="Reason for rejection when the claim needs missing definitions.",
    )
    is_raw_lean: bool = Field(
        description="Whether the input already looked like Lean code."
    )
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
            "If empty, auto-detected from the classifier for DEFINABLE claims."
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
    errors: list[str] = Field(
        description="Lean errors from the last failed formalization attempt."
    )
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
                "prover_mode": "agentic",
                "error_code": "none",
                "explanation": None,
                "explanation_generated": None,
            }
        }
    )

    success: bool = Field(description="Whether Lean accepted the final proof.")
    lean_code: str = Field(
        description="Final Lean file content returned by the verification run."
    )
    errors: list[str] = Field(description="Lean verification errors, if any.")
    warnings: list[str] = Field(description="Lean warnings emitted during verification.")
    proof_strategy: str = Field(
        description="High-level proof plan reported by the proving stage."
    )
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
    elapsed_seconds: float = Field(
        description="Total wall-clock time reported by the pipeline."
    )
    prover_mode: Literal["agentic"] = Field(
        description="Proof backend used for the request."
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


class ExplainResponse(BaseModel):
    """Natural language explanation of pipeline results."""

    explanation: str = Field(description="Markdown-formatted explanation.")
    generated: bool = Field(
        description="True if LLM generated, False if fallback."
    )
    error_code: LeanEconErrorCode = Field(
        default=LeanEconErrorCode.NONE,
        description="Machine-readable error code.",
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


def _formalize_error_code(result: dict) -> LeanEconErrorCode:
    """Choose the right error code for a failed formalization result."""
    if not result.get("formalization_failed"):
        return LeanEconErrorCode.NONE
    reason = (result.get("failure_reason") or "").lower()
    if any(kw in reason for kw in ("unformalizable", "not supported", "requires", "definition")):
        return LeanEconErrorCode.FORMALIZATION_UNFORMALIZABLE
    return LeanEconErrorCode.FORMALIZATION_FAILED


def _verify_error_code(result: dict) -> LeanEconErrorCode:
    """Choose the right error code for a completed pipeline result."""
    if result.get("success"):
        return LeanEconErrorCode.NONE
    lean_code = result.get("lean_code", "")
    if lean_code and "sorry" in lean_code:
        return LeanEconErrorCode.VERIFICATION_SORRY
    if result.get("proof_generated") is False:
        return LeanEconErrorCode.PROOF_NOT_FOUND
    return LeanEconErrorCode.VERIFICATION_REJECTED


# ---------------------------------------------------------------------------
# Background task
# ---------------------------------------------------------------------------

def _run_verify_job(job_id: str, theorem_code: str, prover_mode: str, explain: bool) -> None:
    """Background task that runs the full pipeline and stores the result."""
    job_store.update_status(job_id, JobStatus.RUNNING)
    try:
        result = run_pipeline(
            raw_input=theorem_code,
            preformalized_theorem=theorem_code,
            prover_mode=prover_mode,
        )
        error_code = _verify_error_code(result)
        response_data: dict[str, Any] = {
            "prover_mode": prover_mode,
            "error_code": error_code,
            **result,
        }
        if explain:
            expl = explain_result(
                original_claim=theorem_code,
                theorem_code=theorem_code,
                verification_result=result,
            )
            response_data["explanation"] = expl["explanation"]
            response_data["explanation_generated"] = expl["generated"]
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
        )

    try:
        cleaned_claim = parse_claim(raw_claim)["text"]
        if not cleaned_claim:
            raise HTTPException(
                status_code=422,
                detail="`raw_claim` must contain non-empty content after cleaning.",
            )

        classification = classify_claim(cleaned_claim)
        is_rejected = classification["category"] == "REQUIRES_DEFINITIONS"
        formalizable = not is_rejected  # ALGEBRAIC and DEFINABLE are both formalizable
        return ClassifyResponse(
            cleaned_claim=cleaned_claim,
            category=classification["category"],
            formalizable=formalizable,
            reason=classification["reason"],
            is_raw_lean=False,
            error_code=LeanEconErrorCode.CLASSIFICATION_REJECTED if is_rejected else LeanEconErrorCode.NONE,
            definitions_needed=classification.get("definitions_needed"),
            preamble_matches=classification.get("preamble_matches", []),
            suggested_reformulation=classification.get("suggested_reformulation"),
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
        "Optionally accepts `preamble_names` to inject known definitions."
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
        error_code = _formalize_error_code(result)
        return FormalizeResponse(error_code=error_code, **result)
    except HTTPException:
        raise
    except Exception as exc:
        raise _server_error("Claim formalization failed", exc) from exc


@router.post(
    "/verify",
    response_model=VerifyAcceptedResponse,
    status_code=202,
    summary="Verify a formalized theorem (async)",
    description=(
        "Queue a proving and Lean verification job. Returns HTTP 202 with a `job_id` "
        "immediately. Poll `GET /api/v1/jobs/{job_id}` until status is `completed` "
        "or `failed`. Only `agentic` prover mode is supported."
    ),
    responses={
        202: {"description": "Job queued successfully."},
        422: {
            "description": (
                "The theorem payload was blank, did not look like a Lean proof stub, "
                "or an unsupported prover_mode was specified."
            )
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

    job_id = job_store.create(
        {"theorem_code": theorem_code, "prover_mode": request.prover_mode, "explain": request.explain}
    )
    background_tasks.add_task(
        _run_verify_job, job_id, theorem_code, request.prover_mode, request.explain
    )
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
        result = explain_result(
            original_claim=original_claim,
            theorem_code=request.theorem_code or "",
            verification_result=v_result,
        )
        return ExplainResponse(
            explanation=result["explanation"],
            generated=result["generated"],
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Explanation failed: {exc}") from exc


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
def verify_legacy(request: VerifyRequest, background_tasks: BackgroundTasks) -> VerifyAcceptedResponse:
    return verify_endpoint(request, background_tasks)


# ---------------------------------------------------------------------------
# Register router
# ---------------------------------------------------------------------------

app.include_router(router)
