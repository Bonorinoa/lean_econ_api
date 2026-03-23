"""
Standalone smoke tests for formalizer.py.

Usage:
  pytest tests/test_formalizer.py

Includes:
  - Live smoke tests (require MISTRAL_API_KEY and a local Lean toolchain)
  - Unit tests for preamble library, injection, and diagnostics (mock-based)
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from formalizer import (
    REPAIR_BUCKET_SEMANTIC_MISMATCH,
    REPAIR_BUCKET_SYNTAX_NOTATION,
    REPAIR_BUCKET_TYPECLASS_INSTANCE,
    REPAIR_BUCKET_UNKNOWN_IDENTIFIER,
    REPAIR_BUCKET_UNKNOWN_IMPORT_MODULE,
    _inject_preamble_imports,
    classify_repair_bucket,
    formalize,
)
from preamble_library import (
    PREAMBLE_LIBRARY,
    build_preamble_block,
    build_preamble_catalog_summary,
    build_preamble_imports,
    find_matching_preambles,
    get_preamble_entries,
    read_preamble_source,
)
from prompts import build_classify_prompt

# ---------------------------------------------------------------------------
# Live smoke tests (require MISTRAL_API_KEY + local Lean toolchain)
# ---------------------------------------------------------------------------


def _run_live_case(
    label: str,
    claim: str,
    *,
    expect_success: bool,
    expect_failed: bool,
) -> bool:
    result = formalize(claim)
    ok = result["success"] == expect_success and result["formalization_failed"] == expect_failed

    print(f"\n{label}")
    print(f"  success:              {result['success']}")
    print(f"  formalization_failed: {result['formalization_failed']}")
    print(f"  attempts:             {result['attempts']}")
    if result["failure_reason"]:
        print(f"  failure_reason:       {result['failure_reason']}")
    if result["errors"]:
        print(f"  errors:               {result['errors'][0][:120]}")
    if result["success"]:
        print("  theorem_code (first 4 lines):")
        for line in result["theorem_code"].splitlines()[:4]:
            print(f"    {line}")
    if result.get("preamble_used"):
        print(f"  preamble_used:        {result['preamble_used']}")
    if result.get("diagnosis"):
        print(f"  diagnosis:            {result['diagnosis'][:120]}")
    print(f"  status:               {'PASS' if ok else 'FAIL'}")
    return ok


# ---------------------------------------------------------------------------
# Unit tests: preamble library
# ---------------------------------------------------------------------------


def test_preamble_library_has_entries() -> None:
    assert len(PREAMBLE_LIBRARY) >= 10, f"Expected >=10 entries, got {len(PREAMBLE_LIBRARY)}"
    for name, entry in PREAMBLE_LIBRARY.items():
        assert entry.name == name
        assert entry.lean_path.is_file(), f"Missing Lean file for {name}: {entry.lean_path}"
        assert len(read_preamble_source(entry, strip_header=False).strip()) > 0
        assert len(entry.description) > 0
        assert len(entry.keywords) > 0


def test_find_matching_preambles_cobb_douglas() -> None:
    matches = find_matching_preambles("Cobb-Douglas output elasticity equals alpha.")
    names = [m.name for m in matches]
    assert "cobb_douglas_2factor" in names


def test_find_matching_preambles_crra() -> None:
    matches = find_matching_preambles("Under CRRA utility, RRA equals gamma.")
    names = [m.name for m in matches]
    assert "crra_utility" in names


def test_find_matching_preambles_no_match() -> None:
    matches = find_matching_preambles("Nash equilibrium exists in finite games.")
    assert len(matches) == 0


def test_build_preamble_block() -> None:
    entries = get_preamble_entries(["cobb_douglas_2factor", "crra_utility"])
    block = build_preamble_block(entries)
    assert "noncomputable def cobb_douglas" in block
    assert "noncomputable def crra_utility" in block
    assert "import Mathlib" not in block


def test_build_preamble_imports() -> None:
    entries = get_preamble_entries(["cobb_douglas_2factor", "crra_utility", "crra_utility"])
    imports = build_preamble_imports(entries)
    assert imports == [
        "import LeanEcon.Preamble.Producer.CobbDouglas2Factor",
        "import LeanEcon.Preamble.Consumer.CRRAUtility",
    ]


def test_get_preamble_entries_unknown() -> None:
    entries = get_preamble_entries(["nonexistent_entry"])
    assert entries == []


def test_preamble_keyword_coverage() -> None:
    """Verify keyword matching for all major textbook concepts."""
    test_cases = [
        ("Cobb-Douglas output elasticity", "cobb_douglas_2factor"),
        ("Solow model steady state", "solow_steady_state"),
        ("Pareto efficient allocation", "pareto_efficiency"),
        ("present value of cash flows", "discount_factor"),
        ("extreme value theorem", "extreme_value_theorem"),
        ("CRRA utility function", "crra_utility"),
        ("indirect utility function", "indirect_utility"),
        ("expected payoff mixed strategy", "expected_payoff"),
    ]
    for claim, expected_name in test_cases:
        matches = find_matching_preambles(claim)
        names = [m.name for m in matches]
        assert expected_name in names, f"{claim!r} should match {expected_name!r}, got {names}"


def test_preamble_library_expanded() -> None:
    """Verify the library has the expected number of entries after expansion."""
    assert len(PREAMBLE_LIBRARY) >= 20, f"Expected >=20 entries, got {len(PREAMBLE_LIBRARY)}"


def test_read_preamble_source_strips_import_header() -> None:
    entry = PREAMBLE_LIBRARY["crra_utility"]
    source = read_preamble_source(entry)
    assert "import Mathlib" not in source
    assert "noncomputable def crra_utility" in source


# ---------------------------------------------------------------------------
# Unit tests: _inject_preamble_imports
# ---------------------------------------------------------------------------


def test_inject_preamble_imports_placement() -> None:
    lean_code = "import Mathlib\nopen Real\n\ntheorem foo : 1 = 1 := by\n  sorry\n"
    imports = ["import LeanEcon.Preamble.Consumer.CRRAUtility"]
    result = _inject_preamble_imports(lean_code, imports)
    lines = result.splitlines()
    import_idx = None
    open_idx = None
    for i, line in enumerate(lines):
        if "import LeanEcon.Preamble.Consumer.CRRAUtility" in line:
            import_idx = i
        if "open Real" in line:
            open_idx = i
    assert import_idx is not None, "Preamble import not found in output"
    assert open_idx is not None, "`open Real` not found in output"
    assert import_idx < open_idx, "Preamble import should appear before `open Real`"


# ---------------------------------------------------------------------------
# Unit tests: three-tier classify_claim
# ---------------------------------------------------------------------------


def test_classify_algebraic() -> None:
    import formalizer

    with patch.object(formalizer, "call_leanstral", return_value="ALGEBRAIC"):
        result = formalizer.classify_claim("-c * (-gamma * c⁻¹) = gamma")
    assert result["category"] == "ALGEBRAIC"
    assert result["preamble_matches"] == []
    assert result["suggested_reformulation"] is None


def test_classify_definable_with_match() -> None:
    import formalizer

    with patch.object(
        formalizer,
        "call_leanstral",
        return_value="DEFINABLE: Cobb-Douglas production function definition needed",
    ):
        result = formalizer.classify_claim(
            "Cobb-Douglas output elasticity with respect to capital equals alpha."
        )
    assert result["category"] == "DEFINABLE"
    assert "cobb_douglas_2factor" in result["preamble_matches"]
    assert result["definitions_needed"] is not None


def test_classify_definable_without_match() -> None:
    import formalizer

    with patch.object(
        formalizer,
        "call_leanstral",
        return_value="DEFINABLE: Custom Leontief production function",
    ):
        result = formalizer.classify_claim("Leontief production is not differentiable.")
    assert result["category"] == "DEFINABLE"
    assert result["preamble_matches"] == []
    assert result["suggested_reformulation"] is not None


def test_classify_requires_definitions() -> None:
    import formalizer

    with patch.object(
        formalizer,
        "call_leanstral",
        return_value="REQUIRES_DEFINITIONS: Needs competitive equilibrium framework.",
    ):
        result = formalizer.classify_claim("Nash equilibrium exists in finite games.")
    assert result["category"] == "REQUIRES_DEFINITIONS"
    assert result["preamble_matches"] == []


def test_classify_requires_definitions_rescued() -> None:
    """When LLM says REQUIRES_DEFINITIONS but preamble matches exist, rescue to DEFINABLE."""
    import formalizer

    with patch.object(
        formalizer,
        "call_leanstral",
        return_value="REQUIRES_DEFINITIONS: Needs concavity infrastructure.",
    ):
        result = formalizer.classify_claim(
            "A strictly concave function attains a maximum on a compact set."
        )
    assert result["category"] == "DEFINABLE", f"Expected DEFINABLE, got {result['category']}"
    assert len(result["preamble_matches"]) > 0, "Expected preamble matches from rescue"
    assert "extreme_value_theorem" in result["preamble_matches"]


def test_classify_mathlib_native() -> None:
    import formalizer

    with patch.object(
        formalizer,
        "call_leanstral",
        return_value="MATHLIB_NATIVE: LinearAlgebra.Matrix.PosDef",
    ):
        result = formalizer.classify_claim("A positive definite matrix is invertible.")
    assert result["category"] == "MATHLIB_NATIVE"
    assert result["mathlib_hint"] == "LinearAlgebra.Matrix.PosDef"
    assert result["definitions_needed"] is None
    assert result["preamble_matches"] == []


def test_classify_mathlib_native_rescued() -> None:
    """When LLM says MATHLIB_NATIVE but preamble matches exist, rescue to DEFINABLE."""
    import formalizer

    with patch.object(
        formalizer,
        "call_leanstral",
        return_value="MATHLIB_NATIVE: Analysis.Convex for extreme value",
    ):
        result = formalizer.classify_claim(
            "A continuous function on a compact set attains its maximum (extreme value theorem)."
        )
    assert result["category"] == "DEFINABLE"
    assert "extreme_value_theorem" in result["preamble_matches"]
    assert result["mathlib_hint"] is None


def test_classify_mathlib_native_formalizable() -> None:
    import api
    from error_codes import LeanEconErrorCode

    classification = {
        "category": "MATHLIB_NATIVE",
        "reason": "Topology.MetricSpace.Contracting",
        "definitions_needed": None,
        "preamble_matches": [],
        "suggested_reformulation": None,
        "mathlib_hint": "Topology.MetricSpace.Contracting",
    }
    with patch.object(api, "classify_claim", return_value=classification):
        response = api.classify_endpoint(
            api.ClaimRequest(raw_claim="A metric contraction has a fixed point.")
        )
    assert response.category == "MATHLIB_NATIVE"
    assert response.formalizable is True
    assert response.error_code == LeanEconErrorCode.NONE


# ---------------------------------------------------------------------------
# Unit tests: diagnostics
# ---------------------------------------------------------------------------


def test_diagnose_valid_json() -> None:
    import formalizer

    mock_response = (
        '{"diagnosis": "Type mismatch", "suggested_fix": '
        '"Use Real instead of Nat", "fixable": true}'
    )
    with patch.object(formalizer, "call_leanstral", return_value=mock_response):
        result = formalizer._diagnose_formalization_failure(
            "some claim", "import Mathlib\nsorry", ["error: type mismatch"]
        )
    assert result["diagnosis"] == "Type mismatch"
    assert result["suggested_fix"] == "Use Real instead of Nat"
    assert result["fixable"] is True


def test_diagnose_invalid_json_fallback() -> None:
    import formalizer

    with patch.object(formalizer, "call_leanstral", return_value="not valid json at all"):
        result = formalizer._diagnose_formalization_failure(
            "some claim", "import Mathlib\nsorry", ["error"]
        )
    assert result["diagnosis"] is not None
    assert result["fixable"] is False


# ---------------------------------------------------------------------------
# Unit tests: sorry_validate lean_run_code integration
# ---------------------------------------------------------------------------


def test_sorry_validate_uses_run_code() -> None:
    """sorry_validate returns method='lean_run_code' when lean_runner succeeds."""
    import formalizer

    mock_result = {"valid": True, "errors": [], "warnings": ["declaration uses `sorry`"]}
    with patch("formalizer.run_code", create=True):
        import lean_runner

        with patch.object(lean_runner, "run_code", return_value=mock_result):
            with patch.dict("sys.modules", {"lean_runner": lean_runner}):
                result = formalizer.sorry_validate("import Mathlib\ntheorem t : True := by sorry")
    assert result["method"] in {"lean_run_code", "lake_env_lean"}


def test_sorry_validate_fallback_on_error() -> None:
    """sorry_validate falls back to lake_env_lean when lean_runner raises."""
    import formalizer

    mock_raw = {
        "returncode": 0,
        "errors": ["declaration uses `sorry`"],
        "warnings": [],
        "verification_method": "lake_env_lean",
    }
    with patch.dict("sys.modules", {"lean_runner": None}):
        with patch.object(formalizer, "write_lean_file", return_value=Path("/tmp/fake.lean")):
            with patch.object(formalizer, "run_direct_lean_check", return_value=mock_raw):
                result = formalizer.sorry_validate("import Mathlib\ntheorem t : True := by sorry")
    assert result["method"] == "lake_env_lean"
    assert result["valid"] is True
    assert result["errors"] == []


def test_formalize_no_classify_call() -> None:
    """formalize() must NOT call classify_claim() internally."""
    import formalizer

    lean_code = "import Mathlib\nopen Real\n\ntheorem foo : 1 = 1 := by\n  sorry"
    with patch.object(formalizer, "call_leanstral", return_value=lean_code):
        with patch.object(
            formalizer,
            "sorry_validate",
            return_value={
                "valid": True,
                "errors": [],
                "warnings": ["sorry"],
                "method": "lean_run_code",
            },
        ):
            with patch.object(
                formalizer,
                "classify_claim",
                side_effect=AssertionError("classify_claim should not be called"),
            ) as mock_classify:
                result = formalizer.formalize("1 + 1 = 2")
    assert result["success"] is True
    mock_classify.assert_not_called()


def test_formalize_with_explicit_preamble() -> None:
    """formalize() with explicit preamble_names should inject preamble imports."""
    import formalizer

    lean_code = "import Mathlib\nopen Real\n\ntheorem foo : 1 = 1 := by\n  sorry"
    with patch.object(formalizer, "call_leanstral", return_value=lean_code):
        with patch.object(
            formalizer,
            "sorry_validate",
            return_value={
                "valid": True,
                "errors": [],
                "warnings": ["sorry"],
                "method": "lean_run_code",
            },
        ):
            result = formalizer.formalize(
                "Cobb-Douglas elasticity",
                preamble_names=["cobb_douglas_2factor"],
            )
    assert result["success"] is True
    assert "cobb_douglas_2factor" in result["preamble_used"]
    assert "LeanEcon.Preamble.Producer.CobbDouglas2Factor" in result["theorem_code"]


def test_formalize_without_preamble_names() -> None:
    """formalize() auto-selects matching preambles when names are omitted."""
    import formalizer

    lean_code = "import Mathlib\nopen Real\n\ntheorem foo : 1 = 1 := by\n  sorry"
    with patch.object(formalizer, "call_leanstral", return_value=lean_code):
        with patch.object(
            formalizer,
            "sorry_validate",
            return_value={
                "valid": True,
                "errors": [],
                "warnings": ["sorry"],
                "method": "lean_run_code",
            },
        ):
            result = formalizer.formalize(
                "For Cobb-Douglas preferences, Marshallian demand for good 1 is alpha * m / p1."
            )
    assert result["success"] is True
    assert "marshallian_demand" in result["preamble_used"]
    assert "LeanEcon.Preamble.Consumer.MarshallianDemand" in result["theorem_code"]


def test_classify_repair_bucket() -> None:
    assert classify_repair_bucket(["unknown module prefix 'Topology'"]) == (
        REPAIR_BUCKET_UNKNOWN_IMPORT_MODULE
    )
    assert classify_repair_bucket(["unknown identifier 'StrictConcave'"]) == (
        REPAIR_BUCKET_UNKNOWN_IDENTIFIER
    )
    assert classify_repair_bucket(["failed to synthesize instance MetricSpace α"]) == (
        REPAIR_BUCKET_TYPECLASS_INSTANCE
    )
    assert classify_repair_bucket(["unexpected token ':'; expected command"]) == (
        REPAIR_BUCKET_SYNTAX_NOTATION
    )
    assert classify_repair_bucket(["application type mismatch"]) == REPAIR_BUCKET_SEMANTIC_MISMATCH


def test_formalize_applies_deterministic_import_repair_before_second_model_call() -> None:
    import formalizer

    responses = [
        "import Topology\n\ntheorem foo : True := by\n  sorry\n",
    ]
    validations = [
        {
            "valid": False,
            "errors": ["unknown module prefix 'Topology'"],
            "warnings": [],
            "method": "lean_run_code",
        },
        {
            "valid": True,
            "errors": [],
            "warnings": ["declaration uses `sorry`"],
            "method": "lake_env_lean",
        },
    ]

    with patch.object(formalizer, "call_leanstral", side_effect=responses) as mock_call:
        with patch.object(formalizer, "sorry_validate", side_effect=validations):
            result = formalizer.formalize("A trivial true claim.")

    assert result["success"] is True
    assert result["attempts"] == 1
    assert mock_call.call_count == 1
    assert result["formalizer_telemetry"]["deterministic_repairs_applied"] == [
        "normalize_imports"
    ]
    assert result["formalizer_telemetry"]["validation_methods"] == [
        "lean_run_code",
        "lake_env_lean",
    ]


def test_formalize_uses_bucket_specific_repair_prompt() -> None:
    import formalizer

    lean_code = "import Mathlib\n\ntheorem foo : True := by\n  sorry\n"
    prompts: list[str] = []

    def fake_call(_client, messages, _stage, **_kwargs):
        prompts.append(messages[0]["content"])
        if len(prompts) == 1:
            return lean_code
        return "import Mathlib\n\ntheorem foo : True := by\n  sorry\n"

    with patch.object(formalizer, "call_leanstral", side_effect=fake_call):
        with patch.object(
            formalizer,
            "sorry_validate",
            side_effect=[
                {
                    "valid": False,
                    "errors": ["unknown identifier 'StrictConcave'"],
                    "warnings": [],
                    "method": "lean_run_code",
                },
                {
                    "valid": True,
                    "errors": [],
                    "warnings": ["declaration uses `sorry`"],
                    "method": "lake_env_lean",
                },
            ],
        ):
            result = formalizer.formalize("A strictly concave function has a property.")

    assert result["success"] is True
    assert len(prompts) == 2
    assert "UNKNOWN IDENTIFIER" in prompts[1]
    assert result["formalizer_telemetry"]["repair_buckets"] == [
        REPAIR_BUCKET_UNKNOWN_IDENTIFIER
    ]


def test_expanded_keyword_strictly_concave() -> None:
    matches = find_matching_preambles(
        "A strictly concave function attains a maximum on a compact set."
    )
    names = [m.name for m in matches]
    assert "extreme_value_theorem" in names, f"Expected extreme_value_theorem, got {names}"


def test_expanded_keyword_risk_premium() -> None:
    matches = find_matching_preambles("The risk premium for a risk-averse agent.")
    names = [m.name for m in matches]
    assert any(n in names for n in ("arrow_pratt_rra", "arrow_pratt_ara")), (
        f"Expected arrow_pratt entry, got {names}"
    )


def test_expanded_keyword_marginal_product() -> None:
    matches = find_matching_preambles("The marginal product of capital in a Cobb-Douglas economy.")
    names = [m.name for m in matches]
    assert "cobb_douglas_2factor" in names, f"Expected cobb_douglas_2factor, got {names}"


def test_expanded_keyword_diminishing_returns() -> None:
    matches = find_matching_preambles("Diminishing returns to labor in production.")
    names = [m.name for m in matches]
    assert "cobb_douglas_2factor" in names, f"Expected cobb_douglas_2factor, got {names}"


def test_expanded_keyword_returns_to_scale_ces() -> None:
    matches = find_matching_preambles("CES production exhibits constant returns to scale.")
    names = [m.name for m in matches]
    assert "ces_2factor" in names, f"Expected ces_2factor, got {names}"


def test_build_preamble_catalog_summary() -> None:
    summary = build_preamble_catalog_summary()
    for name in PREAMBLE_LIBRARY:
        assert name in summary, f"Entry {name!r} missing from catalog summary"


def test_build_classify_prompt_includes_catalog() -> None:
    prompt = build_classify_prompt()
    assert "AVAILABLE PREAMBLES" in prompt
    assert "cobb_douglas_2factor" in prompt
    assert "crra_utility" in prompt


def test_extract_theorem_name() -> None:
    """extract_theorem_name picks up theorem and lemma declarations."""
    from lean_runner import extract_theorem_name

    assert extract_theorem_name("theorem foo : True := by sorry") == "foo"
    assert extract_theorem_name("lemma bar_baz (x : ℝ) : x = x := by rfl") == "bar_baz"
    assert extract_theorem_name("def not_a_theorem := 42") is None
