"""Tests for src/explainer.py."""

from __future__ import annotations

import explainer


def test_infer_outcome_label() -> None:
    assert explainer._infer_outcome_label({"success": True}) == "verified"
    assert explainer._infer_outcome_label({"formalization_failed": True}) == "formalization_failed"
    assert (
        explainer._infer_outcome_label(
            {"formalization_failed": True, "failure_reason": "Needs definitions."}
        )
        == "classification_rejected"
    )
    assert explainer._infer_outcome_label({"proof_generated": False}) == "proving_failed"


def test_axiom_section_reports_soundness() -> None:
    text = explainer._axiom_section({"axiom_info": {"sound": True}})
    assert "Proof is sound" in text


def test_explain_result_generated(monkeypatch) -> None:
    logs: list[dict] = []
    monkeypatch.setattr(explainer, "_call_with_timeout", lambda prompt: "Explanation text")

    result = explainer.explain_result(
        original_claim="1 + 1 = 2",
        theorem_code="theorem one_plus_one : 1 + 1 = 2 := by sorry",
        verification_result={"success": True, "proof_tactics": "norm_num"},
        on_log=logs.append,
    )

    assert result == {"explanation": "Explanation text", "generated": True}
    assert any(entry["stage"] == "explain" for entry in logs)


def test_explain_result_falls_back(monkeypatch) -> None:
    monkeypatch.setattr(
        explainer, "_call_with_timeout", lambda prompt: (_ for _ in ()).throw(RuntimeError("boom"))
    )

    result = explainer.explain_result(
        original_claim="The second welfare theorem holds.",
        theorem_code="",
        verification_result={"formalization_failed": True, "failure_reason": "Needs definitions."},
    )

    assert result["generated"] is False
    assert "Claim not supported" in result["explanation"]
