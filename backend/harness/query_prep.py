"""
Deterministic query preparation: normalisation, sensor value extraction,
explicitly-missing channels, qualitative directions and metadata extraction.

Nothing here guesses.  A sensor is only present in ``profile.sensors`` if the
user literally stated a number for it.
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

from harness.canonical import equipment_type_of
from harness.schema import QueryProfile

NUM = r"(-?\d+(?:\.\d+)?)"

_SENSOR_WORDS = {
    "temperature": r"temperature|temp",
    "vibration": r"vibration",
    "pressure": r"pressure",
    "rpm": r"rpm|speed",
    "current": r"current|amperage",
    "voltage": r"voltage",
    "flow_rate": r"flow(?:\s*rate)?",
}

_LINK = (r"\s*(?:level|amplitude|index|reading|draw|value)?\s*"
         r"(?:(?:has\s+)?(?:dropped|fell|rose|increased|decreased|climbed|spiked|jumped|risen|is|was|of|at|=|:|reads|reading|around|about|~|≈)\s*)?"
         r"(?:to\s*)?(?:approximately\s*|about\s*)?")

_PATTERNS: Dict[str, List[str]] = {
    "temperature": [rf"(?:temperature|temp)\b{_LINK}{NUM}\s*(?:°\s*c|deg(?:rees)?\s*c?|c\b)?",
                    rf"{NUM}\s*°\s*c\b", rf"{NUM}\s*deg(?:rees)?\s*c\b"],
    "vibration": [rf"vibration\b{_LINK}{NUM}"],
    "pressure": [rf"pressure\b{_LINK}{NUM}", rf"{NUM}\s*psi\b"],
    "rpm": [rf"{NUM}\s*rpm\b", rf"(?:speed|rpm)\b{_LINK}{NUM}"],
    "current": [rf"current\b{_LINK}{NUM}", rf"{NUM}\s*(?:a|amps?)\b(?!\s*/)"],
    "voltage": [rf"voltage\b{_LINK}{NUM}", rf"{NUM}\s*(?:v|volts?)\b"],
    "flow_rate": [rf"flow(?:\s*rate)?\b{_LINK}{NUM}", rf"{NUM}\s*(?:l/min|lpm)\b"],
}

_MISSING = re.compile(
    r"(temperature|temp|vibration|pressure|speed|rpm|current|voltage|flow(?:\s*rate)?)"
    r"\s*(?:sensor|channel|reading|data|value|signal)?\s*(?:is\s+|was\s+|are\s+)?"
    r"(?:unavailable|missing|offline|not available|n/a|null|unknown|not recorded|dead|failed)", re.I)

_UP = r"elevated|high|higher|increasing|increased|rising|spiking|spike|excessive|abnormal|surging"
_DOWN = r"low|lower|decreasing|decreased|dropping|drop|reduced|falling|loss of"

FAILURE_MODE_WORDS = {
    "Bearing Wear": r"bearing",
    "Rotor Imbalance": r"imbalance|unbalance",
    "Lubrication Degradation": r"lubrica",
    "Cooling System Failure": r"cooling",
    "Electrical Overload": r"overload|electrical fault",
    "Valve Blockage": r"valve|blockage",
    "Sensor Malfunction": r"sensor (?:malfunction|fault|failure)",
    "Seal Failure": r"\bseal",
    "Pump Cavitation": r"cavitation",
    "Gearbox Degradation": r"gearbox (?:degradation|wear|failure)",
}


def _canon_sensor(word: str) -> str:
    w = word.lower()
    for s, pat in _SENSOR_WORDS.items():
        if re.fullmatch(pat, w) or re.match(pat, w):
            return s
    return w


def _normalise(q: str) -> str:
    t = q.replace("℃", "°C").replace("º", "°").replace(" ", " ")
    t = re.sub(r"(\d),(\d{3})\b", r"\1\2", t)
    return re.sub(r"\s+", " ", t).strip()


def extract_sensors(text: str) -> Tuple[Dict[str, float], List[str], List[str]]:
    """Returns (values, explicit_missing, notes)."""
    low = text.lower()
    values: Dict[str, float] = {}
    notes: List[str] = []
    missing = sorted({_canon_sensor(m.group(1)) for m in _MISSING.finditer(low)})
    for sensor, pats in _PATTERNS.items():
        if sensor in missing:
            continue
        for pat in pats:
            m = re.search(pat, low)
            if m:
                try:
                    values[sensor] = float(m.group(1))
                except ValueError:
                    continue
                break
    # unit handling
    if "pressure" in values and re.search(r"pressure\b[^.,;]{0,25}?\d+(?:\.\d+)?\s*bar\b", low):
        values["pressure"] = round(values["pressure"] * 14.5038, 1)
        notes.append("pressure converted from bar to PSI (×14.5038)")
    if "vibration" in values and re.search(r"vibration\b[^.,;]{0,25}?\d+(?:\.\d+)?\s*mm/s", low):
        notes.append("vibration given in mm/s; the knowledge base uses a normalised 0–1 vibration "
                     "index, so this value was not used for numeric matching")
        values.pop("vibration")
    if "temperature" in values and re.search(r"\d+(?:\.\d+)?\s*°?\s*f\b", low):
        values["temperature"] = round((values["temperature"] - 32) * 5 / 9, 1)
        notes.append("temperature converted from °F to °C")
    return values, missing, notes


def extract_qualitative(text: str, numeric: Dict[str, float]) -> Dict[str, str]:
    low = text.lower()
    out: Dict[str, str] = {}
    sensor_alt = "|".join(_SENSOR_WORDS.values())
    for direction, words in (("high", _UP), ("low", _DOWN)):
        for m in re.finditer(rf"\b(?:{words})\b((?:\s+(?:and|,|&)?\s*(?:{sensor_alt})\b)+)", low):
            for w in re.findall(rf"(?:{sensor_alt})", m.group(1)):
                s = _canon_sensor(w)
                if s not in numeric:
                    out.setdefault(s, direction)
        for m in re.finditer(rf"\b({sensor_alt})\b\s*(?:is|are|has been|keeps)?\s*(?:{words})\b", low):
            s = _canon_sensor(m.group(1))
            if s not in numeric:
                out.setdefault(s, direction)
    if "temperature" not in numeric and re.search(r"overheat", low):
        out.setdefault("temperature", "high")
    return out


def prepare_query(question: str) -> QueryProfile:
    norm = _normalise(question)
    values, missing, notes = extract_sensors(norm)
    qual = extract_qualitative(norm, values)
    eq_type = equipment_type_of(norm)
    eq_phrase = None
    if eq_type:
        m = re.search(r"([A-Za-z\- ]{0,40}\b(?:pump|motor|compressor|turbine|fan|blower|gearbox|conveyor|press|mixer|extruder|spindle|transformer|engine|generator)\b[A-Za-z\- ]{0,40})", norm, re.I)
        eq_phrase = m.group(1).strip() if m else None
    mentioned = [fm for fm, pat in FAILURE_MODE_WORDS.items() if re.search(pat, norm.lower())]
    intent = "diagnose"
    if re.search(r"\b(which|what) (asset|equipment) has the (highest|most)", norm.lower()):
        intent = "dataset_question"
    elif re.search(r"\b(how (?:can|do|should) i|prevent|maintenance (?:is )?recommended|what maintenance)\b", norm.lower()) and not values:
        intent = "maintenance_advice"
    prof = QueryProfile(raw_query=question, normalized_query=norm, sensors=values,
                        missing_sensors=missing, qualitative=qual, equipment_type=eq_type,
                        equipment_phrase=eq_phrase, mentioned_failure_modes=mentioned, intent=intent,
                        notes=notes)
    return prof
