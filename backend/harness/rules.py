"""
Explicitly defined domain rules.

Everything in this module is a *declared* rule with an ID so that claims based
on it can be classified as DERIVED by the claim validator.  Rules are
deliberately few and conservative.

* Consistency rules (R-C*) — physically implausible channel combinations that
  point at instrumentation problems rather than at a mechanical fault.
* Band rules (R-B*) — a channel is "high"/"low" when it lies outside the
  reference band computed from the data (see KnowledgeBase.reference).
* Maintenance guidance (R-M*) — generic first actions per failure mode.  They
  are guidance templates, not facts about the specific asset.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

from harness.canonical import SENSORS, SENSOR_SPECS, fmt_sensor


@dataclass(frozen=True)
class ConsistencyRule:
    rule_id: str
    description: str
    sensors: tuple
    check: Callable[[Dict[str, float]], bool]
    thresholds: tuple = ()


CONSISTENCY_RULES: List[ConsistencyRule] = [
    ConsistencyRule("R-C1", "Strong vibration reported while the shaft is (almost) stopped (vibration ≥ 0.6 at < 100 RPM)",
                    ("vibration", "rpm"), lambda s: s["vibration"] >= 0.6 and s["rpm"] < 100, (0.6, 100)),
    ConsistencyRule("R-C2", "Near-ambient temperature under very heavy electrical load (≤ 25 °C at ≥ 120 A)",
                    ("temperature", "current"), lambda s: s["temperature"] <= 25 and s["current"] >= 120, (25, 120)),
    ConsistencyRule("R-C3", "Very high flow and pressure with almost no motor current (≥ 180 L/min, ≥ 90 PSI, ≤ 20 A)",
                    ("flow_rate", "pressure", "current"),
                    lambda s: s["flow_rate"] >= 180 and s["pressure"] >= 90 and s["current"] <= 20, (180, 90, 20)),
]

PHYSICAL_BOUNDS = {
    "temperature": (-40.0, 250.0), "vibration": (0.0, 1.0), "pressure": (0.0, 300.0),
    "rpm": (0.0, 20000.0), "current": (0.0, 1000.0), "voltage": (0.0, 1000.0), "flow_rate": (0.0, 2000.0),
}

RULE_THRESHOLDS: List[float] = sorted({t for r in CONSISTENCY_RULES for t in r.thresholds})

MAINTENANCE_GUIDANCE: Dict[str, str] = {
    "Bearing Wear": "Schedule a bearing inspection (vibration spectrum / envelope analysis) and check lubrication condition before the next run window.",
    "Rotor Imbalance": "Perform a balance check and inspect for rotor/impeller build-up, looseness or misalignment.",
    "Lubrication Degradation": "Take an oil sample, verify lubricant level/grade and re-lubricate per the OEM schedule.",
    "Cooling System Failure": "Inspect coolant flow path, pumps, fans and heat-exchanger fouling; verify coolant level.",
    "Electrical Overload": "Check load vs. motor rating, supply voltage balance and protection settings with an electrician.",
    "Valve Blockage": "Inspect valves and strainers downstream of the pump for obstruction; verify valve positions.",
    "Sensor Malfunction": "Verify instrumentation (wiring, calibration, cross-check with a portable instrument) before acting on the readings.",
    "Seal Failure": "Inspect the mechanical seal for leakage and check seal flush/barrier fluid.",
    "Pump Cavitation": "Check suction conditions (NPSH available, suction strainer, inlet valve) and reduce flow demand if needed.",
    "Gearbox Degradation": "Inspect gear teeth and gearbox oil (debris analysis) and review the gearbox's operating hours.",
    "Normal Operation": "No corrective action indicated; continue routine condition monitoring.",
}


def check_consistency(sensors: Dict[str, float]) -> List[Dict]:
    """Return triggered consistency rules for the query readings."""
    hits = []
    for rule in CONSISTENCY_RULES:
        if all(s in sensors for s in rule.sensors):
            try:
                if rule.check(sensors):
                    vals = ", ".join(f"{SENSOR_SPECS[s]['label'].lower()} {fmt_sensor(s, sensors[s])}" for s in rule.sensors)
                    hits.append({"rule_id": rule.rule_id, "description": rule.description, "observed": vals})
            except KeyError:
                continue
    for s, v in sensors.items():
        lo, hi = PHYSICAL_BOUNDS.get(s, (float("-inf"), float("inf")))
        if not (lo <= v <= hi):
            hits.append({"rule_id": "R-C0", "description": f"{SENSOR_SPECS[s]['label']} outside physical range",
                         "observed": f"{fmt_sensor(s, v)}"})
    return hits


def band_flags(sensors: Dict[str, float], band_low: Dict[str, float], band_high: Dict[str, float]) -> Dict[str, str]:
    """R-B1: channel classified 'high' / 'low' / 'normal' against the reference band."""
    out = {}
    for s, v in sensors.items():
        lo, hi = band_low.get(s), band_high.get(s)
        if lo is None or hi is None or lo != lo or hi != hi:
            continue
        out[s] = "high" if v > hi else ("low" if v < lo else "normal")
    return out


def guidance_for(label: Optional[str]) -> str:
    if not label:
        return "Collect complete sensor readings (temperature, vibration, pressure, current, flow) and re-run the diagnosis."
    return MAINTENANCE_GUIDANCE.get(label, "Inspect the affected component and confirm with additional measurements.")
