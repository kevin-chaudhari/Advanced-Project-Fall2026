"""
Deterministic claim validation (not an agent).

Every numeric statement about a physical quantity, every evidence reference
(EV-xxx / D-xxx) and every failure-mode name in agent or final output is mapped
to one of:

    SUPPORTED   – value/label present in the user's query or in a retrieved record
    DERIVED     – value computed by the harness (D-xxx) or a declared rule threshold
    UNSUPPORTED – nothing backs it  → the sentence is removed (lists) or replaced
                  by an explicit "[unverified statement removed]" marker (prose)
"""

from __future__ import annotations

import re
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from harness.canonical import SENSORS
from harness.rules import RULE_THRESHOLDS
from harness.schema import ClaimCheck, DiagnosticState

_UNIT = (r"°\s?c|°|mm/s|psi|bar\b|rpm|a\b|amps?\b|v\b|volts?\b|l/min|lpm|hrs|hours|db\b|ppm|cst|mω|days")
_NUM_UNIT = re.compile(rf"(?<![A-Za-z\-#])(\d{{1,3}}(?:,\d{{3}})+|\d+(?:\.\d+)?)\s*({_UNIT})", re.I)
_NUM = re.compile(r"(?<![A-Za-z\-#\[])(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)(?![\w\]%])")
_SENSOR_CTX = re.compile(r"temperature|temp\b|vibration|pressure|rpm|speed|current|voltage|flow|hours|maintenance", re.I)
_REF = re.compile(r"\b(EV|D)-(\d{3,})\b")
_SENT_SPLIT = re.compile(r"(?<=[.!?;])\s+")

UNVERIFIED_MARK = "[unverified statement removed]"


_UNIT_SENSOR = [("°", "temperature"), ("psi", "pressure"), ("bar", "pressure"), ("rpm", "rpm"),
                ("l/min", "flow_rate"), ("lpm", "flow_rate"), ("volt", "voltage"), ("amp", "current"),
                ("hour", "operating_hours"), ("hrs", "operating_hours"), ("day", "last_maintenance_days")]
_KW_SENSOR = [("temperature", "temperature"), ("temp", "temperature"), ("vibration", "vibration"),
              ("pressure", "pressure"), ("rpm", "rpm"), ("speed", "rpm"), ("current", "current"),
              ("voltage", "voltage"), ("flow", "flow_rate"), ("hours", "operating_hours"),
              ("maintenance", "last_maintenance_days")]


def guess_sensor(unit: str, window: str) -> Optional[str]:
    u = (unit or "").lower().strip()
    if u in ("a",):
        return "current"
    if u in ("v",):
        return "voltage"
    for key, sensor in _UNIT_SENSOR:
        if u and key in u:
            return sensor
    w = window.lower()
    best, pos = None, -1
    for key, sensor in _KW_SENSOR:
        i = w.rfind(key)
        if i > pos:
            best, pos = sensor, i
    return best


def _close(v: float, a: float) -> bool:
    tol = max(abs(a) * 0.006, 0.0051 if abs(a) < 1 else 0.051)
    return abs(v - a) <= tol


