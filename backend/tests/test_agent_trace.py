"""Collaborative council + AgentTrace: the agents build the finding together, observably and persistently."""
import asyncio
import json
import os
import subprocess
import sys
from functools import lru_cache
from pathlib import Path

import pandas as pd
import pytest

import agents.orchestrator as orch_mod
from agents.diagnostic_expert import DiagnosticExpertAgent
from agents.pattern_recognition import PatternRecognitionAgent
from harness.agent_trace.trace_analyzer import build_semantic, evidence_view
from harness.agent_trace.trace_manager import TraceRecorder
from harness.agent_trace.trace_repository import TraceReader, db_path, link_analysis
from harness.agent_trace.trace_schema import EventType
from harness.collaboration import PARTICIPANTS, pool
from harness.schema import DiagnosticState, EvidenceStatement
from tests.test_harness import CLEAR_BEARING, CONTRADICTORY, MISSING_TEMP
from utils.llm_client import llm_client

BACKEND = Path(__file__).resolve().parent.parent
SCEN = pd.read_csv(BACKEND / "data" / "synthetic" / "test_scenarios.csv")
SIX = {"diagnostic_expert", "pattern_agent", "aggressive_agent", "verification", "ambiguity", "human_review_coordinator"}
COLLAB = ("collaboration", "resync")


def run(orch, kb, q, mode="combined"):
    return asyncio.run(orch.run_harness(q, "afrb", mode, kb, embedder=None, store=None))


def trace_of(res):
    tid = res["harness"]["trace_id"]
    assert tid and tid.startswith("TR-")
    return tid, TraceReader()


def events(reader, tid, et=None):
    return reader.events(tid, limit=100000, event_type=et)[0]


def find_case(orch, kb, predicate, limit=120):
    """First scenario (in file order) whose run satisfies ``predicate`` — keeps tests independent of tuning."""
    for q in SCEN.question[:limit]:
        res = run(orch, kb, q)
        if predicate(res):
            return q, res
    pytest.skip("no scenario in the file shows this behaviour")


def collab_msgs(res, kinds=None):
    return [m for m in res["harness"]["messages"] if m["phase"] in COLLAB and (not kinds or m["kind"] in kinds)]


# ── pooling rule ─────────────────────────────────────────────────────────────
def test_pooling_moves_toward_peers_by_openness():
    labels = ["A", "B"]
    own = {"A": 0.7, "B": 0.3}
    peer = {"A": 0.2, "B": 0.8}
    assert pool(own, [], 0.5, labels) == pytest.approx(own)
    stubborn, open_ = pool(own, [peer], 0.1, labels), pool(own, [peer], 0.6, labels)
    assert stubborn["A"] > open_["A"] and open_["A"] < own["A"]
    flat = pool(own, [{"A": 0.5, "B": 0.5}], 0.5, labels)     # a uniform peer tempers the view, never re-ranks it
    assert 0.5 < flat["A"] < own["A"]


# ── 1. six agents execute and all of them take part ─────────────────────────
def test_six_agents_execute_and_collaborate(orchestrator, small_kb):
    res = run(orchestrator, small_kb, MISSING_TEMP)
    tid, r = trace_of(res)
    execs = r.executions(tid)
    assert {x["agent_id"] for x in execs if x["kind"] == "analyze" and x["status"] == "COMPLETED"} == SIX
    assert {x["agent_id"] for x in execs if x["kind"].startswith("collab_")} == SIX
    t = r.get_trace(tid)
    assert t["status"] == "COMPLETED" and t["final_label"] == res["harness"]["predicted_label"]
    for x in execs:
        assert x["seq_end"] > x["seq_start"] and x["completed_at"]


# ── 2. positions travel by message and are read before anyone updates ───────
def test_positions_are_shared_and_read_before_updating(orchestrator, small_kb):
    res = run(orchestrator, small_kb, MISSING_TEMP)
    tid, r = trace_of(res)
    msgs = r.messages(tid)
    shares = [m for m in msgs if m["stage"] == "collaboration" and m["payload"].get("draft")]
    assert {m["sender_agent_id"] for m in shares} == set(PARTICIPANTS)
    for m in shares:
        readers = {d["receiver"] for d in m["deliveries"] if d["via"] == "inbox_read"}
        assert set(PARTICIPANTS) - {m["sender_agent_id"]} <= readers, m["message_id"]
    updates = [m for m in msgs if m["message_type"] in ("POSITION_UPDATE", "HOLD") and m["stage"] == "collaboration"]
    assert updates
    sent_seq = {m["message_id"]: m["seq"] for m in msgs}
    for u in updates:
        for peer in u["payload"]["read_positions_from"]:
            # the peer's position message was read by this agent before it posted its update
            peer_pos = [m for m in shares if m["sender_agent_id"] == peer][0]
            read = [d for d in peer_pos["deliveries"] if d["receiver"] == u["sender_agent_id"]]
            assert read and read[0]["seq"] < u["seq"]
        assert sent_seq[u["message_id"]] == u["seq"]


