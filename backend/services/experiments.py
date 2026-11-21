"""
Experiment Lab — controlled what-if experiments over the diagnostic council.

An experiment is a small spec: one input question, a baseline configuration and a
few factors to vary. The Lab runs the normal diagnosis pipeline once per setting
(``Runtime.diagnose``), so every run is an ordinary AgentTrace that opens in the
Trace explorer. Nothing here is pre-baked data.

Design: **one factor at a time around a baseline** (OFAT). Each run changes exactly
one thing relative to the baseline, which keeps the run count small (≈ 8–25) and
makes every answer change attributable to that one change. Results are associations
on one input, not causal claims; the analysis says so.

Experiment kinds
* ``sensor_sweep``  — vary sensor readings in the question (what-if on the input).
* ``settings``      — vary pipeline settings: data_mode, top_k, leave-one-evidence-out.

Storage: its own SQLite file (``EXPERIMENTS_DB_PATH``, default ``./data/experiments.db``)
so the committed analysis/trace database schema is untouched.
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import re
import sqlite3
import threading
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

from harness.canonical import SENSOR_SPECS, SENSORS
from harness.query_prep import _PATTERNS, _normalise, extract_sensors, prepare_query
from utils.logger import setup_logger

logger = setup_logger("services.experiments")

DB_PATH = os.getenv("EXPERIMENTS_DB_PATH", "./data/experiments.db")
MAX_RUNS = int(os.getenv("EXPERIMENT_MAX_RUNS", "60"))
MIN_RUNS_FOR_CONFIDENCE = 8
DEFAULT_TOLERANCE_PCT = float(os.getenv("ROBUSTNESS_TOLERANCE_PCT", "3"))
DATA_MODES = ("real", "synthetic", "combined")

_DDL = [
    """CREATE TABLE IF NOT EXISTS experiments (
        experiment_id TEXT PRIMARY KEY, name TEXT NOT NULL, kind TEXT NOT NULL, status TEXT NOT NULL,
        spec_json TEXT NOT NULL, created_at TEXT NOT NULL, started_at TEXT, finished_at TEXT,
        total_runs INTEGER NOT NULL, error TEXT, source_trace_id TEXT)""",
    """CREATE TABLE IF NOT EXISTS experiment_runs (
        experiment_id TEXT NOT NULL, run_index INTEGER NOT NULL, is_baseline INTEGER NOT NULL,
        factor TEXT, value_json TEXT, label TEXT NOT NULL, question TEXT NOT NULL, config_json TEXT NOT NULL,
        status TEXT NOT NULL, trace_id TEXT, predicted_label TEXT, confidence REAL, review_decision TEXT,
        feedback_rounds INTEGER, latency_ms REAL, outcome_json TEXT, steps_json TEXT, error TEXT,
        started_at TEXT, finished_at TEXT,
        PRIMARY KEY (experiment_id, run_index))""",
    """CREATE TABLE IF NOT EXISTS reviews (
        review_id TEXT PRIMARY KEY, trace_id TEXT NOT NULL, decision TEXT NOT NULL, final_label TEXT,
        reason TEXT NOT NULL, reviewer TEXT, experiment_id TEXT, created_at TEXT NOT NULL)""",
    "CREATE INDEX IF NOT EXISTS idx_rv_trace ON reviews(trace_id, created_at DESC)",
]

_lock = threading.Lock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _conn() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(os.path.abspath(DB_PATH)), exist_ok=True)
    c = sqlite3.connect(DB_PATH, timeout=30)
    c.row_factory = sqlite3.Row
    return c


def init_experiment_tables() -> None:
    with _lock, _conn() as c:
        for ddl in _DDL:
            c.execute(ddl)
        for table, col, typ in (("experiments", "verdict_json", "TEXT"), ("experiments", "versions_json", "TEXT"),
                                ("experiments", "deleted", "INTEGER"), ("experiment_runs", "short_label", "TEXT"),
                                ("experiment_runs", "run_group", "TEXT"), ("experiment_runs", "rewrite_mode", "TEXT")):
            if col not in {r[1] for r in c.execute(f"PRAGMA table_info({table})")}:
                c.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typ}")
        # a process restart kills the runner: anything mid-flight becomes resumable
        c.execute("UPDATE experiments SET status='interrupted' WHERE status IN ('running','queued')")
        c.execute("UPDATE experiment_runs SET status='pending' WHERE status='running'")


# ─── Input handling: read and rewrite sensor readings in a question ─────────

def _fmt(sensor: str, value: float) -> str:
    d = SENSOR_SPECS[sensor]["decimals"]
    s = f"{value:.{d}f}"
    return s.rstrip("0").rstrip(".") if "." in s else s


def _unit(sensor: str) -> str:
    return "" if sensor == "vibration" else SENSOR_SPECS[sensor]["unit"]


def parse_readings(question: str) -> Dict[str, float]:
    values, _missing, _notes = extract_sensors(_normalise(question))
    return values


def _canonical_question(question: str, readings: Dict[str, float]) -> str:
    prof = prepare_query(question)
    subject = (getattr(prof, "equipment_phrase", None) or getattr(prof, "equipment_type", None) or "Equipment")
    parts = [f"{SENSOR_SPECS[s]['label'].lower() if s != 'rpm' else 'speed'} {_fmt(s, v)} "
             f"{SENSOR_SPECS[s]['unit'] if s != 'vibration' else ''}".strip()
             for s, v in readings.items()]
    return f"{str(subject).strip().capitalize()}. Telemetry: {', '.join(parts)}. Which failure is most probable and what should we do?"


def rewrite_question(question: str, overrides: Dict[str, float]) -> str:
    return rewrite_question_ex(question, overrides)[0]


def rewrite_question_ex(question: str, overrides: Dict[str, float]) -> Tuple[str, str]:
    """Return ``question`` with the given sensor values substituted in place.

    The rewritten text is re-parsed with the same extractor the pipeline uses; if it
    does not read back exactly (unit conversions, unusual phrasing), fall back to a
    canonical telemetry sentence that does.
    """
    text = _normalise(question)
    for sensor, value in overrides.items():
        low = text.lower()
        match = None
        for pat in _PATTERNS[sensor]:
            match = re.search(pat, low)
            if match:
                break
        if match:
            a, b = match.span(1)
            text = text[:a] + _fmt(sensor, value) + text[b:]
        else:
            unit = SENSOR_SPECS[sensor]["unit"] if sensor != "vibration" else ""
            word = "speed" if sensor == "rpm" else SENSOR_SPECS[sensor]["label"].lower()
            text = f"{text.rstrip()} Additional reading: {word} {_fmt(sensor, value)} {unit}".rstrip() + "."
    want = {**parse_readings(question), **overrides}
    got = parse_readings(text)
    tol = lambda s: 0.51 * 10 ** (-SENSOR_SPECS[s]["decimals"])  # noqa: E731
    if all(s in got and abs(got[s] - v) <= tol(s) for s, v in want.items()):
        return text, "in_place"
    return _canonical_question(question, want), "canonical"


def _sig2(x: float) -> float:
    """Round to two significant figures so suggested values read naturally (63.47 → 63, 0.2413 → 0.24)."""
    return 0.0 if x == 0 else round(x, 1 - int(math.floor(math.log10(abs(x)))))


def _sig3(x: float) -> float:
    return 0.0 if x == 0 else round(x, 2 - int(math.floor(math.log10(abs(x)))))


def reading_bands(kb, data_mode: str) -> Dict[str, List[float]]:
    ref = kb.reference(data_mode if data_mode in kb.available_modes() else kb.available_modes()[0])
    return {s: [ref.band_low[s], ref.band_high[s]] for s in SENSORS
            if s in ref.band_low and not math.isnan(ref.band_low[s])}


def suggest_sweep(question: str, kb, data_mode: str, points: int = 4) -> Dict[str, Any]:
    """Readings found in the question plus suggested what-if values per sensor.

    Values span the knowledge base's reference band for the sensor (normal operating
    range), extended past both edges, always including the baseline reading.
    """
    readings = parse_readings(question)
    ref = kb.reference(data_mode if data_mode in kb.available_modes() else kb.available_modes()[0])
    sensors = []
    for s in SENSORS:
        lo, hi = ref.band_low.get(s), ref.band_high.get(s)
        if lo is None or hi is None or (isinstance(lo, float) and math.isnan(lo)):
            continue
        base = readings.get(s)
        span = hi - lo if hi > lo else max(abs(hi), 1.0)
        lo2, hi2 = max(lo - 0.25 * span, 0.5 * lo), hi + 0.6 * span
        if base is not None:
            lo2, hi2 = min(lo2, base), max(hi2, base)
        raw = ([base * (1 + f) for f in (-0.4, -0.2, 0.2, 0.4)][:max(points, 2)] if base else
               [lo2 + i * (hi2 - lo2) / max(points - 1, 1) for i in range(points)])
        vals = sorted({round(_sig2(v), SENSOR_SPECS[s]["decimals"]) for v in raw if v > 0})
        vals = [v for v in vals if base is None or abs(v - base) > 1e-9]
        sensors.append({
            "sensor": s, "label": SENSOR_SPECS[s]["label"], "unit": SENSOR_SPECS[s]["unit"],
            "baseline": base, "band_low": _sig3(lo), "band_high": _sig3(hi),
            "status": band_status(base, (lo, hi)) if base is not None else None,
            "suggested_values": vals, "in_question": base is not None,
            "tolerance_pct": SENSOR_TOLERANCE_PCT.get(s),
        })
    return {"readings": readings, "sensors": sensors}


# ─── Designing the run list ──────────────────────────────────────────────────

# typical measurement uncertainty of industrial sensors (% of reading) — the robustness check's default noise
SENSOR_TOLERANCE_PCT = {"temperature": 2.0, "vibration": 5.0, "pressure": 2.0, "rpm": 1.0,
                        "current": 3.0, "voltage": 2.0, "flow_rate": 3.0}
SHORT = {"temperature": "Temp", "vibration": "Vib", "pressure": "Press", "rpm": "RPM",
         "current": "Curr", "voltage": "Volt", "flow_rate": "Flow"}
WIDE_STEPS_PCT = (-40, -20, 20, 40)        # robustness: wider sweep on readings outside the normal band


def _tol(sensor: str, override: Optional[float]) -> float:
    return float(override) if override else SENSOR_TOLERANCE_PCT.get(sensor, 3.0)


def band_status(value: float, band: Optional[Tuple[float, float]]) -> str:
    if not band:
        return "unknown"
    lo, hi = band
    return "low" if value < lo else "high" if value > hi else "in_band"


def design_runs(kind: str, spec: Dict[str, Any]) -> List[Dict[str, Any]]:
    """One baseline + one run per change (one factor at a time), deduplicated, capped at MAX_RUNS.

    If any reading cannot be rewritten in place (unit conversions, unusual phrasing), every run —
    the baseline included — uses the same canonical telemetry sentence, so wording never differs
    between runs and an answer change is only ever due to the value.
    """
    question = spec["question"]
    base_cfg = {"dataset_type": spec.get("dataset_type", "afrb"), "data_mode": spec.get("data_mode", "combined"),
                "top_k": int(spec.get("top_k", 8)), "exclude_record_ids": []}
    factors = spec.get("factors") or {}
    readings = parse_readings(question)
    changes: List[Dict[str, Any]] = []       # each: factor, value, label, short, group, overrides | config | drop_rank

    def add(factor, value, label, short, group, overrides=None, config=None, drop_rank=None):
        changes.append({"factor": factor, "value": value, "label": label, "short": short, "group": group,
                        "overrides": overrides, "config": config, "drop_rank": drop_rank})

    if kind == "sensor_sweep":
        for sensor, values in factors.items():
            if sensor not in SENSOR_SPECS:
                raise ValueError(f"Unknown sensor '{sensor}'")
            for v in dict.fromkeys(float(x) for x in values):
                if sensor in readings and abs(readings[sensor] - v) < 1e-9:
                    continue
                add(sensor, v, f"{SENSOR_SPECS[sensor]['label']} = {_fmt(sensor, v)} {_unit(sensor)}".rstrip(),
                    f"{SHORT[sensor]} {_fmt(sensor, v)}", "sweep", overrides={sensor: v})
    elif kind == "settings":
        allowed = spec.get("available_modes") or list(DATA_MODES)
        for mode in factors.get("data_mode") or []:
            if mode not in allowed:
                raise ValueError(f"data_mode '{mode}' is not available for this knowledge base (has {allowed})")
            if mode != base_cfg["data_mode"]:
                add("data_mode", mode, f"Data mode = {mode}", mode, "settings", config={"data_mode": mode})
        for k in dict.fromkeys(int(x) for x in (factors.get("top_k") or [])):
            if not 1 <= k <= 40:
                raise ValueError("top_k must be between 1 and 40")
            if k != base_cfg["top_k"]:
                add("top_k", k, f"top_k = {k}", f"k={k}", "settings", config={"top_k": k})
        for i in range(min(int(factors.get("drop_evidence") or 0), 10)):
            add("drop_evidence", i + 1, f"Without cited evidence #{i + 1}", f"−EV{i + 1}", "evidence", drop_rank=i)
    elif kind == "robustness":
        override = factors.get("tolerance_pct")
        if override is not None and not 0 < float(override) <= 25:
            raise ValueError("tolerance_pct must be between 0 and 25")
        bands = spec.get("bands") or {}
        for sensor, base in readings.items():
            t = _tol(sensor, override)
            for sign in (-1, 1):
                v = round(base * (1 + sign * t / 100), SENSOR_SPECS[sensor]["decimals"])
                if abs(v - base) > 1e-9:
                    add(sensor, v, f"{SENSOR_SPECS[sensor]['label']} {'+' if sign > 0 else '−'}{t:g}% → {_fmt(sensor, v)} {_unit(sensor)}".rstrip(),
                        f"{SHORT[sensor]} {'+' if sign > 0 else '−'}{t:g}%", "tolerance", overrides={sensor: v})
        if len(readings) > 1:   # real errors are not one-at-a-time: shift every reading together
            for sign in (-1, 1):
                ov = {s: round(b * (1 + sign * _tol(s, override) / 100), SENSOR_SPECS[s]["decimals"]) for s, b in readings.items()}
                add("all_readings", sign, f"All readings {'+' if sign > 0 else '−'}tolerance together",
                    f"All {'+' if sign > 0 else '−'}", "joint", overrides=ov)
        for i in range(min(int(factors.get("drop_evidence", 3)), 10)):
            add("drop_evidence", i + 1, f"Without cited evidence #{i + 1}", f"−EV{i + 1}", "evidence", drop_rank=i)
        # readings outside their normal band: a wider sweep finds how far the answer is from flipping
        for sensor, base in readings.items():
            b = bands.get(sensor)
            if b and band_status(base, tuple(b)) != "in_band":
                for pct in WIDE_STEPS_PCT:
                    v = round(base * (1 + pct / 100), SENSOR_SPECS[sensor]["decimals"])
                    add(sensor, v, f"{SENSOR_SPECS[sensor]['label']} {pct:+d}% → ".replace("-", "−") + f"{_fmt(sensor, v)} {_unit(sensor)}".rstrip(),
                        f"{SHORT[sensor]} {pct:+d}%".replace("-", "−"), "wide", overrides={sensor: v})
    elif kind == "grid":
        # two sensors changed together: every combination (each axis includes the baseline reading)
        if len(factors) != 2:
            raise ValueError("a grid needs exactly two sensors")
        (fa, va), (fb, vb) = list(factors.items())
        for f in (fa, fb):
            if f not in SENSOR_SPECS:
                raise ValueError(f"Unknown sensor '{f}'")
        axis = lambda f, vals: sorted(set(float(v) for v in vals) | ({readings[f]} if f in readings else set()))  # noqa: E731
        xa, xb = axis(fa, va), axis(fb, vb)
        if len(xa) * len(xb) > MAX_RUNS:
            raise ValueError(f"{len(xa)} × {len(xb)} = {len(xa) * len(xb)} runs; the limit is {MAX_RUNS}. Use fewer values.")
        for a_ in xa:
            for b_ in xb:
                if readings.get(fa) == a_ and readings.get(fb) == b_:
                    continue          # that cell is the baseline run
                add("grid", [a_, b_], f"{SENSOR_SPECS[fa]['label']} {_fmt(fa, a_)} · {SENSOR_SPECS[fb]['label']} {_fmt(fb, b_)}",
                    f"{SHORT[fa]} {_fmt(fa, a_)}·{SHORT[fb]} {_fmt(fb, b_)}", "grid", overrides={fa: a_, fb: b_})
        spec["grid_axes"] = {"x": fa, "y": fb, "x_values": xa, "y_values": xb}
    else:
        raise ValueError("kind must be 'sensor_sweep', 'settings', 'robustness' or 'grid'")

    # rewrite questions; if any needs the canonical form, use it everywhere (baseline included)
    texts = [(rewrite_question_ex(question, c["overrides"]) if c["overrides"] else (question, "in_place")) for c in changes]
    canonical = any(m == "canonical" for _, m in texts)
    base_q = _canonical_question(question, readings) if canonical else question
    runs = [{"is_baseline": True, "factor": None, "value": None, "label": "Baseline", "short": "Base", "group": "baseline",
             "question": base_q, "config": dict(base_cfg), "rewrite_mode": "canonical" if canonical else "original"}]
    for c, (text, mode) in zip(changes, texts):
        if c["overrides"] and canonical:
            text, mode = _canonical_question(question, {**readings, **c["overrides"]}), "canonical"
        run = {"is_baseline": False, "factor": c["factor"], "value": c["value"], "label": c["label"], "short": c["short"],
               "group": c["group"], "question": text, "config": {**base_cfg, **(c["config"] or {})}, "rewrite_mode": mode}
        if c["drop_rank"] is not None:
            run["drop_rank"] = c["drop_rank"]
        runs.append(run)
    if len(runs) > MAX_RUNS:
        raise ValueError(f"{len(runs)} runs requested; the limit is {MAX_RUNS}. Vary fewer values.")
    if len(runs) < 2:
        raise ValueError("Nothing to vary: choose at least one value that differs from the baseline.")
    return runs


# ─── Persistence helpers ─────────────────────────────────────────────────────

def create_experiment(name: str, kind: str, spec: Dict[str, Any], source_trace_id: Optional[str] = None,
                      versions: Optional[Dict[str, Any]] = None) -> str:
    runs = design_runs(kind, spec)
    exp_id = "EXP-" + datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S") + "-" + uuid.uuid4().hex[:6]
    if any(r["rewrite_mode"] == "canonical" for r in runs):
        spec = {**spec, "rewrite_mode": "canonical"}
    with _lock, _conn() as c:
        c.execute("INSERT INTO experiments (experiment_id, name, kind, status, spec_json, created_at, total_runs,"
                  " source_trace_id, versions_json, deleted) VALUES (?,?,?,?,?,?,?,?,?,0)",
                  (exp_id, name or "Untitled experiment", kind, "queued", json.dumps(spec), _now(), len(runs),
                   source_trace_id, json.dumps(versions or {})))
        for i, r in enumerate(runs):
            cfg = {**r["config"], **({"drop_rank": r["drop_rank"]} if "drop_rank" in r else {})}
            c.execute("INSERT INTO experiment_runs (experiment_id, run_index, is_baseline, factor, value_json, label,"
                      " short_label, run_group, rewrite_mode, question, config_json, status) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                      (exp_id, i, int(r["is_baseline"]), r["factor"], json.dumps(r["value"]), r["label"], r["short"],
                       r["group"], r["rewrite_mode"], r["question"], json.dumps(cfg), "pending"))
    return exp_id


def _exp_row(c, exp_id: str) -> Optional[sqlite3.Row]:
    return c.execute("SELECT * FROM experiments WHERE experiment_id=? AND COALESCE(deleted,0)=0", (exp_id,)).fetchone()


def set_status(exp_id: str, status: str, **fields) -> None:
    cols = ", ".join([f"{k}=?" for k in fields])
    with _lock, _conn() as c:
        c.execute(f"UPDATE experiments SET status=?{', ' + cols if cols else ''} WHERE experiment_id=?",
                  (status, *fields.values(), exp_id))


def list_experiments(limit: int = 50, source_trace_id: Optional[str] = None, kind: Optional[str] = None) -> List[Dict[str, Any]]:
    where, params = ["COALESCE(deleted,0)=0"], []
    if source_trace_id:
        where.append("source_trace_id=?"); params.append(source_trace_id)
    if kind:
        where.append("kind=?"); params.append(kind)
    with _conn() as c:
        rows = c.execute(f"SELECT * FROM experiments WHERE {' AND '.join(where)} ORDER BY created_at DESC LIMIT ?",
                         (*params, limit)).fetchall()
        out = []
        for r in rows:
            counts = dict(c.execute("SELECT status, COUNT(*) FROM experiment_runs WHERE experiment_id=? GROUP BY status",
                                    (r["experiment_id"],)).fetchall())
            spec = json.loads(r["spec_json"])
            out.append({"experiment_id": r["experiment_id"], "name": r["name"], "kind": r["kind"], "status": r["status"],
                        "created_at": r["created_at"], "finished_at": r["finished_at"], "total_runs": r["total_runs"],
                        "done_runs": counts.get("done", 0) + counts.get("failed", 0), "failed_runs": counts.get("failed", 0),
                        "question": spec.get("question"), "source_trace_id": r["source_trace_id"],
                        "verdict": json.loads(r["verdict_json"]) if r["verdict_json"] else None})
        return out


def delete_experiment(exp_id: str) -> bool:
    """Soft delete: hidden from the Lab, kept for audit (its traces are untouched)."""
    with _lock, _conn() as c:
        return c.execute("UPDATE experiments SET deleted=1 WHERE experiment_id=? AND COALESCE(deleted,0)=0",
                         (exp_id,)).rowcount > 0


# ─── Step signatures: what *decision* a step made, ignoring incidental text ─

_NUM_RE = re.compile(r"-?\d+(?:\.\d+)?")


def step_signature(step: Dict[str, Any], ev_labels: Dict[str, str], ev_sources: Dict[str, str]) -> str:
    stage = step.get("stage") or "unknown"
    reason = str(step.get("reason") or "")
    action = str(step.get("action") or "")
    status = str(step.get("status") or "ok")
    if stage in ("initial_rag", "targeted_rag"):
        used = step.get("evidence_used") or []
        labels = Counter(ev_labels.get(e, "?") for e in used)
        sources = {ev_sources.get(e, "?") for e in used}
        if not labels:
            return "no evidence"
        top = max(labels.values())
        lead = " / ".join(sorted(l for l, n in labels.items() if n == top))
        src = next(iter(sources)) if len(sources) == 1 else "mixed"
        return f"{src} evidence → {lead}"
    if stage == "numerical_analysis":
        ranked = [p.strip() for p in _NUM_RE.sub("", reason).split(",") if p.strip()]
        return " > ".join(ranked[:2]) or reason
    if stage == "collaboration":
        m = re.search(r"joint ([^(]+)", reason)
        return f"joint {m.group(1).strip()}" if m else _NUM_RE.sub("#", reason)[:80]
    if stage == "evidence_check":
        code = reason.split(":", 1)[0].strip()
        return f"{code}{' + agents disagree' if 'agents disagree' in reason else ''}"
    if stage == "claim_validation":
        m = re.search(r"'UNSUPPORTED':\s*(\d+)", reason)
        return "unsupported claims removed" if m and int(m.group(1)) else "all claims supported"
    if stage == "review_gate":
        gates = sorted(set(re.findall(r"\bG\d\b", reason)))
        return f"{action}{' (' + ', '.join(gates) + ')' if gates else ''}"
    if stage == "council" and step.get("agent") is None:
        return "council convened" if status == "loop" else ("council skipped" if "skip" in reason.lower() else _NUM_RE.sub("#", reason)[:60])
    if ".deliberate" in action:
        kinds = re.findall(r"M-\d+\s+([A-Z_]+)", reason)
        return ", ".join(kinds) if kinds else _NUM_RE.sub("#", reason)[:60]
    if ".analyze" in action:
        label = re.split(r"\s+[—(\[]|\s+-\s", reason, maxsplit=1)[0].strip()
        label = re.sub(r"^most likely\s+", "", label, flags=re.I)
        return label or status
    if stage == "query_prep":
        return re.sub(r"^\d+ numeric", "n numeric", reason)
    return _NUM_RE.sub("#", reason)[:80] or action


def _step_key_base(step: Dict[str, Any]) -> str:
    action = str(step.get("action") or "")
    verb = action.split(".", 1)[1].split(" ", 1)[0] if "." in action else ""
    return ":".join(p for p in (step.get("stage") or "unknown", step.get("agent") or "", verb) if p)


def compact_steps(timeline: List[Dict[str, Any]], evidence: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    ev_labels = {e.get("evidence_id"): str(e.get("label") or "?") for e in evidence}
    ev_sources = {e.get("evidence_id"): str(e.get("source_type") or "?") for e in evidence}
    seen: Counter = Counter()
    out = []
    for i, t in enumerate(timeline):
        base = _step_key_base(t)
        seen[base] += 1
        out.append({"key": f"{base}#{seen[base]}", "position": i, "stage": t.get("stage"), "agent": t.get("agent"),
                    "action": t.get("action"), "status": t.get("status"), "reason": str(t.get("reason") or "")[:400],
                    "signature": step_signature(t, ev_labels, ev_sources), "duration_ms": t.get("duration_ms")})
    return out


# ─── Runner ──────────────────────────────────────────────────────────────────

_tasks: Dict[str, asyncio.Task] = {}
_cancel: set = set()
_runner_lock = asyncio.Lock()          # one experiment at a time; the pipeline is CPU-bound anyway

DiagnoseFn = Callable[..., Awaitable[Dict[str, Any]]]


def start_experiment(exp_id: str, diagnose: DiagnoseFn) -> None:
    if exp_id in _tasks and not _tasks[exp_id].done():
        return
    _cancel.discard(exp_id)
    set_status(exp_id, "queued")
    _tasks[exp_id] = asyncio.create_task(_run(exp_id, diagnose))


def cancel_experiment(exp_id: str) -> None:
    _cancel.add(exp_id)


def _trace_db_path() -> str:
    return os.getenv("AGENT_TRACE_DB_PATH") or os.getenv("ANALYSIS_DB_PATH", "./data/analysis_store.db")


def tag_trace(trace_id: str, info: Dict[str, Any]) -> None:
    """Mark a trace as a counterfactual experiment run (config_json.experiment), so the Trace explorer
    and any statistics can tell it apart from a real diagnosis."""
    con = sqlite3.connect(_trace_db_path(), timeout=30)
    try:
        row = con.execute("SELECT config_json FROM agent_traces WHERE trace_id=?", (trace_id,)).fetchone()
        if row is None:
            return
        cfg = json.loads(row[0] or "{}")
        cfg["experiment"] = info
        con.execute("UPDATE agent_traces SET config_json=? WHERE trace_id=?", (json.dumps(cfg), trace_id))
        con.commit()
    finally:
        con.close()


async def _run(exp_id: str, diagnose: DiagnoseFn) -> None:
    async with _runner_lock:
        set_status(exp_id, "running", started_at=_now())
        try:
            with _conn() as c:
                runs = c.execute("SELECT * FROM experiment_runs WHERE experiment_id=? AND status IN ('pending','failed') "
                                 "ORDER BY run_index", (exp_id,)).fetchall()
            drop_order = _baseline_drop_order(exp_id)
            for r in runs:
                if exp_id in _cancel:
                    set_status(exp_id, "cancelled", finished_at=_now())
                    return
                idx = r["run_index"]
                try:
                    cfg = json.loads(r["config_json"])
                    if "drop_rank" in cfg:
                        rank = int(cfg["drop_rank"])
                        if rank >= len(drop_order):
                            _finish_run(exp_id, idx, error="the baseline has fewer evidence records than requested")
                            continue
                        cfg["exclude_record_ids"] = [drop_order[rank]]
                    with _lock, _conn() as c:
                        c.execute("UPDATE experiment_runs SET status='running', started_at=?, config_json=? "
                                  "WHERE experiment_id=? AND run_index=?", (_now(), json.dumps(cfg), exp_id, idx))
                    # the pipeline is synchronous CPU work inside async functions: run it on a worker
                    # thread with its own event loop so the API (polls, chat) stays responsive
                    result = await asyncio.to_thread(lambda: asyncio.run(diagnose(
                        r["question"], cfg["dataset_type"], cfg["data_mode"], top_k=cfg["top_k"],
                        exclude_record_ids=cfg.get("exclude_record_ids") or [])))
                    _finish_run(exp_id, idx, result=result)
                    tid = (result.get("harness") or {}).get("trace_id")
                    if tid:
                        tag_trace(tid, {"experiment_id": exp_id, "run_index": idx, "label": r["label"],
                                        "is_baseline": bool(r["is_baseline"]), "origin": "experiment"})
                    if r["is_baseline"]:
                        drop_order = _baseline_drop_order(exp_id)
                except Exception as exc:          # one failed run never sinks the experiment or stays 'running'
                    logger.warning("[experiment %s] run %s failed: %s", exp_id, idx, exc)
                    _finish_run(exp_id, idx, error=str(exc)[:500])
            set_status(exp_id, "done", finished_at=_now())
            freeze_verdict(exp_id)
        except Exception as exc:
            logger.error("[experiment %s] aborted: %s", exp_id, exc, exc_info=True)
            set_status(exp_id, "failed", finished_at=_now(), error=str(exc)[:500])
            with _lock, _conn() as c:
                c.execute("UPDATE experiment_runs SET status='failed', error='experiment aborted' "
                          "WHERE experiment_id=? AND status='running'", (exp_id,))
        finally:
            _cancel.discard(exp_id)


def _baseline_drop_order(exp_id: str) -> List[str]:
    """Record ids to leave out, most important first: records the final diagnosis cites, then retrieval rank."""
    with _conn() as c:
        row = c.execute("SELECT outcome_json FROM experiment_runs WHERE experiment_id=? AND is_baseline=1 AND status='done'",
                        (exp_id,)).fetchone()
    if not row or not row["outcome_json"]:
        return []
    o = json.loads(row["outcome_json"])
    ranked = [e["record_id"] for e in o.get("evidence", []) if e.get("record_id")]
    cited = [r for r in o.get("cited_record_ids", []) if r in ranked]
    return list(dict.fromkeys(cited + ranked))


def _agent_summaries(agents: Dict[str, Any], evidence: List[Dict[str, Any]]) -> Dict[str, Any]:
    labels = {e.get("evidence_id"): str(e.get("label") or "?") for e in evidence}
    out = {}
    for key, a in agents.items():
        if not a:
            continue
        cited = Counter(labels[e] for e in (a.get("evidence_ids") or []) if e in labels)
        out[key] = {"name": a.get("display_name") or key, "finding": a.get("finding_label") or a.get("finding"),
                    "confidence": a.get("confidence"), "pass_number": a.get("pass_number"),
                    "cited": dict(cited.most_common(4)), "n_cited": sum(cited.values()),
                    "recommendation": (a.get("recommendation") or "")[:240]}
    return out


def _finish_run(exp_id: str, idx: int, result: Optional[Dict[str, Any]] = None, error: Optional[str] = None) -> None:
    if result is not None:
        try:
            h = result.get("harness") or {}
            evidence = h.get("evidence") or []
            ev_record = {e.get("evidence_id"): e.get("record_id") for e in evidence}
            coord = (h.get("agents") or {}).get("human_review_coordinator") or {}
            hyps = h.get("hypothesis_scores") or []
            outcome = {
                "final_diagnosis": result.get("final_diagnosis"), "direct_answer": result.get("direct_answer"),
                "hypothesis_scores": [{"label": x.get("label"), "score": x.get("score")} for x in hyps[:6]],
                "margin": round(hyps[0]["score"] - hyps[1]["score"], 4) if len(hyps) > 1 else None,
                "evidence": [{"evidence_id": e.get("evidence_id"), "record_id": e.get("record_id"), "label": e.get("label"),
                              "source_type": e.get("source_type"), "retrieval_score": e.get("retrieval_score")} for e in evidence],
                "cited_record_ids": [ev_record[e] for e in coord.get("evidence_ids") or [] if ev_record.get(e)],
                "evidence_composition": h.get("evidence_composition"), "sensor_view": h.get("sensor_view"),
                "llm_mode": h.get("llm_mode"), "data_mode_used": h.get("data_mode"),
                "agents": _agent_summaries(h.get("agents") or {}, evidence),
            }
            steps = compact_steps(h.get("timeline") or [], evidence)
            values = (h.get("trace_id"), h.get("predicted_label"), result.get("confidence"), result.get("review_decision"),
                      h.get("feedback_rounds"), h.get("latency_ms"), json.dumps(outcome, default=str),
                      json.dumps(steps, default=str), _now(), exp_id, idx)
            with _lock, _conn() as c:
                c.execute("UPDATE experiment_runs SET status='done', trace_id=?, predicted_label=?, confidence=?, review_decision=?,"
                          " feedback_rounds=?, latency_ms=?, outcome_json=?, steps_json=?, finished_at=?, error=NULL"
                          " WHERE experiment_id=? AND run_index=?", values)
            return
        except Exception as exc:
            error = f"could not record the result: {exc}"
    with _lock, _conn() as c:
        c.execute("UPDATE experiment_runs SET status='failed', error=?, finished_at=? WHERE experiment_id=? AND run_index=?",
                  (error, _now(), exp_id, idx))


# ─── Reading back ────────────────────────────────────────────────────────────

def _load_runs(exp_id: str) -> List[Dict[str, Any]]:
    with _conn() as c:
        rows = c.execute("SELECT * FROM experiment_runs WHERE experiment_id=? ORDER BY run_index", (exp_id,)).fetchall()
    return [{
        "run_index": r["run_index"], "is_baseline": bool(r["is_baseline"]), "factor": r["factor"],
        "value": json.loads(r["value_json"]) if r["value_json"] else None, "label": r["label"],
        "short": r["short_label"] or r["label"], "group": r["run_group"] or ("baseline" if r["is_baseline"] else "sweep"),
        "rewrite_mode": r["rewrite_mode"], "question": r["question"], "config": json.loads(r["config_json"]),
        "status": r["status"], "trace_id": r["trace_id"], "answer": r["predicted_label"], "confidence": r["confidence"],
        "review_decision": r["review_decision"], "feedback_rounds": r["feedback_rounds"], "latency_ms": r["latency_ms"],
        "error": r["error"], "outcome": json.loads(r["outcome_json"]) if r["outcome_json"] else None,
        "steps": json.loads(r["steps_json"]) if r["steps_json"] else [],
    } for r in rows]


def get_experiment(exp_id: str, embedder_id: Optional[str] = None, light: bool = False) -> Optional[Dict[str, Any]]:
    with _conn() as c:
        exp = _exp_row(c, exp_id)
    if not exp:
        return None
    spec = json.loads(exp["spec_json"])
    runs = _load_runs(exp_id)
    out = {
        "experiment_id": exp["experiment_id"], "name": exp["name"], "kind": exp["kind"], "status": exp["status"],
        "spec": spec, "created_at": exp["created_at"], "started_at": exp["started_at"], "finished_at": exp["finished_at"],
        "error": exp["error"], "source_trace_id": exp["source_trace_id"],
        "versions": json.loads(exp["versions_json"]) if exp["versions_json"] else {},
        "verdict": json.loads(exp["verdict_json"]) if exp["verdict_json"] else None,
        "progress": {"total": len(runs), "done": sum(r["status"] == "done" for r in runs),
                     "failed": sum(r["status"] == "failed" for r in runs),
                     "running": next((r["label"] for r in runs if r["status"] == "running"), None)},
    }
    if light:                         # cheap progress poll: no runs, no analysis
        return out
    done = [r for r in runs if r["status"] == "done"]
    baseline = next((r for r in runs if r["is_baseline"] and r["status"] == "done"), None)
    out["runs"] = [{k: v for k, v in r.items() if k != "steps"} for r in runs]
    out["analysis"] = analyse(done, baseline, embedder_id or out["versions"].get("embedder"), exp["kind"], spec,
                              finished=exp["status"] == "done", failed=out["progress"]["failed"])
    if out["verdict"] is None and out["analysis"].get("verdict", {}) and exp["status"] == "done":
        out["verdict"] = out["analysis"]["verdict"]
    return out


def freeze_verdict(exp_id: str) -> None:
    """Store the verdict computed at completion, so later code changes never rewrite a recorded result."""
    exp = get_experiment(exp_id)
    if exp and exp["kind"] == "robustness" and exp["analysis"].get("verdict"):
        with _lock, _conn() as c:
            c.execute("UPDATE experiments SET verdict_json=? WHERE experiment_id=?",
                      (json.dumps({**exp["analysis"]["verdict"], "frozen_at": _now()}), exp_id))


# ─── Analysis ────────────────────────────────────────────────────────────────

MIN_GROUP = 2          # a step decision seen in a single run says nothing about the answer


def _answer_link(items: List[Tuple[Dict[str, Any], Dict[str, Any]]], n_answers: int, dominant_rate: float) -> Tuple[float, bool]:
    """How well this step's decision predicts the final answer, counting only groups of ≥ MIN_GROUP runs.
    Linked only if answers actually differ, the step has ≥ 2 such groups, and purity beats always guessing
    the most common answer by a clear margin."""
    groups: Dict[str, Counter] = defaultdict(Counter)
    for r, s in items:
        groups[s["signature"]][r["answer"] or "Unknown"] += 1
    big = [g for g in groups.values() if sum(g.values()) >= MIN_GROUP]
    covered = sum(sum(g.values()) for g in big)
    if n_answers < 2 or len(big) < 2 or not covered:
        return 0.0, False
    purity = sum(max(g.values()) for g in big) / covered
    return round(purity, 3), purity >= min(1.0, dominant_rate + 0.15)


def analyse(done: List[Dict[str, Any]], baseline: Optional[Dict[str, Any]], embedder_id: Optional[str],
            kind: str = "sensor_sweep", spec: Optional[Dict[str, Any]] = None, finished: bool = True,
            failed: int = 0) -> Dict[str, Any]:
    if not done:
        return {"ready": False}
    spec = spec or {}
    answers = Counter(r["answer"] or "Unknown" for r in done)
    reviews = Counter(r["review_decision"] or "Unknown" for r in done)
    others = [r for r in done if r is not baseline]

    # per-factor sweeps (baseline included as the factor's reference point)
    factors: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in done:
        if r["factor"] and r["factor"] not in ("all_readings", "grid"):
            factors[r["factor"]].append(r)
    base_readings = parse_readings(baseline["question"]) if baseline else {}
    factor_summaries = []
    for f, group in factors.items():
        pts = list(group)
        base_value = base_readings.get(f) if f in SENSOR_SPECS else (baseline["config"].get(f) if baseline and f in ("data_mode", "top_k") else None)
        if baseline and base_value is not None:
            pts.append({**baseline, "value": base_value})
        numeric = all(isinstance(p["value"], (int, float)) for p in pts)
        pts.sort(key=lambda p: (p["value"] if numeric else str(p["value"])))
        transitions = [{"from_value": a["value"], "to_value": b["value"], "from_answer": a["answer"], "to_answer": b["answer"]}
                       for a, b in zip(pts, pts[1:]) if numeric and a["answer"] != b["answer"]]
        flips = [p for p in group if baseline and p["answer"] != baseline["answer"]]
        review_flips = [p for p in group if baseline and p["review_decision"] != baseline["review_decision"]]
        confs = [p["confidence"] or 0 for p in pts]
        factor_summaries.append({
            "factor": f, "label": SENSOR_SPECS[f]["label"] if f in SENSOR_SPECS else f.replace("_", " "),
            "unit": _unit(f) if f in SENSOR_SPECS else "", "numeric": numeric, "baseline_value": base_value,
            "run_count": len(group), "answer_flips": len(flips), "review_flips": len(review_flips),
            "confidence_range": [round(min(confs), 3), round(max(confs), 3)] if confs else None,
            "transitions": transitions,
            "points": [{"run_index": p["run_index"], "value": p["value"], "answer": p["answer"], "confidence": p["confidence"],
                        "review_decision": p["review_decision"], "trace_id": p["trace_id"], "is_baseline": p["is_baseline"]}
                       for p in pts],
        })
    factor_summaries.sort(key=lambda s: (-s["answer_flips"], -s["review_flips"],
                                         -((s["confidence_range"] or [0, 0])[1] - (s["confidence_range"] or [0, 0])[0])))

    # step divergence, aligned by step key (stage:agent:verb#occurrence), not by position
    by_key: Dict[str, List[Tuple[Dict[str, Any], Dict[str, Any]]]] = defaultdict(list)
    for r in done:
        for s in r["steps"]:
            by_key[s["key"]].append((r, s))
    order = sorted(by_key, key=lambda k: sorted(s["position"] for _, s in by_key[k])[len(by_key[k]) // 2])
    dominant_rate = answers.most_common(1)[0][1] / len(done)
    base_steps = {s["key"]: s for s in (baseline["steps"] if baseline else [])}
    divergence, first_divergent_key = [], None
    for key in order:
        items = by_key[key]
        sigs = Counter(s["signature"] for _, s in items)
        ref_sig = base_steps[key]["signature"] if key in base_steps else sigs.most_common(1)[0][0]
        groups: Dict[str, Counter] = defaultdict(Counter)
        for r, s in items:
            groups[s["signature"]][r["answer"] or "Unknown"] += 1
        link, linked = _answer_link(items, len(answers), dominant_rate)
        n_changed = sum(1 for _, s in items if s["signature"] != ref_sig)
        entry = {
            "key": key, "stage": items[0][1]["stage"], "agent": items[0][1]["agent"],
            "run_count": len(items), "missing_runs": len(done) - len(items),
            "changed_runs": n_changed, "distinct_variants": len(sigs), "baseline_signature": ref_sig,
            "answer_link_score": link, "answer_linked": linked,
            "variants": [{"signature": sig, "count": n, "answers": dict(groups[sig]),
                          "run_indexes": [r["run_index"] for r, s in items if s["signature"] == sig][:60]}
                         for sig, n in sigs.most_common(6)],
        }
        if first_divergent_key is None and n_changed and linked:
            first_divergent_key = key
        divergence.append(entry)

    reps, seen = [], set()
    for r in ([baseline] if baseline else []) + done:
        if r and (r["answer"] not in seen):
            seen.add(r["answer"])
            reps.append(r)
    representative = [{"run_index": r["run_index"], "label": r["label"], "short": r["short"], "answer": r["answer"],
                       "confidence": r["confidence"], "review_decision": r["review_decision"], "trace_id": r["trace_id"],
                       "steps": r["steps"]} for r in reps[:6]]

    caveats = ["Associations on one input, not causal proof: runs change one thing (or all readings together) around the baseline."]
    if len(done) < MIN_RUNS_FOR_CONFIDENCE:
        caveats.append(f"Only {len(done)} completed runs — treat the patterns as anecdotal (fewer than {MIN_RUNS_FOR_CONFIDENCE}).")
    if any(((r.get("outcome") or {}).get("llm_mode") or "").startswith("deterministic") for r in done):
        caveats.append("No LLM configured: agents are deterministic, so repeating a setting gives the same answer.")
    if embedder_id and "hashing" in embedder_id.lower():
        caveats.append("The hashing fallback embedder was used; semantic retrieval differs from the real embedding model.")
    if spec.get("rewrite_mode") == "canonical":
        caveats.append("The question could not be edited in place, so every run (baseline included) uses a standard telemetry sentence.")
    synth = sum(((r.get("outcome") or {}).get("evidence_composition") or {}).get("synthetic", 0) for r in done)
    total_ev = sum(sum(((r.get("outcome") or {}).get("evidence_composition") or {}).values()) for r in done)
    if total_ev and synth / total_ev > 0.7:
        caveats.append(f"{synth / total_ev:.0%} of retrieved evidence is synthetic: answer boundaries describe the model and its "
                       "knowledge base, not physical equipment limits.")
    caveats.append("No ground truth is attached: answer changes describe behaviour, not correctness.")

    confs = [r["confidence"] or 0 for r in done]
    return {
        "ready": True, "completed_runs": len(done), "finished": finished,
        "baseline": ({"answer": baseline["answer"], "confidence": baseline["confidence"],
                      "review_decision": baseline["review_decision"], "trace_id": baseline["trace_id"],
                      "margin": (baseline.get("outcome") or {}).get("margin"),
                      "runner_up": next(iter(((baseline.get("outcome") or {}).get("hypothesis_scores") or [])[1:2]), {}).get("label")}
                     if baseline else None),
        "answer_counts": dict(answers), "review_counts": dict(reviews),
        "confidence_range": [round(min(confs), 3), round(max(confs), 3)],
        "answer_stability": round(answers.most_common(1)[0][1] / len(done), 3),
        "runs_changed_vs_baseline": {
            "answer": sum(1 for r in others if baseline and r["answer"] != baseline["answer"]),
            "review": sum(1 for r in others if baseline and r["review_decision"] != baseline["review_decision"])},
        "factors": factor_summaries, "step_divergence": divergence, "first_divergent_step": first_divergent_key,
        "representative_runs": representative, "caveats": caveats, "embedder": embedder_id,
        "agents": agent_divergence(done, baseline),
        "verdict": robustness_verdict(done, baseline, finished, failed) if kind == "robustness" else None,
        "grid": grid_summary(done, baseline, spec.get("grid_axes")) if kind == "grid" else None,
    }


def grid_summary(done: List[Dict[str, Any]], baseline: Optional[Dict[str, Any]], axes: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Two-sensor grid: the outcome in every cell, and whether the sensors interact — i.e. whether the
    effect of one sensor on the answer depends on the value of the other."""
    if not axes:
        return None
    fx, fy = axes["x"], axes["y"]
    cells = {}
    for r in done:
        if r["factor"] == "grid" and isinstance(r["value"], list):
            key = (float(r["value"][0]), float(r["value"][1]))
        elif r["is_baseline"]:
            rd = parse_readings(r["question"])
            key = (rd.get(fx), rd.get(fy))
        else:
            continue
        o = r.get("outcome") or {}
        cells[key] = {"x": key[0], "y": key[1], "run_index": r["run_index"], "answer": r["answer"], "confidence": r["confidence"],
                      "review_decision": r["review_decision"], "margin": o.get("margin"), "trace_id": r["trace_id"],
                      "is_baseline": r["is_baseline"]}
    xs, ys = axes["x_values"], axes["y_values"]
    rows = [[cells.get((float(x), float(y))) for x in xs] for y in ys]
    # interaction: the answer pattern along X differs between rows (or along Y between columns)
    row_patterns = {tuple((c or {}).get("answer") for c in row) for row in rows}
    col_patterns = {tuple((rows[j][i] or {}).get("answer") for j in range(len(ys))) for i in range(len(xs))}
    answers = {c["answer"] for c in cells.values()}
    interacts = len(answers) > 1 and len(row_patterns) > 1 and len(col_patterns) > 1
    boundaries = sum(1 for j in range(len(ys)) for i in range(len(xs) - 1)
                     if rows[j][i] and rows[j][i + 1] and rows[j][i]["answer"] != rows[j][i + 1]["answer"]) + \
                 sum(1 for j in range(len(ys) - 1) for i in range(len(xs))
                     if rows[j][i] and rows[j + 1][i] and rows[j][i]["answer"] != rows[j + 1][i]["answer"])
    if len(answers) <= 1:
        note = "The diagnosis is the same in every combination tested."
    elif interacts:
        note = (f"The sensors interact: how {SENSOR_SPECS[fx]['label'].lower()} affects the diagnosis depends on "
                f"{SENSOR_SPECS[fy]['label'].lower()} (and the other way round). Testing them one at a time would miss this.")
    elif len(row_patterns) > 1:
        note = f"Only {SENSOR_SPECS[fy]['label'].lower()} changes the diagnosis in this range; {SENSOR_SPECS[fx]['label'].lower()} does not."
    else:
        note = f"Only {SENSOR_SPECS[fx]['label'].lower()} changes the diagnosis in this range; {SENSOR_SPECS[fy]['label'].lower()} does not."
    return {"x": fx, "y": fy, "x_label": SENSOR_SPECS[fx]["label"], "y_label": SENSOR_SPECS[fy]["label"],
            "x_unit": _unit(fx), "y_unit": _unit(fy), "x_values": xs, "y_values": ys, "rows": rows,
            "interacts": interacts, "boundaries": boundaries, "answers": sorted(answers), "note": note,
            "filled": sum(1 for row in rows for c in row if c), "total": len(xs) * len(ys)}


