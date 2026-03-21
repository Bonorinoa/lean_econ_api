"""
Standalone smoke tests for lean_verifier.py.

Usage:
  ./leanEconAPI_venv/bin/python tests/test_verifier.py
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
EXAMPLES_DIR = PROJECT_ROOT / "examples"
sys.path.insert(0, str(SRC_DIR))

from lean_verifier import LEAN_WORKSPACE, verify

KNOWN_GOOD_LEAN = """\
import Mathlib
open Real

theorem one_plus_one : 1 + 1 = 2 := by
  norm_num
"""

KNOWN_BAD_LEAN = """\
import Mathlib
open Real

theorem false_claim : 1 + 1 = 3 := by
  norm_num
"""

SORRY_LEAN = """\
import Mathlib
open Real

theorem unproven : 1 + 1 = 2 := by
  sorry
"""

LEAN_WITH_PREAMBLE_IMPORT = """\
import Mathlib
import LeanEcon.Preamble.Consumer.CRRAUtility
open Real

theorem imported_crra_definition (c γ : ℝ) :
    crra_utility c γ = Real.rpow c (1 - γ) / (1 - γ) := by
  rfl
"""

CURATED_PARITY_EXAMPLES = {
    "even_form_example": EXAMPLES_DIR / "even_form_pass.lean",
    "even_sum_example": EXAMPLES_DIR / "even_sum_pass.lean",
    "double_even_example": EXAMPLES_DIR / "double_even_pass.lean",
}


def _run_case(name: str, code: str, expected_success: bool) -> bool:
    result = verify(code, filename=f"_test_{name}")
    ok = result["success"] == expected_success
    status = "PASS" if result["success"] else "FAIL"

    print(f"\n{name}")
    print(f"  expected: {'PASS' if expected_success else 'FAIL'}")
    print(f"  got:      {status}")
    if result["errors"]:
        print(f"  errors:   {result['errors'][0][:120]}")
    print(f"  status:   {'PASS' if ok else 'FAIL'}")
    return ok


def _run_example_case(name: str, path: Path, expected_success: bool = True) -> bool:
    code = path.read_text(encoding="utf-8")
    result = verify(code, filename=f"_example_{name}")
    ok = result["success"] == expected_success
    status = "PASS" if result["success"] else "FAIL"

    print(f"\n{name}")
    print(f"  file:     {path.name}")
    print(f"  expected: {'PASS' if expected_success else 'FAIL'}")
    print(f"  got:      {status}")
    if result["errors"]:
        print(f"  errors:   {result['errors'][0][:120]}")
    print(f"  status:   {'PASS' if ok else 'FAIL'}")
    return ok


def _test_verify_does_not_touch_proof_module() -> bool:
    proof_path = LEAN_WORKSPACE / "LeanEcon" / "Proof.lean"
    original = proof_path.read_text(encoding="utf-8")
    result = verify(KNOWN_GOOD_LEAN, filename="_test_restore_check")
    restored = proof_path.read_text(encoding="utf-8")
    ok = result["success"] and restored == original

    print("\nproof_module_unchanged")
    print("  expected: PASS")
    print(f"  got:      {'PASS' if ok else 'FAIL'}")
    if not ok and restored != original:
        print("  errors:   verify() unexpectedly modified LeanEcon/Proof.lean")
    print(f"  status:   {'PASS' if ok else 'FAIL'}")
    return ok


def _test_verify_cleans_up_temp_file() -> bool:
    proof_dir = LEAN_WORKSPACE / "LeanEcon"
    prefix = "TempCleanupCheck"
    before = set(proof_dir.glob(f"{prefix}_*.lean"))
    result = verify(KNOWN_GOOD_LEAN, filename=prefix)
    after = set(proof_dir.glob(f"{prefix}_*.lean"))
    ok = result["success"] and before == after

    print("\nverify_temp_file_cleanup")
    print("  expected: PASS")
    print(f"  got:      {'PASS' if ok else 'FAIL'}")
    if not ok:
        leaked = sorted(str(path.name) for path in after - before)
        if leaked:
            print(f"  errors:   leaked temp files: {', '.join(leaked)}")
    print(f"  status:   {'PASS' if ok else 'FAIL'}")
    return ok


def main() -> int:
    print("=" * 60)
    print("LeanEcon Verifier Smoke Tests")
    print("=" * 60)
    print(f"lean_workspace: {LEAN_WORKSPACE}")

    results = {
        "known_good": _run_case("known_good", KNOWN_GOOD_LEAN, True),
        "known_bad": _run_case("known_bad", KNOWN_BAD_LEAN, False),
        "sorry_proof": _run_case("sorry_proof", SORRY_LEAN, False),
        "preamble_import": _run_case("preamble_import", LEAN_WITH_PREAMBLE_IMPORT, True),
        "proof_module_unchanged": _test_verify_does_not_touch_proof_module(),
        "verify_temp_file_cleanup": _test_verify_cleans_up_temp_file(),
    }
    for name, path in CURATED_PARITY_EXAMPLES.items():
        results[name] = _run_example_case(name, path, True)

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
