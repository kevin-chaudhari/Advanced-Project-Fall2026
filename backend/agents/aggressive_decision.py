"""
Rapid Triage Agent (formerly "Aggressive Decision Agent") — Commander Marcus Chen

A fast, *independent* first opinion built only from explicit deterministic
rules — no LLM call, no dependence on the other agents:

1. consistency rules (R-C*) — are the readings physically plausible?
2. band rule (R-B1) — which channels are outside the reference band?
3. signature-direction rule — which failure signature shares the direction of
   the abnormal channels?
4. severity triage from the number / size of deviations.

Its output is a ``rapid_signal`` that the Verification Analyst is expected to
challenge — never an absolute decision.  The class name is kept for backward
compatibility.
"""

from __future__ import annotations

from typing import Dict, List

from agents.base_agent import AgentContext, BaseAgent
from harness.analysis import centroid_fit, key_sensors, sensor_assessment
from harness.canonical import fmt_sensor
from harness.rules import check_consistency, guidance_for
from harness.schema import AgentReport, DiagnosticState, EvidenceStatement
from harness.statements import band_id, band_low_id, sensor_name

PERSONA_NAME = "Commander Marcus Chen"
PERSONA_EMOJI = "⚡"


class AggressiveDecisionAgent(BaseAgent):
    key = "aggressive_agent"
    uses_llm = False   # deterministic by design

    @property
    def role(self) -> str:
        return "Rapid Triage Agent"

    @property
    def goal(self) -> str:
        return "Produce a fast, rule-based rapid_signal and severity triage that later stages can challenge."

    def deterministic(self, state: DiagnosticState, ctx: AgentContext, **_) -> AgentReport:
        prof = state.profile
        support: List[EvidenceStatement] = []
        missing: List[str] = []
        if not prof or (not prof.sensors and not prof.qualitative):
            return AgentReport(agent=self.key, display_name=self.role, finding="No rapid signal (no sensor readings)",
                               missing_information=["Rapid triage needs numeric or directional sensor readings"],
                               confidence=0.0, narrative="Rapid triage skipped: the query contains no sensor readings.",
                               extras={"rapid_signal": None, "severity": "UNKNOWN", "rules_fired": []})

        violations = check_consistency(prof.sensors)
        rules_fired = [v["rule_id"] for v in violations]
        for v in violations:
            support.append(EvidenceStatement(statement=f"{v['rule_id']}: {v['description']} — observed {v['observed']}",
                                             evidence_ids=[]))

        directions: Dict[str, str] = {}
        deviations = []
        if prof.sensors:
            for s, a in sensor_assessment(prof, ctx.ref).items():
                if a["band"] in ("high", "low"):
                    directions[s] = a["band"]
                    deviations.append(abs(a["z"]))
                    did = band_id(state, ctx.ref, s) if a["band"] == "high" else band_low_id(state, ctx.ref, s)
                    support.append(EvidenceStatement(
                        statement=f"R-B1: {sensor_name(s)} {fmt_sensor(s, a['value'])} is {a['band']} vs the reference band [{did}]",
                        evidence_ids=[did]))
            rules_fired.append("R-B1")
        for s, d in prof.qualitative.items():
            directions.setdefault(s, d)

        # signature-direction rule
        best, best_key = None, (-1.0, -1.0)
        for label in ctx.ref.labels:
            if label == "Normal Operation":
                continue
            ks = dict(key_sensors(label, ctx.ref))
            if not ks:
                continue
            match = sum(1 for s, d in directions.items() if s in ks and ((ks[s] > 0) == (d == "high")))
            clash = sum(1 for s, d in directions.items() if s in ks and ((ks[s] > 0) != (d == "high")))
            fit = centroid_fit(label, prof, ctx.ref) or 0.0
            key = (match - clash, fit)
            if key > best_key:
                best, best_key = label, key

        if violations:
            signal, label = "Sensor readings are physically inconsistent — verify instrumentation first", "Sensor Malfunction"
        elif not directions:
            if "Normal Operation" in ctx.ref.labels:
                signal, label = "Normal Operation", "Normal Operation"
            else:
                signal, label = "No channel outside the reference band", None
        else:
            signal, label = (best or "Unclassified anomaly"), best

        n_dev = len(deviations)
        big = sum(1 for z in deviations if z >= 3)
        if violations:
            severity = "HIGH"
        elif big >= 3:
            severity = "CRITICAL"
        elif n_dev >= 2:
            severity = "HIGH"
        elif n_dev == 1 or prof.qualitative:
            severity = "MEDIUM"
        else:
            severity = "LOW"
        rules_fired.append("R-SIG")
        if label and label not in ("Normal Operation",):
            ks = dict(key_sensors(label, ctx.ref))
            missing = [f"{sensor_name(s)} not reported (part of the {label} signature)"
                       for s in ks if s not in prof.sensors and s not in prof.qualitative]
        narrative = (f"rapid_signal: {signal}. Severity triage {severity} from {n_dev} out-of-band channel(s)"
                     + (f" and {len(violations)} consistency-rule violation(s)" if violations else "")
                     + ". This is a fast rule-based signal for Verification to challenge, not a final decision."
                     + " Time-to-failure is not estimated (no time-series data).")
        return AgentReport(agent=self.key, display_name=self.role, finding=signal, finding_label=label,
                           supporting_evidence=support, missing_information=missing,
                           confidence=0.5 if label else 0.2, narrative=narrative,
                           recommendation=guidance_for(label) if label else guidance_for(None),
                           extras={"rapid_signal": signal, "severity": severity, "rules_fired": rules_fired,
                                   "out_of_band": directions, "consistency_violations": violations})
