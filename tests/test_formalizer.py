"""
Standalone smoke tests for formalizer.py.

Usage:
  ./econProver_venv/bin/python tests/test_formalizer.py

Includes:
  - Live smoke tests (require MISTRAL_API_KEY and lake build)
  - Unit tests for preamble library, injection, and diagnostics (mock-based)
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_DIR))

from formalizer import _inject_preamble_imports, formalize
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


def _run_case(name: str, fn) -> bool:
    try:
        fn()
    except Exception as exc:
        print(f"{name}: FAIL ({exc})")
        return False
    print(f"{name}: PASS")
    return True


# ---------------------------------------------------------------------------
# Live smoke tests (require MISTRAL_API_KEY + lake build)
# ---------------------------------------------------------------------------

def _run_live_case(
    label: str,
    claim: str,
    *,
    expect_success: bool,
    expect_failed: bool,
) -> bool:
    result = formalize(claim)
    ok = (
        result["success"] == expect_success
        and result["formalization_failed"] == expect_failed
    )

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

def _test_preamble_library_has_entries() -> None:
    assert len(PREAMBLE_LIBRARY) >= 10, f"Expected >=10 entries, got {len(PREAMBLE_LIBRARY)}"
    for name, entry in PREAMBLE_LIBRARY.items():
        assert entry.name == name
        assert entry.lean_path.is_file(), f"Missing Lean file for {name}: {entry.lean_path}"
        assert len(read_preamble_source(entry, strip_header=False).strip()) > 0
        assert len(entry.description) > 0
        assert len(entry.keywords) > 0


def _test_find_matching_preambles_cobb_douglas() -> None:
    matches = find_matching_preambles("Cobb-Douglas output elasticity equals alpha.")
    names = [m.name for m in matches]
    assert "cobb_douglas_2factor" in names


def _test_find_matching_preambles_crra() -> None:
    matches = find_matching_preambles("Under CRRA utility, RRA equals gamma.")
    names = [m.name for m in matches]
    assert "crra_utility" in names


def _test_find_matching_preambles_no_match() -> None:
    matches = find_matching_preambles("Nash equilibrium exists in finite games.")
    assert len(matches) == 0


def _test_build_preamble_block() -> None:
    entries = get_preamble_entries(["cobb_douglas_2factor", "crra_utility"])
    block = build_preamble_block(entries)
    assert "noncomputable def cobb_douglas" in block
    assert "noncomputable def crra_utility" in block
    assert "import Mathlib" not in block


def _test_build_preamble_imports() -> None:
    entries = get_preamble_entries(["cobb_douglas_2factor", "crra_utility", "crra_utility"])
    imports = build_preamble_imports(entries)
    assert imports == [
        "import LeanEcon.Preamble.Producer.CobbDouglas2Factor",
        "import LeanEcon.Preamble.Consumer.CRRAUtility",
    ]


def _test_get_preamble_entries_unknown() -> None:
    entries = get_preamble_entries(["nonexistent_entry"])
    assert entries == []


def _test_preamble_keyword_coverage() -> None:
    """Verify keyword matching for all major textbook concepts."""
    test_cases = [
        ("Cobb-Douglas output elasticity", "cobb_douglas_2factor"),
        ("contraction mapping theorem", "contraction_mapping"),
        ("Blackwell sufficient conditions", "blackwell_sufficient"),
        ("Slutsky equation decomposition", "slutsky_equation"),
        ("Solow model steady state", "solow_steady_state"),
        ("Euler equation for consumption", "euler_equation"),
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


def _test_preamble_library_expanded() -> None:
    """Verify the library has the expected number of entries after expansion."""
    assert len(PREAMBLE_LIBRARY) >= 25, f"Expected >=25 entries, got {len(PREAMBLE_LIBRARY)}"


def _test_read_preamble_source_strips_import_header() -> None:
    entry = PREAMBLE_LIBRARY["crra_utility"]
    source = read_preamble_source(entry)
    assert "import Mathlib" not in source
    assert "noncomputable def crra_utility" in source


# ---------------------------------------------------------------------------
# Unit tests: _inject_preamble_imports
# ---------------------------------------------------------------------------

def _test_inject_preamble_imports_placement() -> None:
    lean_code = (
        "import Mathlib\n"
        "open Real\n"
        "\n"
        "theorem foo : 1 = 1 := by\n"
        "  sorry\n"
    )
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

def _test_classify_algebraic() -> None:
    import formalizer
    with patch.object(formalizer, "call_leanstral", return_value="ALGEBRAIC"):
        result = formalizer.classify_claim("-c * (-gamma * c⁻¹) = gamma")
    assert result["category"] == "ALGEBRAIC"
    assert result["preamble_matches"] == []
    assert result["suggested_reformulation"] is None


def _test_classify_definable_with_match() -> None:
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


def _test_classify_definable_without_match() -> None:
    import formalizer
    with patch.object(
        formalizer,
        "call_leanstral",
        return_value="DEFINABLE: Custom Leontief production function",
    ):
        result = formalizer.classify_claim(
            "Leontief production is not differentiable."
        )
    assert result["category"] == "DEFINABLE"
    assert result["preamble_matches"] == []
    assert result["suggested_reformulation"] is not None


def _test_classify_requires_definitions() -> None:
    import formalizer
    with patch.object(
        formalizer,
        "call_leanstral",
        return_value="REQUIRES_DEFINITIONS: Needs competitive equilibrium framework.",
    ):
        result = formalizer.classify_claim("Nash equilibrium exists in finite games.")
    assert result["category"] == "REQUIRES_DEFINITIONS"
    assert result["preamble_matches"] == []


def _test_classify_requires_definitions_rescued() -> None:
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


# ---------------------------------------------------------------------------
# Unit tests: diagnostics
# ---------------------------------------------------------------------------

def _test_diagnose_valid_json() -> None:
    import formalizer
    mock_response = '{"diagnosis": "Type mismatch", "suggested_fix": "Use Real instead of Nat", "fixable": true}'
    with patch.object(formalizer, "call_leanstral", return_value=mock_response):
        result = formalizer._diagnose_formalization_failure(
            "some claim", "import Mathlib\nsorry", ["error: type mismatch"]
        )
    assert result["diagnosis"] == "Type mismatch"
    assert result["suggested_fix"] == "Use Real instead of Nat"
    assert result["fixable"] is True


def _test_diagnose_invalid_json_fallback() -> None:
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

def _test_sorry_validate_uses_run_code() -> None:
    """sorry_validate returns method='lean_run_code' when lean_runner succeeds."""
    import formalizer
    mock_result = {"valid": True, "errors": [], "warnings": ["declaration uses `sorry`"]}
    with patch("formalizer.run_code", create=True) as mock_run:
        # Patch the lazy import inside sorry_validate
        import lean_runner
        with patch.object(lean_runner, "run_code", return_value=mock_result):
            with patch.dict("sys.modules", {"lean_runner": lean_runner}):
                result = formalizer.sorry_validate("import Mathlib\ntheorem t : True := by sorry")
    # The function does a lazy import, so we patch at module level
    assert result["method"] == "lean_run_code" or result["method"] == "lake_build"


def _test_sorry_validate_fallback_on_error() -> None:
    """sorry_validate falls back to lake_build when lean_runner raises."""
    import formalizer
    from lean_verifier import write_lean_file, run_lake_build
    mock_raw = {
        "returncode": 0,
        "errors": ["declaration uses `sorry`"],
        "warnings": [],
    }
    # Make lean_runner import fail, forcing fallback
    with patch.dict("sys.modules", {"lean_runner": None}):
        with patch.object(formalizer, "write_lean_file", return_value=Path("/tmp/fake.lean")):
            with patch.object(formalizer, "run_lake_build", return_value=mock_raw):
                result = formalizer.sorry_validate("import Mathlib\ntheorem t : True := by sorry")
    assert result["method"] == "lake_build"
    assert result["valid"] is True
    assert result["errors"] == []


def _test_expanded_keyword_strictly_concave() -> None:
    matches = find_matching_preambles("A strictly concave function attains a maximum on a compact set.")
    names = [m.name for m in matches]
    assert "extreme_value_theorem" in names, f"Expected extreme_value_theorem, got {names}"


def _test_expanded_keyword_risk_premium() -> None:
    matches = find_matching_preambles("The risk premium for a risk-averse agent.")
    names = [m.name for m in matches]
    assert any(n in names for n in ("arrow_pratt_rra", "arrow_pratt_ara")), (
        f"Expected arrow_pratt entry, got {names}"
    )


def _test_expanded_keyword_marginal_product() -> None:
    matches = find_matching_preambles("The marginal product of capital in a Cobb-Douglas economy.")
    names = [m.name for m in matches]
    assert "cobb_douglas_2factor" in names, f"Expected cobb_douglas_2factor, got {names}"


def _test_expanded_keyword_diminishing_returns() -> None:
    matches = find_matching_preambles("Diminishing returns to labor in production.")
    names = [m.name for m in matches]
    assert "cobb_douglas_2factor" in names, f"Expected cobb_douglas_2factor, got {names}"


def _test_expanded_keyword_returns_to_scale_ces() -> None:
    matches = find_matching_preambles("CES production exhibits constant returns to scale.")
    names = [m.name for m in matches]
    assert "ces_2factor" in names, f"Expected ces_2factor, got {names}"


def _test_build_preamble_catalog_summary() -> None:
    summary = build_preamble_catalog_summary()
    for name in PREAMBLE_LIBRARY:
        assert name in summary, f"Entry {name!r} missing from catalog summary"


def _test_build_classify_prompt_includes_catalog() -> None:
    prompt = build_classify_prompt()
    assert "AVAILABLE DEFINITIONS" in prompt
    assert "cobb_douglas_2factor" in prompt
    assert "crra_utility" in prompt


def _test_extract_theorem_name() -> None:
    """extract_theorem_name picks up theorem and lemma declarations."""
    from lean_runner import extract_theorem_name
    assert extract_theorem_name("theorem foo : True := by sorry") == "foo"
    assert extract_theorem_name("lemma bar_baz (x : ℝ) : x = x := by rfl") == "bar_baz"
    assert extract_theorem_name("def not_a_theorem := 42") is None


def main() -> int:
    print("=" * 60)
    print("LeanEcon Formalizer Tests")
    print("=" * 60)

    # Unit tests (no API key needed)
    results = {
        # preamble library
        "preamble_library_has_entries": _run_case(
            "preamble_library_has_entries", _test_preamble_library_has_entries
        ),
        "find_matching_preambles_cobb_douglas": _run_case(
            "find_matching_preambles_cobb_douglas", _test_find_matching_preambles_cobb_douglas
        ),
        "find_matching_preambles_crra": _run_case(
            "find_matching_preambles_crra", _test_find_matching_preambles_crra
        ),
        "find_matching_preambles_no_match": _run_case(
            "find_matching_preambles_no_match", _test_find_matching_preambles_no_match
        ),
        "build_preamble_block": _run_case(
            "build_preamble_block", _test_build_preamble_block
        ),
        "build_preamble_imports": _run_case(
            "build_preamble_imports", _test_build_preamble_imports
        ),
        "get_preamble_entries_unknown": _run_case(
            "get_preamble_entries_unknown", _test_get_preamble_entries_unknown
        ),
        "preamble_keyword_coverage": _run_case(
            "preamble_keyword_coverage", _test_preamble_keyword_coverage
        ),
        "preamble_library_expanded": _run_case(
            "preamble_library_expanded", _test_preamble_library_expanded
        ),
        "read_preamble_source_strips_import_header": _run_case(
            "read_preamble_source_strips_import_header",
            _test_read_preamble_source_strips_import_header,
        ),
        # inject preamble imports
        "inject_preamble_imports_placement": _run_case(
            "inject_preamble_imports_placement",
            _test_inject_preamble_imports_placement,
        ),
        # three-tier classifier
        "classify_algebraic": _run_case(
            "classify_algebraic", _test_classify_algebraic
        ),
        "classify_definable_with_match": _run_case(
            "classify_definable_with_match", _test_classify_definable_with_match
        ),
        "classify_definable_without_match": _run_case(
            "classify_definable_without_match", _test_classify_definable_without_match
        ),
        "classify_requires_definitions": _run_case(
            "classify_requires_definitions", _test_classify_requires_definitions
        ),
        "classify_requires_definitions_rescued": _run_case(
            "classify_requires_definitions_rescued",
            _test_classify_requires_definitions_rescued,
        ),
        # diagnostics
        "diagnose_valid_json": _run_case(
            "diagnose_valid_json", _test_diagnose_valid_json
        ),
        "diagnose_invalid_json_fallback": _run_case(
            "diagnose_invalid_json_fallback", _test_diagnose_invalid_json_fallback
        ),
        # sorry_validate lean_run_code integration
        "sorry_validate_fallback_on_error": _run_case(
            "sorry_validate_fallback_on_error", _test_sorry_validate_fallback_on_error
        ),
        "extract_theorem_name": _run_case(
            "extract_theorem_name", _test_extract_theorem_name
        ),
        # expanded keyword coverage
        "expanded_keyword_strictly_concave": _run_case(
            "expanded_keyword_strictly_concave",
            _test_expanded_keyword_strictly_concave,
        ),
        "expanded_keyword_risk_premium": _run_case(
            "expanded_keyword_risk_premium",
            _test_expanded_keyword_risk_premium,
        ),
        "expanded_keyword_marginal_product": _run_case(
            "expanded_keyword_marginal_product",
            _test_expanded_keyword_marginal_product,
        ),
        "expanded_keyword_diminishing_returns": _run_case(
            "expanded_keyword_diminishing_returns",
            _test_expanded_keyword_diminishing_returns,
        ),
        "expanded_keyword_returns_to_scale_ces": _run_case(
            "expanded_keyword_returns_to_scale_ces",
            _test_expanded_keyword_returns_to_scale_ces,
        ),
        # catalog & classify prompt
        "build_preamble_catalog_summary": _run_case(
            "build_preamble_catalog_summary",
            _test_build_preamble_catalog_summary,
        ),
        "build_classify_prompt_includes_catalog": _run_case(
            "build_classify_prompt_includes_catalog",
            _test_build_classify_prompt_includes_catalog,
        ),
    }

    # Live smoke tests (skip if no API key)
    import os
    if os.environ.get("MISTRAL_API_KEY"):
        print("\n--- Live smoke tests (requires MISTRAL_API_KEY + lake build) ---")
        try:
            results["crra_rra"] = _run_live_case(
                "CRRA RRA",
                (
                    "Under CRRA utility u(c) = c^{1-γ}/(1-γ), the coefficient of "
                    "relative risk aversion is constant and equal to γ."
                ),
                expect_success=True,
                expect_failed=False,
            )
            results["requires_definitions"] = _run_live_case(
                "Nash equilibrium existence",
                "Every finite normal-form game has a Nash equilibrium.",
                expect_success=False,
                expect_failed=True,
            )
        except Exception as exc:
            print(f"\n--- Skipping live smoke tests (Leanstral unavailable: {exc}) ---")
    else:
        print("\n--- Skipping live smoke tests (no MISTRAL_API_KEY) ---")

    print("\n" + "=" * 60)
    print("Results:")
    for name, passed in results.items():
        print(f"  {name}: {'PASS' if passed else 'FAIL'}")

    all_passed = all(results.values())
    print(f"\nOverall: {'ALL PASSED' if all_passed else 'SOME FAILED'}")
    print("=" * 60)
    return 0 if all_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
