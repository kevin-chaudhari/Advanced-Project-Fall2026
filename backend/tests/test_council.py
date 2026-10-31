"""Agent council: agents talk to each other on hard cases, without inflating confidence."""
import asyncio

import harness.council as council
from harness.schema import DiagnosticState
from tests.test_harness import CLEAR_BEARING, CONTRADICTORY, MISSING_TEMP


def run(orch, kb, q, mode="combined"):
    return asyncio.run(orch.run_harness(q, "afrb", mode, kb, embedder=None, store=None))


def test_clear_case_does_not_convene(orchestrator, small_kb):
    h = run(orchestrator, small_kb, CLEAR_BEARING)["harness"]
    assert h["council"]["convened"] is False
    # the escalation council posts nothing; the agents still collaborate on every case
    assert [m for m in h["messages"] if m["phase"] == "council"] == []
    assert any(m["phase"] == "collaboration" for m in h["messages"])
    assert h["council"]["messages"] == 0


def test_collaboration_off_restores_silent_clear_case(orchestrator, small_kb, monkeypatch):
    monkeypatch.setenv("COLLAB_MODE", "off")
    h = run(orchestrator, small_kb, CLEAR_BEARING)["harness"]
    assert h["messages"] == []


def test_hard_case_convenes_and_messages_are_traceable(orchestrator, small_kb):
    h = run(orchestrator, small_kb, MISSING_TEMP)["harness"]
    c = h["council"]
    assert c["convened"] and c["reasons"]
    msgs = h["messages"]
    assert [m["message_id"] for m in msgs] == [f"M-{i + 1:03d}" for i in range(len(msgs))]
    council_msgs = [m for m in msgs if m["phase"] == "council"]
    valid = {e["evidence_id"] for e in h["evidence"]} | {d["derived_id"] for d in h["derived_values"]}
    assert all(set(m["evidence_ids"]) <= valid for m in msgs)
    assert msgs[-1]["kind"] == "SYNTHESIS" and msgs[-1]["sender"] == "human_review_coordinator"
    senders = {m["sender"] for m in msgs}
    assert {"ambiguity", "human_review_coordinator"} <= senders
    # an unmeasured channel can only be resolved by a person
    assert "temperature" in c["human_inputs"]
    assert c["confidence_before"] is not None and c["confidence_after"] is not None


def test_council_off_posts_nothing(orchestrator, small_kb, monkeypatch):
    monkeypatch.setattr(council, "COUNCIL_MODE", "off")
    h = run(orchestrator, small_kb, MISSING_TEMP)["harness"]
    assert h["council"]["convened"] is False and [m for m in h["messages"] if m["phase"] == "council"] == []


def test_rapid_triage_holds_on_safety_rule(orchestrator, small_kb, monkeypatch):
    monkeypatch.setattr(council, "COUNCIL_MODE", "always")
    h = run(orchestrator, small_kb, CONTRADICTORY)["harness"]
    holds = [m for m in h["messages"] if m["sender"] == "aggressive_agent" and m["kind"] == "CONCESSION"]
    assert not holds, "Rapid Triage must not concede while a consistency rule is violated"


def test_single_or_disagreeing_views_never_rescore():
    st = DiagnosticState(run_id="t", query="q", dataset_type="afrb", data_mode="real")
    st.analysis["hypotheses"] = [{"label": "A", "score": 0.4}, {"label": "B", "score": 0.35}, {"label": "C", "score": 0.25}]
    # one view alone is not enough
    assert council.apply_pair_resolution(st, "A", "B", {"precedent": {"A": 0.9, "B": 0.1}}, 1) is None
    # two views that disagree are not enough
    assert council.apply_pair_resolution(st, "A", "B", {"precedent": {"A": 0.9, "B": 0.1},
                                                       "signature": {"A": 0.2, "B": 0.8}}, 1) is None
    # two agreeing views move the pair a little, once, and keep the pair total
    res = council.apply_pair_resolution(st, "A", "B", {"precedent": {"A": 0.8, "B": 0.2},
                                                      "signature": {"A": 0.7, "B": 0.3}}, 1)
    assert res and abs(sum(res["after"].values()) - 0.75) < 1e-6
    assert res["after"]["A"] - res["before"]["A"] < 0.06
    assert council.apply_pair_resolution(st, "A", "B", {"precedent": {"A": 0.8, "B": 0.2},
                                                       "signature": {"A": 0.7, "B": 0.3}}, 2) is None