AGENT_ORDER = ["diagnostic_expert", "pattern_agent", "aggressive_agent", "verification", "ambiguity", "human_review_coordinator"]


def agent_divergence(done: List[Dict[str, Any]], baseline: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Per agent: its finding in every run, and whether it moved away from its baseline finding."""
    ref_run = baseline or (done[0] if done else None)
    if not ref_run:
        return []
    ref = (ref_run.get("outcome") or {}).get("agents") or {}
    keys = [k for k in AGENT_ORDER if any(k in ((r.get("outcome") or {}).get("agents") or {}) for r in done)]
    out = []
    for k in keys:
        base = (ref.get(k) or {}).get("finding")
        cells, changed = [], 0
        for r in done:
            a = ((r.get("outcome") or {}).get("agents") or {}).get(k)
            f = a.get("finding") if a else None
            diff = r is not ref_run and f != base
            changed += diff
            cells.append({"run_index": r["run_index"], "short": r["short"], "label": r["label"], "finding": f,
                          "confidence": a.get("confidence") if a else None, "changed": diff, "answer": r["answer"]})
        out.append({"agent": k, "name": (ref.get(k) or {}).get("name") or k.replace("_", " "), "baseline_finding": base,
                    "changed_runs": changed, "distinct_findings": len({c["finding"] for c in cells}),
                    "agrees_with_answer": sum(1 for c in cells if c["finding"] == c["answer"]), "cells": cells})
    return out


THIN_MARGIN = 0.10       # runner-up within this score of the leader: the baseline itself is a coin-flip


def robustness_verdict(done: List[Dict[str, Any]], baseline: Optional[Dict[str, Any]], finished: bool = True,
                       failed: int = 0) -> Optional[Dict[str, Any]]:
    if not baseline:
        return None
    if not finished:
        return {"level": "incomplete", "text": f"Still running: {len(done)} run(s) finished so far. No verdict until all runs finish."}
    core = [r for r in done if r is not baseline and r["group"] in ("tolerance", "joint", "evidence")]
    wide = [r for r in done if r["group"] == "wide"]
    flips = [r for r in core if r["answer"] != baseline["answer"]]
    review = [r for r in core if r["review_decision"] != baseline["review_decision"]]
    confs = [r["confidence"] or 0 for r in core + [baseline]]
    lo, hi = min(confs), max(confs)
    margin = (baseline.get("outcome") or {}).get("margin")
    thin = margin is not None and margin < THIN_MARGIN
    level = "fragile" if flips else ("sensitive" if review or (hi - lo) >= 0.15 or thin else "stable")
    sensor_flips = [r for r in flips if r["group"] in ("tolerance", "joint")]
    evidence_flips = [r for r in flips if r["group"] == "evidence"]
    if level == "fragile":
        parts = []
        if sensor_flips:
            parts.append(f"a change within normal sensor error gives a different diagnosis in {len(sensor_flips)} run(s) "
                         f"({'; '.join(f'{r['label']} → {r['answer']}' for r in sensor_flips[:2])})")
        if evidence_flips:
            parts.append(f"leaving out one cited evidence record changes it in {len(evidence_flips)} run(s)")
        text = "Not robust: " + ", and ".join(parts) + ". Confirm with an inspection before acting."
    else:
        reasons = []
        if review:
            reasons.append(f"the review decision changed in {len(review)} run(s)")
        if hi - lo >= 0.15:
            reasons.append(f"confidence ranged {lo:.0%}–{hi:.0%}")
        if thin:
            reasons.append(f"the runner-up is only {margin:.2f} behind the leading diagnosis")
        text = (f"Same diagnosis in all {len(core)} disturbed runs, but " + " and ".join(reasons) + "."
                if level == "sensitive" else
                f"Same diagnosis and review decision in all {len(core)} disturbed runs; confidence {lo:.0%}–{hi:.0%}.")
    nearest = []
    for r in sorted(wide, key=lambda r: abs((r["value"] or 0) - parse_readings(baseline["question"]).get(r["factor"], 0))):
        if r["answer"] != baseline["answer"] and r["factor"] not in {n["factor"] for n in nearest}:
            nearest.append({"factor": r["factor"], "label": r["label"], "answer": r["answer"], "run_index": r["run_index"]})
    return {"level": level, "text": text, "tested": len(core), "failed": failed, "answer_flips": len(flips),
            "review_flips": len(review), "confidence_range": [round(lo, 3), round(hi, 3)], "baseline_margin": margin,
            "wide_runs": len(wide), "nearest_flips": nearest,
            "flipping_runs": [{"run_index": r["run_index"], "label": r["label"], "answer": r["answer"]} for r in flips]}


def compare_runs(exp_id: str, a: int, b: int) -> Optional[Dict[str, Any]]:
    """Step- and agent-aligned comparison of two runs of one experiment."""
    runs = {r["run_index"]: r for r in _load_runs(exp_id) if r["run_index"] in (a, b)}
    if a not in runs or b not in runs:
        return None
    return compare_snapshots(runs[a], runs[b])


def compare_snapshots(ra: Dict[str, Any], rb: Dict[str, Any]) -> Dict[str, Any]:
    """Align two runs (experiment runs or trace snapshots) step by step and agent by agent."""
    sa = {s["key"]: s for s in ra["steps"]}
    sb = {s["key"]: s for s in rb["steps"]}
    keys = sorted(set(sa) | set(sb), key=lambda k: (sa.get(k) or sb.get(k))["position"] + (0.5 if k not in sa else 0))
    aligned, first = [], None
    for k in keys:
        x, y = sa.get(k), sb.get(k)
        state = "only_a" if y is None else "only_b" if x is None else ("same" if x["signature"] == y["signature"] else "different")
        if first is None and state != "same":
            first = k
        aligned.append({"key": k, "stage": (x or y)["stage"], "agent": (x or y)["agent"], "state": state, "a": x, "b": y})
    aa = (ra["outcome"] or {}).get("agents") or {}
    ab = (rb["outcome"] or {}).get("agents") or {}
    agents = []
    for k in [k for k in AGENT_ORDER if k in aa or k in ab]:
        x, y = aa.get(k), ab.get(k)
        state = "same" if x and y and x.get("finding") == y.get("finding") else ("different" if x and y else "only_one")
        cx_, cy_ = (x or {}).get("confidence"), (y or {}).get("confidence")
        agents.append({"agent": k, "name": (x or y).get("name"), "state": state, "a": x, "b": y,
                       "confidence_delta": round(cy_ - cx_, 3) if cx_ is not None and cy_ is not None else None,
                       "changed_steps": [st["key"] for st in aligned if st["agent"] == k and st["state"] != "same"]})

    def head(r):
        return {k: r[k] for k in ("run_index", "label", "short", "question", "answer", "confidence", "review_decision",
                                  "trace_id", "config")}
    return {"a": head(ra), "b": head(rb), "first_divergence": first, "steps": aligned, "agents": agents,
            "summary": {s: sum(1 for x in aligned if x["state"] == s) for s in ("same", "different", "only_a", "only_b")}}


# ─── Reviewer sign-off ───────────────────────────────────────────────────────

def add_review(trace_id: str, decision: str, reason: str, final_label: Optional[str], reviewer: str,
               experiment_id: Optional[str]) -> Dict[str, Any]:
    if decision not in ("approve", "reject", "change"):
        raise ValueError("decision must be approve, reject or change")
    if not reason.strip():
        raise ValueError("a reason is required")
    if decision == "change" and not (final_label or "").strip():
        raise ValueError("give the corrected diagnosis")
    row = {"review_id": "RV-" + uuid.uuid4().hex[:10], "trace_id": trace_id, "decision": decision,
           "final_label": (final_label or "").strip() or None, "reason": reason.strip()[:2000],
           "reviewer": (reviewer or "anonymous").strip()[:120], "experiment_id": experiment_id, "created_at": _now()}
    with _lock, _conn() as c:
        c.execute("INSERT INTO reviews VALUES (:review_id,:trace_id,:decision,:final_label,:reason,:reviewer,:experiment_id,:created_at)", row)
    return row


def list_reviews(trace_id: str) -> List[Dict[str, Any]]:
    with _conn() as c:
        return [dict(r) for r in c.execute("SELECT * FROM reviews WHERE trace_id=? ORDER BY created_at DESC", (trace_id,))]