# ── 3. agents challenge each other and answer ───────────────────────────────
def test_agents_challenge_and_answer_in_the_council(orchestrator, small_kb):
    _, res = find_case(orchestrator, small_kb, lambda r: collab_msgs(r, ("CHALLENGE", "COUNTER_ARGUMENT")))
    tid, r = trace_of(res)
    msgs = r.messages(tid)
    c = next(m for m in msgs if m["stage"] in COLLAB and m["message_type"] in ("CHALLENGE", "COUNTER_ARGUMENT"))
    target = c["receiver_agent_ids"][0]
    assert c["payload"]["your_label"] != c["payload"]["proposed"]
    reply = [m for m in msgs if m["response_to_message_id"] == c["message_id"]]
    assert reply and reply[0]["sender_agent_id"] == target
    assert reply[0]["message_type"] in ("RESPONSE", "CONCESSION")
    assert any(h["status"] == "CHALLENGED" and h["agent_id"] == target for h in r.hypothesis_states(tid))


# ── 4. questions, evidence shares and verification requests ─────────────────
def test_agents_ask_share_and_request_verification(orchestrator, small_kb):
    res = run(orchestrator, small_kb, MISSING_TEMP)
    tid, r = trace_of(res)
    msgs = {m["message_id"]: m for m in r.messages(tid)}
    q = next(m for m in msgs.values() if m["message_type"] == "QUESTION" and m["payload"].get("need") == "separate")
    assert q["sender_agent_id"] == "ambiguity"
    answers = [m for m in msgs.values() if m["response_to_message_id"] == q["message_id"]]
    assert {a["sender_agent_id"] for a in answers} == {"diagnostic_expert", "pattern_agent"}
    reqs = [m for m in msgs.values() if m["message_type"] == "VERIFICATION_REQUEST"]
    assert len(reqs) == 3 and all(m["resolution_status"] == "RESOLVED" for m in reqs)
    for q in reqs:
        assert any(m["message_type"] == "VERIFICATION_RESULT" and m["response_to_message_id"] == q["message_id"]
                   for m in msgs.values())


# ── 5. an agent changes its mind and the change is traceable to messages ────
def test_position_change_is_recorded_and_applied(orchestrator, small_kb):
    def changed(r):
        return any(m["kind"] in ("POSITION_UPDATE", "CONCESSION") and m["payload"].get("new_label")
                   and m["sender"] in ("diagnostic_expert", "pattern_agent", "aggressive_agent") for m in collab_msgs(r))
    _, res = find_case(orchestrator, small_kb, changed)
    tid, r = trace_of(res)
    m = next(m for m in r.messages(tid) if m["stage"] in COLLAB and m["payload"].get("new_label")
             and m["sender_agent_id"] in ("diagnostic_expert", "pattern_agent", "aggressive_agent"))
    states = [h for h in r.hypothesis_states(tid) if h["agent_id"] == m["sender_agent_id"]]
    assert any(h["status"] == "MODIFIED" and h["message_id"] == m["message_id"] for h in states)
    assert any(h["status"] == "REJECTED" for h in states)
    # the agent's report carries its post-discussion position and its draft
    rep = res["harness"]["agents"][m["sender_agent_id"]]
    assert rep["extras"]["collab_position"] and rep["extras"]["own_view"]
    assert rep["extras"]["position_history"][0]["phase"] == "draft"


# ── 6. a disagreement can stay open ─────────────────────────────────────────
def test_dissent_can_remain_unresolved(orchestrator, small_kb):
    _, res = find_case(orchestrator, small_kb,
                       lambda r: any(m["resolved"] is False for m in collab_msgs(r, ("CHALLENGE", "COUNTER_ARGUMENT"))))
    tid, r = trace_of(res)
    open_ = [m for m in r.messages(tid) if m["stage"] in COLLAB and m["resolution_status"] == "UNRESOLVED"
             and m["message_type"] in ("CHALLENGE", "COUNTER_ARGUMENT")]
    assert open_ and "still backs" in open_[0]["payload"]["outcome"]
    assert any(e["message_id"] == open_[0]["message_id"] for e in events(r, tid, "DISAGREEMENT_UNRESOLVED"))
    assert build_semantic(r, tid)["summary"]["unresolved_disagreements"] >= 1


