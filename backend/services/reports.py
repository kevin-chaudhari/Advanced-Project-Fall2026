"""
Run report and fleet analytics (Agent-Viz features).

* ``run_report(trace_id)`` — one self-contained, printable HTML page per trace for audit: the answer,
  review-gate criteria, readings vs normal range, signals and gaps, robustness checks, reviewer decisions,
  agents, step breakdown, evidence and versions. "Print → Save as PDF" gives a PDF.
* ``fleet(...)`` — aggregates over many traces: review rate, confidence, signal frequency, answer × signal
  heatmap, confidence-vs-margin scatter, daily volume, reviewer outcomes and robustness verdicts.
"""

from __future__ import annotations

import html
import json
import sqlite3
from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional

from services import experiments as ex
from services import trace_insights as ti

_e = lambda v: html.escape("" if v is None else str(v))  # noqa: E731
_pct = lambda v: "—" if v is None else f"{round(v * 100)}%"  # noqa: E731


def _trace_row(trace_id: str) -> Dict[str, Any]:
    con = sqlite3.connect(ex._trace_db_path(), timeout=10)
    con.row_factory = sqlite3.Row
    try:
        r = con.execute("SELECT * FROM agent_traces WHERE trace_id=?", (trace_id,)).fetchone()
        return dict(r) if r else {}
    finally:
        con.close()


