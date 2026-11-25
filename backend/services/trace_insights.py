"""
Trace insights — the Agent-Viz features for one trace, inside the Trace explorer.

* Step breakdown: the pipeline's audit trail in order, each step reduced to the decision it made.
* Signals: rule-based checks for things a reviewer should look at (thin margin, unresolved
  disagreement, evidence nobody cited, synthetic-only support, failed agents, out-of-range readings …).
* Compare: any two traces aligned step by step and agent by agent.

AgentTrace stores messages and events but not the ordered audit trail, so every diagnosis also writes a
compact snapshot (``trace_snapshots`` in the Experiment Lab database). Traces made before this existed
have no snapshot; the API says so and the UI offers a re-run.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any, Dict, List, Optional

from services import experiments as ex
from utils.logger import setup_logger

logger = setup_logger("services.trace_insights")

_DDL = """CREATE TABLE IF NOT EXISTS trace_snapshots (
    trace_id TEXT PRIMARY KEY, created_at TEXT NOT NULL, snapshot_json TEXT NOT NULL)"""


def init_tables() -> None:
    with ex._lock, ex._conn() as c:
        c.execute(_DDL)


def store_snapshot(question: str, result: Dict[str, Any], top_k: int) -> None:
    """Called after every diagnosis (Runtime.diagnose). Never raises."""
    try:
        h = result.get("harness") or {}
        tid = h.get("trace_id")
        if not tid:
            return
        evidence = h.get("evidence") or []
        agents_raw = h.get("agents") or {}
        cited_any = {e for a in agents_raw.values() if a for e in (a.get("evidence_ids") or [])}
        hyps = h.get("hypothesis_scores") or []
        review = h.get("review") or {}
        snap = {
            "trace_id": tid, "question": question, "answer": h.get("predicted_label"),
            "confidence": result.get("confidence"), "review_decision": result.get("review_decision"),
            "review_criteria": review.get("criteria") or [],
            "data_mode": h.get("data_mode"), "top_k": top_k, "dataset_type": h.get("dataset_type"),
            "margin": round(hyps[0]["score"] - hyps[1]["score"], 4) if len(hyps) > 1 else None,
            "hypothesis_scores": [{"label": x.get("label"), "score": x.get("score")} for x in hyps[:6]],
            "evidence": [{"evidence_id": e.get("evidence_id"), "record_id": e.get("record_id"), "label": e.get("label"),
                          "source_type": e.get("source_type")} for e in evidence],
            "uncited_evidence": [e.get("evidence_id") for e in evidence if e.get("evidence_id") not in cited_any],
            "evidence_composition": h.get("evidence_composition"), "sensor_view": h.get("sensor_view"),
            "missing_sensors": (h.get("query_profile") or {}).get("missing_sensors") or [],
            "feedback_rounds": h.get("feedback_rounds"), "claim_validation": {k: v for k, v in (h.get("claim_validation") or {}).items() if k != "checks"},
            "council": {k: (h.get("council") or {}).get(k) for k in ("convened", "rounds", "confidence_before", "confidence_after")},
            "agents": ex._agent_summaries(agents_raw, evidence),
            "steps": ex.compact_steps(h.get("timeline") or [], evidence),
            "llm_mode": h.get("llm_mode"),
        }
        with ex._lock, ex._conn() as c:
            c.execute("INSERT OR REPLACE INTO trace_snapshots VALUES (?,?,?)", (tid, ex._now(), json.dumps(snap, default=str)))
    except Exception as exc:          # observability must never break a diagnosis
        logger.warning("Could not store trace snapshot: %s", exc)


def get_snapshot(trace_id: str) -> Optional[Dict[str, Any]]:
    with ex._conn() as c:
        row = c.execute("SELECT snapshot_json FROM trace_snapshots WHERE trace_id=?", (trace_id,)).fetchone()
    if not row:
        return None
    snap = json.loads(row["snapshot_json"])
    ex.plain_steps(snap.get("steps") or [])
    return snap


# ─── Signals ─────────────────────────────────────────────────────────────────

def _trace_summary(trace_id: str) -> Dict[str, Any]:
    """Counts the AgentTrace analyzer already computed (unresolved disagreements, failed executions …)."""
    try:
        con = sqlite3.connect(ex._trace_db_path(), timeout=10)
        row = con.execute("SELECT semantic_json FROM agent_traces WHERE trace_id=?", (trace_id,)).fetchone()
        con.close()
        return (json.loads(row[0]) if row and row[0] else {}).get("summary") or {}
    except Exception:
        return {}


EXPECTED_STAGES = ["query_prep", "initial_rag", "numerical_analysis", "phase1", "verification", "evidence_check",
                   "ambiguity", "final_coordinator", "claim_validation", "review_gate"]
STAGE_LABEL = {"query_prep": "reading the question", "initial_rag": "evidence retrieval", "numerical_analysis": "hypothesis scoring",
               "phase1": "first opinions", "verification": "verification", "evidence_check": "evidence check",
               "ambiguity": "ambiguity check", "final_coordinator": "final answer", "claim_validation": "claim check",
               "review_gate": "review gate"}


def _first_step(snap: Dict[str, Any], stage: str, agent: Optional[str] = None) -> Optional[str]:
    """First step of a stage; with ``agent``, that agent's step in the stage (else the agent's first step anywhere)."""
    steps = snap.get("steps") or []
    if agent:
        return (next((s["key"] for s in steps if s["stage"] == stage and s.get("agent") == agent), None)
                or next((s["key"] for s in steps if s.get("agent") == agent), None))
    return next((s["key"] for s in steps if s["stage"] == stage), None)


def _n(n: Any, word: str, plural: Optional[str] = None) -> str:
    """'1 agent', '3 agents' — a proper plural instead of 'agent(s)'."""
    return f"{n} {word if n == 1 else (plural or word + 's')}"


def signals(snap: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Rule-based checks, most severe first. Each names the step it relates to, when there is one."""
    out: List[Dict[str, Any]] = []
    summ = _trace_summary(snap["trace_id"])

    def add(sid, severity, title, detail, step=None, kind="signal", **extra):
        out.append({"id": sid, "severity": severity, "title": title, "detail": detail, "step": step, "kind": kind, **extra})

    chk = ex.second_check(snap.get("steps") or [], snap.get("feedback_rounds"), snap.get("review_decision"), snap.get("council"))
    src = chk["sources"]
    src_txt = " / ".join(f"{src[k]} {k}" for k in ("real", "synthetic") if k in src) if src else ""

    failed = [c for c in snap.get("review_criteria") or [] if not c.get("passed")]
    if snap.get("review_decision") == "REQUIRES_HUMAN_REVIEW":
        add("human_review", "high", "Sent to human review",
            "; ".join(f"{c.get('criterion_id')}: {c.get('description')} (observed {c.get('observed')})" for c in failed) or
            "The review gate did not pass.", _first_step(snap, "review_gate"))
    m = snap.get("margin")
    if m is not None and m < 0.15:
        runner = (snap.get("hypothesis_scores") or [{}, {}])[1].get("label")
        add("thin_margin", "high" if m < 0.10 else "medium", "Runner-up is close",
            f"{runner} is only {m:.2f} behind {snap.get('answer')} — a small change in the input could swap them.",
            _first_step(snap, "numerical_analysis"))
    agents = snap.get("agents") or {}
    dissent_keys = [k for k, v in agents.items() if k not in ("ambiguity",) and v.get("finding") and v["finding"] != snap.get("answer")]
    dissent = [agents[k]["name"] for k in dissent_keys]
    if dissent:
        add("agents_dissent", "medium", f"{_n(len(dissent), 'agent')} ended on a different finding",
            f"{', '.join(dissent)} did not agree with the final answer.", _first_step(snap, "phase1", dissent_keys[0]))
    unresolved = summ.get("unresolved_disagreements") or 0
    if unresolved:
        add("unresolved_disagreement", "medium", "Disagreements left open",
            f"{_n(unresolved, 'challenge or question', 'challenges or questions')} between agents {'was' if unresolved == 1 else 'were'} never settled.", _first_step(snap, "council"))
    comp = snap.get("evidence_composition") or {}
    if comp and not comp.get("real") and comp.get("synthetic"):
        add("synthetic_only", "high" if chk["auto_no_check"] else "medium", "Only synthetic evidence",
            f"All {_n(comp.get('synthetic'), 'evidence record')} {'is' if comp.get('synthetic') == 1 else 'are'} synthetic; no real historical case supports this answer"
            + (", and it was auto-approved without a second check." if chk["auto_no_check"] else "."),
            _first_step(snap, "initial_rag"))
    unc = snap.get("uncited_evidence") or []
    ev_n = len(snap.get("evidence") or [])
    if ev_n and len(unc) >= max(2, ev_n // 2):
        add("evidence_uncited", "info", "Evidence retrieved but never cited",
            f"{len(unc)} of {ev_n} retrieved records were not cited by any agent ({', '.join(unc[:6])}).", _first_step(snap, "initial_rag"))
    out_of_band = [s for s in snap.get("sensor_view") or [] if s.get("value") is not None and s.get("band_low") is not None
                   and (s["value"] < s["band_low"] or s["value"] > s["band_high"])]
    if out_of_band:
        add("out_of_range", "info", "Readings outside the normal range",
            ", ".join(f"{s['label']} {s['value']:g} ({'above' if s['value'] > s['band_high'] else 'below'} "
                      f"{s['band_high'] if s['value'] > s['band_high'] else s['band_low']:.3g})" for s in out_of_band))
    if snap.get("missing_sensors"):
        add("missing_sensors", "medium", "Sensors reported missing", ", ".join(snap["missing_sensors"]), _first_step(snap, "query_prep"))
    if summ.get("failed_executions"):
        add("agent_failed", "high", "An agent failed", f"{_n(summ['failed_executions'], 'agent execution')} raised an error.")
    errored = [s for s in snap.get("steps") or [] if s.get("status") == "error"]
    if errored:
        add("step_error", "high", "A pipeline step errored", f"{errored[0]['stage']}: {errored[0]['reason'][:160]}", errored[0]["key"])
    cv = snap.get("claim_validation") or {}
    if (cv.get("removed") or 0) > 0:
        add("claims_removed", "medium", "Unsupported claims removed",
            f"{_n(cv['removed'], 'claim')} in the agents' text {'was' if cv['removed'] == 1 else 'were'} not backed by evidence and removed.", _first_step(snap, "claim_validation"))
    if (snap.get("feedback_rounds") or 0) > 0:
        add("feedback_loop", "info", "Needed extra evidence",
            f"The evidence check sent the agents back {_n(snap['feedback_rounds'], 'time')} for targeted retrieval"
            + (f"; the extra search found {src_txt} records." if src_txt else "."), _first_step(snap, "targeted_rag"))
    if chk["synthetic_only"]:
        add("double_check_synthetic", "medium", "Double-check found only synthetic evidence",
            (f"The extra evidence search found {src_txt} records" if src_txt else "The extra evidence search found only synthetic records")
            + ": no real historical case backs the re-check.", _first_step(snap, "targeted_rag"))
    c = snap.get("council") or {}
    if c.get("convened") and c.get("confidence_before") is not None and c.get("confidence_after") is not None \
            and c["confidence_after"] < c["confidence_before"] - 0.05:
        add("council_lowered", "info", "Council lowered confidence",
            f"{c['confidence_before']:.2f} → {c['confidence_after']:.2f} after deliberation.", _first_step(snap, "council"))
    # ── gap checks: things that should have happened and did not (Agent-Viz "gaps") ──
    stages = {st["stage"] for st in snap.get("steps") or []}
    missing = [x for x in EXPECTED_STAGES if x not in stages]
    if missing and snap.get("steps"):
        add("never_reached_stage", "high", "Expected step never ran",
            f"The pipeline skipped: {', '.join(STAGE_LABEL.get(x, x) for x in missing)}.", None, kind="gap")
    auto = snap.get("review_decision") == "AUTO_RESOLVE"
    ver = (agents.get("verification") or {}).get("finding")
    if "verification" not in stages and snap.get("steps"):
        add("verification_missing", "high", "No verification", "The adversarial verification agent never ran on this answer.", None, kind="gap")
    elif ver and ver != snap.get("answer"):
        add("verification_ignored", "high" if auto else "medium", "Verification disagreed",
            f"Verification concluded {ver}, but the final answer is {snap.get('answer')}"
            + (" and it was auto-resolved without a person." if auto else "."), _first_step(snap, "verification"), kind="gap")
    conflict = [st for st in snap.get("steps") or [] if st["stage"] == "evidence_check" and st.get("status") == "warning"
                and "CONFLICT" in (st.get("signature") or "").upper()]
    if conflict and auto:
        add("conflict_ignored", "high", "Conflict flagged, answer auto-resolved",
            "The evidence check reported conflicting hypotheses, yet the case passed the review gate.", conflict[-1]["key"], kind="gap")
    if chk["auto_no_check"] and snap.get("steps"):
        add("auto_no_second_check", "high", "Auto-approved without a second check",
            "The review gate approved this answer automatically, but neither the extra evidence search nor the council "
            "debate ran: nothing re-checked it before it was released"
            + (f" (confidence {snap['confidence']:.0%})." if snap.get("confidence") is not None else "."),
            _first_step(snap, "review_gate"), kind="gap",
            fleet_title="Approved with no evidence re-check or agent debate")
    conf = snap.get("confidence")
    should_convene = (conf is not None and conf < 0.65) or (m is not None and m < 0.15) or bool(dissent)
    if should_convene and not (snap.get("council") or {}).get("convened") and "collaboration" not in stages:
        add("council_not_convened", "medium", "Council should have met",
            "Confidence, margin or first-pass disagreement met the council's criteria, but it did not convene.", None, kind="gap")
    order = {"high": 0, "medium": 1, "info": 2}
    return sorted(out, key=lambda s: order[s["severity"]])


def breakdown(trace_id: str) -> Optional[Dict[str, Any]]:
    snap = get_snapshot(trace_id)
    if not snap:
        return None
    sig = signals(snap)
    flagged = {s["step"] for s in sig if s["step"] and s["severity"] != "info"}
    first = next((s["key"] for s in snap["steps"] if s.get("status") in ("error", "warning") or s["key"] in flagged), None)
    return {"trace_id": trace_id, "answer": snap["answer"], "confidence": snap["confidence"],
            "review_decision": snap["review_decision"], "steps": snap["steps"], "agents": snap["agents"],
            "signals": sig, "first_problem_step": first, "flagged_steps": sorted(flagged),
            "evidence": snap["evidence"], "hypothesis_scores": snap["hypothesis_scores"], "margin": snap["margin"]}


# ─── Compare N traces ────────────────────────────────────────────────────────

MAX_COMPARE = 12


def compare_many(ids: List[str], labels: Optional[List[str]] = None) -> Dict[str, Any]:
    """Align N traces step by step and agent by agent. The first trace is the reference every other
    cell is compared with. Traces without a snapshot are reported in ``missing``."""
    ids = list(dict.fromkeys(i for i in ids if i))[:MAX_COMPARE]
    snaps, missing = [], []
    for i in ids:
        sn = get_snapshot(i)
        (snaps.append(sn) if sn else missing.append(i))
    labels = labels or []
    lab = {i: (labels[k] if k < len(labels) and labels[k] else i) for k, i in enumerate(ids)}
    if len(snaps) < 2:
        return {"traces": [], "missing": missing, "steps": [], "agents": [], "inputs": [], "first_divergence": None}
    ref = snaps[0]
    traces = [{"trace_id": s["trace_id"], "label": lab[s["trace_id"]], "question": s["question"], "answer": s["answer"],
               "confidence": s["confidence"], "review_decision": s["review_decision"], "margin": s.get("margin"),
               "settings": {"data_mode": s.get("data_mode"), "top_k": s.get("top_k"), "dataset": s.get("dataset_type")}}
              for s in snaps]

    # inputs: every reading stated in any of the questions
    readings = [ex.parse_readings(s["question"]) for s in snaps]
    sensors = [x for x in ex.SENSORS if any(x in r for r in readings)]
    inputs = [{"sensor": x, "label": ex.SENSOR_SPECS[x]["label"], "unit": ex._unit(x), "values": [r.get(x) for r in readings],
               "differs": len({r.get(x) for r in readings}) > 1} for x in sensors]
    for k in ("data_mode", "top_k"):
        vals = [t["settings"][k] for t in traces]
        inputs.append({"sensor": k, "label": k.replace("_", " "), "unit": "", "values": vals, "differs": len(set(map(str, vals))) > 1})

    # steps: union of step keys, ordered by median position
    by = [{st["key"]: st for st in s["steps"]} for s in snaps]
    keys = {k for m in by for k in m}
    def pos(k):
        p = sorted(m[k]["position"] for m in by if k in m)
        return p[len(p) // 2]
    steps, first = [], None
    for k in sorted(keys, key=pos):
        cells = [m.get(k) for m in by]
        ref_sig = (cells[0] or {}).get("signature")
        states = ["missing" if c is None else ("ref" if j == 0 else ("same" if c["signature"] == ref_sig and cells[0] else "different"))
                  for j, c in enumerate(cells)]
        changed = sum(st in ("different", "missing") for st in states[1:]) + (cells[0] is None)
        if first is None and changed:
            first = k
        any_cell = next(c for c in cells if c)
        steps.append({"key": k, "stage": any_cell["stage"], "agent": any_cell["agent"], "changed": changed,
                      "distinct": len({(c or {}).get("signature") for c in cells}),
                      "cells": [None if c is None else {"signature": c["signature"], "status": c.get("status"),
                                                        "reason": c.get("reason", "")[:240], "state": st}
                                for c, st in zip(cells, states)]})

    # agents: finding per trace
    agents = []
    for k in ex.AGENT_ORDER:
        cells = [(s.get("agents") or {}).get(k) for s in snaps]
        if not any(cells):
            continue
        base = (cells[0] or {}).get("finding")
        agents.append({"agent": k, "name": next(c for c in cells if c).get("name"),
                       "changed": sum(1 for c in cells[1:] if (c or {}).get("finding") != base),
                       "cells": [None if c is None else {"finding": c.get("finding"), "confidence": c.get("confidence"),
                                                         "pass_number": c.get("pass_number"), "cited": c.get("cited"),
                                                         "changed": j > 0 and c.get("finding") != base}
                                 for j, c in enumerate(cells)]})
    return {"traces": traces, "missing": missing, "inputs": inputs, "steps": steps, "agents": agents,
            "first_divergence": first,
            "summary": {"answers": len({t["answer"] for t in traces}), "steps_changed": sum(1 for x in steps if x["changed"]),
                        "agents_changed": sum(1 for a in agents if a["changed"])}}
