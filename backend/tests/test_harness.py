"""End-to-end harness tests on a small offline knowledge base."""
import asyncio
import json
import re

import pytest

from harness.canonical import SENSORS
from utils.llm_client import llm_client

CLEAR_BEARING = ("Slurry pump in a mineral processing facility: temperature 95.0 °C, vibration 0.790, pressure 55.0 PSI, "
                 "2400 RPM, current 55.0 A, voltage 310.0 V, flow rate 100.0 L/min. What is the most likely fault?")
MISSING_TEMP = ("Gearbox driving a paper mill roller: temperature reading unavailable, vibration 0.810, pressure 50.0 PSI, "
                "2200 RPM, current 75.0 A, voltage 330.0 V, flow rate 100.0 L/min. Diagnose.")
NO_MATCH = ("Axial fan unit: temperature 118.0 °C, vibration 0.040, pressure 97.0 PSI, 4800 RPM, current 30.0 A, "
            "voltage 470.0 V, flow rate 190.0 L/min. What is wrong?")
CONTRADICTORY = ("Industrial pump: temperature 55.0 °C, vibration 0.900, pressure 50.0 PSI, 20 RPM, current 60.0 A, "
                 "voltage 330.0 V, flow rate 110.0 L/min.")
NORMAL = ("Centrifugal pump: temperature 54.0 °C, vibration 0.140, pressure 52.0 PSI, 2000 RPM, current 60.0 A, "
          "voltage 330.0 V, flow rate 110.0 L/min.")


def run(orch, kb, q, mode="combined"):
    return asyncio.run(orch.run_harness(q, "afrb", mode, kb, embedder=None, store=None))


def _all_text(r):
    parts = [r["final_diagnosis"], r["direct_answer"], *r["reasoning"], *r["supporting_evidence"]]
    for a in r["agent_outputs"]:
        parts += [a["diagnosis"], a["reasoning"], *a["key_findings"]]
    return " ".join(parts)


def test_clear_case_is_resolved_with_valid_evidence(orchestrator, small_kb):
    r = run(orchestrator, small_kb, CLEAR_BEARING)
    h = r["harness"]
    assert h["predicted_label"] == "Bearing Wear"
    ids = {e["evidence_id"] for e in h["evidence"]}
    cited = set(re.findall(r"EV-\d{3}", " ".join(r["supporting_evidence"])))
    assert cited and cited <= ids
    assert all(e["source_type"] in ("real", "synthetic") for e in h["evidence"])
    assert h["claim_validation"]["UNSUPPORTED"] == 0
    assert [f["name"] for f in h["confidence"]["factors"]][:2] == ["evidence_quality", "hypothesis_separation"]


def test_missing_temperature_is_never_invented(orchestrator, small_kb):
    r = run(orchestrator, small_kb, MISSING_TEMP)
    evidence_temps = {e["content"]["sensors"].get("temperature") for e in r["harness"]["evidence"]}
    text = _all_text(r)
    for m in re.finditer(r"temperature\D{0,12}(\d+(?:\.\d+)?)\s*°C", text, re.I):
        assert float(m.group(1)) in evidence_temps or "median" in text[max(0, m.start() - 60):m.end()], m.group(0)
    assert "temperature" in r["harness"]["query_profile"]["missing_sensors"]
    assert r["review_decision"] == "REQUIRES_HUMAN_REVIEW"


def test_no_historical_match_abstains(orchestrator, small_kb):
    r = run(orchestrator, small_kb, NO_MATCH)
    assert r["harness"]["predicted_label"] == "Insufficient Evidence"
    assert r["final_diagnosis"].lower().startswith("insufficient evidence")
    assert r["review_decision"] == "REQUIRES_HUMAN_REVIEW"
    assert any(t["stage"] == "targeted_rag" for t in r["harness"]["timeline"])   # feedback loop tried first


def test_contradictory_sensors_trigger_review(orchestrator, small_kb):
    r = run(orchestrator, small_kb, CONTRADICTORY)
    crit = {c["criterion_id"]: c["passed"] for c in r["harness"]["review"]["criteria"]}
    assert crit["G3"] is False
    assert r["review_decision"] == "REQUIRES_HUMAN_REVIEW"


def test_normal_equipment_not_forced_into_failure(orchestrator, small_kb):
    r = run(orchestrator, small_kb, NORMAL)
    assert r["harness"]["predicted_label"] == "Normal Operation"


def test_feedback_loop_reruns_only_affected_agents(orchestrator, small_kb):
    q = ("Gearbox driving a paper mill roller: temperature 86.0 °C, vibration 0.790, pressure 51.0 PSI, 2300 RPM, "
         "current 73.0 A, voltage 318.0 V, flow rate 99.0 L/min.")
    r = run(orchestrator, small_kb, q)
    tl = r["harness"]["timeline"]
    reruns = [t for t in tl if t["stage"] == "targeted_rerun"]
    assert r["harness"]["feedback_rounds"] >= 1, r["harness"]["deficiencies_history"]
    if r["harness"]["feedback_rounds"]:
        assert reruns, "a feedback round must re-run at least one agent"
        assert all(t["agent"] in ("diagnostic_expert", "pattern_agent") for t in reruns)
        assert not any(t["agent"] == "aggressive_agent" for t in reruns)      # rapid triage never re-run
        assert sum(1 for t in tl if t["agent"] == "verification") >= 2          # re-verified


