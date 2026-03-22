"""Unit tests for src/lean_verifier.py."""

from __future__ import annotations

import subprocess

import lean_verifier


def test_sanitize_file_stem_and_parse_diagnostics() -> None:
    assert lean_verifier._sanitize_file_stem("123-demo.lean", "Proof") == "Proof_123_demo"
    assert lean_verifier._parse_diagnostics(
        "LeanEcon/Proof.lean:5:2: error: unknown identifier `x`",
        "error",
    ) == ["LeanEcon/Proof.lean:5:2: unknown identifier `x`"]


def test_run_direct_lean_check_handles_missing_lake(monkeypatch, tmp_path) -> None:
    workspace = tmp_path / "lean_workspace"
    source_dir = workspace / "LeanEcon"
    source_dir.mkdir(parents=True)
    lean_file = source_dir / "Demo.lean"
    lean_file.write_text("import Mathlib\n", encoding="utf-8")

    monkeypatch.setattr(lean_verifier, "LEAN_WORKSPACE", workspace)
    monkeypatch.setattr(
        lean_verifier.subprocess,
        "run",
        lambda *args, **kwargs: (_ for _ in ()).throw(FileNotFoundError()),
    )

    result = lean_verifier.run_direct_lean_check(lean_file)
    assert result["success"] is False
    assert "lake executable not found" in result["errors"][0]


def test_run_direct_lean_check_handles_timeout(monkeypatch, tmp_path) -> None:
    workspace = tmp_path / "lean_workspace"
    source_dir = workspace / "LeanEcon"
    source_dir.mkdir(parents=True)
    lean_file = source_dir / "Demo.lean"
    lean_file.write_text("import Mathlib\n", encoding="utf-8")

    monkeypatch.setattr(lean_verifier, "LEAN_WORKSPACE", workspace)

    def _raise_timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=["lake"], timeout=300)

    monkeypatch.setattr(lean_verifier.subprocess, "run", _raise_timeout)

    result = lean_verifier.run_direct_lean_check(lean_file)
    assert result["success"] is False
    assert result["returncode"] == -1
    assert "Timeout after 300s" in result["errors"][0]


def test_run_direct_lean_check_flags_sorry(monkeypatch, tmp_path) -> None:
    workspace = tmp_path / "lean_workspace"
    source_dir = workspace / "LeanEcon"
    source_dir.mkdir(parents=True)
    lean_file = source_dir / "Demo.lean"
    lean_file.write_text("import Mathlib\n", encoding="utf-8")

    monkeypatch.setattr(lean_verifier, "LEAN_WORKSPACE", workspace)
    monkeypatch.setattr(
        lean_verifier.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args=["lake"],
            returncode=0,
            stdout="warning: declaration uses `sorry`",
            stderr="",
        ),
    )

    result = lean_verifier.run_direct_lean_check(lean_file)
    assert result["success"] is False
    assert "Proof contains 'sorry'" in result["errors"][-1]


def test_verify_cleans_up_temp_file(monkeypatch, tmp_path) -> None:
    temp_file = tmp_path / "AgenticProof_test.lean"
    temp_file.write_text("import Mathlib\n", encoding="utf-8")

    monkeypatch.setattr(lean_verifier, "write_verification_file", lambda *args, **kwargs: temp_file)
    monkeypatch.setattr(
        lean_verifier,
        "run_direct_lean_check",
        lambda path: {
            "success": True,
            "errors": [],
            "warnings": [],
            "returncode": 0,
            "stdout": "",
            "stderr": "",
            "lean_file": str(path),
            "verification_method": "lake_env_lean",
        },
    )
    monkeypatch.setattr(lean_verifier, "_save_to_outputs", lambda *args, **kwargs: None)

    result = lean_verifier.verify(
        "import Mathlib\n\ntheorem demo : True := by trivial\n", check_axioms=False
    )

    assert result["success"] is True
    assert not temp_file.exists()
