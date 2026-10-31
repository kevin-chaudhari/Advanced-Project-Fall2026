"""
Export a persisted trace as files: a complete JSON bundle, a readable conversation
transcript, and CSV tables (messages, events, executions, evidence flow).

Used by GET /traces/{id}/export (services/trace_api.py) and by
backend/scripts/export_traces.py, so every route produces identical files.
Everything is read from the SQLite trace store, never from a live run.
"""

from __future__ import annotations

import csv
import io
import json
from typing import Any, Dict, List

from harness.agent_trace.trace_analyzer import AGENT_NAMES, build_semantic, evidence_view, full_timeline
from harness.agent_trace.trace_repository import TraceReader
from harness.agent_trace.trace_schema import TRACE_SCHEMA_VERSION

FORMATS = ("json", "transcript", "messages_csv", "events_csv", "executions_csv", "evidence_csv")
EXT = {"json": "json", "transcript": "md", "messages_csv": "messages.csv", "events_csv": "events.csv",
       "executions_csv": "executions.csv", "evidence_csv": "evidence.csv"}
MEDIA = {"json": "application/json", "transcript": "text/markdown; charset=utf-8"}


def bundle(reader: TraceReader, trace_id: str, include_prompts: bool = True) -> Dict[str, Any]:
    """The whole trace in one JSON-serialisable object."""
    t = reader.get_trace(trace_id)
    if not t:
        raise KeyError(trace_id)
    t.pop("semantic", None)
    events, _ = reader.events(trace_id, limit=1_000_000)
    return {
        "export_format": "ida.agenttrace.export/1.0", "schema_version": TRACE_SCHEMA_VERSION,
        "trace": t, **build_semantic(reader, trace_id),
        "messages": reader.messages(trace_id),
        "timeline": full_timeline(reader, trace_id)["segments"],
        "hypothesis_states": reader.hypothesis_states(trace_id),
        "executions": reader.executions(trace_id, include_prompts=include_prompts),
        "evidence_flow": evidence_view(reader, trace_id),
        "events": events,
    }


def _name(a: str) -> str:
    return AGENT_NAMES.get(a, a)


def transcript(b: Dict[str, Any]) -> str:
    """A readable log of the agents' conversation, phase by phase."""
    t, s = b["trace"], b["summary"]
    by_id = {m["message_id"]: m for m in b["messages"]}
    out: List[str] = [
        f"# Agent conversation — {t['trace_id']}", "",
        f"**Question:** {t['query']}", "",
        f"- Dataset: {t['dataset_type']} ({t['data_mode'].upper()}), {t.get('llm_mode')}, status {t['status']}",
        f"- Final decision: **{t.get('final_label')}**, confidence {t.get('final_confidence')}, {t.get('review_decision')}",
        f"- {s['total_messages']} messages, {s['total_rounds']} rounds, {s['challenges']} challenge(s) "
        f"({s['resolved_disagreements']} resolved, {s['unresolved_disagreements']} open), {s['total_events']} events",
    ]
    c = s.get("collaboration") or {}
    if c.get("joint_label"):
        out.append(f"- Council: joint finding {c['joint_label']}, council confidence {c.get('council_confidence')}, "
                   f"converged {c.get('converged')}, dissent {', '.join(_name(d) for d in c.get('dissent') or []) or 'none'}")
    for seg in b["timeline"]:
        out += ["", f"## {seg['label']}", ""]
        for row in seg["messages"]:
            m = by_id[row["message_id"]]
            to = ", ".join(_name(r) for r in m["receiver_agent_ids"])
            reply = f" (reply to {m['response_to_message_id']})" if m["response_to_message_id"] else ""
            out.append(f"**{m['message_id']} · {_name(m['sender_agent_id'])} → {to}** — {m['message_type']}{reply}")
            out.append("")
            out.append(f"> {m['message_content']}")
            extra = []
            if m["payload"].get("position"):
                extra.append("position: " + ", ".join(f"{l} {v:.0%}" for l, v in m["payload"]["position"].items()))
            if m["evidence_ids"]:
                extra.append("evidence: " + " ".join(m["evidence_ids"]))
            readers = sorted({_name(d["receiver"]) for d in m["deliveries"]})
            extra.append("read by: " + (", ".join(readers) or "nobody"))
            if m["resolution_status"] != "NOT_APPLICABLE":
                extra.append(f"resolution: {m['resolution_status']}"
                             + (f" — {m['payload']['outcome']}" if m["payload"].get("outcome") else ""))
            if m["payload"].get("voice") == "llm":
                extra.append(f"voiced by {m['payload'].get('voice_model')}")
            out.append("")
            out.append("_" + " · ".join(extra) + "_")
            out.append("")
    return "\n".join(out) + "\n"


def _csv(rows: List[Dict[str, Any]], cols: List[str]) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore")
    w.writeheader()
    for r in rows:
        w.writerow({k: (json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v) for k, v in r.items()})
    return buf.getvalue()


def render(b: Dict[str, Any], fmt: str) -> str:
    if fmt == "json":
        return json.dumps(b, indent=1, ensure_ascii=False, default=str)
    if fmt == "transcript":
        return transcript(b)
    if fmt == "messages_csv":
        rows = [{**m, "readers": sorted({d["receiver"] for d in m["deliveries"]}), "position": m["payload"].get("position"),
                 "voice": m["payload"].get("voice"), "outcome": m["payload"].get("outcome")} for m in b["messages"]]
        return _csv(rows, ["seq", "message_id", "round_id", "stage", "sender_agent_id", "receiver_agent_ids", "readers",
                           "message_type", "topic", "message_content", "position", "evidence_ids",
                           "response_to_message_id", "challenge_status", "resolution_status", "outcome", "voice", "timestamp"])
    if fmt == "events_csv":
        return _csv(b["events"], ["seq", "event_type", "actor", "execution_id", "message_id", "evidence_ids", "payload",
                                  "timestamp", "event_id"])
    if fmt == "executions_csv":
        rows = [{**x, "llm_calls": len(x.get("llm_calls") or []), "evidence_in_input": len(x.get("evidence_in_input") or []),
                 "finding": (x.get("output") or {}).get("finding")} for x in b["executions"]]
        return _csv(rows, ["seq_start", "execution_id", "agent_id", "stage", "kind", "pass_number", "round_id", "status",
                           "duration_ms", "finding_label", "confidence", "finding", "evidence_in_input", "llm_calls",
                           "messages_sent", "messages_received", "error"])
    if fmt == "evidence_csv":
        return _csv(b["evidence_flow"], ["evidence_id", "kind", "provenance", "label", "retrieval_action", "retrieval_method",
                                         "retrieval_round", "received_by", "rendered_status", "cited_by",
                                         "verification_status", "description"])
    raise ValueError(f"unknown format {fmt!r}; choose from {', '.join(FORMATS)}")


def filename(trace_id: str, fmt: str) -> str:
    return f"{trace_id}.{EXT[fmt]}"
