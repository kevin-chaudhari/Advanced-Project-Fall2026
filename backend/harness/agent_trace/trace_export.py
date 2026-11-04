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

FORMATS = ("json", "transcript", "messages_csv", "events_csv", "executions_csv", "evidence_csv",
           "llm_calls_csv", "scores_csv")
EXT = {"json": "json", "transcript": "md", "messages_csv": "messages.csv", "events_csv": "events.csv",
       "executions_csv": "executions.csv", "evidence_csv": "evidence.csv", "llm_calls_csv": "llm_calls.csv",
       "scores_csv": "scores.csv"}
MEDIA = {"json": "application/json", "transcript": "text/markdown; charset=utf-8"}


def bundle(reader: TraceReader, trace_id: str, include_prompts: bool = True) -> Dict[str, Any]:
    """The whole trace in one JSON-serialisable object."""
    t = reader.get_trace(trace_id)
    if not t:
        raise KeyError(trace_id)
    t.pop("semantic", None)
    events, _ = reader.events(trace_id, limit=1_000_000)
    return {
        "export_format": "ida.agenttrace.export/1.1", "schema_version": TRACE_SCHEMA_VERSION,
        "trace_schema_version": t.get("schema_version"), "code_version": t.get("code_version"),
        "trace": t, **build_semantic(reader, trace_id),
        "llm_calls": reader.llm_calls(trace_id, include_responses=include_prompts),
        "score_changes": reader.score_changes(trace_id),
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
        f"- Code version: `{(t.get('code_version') or {}).get('id') or 'not recorded (trace predates schema 1.1)'}`",
    ]
    u = s.get("llm_usage") or {}
    if s.get("llm_calls"):
        out.append(f"- Model calls: {s['llm_calls']} ({', '.join(u.get('models') or []) or 'model unknown'}), "
                   f"{u.get('prompt_tokens', 0):,} prompt + {u.get('completion_tokens', 0):,} completion tokens")
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
    if b.get("score_changes"):
        out += ["", "## Score changes", "",
                "Scores immediately before and after every operation that changed them (Δ = after − before).", ""]
        for c in b["score_changes"]:
            where = " · ".join(x for x in (c.get("stage"), c.get("phase") and f"phase {c['phase']}",
                                           c.get("round_id") is not None and f"round {c['round_id']}") if x)
            out += [f"**{c['change_id']} · {c['operation']}** ({c['quantity']}; {where}; by {_name(c.get('actor') or 'harness')})", "",
                    "| label | before | after | Δ |", "|---|---:|---:|---:|"]
            for l in sorted(c["after"] | c["before"], key=lambda k: -c["after"].get(k, 0.0)):
                out.append(f"| {l} | {c['before'].get(l, 0.0):.4f} | {c['after'].get(l, 0.0):.4f} | {c['delta'].get(l, 0.0):+.4f} |")
            if c.get("top_before") != c.get("top_after"):
                out.append(f"\nTop hypothesis changed: {c['top_before']} → {c['top_after']}.")
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
        return _csv(b["evidence_flow"], ["evidence_id", "kind", "provenance", "dataset", "record_id", "label",
                                         "retrieval_action", "retrieval_method", "retrieval_round", "retrieval_score",
                                         "received_by", "rendered_status", "cited_by", "verification_status",
                                         "description", "content_text", "content", "content_sha256"])
    if fmt == "llm_calls_csv":
        rows = [{**c, "x_request_id": (c.get("response_meta") or {}).get("x_request_id"),
                 "response_id": (c.get("response_meta") or {}).get("id")} for c in b.get("llm_calls", [])]
        return _csv(rows, ["seq", "execution_id", "agent_id", "call_index", "provider", "model", "response_model", "ok",
                           "error", "duration_ms", "prompt_tokens", "completion_tokens", "total_tokens", "usage",
                           "finish_reason", "response_id", "x_request_id", "input_sha256", "input_chars",
                           "response_chars", "response_sha256", "request", "response_meta", "response_raw", "ts"])
    if fmt == "scores_csv":       # long format: one row per (score change, label)
        rows = []
        for c in b.get("score_changes", []):
            p = c.get("parameters") or {}
            for l in list(dict.fromkeys(list(c["before"]) + list(c["after"]))):
                rows.append({"seq": c["seq"], "change_id": c["change_id"], "operation": c["operation"],
                             "quantity": c["quantity"], "stage": c["stage"], "phase": c["phase"], "round_id": c["round_id"],
                             "actor": c["actor"], "label": l, "before": c["before"].get(l), "after": c["after"].get(l),
                             "delta": c["delta"].get(l), "rank_before": (p.get("rank_before") or {}).get(l),
                             "rank_after": (p.get("rank_after") or {}).get(l), "top_before": c["top_before"],
                             "top_after": c["top_after"], "ts": c["ts"]})
        return _csv(rows, ["seq", "change_id", "operation", "quantity", "stage", "phase", "round_id", "actor", "label",
                           "before", "after", "delta", "rank_before", "rank_after", "top_before", "top_after", "ts"])
    raise ValueError(f"unknown format {fmt!r}; choose from {', '.join(FORMATS)}")


def filename(trace_id: str, fmt: str) -> str:
    return f"{trace_id}.{EXT[fmt]}"