# ── 7 + 15. verification rejects an unsupported claim; missing IDs handled ──
def test_verification_rejects_unsupported_claim_and_missing_ids(orchestrator, small_kb, monkeypatch):
    orig = DiagnosticExpertAgent.deterministic
    bad = "Bearing housing vibration reached 9.87 mm/s during the last shift [EV-999]"

    def with_bad_claim(self, state, ctx, **kw):
        rep = orig(self, state, ctx, **kw)
        rep.supporting_evidence.insert(0, EvidenceStatement(statement=bad, evidence_ids=["EV-999"]))
        return rep
    monkeypatch.setattr(DiagnosticExpertAgent, "deterministic", with_bad_claim)
    tid, r = trace_of(run(orchestrator, small_kb, CLEAR_BEARING))
    msgs = r.messages(tid)
    req = next(m for m in msgs if m["message_type"] == "VERIFICATION_REQUEST" and m["sender_agent_id"] == "diagnostic_expert")
    assert "EV-999" in req["evidence_ids"] and req["payload"]["_trace_unknown_evidence_ids"] == ["EV-999"]
    res = next(m for m in msgs if m["response_to_message_id"] == req["message_id"])
    flagged = [x for x in res["payload"]["results"] if x["status"] == "UNSUPPORTED"]
    assert flagged and flagged[0]["missing_ids"] == ["EV-999"]
    ack = [m for m in msgs if m["response_to_message_id"] == res["message_id"]]
    assert ack and flagged[0]["claim_id"] in ack[0]["payload"]["withdrawn_claims"]
    assert "EV-999" not in {e["evidence_id"] for e in r.evidence(tid)}
    assert build_semantic(r, tid)["summary"]["unsupported_claims_flagged"] >= 1


# ── 8. targeted retrieval re-executes agents and the council re-syncs ───────
def test_targeted_retrieval_triggers_resync(orchestrator, small_kb):
    tid, r = trace_of(run(orchestrator, small_kb, MISSING_TEMP))
    assert events(r, tid, "FEEDBACK_LOOP_TRIGGERED") and events(r, tid, "TARGETED_RETRIEVAL_STARTED")
    assert any(e["payload"]["stage"] == "targeted_rerun" for e in events(r, tid, "AGENT_REEXECUTED"))
    resync = [m for m in r.messages(tid) if m["stage"] == "resync"]
    assert resync and any(m["payload"].get("resumed") for m in resync)
    joints = [e for e in events(r, tid, "JOINT_FINDING_REACHED")]
    assert [e["payload"]["phase"] for e in joints][:2] == ["collaboration", "resync"]
    targeted = {i for e in events(r, tid, "EVIDENCE_RETRIEVED") if e["payload"]["action"] != "initial" for i in e["evidence_ids"]}
    x = next(x for x in r.executions(tid) if x["stage"] == "targeted_rerun")
    assert targeted and targeted & set(x["evidence_in_input"])


# ── 9. round limits ─────────────────────────────────────────────────────────
def test_collaboration_and_council_round_limits(orchestrator, small_kb, monkeypatch):
    monkeypatch.setenv("COLLAB_MAX_ROUNDS", "1")
    monkeypatch.setattr(orch_mod, "COUNCIL_MAX_ROUNDS", 1)
    tid, r = trace_of(run(orchestrator, small_kb, MISSING_TEMP))
    done = [e for e in events(r, tid, "COLLABORATION_ROUND_COMPLETED") if e["payload"]["phase"] == "collaboration"]
    assert len(done) == 1
    council_rounds = {m["round_id"] for m in r.messages(tid) if m["stage"] == "council"}
    assert len(council_rounds) == 1
    assert len(events(r, tid, "COUNCIL_ROUND_COMPLETED")) == 1


# ── 10. an agent fails during execution ─────────────────────────────────────
def test_agent_failure_is_recorded_and_agent_abstains(orchestrator, small_kb, monkeypatch):
    def boom(self, state, ctx, **kw):
        raise RuntimeError("simulated pattern-store outage")
    monkeypatch.setattr(PatternRecognitionAgent, "deterministic", boom)
    res = run(orchestrator, small_kb, CLEAR_BEARING)
    tid, r = trace_of(res)
    assert r.get_trace(tid)["status"] == "COMPLETED_WITH_ERRORS"
    failed = [x for x in r.executions(tid) if x["status"] == "FAILED"]
    assert failed and failed[0]["agent_id"] == "pattern_agent" and "outage" in failed[0]["error"]
    assert events(r, tid, "AGENT_FAILED")
    share = next(m for m in r.messages(tid) if m["sender_agent_id"] == "pattern_agent" and m["stage"] == "collaboration")
    assert share["payload"].get("abstain") is True          # a failed agent does not vote
    assert res["final_diagnosis"]


def test_pipeline_failure_marks_trace_failed_and_keeps_prior_events(orchestrator, small_kb, monkeypatch):
    def boom(self, state, ctx):
        raise RuntimeError("evidence check crashed")
    monkeypatch.setattr(orch_mod.AgentOrchestrator, "_evidence_check", boom)
    with pytest.raises(RuntimeError):
        run(orchestrator, small_kb, CLEAR_BEARING)
    r = TraceReader()
    tid = r.list_traces(limit=1, status="FAILED")[0][0]["trace_id"]
    assert "evidence check crashed" in r.get_trace(tid)["error"]
    types = [e["event_type"] for e in events(r, tid)]
    assert types[-1] == "TRACE_FAILED" and "JOINT_FINDING_REACHED" in types and "MESSAGE_SENT" in types