def run_report(trace_id: str) -> Optional[str]:
    snap = ti.get_snapshot(trace_id)
    row = _trace_row(trace_id)
    if not snap and not row:
        return None
    snap = snap or {}
    sig = ti.signals(snap) if snap else []
    robust = ex.list_experiments(5, trace_id, "robustness")
    reviews = ex.list_reviews(trace_id)
    cfg = json.loads(row.get("config_json") or "{}") if row else {}
    exp_tag = cfg.get("experiment")

    def table(head, rows):
        return ("<table><thead><tr>" + "".join(f"<th>{_e(h)}</th>" for h in head) + "</tr></thead><tbody>"
                + "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows) + "</tbody></table>")

    parts = [f"<h1>Diagnosis report</h1><p class=muted>{_e(trace_id)} · {_e(row.get('started_at'))} · "
             f"{_e(row.get('dataset_type'))}, {_e(row.get('data_mode'))} data · {_e(row.get('llm_mode'))} · code {_e(row.get('code_version'))}</p>"]
    if exp_tag:
        parts.append(f"<p class=warn>Experiment run — a hypothetical input (“{_e(exp_tag.get('label'))}” of {_e(exp_tag.get('experiment_id'))}), not a real diagnosis.</p>")
    parts.append(f"<h2>Question</h2><p>{_e(row.get('query') or snap.get('question'))}</p>")
    parts.append("<h2>Answer</h2>" + table(["Diagnosis", "Confidence", "Review decision", "Lead over runner-up"], [[
        f"<b>{_e(snap.get('answer') or row.get('final_label'))}</b>", _pct(snap.get("confidence", row.get("final_confidence"))),
        _e(snap.get("review_decision") or row.get("review_decision")),
        "—" if snap.get("margin") is None else f"{snap['margin']:.2f} over {_e((snap.get('hypothesis_scores') or [{}, {}])[1].get('label'))}"]]))
    if snap.get("review_criteria"):
        parts.append("<h3>Review gate</h3>" + table(["Rule", "Passed", "Observed"], [
            [f"{_e(c.get('criterion_id'))}: {_e(c.get('description'))}", "yes" if c.get("passed") else "<b class=bad>no</b>", _e(c.get("observed"))]
            for c in snap["review_criteria"]]))
    sv = [s for s in snap.get("sensor_view") or [] if s.get("value") is not None]
    if sv:
        parts.append("<h2>Readings vs normal range</h2>" + table(["Sensor", "Value", "Normal range", "Status"], [
            [_e(s["label"]), _e(s["value"]), f"{s.get('band_low', 0):.3g}–{s.get('band_high', 0):.3g} {_e(s.get('unit'))}",
             _e(s.get("status"))] for s in sv]))
    if sig:
        parts.append("<h2>Signals and gaps</h2>" + table(["Severity", "Type", "Finding", "Detail"], [
            [f"<b class={'bad' if g['severity'] == 'high' else ''}>{_e(g['severity'])}</b>", _e(g.get("kind")), _e(g["title"]), _e(g["detail"])] for g in sig]))
    if robust:
        parts.append("<h2>Robustness checks</h2>" + table(["When", "Verdict", "Detail"], [
            [_e(x["created_at"]), _e((x.get("verdict") or {}).get("level") or x["status"]), _e((x.get("verdict") or {}).get("text"))] for x in robust]))
    parts.append("<h2>Human review</h2>" + (table(["When", "Reviewer", "Decision", "Reason"], [
        [_e(r["created_at"]), _e(r["reviewer"]), _e(r["decision"] + (f" → {r['final_label']}" if r.get("final_label") else "")), _e(r["reason"])]
        for r in reviews]) if reviews else "<p class=muted>No reviewer decision recorded yet.</p>"))
    if snap.get("agents"):
        parts.append("<h2>Agents</h2>" + table(["Agent", "Final finding", "Confidence", "Passes", "Cited evidence"], [
            [_e(a["name"]), _e(a.get("finding")), _pct(a.get("confidence")), _e(a.get("pass_number")),
             _e(", ".join(f"{k} ×{v}" for k, v in (a.get("cited") or {}).items()))] for a in snap["agents"].values()]))
    if snap.get("steps"):
        parts.append("<h2>Step breakdown</h2>" + table(["#", "Step", "Agent", "Decision", "Status"], [
            [str(st["position"] + 1), _e(st["stage"]), _e(st.get("agent") or ""), _e(st["signature"]), _e(st.get("status"))] for st in snap["steps"]]))
    if snap.get("evidence"):
        unc = set(snap.get("uncited_evidence") or [])
        parts.append("<h2>Evidence</h2>" + table(["ID", "Record", "Label", "Source", "Cited"], [
            [_e(e["evidence_id"]), _e(e.get("record_id")), _e(e.get("label")), _e(e.get("source_type")), "no" if e["evidence_id"] in unc else "yes"]
            for e in snap["evidence"]]))
    parts.append("<p class=muted>Confidence is a recorded system score, not a calibrated probability. Generated by Mission Control.</p>")
    css = ("body{font:13px/1.45 -apple-system,'IBM Plex Sans',sans-serif;color:#17140F;background:#FFFCF5;max-width:960px;margin:24px auto;padding:0 16px}"
           "h1{font-size:22px;margin:0 0 4px}h2{font-size:15px;margin:22px 0 6px;border-bottom:1px solid #E5DED1;padding-bottom:3px}h3{font-size:13px}"
           "table{border-collapse:collapse;width:100%;margin:4px 0}th,td{border:1px solid #E5DED1;padding:4px 6px;text-align:left;vertical-align:top}"
           "th{background:#EFE9DD}.muted{color:#4A453D}.bad{color:#8E463D}.warn{background:#FBF3E8;border:1px solid #F4E3CB;padding:6px 8px}"
           "@media print{body{margin:0}button{display:none}}")
    return (f"<!doctype html><html><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
            f"<title>Report {_e(trace_id)}</title><style>{css}</style></head><body>"
            f"<button onclick='print()' style='float:right'>Print / save as PDF</button>{''.join(parts)}</body></html>")


# ─── Fleet analytics ─────────────────────────────────────────────────────────

def fleet(origin: str = "live", dataset: Optional[str] = None, limit: int = 500) -> Dict[str, Any]:
    con = sqlite3.connect(ex._trace_db_path(), timeout=10)
    con.row_factory = sqlite3.Row
    where, params = [], []
    exp_cond = "COALESCE(config_json,'') LIKE '%\"experiment_id\"%'"
    if origin == "live":
        where.append(f"NOT ({exp_cond})")
    elif origin == "experiment":
        where.append(exp_cond)
    if dataset:
        where.append("dataset_type=?"); params.append(dataset)
    w = ("WHERE " + " AND ".join(where)) if where else ""
    rows = [dict(r) for r in con.execute(
        f"SELECT trace_id, started_at, dataset_type, final_label, final_confidence, review_decision FROM agent_traces {w} "
        f"ORDER BY started_at DESC LIMIT ?", (*params, limit))]
    con.close()
    n = len(rows)
    if not n:
        return {"total": 0}
    review = sum(1 for r in rows if r["review_decision"] == "REQUIRES_HUMAN_REVIEW")

    by_answer: Dict[str, Dict[str, Any]] = defaultdict(lambda: {"count": 0, "review": 0, "conf": [], "margin": []})
    by_day: Dict[str, Counter] = defaultdict(Counter)
    hist = Counter()
    for r in rows:
        a = by_answer[r["final_label"] or "Unknown"]
        a["count"] += 1
        a["review"] += r["review_decision"] == "REQUIRES_HUMAN_REVIEW"
        if r["final_confidence"] is not None:
            a["conf"].append(r["final_confidence"])
            hist[min(int(r["final_confidence"] * 10), 9)] += 1
        by_day[(r["started_at"] or "")[:10]]["review" if r["review_decision"] == "REQUIRES_HUMAN_REVIEW" else "auto"] += 1

    # signals need a step snapshot (diagnoses since step recording)
    sig_count, heat, scatter, with_snap = Counter(), defaultdict(Counter), [], 0
    titles: Dict[str, Dict[str, str]] = {}
    for r in rows:
        snap = ti.get_snapshot(r["trace_id"])
        if not snap:
            continue
        with_snap += 1
        ans = snap.get("answer") or "Unknown"
        if snap.get("margin") is not None:
            by_answer[ans]["margin"].append(snap["margin"])
            scatter.append({"trace_id": r["trace_id"], "confidence": snap.get("confidence"), "margin": snap["margin"],
                            "answer": ans, "review": snap.get("review_decision")})
        for g in ti.signals(snap):
            sig_count[g["id"]] += 1
            heat[ans][g["id"]] += 1
            titles[g["id"]] = {"title": g["title"], "severity": g["severity"], "kind": g.get("kind", "signal")}

    with ex._conn() as c:
        rv = Counter(dict(c.execute("SELECT decision, COUNT(*) FROM reviews GROUP BY decision").fetchall()))
        verdicts = Counter()
        for (vj,) in c.execute("SELECT verdict_json FROM experiments WHERE kind='robustness' AND verdict_json IS NOT NULL "
                               "AND COALESCE(deleted,0)=0").fetchall():
            verdicts[json.loads(vj).get("level")] += 1

    avg = lambda xs: round(sum(xs) / len(xs), 3) if xs else None  # noqa: E731
    answers = sorted(by_answer, key=lambda k: -by_answer[k]["count"])
    return {
        "total": n, "with_snapshot": with_snap, "review_rate": round(review / n, 3),
        "auto_resolved": n - review, "requires_review": review,
        "avg_confidence": avg([r["final_confidence"] for r in rows if r["final_confidence"] is not None]),
        "by_answer": [{"answer": k, "count": by_answer[k]["count"], "review_rate": round(by_answer[k]["review"] / by_answer[k]["count"], 3),
                       "avg_confidence": avg(by_answer[k]["conf"]), "avg_margin": avg(by_answer[k]["margin"])} for k in answers],
        "signals": [{"id": k, **titles[k], "count": v, "rate": round(v / with_snap, 3) if with_snap else 0}
                    for k, v in sig_count.most_common()],
        "heatmap": {"answers": [a for a in answers if a in heat], "signals": [k for k, _ in sig_count.most_common()],
                    "cells": {a: dict(heat[a]) for a in heat}, "answer_counts": {a: by_answer[a]["count"] for a in answers}},
        "scatter": scatter, "confidence_hist": [{"bin": f"{i * 10}–{i * 10 + 10}%", "count": hist[i]} for i in range(10)],
        "by_day": [{"day": d, "auto": by_day[d]["auto"], "review": by_day[d]["review"]} for d in sorted(by_day)],
        "reviews": dict(rv), "robustness": dict(verdicts),
    }
