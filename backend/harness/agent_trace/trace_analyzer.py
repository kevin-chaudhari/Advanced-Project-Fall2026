"""
Derived (semantic) views over a persisted trace.

Everything here is computed from the stored rows of one trace — never from the
live run and never from sample data — so the API, the dashboard and the stored
``semantic_json`` snapshot always agree with the raw events.  These are
inferences in the AgentTrace sense: they are recomputed on demand and keep
pointers (seq, message_id, execution_id) back to the raw rows.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional

from harness.agent_trace.trace_repository import TraceReader
from harness.agent_trace.trace_schema import CHALLENGE_KINDS, EvidenceRelation, Observed

AGENTS = ["diagnostic_expert", "pattern_agent", "aggressive_agent", "verification", "ambiguity",
          "human_review_coordinator"]
AGENT_NAMES = {"diagnostic_expert": "Diagnostic Expert", "pattern_agent": "Pattern Recognition",
               "aggressive_agent": "Rapid Triage", "verification": "Verification",
               "ambiguity": "Ambiguity Analysis", "human_review_coordinator": "Final Coordinator",
               "harness": "Harness (retrieval)", "all": "Broadcast"}


PHASE_LABEL = {"collaboration": "Collaboration", "resync": "Re-sync after targeted retrieval",
               "verification": "Claim verification", "uncertainty": "Uncertainty flags",
               "council": "Escalation council", "synthesis": "Final synthesis",
               "exchange": "Exchange", "final_coordinator": "Final synthesis"}


def _segment_label(phase: Optional[str], index: int) -> str:
    base = PHASE_LABEL.get(phase or "", (phase or "Messages").replace("_", " ").capitalize())
    return f"{base}, round {index}" if phase in ("collaboration", "resync", "council") else base


def communication_graph(messages: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Nodes = the six agents (+ harness when addressed). Edges = sender → receiver.

    ``addressed`` counts messages explicitly addressed to the receiver;
    ``delivered`` counts those the receiver observably read (inbox read or
    rendered prompt).  A broadcast ('all') becomes an edge only to agents that
    actually read it.
    """
    edges: Dict[tuple, Dict[str, Any]] = {}
    sent, received = Counter(), Counter()

    def edge(a: str, b: str) -> Dict[str, Any]:
        return edges.setdefault((a, b), {"source": a, "target": b, "count": 0, "addressed": 0, "delivered": 0,
                                         "types": Counter(), "message_ids": [], "first_seq": None,
                                         "last_seq": None, "rounds": set()})

    for m in messages:
        s = m["sender_agent_id"]
        sent[s] += 1
        readers = {d["receiver"] for d in m.get("deliveries", [])}
        targets = set(r for r in m["receiver_agent_ids"] if r != "all")
        if "all" in m["receiver_agent_ids"]:
            targets |= readers
        for t in sorted(targets):
            if t == s:
                continue
            e = edge(s, t)
            e["count"] += 1
            e["addressed"] += int(t in m["receiver_agent_ids"])
            e["delivered"] += int(t in readers)
            e["types"][m["message_type"]] += 1
            e["message_ids"].append(m["message_id"])
            e["rounds"].add(m["round_id"])
            e["first_seq"] = m["seq"] if e["first_seq"] is None else min(e["first_seq"], m["seq"])
            e["last_seq"] = m["seq"] if e["last_seq"] is None else max(e["last_seq"], m["seq"])
            if t in readers:
                received[t] += 1
    nodes = [{"id": a, "name": AGENT_NAMES[a], "sent": sent.get(a, 0), "received": received.get(a, 0)}
             for a in AGENTS]
    if any("harness" in (e["source"], e["target"]) for e in edges.values()):
        nodes.append({"id": "harness", "name": AGENT_NAMES["harness"], "sent": sent.get("harness", 0),
                      "received": received.get("harness", 0)})
    out = []
    for e in sorted(edges.values(), key=lambda x: x["first_seq"] or 0):
        out.append({**e, "types": dict(e["types"]), "rounds": sorted(e["rounds"])})
    return {"nodes": nodes, "edges": out}