# ── 11. traces survive a backend restart ────────────────────────────────────
def test_trace_survives_restart(orchestrator, small_kb):
    tid, r = trace_of(run(orchestrator, small_kb, MISSING_TEMP))
    n_msgs, n_ev = len(r.messages(tid)), len(events(r, tid))
    code = ("import sys, json; sys.path.insert(0, %r);"
            "from harness.agent_trace.trace_repository import TraceReader;"
            "r = TraceReader(); t = r.get_trace(%r);"
            "print(json.dumps([t['status'], len(r.messages(%r)), r.events(%r)[1]]))") % (str(BACKEND), tid, tid, tid)
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=str(BACKEND),
                         env={**os.environ, "AGENT_TRACE_DB_PATH": db_path()}, check=True).stdout
    assert json.loads(out.strip().splitlines()[-1]) == ["COMPLETED", n_msgs, n_ev]


# ── 12. concurrent analyses never mix ───────────────────────────────────────
def test_concurrent_analyses_do_not_mix(orchestrator, small_kb):
    async def both():
        return await asyncio.gather(
            orchestrator.run_harness(CLEAR_BEARING, "afrb", "combined", small_kb),
            orchestrator.run_harness(CONTRADICTORY, "afrb", "real", small_kb))
    a, b = asyncio.run(both())
    r = TraceReader()
    assert a["harness"]["trace_id"] != b["harness"]["trace_id"]
    for res, q, mode in ((a, CLEAR_BEARING, "combined"), (b, CONTRADICTORY, "real")):
        tid = res["harness"]["trace_id"]
        t = r.get_trace(tid)
        assert t["query"] == q and t["data_mode"] == mode and t["final_label"] == res["harness"]["predicted_label"]
        msgs = r.messages(tid)
        assert [m["message_content"] for m in msgs] == [m["text"] for m in res["harness"]["messages"]]
        seqs = [e["seq"] for e in events(r, tid)]
        assert seqs == sorted(set(seqs))
        assert {e["evidence_id"] for e in r.evidence(tid) if e["kind"] == "record"} == \
            {e["evidence_id"] for e in res["harness"]["evidence"]}
    assert all(e["provenance"] == "REAL" for e in r.evidence(b["harness"]["trace_id"]) if e["kind"] == "record")


# ── 13. deterministic mode generates a structurally valid trace ─────────────
def _assert_valid(r, tid):
    evs = events(r, tid)
    assert {e["event_type"] for e in evs} <= {t.value for t in EventType}
    assert evs[0]["event_type"] == "TRACE_STARTED" and evs[-1]["event_type"] == "TRACE_COMPLETED"
    seqs = [e["seq"] for e in evs]
    assert seqs == sorted(set(seqs))
    msgs = r.messages(tid)
    sent = {e["message_id"] for e in evs if e["event_type"] == "MESSAGE_SENT"}
    assert {m["message_id"] for m in msgs} == sent
    known = {e["evidence_id"] for e in r.evidence(tid)}
    for m in msgs:
        assert set(m["evidence_ids"]) - known == set(m["payload"].get("_trace_unknown_evidence_ids", [])), m["message_id"]
        if m["response_to_message_id"]:
            assert m["response_to_message_id"] in sent
    assert all(l["evidence_id"] in known for l in r.evidence_links(tid))
    assert all(x["status"] in ("COMPLETED", "FAILED") for x in r.executions(tid))


def test_deterministic_trace_is_valid(orchestrator, small_kb):
    tid, r = trace_of(run(orchestrator, small_kb, MISSING_TEMP))
    _assert_valid(r, tid)
    flow = evidence_view(r, tid)
    assert flow and all(f["rendered_status"] == "NOT_APPLICABLE" for f in flow)
    assert all(not x["llm_calls"] for x in r.executions(tid))
    assert all(m["payload"].get("voice") in (None, "method") for m in r.messages(tid))


# ── 14. LLM mode: GPT voices the council, numbers stay the methods' ─────────
def _fake_llm(calls):
    async def fake_raw(prompt, system, model=None, temperature=None):
        calls.append({"prompt": prompt, "system": system, "model": model})
        try:
            data = json.loads(prompt)
        except ValueError:
            return json.dumps({"narrative": "The cited records EV-001 and EV-002 are consistent with the leading hypothesis."})
        if data.get("message_type") == "FINDING":           # an invented reading must be rejected
            return json.dumps({"text": data["DRAFT"] + " Vibration was 9.99 mm/s yesterday."})
        return json.dumps({"text": "Colleagues, " + data["DRAFT"]})
    return fake_raw


