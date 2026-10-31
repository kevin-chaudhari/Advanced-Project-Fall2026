"""
Diagnostic Expert Agent — Dr. Elena Vasquez

Generates multiple failure hypotheses, cites the evidence for and against each,
lists missing evidence and deliberately keeps runner-up hypotheses alive
instead of accepting the first idea.

Pass 1 : hypotheses from the evidence engine (kNN vote + signature fit).
Pass 2 : (only when the orchestrator detects conflicting hypotheses) re-scores
         the two leading hypotheses on the sensors that actually discriminate
         between them, using targeted evidence retrieved for that conflict.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List

from agents.base_agent import AgentContext, BaseAgent
from harness.analysis import discriminating_sensors
from harness.canonical import fmt_sensor
from harness.claims import ClaimValidator
from harness.schema import AgentReport, DiagnosticState, EvidenceStatement
from harness.statements import build_hypothesis, sensor_name, signature_median_id

PERSONA_NAME = "Dr. Elena Vasquez"
PERSONA_EMOJI = "🧠"


class DiagnosticExpertAgent(BaseAgent):
    key = "diagnostic_expert"

    @property
    def role(self) -> str:
        return "Diagnostic Expert"

    @property
    def goal(self) -> str:
        return ("Generate several competing failure hypotheses, cite supporting and contradicting evidence "
                "for each, and name the evidence that is missing.")

    def deterministic(self, state: DiagnosticState, ctx: AgentContext, conflict: Dict | None = None, **_) -> AgentReport:
        scored = list(state.analysis.get("hypotheses", []))
        if not scored:
            return AgentReport(agent=self.key, display_name=self.role, finding="No hypothesis could be formed",
                               missing_information=["No usable evidence was retrieved"], confidence=0.0,
                               narrative="No evidence was available to form hypotheses.")
        pass_no = 1
        notes: List[str] = []
        if conflict and len(scored) >= 2:
            scored, notes = self._resolve_conflict(state, ctx, scored, conflict)
            pass_no = 2
        top = scored[:3] if len(scored) >= 3 else scored
        hyps = [build_hypothesis(state, ctx.ref, h["label"], h["score"]) for h in top]
        lead = hyps[0]
        missing = [m for h in hyps[:2] for m in h.missing]
        runner = hyps[1] if len(hyps) > 1 else None
        narrative = [f"Evaluated {len(hyps)} competing hypotheses."]
        narrative.append(f"Leading hypothesis: {lead.label} (evidence score {lead.score:.2f}; "
                         f"{len(lead.supporting)} supporting, {len(lead.contradicting)} contradicting items).")
        if runner:
            narrative.append(f"{runner.label} is kept as an alternative (score {runner.score:.2f}) rather than discarded.")
        narrative.extend(notes)
        if missing:
            narrative.append(f"Missing evidence: {len(missing)} signature channel(s) not reported.")
        return AgentReport(
            agent=self.key, display_name=self.role, finding=lead.label, finding_label=lead.label,
            hypotheses=hyps, evidence_ids=lead.evidence_ids,
            supporting_evidence=lead.supporting[:6], contradicting_evidence=lead.contradicting[:6],
            missing_information=missing[:6], confidence=lead.score,
            narrative=" ".join(narrative), recommendation="Validate the leading hypothesis against the channels listed as missing or contradicting.",
            pass_number=pass_no, extras={"scores": [{"label": h["label"], "score": h["score"]} for h in scored[:5]]})

    def _resolve_conflict(self, state: DiagnosticState, ctx: AgentContext, scored: List[Dict], conflict: Dict):
        a, b = scored[0]["label"], scored[1]["label"]
        disc = discriminating_sensors(a, b, ctx.ref, top=3)
        prof = state.profile
        notes, fa, fb = [], 0.0, 0.0
        for d in disc:
            s = d["sensor"]
            if s not in prof.sensors:
                notes.append(f"Discriminating channel {sensor_name(s)} is not reported, so {a} vs {b} cannot be separated on it.")
                continue
            v = prof.sensors[s]
            sa, sb = ctx.ref.signatures[a], ctx.ref.signatures[b]
            za = abs(v - sa["median"][s]) / sa["scale"][s]
            zb = abs(v - sb["median"][s]) / sb["scale"][s]
            fa += math.exp(-0.5 * za * za)
            fb += math.exp(-0.5 * zb * zb)
            ida = signature_median_id(state, a, s, sa["median"][s])
            idb = signature_median_id(state, b, s, sb["median"][s])
            closer = a if za < zb else b
            notes.append(f"Discriminating channel {sensor_name(s)}: reported {fmt_sensor(s, v)} is closer to {closer} "
                         f"({a} median {fmt_sensor(s, sa['median'][s])} [{ida}], {b} median {fmt_sensor(s, sb['median'][s])} [{idb}]).")
        targeted = conflict.get("evidence_ids", [])
        if targeted:
            notes.append(f"Targeted conflict evidence reviewed: {', '.join(targeted[:6])}.")
        if fa + fb > 0:
            pair_total = scored[0]["score"] + scored[1]["score"]
            share_a = fa / (fa + fb)
            new_a = 0.5 * scored[0]["score"] + 0.5 * pair_total * share_a
            new_b = 0.5 * scored[1]["score"] + 0.5 * pair_total * (1 - share_a)
            rescored = [dict(scored[0], score=round(new_a, 4)), dict(scored[1], score=round(new_b, 4))] + scored[2:]
            rescored.sort(key=lambda r: -r["score"])
            state.analysis["hypotheses"] = rescored
            state.analysis["conflict_resolution"] = {"pair": [a, b], "discriminating": disc,
                                                     "pairwise_share": {a: round(share_a, 3), b: round(1 - share_a, 3)}}
            return rescored, notes
        return scored, notes

    # ── council: discriminating-channel test of a contested pair ────────────
    def pair_signature_test(self, state: DiagnosticState, ctx: AgentContext, a: str, b: str) -> Dict[str, Any]:
        """Which hypothesis do the channels that best separate a from b favour? (no state mutation)"""
        disc = discriminating_sensors(a, b, ctx.ref, top=3)
        prof = state.profile
        fa = fb = 0.0
        used, unreported, ids, notes = [], [], [], []
        for d in disc:
            s_ = d["sensor"]
            if s_ not in prof.sensors:
                unreported.append(s_)
                continue
            v = prof.sensors[s_]
            sa, sb = ctx.ref.signatures[a], ctx.ref.signatures[b]
            za = abs(v - sa["median"][s_]) / sa["scale"][s_]
            zb = abs(v - sb["median"][s_]) / sb["scale"][s_]
            fa += math.exp(-0.5 * za * za)
            fb += math.exp(-0.5 * zb * zb)
            ida, idb = signature_median_id(state, a, s_, sa["median"][s_]), signature_median_id(state, b, s_, sb["median"][s_])
            ids += [ida, idb]
            used.append(s_)
            notes.append(f"{sensor_name(s_)} {fmt_sensor(s_, v)} is closer to {a if za < zb else b} "
                         f"({a} median [{ida}], {b} median [{idb}])")
        share = {a: round(fa / (fa + fb), 3), b: round(fb / (fa + fb), 3)} if fa + fb > 0 else None
        return {"share": share, "used": used, "unreported": unreported, "ids": ids, "notes": notes}

    def deliberate(self, state: DiagnosticState, ctx: AgentContext, round_no: int, tools=None):
        """Persona: hypothesis-driven investigator. Answers with a structured elimination test on the
        channels that separate the contested hypotheses, and asks for evidence when a rival is thin."""
        posted = []
        prior = state.analysis.get("conflict_resolution") or {}
        for m in state.inbox(self.key, round_no):
            if m.kind == "QUESTION" and m.payload.get("need") == "separate":
                a, b = m.payload["pair"]
            elif m.kind == "CHALLENGE":
                a, b = m.payload["verified"], m.payload["your_label"]
            else:
                continue
            if a not in ctx.ref.signatures or b not in ctx.ref.signatures:
                continue
            t = self.pair_signature_test(state, ctx, a, b)
            already = sorted(prior.get("pair", [])) == sorted([a, b])
            if t["share"]:
                fav = a if t["share"][a] >= t["share"][b] else b
                text = (f"Discriminating-channel test, {a} vs {b}: " + "; ".join(t["notes"]) +
                        f". Signature evidence favours {fav} ({t['share'][fav]:.0%} of the pairwise fit)."
                        + (" This was already applied in the feedback loop, so it is not counted twice." if already else ""))
            else:
                text = f"None of the channels that separate {a} from {b} were reported, so I cannot separate them."
            posted.append(state.post(round=round_no, sender=self.key, kind="EVIDENCE_SHARE",
                                     recipients=[m.sender, "all"], topic=f"{a} vs {b}", in_reply_to=m.message_id,
                                     text=text, evidence_ids=t["ids"],
                                     payload={"pair": [a, b], "signature_share": t["share"], "already_applied": already,
                                              "channels": t["used"]}))
            if t["unreported"]:
                names = [sensor_name(x) for x in t["unreported"]]
                posted.append(state.post(round=round_no, sender=self.key, kind="HUMAN_INPUT_REQUEST",
                                         recipients=["human_review_coordinator"], topic=f"{a} vs {b}",
                                         text=f"Measuring {', '.join(names)} would separate {a} from {b}.",
                                         payload={"channels": t["unreported"], "pair": [a, b]}))
            n_b = sum(1 for e in state.evidence if e.label == b)
            if tools and n_b < 2 and not any(x.kind == "EVIDENCE_REQUEST" and x.sender == self.key
                                             and x.payload.get("label") == b for x in state.messages):
                added = tools.request_label_evidence(b)
                posted.append(state.post(round=round_no, sender=self.key, kind="EVIDENCE_REQUEST", recipients=["harness"],
                                         topic=b, text=(f"Only {n_b} record(s) for {b} in the bundle; requested cases labelled {b}. "
                                                        + (f"Retrieval added {', '.join(added)}." if added else "No further cases found.")),
                                         evidence_ids=added, payload={"label": b, "added": added}, resolved=bool(added)))
        return posted

    # ── collaborative council ───────────────────────────────────────────────
    COLLAB_OPENNESS = 0.5          # the integrator: listens most, but keeps half its own evidence view

    def collab_view(self, state: DiagnosticState, ctx: AgentContext, candidates: List[str]):
        from harness.collaboration import View
        scores = {h["label"]: h["score"] for h in state.analysis.get("hypotheses", [])}
        rep = state.diagnostic_expert_output
        mine = {h.label: h for h in (rep.hypotheses if rep else [])}
        why, ids = {}, {}
        for c in candidates:
            h = mine.get(c)
            parts = [f"evidence score {scores.get(c, 0.0):.2f}"]
            if h:
                parts.append(f"{len(h.supporting)} supporting / {len(h.contradicting)} contradicting statement(s)")
                if h.contradicting:
                    parts.append(h.contradicting[0].statement.split(" [")[0].lower())
            why[c] = "; ".join(parts)
            ids[c] = list(dict.fromkeys((h.evidence_ids[:3] if h else [])
                                        + [i for st in ((h.supporting[:2] + h.contradicting[:1]) if h else []) for i in st.evidence_ids]))
        if not any(scores.get(c, 0.0) for c in candidates):
            return View(support={}, abstain=True, abstain_reason="no candidate has an evidence score")
        return View(support={c: scores.get(c, 0.0) for c in candidates}, why=why, ids=ids,
                    method="hypothesis evidence scores (signature fit + case vote)")

    def collab_answer(self, state: DiagnosticState, ctx: AgentContext, a: str, b: str, view):
        if a not in ctx.ref.signatures or b not in ctx.ref.signatures:
            return None
        t = self.pair_signature_test(state, ctx, a, b)
        if not t["share"]:
            return (f"None of the channels that separate {a} from {b} were reported, so my signatures cannot split them.",
                    [], None, {"channels": [], "unreported": t["unreported"]})
        tot = view.support.get(a, 0.0) + view.support.get(b, 0.0)
        before = {a: view.support.get(a, 0.0), b: view.support.get(b, 0.0)}
        view.support[a] = 0.5 * before[a] + 0.5 * tot * t["share"][a]      # fold the test into my own view
        view.support[b] = 0.5 * before[b] + 0.5 * tot * t["share"][b]
        fav = a if t["share"][a] >= t["share"][b] else b
        text = (f"Discriminating-channel test, {a} vs {b}: " + "; ".join(t["notes"])
                + f". The signatures favour {fav} ({t['share'][fav]:.0%} of the pairwise fit); I fold this into my position.")
        return text, t["ids"], t["share"], {"channels": t["used"], "unreported": t["unreported"], "favours": fav,
                                            "view_before": {k: round(v, 3) for k, v in before.items()},
                                            "view_after": {a: round(view.support[a], 3), b: round(view.support[b], 3)}}

    def collab_finding_text(self, report, new, old):
        return new

    def llm_task(self, state, ctx, report, **_):
        return ("Review the draft. Return JSON {\"hypotheses\": [{\"label\": str, \"supporting\": [{\"statement\": str, "
                "\"evidence_ids\": [..]}], \"contradicting\": [...], \"missing\": [str]}], \"narrative\": str}. "
                "Keep at least two hypotheses. Do not invent readings.")

    def merge_llm(self, state, ctx, report, data: Dict[str, Any]) -> AgentReport:
        report = super().merge_llm(state, ctx, report, data)
        validator = ClaimValidator(state, ctx.known_labels)
        by_label = {h.label: h for h in report.hypotheses}
        for h in data.get("hypotheses") or []:
            if not isinstance(h, dict):
                continue
            lab = str(h.get("label", ""))
            if lab not in by_label:
                if not validator.label_supported(lab):
                    report.claims_removed += 1
                continue
            for kind in ("supporting", "contradicting"):
                for st in self._statements(h.get(kind), state):
                    chk = validator.check_sentence(st.statement, f"{self.key}:llm")
                    state.claim_checks.extend(chk)
                    if st.evidence_ids and not any(c.status == "UNSUPPORTED" for c in chk):
                        getattr(by_label[lab], kind).append(st)
                    else:
                        report.claims_removed += 1
        return report