def timeline(messages: List[Dict[str, Any]], events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Messages in sequence order, split into contiguous (phase, round) segments."""
    segments: List[Dict[str, Any]] = []
    per_phase: Dict[str, int] = defaultdict(int)
    for m in sorted(messages, key=lambda x: x["seq"]):
        phase = m.get("stage")
        if not segments or segments[-1]["round_id"] != m["round_id"] or segments[-1]["phase"] != phase:
            per_phase[phase] += 1
            segments.append({"round_id": m["round_id"], "phase": phase,
                             "label": _segment_label(phase, per_phase[phase]), "messages": [], "markers": []})
        segments[-1]["messages"].append({
            "seq": m["seq"], "message_id": m["message_id"], "message_type": m["message_type"],
            "sender": m["sender_agent_id"], "receivers": m["receiver_agent_ids"], "topic": m["topic"],
            "stage": phase, "response_to": m["response_to_message_id"],
            "readers": sorted({d["receiver"] for d in m.get("deliveries", [])}),
            "evidence_ids": m["evidence_ids"], "resolution_status": m["resolution_status"],
            "challenge_status": m["challenge_status"], "voice": m["payload"].get("voice"),
            "position": m["payload"].get("position"), "label": m["payload"].get("label")})
    for e in events:
        if e["event_type"] in ("COUNCIL_ROUND_STARTED", "COUNCIL_ROUND_COMPLETED", "COLLABORATION_ROUND_COMPLETED"):
            for seg in segments:
                if seg["round_id"] == e["payload"].get("round"):
                    seg["markers"].append({"seq": e["seq"], "event_type": e["event_type"], "payload": e["payload"]})
    return segments


def positions(messages: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Each agent's stated position (belief over candidates) message by message, from the persisted payloads."""
    rows: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    joint: List[Dict[str, Any]] = []
    cols: List[Dict[str, Any]] = []
    seen = set()
    for m in sorted(messages, key=lambda x: x["seq"]):
        p = m["payload"]
        if m["message_type"] == "SYNTHESIS" and p.get("joint"):
            joint.append({"seq": m["seq"], "round_id": m["round_id"], "phase": m.get("stage"), "message_id": m["message_id"],
                          "joint": p["joint"], "label": p.get("label"), "council_confidence": p.get("council_confidence"),
                          "converged": p.get("converged"), "dissent": p.get("dissent", [])})
        if "position" not in p and not p.get("abstain"):
            continue
        draft = bool(p.get("draft"))
        key = (m.get("stage"), m["round_id"], draft)
        if key not in seen:
            seen.add(key)
            cols.append({"phase": m.get("stage"), "round_id": m["round_id"], "draft": draft})
        rows[m["sender_agent_id"]].append({"seq": m["seq"], "round_id": m["round_id"], "phase": m.get("stage"), "draft": draft,
                                           "message_id": m["message_id"], "message_type": m["message_type"],
                                           "label": p.get("label"), "confidence": p.get("confidence"),
                                           "position": p.get("position"), "abstain": bool(p.get("abstain")),
                                           "moved_by": p.get("moved_by", []), "old_label": p.get("old_label")})
    return {"columns": cols, "agents": dict(rows), "joint": joint}


def disagreements(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Each CHALLENGE / COUNTER_ARGUMENT thread: the assertion it targets, replies, outcome."""
    by_id = {m["message_id"]: m for m in messages}
    replies = defaultdict(list)
    for m in messages:
        if m["response_to_message_id"]:
            replies[m["response_to_message_id"]].append(m)
    out = []
    for m in messages:
        if m["message_type"] not in CHALLENGE_KINDS:
            continue
        target_label = m["payload"].get("your_label")
        challenged = [r for r in m["receiver_agent_ids"] if r not in ("all", "harness")][:1]   # rest are CCs
        assertion = None
        for f in messages:
            if (f["message_type"] in ("FINDING", "POSITION_UPDATE") and f["sender_agent_id"] in challenged
                    and f["seq"] < m["seq"] and (f["payload"].get("label") == target_label
                                                 or f["payload"].get("new_label") == target_label)):
                assertion = f["message_id"]
        thread = [{"message_id": r["message_id"], "sender": r["sender_agent_id"], "type": r["message_type"],
                   "stance": r["payload"].get("stance"), "seq": r["seq"]} for r in sorted(replies[m["message_id"]],
                                                                                  key=lambda x: x["seq"])]
        out.append({"message_id": m["message_id"], "round_id": m["round_id"], "type": m["message_type"],
                    "challenger": m["sender_agent_id"], "challenged": challenged, "challenged_label": target_label,
                    "challenger_label": m["payload"].get("proposed") or m["payload"].get("verified"),
                    "cc": [r for r in m["receiver_agent_ids"] if r not in ("all", "harness")][1:],
                    "original_assertion": assertion if assertion in by_id else None,
                    "evidence_ids": m["evidence_ids"], "replies": thread,
                    "challenge_status": m["challenge_status"], "resolution_status": m["resolution_status"],
                    "outcome": m["payload"].get("outcome")})
    return out


def evidence_flow(evidence: List[Dict[str, Any]], links: List[Dict[str, Any]],
                  executions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    agent_of = {x["execution_id"]: x["agent_id"] for x in executions}
    llm_execs = {x["execution_id"] for x in executions if x.get("llm_calls")}
    by_ev = defaultdict(list)
    for l in links:
        by_ev[l["evidence_id"]].append(l)
    out = []
    for ev in evidence:
        ls = by_ev.get(ev["evidence_id"], [])
        rel = defaultdict(list)
        for l in ls:
            rel[l["relation"]].append(l)
        received = sorted({agent_of.get(l["subject_id"], "?") for l in rel[EvidenceRelation.IN_AGENT_INPUT.value]})
        rendered_true = sorted({agent_of.get(l["subject_id"], "?") for l in rel[EvidenceRelation.IN_RENDERED_INPUT.value]
                                if l["value"] == Observed.TRUE.value})
        rendered_false = sorted({agent_of.get(l["subject_id"], "?") for l in rel[EvidenceRelation.IN_RENDERED_INPUT.value]
                                 if l["value"] == Observed.FALSE.value} - set(rendered_true))
        cited = sorted({l["actor"] for l in rel[EvidenceRelation.CITED_BY_AGENT.value]})
        claims = [{"claim_id": l["subject_id"], "agent": l["actor"], "polarity": l["value"],
                   "statement": (l["detail"] or {}).get("statement")} for l in rel[EvidenceRelation.CITED_BY_CLAIM.value]]
        msgs = [{"message_id": l["subject_id"], "sender": l["actor"],
                 "message_type": (l["detail"] or {}).get("message_type")} for l in rel[EvidenceRelation.CITED_IN_MESSAGE.value]]
        ver = [{"claim_id": l["subject_id"], "status": l["value"], "by": l["actor"],
                "message_id": (l["detail"] or {}).get("message_id")} for l in rel[EvidenceRelation.VERIFIED.value]]
        vstatus = ("NOT_CHECKED" if not ver else "UNSUPPORTED" if any(v["status"] == "UNSUPPORTED" for v in ver)
                   else "VERIFIED")
        exec_received = {l["subject_id"] for l in rel[EvidenceRelation.IN_AGENT_INPUT.value]}
        rendered_state = ("NOT_APPLICABLE" if not (exec_received & llm_execs) else
                          ("TRUE" if rendered_true else "FALSE"))
        out.append({**{k: ev.get(k) for k in ("evidence_id", "kind", "provenance", "dataset", "record_id", "label",
                                              "retrieval_action", "retrieval_method", "retrieval_round",
                                              "retrieval_score", "description", "content", "content_text",
                                              "content_sha256")},
                    "received_by": received, "in_rendered_input": rendered_true, "not_in_rendered_input": rendered_false,
                    "rendered_status": rendered_state, "cited_by": cited, "claims": claims[:12], "messages": msgs[:12],
                    "verification": ver[:12], "verification_status": vstatus})
    return out


def agent_histories(executions: List[Dict[str, Any]], messages: List[Dict[str, Any]],
                    hyp_states: List[Dict[str, Any]], events: List[Dict[str, Any]]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for a in AGENTS:
        xs = [x for x in executions if x["agent_id"] == a]
        sent = [m for m in messages if m["sender_agent_id"] == a]
        recv = [m for m in messages if any(d["receiver"] == a for d in m.get("deliveries", []))]
        conf = [{"execution_id": x["execution_id"], "stage": x["stage"], "confidence": x["confidence"],
                 "seq": x["seq_start"]} for x in xs if x.get("confidence") is not None and x.get("kind") == "analyze"]
        out[a] = {
            "agent_id": a, "name": AGENT_NAMES[a], "executions": len(xs),
            "analyze_executions": sum(1 for x in xs if x.get("kind") == "analyze"),
            "failed": sum(1 for x in xs if x["status"] == "FAILED"),
            "incomplete": sum(1 for x in xs if x["status"] == "RUNNING"),
            "messages_sent": len(sent), "messages_received": len(recv),
            "challenges_sent": sum(1 for m in sent if m["message_type"] in CHALLENGE_KINDS),
            "challenges_received": sum(1 for m in messages if m["message_type"] in CHALLENGE_KINDS
                                       and m["receiver_agent_ids"][:1] == [a]),
            "responses": sum(1 for m in sent if m["message_type"] in ("RESPONSE", "HOLD", "CONCESSION")),
            "llm_calls": sum(len(x.get("llm_calls") or []) for x in xs),
            "confidence_progression": conf,
            "hypothesis_states": [h for h in hyp_states if h["agent_id"] == a],
            "final_label": next((x["finding_label"] for x in reversed(xs) if x.get("finding_label")), None),
        }
    return out


def build_semantic(reader: TraceReader, trace_id: str) -> Dict[str, Any]:
    trace = reader.get_trace(trace_id) or {}
    events, n_events = reader.events(trace_id, limit=100000)
    messages = reader.messages(trace_id)
    executions = reader.executions(trace_id, include_prompts=False)
    evidence = reader.evidence(trace_id)
    links = reader.evidence_links(trace_id)
    hyps = reader.hypothesis_states(trace_id)
    calls = reader.llm_calls(trace_id, include_responses=False)
    score_changes = reader.score_changes(trace_id)
    dis = disagreements(messages)
    graph = communication_graph(messages)
    conf_prog = [{"seq": e["seq"], "confidence": e["payload"].get("confidence"), "stage": e["payload"].get("stage"),
                  "source": e["payload"].get("source"), "evidence_confidence": e["payload"].get("evidence_confidence"),
                  "council_confidence": e["payload"].get("council_confidence")}
                 for e in events if e["event_type"] == "CONFIDENCE_RECALCULATED"]
    refs = [l for l in links if l["relation"] in (EvidenceRelation.CITED_BY_AGENT.value,
                                                  EvidenceRelation.CITED_BY_CLAIM.value,
                                                  EvidenceRelation.CITED_IN_MESSAGE.value)]
    type_counts = Counter(m["message_type"] for m in messages)
    deliveries = sum(len(m.get("deliveries", [])) for m in messages)
    summary = {
        "trace_id": trace_id, "status": trace.get("status"),
        "total_agents": len({x["agent_id"] for x in executions}),
        "total_messages": len(messages),
        "total_deliveries": deliveries,
        "undelivered_messages": sum(1 for m in messages if not m.get("deliveries")),
        "total_rounds": len({m["round_id"] for m in messages}),
        "council_rounds": len({m["round_id"] for m in messages if m["round_id"] > 0}),
        "total_events": n_events,
        "total_executions": len(executions),
        "failed_executions": sum(1 for x in executions if x["status"] == "FAILED"),
        "total_evidence_items": len(evidence),
        "evidence_records": sum(1 for e in evidence if e["kind"] == "record"),
        "derived_values": sum(1 for e in evidence if e["kind"] == "derived"),
        "total_evidence_references": len(refs),
        "message_types": dict(type_counts),
        "challenges": len(dis),
        "resolved_disagreements": sum(1 for d in dis if d["resolution_status"] == "RESOLVED"),
        "unresolved_disagreements": sum(1 for d in dis if d["resolution_status"] != "RESOLVED"),
        "questions": type_counts.get("QUESTION", 0),
        "verification_results": type_counts.get("VERIFICATION_RESULT", 0),
        "unsupported_claims_flagged": sum(1 for m in messages if m["message_type"] == "VERIFICATION_RESULT"
                                          for x in m["payload"].get("results", []) if x.get("status") == "UNSUPPORTED"),
        "hypothesis_changes": sum(1 for h in hyps if h["status"] in ("MODIFIED", "REJECTED")),
        "llm_calls": sum(len(x.get("llm_calls") or []) for x in executions),
        "llm_usage": {"calls_with_full_response": sum(1 for c in calls if c.get("response_chars") is not None),
                      "failed_calls": sum(1 for c in calls if not c["ok"]),
                      "prompt_tokens": sum(c.get("prompt_tokens") or 0 for c in calls),
                      "completion_tokens": sum(c.get("completion_tokens") or 0 for c in calls),
                      "total_tokens": sum(c.get("total_tokens") or 0 for c in calls),
                      "calls_without_usage": sum(1 for c in calls if c.get("total_tokens") is None),
                      "models": sorted({c.get("response_model") or c.get("model") for c in calls if c.get("model")})},
        "score_changes": [{"change_id": s["change_id"], "seq": s["seq"], "operation": s["operation"],
                           "quantity": s["quantity"], "stage": s["stage"], "phase": s["phase"], "round": s["round_id"],
                           "top_before": s["top_before"], "top_after": s["top_after"],
                           "max_abs_delta": s["max_abs_delta"]} for s in score_changes],
        "code_version": (trace.get("code_version") or {}).get("id"),
        "final_decision": {"label": trace.get("final_label"), "diagnosis": trace.get("final_diagnosis"),
                           "confidence": trace.get("final_confidence"), "review_decision": trace.get("review_decision")},
        "confidence_progression": conf_prog,
    }
    pos = positions(messages)
    last_joint = pos["joint"][-1] if pos["joint"] else None
    summary["collaboration"] = {
        "rounds": len([c for c in pos["columns"] if c["phase"] in ("collaboration", "resync")]),
        "messages": sum(1 for m in messages if m.get("stage") in ("collaboration", "resync")),
        "joint_label": last_joint["label"] if last_joint else None,
        "council_confidence": last_joint["council_confidence"] if last_joint else None,
        "converged": last_joint["converged"] if last_joint else None,
        "dissent": last_joint["dissent"] if last_joint else [],
        "position_changes": sum(1 for rs in pos["agents"].values() for x in rs
                                if x["old_label"] and x["label"] and x["old_label"] != x["label"]),
        "llm_voiced_messages": sum(1 for m in messages if m["payload"].get("voice") == "llm"),
    }
    return {"summary": summary, "graph": graph, "disagreements": dis, "positions": pos,
            "agents": agent_histories(executions, messages, hyps, events)}


def full_timeline(reader: TraceReader, trace_id: str) -> Dict[str, Any]:
    events, _ = reader.events(trace_id, limit=100000)
    messages = reader.messages(trace_id)
    return {"trace_id": trace_id, "segments": timeline(messages, events),
            "events": [{"seq": e["seq"], "event_type": e["event_type"], "actor": e["actor"],
                        "message_id": e["message_id"], "execution_id": e["execution_id"],
                        "timestamp": e["timestamp"], "stage": e["payload"].get("stage")} for e in events]}


def evidence_view(reader: TraceReader, trace_id: str) -> List[Dict[str, Any]]:
    return evidence_flow(reader.evidence(trace_id), reader.evidence_links(trace_id),
                         reader.executions(trace_id, include_prompts=False))
