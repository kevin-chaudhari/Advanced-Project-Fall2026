"""
Canonical record schema shared by REAL and SYNTHETIC data.

Both the original AFRB CSV and the synthetic CSV (same column schema plus
provenance columns) are converted into ``CanonicalRecord`` objects by the same
function, so synthetic data goes through exactly the same preprocessing,
feature engineering, embedding and retrieval path as real data.

Important preprocessing rule: **missing sensor values stay missing**.  The
original loader filled numeric gaps with the column median, which silently
fabricated sensor readings; the canonical schema keeps ``None``.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

SENSORS = ["temperature", "vibration", "pressure", "rpm", "current", "voltage", "flow_rate"]

SENSOR_SPECS: Dict[str, Dict[str, Any]] = {
    "temperature": {"label": "Temperature", "unit": "°C", "csv": "Temperature", "decimals": 1},
    "vibration":   {"label": "Vibration", "unit": "(norm. index)", "csv": "Vibration", "decimals": 3},
    "pressure":    {"label": "Pressure", "unit": "PSI", "csv": "Pressure", "decimals": 1},
    "rpm":         {"label": "Speed", "unit": "RPM", "csv": "RPM", "decimals": 0},
    "current":     {"label": "Current", "unit": "A", "csv": "Current", "decimals": 1},
    "voltage":     {"label": "Voltage", "unit": "V", "csv": "Voltage", "decimals": 1},
    "flow_rate":   {"label": "Flow rate", "unit": "L/min", "csv": "Flow_Rate", "decimals": 1},
}

EQUIPMENT_KEYWORDS = [
    ("gearbox", ["gearbox", "gear box", "gear train", "gear"]),
    ("pump", ["pump"]),
    ("compressor", ["compressor"]),
    ("turbine", ["turbine"]),
    ("fan", ["fan", "blower"]),
    ("conveyor", ["conveyor"]),
    ("press", ["press"]),
    ("mixer", ["mixer"]),
    ("extruder", ["extruder"]),
    ("spindle", ["spindle"]),
    ("transformer", ["transformer"]),
    ("engine", ["engine"]),
    ("generator", ["generator"]),
    ("motor", ["motor"]),
]


def equipment_type_of(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    t = text.lower()
    for etype, kws in EQUIPMENT_KEYWORDS:
        if any(re.search(rf"\b{re.escape(k)}", t) for k in kws):
            return etype
    return None


def fmt_sensor(sensor: str, value: Optional[float]) -> str:
    if value is None:
        return "unavailable"
    spec = SENSOR_SPECS[sensor]
    d = spec["decimals"]
    num = f"{value:.{d}f}" if d else f"{int(round(value))}"
    unit = spec["unit"]
    if sensor == "vibration":
        return num
    return f"{num} {unit}" if unit != "°C" else f"{num}°C"


def _num(v: Any) -> Optional[float]:
    if v is None:
        return None
    if isinstance(v, str):
        v = v.strip()
        if v == "" or v.lower() in ("nan", "n/a", "na", "unknown", "none", "null"):
            return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) else f


def _str(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, float) and math.isnan(v):
        return ""
    return str(v).strip()


@dataclass
class CanonicalRecord:
    record_id: str
    dataset: str
    source_type: str                       # "real" | "synthetic"
    label: Optional[str]
    text: str
    sensors: Dict[str, Optional[float]] = field(default_factory=dict)
    system_context: str = ""
    equipment_type: Optional[str] = None
    component: str = ""
    severity: str = ""
    difficulty: str = ""
    ambiguity_score: Optional[float] = None
    human_review: Optional[bool] = None
    operating_hours: Optional[float] = None
    last_maintenance_days: Optional[float] = None
    secondary_label: str = ""
    synthetic_scenario: str = ""
    generator_version: str = ""
    reasoning: str = ""
    extra: Dict[str, Any] = field(default_factory=dict)

    def evidence_content(self) -> Dict[str, Any]:
        content: Dict[str, Any] = {
            "system_context": self.system_context,
            "equipment_type": self.equipment_type,
            "failure_mode": self.label,
            "sensors": {s: self.sensors.get(s) for s in SENSORS} if self.sensors else {},
        }
        for key in ("component", "severity", "difficulty", "secondary_label",
                    "synthetic_scenario", "generator_version"):
            val = getattr(self, key)
            if val:
                content[key] = val
        if self.ambiguity_score is not None:
            content["ambiguity_score"] = self.ambiguity_score
        if self.human_review is not None:
            content["human_review_recommended"] = self.human_review
        if self.operating_hours is not None:
            content["operating_hours"] = self.operating_hours
        if self.last_maintenance_days is not None:
            content["last_maintenance_days"] = self.last_maintenance_days
        if self.extra:
            content.update(self.extra)
        return content


# ─────────────────────────────────────────────────────────────────────────────
# AFRB (real + synthetic) rows
# ─────────────────────────────────────────────────────────────────────────────

# Provenance / ground-truth columns that must never be embedded as evidence text.
NON_EVIDENCE_COLUMNS = {
    "source_type", "synthetic", "synthetic_scenario", "synthetic_generator_version",
    "synthetic_record_id", "expected_ambiguity", "secondary_failure_mode",
}


def normalise_column(c: str) -> str:
    return re.sub(r"[^a-z0-9_]", "_", c.lower().strip())


def afrb_row_text(row: Dict[str, Any], columns: List[str]) -> str:
    """Text used for embedding.  Identical formatting to the original loader
    (so the persisted real-data FAISS vectors remain valid), except that
    missing values are written explicitly as 'unavailable' instead of being
    imputed, and provenance columns are excluded."""
    parts = []
    for col in columns:
        if col in NON_EVIDENCE_COLUMNS:
            continue
        val = row.get(col)
        sval = _str(val)
        label = col.replace("_", " ").title()
        if col in SENSORS:
            if _num(val) is None:
                parts.append(f"{label}: unavailable")
                continue
        if sval.lower() in ("", "nan", "unknown"):
            continue
        parts.append(f"{label}: {val}")
    if str(row.get("source_type", "")).lower() == "synthetic":
        parts.append("Source Type: SYNTHETIC")
    return "\n".join(parts) if parts else "No data."


def afrb_row_to_record(row: Dict[str, Any], columns: List[str], dataset: str = "afrb") -> CanonicalRecord:
    source = _str(row.get("source_type")).lower() or "real"
    if source not in ("real", "synthetic"):
        source = "real"
    label = None
    ans = _str(row.get("correct_answer")).upper()
    if ans in ("A", "B", "C", "D"):
        label = _str(row.get(f"option_{ans.lower()}")) or None
    elif _str(row.get("failure_mode")):
        label = _str(row.get("failure_mode"))

    sensors: Dict[str, Optional[float]] = {}
    aliases = {
        "temperature": ["temperature", "temperature_c"],
        "vibration": ["vibration", "vibration_mms"],
        "pressure": ["pressure", "pressure_bar"],
        "rpm": ["rpm"],
        "current": ["current"],
        "voltage": ["voltage"],
        "flow_rate": ["flow_rate", "flow_rate_lpm"],
    }
    for s, keys in aliases.items():
        val = None
        for k in keys:
            if k in row:
                val = _num(row.get(k))
                break
        sensors[s] = val

    context = _str(row.get("system_context")) or _str(row.get("asset_name")) or _str(row.get("system"))
    record_id = _str(row.get("question_id")) or _str(row.get("synthetic_record_id")) or _str(row.get("asset_id"))
    human = _str(row.get("human_intervention_recommended")).lower()
    return CanonicalRecord(
        record_id=record_id,
        dataset=dataset,
        source_type=source,
        label=label,
        text=afrb_row_text(row, columns),
        sensors=sensors,
        system_context=context,
        equipment_type=equipment_type_of(context),
        component=_str(row.get("component")),
        severity=_str(row.get("severity")),
        difficulty=_str(row.get("difficulty_level")),
        ambiguity_score=_num(row.get("ambiguity_score")),
        human_review=(human == "yes") if human in ("yes", "no") else None,
        operating_hours=_num(row.get("operating_hours")),
        last_maintenance_days=_num(row.get("last_maintenance_days")),
        secondary_label=_str(row.get("secondary_failure_mode")),
        synthetic_scenario=_str(row.get("synthetic_scenario")),
        generator_version=_str(row.get("synthetic_generator_version")),
        reasoning=_str(row.get("correct_answer_reasoning")),
    )


# ─────────────────────────────────────────────────────────────────────────────
# FailureSensorIQ rows
# ─────────────────────────────────────────────────────────────────────────────

_NEG = re.compile(r"\b(not|irrelevant|non-relevant|excluded|exclude|least|should not|unrelated|disregard(?:ed)?|ignored?)\b")

FIQ_EQUIPMENT = [
    "reciprocating internal combustion engine", "industrial gas turbine", "aero gas turbine",
    "steam turbine", "power transformer", "electric generator", "electric motor",
    "compressor", "pump", "fan",
]

_FE_PATTERNS = [
    r"failure event (.+?) (?:occurs|happens)", r"if (.+?) (?:occurs|happens)", r"when (.+?) occurs",
    r"has (.+?), which", r"dealing with (.+?) in ", r"presence of (.+?) in ", r"considering (.+?) in ",
    r"detecting (.+?) in ", r"detecting (.+?)\?", r"identifying (.+?)\?", r"for (.+?) in (?:asset )?[a-z ]+\?$",
]
_SENSOR_PATTERNS = [
    r"abnormal readings? (?:is detected )?(?:from|by) the sensor (.+?)(?:\?| in |,|$)",
    r"by the sensor (.+?)(?:\?| in |,|$)", r"the sensor (.+?)(?:\?| in |,| shows| detects|$)",
    r"when (.+?) (?:detects|shows) abnormal", r"when (.+?) shows abnormal",
    r"if (.+?) (?:registers|exhibits|has|shows|detects) abnormal", r"when (.+?) (?:has|registers|exhibits) abnormal",
    r"detected by (.+?)\?", r"from the sensor (.+?)\?",
]


def parse_failure_iq_question(question: str) -> Dict[str, Any]:
    """Extract equipment, anchor (failure event or sensor), polarity and what
    the answer items are (sensors or failure events)."""
    q = question.strip()
    ql = q.lower()
    polarity = "irrelevant" if _NEG.search(ql) else "relevant"
    asks_for = "failure_events" if re.search(r"failure (events|modes)", ql) else "sensors"
    equipment = next((e for e in FIQ_EQUIPMENT if e in ql), None)
    anchor, anchor_type = None, None
    patterns = _FE_PATTERNS if asks_for == "sensors" else _SENSOR_PATTERNS
    for pat in patterns:
        m = re.search(pat, ql)
        if m:
            cand = m.group(1).strip(" ,?")
            if equipment:
                cand = re.sub(rf"\s*(?:in |for )?(?:asset |the )?{re.escape(equipment)}.*$", "", cand).strip(" ,")
            cand = re.sub(r"^(?:a|an|the) ", "", cand)
            if cand and len(cand) < 90:
                anchor = cand
                anchor_type = "failure_event" if asks_for == "sensors" else "sensor"
                break
    return {"equipment": equipment, "anchor": anchor, "anchor_type": anchor_type,
            "polarity": polarity, "asks_for": asks_for}


def failure_iq_row_to_record(row: Dict[str, Any]) -> CanonicalRecord:
    question = _str(row.get("question"))
    parsed = parse_failure_iq_question(question)
    options, answers = [], []
    for i in range(5):
        opt = _str(row.get(f"options/{i}"))
        if not opt:
            continue
        options.append(opt)
        if _str(row.get(f"correct/{i}")).lower() == "true":
            answers.append(opt)
    others = [o for o in options if o not in answers]
    relevant = answers if parsed["polarity"] == "relevant" else others
    irrelevant = others if parsed["polarity"] == "relevant" else answers
    item_word = "sensors" if parsed["asks_for"] == "sensors" else "failure events"

    lines = [
        "Domain: Failure Sensor Intelligence (FailureSensorIQ)",
        f"Equipment: {parsed['equipment'] or 'unspecified'}",
    ]
    if parsed["anchor_type"] == "failure_event":
        lines.append(f"Failure Event: {parsed['anchor']}")
    elif parsed["anchor_type"] == "sensor":
        lines.append(f"Sensor: {parsed['anchor']}")
    lines += ["", "Diagnostic Question:", f"  {question}", "", "Options:"]
    lines += [f"  {chr(65 + i)}. {o}" for i, o in enumerate(options)]
    lines.append("")
    if relevant:
        lines.append(f"Relevant {item_word}: {', '.join(relevant)}")
    if irrelevant:
        lines.append(f"Not relevant {item_word}: {', '.join(irrelevant)}")

    label = parsed["anchor"] if parsed["anchor_type"] == "failure_event" else None
    return CanonicalRecord(
        record_id=f"FIQ-{_str(row.get('id'))}",
        dataset="failure_iq",
        source_type="real",
        label=label,
        text="\n".join(lines),
        sensors={},
        system_context=parsed["equipment"] or "",
        equipment_type=equipment_type_of(parsed["equipment"] or ""),
        extra={
            "anchor": parsed["anchor"], "anchor_type": parsed["anchor_type"],
            "polarity": parsed["polarity"], "asks_for": parsed["asks_for"],
            "relevant_items": relevant, "irrelevant_items": irrelevant,
        },
    )