def test_llm_mode_voices_messages_and_keeps_decisions(orchestrator, small_kb, monkeypatch):
    baseline = run(orchestrator, small_kb, MISSING_TEMP)
    calls = []
    monkeypatch.setattr(llm_client, "is_available", lambda: True)
    monkeypatch.setattr(llm_client, "provider", "openai")
    monkeypatch.setattr(llm_client, "_openai_raw", _fake_llm(calls))
    res = run(orchestrator, small_kb, MISSING_TEMP)
    tid, r = trace_of(res)
    assert res["harness"]["predicted_label"] == baseline["harness"]["predicted_label"]
    assert res["confidence"] == baseline["confidence"] and res["review_decision"] == baseline["review_decision"]
    voice_calls = [c for c in calls if c["model"] == "gpt-4.1"]            # COUNCIL_LLM_MODEL default
    assert voice_calls and all("one of six agents" in c["system"] for c in voice_calls)
    msgs = r.messages(tid)
    voiced = [m for m in msgs if m["payload"].get("voice") == "llm"]
    rejected = [m for m in msgs if m["payload"].get("voice_rejected")]
    assert voiced and all(m["message_content"].startswith("Colleagues, ") and m["payload"]["method_text"] for m in voiced)
    assert rejected and all(m["message_type"] == "FINDING" and "9.99" not in m["message_content"] for m in rejected)
    collab_x = [x for x in r.executions(tid) if x["kind"].startswith("collab_") and x["llm_calls"]]
    assert collab_x and all(c["model"] == "gpt-4.1" for x in collab_x for c in x["llm_calls"])
    assert all(x["rendered_input"] for x in collab_x)
    assert r.get_trace(tid)["config"]["council_llm_model"] == "gpt-4.1"
    _assert_valid(r, tid)


def test_council_llm_model_is_configurable(orchestrator, small_kb, monkeypatch):
    calls = []
    monkeypatch.setenv("COUNCIL_LLM_MODEL", "o4-mini")
    monkeypatch.setattr(llm_client, "is_available", lambda: True)
    monkeypatch.setattr(llm_client, "provider", "openai")
    monkeypatch.setattr(llm_client, "_openai_raw", _fake_llm(calls))
    run(orchestrator, small_kb, CLEAR_BEARING)
    assert any(c["model"] == "o4-mini" for c in calls)


# ── confidence: the council can lower, never raise, the evidence confidence ──
@pytest.mark.parametrize("q", [CLEAR_BEARING, MISSING_TEMP, CONTRADICTORY])
def test_council_confidence_is_capped_by_evidence(orchestrator, small_kb, q):
    c = run(orchestrator, small_kb, q)["harness"]["confidence"]
    assert c["council_confidence"] is not None and c["evidence_confidence"] is not None
    assert c["confidence"] <= c["evidence_confidence"] + 1e-9
    assert any(f["name"] == "council_agreement" for f in c["factors"])


def test_collaboration_off_restores_independent_first_pass(orchestrator, small_kb, monkeypatch):
    monkeypatch.setenv("COLLAB_MODE", "off")
    h = run(orchestrator, small_kb, MISSING_TEMP)["harness"]
    assert not [m for m in h["messages"] if m["phase"] in COLLAB]
    assert h["confidence"]["council_confidence"] is None
    assert h["confidence"]["confidence"] == h["confidence"]["evidence_confidence"]


# ── 16. duplicate events are handled safely ─────────────────────────────────
def test_duplicate_events_are_ignored(tmp_path):
    rec = TraceRecorder(run_id="abcdef012345", query="q", dataset_type="afrb", data_mode="real",
                        llm_mode="deterministic", path=str(tmp_path / "dup.db"))
    st = DiagnosticState(run_id="abcdef012345", query="q", dataset_type="afrb", data_mode="real")
    rec.attach(st)
    a = rec.event(EventType.QUERY_PREPARED, actor="harness", dedup_key="once")
    b = rec.event(EventType.QUERY_PREPARED, actor="harness", dedup_key="once")
    assert a and b is None
    m = st.post(round=1, sender="diagnostic_expert", kind="FINDING", text="x", recipients=["pattern_agent"],
                evidence_ids=["EV-404"], phase="collaboration")
    rec.on_post(st, m)
    st.inbox("pattern_agent", 1)
    st.inbox("pattern_agent", 1)
    rec.complete(st, {})
    r = TraceReader(str(tmp_path / "dup.db"))
    msgs = r.messages(rec.trace_id)
    assert len(msgs) == 1 and len(msgs[0]["deliveries"]) == 1 and msgs[0]["stage"] == "collaboration"
    evs = r.events(rec.trace_id, limit=1000)[0]
    assert sum(e["event_type"] == "QUERY_PREPARED" for e in evs) == 1
    assert sum(e["event_type"] == "MESSAGE_SENT" for e in evs) == 1
    assert msgs[0]["payload"]["_trace_unknown_evidence_ids"] == ["EV-404"]


