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

    # ── council: rules-only answers ─────────────────────────────────────────
    def deliberate(self, state: DiagnosticState, ctx: AgentContext, round_no: int, tools=None):
        """Persona: fast, safety-first triage officer with no LLM. He never argues from data he does not
        use: on a challenge he checks the proposed label against his own rule outputs, defers on the label
        only if it fits every out-of-band direction, and never drops a safety signal."""
        rep = state.rapid_triage_output
        if not rep:
            return []
        posted = []
        violations = rep.extras.get("consistency_violations") or []
        directions = rep.extras.get("out_of_band") or {}
        severity = rep.extras.get("severity")
        for m in state.inbox(self.key, round_no):
            if m.kind == "CHALLENGE":
                proposed, mine = m.payload["verified"], m.payload["your_label"]
                if violations:
                    posted.append(state.post(round=round_no, sender=self.key, kind="HOLD", recipients=[m.sender, "all"],
                                             topic=m.topic, in_reply_to=m.message_id,
                                             text=("Safety first: " + "; ".join(f"{v['rule_id']} {v['description']}" for v in violations)
                                                   + ". The readings themselves are suspect, so I keep 'verify instrumentation first'."),
                                             payload={"label": mine, "rules": [v["rule_id"] for v in violations]}))
                    continue
                ks = dict(key_sensors(proposed, ctx.ref))
                match = [s_ for s_, d in directions.items() if s_ in ks and ((ks[s_] > 0) == (d == "high"))]
                clash = [s_ for s_, d in directions.items() if s_ in ks and ((ks[s_] > 0) != (d == "high"))]
                if match and not clash:
                    posted.append(state.post(round=round_no, sender=self.key, kind="CONCESSION", recipients=[m.sender, "all"],
                                             topic=m.topic, in_reply_to=m.message_id,
                                             text=(f"R-SIG check: {proposed} fits every out-of-band direction "
                                                   f"({', '.join(sensor_name(x) for x in match)}) with no clash. I defer on the label "
                                                   f"and keep severity {severity}."),
                                             payload={"new_label": proposed, "old_label": mine, "severity": severity}))
                else:
                    why = (f"its signature clashes with {', '.join(sensor_name(x) for x in clash)}" if clash else
                           "none of my out-of-band channels belongs to its signature" if directions else
                           "my rules see no channel outside its reference band")
                    posted.append(state.post(round=round_no, sender=self.key, kind="HOLD", recipients=[m.sender, "all"],
                                             topic=m.topic, in_reply_to=m.message_id,
                                             text=f"R-SIG check: I cannot confirm {proposed}: {why}. My rapid signal stays {mine}.",
                                             payload={"label": mine, "clash": clash}))
            elif m.kind == "QUESTION" and m.payload.get("need") == "instrumentation":
                posted.append(state.post(round=round_no, sender=self.key, kind="RISK_FLAG",
                                         recipients=["human_review_coordinator", m.sender], topic="instrumentation",
                                         in_reply_to=m.message_id, resolved=None,
                                         text=("Instrumentation is not trustworthy: " + "; ".join(f"{v['rule_id']} observed {v['observed']}" for v in violations)
                                               + ". Verify the sensors before acting on any diagnosis.") if violations
                                         else "No consistency rule fired; the instrumentation looks plausible.",
                                         payload={"rules": [v["rule_id"] for v in violations]}))
                m.resolved = True
        if round_no == 1 and severity in ("HIGH", "CRITICAL"):
            posted.append(state.post(round=round_no, sender=self.key, kind="RISK_FLAG", recipients=["human_review_coordinator"],
                                     topic="severity", text=f"Severity triage {severity}: whatever the label, do not delay the inspection.",
                                     payload={"severity": severity}))
        return posted