class ClaimValidator:
    def __init__(self, state: DiagnosticState, known_labels: Iterable[str]):
        self.state = state
        # (value, sensor-or-None, status, source)
        self.values: List[Tuple[float, Optional[str], str, str]] = []
        prof = state.profile
        if prof:
            for s, v in prof.sensors.items():
                self.values.append((float(v), s, "SUPPORTED", f"query:{s}"))
            for n in re.findall(r"\d+(?:\.\d+)?", prof.normalized_query):
                self.values.append((float(n), None, "SUPPORTED", "query"))
        for e in state.evidence:
            sens = e.content.get("sensors") or {}
            for s, v in sens.items():
                if v is not None:
                    self.values.append((float(v), s, "SUPPORTED", e.evidence_id))
            for k in ("operating_hours", "last_maintenance_days"):
                if e.content.get(k) is not None:
                    self.values.append((float(e.content[k]), k, "SUPPORTED", e.evidence_id))
        for d in state.derived:
            if d.value is not None:
                self.values.append((float(d.value), None, "DERIVED", d.derived_id))
        for t in RULE_THRESHOLDS:
            self.values.append((float(t), None, "DERIVED", "rule-threshold"))
        self.ev_ids = {e.evidence_id for e in state.evidence}
        self.d_ids = {d.derived_id for d in state.derived}
        self.labels = {l.lower() for l in known_labels if l} | {"insufficient evidence", "normal operation"}

    # ── primitives ───────────────────────────────────────────────────────────
    def _match(self, v: float, sensor: Optional[str] = None) -> Tuple[str, Optional[str]]:
        best = None
        for a, tag, status, src in self.values:
            if sensor and tag and tag != sensor:
                continue
            if _close(v, a):
                if status == "SUPPORTED":
                    return "SUPPORTED", src
                best = best or ("DERIVED", src)
        return best or ("UNSUPPORTED", None)

    @staticmethod
    def numeric_claims(text: str) -> List[Tuple[float, str, Optional[str]]]:
        claims, seen = [], set()
        for m in _NUM_UNIT.finditer(text):
            try:
                window = text[max(0, m.start() - 28): m.start()]
                claims.append((float(m.group(1).replace(",", "")), m.group(0), guess_sensor(m.group(2), window)))
                seen.add(m.start(1))
            except ValueError:
                pass
        low = text.lower()
        for m in _NUM.finditer(text):
            if m.start(1) in seen:
                continue
            window = low[max(0, m.start() - 28): m.start()]
            after = low[m.end(): m.end() + 22]
            if re.search(r"(ev-|d-|step|rank|top-|#)\s*$", window[-6:]):
                continue
            post = re.match(r"\s*(?:\w+\s+){0,2}?(hours|hrs|rpm|psi|volts?|amps?|l/min|mm/s|°|degrees|days)", after)
            if post:
                val = float(m.group(1).replace(",", ""))
                claims.append((val, text[max(0, m.start() - 10): m.end() + len(post.group(0))],
                               guess_sensor(post.group(1), "")))
                continue
            if _SENSOR_CTX.search(window):
                val = float(m.group(1).replace(",", ""))
                if val.is_integer() and val < 10 and "vibration" not in window:
                    continue
                claims.append((val, text[max(0, m.start() - 20): m.end()], guess_sensor("", window)))
        return claims

    def check_sentence(self, sentence: str, source: str) -> List[ClaimCheck]:
        checks: List[ClaimCheck] = []
        for val, ctx, sensor in self.numeric_claims(sentence):
            status, src = self._match(val, sensor)
            checks.append(ClaimCheck(claim=ctx.strip(), source=source, status=status, matched=src))
        for kind, num in _REF.findall(sentence):
            ref = f"{kind}-{num}"
            ok = ref in (self.ev_ids if kind == "EV" else self.d_ids)
            checks.append(ClaimCheck(claim=ref, source=source, status="SUPPORTED" if ok else "UNSUPPORTED",
                                     matched=ref if ok else None))
        return checks

    # ── public API ───────────────────────────────────────────────────────────
    def clean_text(self, text: str, source: str, prose: bool = True) -> Tuple[str, List[ClaimCheck]]:
        if not text:
            return text, []
        out, all_checks = [], []
        for sent in _SENT_SPLIT.split(text):
            checks = self.check_sentence(sent, source)
            bad = [c for c in checks if c.status == "UNSUPPORTED"]
            if bad:
                for c in bad:
                    c.action = "removed"
                if prose:
                    out.append(UNVERIFIED_MARK)
            else:
                out.append(sent)
            all_checks.extend(checks)
        cleaned = " ".join(out)
        cleaned = re.sub(rf"(?:{re.escape(UNVERIFIED_MARK)}\s*)+", UNVERIFIED_MARK + " ", cleaned).strip()
        self.state.claim_checks.extend(all_checks)
        return cleaned, all_checks

    def clean_list(self, items: Sequence[str], source: str) -> Tuple[List[str], int]:
        kept, removed = [], 0
        for it in items:
            checks = self.check_sentence(str(it), source)
            if any(c.status == "UNSUPPORTED" for c in checks):
                removed += 1
                for c in checks:
                    if c.status == "UNSUPPORTED":
                        c.action = "removed"
            else:
                kept.append(str(it))
            self.state.claim_checks.extend(checks)
        return kept, removed

    def label_supported(self, label: Optional[str]) -> bool:
        return bool(label) and label.lower() in self.labels

    def summary(self) -> Dict:
        counts = {"SUPPORTED": 0, "DERIVED": 0, "UNSUPPORTED": 0}
        removed = 0
        for c in self.state.claim_checks:
            counts[c.status] += 1
            removed += int(c.action == "removed")
        total = sum(counts.values())
        return {"total_claims": total, **counts, "removed": removed,
                "unsupported_rate": round(counts["UNSUPPORTED"] / total, 3) if total else 0.0}
