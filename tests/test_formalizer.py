"""
Standalone smoke tests for formalizer.py.

Usage:
  ./econProver_venv/bin/python tests/test_formalizer.py
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_DIR))

from formalizer import formalize


def _run_case(
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
    print(f"  status:               {'PASS' if ok else 'FAIL'}")
    return ok


def main() -> int:
    print("=" * 60)
    print("LeanEcon Formalizer Smoke Tests")
    print("=" * 60)

    results = {
        "crra_rra": _run_case(
            "CRRA RRA",
            (
                "Under CRRA utility u(c) = c^{1-γ}/(1-γ), the coefficient of "
                "relative risk aversion is constant and equal to γ."
            ),
            expect_success=True,
            expect_failed=False,
        ),
        "requires_definitions": _run_case(
            "Second welfare theorem",
            "The second welfare theorem holds under convex preferences.",
            expect_success=False,
            expect_failed=True,
        ),
    }

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
