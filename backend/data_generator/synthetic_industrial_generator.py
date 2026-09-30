"""
Synthetic Industrial Scenario Generator  (generator version v1)
================================================================

Generates *clearly labelled* synthetic sensor records in the same column
schema as the original AFRB dataset so that they flow through exactly the same
loader -> canonical schema -> embedding -> FAISS -> RAG -> agents pipeline.

Design principles
-----------------
* Deterministic: every call is seeded (numpy Generator), no LLM involved.
* Gap-driven: the scenario mix is chosen from a gap analysis of the original
  AFRB data (see ``analyse_gaps``).  The original data has 7 balanced fault
  classes, **no normal-operation class, no missing values, no seal / cavitation
  / gearbox-specific scenarios, no contradictory-sensor cases and no severity
  gradation**.  Those gaps are what we fill.
* Calibrated: fault signatures for classes that already exist in AFRB are the
  per-class medians measured on the original data; spreads are taken from the
  observed inter-quartile ranges.  New classes (Seal Failure, Pump Cavitation,
  Gearbox Degradation, Normal Operation) use *synthetic scenario assumptions*
  documented in ``SCENARIO_SIGNATURES`` — they are experimental scenarios, not
  universal engineering truths.
* Provenance: every row carries ``Source_Type=synthetic``, ``Synthetic=True``,
  ``Synthetic_Scenario``, ``Synthetic_Generator_Version`` and a
  ``Synthetic_Record_ID`` (``SYN-000001``...).

Two artefacts are produced:

1. ``afrb_synthetic.csv``  – knowledge-base records that are indexed for RAG.
2. ``test_scenarios.csv``  – a *held-out* evaluation set (different seed, never
   indexed) with known ground truth used to measure diagnostic accuracy,
   hallucination, ambiguity detection and retrieval quality.

Run:  ``python -m data_generator.synthetic_industrial_generator`` from backend/.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

GENERATOR_VERSION = "v1"

SENSORS = ["Temperature", "Vibration", "Pressure", "RPM", "Current", "Voltage", "Flow_Rate"]

# Physical/plausible bounds of the AFRB value space (taken from the original
# data min/max).  Values are clipped to these bounds.
BOUNDS: Dict[str, Tuple[float, float]] = {
    "Temperature": (15.0, 125.0),
    "Vibration": (0.0, 1.0),        # normalised vibration index used by AFRB
    "Pressure": (15.0, 100.0),      # PSI
    "RPM": (300.0, 4950.0),
    "Current": (3.0, 150.0),        # A
    "Voltage": (100.0, 480.0),      # V
    "Flow_Rate": (0.0, 200.0),      # L/min
}

DECIMALS = {"Temperature": 1, "Vibration": 3, "Pressure": 1, "RPM": 0,
            "Current": 1, "Voltage": 1, "Flow_Rate": 1}

# Typical spread (≈ IQR/1.35 observed in AFRB) used as per-sensor noise.
NOISE_SD = {"Temperature": 6.0, "Vibration": 0.06, "Pressure": 6.0, "RPM": 0.0,
            "Current": 10.0, "Voltage": 35.0, "Flow_Rate": 14.0}

# ── Scenario signatures ──────────────────────────────────────────────────────
# "median" of each fault profile at full severity.  Classes marked (AFRB) use
# the per-class medians measured on the original data.  (SYNTHETIC ASSUMPTION)
# marks scenario assumptions introduced for experimentation.
SCENARIO_SIGNATURES: Dict[str, Dict[str, float]] = {
    # (SYNTHETIC ASSUMPTION) healthy operating envelope
    "Normal Operation":       {"Temperature": 55.0, "Vibration": 0.15, "Pressure": 52.0,
                               "Current": 60.0, "Voltage": 330.0, "Flow_Rate": 110.0},
    # (AFRB) medians
    "Bearing Wear":           {"Temperature": 93.4, "Vibration": 0.78, "Pressure": 54.8,
                               "Current": 54.9, "Voltage": 309.5, "Flow_Rate": 99.7},
    "Rotor Imbalance":        {"Temperature": 77.6, "Vibration": 0.80, "Pressure": 49.9,
                               "Current": 92.4, "Voltage": 320.5, "Flow_Rate": 99.3},
    "Lubrication Degradation": {"Temperature": 98.2, "Vibration": 0.65, "Pressure": 55.1,
                               "Current": 84.2, "Voltage": 313.9, "Flow_Rate": 94.9},
    "Cooling System Failure": {"Temperature": 105.1, "Vibration": 0.25, "Pressure": 34.0,
                               "Current": 54.3, "Voltage": 316.3, "Flow_Rate": 25.3},
    "Electrical Overload":    {"Temperature": 96.3, "Vibration": 0.23, "Pressure": 55.2,
                               "Current": 125.0, "Voltage": 424.8, "Flow_Rate": 100.3},
    "Valve Blockage":         {"Temperature": 67.0, "Vibration": 0.25, "Pressure": 87.5,
                               "Current": 97.7, "Voltage": 319.4, "Flow_Rate": 21.0},
    "Sensor Malfunction":     {"Temperature": 23.0, "Vibration": 0.02, "Pressure": 25.0,
                               "Current": 11.5, "Voltage": 125.2, "Flow_Rate": 195.0},
    # (SYNTHETIC ASSUMPTION) new scenario families not present in AFRB
    "Seal Failure":           {"Temperature": 68.0, "Vibration": 0.30, "Pressure": 28.0,
                               "Current": 62.0, "Voltage": 325.0, "Flow_Rate": 62.0},
    "Pump Cavitation":        {"Temperature": 58.0, "Vibration": 0.55, "Pressure": 22.0,
                               "Current": 70.0, "Voltage": 325.0, "Flow_Rate": 48.0},
    "Gearbox Degradation":    {"Temperature": 88.0, "Vibration": 0.62, "Pressure": 52.0,
                               "Current": 80.0, "Voltage": 320.0, "Flow_Rate": 100.0},
}

SCENARIO_KEY = {
    "Normal Operation": "normal_operation",
    "Bearing Wear": "bearing_degradation",
    "Rotor Imbalance": "shaft_imbalance",
    "Lubrication Degradation": "lubrication_problem",
    "Cooling System Failure": "cooling_degradation",
    "Electrical Overload": "electrical_overload",
    "Valve Blockage": "valve_blockage",
    "Sensor Malfunction": "sensor_malfunction",
    "Seal Failure": "seal_failure",
    "Pump Cavitation": "pump_cavitation",
    "Gearbox Degradation": "gearbox_degradation",
}

COMPONENT = {
    "Normal Operation": "None",
    "Bearing Wear": "Bearing",
    "Rotor Imbalance": "Shaft / Rotor",
    "Lubrication Degradation": "Lubrication System",
    "Cooling System Failure": "Cooling Circuit",
    "Electrical Overload": "Motor Winding",
    "Valve Blockage": "Valve",
    "Sensor Malfunction": "Instrumentation",
    "Seal Failure": "Mechanical Seal",
    "Pump Cavitation": "Impeller",
    "Gearbox Degradation": "Gear Train",
}

# Human-readable description of each scenario's sensor pattern (used in the
# synthetic reasoning text and as expected_sensor_pattern for evaluation).
PATTERN_TEXT = {
    "Normal Operation": "all channels inside the synthetic healthy envelope",
    "Bearing Wear": "high vibration with elevated temperature at normal current",
    "Rotor Imbalance": "high vibration with elevated current and only moderate temperature",
    "Lubrication Degradation": "high temperature with moderately elevated vibration and current",
    "Cooling System Failure": "high temperature with low coolant flow and low pressure",
    "Electrical Overload": "high current and high voltage with elevated temperature",
    "Valve Blockage": "high pressure with restricted flow",
    "Sensor Malfunction": "implausible readings across channels",
    "Seal Failure": "pressure loss with moderate flow loss and slight temperature rise",
    "Pump Cavitation": "very low pressure, reduced flow and elevated vibration at normal temperature",
    "Gearbox Degradation": "rising vibration and temperature on a high-hour gear train",
}

CONTEXTS_ALL = [
    "Axial fan unit in a steel mill ventilation system",
    "Booster pump station in a municipal water distribution network",
    "Centrifugal pump in a municipal water treatment facility",
    "Chilled water pump in a pharmaceutical cleanroom HVAC system",
    "Cooling tower circulation pump in a data center",
    "Electric motor driving a conveyor belt in a manufacturing facility",
    "Gearbox driving a paper mill roller",
    "HVAC compressor in a commercial high-rise building",
    "High-pressure feed pump in a petrochemical refinery",
    "Industrial mixer drive in a pharmaceutical manufacturing plant",
    "Process gas compressor in a natural gas distribution network",
    "Slurry pump in a mineral processing facility",
    "Steam turbine generator in a thermal power station",
    "Bagasse conveyor drive in a sugar processing mill",
]
CONTEXTS_PUMP = [c for c in CONTEXTS_ALL if "pump" in c.lower()]
CONTEXTS_GEAR = [
    "Gearbox driving a paper mill roller",
    "Bagasse conveyor drive in a sugar processing mill",
    "Industrial mixer drive in a pharmaceutical manufacturing plant",
    "Electric motor driving a conveyor belt in a manufacturing facility",
]
SCENARIO_CONTEXTS = {
    "Seal Failure": CONTEXTS_PUMP,
    "Pump Cavitation": CONTEXTS_PUMP,
    "Gearbox Degradation": CONTEXTS_GEAR,
}

SEVERITY_LEVELS = {"mild": 0.40, "moderate": 0.70, "severe": 1.0}
SEVERITY_LABEL = {"mild": "Low", "moderate": "Medium", "severe": "High"}

QUESTION_STEMS = [
    "Based on the current sensor data, which failure mode is most probable?",
    "Which diagnosis best matches the observed operational parameters?",
    "What is the most plausible fault diagnosis given the current sensor readings?",
    "Which fault condition best explains the observed sensor readings?",
]

ALL_LABELS = list(SCENARIO_SIGNATURES.keys())


# ─────────────────────────────────────────────────────────────────────────────
# Core sampling helpers
# ─────────────────────────────────────────────────────────────────────────────

def _clip(sensor: str, value: float) -> float:
    lo, hi = BOUNDS[sensor]
    return float(np.clip(value, lo, hi))


def _round(sensor: str, value: Optional[float]) -> Optional[float]:
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return None
    d = DECIMALS[sensor]
    return float(round(value, d)) if d else float(int(round(value)))


def _profile(rng: np.random.Generator, label: str, severity: float,
             noise_scale: float = 1.0) -> Dict[str, float]:
    """Sample a sensor profile: normal + severity*(signature - normal) + noise."""
    normal = SCENARIO_SIGNATURES["Normal Operation"]
    sig = SCENARIO_SIGNATURES[label]
    out: Dict[str, float] = {}
    for s in SENSORS:
        if s == "RPM":
            out[s] = 747.0 if label == "Sensor Malfunction" else rng.uniform(700, 4200)
            if label == "Sensor Malfunction":
                out[s] += rng.normal(0, 90)
            continue
        base = normal[s] + severity * (sig[s] - normal[s])
        sd = NOISE_SD[s] * noise_scale
        if label == "Sensor Malfunction":
            sd = sd * 0.25
        out[s] = base + rng.normal(0, sd)
    return {s: _round(s, _clip(s, v)) for s, v in out.items()}


def _mix(rng: np.random.Generator, a: str, b: str, alpha: float) -> Dict[str, float]:
    """Profile between two fault signatures (alpha weight on `a`)."""
    pa = _profile(rng, a, 1.0, noise_scale=0.6)
    pb = _profile(rng, b, 1.0, noise_scale=0.6)
    out = {}
    for s in SENSORS:
        out[s] = _round(s, _clip(s, alpha * pa[s] + (1 - alpha) * pb[s]))
    return out


def _operating_hours(rng, label: str, severity: float) -> int:
    if label in ("Bearing Wear", "Gearbox Degradation"):
        return int(rng.uniform(18000, 32000) + severity * rng.uniform(5000, 25000))
    if label == "Normal Operation":
        return int(rng.uniform(1500, 30000))
    return int(rng.uniform(4000, 40000))


def _maintenance_days(rng, label: str, severity: float) -> int:
    if label == "Lubrication Degradation":
        return int(rng.uniform(110, 200) + severity * rng.uniform(40, 200))
    if label == "Normal Operation":
        return int(rng.uniform(5, 90))
    return int(rng.uniform(20, 180))


def _fmt(sensor: str, value: Optional[float]) -> str:
    if value is None:
        return "unavailable"
    units = {"Temperature": "°C", "Vibration": "", "Pressure": " PSI", "RPM": " RPM",
             "Current": " A", "Voltage": " V", "Flow_Rate": " L/min"}
    d = DECIMALS[sensor]
    txt = f"{value:.{d}f}" if d else f"{int(value)}"
    return f"{txt}{units[sensor]}"


def _reasoning(label: str, p: Dict[str, Optional[float]], scenario: str,
               secondary: Optional[str] = None) -> str:
    """Synthetic record narrative — explicitly framed as a synthetic scenario."""
    vals = ", ".join(f"{s.replace('_', ' ').lower()} {_fmt(s, p[s])}" for s in SENSORS)
    txt = (f"[SYNTHETIC scenario '{scenario}'] Recorded values: {vals}. "
           f"Scenario pattern: {PATTERN_TEXT[label]}.")
    if secondary:
        txt += f" Symptoms of {secondary.lower()} are also present in this scenario."
    missing = [s for s in SENSORS if p[s] is None]
    if missing:
        txt += (" Channels without data: "
                + ", ".join(m.replace('_', ' ').lower() for m in missing)
                + "; no values were recorded for them.")
    return txt


def _options(rng, correct: str, distractor_pool: Sequence[str]) -> Tuple[List[str], str]:
    pool = [l for l in distractor_pool if l != correct]
    distractors = list(rng.choice(pool, size=3, replace=False))
    opts = distractors + [correct]
    rng.shuffle(opts)
    letter = "ABCD"[opts.index(correct)]
    return opts, letter


@dataclass
class Row:
    label: str
    scenario: str
    profile: Dict[str, Optional[float]]
    severity_name: str
    difficulty: str
    ambiguity: float
    human: bool
    context: str
    secondary: Optional[str] = None
    expected_ambiguity: bool = False


def _row_to_record(rng, idx: int, r: Row, id_prefix: str = "SYN") -> Dict:
    opts, letter = _options(rng, r.label, ALL_LABELS)
    sev_hours = SEVERITY_LEVELS.get(r.severity_name, 0.7)
    rec = {
        "Question_ID": f"{id_prefix}-{idx:06d}",
        "System_Context": r.context,
    }
    for s in SENSORS:
        rec[s] = r.profile[s]
    rec.update({
        "MCQ_Question": QUESTION_STEMS[idx % len(QUESTION_STEMS)],
        "Option_A": opts[0], "Option_B": opts[1], "Option_C": opts[2], "Option_D": opts[3],
        "Correct_Answer": letter,
        "Difficulty_Level": r.difficulty,
        "Ambiguity_Score": round(r.ambiguity, 3),
        "Correct_Answer_Reasoning": _reasoning(r.label, r.profile, r.scenario, r.secondary),
        "Human_Intervention_Recommended": "Yes" if r.human else "No",
        # extra metadata not present in the original AFRB schema
        "Asset_ID": f"SYN-ASSET-{int(rng.integers(1, 400)):03d}",
        "Component": COMPONENT[r.label],
        "Severity": "None" if r.label == "Normal Operation" else SEVERITY_LABEL.get(r.severity_name, "Medium"),
        "Operating_Hours": _operating_hours(rng, r.label, sev_hours),
        "Last_Maintenance_Days": _maintenance_days(rng, r.label, sev_hours),
        # provenance (never embedded as evidence content)
        "Source_Type": "synthetic",
        "Synthetic": True,
        "Synthetic_Scenario": r.scenario,
        "Synthetic_Generator_Version": GENERATOR_VERSION,
        "Synthetic_Record_ID": f"{id_prefix}-{idx:06d}",
        "Secondary_Failure_Mode": r.secondary or "",
        "Expected_Ambiguity": r.expected_ambiguity,
    })
    return rec


# ─────────────────────────────────────────────────────────────────────────────
# Scenario family generators (deterministic given rng)
# ─────────────────────────────────────────────────────────────────────────────

def _ctx(rng, label: str) -> str:
    return str(rng.choice(SCENARIO_CONTEXTS.get(label, CONTEXTS_ALL)))


def _graded(rng, label: str, n_per_level: int) -> List[Row]:
    rows = []
    for level, sev in SEVERITY_LEVELS.items():
        for _ in range(n_per_level):
            s = float(np.clip(sev + rng.normal(0, 0.05), 0.25, 1.1))
            amb = {"mild": rng.uniform(0.45, 0.7), "moderate": rng.uniform(0.2, 0.45),
                   "severe": rng.uniform(0.02, 0.3)}[level]
            rows.append(Row(label, SCENARIO_KEY[label], _profile(rng, label, s), level,
                            {"mild": "Medium", "moderate": "Easy", "severe": "Easy"}[level],
                            float(amb), False, _ctx(rng, label)))
    return rows


def generate_normal_cases(rng, n: int) -> List[Row]:
    return [Row("Normal Operation", "normal_operation", _profile(rng, "Normal Operation", 0.0, 0.8),
                "none", "Easy", float(rng.uniform(0.0, 0.2)), False, _ctx(rng, "Normal Operation"))
            for _ in range(n)]


def generate_bearing_cases(rng, n_per_level: int) -> List[Row]:
    return _graded(rng, "Bearing Wear", n_per_level)


def generate_shaft_cases(rng, n_per_level: int) -> List[Row]:
    return _graded(rng, "Rotor Imbalance", n_per_level)


def generate_lubrication_cases(rng, n_per_level: int) -> List[Row]:
    return _graded(rng, "Lubrication Degradation", n_per_level)


def generate_seal_cases(rng, n_per_level: int) -> List[Row]:
    return _graded(rng, "Seal Failure", n_per_level)


def generate_gearbox_cases(rng, n_per_level: int) -> List[Row]:
    return _graded(rng, "Gearbox Degradation", n_per_level)


def generate_pump_cases(rng, n_per_level: int) -> List[Row]:
    return _graded(rng, "Pump Cavitation", n_per_level)


def generate_existing_class_mild_cases(rng, n: int) -> List[Row]:
    """Mild (early-stage) variants of AFRB classes — AFRB has no severity gradation."""
    rows = []
    for label in ["Cooling System Failure", "Electrical Overload", "Valve Blockage"]:
        for _ in range(n):
            s = float(rng.uniform(0.35, 0.55))
            rows.append(Row(label, SCENARIO_KEY[label] + "_mild", _profile(rng, label, s), "mild",
                            "Medium", float(rng.uniform(0.4, 0.65)), False, _ctx(rng, label)))
    return rows


AMBIGUOUS_PAIRS = [
    ("Bearing Wear", "Rotor Imbalance"),
    ("Lubrication Degradation", "Bearing Wear"),
    ("Seal Failure", "Pump Cavitation"),
    ("Gearbox Degradation", "Lubrication Degradation"),
    ("Cooling System Failure", "Lubrication Degradation"),
]


def generate_ambiguous_cases(rng, n_per_pair: int) -> List[Row]:
    rows = []
    for a, b in AMBIGUOUS_PAIRS:
        for _ in range(n_per_pair):
            alpha = float(rng.uniform(0.42, 0.58))
            label = a if alpha >= 0.5 else b
            other = b if label == a else a
            ctx_label = a if a in SCENARIO_CONTEXTS else (b if b in SCENARIO_CONTEXTS else a)
            rows.append(Row(label, f"ambiguous_{SCENARIO_KEY[a]}_vs_{SCENARIO_KEY[b]}",
                            _mix(rng, a, b, alpha), "moderate", "Hard",
                            float(rng.uniform(0.7, 0.95)), True, _ctx(rng, ctx_label),
                            secondary=other, expected_ambiguity=True))
    return rows


MIXED_PAIRS = [("Bearing Wear", "Lubrication Degradation"), ("Seal Failure", "Pump Cavitation")]


def generate_mixed_symptom_cases(rng, n_per_pair: int) -> List[Row]:
    rows = []
    for a, b in MIXED_PAIRS:
        for _ in range(n_per_pair):
            p = _mix(rng, a, b, float(rng.uniform(0.6, 0.72)))
            rows.append(Row(a, f"mixed_{SCENARIO_KEY[a]}_with_{SCENARIO_KEY[b]}", p, "moderate",
                            "Medium", float(rng.uniform(0.45, 0.7)), False,
                            _ctx(rng, a), secondary=b, expected_ambiguity=False))
    return rows


FAULT_LABELS = [l for l in ALL_LABELS if l not in ("Normal Operation", "Sensor Malfunction")]


def generate_missing_data_cases(rng, n: int, forced_missing: Optional[List[str]] = None,
                                labels: Optional[List[str]] = None) -> List[Row]:
    rows = []
    for _ in range(n):
        label = str(rng.choice(labels or FAULT_LABELS))
        p = _profile(rng, label, float(rng.uniform(0.75, 1.0)))
        if forced_missing:
            drop = list(forced_missing)
        else:
            k = int(rng.integers(1, 4))
            drop = list(rng.choice([s for s in SENSORS if s != "RPM"], size=k, replace=False))
        for s in drop:
            p[s] = None
        rows.append(Row(label, "missing_" + "_".join(d.lower() for d in drop), p, "moderate",
                        "Medium", float(rng.uniform(0.4, 0.75)), len(drop) >= 2, _ctx(rng, label),
                        expected_ambiguity=len(drop) >= 2))
    return rows


def generate_contradictory_cases(rng, n: int) -> List[Row]:
    """Physically inconsistent sensor combinations (instrumentation suspect)."""
    rows = []
    kinds = ["vibration_while_stopped", "cold_under_heavy_load", "flow_without_pressure_drop"]
    for i in range(n):
        kind = kinds[i % len(kinds)]
        p = _profile(rng, "Normal Operation", 0.0, 0.8)
        if kind == "vibration_while_stopped":
            p["RPM"] = float(int(rng.uniform(0, 80)))            # stopped shaft
            p["Vibration"] = _round("Vibration", rng.uniform(0.75, 0.97))
        elif kind == "cold_under_heavy_load":
            p["Temperature"] = _round("Temperature", rng.uniform(15, 22))
            p["Current"] = _round("Current", rng.uniform(128, 148))
        else:
            p["Flow_Rate"] = _round("Flow_Rate", rng.uniform(185, 200))
            p["Pressure"] = _round("Pressure", rng.uniform(92, 100))
            p["Current"] = _round("Current", rng.uniform(6, 14))
        rows.append(Row("Sensor Malfunction", f"contradictory_{kind}", p, "moderate", "Hard",
                        float(rng.uniform(0.75, 0.98)), True, _ctx(rng, "Normal Operation"),
                        expected_ambiguity=True))
    return rows


# ─────────────────────────────────────────────────────────────────────────────
# Knowledge-base dataset
# ─────────────────────────────────────────────────────────────────────────────

def generate_knowledge_base(seed: int = 523) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows: List[Row] = []
    rows += generate_normal_cases(rng, 1000)
    rows += generate_bearing_cases(rng, 150)
    rows += generate_shaft_cases(rng, 150)
    rows += generate_lubrication_cases(rng, 150)
    rows += generate_seal_cases(rng, 200)
    rows += generate_gearbox_cases(rng, 200)
    rows += generate_pump_cases(rng, 200)
    rows += generate_existing_class_mild_cases(rng, 100)
    rows += generate_ambiguous_cases(rng, 120)
    rows += generate_mixed_symptom_cases(rng, 150)
    rows += generate_missing_data_cases(rng, 700)
    rows += generate_contradictory_cases(rng, 300)
    recs = [_row_to_record(rng, i + 1, r) for i, r in enumerate(rows)]
    df = pd.DataFrame(recs)
    return df


# ─────────────────────────────────────────────────────────────────────────────
# Held-out evaluation scenarios (never indexed)
# ─────────────────────────────────────────────────────────────────────────────

QUERY_TEMPLATES = [
    "{ctx}: {readings}. What is the most likely fault?",
    "Diagnose this asset — {ctx}. Current readings: {readings}.",
    "We are seeing the following on the {ctx_short}: {readings}. What failure mode does this indicate?",
    "{ctx}. Telemetry: {readings}. Which failure is most probable and what should we do?",
]

SENSOR_WORDS = {"Temperature": "temperature", "Vibration": "vibration", "Pressure": "pressure",
                "RPM": "speed", "Current": "current", "Voltage": "voltage", "Flow_Rate": "flow rate"}


def readings_text(p: Dict[str, Optional[float]]) -> str:
    parts = []
    for s in SENSORS:
        v = p.get(s)
        if v is None:
            parts.append(f"{SENSOR_WORDS[s]} reading unavailable")
            continue
        if s == "Temperature":
            parts.append(f"temperature {v:.1f} °C")
        elif s == "Vibration":
            parts.append(f"vibration {v:.3f}")
        elif s == "Pressure":
            parts.append(f"pressure {v:.1f} PSI")
        elif s == "RPM":
            parts.append(f"{int(v)} RPM")
        elif s == "Current":
            parts.append(f"current {v:.1f} A")
        elif s == "Voltage":
            parts.append(f"voltage {v:.1f} V")
        else:
            parts.append(f"flow rate {v:.1f} L/min")
    return ", ".join(parts)


def _query(rng, ctx: str, p: Dict[str, Optional[float]]) -> str:
    tpl = QUERY_TEMPLATES[int(rng.integers(0, len(QUERY_TEMPLATES)))]
    short = ctx.split(" in ")[0].split(" driving ")[0].lower()
    return tpl.format(ctx=ctx, ctx_short=short, readings=readings_text(p))


def _test_case(rng, case_id: str, category: str, row: Row, acceptable: List[str],
               expected_ambiguity: bool, expect_no_match: bool = False,
               expected_pattern: Optional[str] = None) -> Dict:
    return {
        "case_id": case_id,
        "category": category,
        "scenario": row.scenario,
        "source_type": "synthetic",
        "question": _query(rng, row.context, row.profile),
        "system_context": row.context,
        **{f"sensor_{s}": row.profile[s] for s in SENSORS},
        "expected_failure_mode": row.label,
        "acceptable_labels": json.dumps(acceptable),
        "expected_ambiguity": bool(expected_ambiguity),
        "expect_no_historical_match": bool(expect_no_match),
        "expected_sensor_pattern": expected_pattern or PATTERN_TEXT.get(row.label, ""),
        "missing_sensors": json.dumps([s for s in SENSORS if row.profile[s] is None]),
        "exclude_record_id": "",
    }


def generate_test_scenarios(seed: int = 2026, real_csv: Optional[Path] = None,
                            n_real_per_class: int = 10) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    cases: List[Dict] = []
    k = 0

    def add(category, row, acceptable, amb, no_match=False, pattern=None):
        nonlocal k
        k += 1
        cases.append(_test_case(rng, f"T-{k:04d}", category, row, acceptable, amb, no_match, pattern))

    # clear single-fault scenarios (severe)
    for label, n in [("Bearing Wear", 12), ("Rotor Imbalance", 12), ("Lubrication Degradation", 12),
                     ("Seal Failure", 12), ("Gearbox Degradation", 10), ("Pump Cavitation", 12),
                     ("Cooling System Failure", 8), ("Electrical Overload", 8), ("Valve Blockage", 8)]:
        for _ in range(n):
            row = Row(label, SCENARIO_KEY[label], _profile(rng, label, float(rng.uniform(0.9, 1.05)), 0.8),
                      "severe", "Easy", 0.1, False, _ctx(rng, label))
            add("clear_fault", row, [label], False)

    # Case E — normal equipment
    for _ in range(15):
        row = Row("Normal Operation", "normal_operation", _profile(rng, "Normal Operation", 0.0, 0.6),
                  "none", "Easy", 0.05, False, _ctx(rng, "Normal Operation"))
        add("normal_equipment", row, ["Normal Operation"], False)

    # Case A — missing temperature with high vibration
    for r in generate_missing_data_cases(rng, 12, forced_missing=["Temperature"],
                                         labels=["Bearing Wear", "Rotor Imbalance"]):
        add("missing_temperature", r, ["Bearing Wear", "Rotor Imbalance"], True,
            pattern="high vibration; temperature channel missing")

    # Case B — conflicting signals: high vibration, normal temperature/pressure/current
    for _ in range(12):
        p = _profile(rng, "Normal Operation", 0.0, 0.6)
        p["Vibration"] = _round("Vibration", rng.uniform(0.8, 0.95))
        row = Row("Rotor Imbalance", "conflicting_high_vibration_normal_temperature", p, "moderate",
                  "Hard", 0.8, True, _ctx(rng, "Normal Operation"))
        add("conflicting_signals", row, ["Rotor Imbalance", "Bearing Wear", "Insufficient Evidence"], True,
            pattern="high vibration while temperature, pressure and current are normal")

    # Case C — no historical match (pattern absent from the knowledge base)
    for _ in range(12):
        p = {"Temperature": _round("Temperature", rng.uniform(112, 122)),
             "Vibration": _round("Vibration", rng.uniform(0.02, 0.06)),
             "Pressure": _round("Pressure", rng.uniform(94, 99)),
             "RPM": float(int(rng.uniform(4600, 4950))),
             "Current": _round("Current", rng.uniform(24, 34)),
             "Voltage": _round("Voltage", rng.uniform(460, 478)),
             "Flow_Rate": _round("Flow_Rate", rng.uniform(186, 199))}
        row = Row("Insufficient Evidence", "no_historical_match", p, "moderate", "Hard", 0.95, True,
                  _ctx(rng, "Normal Operation"))
        add("no_historical_match", row, ["Insufficient Evidence", "Sensor Malfunction"], True, True,
            pattern="combination not represented in the knowledge base")

    # Case D — ambiguous bearing degradation vs shaft imbalance
    for _ in range(12):
        alpha = float(rng.uniform(0.45, 0.55))
        row = Row("Bearing Wear" if alpha >= 0.5 else "Rotor Imbalance",
                  "ambiguous_bearing_vs_imbalance", _mix(rng, "Bearing Wear", "Rotor Imbalance", alpha),
                  "moderate", "Hard", 0.85, True, _ctx(rng, "Bearing Wear"))
        add("ambiguous_failure", row, ["Bearing Wear", "Rotor Imbalance"], True,
            pattern="between bearing wear and rotor imbalance signatures")

    # contradictory sensors
    for r in generate_contradictory_cases(rng, 9):
        add("contradictory_sensors", r, ["Sensor Malfunction", "Insufficient Evidence"], True,
            pattern="physically inconsistent channel combination")

    # mixed symptoms
    for r in generate_mixed_symptom_cases(rng, 5):
        add("mixed_symptoms", r, [r.label, r.secondary], False,
            pattern=f"{PATTERN_TEXT[r.label]} plus {r.secondary.lower()} symptoms")

    df = pd.DataFrame(cases)

    # held-out real AFRB records (excluded from retrieval at evaluation time)
    if real_csv is not None and Path(real_csv).exists():
        real = pd.read_csv(real_csv, low_memory=False)
        real["label"] = real.apply(lambda r: r["Option_" + r["Correct_Answer"]], axis=1)
        picks = real.groupby("label").sample(n=n_real_per_class, random_state=seed)
        real_cases = []
        for _, r in picks.iterrows():
            k += 1
            p = {s: float(r[s]) for s in SENSORS}
            human = str(r["Human_Intervention_Recommended"]).strip().lower() == "yes"
            real_cases.append({
                "case_id": f"T-{k:04d}", "category": "real_afrb_holdout", "scenario": "real_record",
                "source_type": "real",
                "question": _query(rng, r["System_Context"], p),
                "system_context": r["System_Context"],
                **{f"sensor_{s}": p[s] for s in SENSORS},
                "expected_failure_mode": r["label"],
                "acceptable_labels": json.dumps([r["label"]]),
                "expected_ambiguity": human,
                "expect_no_historical_match": False,
                "expected_sensor_pattern": PATTERN_TEXT.get(r["label"], ""),
                "missing_sensors": "[]",
                "exclude_record_id": r["Question_ID"],
            })
        df = pd.concat([df, pd.DataFrame(real_cases)], ignore_index=True)
    return df


# ─────────────────────────────────────────────────────────────────────────────
# Gap analysis & validation
# ─────────────────────────────────────────────────────────────────────────────

def analyse_gaps(real_csv: Path) -> Dict:
    df = pd.read_csv(real_csv, low_memory=False)
    df["label"] = df.apply(lambda r: r["Option_" + r["Correct_Answer"]], axis=1)
    missing = {s: float(df[s].isna().mean()) for s in SENSORS}
    return {
        "records": int(len(df)),
        "label_distribution": df["label"].value_counts().to_dict(),
        "difficulty_distribution": df["Difficulty_Level"].value_counts().to_dict(),
        "human_intervention_rate": float((df["Human_Intervention_Recommended"] == "Yes").mean()),
        "missing_value_rate_per_sensor": missing,
        "system_contexts": int(df["System_Context"].nunique()),
        "label_context_dependence": "none observed (contexts are uniformly distributed across labels)",
        "gaps_identified": [
            "No normal-operation / no-fault class: every record is a failure",
            "No missing sensor values at all (0% missing)",
            "No seal-failure, pump-cavitation or gearbox-specific degradation scenarios",
            "No severity gradation (mild / moderate / severe)",
            "No physically contradictory sensor combinations",
            "No explicit mixed-symptom (co-occurring fault) cases",
            "No 'no historical match' situations to test abstention",
            "No asset metadata such as operating hours / maintenance interval / component",
        ],
    }


def validate(df: pd.DataFrame) -> Dict:
    """Automatic validation of generated records."""
    report: Dict = {"records": int(len(df)), "checks": {}}
    for s in SENSORS:
        col = pd.to_numeric(df[s], errors="coerce")
        lo, hi = BOUNDS[s]
        present = col.dropna()
        if s == "RPM":
            lo = 0.0
        report["checks"][f"{s}_range"] = {
            "min": float(present.min()), "max": float(present.max()),
            "bounds": [lo, hi], "ok": bool(((present >= lo) & (present <= hi)).all()),
            "missing_rate": float(col.isna().mean()),
        }
    oh = df["Operating_Hours"]
    report["checks"]["operating_hours"] = {"min": int(oh.min()), "max": int(oh.max()),
                                           "ok": bool((oh > 0).all())}
    dup_cols = SENSORS + ["System_Context"]
    report["checks"]["duplicate_rate"] = float(df.duplicated(subset=dup_cols).mean())
    report["checks"]["all_marked_synthetic"] = bool((df["Synthetic"] == True).all()  # noqa: E712
                                                   and (df["Source_Type"] == "synthetic").all())
    labels = df.apply(lambda r: r["Option_" + r["Correct_Answer"]], axis=1)
    report["label_distribution"] = labels.value_counts().to_dict()
    report["scenario_family_distribution"] = (
        df["Synthetic_Scenario"].str.replace(r"_(mild)$", "", regex=True)
        .str.split("_").str[0].value_counts().to_dict())
    report["severity_distribution"] = df["Severity"].value_counts().to_dict()
    report["overall_missing_value_rate"] = float(df[SENSORS].isna().mean().mean())

    # internal relationship checks on complete, non-ambiguous records
    clean = df[(df["Synthetic_Scenario"].isin(list(SCENARIO_KEY.values())))].copy()
    clean["label"] = labels.loc[clean.index]
    med = clean.groupby("label")[SENSORS].median()
    rel = {}
    if {"Normal Operation", "Bearing Wear"} <= set(med.index):
        rel["bearing_vibration_gt_normal"] = bool(med.loc["Bearing Wear", "Vibration"] > med.loc["Normal Operation", "Vibration"])
        rel["bearing_temperature_gt_normal"] = bool(med.loc["Bearing Wear", "Temperature"] > med.loc["Normal Operation", "Temperature"])
    if "Rotor Imbalance" in med.index:
        rel["imbalance_temperature_lt_bearing"] = bool(med.loc["Rotor Imbalance", "Temperature"] < med.loc["Bearing Wear", "Temperature"])
    if "Seal Failure" in med.index:
        rel["seal_pressure_lt_normal"] = bool(med.loc["Seal Failure", "Pressure"] < med.loc["Normal Operation", "Pressure"])
    if "Pump Cavitation" in med.index:
        rel["cavitation_flow_lt_normal"] = bool(med.loc["Pump Cavitation", "Flow_Rate"] < med.loc["Normal Operation", "Flow_Rate"])
    if "Lubrication Degradation" in med.index:
        rel["lubrication_temperature_gt_normal"] = bool(med.loc["Lubrication Degradation", "Temperature"] > med.loc["Normal Operation", "Temperature"])
    rel["gearbox_only_on_gear_contexts"] = bool(
        df.loc[labels == "Gearbox Degradation", "System_Context"].isin(CONTEXTS_GEAR).all())
    rel["lubrication_maintenance_delay_gt_normal"] = bool(
        df.loc[labels == "Lubrication Degradation", "Last_Maintenance_Days"].median()
        > df.loc[labels == "Normal Operation", "Last_Maintenance_Days"].median())
    report["relationship_checks"] = rel
    report["all_checks_passed"] = bool(
        all(v.get("ok", True) for v in report["checks"].values() if isinstance(v, dict))
        and report["checks"]["all_marked_synthetic"] and all(rel.values())
        and report["checks"]["duplicate_rate"] < 0.01)
    return report


def main() -> None:
    backend = Path(__file__).resolve().parent.parent
    real_csv = backend / "data" / "afrb_sample.csv"
    out_dir = backend / "data" / "synthetic"
    out_dir.mkdir(parents=True, exist_ok=True)

    kb = generate_knowledge_base()
    kb.to_csv(out_dir / "afrb_synthetic.csv", index=False)
    tests = generate_test_scenarios(real_csv=real_csv)
    tests.to_csv(out_dir / "test_scenarios.csv", index=False)

    report = {"generator_version": GENERATOR_VERSION,
              "knowledge_base": validate(kb),
              "test_scenarios": {"cases": int(len(tests)),
                                 "by_category": tests["category"].value_counts().to_dict()}}
    if real_csv.exists():
        report["gap_analysis"] = analyse_gaps(real_csv)
    (out_dir / "validation_report.json").write_text(json.dumps(report, indent=2, default=str))
    print(json.dumps({"kb_records": len(kb), "test_cases": len(tests),
                      "all_checks_passed": report["knowledge_base"]["all_checks_passed"]}, indent=2))


if __name__ == "__main__":
    main()