# ── 17. trace API endpoints ─────────────────────────────────────────────────
def test_trace_api_endpoints(orchestrator, small_kb):
    from fastapi.testclient import TestClient
    import main
    tid, _ = trace_of(run(orchestrator, small_kb, MISSING_TEMP))
    c = TestClient(main.app)
    lst = c.get("/traces", params={"limit": 200}).json()
    assert tid in [t["trace_id"] for t in lst["traces"]]
    full = c.get(f"/traces/{tid}").json()
    assert full["summary"]["total_agents"] == 6 and full["graph"]["edges"]
    pos = full["positions"]
    assert set(pos["agents"]) >= set(PARTICIPANTS) and pos["joint"] and pos["columns"][0]["phase"] == "collaboration"
    assert full["summary"]["collaboration"]["joint_label"]
    page = c.get(f"/traces/{tid}/events", params={"limit": 10, "offset": 5}).json()
    assert len(page["events"]) == 10 and page["total"] > 15
    assert c.get(f"/traces/{tid}/events", params={"event_type": "MESSAGE_SENT"}).json()["total"] == \
        len(c.get(f"/traces/{tid}/messages").json()["messages"])
    assert set(c.get(f"/traces/{tid}/agents").json()["agents"]) == SIX
    seg = c.get(f"/traces/{tid}/timeline").json()["segments"]
    assert seg[0]["label"] == "Collaboration, round 1" and seg[-1]["label"] == "Final synthesis"
    assert {s["phase"] for s in seg} >= {"collaboration", "verification", "council", "synthesis"}
    assert c.get(f"/traces/{tid}/evidence").json()["evidence"]
    assert c.get(f"/traces/{tid}/hypotheses").json()["states"]
    link_analysis(tid, 987654)
    assert c.get("/analyses/987654/trace").json()["trace_id"] == tid
    assert c.get("/traces/TR-20990101000000-deadbeef").status_code == 404
    assert c.get("/traces/not-a-trace").status_code == 422


def test_tracing_disabled_still_diagnoses(orchestrator, small_kb, monkeypatch):
    monkeypatch.setenv("AGENT_TRACE_ENABLED", "0")
    res = run(orchestrator, small_kb, CLEAR_BEARING)
    assert res["harness"]["trace_id"] is None and res["harness"]["predicted_label"] == "Bearing Wear"


# ── export: API downloads and the standalone script produce the same files ──
def test_trace_export_api_and_script(orchestrator, small_kb, tmp_path):
    import io
    import zipfile
    from fastapi.testclient import TestClient
    import main
    tid, _ = trace_of(run(orchestrator, small_kb, MISSING_TEMP))
    c = TestClient(main.app)
    full = c.get(f"/traces/{tid}/export", params={"format": "json"})
    assert full.status_code == 200 and f'filename="{tid}.json"' in full.headers["content-disposition"]
    b = full.json()
    assert b["trace"]["trace_id"] == tid and b["messages"] and b["events"] and b["executions"] and b["positions"]
    md = c.get(f"/traces/{tid}/export", params={"format": "transcript"}).text
    assert md.startswith(f"# Agent conversation — {tid}") and "## Collaboration, round 1" in md
    csv_text = c.get(f"/traces/{tid}/export", params={"format": "messages_csv"}).text
    assert csv_text.splitlines()[0].startswith("seq,message_id") and len(csv_text.splitlines()) > len(b["messages"])
    assert c.get(f"/traces/{tid}/export", params={"format": "pdf"}).status_code == 422
    z = zipfile.ZipFile(io.BytesIO(c.get("/traces/export/archive", params={"limit": 2}).content))
    assert "index.json" in z.namelist() and any(n.endswith(".md") for n in z.namelist())
    out = subprocess.run([sys.executable, str(BACKEND / "scripts" / "export_traces.py"), "--trace-id", tid,
                          "--format", "all", "--out", str(tmp_path)], capture_output=True, text=True,
                         env={**os.environ, "AGENT_TRACE_DB_PATH": db_path()})
    assert out.returncode == 0, out.stderr
    files = sorted(p.name for p in tmp_path.iterdir())
    from harness.agent_trace.trace_export import FORMATS
    assert len(files) == len(FORMATS) and f"{tid}.json" in files and f"{tid}.md" in files
    assert f"{tid}.llm_calls.csv" in files and f"{tid}.scores.csv" in files
    assert (tmp_path / f"{tid}.md").read_text(encoding="utf-8") == md


# ── schema 1.1: full model responses, evidence content, score changes, code version ──

LONG_TAIL = " ".join(f"word{i}" for i in range(900))       # > 2,000 characters: the old excerpt limit


def _fake_openai_http(monkeypatch, n=None):
    """Answer /chat/completions like OpenAI does (usage, id, fingerprint, headers) — exercises the real client code."""
    import httpx
    n = n if n is not None else [0]

    async def post(self, url, json=None, headers=None, **kw):
        n[0] += 1
        body = json["messages"][-1]["content"]
        try:
            txt = {"text": __import__("json").loads(body).get("DRAFT", "ok")}
        except ValueError:
            txt = {"narrative": "The cited records EV-001 and EV-002 are consistent. " + LONG_TAIL}
        content = __import__("json").dumps(txt)
        data = {"id": f"chatcmpl-{n[0]}", "object": "chat.completion", "created": 1793650000,
                "model": json["model"] + "-2025-04-14", "system_fingerprint": "fp_test",
                "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 100 + n[0], "completion_tokens": 7, "total_tokens": 107 + n[0],
                          "prompt_tokens_details": {"cached_tokens": 0}}}
        return httpx.Response(200, json=data, headers={"x-request-id": f"req_{n[0]}"}, request=httpx.Request("POST", url))
    monkeypatch.setattr(httpx.AsyncClient, "post", post)
    monkeypatch.setattr(llm_client, "provider", "openai")
    monkeypatch.setattr(llm_client, "openai_key", "sk-test-SECRET-should-never-be-stored")
    monkeypatch.setenv("HARNESS_USE_LLM", "1")
    return n


