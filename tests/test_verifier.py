"""Live smoke tests for lean_verifier.py."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

import lean_verifier
from lean_verifier import LEAN_WORKSPACE, verify

EXAMPLES_DIR = Path(__file__).resolve().parents[1] / "docs" / "legacy_examples"

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


def test_compile_lean_code_attaches_local_only_telemetry(tmp_path: Path) -> None:
    lean_code = """\
import Mathlib

theorem demo : True := by
  trivial
"""
    lean_path = tmp_path / "demo.lean"
    lean_path.write_text(lean_code, encoding="utf-8")

    with (
        patch.object(lean_verifier, "write_verification_file", return_value=lean_path),
        patch.object(
            lean_verifier,
            "run_direct_lean_check",
            return_value={
                "success": True,
                "returncode": 0,
                "stdout": "",
                "stderr": "",
                "errors": [],
                "warnings": [],
                "lean_file": str(lean_path),
                "verification_method": "lake_env_lean",
            },
        ),
    ):
        result = lean_verifier.compile_lean_code(lean_code, filename="demo", check_axioms=False)

    assert result["success"] is True
    assert result["telemetry"]["endpoint"] == "lean_compile"
    assert result["telemetry"]["local_only"] is True
    assert result["telemetry"]["estimated_cost_base_usd"] is None


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


@pytest.mark.live
def test_verify_known_good() -> None:
    result = verify(KNOWN_GOOD_LEAN, filename="_test_known_good", check_axioms=False)
    assert result["success"] is True


@pytest.mark.live
def test_verify_known_bad() -> None:
    result = verify(KNOWN_BAD_LEAN, filename="_test_known_bad", check_axioms=False)
    assert result["success"] is False


@pytest.mark.live
def test_verify_sorry_proof() -> None:
    result = verify(SORRY_LEAN, filename="_test_sorry_proof", check_axioms=False)
    assert result["success"] is False


@pytest.mark.live
def test_verify_preamble_import() -> None:
    result = verify(LEAN_WITH_PREAMBLE_IMPORT, filename="_test_preamble_import", check_axioms=False)
    assert result["success"] is True


@pytest.mark.live
def test_verify_does_not_touch_proof_module() -> None:
    proof_path = LEAN_WORKSPACE / "LeanEcon" / "Proof.lean"
    original = proof_path.read_text(encoding="utf-8")
    result = verify(KNOWN_GOOD_LEAN, filename="_test_restore_check", check_axioms=False)
    restored = proof_path.read_text(encoding="utf-8")
    assert result["success"]
    assert restored == original, "verify() unexpectedly modified LeanEcon/Proof.lean"


@pytest.mark.live
def test_verify_cleans_up_temp_file() -> None:
    proof_dir = LEAN_WORKSPACE / "LeanEcon"
    prefix = "TempCleanupCheck"
    before = set(proof_dir.glob(f"{prefix}_*.lean"))
    result = verify(KNOWN_GOOD_LEAN, filename=prefix, check_axioms=False)
    after = set(proof_dir.glob(f"{prefix}_*.lean"))
    assert result["success"]
    assert before == after, f"Leaked temp files: {sorted(str(p.name) for p in after - before)}"


@pytest.mark.live
@pytest.mark.parametrize("name,path", list(CURATED_PARITY_EXAMPLES.items()))
def test_curated_parity_example(name: str, path: Path) -> None:
    code = path.read_text(encoding="utf-8")
    result = verify(code, filename=f"_example_{name}", check_axioms=False)
    assert result["success"] is True, f"Example {name} failed: {result.get('errors', [])[:1]}"
