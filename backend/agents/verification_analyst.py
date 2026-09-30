"""
Verification Analyst — Priya Raman  (now with an adversarial step)

Compares the Diagnostic Expert, Pattern Recognition and Rapid Triage outputs
against the *evidence*, not against each other.  For every candidate it asks:

  * What evidence supports it?          * What evidence contradicts it?
  * What evidence is missing?           * Which alternative explains the same evidence?
  * Did any agent make an unsupported factual/numeric claim?
  * Are any retrieved records irrelevant?

Agreement is recorded but never used as a substitute for evidence: three
agents agreeing on a weakly supported label is flagged as
"agreement without evidence".  The verifier also reports evidence
deficiencies that the orchestrator turns into targeted re-retrieval.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from agents.base_agent import AgentContext, BaseAgent
from harness.analysis import critical_sensors
from harness.canonical import SENSOR_SPECS
from harness.claims import ClaimValidator
from harness.schema import AgentReport, DiagnosticState, EvidenceStatement
from harness.statements import build_hypothesis, derived_id

PERSONA_NAME = "Priya Raman"
PERSONA_EMOJI = "✅"

PHASE1 = ("diagnostic_expert_output", "pattern_output", "rapid_triage_output")


class VerificationAnalystAgent(BaseAgent):
    key = "verification"

    @property
    def role(self) -> str:
        return "Verification Analyst"

    @property
    def goal(self) -> str:
        return ("Adversarially verify the first-pass findings against the evidence: support, contradictions, "
                "missing evidence, alternatives, unsupported claims and irrelevant records.")

    def deterministic(self, state: DiagnosticState, ctx: AgentContext, **_) -> AgentReport:
        scored = state.analysis.get("hypotheses", [])
        score_of = {h["label"]: h["score"] for h in scored}
        reports = {k: getattr(state, k) for k in PHASE1 if getattr(state, k) is not None}
        findings = {k: r.finding_label for k, r in reports.items()}

        candidates: List[str] = [h["label"] for h in scored[:3]]
        for lab in findings.values():
            if lab and lab not in candidates and lab in score_of:
                candidates.append(lab)
        if not candidates:
            return AgentReport(agent=self.key, display_name=self.role, finding="Nothing to verify",
                               missing_information=["No hypothesis had evidence"], confidence=0.0,
                               narrative="Verification could not proceed: no evidence-backed hypotheses.",
                               extras={"verified_label": None, "unsupported_agent_claims": 0})

        # 1) unsupported claims made by first-pass agents
        validator = ClaimValidator(state, ctx.known_labels)
        unsupported = 0
        claim_notes: List[str] = []
        for k, r in reports.items():
            texts = [r.narrative] + [s.statement for s in r.supporting_evidence + r.contradicting_evidence]
            for t in texts:
                for c in validator.check_sentence(t, f"verification:{k}"):
                    state.claim_checks.append(c)
                    if c.status == "UNSUPPORTED":
                        unsupported += 1
                        claim_notes.append(f"{r.display_name}: '{c.claim}' has no evidence")
            if r.finding_label and not validator.label_supported(r.finding_label):
                unsupported += 1
                claim_notes.append(f"{r.display_name}: label '{r.finding_label}' not in the knowledge base")

        # 2) adversarial review per candidate
        reviews = []
        for lab in candidates:
            h = build_hypothesis(state, ctx.ref, lab, score_of.get(lab, 0.0))
            agreeing = [k for k, v in findings.items() if v == lab]
            reviews.append({"label": lab, "score": h.score, "support": len(h.supporting),
                            "contradict": len(h.contradicting), "missing": len(h.missing),
                            "agents_agreeing": agreeing, "hypothesis": h})
        reviews.sort(key=lambda r: -r["score"])
        primary = reviews[0]
        alt = reviews[1] if len(reviews) > 1 else None
        # missing evidence = channels needed to confirm a candidate against its closest rival
        prof = state.profile
        for i, rv in enumerate(reviews):
            rival = (alt or {}).get("label") if i == 0 else primary["label"]
            for sname in critical_sensors(rv["label"], rival, ctx.ref):
                if prof and sname not in prof.sensors and sname not in prof.qualitative:
                    msg = (f"{SENSOR_SPECS[sname]['label']} not reported — needed to separate {rv['label']}"
                           + (f" from {rival}" if rival else ""))
                    if not any(m.startswith(SENSOR_SPECS[sname]['label'] + " not reported") for m in rv["hypothesis"].missing):
                        rv["hypothesis"].missing.append(msg)
            rv["missing"] = len(rv["hypothesis"].missing)
        margin = primary["score"] - (alt["score"] if alt else 0.0)

        agree_ratio = len(primary["agents_agreeing"]) / max(len(findings), 1)
        disagreement = len({v for v in findings.values() if v}) > 1
        agreement_without_evidence = (len(set(findings.values())) == 1 and len(findings) >= 2
                                      and primary["score"] < 0.35)

        # 3) irrelevant records
        top_labels = {r["label"] for r in reviews[:3]}
        fused = sorted(e.retrieval_score for e in state.evidence)
        med = fused[len(fused) // 2] if fused else 0.0
        irrelevant = [e.evidence_id for e in state.evidence
                      if e.label not in top_labels and e.retrieval_score < med]

        qa = {
            "what_supports_it": [s.statement for s in primary["hypothesis"].supporting[:5]],
            "what_contradicts_it": [s.statement for s in primary["hypothesis"].contradicting[:5]],
            "what_is_missing": primary["hypothesis"].missing[:5],
            "alternative_explanation": (f"{alt['label']} (score {alt['score']:.2f}) explains part of the same evidence"
                                        if alt else "none with meaningful support"),
            "unsupported_agent_claims": claim_notes[:6],
            "irrelevant_records": irrelevant,
        }
        margin_id = derived_id(state, f"margin:r{state.feedback_rounds}",
                               "Evidence-score margin between leading and runner-up hypothesis", value=round(margin, 3))
        state.contradictions = list(primary["hypothesis"].contradicting)
        state.missing_evidence = list(primary["hypothesis"].missing)

        narrative = [f"Verified hypothesis: {primary['label']} (evidence score {primary['score']:.2f}, margin {margin:.2f} [{margin_id}])."]
        if primary["agents_agreeing"]:
            names = {"diagnostic_expert_output": "Diagnostic Expert", "pattern_output": "Pattern Recognition",
                     "rapid_triage_output": "Rapid Triage"}
            narrative.append("Agreeing first-pass agents: " + ", ".join(names.get(a, a) for a in primary["agents_agreeing"]) + ".")
        if disagreement:
            narrative.append("First-pass agents disagreed; the verdict follows the evidence scores, not a vote.")
        if agreement_without_evidence:
            narrative.append("Agents agree but the evidence is weak — agreement is not treated as confirmation.")
        if unsupported:
            narrative.append(f"{unsupported} unsupported claim(s) from first-pass agents were detected and excluded.")
        if irrelevant:
            narrative.append(f"{len(irrelevant)} retrieved record(s) judged irrelevant to the leading hypotheses.")

        return AgentReport(
            agent=self.key, display_name=self.role, finding=primary["label"], finding_label=primary["label"],
            hypotheses=[r["hypothesis"] for r in reviews], evidence_ids=primary["hypothesis"].evidence_ids,
            supporting_evidence=primary["hypothesis"].supporting[:6],
            contradicting_evidence=primary["hypothesis"].contradicting[:6],
            missing_information=primary["hypothesis"].missing[:6], confidence=round(primary["score"], 3),
            narrative=" ".join(narrative),
            recommendation=("Proceed to uncertainty assessment." if margin >= 0.15
                            else "Leading hypotheses are close — targeted evidence or human review needed."),
            pass_number=1 + state.feedback_rounds,
            extras={"verified_label": primary["label"], "alternative": alt["label"] if alt else None,
                    "margin": round(margin, 4), "agreement_ratio": round(agree_ratio, 3),
                    "agents_disagree": disagreement, "agreement_without_evidence": agreement_without_evidence,
                    "unsupported_agent_claims": unsupported, "adversarial_review": qa,
                    "candidate_reviews": [{k: v for k, v in r.items() if k != "hypothesis"} for r in reviews],
                    "irrelevant_records": irrelevant, "first_pass_findings": findings})

    def llm_task(self, state, ctx, report, **_):
        return ("Act as an adversarial reviewer of the draft verdict. Return JSON {\"narrative\": str, "
                "\"supporting_evidence\": [{\"statement\": str, \"evidence_ids\": [..]}]}. Point out weaknesses; "
                "do not change the verified label unless the evidence IDs clearly contradict it.")