def test_full_model_responses_with_usage_and_metadata(orchestrator, small_kb, monkeypatch):
    _fake_openai_http(monkeypatch)
    tid, r = trace_of(run(orchestrator, small_kb, MISSING_TEMP))
    calls = r.llm_calls(tid)
    execs = {x["execution_id"]: x for x in r.executions(tid)}
    assert calls and len(calls) == sum(len(x["llm_calls"] or []) for x in execs.values())
    long = [c for c in calls if LONG_TAIL in (c["response_raw"] or "")]
    assert long, "a response longer than the old 2,000-character excerpt must be stored whole"
    for c in calls:
        assert c["ok"] and len(c["response_raw"]) == c["response_chars"]
        assert c["total_tokens"] == c["prompt_tokens"] + 7 and c["usage"]["prompt_tokens_details"] == {"cached_tokens": 0}
        assert c["finish_reason"] == "stop" and c["response_model"].endswith("-2025-04-14")
        assert c["response_meta"]["id"].startswith("chatcmpl-") and c["response_meta"]["x_request_id"].startswith("req_")
        assert c["response_meta"]["system_fingerprint"] == "fp_test" and "messages" not in (c["request"] or {})
        assert c["agent_id"] == execs[c["execution_id"]]["agent_id"]
    s = build_semantic(r, tid)["summary"]["llm_usage"]
    assert s["total_tokens"] == sum(c["total_tokens"] for c in calls) and s["calls_without_usage"] == 0
    # nothing secret: the API key / Authorization header appears nowhere in the trace store
    import sqlite3
    con = sqlite3.connect(db_path())
    dump = "\n".join(con.iterdump())
    con.close()
    assert "SECRET-should-never-be-stored" not in dump and "Bearer" not in dump


def test_failed_model_call_keeps_status_and_error_body(orchestrator, small_kb, monkeypatch):
    import httpx
    _fake_openai_http(monkeypatch)

    async def post(self, url, json=None, headers=None, **kw):
        return httpx.Response(429, json={"error": {"message": "Rate limit reached", "type": "requests"}},
                              request=httpx.Request("POST", url))
    monkeypatch.setattr(httpx.AsyncClient, "post", post)
    tid, r = trace_of(run(orchestrator, small_kb, MISSING_TEMP))
    calls = r.llm_calls(tid)
    assert calls and all(not c["ok"] and c["response_raw"] is None for c in calls)
    assert all("Rate limit reached" in c["error"] and c["response_meta"]["http_status"] == 429 for c in calls)


def test_evidence_records_keep_full_content(orchestrator, small_kb):
    res = run(orchestrator, small_kb, MISSING_TEMP)
    tid, r = trace_of(res)
    stored = {e["evidence_id"]: e for e in r.evidence(tid)}
    live = res["harness"]["evidence"]
    assert live
    for e in live:                               # every retrieved record, field for field
        row = stored[e["evidence_id"]]
        assert row["content"] == json.loads(json.dumps(e["content"], default=str))
        assert row["content_text"] == e["content_text"] and row["description"] == e["selection_reason"]
        assert row["content_sha256"] and row["record_id"] == e["record_id"]
    derived = [e for e in stored.values() if e["kind"] == "derived"]
    assert derived and all(set(d["content"]) == {"value", "text", "inputs"} for d in derived)
    flow = {x["evidence_id"]: x for x in evidence_view(r, tid)}
    assert flow[live[0]["evidence_id"]]["content"] == stored[live[0]["evidence_id"]]["content"]


def _assert_chain(changes, final_scores):
    hyp = [c for c in changes if c["quantity"] == "hypothesis_score"]
    assert hyp[0]["operation"] == "initial_scoring" and hyp[0]["before"] == {}
    for a, b in zip(hyp, hyp[1:]):               # nothing changed the scores without being recorded
        assert set(a["after"]) == set(b["before"]) and all(abs(a["after"][k] - b["before"][k]) < 1e-9 for k in a["after"])
    for c in changes:
        for l in set(c["before"]) | set(c["after"]):
            assert c["delta"][l] == pytest.approx(c["after"].get(l, 0.0) - c["before"].get(l, 0.0), abs=1e-6)
        assert c["max_abs_delta"] == pytest.approx(max(abs(v) for v in c["delta"].values()), abs=1e-6)
    last = hyp[-1]["after"]                      # the run's final ranking (top 8 reported) is the last recorded "after"
    assert set(final_scores) <= set(last) and all(abs(last[k] - final_scores[k]) < 1e-9 for k in final_scores)


