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

from formalizer import _inject_preamble, formalize
from preamble_library import (
    PREAMBLE_LIBRARY,
    build_preamble_block,
    find_matching_preambles,
    get_preamble_entries,
)


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
        assert len(entry.lean_code.strip()) > 0
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


def _test_get_preamble_entries_unknown() -> None:
    entries = get_preamble_entries(["nonexistent_entry"])
    assert entries == []


# ---------------------------------------------------------------------------
# Unit tests: _inject_preamble
# ---------------------------------------------------------------------------

def _test_inject_preamble_placement() -> None:
    lean_code = (
        "import Mathlib\n"
        "open Real\n"
        "\n"
        "theorem foo : 1 = 1 := by\n"
        "  sorry\n"
    )
    preamble = "noncomputable def bar (x : ℝ) : ℝ := x * x"
    result = _inject_preamble(lean_code, preamble)
    lines = result.splitlines()
    # Preamble should appear after open Real, before theorem
    preamble_idx = None
    theorem_idx = None
    for i, line in enumerate(lines):
        if "noncomputable def bar" in line:
            preamble_idx = i
        if "theorem foo" in line:
            theorem_idx = i
    assert preamble_idx is not None, "Preamble not found in output"
    assert theorem_idx is not None, "Theorem not found in output"
    assert preamble_idx < theorem_idx, "Preamble should appear before theorem"


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
        result = formalizer.classify_claim("The second welfare theorem holds.")
    assert result["category"] == "REQUIRES_DEFINITIONS"
    assert result["preamble_matches"] == []


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
        "get_preamble_entries_unknown": _run_case(
            "get_preamble_entries_unknown", _test_get_preamble_entries_unknown
        ),
        # inject preamble
        "inject_preamble_placement": _run_case(
            "inject_preamble_placement", _test_inject_preamble_placement
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
        # diagnostics
        "diagnose_valid_json": _run_case(
            "diagnose_valid_json", _test_diagnose_valid_json
        ),
        "diagnose_invalid_json_fallback": _run_case(
            "diagnose_invalid_json_fallback", _test_diagnose_invalid_json_fallback
        ),
    }

    # Live smoke tests (skip if no API key)
    import os
    if os.environ.get("MISTRAL_API_KEY"):
        print("\n--- Live smoke tests (requires MISTRAL_API_KEY + lake build) ---")
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
            "Second welfare theorem",
            "The second welfare theorem holds under convex preferences.",
            expect_success=False,
            expect_failed=True,
        )
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
