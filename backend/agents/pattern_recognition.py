"""
Pattern Recognition Agent — Dr. Aisha Patel

Analyses the retrieved historical cases: which failure labels dominate among
the nearest sensor profiles, how close the best match is, which channels are
anomalous against the reference band, and whether the current case has any
strong historical precedent at all.  Every pattern cites evidence IDs.
"""

from __future__ import annotations

from typing import Dict, List

from agents.base_agent import AgentContext, BaseAgent
from harness.analysis import sensor_assessment
from harness.canonical import fmt_sensor
from harness.schema import AgentReport, DiagnosticState, EvidenceStatement
from harness.statements import band_id, band_low_id, derived_id, sensor_name

PERSONA_NAME = "Dr. Aisha Patel"
PERSONA_EMOJI = "🔍"


class PatternRecognitionAgent(BaseAgent):
    key = "pattern_agent"

    @property
    def role(self) -> str:
        return "Pattern Recognition Agent"

    @property
    def goal(self) -> str:
        return ("Identify recurring failure signatures among retrieved historical cases and anomalous channels, "
                "always citing evidence IDs; say explicitly when no strong historical match exists.")

    def deterministic(self, state: DiagnosticState, ctx: AgentContext, **_) -> AgentReport:
        stats = state.retrieval_stats
        hist: Dict[str, float] = stats.get("historical_support") or {}
        support: List[EvidenceStatement] = []
        contra: List[EvidenceStatement] = []
        missing: List[str] = []
        prof = state.profile

        # anomalous channels vs reference band
        anomalies = []
        if prof and prof.sensors:
            for s, a in sensor_assessment(prof, ctx.ref).items():
                if a["band"] in ("high", "low"):
                    did = band_id(state, ctx.ref, s) if a["band"] == "high" else band_low_id(state, ctx.ref, s)
                    anomalies.append(s)
                    rel = "above" if a["band"] == "high" else "below"
                    support.append(EvidenceStatement(
                        statement=f"Anomaly: {sensor_name(s)} {fmt_sensor(s, a['value'])} is {rel} the reference band [{did}]",
                        evidence_ids=[did]))
        # historical label distribution among nearest cases
        numeric_ev = [e for e in state.evidence if "numeric" in e.method_scores]
        nearest = sorted(numeric_ev, key=lambda e: -e.method_scores.get("numeric", 0))[:5]
        dominant = max(hist, key=hist.get) if hist else None
        no_match = bool(stats.get("no_historical_match"))
        if hist:
            dist_id = derived_id(state, f"hist:{dominant}:r{state.feedback_rounds}",
                                 f"Share of nearest historical cases labelled '{dominant}' (similarity-weighted)",
                                 value=round(hist[dominant], 3))
            ev_ids = [e.evidence_id for e in nearest if e.label == dominant][:4]
            support.append(EvidenceStatement(
                statement=f"{hist[dominant]:.0%} of the nearest historical cases are labelled {dominant} [{dist_id}]"
                          + (f", e.g. {', '.join(ev_ids)}" if ev_ids else ""),
                evidence_ids=[dist_id] + ev_ids))
            others = sorted(((l, v) for l, v in hist.items() if l != dominant), key=lambda t: -t[1])[:2]
            for l, v in others:
                if v >= 0.15:
                    oid = derived_id(state, f"hist:{l}:r{state.feedback_rounds}",
                                     f"Share of nearest historical cases labelled '{l}'", value=round(v, 3))
                    contra.append(EvidenceStatement(
                        statement=f"{v:.0%} of nearest cases point to {l} instead [{oid}]", evidence_ids=[oid]))
        if stats.get("best_numeric_distance") is not None:
            bd = derived_id(state, f"bestdist:r{state.feedback_rounds}", "Robust distance to the closest historical case",
                            value=round(stats["best_numeric_distance"], 3))
            thr = derived_id(state, "nomatch", "Calibrated 'no strong historical match' distance threshold",
                             value=round(stats.get("no_match_threshold") or 0, 3))
            if no_match:
                contra.append(EvidenceStatement(
                    statement=f"No strong historical match found: closest case is farther than the calibrated threshold [{bd}, {thr}]",
                    evidence_ids=[bd, thr]))
        if prof and not prof.sensors:
            missing.append("No numeric readings: pattern matching relied on text similarity"
                           + (" and reported directions" if prof.qualitative else ""))

        if no_match:
            finding, label, conf = "No strong historical match found", None, 0.2
        elif dominant:
            finding, label, conf = dominant, dominant, float(hist[dominant])
        else:
            text_labels = [e.label for e in state.evidence if e.label]
            label = max(set(text_labels), key=text_labels.count) if text_labels else None
            finding, conf = (label or "No recurring pattern"), (0.4 if label else 0.1)

        narrative = []
        if anomalies:
            narrative.append("Anomalous channels: " + ", ".join(sensor_name(s) for s in anomalies) + ".")
        elif prof and prof.sensors:
            narrative.append("No channel lies outside its reference band.")
        if hist:
            top3 = sorted(hist.items(), key=lambda t: -t[1])[:3]
            narrative.append("Nearest-case label distribution: " + ", ".join(f"{l} {v:.0%}" for l, v in top3) + ".")
        if no_match:
            narrative.append("The closest historical case is outside the calibrated similarity threshold, so no historical pattern is asserted.")
        return AgentReport(agent=self.key, display_name=self.role, finding=finding, finding_label=label,
                           evidence_ids=[e.evidence_id for e in nearest], supporting_evidence=support,
                           contradicting_evidence=contra, missing_information=missing, confidence=round(conf, 3),
                           narrative=" ".join(narrative) or "Pattern analysis complete.",
                           recommendation="Compare the asset against the cited historical cases before acting.",
                           extras={"label_distribution": {k: round(v, 3) for k, v in hist.items()},
                                   "anomalous_channels": anomalies, "no_historical_match": no_match,
                                   "nearest_cases": [e.evidence_id for e in nearest]},
                           pass_number=1 + state.feedback_rounds)

    def llm_task(self, state, ctx, report, **_):
        return ("Describe the recurring patterns across the EVIDENCE. Return JSON {\"narrative\": str, "
                "\"supporting_evidence\": [{\"statement\": str, \"evidence_ids\": [..]}]}. "
                "If the draft says there is no strong historical match, keep that conclusion.")