def test_score_changes_before_after_every_blend_and_rescore(orchestrator, small_kb):
    def conflict(res):
        return any(c["operation"] == "conflict_rescore" for c in TraceReader().score_changes(res["harness"]["trace_id"]))
    _, res = find_case(orchestrator, small_kb, conflict)
    tid, r = trace_of(res)
    changes = r.score_changes(tid)
    ops = [c["operation"] for c in changes]
    assert "council_blend" in ops and "conflict_rescore" in ops
    _assert_chain(changes, {h["label"]: h["score"] for h in res["harness"]["hypothesis_scores"]})
    blend = next(c for c in changes if c["operation"] == "council_blend")
    assert blend["phase"] in COLLAB and blend["round_id"] and 0 < blend["parameters"]["weight"] <= 1
    assert set(blend["parameters"]["joint"]) <= set(blend["after"])
    cr = next(c for c in changes if c["operation"] == "conflict_rescore")
    a, b = cr["parameters"]["pair"]
    assert cr["actor"] == "diagnostic_expert" and {l for l, d in cr["delta"].items() if d} <= {a, b}
    conf = [c for c in changes if c["quantity"] == "confidence"]
    assert conf and all(c["after"]["confidence"] <= c["before"]["confidence"] + 1e-9 for c in conf)   # capped by evidence
    evs = events(r, tid, "SCORES_ADJUSTED")
    assert [e["payload"]["change_id"] for e in evs] == [c["change_id"] for c in changes]
    rows = __import__("csv").DictReader(__import__("io").StringIO(
        __import__("harness.agent_trace.trace_export", fromlist=["x"]).render(
            __import__("harness.agent_trace.trace_export", fromlist=["x"]).bundle(r, tid), "scores_csv")))
    rows = list(rows)
    assert len(rows) == sum(len(set(c["before"]) | set(c["after"])) for c in changes)


def test_code_version_stamped_on_every_trace(orchestrator, small_kb, monkeypatch):
    from harness.agent_trace import code_version as cv
    tid, r = trace_of(run(orchestrator, small_kb, CLEAR_BEARING))
    t = r.get_trace(tid)
    now = cv.code_version()
    assert t["code_version"] == json.loads(json.dumps(now)) and t["code_version"]["id"] == now["id"]
    assert now["id"].endswith("+src." + now["source_sha256"][:12]) and now["source_files"] > 10
    assert r.list_traces(limit=1)[0][0]["code_version"] == now["id"]
    started = events(r, tid, "TRACE_STARTED")[0]["payload"]
    assert started["code_version"]["id"] == now["id"]
    head = subprocess.run(["git", "-C", str(BACKEND.parent), "rev-parse", "HEAD"], capture_output=True, text=True)
    if head.returncode == 0:
        assert now["git"]["commit"] == head.stdout.strip() and now["id"].startswith(head.stdout.strip()[:7])
    if now["git"] and now["git"].get("changed_files"):    # paths are repo-relative and complete
        assert all((BACKEND.parent / f.split(" -> ")[-1]).exists() or f.startswith('"') for f in now["git"]["changed_files"])
    assert cv.source_hash() == cv.source_hash()           # deterministic
    cv.code_version.cache_clear()
    monkeypatch.setenv("CODE_VERSION", "release-2026.11")
    try:
        assert cv.code_version()["id"].startswith("release-2026.11+src.")
    finally:
        cv.code_version.cache_clear()


def test_old_trace_database_is_migrated(tmp_path):
    import sqlite3
    from harness.agent_trace import trace_repository as repo
    p = tmp_path / "old.db"
    con = sqlite3.connect(p)
    con.execute("""CREATE TABLE agent_traces (trace_id TEXT PRIMARY KEY, run_id TEXT, analysis_id INTEGER,
                   schema_version TEXT NOT NULL, query TEXT NOT NULL, dataset_type TEXT NOT NULL, data_mode TEXT NOT NULL,
                   llm_mode TEXT, llm_provider TEXT, llm_model TEXT, config_json TEXT, status TEXT NOT NULL,
                   started_at TEXT NOT NULL, completed_at TEXT, duration_ms REAL, final_label TEXT, final_diagnosis TEXT,
                   final_confidence REAL, review_decision TEXT, communication_rounds INTEGER, total_messages INTEGER,
                   total_events INTEGER, total_evidence_refs INTEGER, error TEXT, semantic_json TEXT, updated_at TEXT)""")
    con.execute("""INSERT INTO agent_traces (trace_id, schema_version, query, dataset_type, data_mode, status, started_at)
                   VALUES ('TR-20261031120000-00000000', 'ida.agenttrace/1.0', 'q', 'afrb', 'combined', 'COMPLETED', '2026-10-31')""")
    con.commit()
    con.close()
    reader = repo.TraceReader(str(p))
    t = reader.get_trace("TR-20261031120000-00000000")
    assert t["code_version"] is None and t["schema_version"] == "ida.agenttrace/1.0"   # old rows stay readable
    cols = {row[1] for row in sqlite3.connect(p).execute("PRAGMA table_info(trace_evidence)")}
    assert {"content_json", "content_text", "content_sha256"} <= cols
    assert reader.llm_calls("TR-20261031120000-00000000") == [] and reader.score_changes("TR-20261031120000-00000000") == []