def test_agreement_does_not_raise_weak_evidence():
    from harness.confidence import compute_confidence
    kw = dict(top_score=0.25, second_score=0.2, retrieval_mean=0.5, key_present=2, key_total=2, has_sensor_data=True,
              n_contradicting=0, n_consistency_violations=0, best_distance=0.1, typical_distance=0.1,
              no_match_distance=0.4, historical_vote=0.3, synthetic_share=0.0, data_mode="real")
    low = compute_confidence(agreement_ratio=0.0, **kw).confidence
    high = compute_confidence(agreement_ratio=1.0, **kw).confidence
    assert low == high < 0.5


def test_review_gate_criteria():
    from harness.review_gate import evaluate_gate
    ok = evaluate_gate(confidence=0.9, margin=0.5, consistency_violations=0, no_historical_match=False,
                       missing_key_sensors=0, has_sensor_data=True, final_label_supported=True,
                       unsupported_in_final=0, severity="HIGH", insufficient_evidence=False)
    assert ok.decision == "AUTO_RESOLVE"
    bad = evaluate_gate(confidence=0.9, margin=0.05, consistency_violations=0, no_historical_match=False,
                        missing_key_sensors=0, has_sensor_data=True, final_label_supported=True,
                        unsupported_in_final=0, severity="HIGH", insufficient_evidence=False)
    assert bad.decision == "REQUIRES_HUMAN_REVIEW" and any(r.startswith("G2") for r in bad.reasons)


def test_claim_validator_strips_fabricated_values(orchestrator, small_kb):
    from harness.claims import ClaimValidator
    from harness.schema import DiagnosticState
    from harness.query_prep import prepare_query
    r = run(orchestrator, small_kb, CLEAR_BEARING)
    st = DiagnosticState(run_id="t", query=CLEAR_BEARING, dataset_type="afrb", data_mode="combined",
                         profile=prepare_query(CLEAR_BEARING))
    v = ClaimValidator(st, ["Bearing Wear"])
    clean, checks = v.clean_text("Temperature is 95.0°C. The bearing reached 8450 operating hours. See EV-999.", "t")
    assert "95.0" in clean and "8450" not in clean and "EV-999" not in clean
    assert sum(c.status == "UNSUPPORTED" for c in checks) == 2


class _FakeLLM:
    """Adversarial LLM: invents readings, unknown labels, bad evidence IDs and malformed payloads."""
    async def generate_json(self, prompt, system=""):
        if "Rewrite the direct answer" in prompt:
            return {"direct_answer": "Bearing Wear confirmed: temperature hit 131.7°C and 9,120 hours were logged."}
        if "hypotheses" in prompt and "Review the draft" in prompt:
            return {"narrative": "Winding temperature 142°C proves a thermal runaway.",
                    "hypotheses": [{"label": "Quantum Flux Failure", "supporting": ["vibration 7.7 mm/s [EV-777]"]},
                                   {"label": "Bearing Wear", "supporting": [{"statement": "oil at 3.3 cSt", "evidence_ids": ["EV-001"]}]}]}
        if "adversarial" in prompt:
            return "not-a-dict"
        return {"narrative": "Pressure spiked to 88.8 PSI two days ago.",
                "supporting_evidence": [{"statement": "Flow 12.3 L/min recorded", "evidence_ids": ["EV-001"]}]}

    def is_available(self):
        return True


def test_llm_hallucinations_are_removed(orchestrator, small_kb, monkeypatch):
    fake = _FakeLLM()
    for agent in orchestrator.agents.values():
        monkeypatch.setattr(agent, "llm", fake)
    monkeypatch.setattr(llm_client, "is_available", lambda: True)
    r = run(orchestrator, small_kb, CLEAR_BEARING)
    text = _all_text(r) + json.dumps(r["harness"]["agents"])
    for fabricated in ["131.7", "9,120", "142°C", "7.7 mm/s", "88.8", "12.3 L/min", "3.3 cSt", "Quantum Flux"]:
        assert fabricated not in text, fabricated
    assert r["harness"]["predicted_label"] == "Bearing Wear"
    assert r["harness"]["claim_validation"]["removed"] > 0
    modes = {k: a["mode"] for k, a in r["harness"]["agents"].items() if a}
    assert "llm+deterministic" in modes.values()          # the LLM path really ran
    assert modes["aggressive_agent"] == "deterministic"   # rapid triage never calls the LLM


def test_agent_failure_is_contained(orchestrator, small_kb, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("simulated crash")
    monkeypatch.setattr(orchestrator.pattern_recognition, "deterministic", boom)
    r = run(orchestrator, small_kb, CLEAR_BEARING)
    assert any(t["status"] == "error" for t in r["harness"]["timeline"])
    assert r["final_diagnosis"]


def test_real_mode_uses_only_real_evidence(orchestrator, small_kb):
    r = run(orchestrator, small_kb, CLEAR_BEARING, mode="real")
    assert {e["source_type"] for e in r["harness"]["evidence"]} == {"real"}
    r = run(orchestrator, small_kb, CLEAR_BEARING, mode="synthetic")
    assert {e["source_type"] for e in r["harness"]["evidence"]} == {"synthetic"}


def test_empty_query_profile_is_handled(orchestrator, small_kb):
    r = run(orchestrator, small_kb, "What is the root cause of the gearbox failure?")
    assert r["harness"]["predicted_label"] == "Insufficient Evidence"
