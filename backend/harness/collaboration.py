"""
Collaborative council — the six agents build the diagnosis together.

The first-pass agents no longer hand independent verdicts to Verification.
After a one-step private draft (kept so agreement still carries information),
the agents work as one council over shared message rounds:

    opening      Final Coordinator puts the candidate hypotheses on the table (QUESTION)
    share        Diagnostic Expert, Pattern Recognition, Rapid Triage → FINDING with a full *position*
                 (a belief over every candidate, from the agent's own method);
                 Verification → EVIDENCE_SHARE with its evidence-balance position
    separate     Ambiguity Detection asks what separates the two leading candidates (QUESTION);
                 Diagnostic Expert answers with a discriminating-channel test, Pattern Recognition with
                 precedent — the Expert folds the test into its own view
    critique     every participant reads the others' positions and CHALLENGEs / COUNTER_ARGUEs any
                 leading label its own method contradicts
    update       every participant reads positions, critiques and answers from its inbox and revises:
                 position ← own view^(1−α) · Π peers^(α/n)   (log-linear pooling, α = persona openness)
                 then answers each critique (RESPONSE retain / qualify, or CONCESSION) and posts a
                 POSITION_UPDATE or HOLD with its new position
    …repeat critique + update until positions converge or COLLAB_MAX_ROUNDS
    joint        Final Coordinator → SYNTHESIS: the joint ranking and the council confidence

What the collaboration changes (by design):
* each first-pass agent's finding becomes its post-discussion position;
* the hypothesis scores Verification checks are blended with the joint ranking
  (weight COLLAB_SCORE_WEIGHT), so the shared discussion shapes the diagnosis;
* the council confidence (agents' belief in the joint label) is blended with the
  evidence confidence and capped by it: final = min(evidence, (1−β)·evidence + β·council).

What it never changes: claim validation, the evidence-confidence factors, the
review-gate criteria, and the rule that numbers come from methods, not words.
With an LLM configured, each message is voiced by ``COUNCIL_LLM_MODEL`` in the
agent's persona; the voiced text is claim-validated and falls back to the
method's own text if it adds any unsupported number, ID or label.

Environment:
    COLLAB_MODE           on (default) | off      off = the previous independent first pass
    COLLAB_MAX_ROUNDS     3
    COLLAB_SCORE_WEIGHT   weight of the joint ranking in the hypothesis scores
    COLLAB_CONF_WEIGHT    β in the confidence blend (0.5)
    COUNCIL_LLM_MODEL     model that voices the agents' messages (default gpt-4.1 for OpenAI)
    COLLAB_LLM_VOICE      on (default) | off
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from harness.claims import ClaimValidator
from harness.schema import DiagnosticState
from utils.logger import setup_logger

logger = setup_logger("harness.collaboration")

FIRST_PASS = ("diagnostic_expert", "pattern_agent", "aggressive_agent")
PARTICIPANTS = ("diagnostic_expert", "pattern_agent", "aggressive_agent", "verification")
OBSERVERS = ("ambiguity", "human_review_coordinator")
REPORT_OF = {"diagnostic_expert": "diagnostic_expert_output", "pattern_agent": "pattern_output",
             "aggressive_agent": "rapid_triage_output", "verification": "verification_output",
             "ambiguity": "ambiguity_output", "human_review_coordinator": "coordinator_output"}
NAMES = {"diagnostic_expert": "Diagnostic Expert", "pattern_agent": "Pattern Recognition",
         "aggressive_agent": "Rapid Triage", "verification": "Verification", "ambiguity": "Ambiguity Detection",
         "human_review_coordinator": "Final Coordinator"}
PERSONAS = {
    "diagnostic_expert": "Dr. Elena Vasquez, Senior Reliability Engineer: hypothesis-driven, weighs competing explanations, open to well-argued evidence",
    "pattern_agent": "Dr. Aisha Patel, Predictive Maintenance Data Scientist: speaks only from historical precedent and similarity statistics",
    "aggressive_agent": "Commander Marcus Chen, Rapid Failure Triage Officer: terse, safety-first, argues from explicit rules and out-of-band channels",
    "verification": "Priya Raman, Reliability Assurance Lead: adversarial, evidence-first, never accepts agreement as proof",
    "ambiguity": "Dr. Sofia Nakamura, Uncertainty Quantification Specialist: names what is still uncertain and asks the question that would settle it",
    "human_review_coordinator": "Director Sarah Mitchell, Plant Operations Director: moderates, summarises decisions plainly for operators",
}
CHALLENGE_KINDS = ("CHALLENGE", "COUNTER_ARGUMENT")
COLLAB_PHASES = ("collaboration", "resync")
EPS = 0.02          # floor so one method can never veto a label outright
CLOSE = 0.15        # same margin as the harness's "conflicting hypotheses"


def collab_enabled() -> bool:
    return os.getenv("COLLAB_MODE", "on").lower() not in ("off", "0", "false", "no")


def _f(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except ValueError:
        return default


def max_rounds() -> int:
    return int(_f("COLLAB_MAX_ROUNDS", 3))


def score_weight() -> float:
    return _f("COLLAB_SCORE_WEIGHT", 0.5)        # tuned on the 246-scenario benchmark (docs/AGENT_TRACE.md)


def conf_weight() -> float:
    return _f("COLLAB_CONF_WEIGHT", 0.5)


# ── positions ────────────────────────────────────────────────────────────────

@dataclass
class View:
    """An agent's own-method assessment of every candidate (before hearing anyone)."""
    support: Dict[str, float]
    why: Dict[str, str] = field(default_factory=dict)
    ids: Dict[str, List[str]] = field(default_factory=dict)
    method: str = ""
    abstain: bool = False
    abstain_reason: str = ""


@dataclass
class Draft:
    kind: str
    recipients: List[str]
    text: str
    topic: str = ""
    evidence_ids: List[str] = field(default_factory=list)
    payload: Dict[str, Any] = field(default_factory=dict)
    in_reply_to: Optional[str] = None
    resolved: Optional[bool] = None
    facts: Dict[str, Any] = field(default_factory=dict)      # what the LLM voice may use
    reply_text: str = ""                                     # the message being answered (for the voice)


def normalise(d: Dict[str, float], labels: List[str]) -> Dict[str, float]:
    vals = {l: max(0.0, float(d.get(l, 0.0))) for l in labels}
    tot = sum(vals.values())
    if tot <= 0:
        return {l: 1.0 / len(labels) for l in labels} if labels else {}
    return {l: v / tot for l, v in vals.items()}


def pool(own: Dict[str, float], peers: List[Dict[str, float]], alpha: float, labels: List[str]) -> Dict[str, float]:
    """Log-linear opinion pooling: own view^(1−α) · Π peer^(α/n).

    A uniform peer tempers the agent's own view without re-ranking it, so abstaining agents are
    excluded from ``peers`` rather than passed in as uniform positions."""
    if not peers or alpha <= 0:
        return normalise(own, labels)
    w = alpha / len(peers)
    logp = {l: (1 - alpha) * math.log(own.get(l, 0.0) + EPS) + sum(w * math.log(p.get(l, 0.0) + EPS) for p in peers)
            for l in labels}
    m = max(logp.values())
    return normalise({l: math.exp(v - m) for l, v in logp.items()}, labels)


def top(p: Dict[str, float]) -> Tuple[Optional[str], float]:
    if not p:
        return None, 0.0
    l = max(p, key=p.get)
    return l, p[l]


def ranked(p: Dict[str, float], n: int = 3) -> List[Tuple[str, float]]:
    return sorted(p.items(), key=lambda t: -t[1])[:n]


def fmt_pos(p: Dict[str, float], n: int = 3) -> str:
    return ", ".join(f"{l} {v:.0%}" for l, v in ranked(p, n))


def compact(p: Dict[str, float], n: int = 5) -> Dict[str, float]:
    return {l: round(v, 3) for l, v in ranked(p, n)}


# ── LLM voice ────────────────────────────────────────────────────────────────

class Voice:
    """Voices a method-generated message in the agent's persona with COUNCIL_LLM_MODEL.

    The method's numbers stay authoritative: the voiced text must keep the
    position label, may cite only IDs and numbers present in the facts, and
    passes the deterministic claim validator; otherwise the method text is kept.
    """

    def __init__(self, state: DiagnosticState, ctx):
        from utils.llm_client import llm_client
        self.client = llm_client
        self.state = state
        self.labels = list(ctx.known_labels)
        self.enabled = bool(ctx.llm_enabled) and os.getenv("COLLAB_LLM_VOICE", "on").lower() not in ("off", "0", "false")
        default = "gpt-4.1" if llm_client.provider == "openai" else llm_client.ollama_model
        self.model = os.getenv("COUNCIL_LLM_MODEL", default) or default

    async def say(self, agent: str, d: Draft) -> Draft:
        d.payload.setdefault("voice", "method")
        if not self.enabled:
            return d
        system = (f"You are {PERSONAS.get(agent, agent)}, one of six agents diagnosing an industrial fault together. "
                  "You are speaking to your fellow agents during the council. Rewrite the DRAFT message in your own "
                  "voice so it reads as a direct, collegial argument (max 3 sentences). Rules: keep the same stance and "
                  "the same leading label; use ONLY numbers, evidence IDs (EV-xxx, D-xxx) and failure-mode labels that "
                  "appear in FACTS or DRAFT; never invent sensor readings; address the agents by role. "
                  'Respond with one JSON object: {"text": "..."}')
        prompt = json.dumps({"message_type": d.kind, "to": [NAMES.get(r, r) for r in d.recipients],
                             "DRAFT": d.text, "FACTS": d.facts, "replying_to": d.reply_text[:600] or None},
                            ensure_ascii=False)
        try:
            data = await self.client.generate_json(prompt, system=system, model=self.model)
        except Exception as exc:  # pragma: no cover - generate_json already swallows errors
            logger.warning("voice failed: %s", exc)
            data = None
        text = str((data or {}).get("text") or "").strip()
        ok, reason = self._valid(text, d)
        if ok:
            d.payload.update({"voice": "llm", "voice_model": self.model, "method_text": d.text})
            d.text = text
        else:
            d.payload.update({"voice": "method", "voice_rejected": reason, "voice_model": self.model})
        return d

    def _valid(self, text: str, d: Draft) -> Tuple[bool, str]:
        if not text:
            return False, "no text returned"
        if len(text) > 900:
            return False, "too long"
        allowed_ids = set(re.findall(r"\b(?:EV|D)-\d{3,}\b", d.text + json.dumps(d.facts))) | set(d.evidence_ids)
        used = set(re.findall(r"\b(?:EV|D)-\d{3,}\b", text))
        if used - allowed_ids:
            return False, f"cited IDs not in the facts: {sorted(used - allowed_ids)}"
        lab = d.payload.get("label") or d.payload.get("new_label")
        if lab and lab.lower() not in text.lower():
            return False, f"dropped the leading label {lab}"
        validator = ClaimValidator(self.state, self.labels)
        source = d.text + " " + json.dumps(d.facts)
        for c in validator.check_sentence(text, "collab:voice"):
            if c.status == "UNSUPPORTED":
                # numbers quoted from the method's own draft/facts (percentages, scores) are allowed
                nums = re.findall(r"\d+(?:\.\d+)?", c.claim)
                if not all(n in source for n in nums):
                    return False, f"unsupported claim '{c.claim}'"
        return True, ""


# ── the engine ───────────────────────────────────────────────────────────────

class Collaboration:
    def __init__(self, agents: Dict[str, Any], state: DiagnosticState, ctx, rec):
        self.agents = agents
        self.state = state
        self.ctx = ctx
        self.rec = rec
        self.voice = Voice(state, ctx)

    # candidates -----------------------------------------------------------------
    def candidates(self) -> List[str]:
        st = self.state
        scored = st.analysis.get("hypotheses", [])
        cands = [h["label"] for h in scored[:4]]
        for k in FIRST_PASS:
            rep = getattr(st, REPORT_OF[k])
            lab = rep.finding_label if rep else None
            if lab and lab not in cands and (lab in {h["label"] for h in scored} or not scored):
                cands.append(lab)
        return cands

    def _restore_base_scores(self) -> None:
        c = self.state.collab
        post, pre = c.get("post_scores"), c.get("pre_scores")
        hyps = self.state.analysis.get("hypotheses", [])
        if post and pre and {h["label"]: h["score"] for h in hyps} == post:
            for h in hyps:
                h["score"] = pre.get(h["label"], h["score"])
            hyps.sort(key=lambda r: -r["score"])
        c["score_delta"] = {}

    # step runner ----------------------------------------------------------------
    async def _step(self, phase: str, round_no: int, step: str, fns: Dict[str, Any]) -> Dict[str, Any]:
        """Run one step for several agents.

        Every agent decides from the board as it stood when the step began
        (``snapshot``), so the order in which agents speak inside a step never
        changes the outcome; drafts are voiced in parallel, then posted in a
        fixed order. Each agent's decision + voicing + posting is one traced execution.
        """
        snapshot = len(self.state.messages)
        execs, drafts, results = {}, {}, {}
        for key, fn in fns.items():
            execs[key] = self.rec.begin_execution(key, stage=phase, kind=f"collab_{step}", state=self.state,
                                                  round_no=round_no)
            try:
                out = fn(snapshot)
                ds, res = (out if isinstance(out, tuple) else (out, None))
                drafts[key], results[key] = ds or [], res
            except Exception as exc:
                logger.exception("collaboration step %s/%s failed", key, step)
                self.rec.end_execution(execs.pop(key), self.state, status="FAILED", error=f"{type(exc).__name__}: {exc}")
                drafts[key], results[key] = [], None
            if key in execs:
                self.rec.suspend_execution(execs[key])

        async def voiced(key):
            self.rec.resume_execution(execs[key])
            out = [await self.voice.say(key, d) for d in drafts[key]]
            self.rec.suspend_execution(execs[key])
            return out
        live = [k for k in fns if k in execs]
        voiced_lists = await asyncio.gather(*(voiced(k) for k in live))
        for key, ds in zip(live, voiced_lists):
            self.rec.resume_execution(execs[key])
            posted = [self.state.post(round=round_no, sender=key, kind=d.kind, recipients=d.recipients, topic=d.topic,
                                      text=d.text, evidence_ids=d.evidence_ids, payload=d.payload,
                                      in_reply_to=d.in_reply_to, resolved=d.resolved, phase=phase) for d in ds]
            self.rec.end_execution(execs[key], self.state,
                                   extra_output={"step": step, "messages_posted": [m.message_id for m in posted],
                                                 **({"position": compact(results[key])} if isinstance(results[key], dict)
                                                    and results[key] and all(isinstance(v, float) for v in results[key].values()) else {})})
        return results

    def _inbox_before(self, agent: str, snapshot: int) -> List[Any]:
        msgs = [m for m in self.state.messages[:snapshot] if m.sender != agent and m.phase in COLLAB_PHASES
                and (agent in m.recipients or "all" in m.recipients)]
        if msgs and self.state._trace is not None:
            self.state._trace.on_inbox(agent, msgs)
        return msgs

    def _peer_positions(self, agent: str, snapshot: int, since_round: int) -> Dict[str, Dict[str, float]]:
        latest: Dict[str, Dict[str, float]] = {}
        for m in self._inbox_before(agent, snapshot):
            if m.round >= since_round and "position" in m.payload and m.sender in PARTICIPANTS:
                if not m.payload.get("abstain"):
                    latest[m.sender] = m.payload["position"]
        return latest

    # main entry -----------------------------------------------------------------
    async def run(self, phase: str = "collaboration", rounds: Optional[int] = None, opening: bool = True) -> Dict[str, Any]:
        st, rec = self.state, self.rec
        st.set_phase(phase)
        self._restore_base_scores()
        if "drafts" not in st.collab:     # the independent first views, kept as a signal
            st.collab["drafts"] = {k: (getattr(st, REPORT_OF[k]).finding_label if getattr(st, REPORT_OF[k]) else None)
                                   for k in FIRST_PASS}
        cands = self.candidates()
        if len(cands) < 2:
            st.collab.update({"skipped": f"only {len(cands)} candidate hypothesis"})
            return st.collab
        rounds = rounds or max_rounds()
        views: Dict[str, View] = {}
        for k in PARTICIPANTS:
            rep = getattr(st, REPORT_OF[k], None)
            if k in FIRST_PASS and (rep is None or rep.extras.get("failed")):
                views[k] = View(support={}, abstain=True, abstain_reason="my own analysis failed, so I have no position")
                continue
            try:
                v = self.agents[k].collab_view(st, self.ctx, cands)
            except Exception as exc:
                logger.exception("collab_view failed for %s", k)
                v = View(support={}, abstain=True, abstain_reason=f"view failed: {exc}")
            v.support = normalise(v.support, cands) if not v.abstain else {l: 1 / len(cands) for l in cands}
            views[k] = v
        pos = {k: dict(v.support) for k, v in views.items()}
        prior = st.collab.get("positions") if phase == "resync" else None
        if prior:   # resume: new evidence moves each agent from where the council left it, not from its draft
            for k in PARTICIPANTS:
                if not views[k].abstain and prior.get(k):
                    pos[k] = pool(views[k].support, [normalise(prior[k], cands)], 0.5, cands)
        start_round = st.round_counter + 1
        history: List[Dict[str, Any]] = []
        rec.event_collab("COLLABORATION_STARTED", {"phase": phase, "candidates": cands, "max_rounds": rounds,
                                                    "views": {k: {"abstain": v.abstain, "position": compact(v.support),
                                                                  "method": v.method} for k, v in views.items()}})
        r = st.next_round()
        rec.event_collab("COLLABORATION_ROUND_STARTED", {"phase": phase, "round": r, "index": 1})

        # opening + share ---------------------------------------------------------------
        if opening:
            scored = {h["label"]: h["score"] for h in st.analysis.get("hypotheses", [])}
            await self._step(phase, r, "open", {"human_review_coordinator": lambda snap: [Draft(
                kind="QUESTION", recipients=list(PARTICIPANTS) + ["ambiguity"], topic="candidates",
                text=("Council open. Candidates on the table: " + ", ".join(f"{c} (evidence score {scored.get(c, 0):.2f})" for c in cands)
                      + ". Each of you: state your position on every candidate from your own method, then we test each other's."),
                payload={"need": "positions", "candidates": cands}, facts={"candidates": cands})]})
        share = {}
        for k in PARTICIPANTS:
            share[k] = (lambda snap, k=k: self._share(k, views[k], pos[k], cands, phase, resumed=bool(prior)))
        await self._step(phase, r, "share", share)

        # separate the two leading candidates (asked by Ambiguity, answered by DE and PR) ---------
        # Ambiguity reads the shared positions from its inbox and measures the split itself
        seen = self._peer_positions("ambiguity", len(st.messages), start_round)
        joint0 = self._joint({k: normalise(seen[k], cands) for k in seen},
                             {k: View(support={}, abstain=k not in seen) for k in PARTICIPANTS}, cands) if seen else {}
        (a, pa), (b, pb) = (ranked(joint0, 2) + [(None, 0.0), (None, 0.0)])[:2]
        if a and b and pa - pb < CLOSE and not st.collab.get("asked", {}).get(f"{a}|{b}"):
            st.collab.setdefault("asked", {})[f"{a}|{b}"] = True
            qres = await self._step(phase, r, "ask", {"ambiguity": lambda snap: [Draft(
                kind="QUESTION", recipients=["diagnostic_expert", "pattern_agent"], topic=f"{a} vs {b}",
                text=(f"The council is split between {a} ({pa:.0%}) and {b} ({pb:.0%}). Which reported channels separate "
                      "them, and what does precedent say?"),
                payload={"need": "separate", "pair": [a, b], "joint": compact(joint0)}, facts={"pair": [a, b]})]})
            ans = {}
            for k in ("diagnostic_expert", "pattern_agent"):
                ans[k] = (lambda snap, k=k: self._answer(k, views[k], snap, phase))
            await self._step(phase, r, "answer", ans)
            pos["diagnostic_expert"] = dict(views["diagnostic_expert"].support) if not views["diagnostic_expert"].abstain \
                else pos["diagnostic_expert"]

        converged = False
        for i in range(1, rounds + 1):
            if i > 1:
                r = st.next_round()
                rec.event_collab("COLLABORATION_ROUND_STARTED", {"phase": phase, "round": r, "index": i})
            # critique
            crit = {k: (lambda snap, k=k: self._critique(k, views[k], pos[k], snap, cands, start_round, phase))
                    for k in PARTICIPANTS if not views[k].abstain}
            await self._step(phase, r, "critique", crit)
            # update (Jacobi: everyone reads the same board)
            before = {k: dict(p) for k, p in pos.items()}
            upd = {k: (lambda snap, k=k: self._update(k, views[k], before[k], snap, cands, start_round, phase))
                   for k in PARTICIPANTS if not views[k].abstain}
            res = await self._step(phase, r, "update", upd)
            for k, newp in res.items():
                if isinstance(newp, dict) and newp:
                    pos[k] = newp
            active = [k for k in PARTICIPANTS if not views[k].abstain]
            tops = {top(pos[k])[0] for k in active}
            delta = max((abs(pos[k][l] - before[k][l]) for k in active for l in cands), default=0.0)
            history.append({"round": r, "index": i, "positions": {k: compact(pos[k]) for k in PARTICIPANTS},
                            "agreed": len(tops) == 1, "max_change": round(delta, 4)})
            rec.event_collab("COLLABORATION_ROUND_COMPLETED", {"phase": phase, "round": r, "index": i,
                                                                "agreed_label": next(iter(tops)) if len(tops) == 1 else None,
                                                                "max_change": round(delta, 4),
                                                                "positions": {k: compact(pos[k], 3) for k in PARTICIPANTS}})
            if len(tops) == 1 and delta < 0.02:
                converged = True
                break

        joint = self._joint(pos, views, cands)
        jl, jp = top(joint)
        active = [k for k in PARTICIPANTS if not views[k].abstain]
        council_conf = round(sum(pos[k][jl] for k in active) / max(1, len(active)), 3)
        changes = self._apply(pos, views, joint, cands)
        dissent = [k for k in active if top(pos[k])[0] != jl]
        r = st.next_round()
        await self._step(phase, r, "joint", {"human_review_coordinator": lambda snap: [self._joint_draft(
            joint, council_conf, pos, views, changes, dissent, converged, len(history), phase, snap)]})
        st.collab.update({
            "enabled": True, "phase": phase, "candidates": cands, "rounds": len(history), "converged": converged,
            "start_round": start_round, "end_round": r,
            "views": {k: {"position": compact(v.support), "method": v.method, "abstain": v.abstain,
                          "abstain_reason": v.abstain_reason} for k, v in views.items()},
            "positions": {k: compact(p) for k, p in pos.items()}, "joint": compact(joint, 6), "joint_label": jl,
            "council_confidence": council_conf, "dissent": dissent, "history": history,
            "position_changes": st.collab.get("position_changes", []) + changes,
        })
        rec.event_collab("JOINT_FINDING_REACHED", {"phase": phase, "label": jl, "joint": compact(joint),
                                                    "council_confidence": council_conf, "converged": converged,
                                                    "dissent": dissent, "rounds": len(history)})
        return st.collab

    # agent actions --------------------------------------------------------------
    def _recipients(self, k: str) -> List[str]:
        return [p for p in PARTICIPANTS if p != k] + list(OBSERVERS)

    def _share(self, k: str, v: View, p: Dict[str, float], cands: List[str], phase: str, resumed: bool = False):
        lab, val = top(p)
        if v.abstain:
            return [Draft(kind="EVIDENCE_SHARE" if k == "verification" else "FINDING", recipients=self._recipients(k),
                          topic="abstain", text=f"I abstain on the label: {v.abstain_reason}.",
                          payload={"abstain": True, "label": None, "method": v.method, "stage": phase},
                          facts={"reason": v.abstain_reason})], None
        ids = list(dict.fromkeys(i for l, _ in ranked(p, 3) for i in v.ids.get(l, [])))[:8]
        why = v.why.get(lab, "")
        if resumed:
            text = (f"With the new evidence, my position moves to {fmt_pos(p)} (from my {v.method} and where the council "
                    f"left me). I lead with {lab}{': ' + why if why else ''}.")
        else:
            text = (f"{'My evidence balance' if k == 'verification' else 'My position'}, from {v.method}: {fmt_pos(p)}. "
                    f"I lead with {lab}{': ' + why if why else ''}.")
        return [Draft(kind="EVIDENCE_SHARE" if k == "verification" else "FINDING", recipients=self._recipients(k),
                      topic=lab, text=text, evidence_ids=ids,
                      payload={"label": lab, "confidence": round(val, 3), "position": compact(p), "method": v.method,
                               "stage": phase, "draft": not resumed, "resumed": resumed},
                      facts={"position": compact(p), "method": v.method, "reason": why, "evidence_ids": ids})], None

    def _answer(self, k: str, v: View, snap: int, phase: str):
        q = next((m for m in reversed(self._inbox_before(k, snap)) if m.kind == "QUESTION" and m.payload.get("need") == "separate"), None)
        if not q or v.abstain:
            return [], None
        a, b = q.payload["pair"]
        res = self.agents[k].collab_answer(self.state, self.ctx, a, b, v)
        if not res:
            return [], None
        text, ids, share, payload = res
        d = Draft(kind="EVIDENCE_SHARE", recipients=[q.sender] + [p for p in PARTICIPANTS if p != k], topic=f"{a} vs {b}",
                  text=text, evidence_ids=ids, in_reply_to=q.message_id,
                  payload={"pair": [a, b], "share": share, **payload}, facts={"share": share, "evidence_ids": ids},
                  reply_text=q.text)
        return [d], None

    def _critique(self, k: str, v: View, p: Dict[str, float], snap: int, cands: List[str], start_round: int, phase: str):
        peers = self._peer_positions(k, snap, start_round)
        mine, pm = top(p)
        done = self.state.collab.setdefault("critiqued", {})
        drafts = []
        for j, pj in peers.items():
            tj, _ = top(pj)
            if not tj or tj == mine or tj not in v.support:
                continue
            key = f"{k}>{j}:{tj}"
            if done.get(key):
                continue
            own_t = v.support.get(tj, 0.0)
            own_m = v.support.get(mine, 0.0)
            if own_t >= 0.6 * own_m:          # my own method does not clearly contradict them
                continue
            done[key] = True
            kind = self.agents[k].COLLAB_CRITIQUE
            reason = v.why.get(tj) or f"my method gives it only {own_t:.0%}"
            ids = list(dict.fromkeys(v.ids.get(tj, []) + v.ids.get(mine, [])))[:8]
            src = next((m for m in reversed(self.state.messages[:snap]) if m.sender == j and "position" in m.payload), None)
            drafts.append(Draft(
                kind=kind, recipients=[j, "verification" if k != "verification" and j != "verification" else "human_review_coordinator"],
                topic=f"{tj} vs {mine}", in_reply_to=src.message_id if src else None, reply_text=src.text if src else "",
                text=(f"{NAMES[j]}, you lead with {tj}, but my {v.method} gives it {own_t:.0%} against {own_m:.0%} for {mine}. "
                      f"{reason[0].upper() + reason[1:]}. What outweighs that?"),
                evidence_ids=ids,
                payload={"your_label": tj, "proposed": mine, "support": {tj: round(own_t, 3), mine: round(own_m, 3)},
                         "method": v.method},
                facts={"their_label": tj, "my_label": mine, "my_support": {tj: round(own_t, 3), mine: round(own_m, 3)},
                       "reason": reason, "evidence_ids": ids}))
        return drafts, None

    def _update(self, k: str, v: View, p: Dict[str, float], snap: int, cands: List[str], start_round: int, phase: str):
        agent = self.agents[k]
        peers = self._peer_positions(k, snap, start_round)
        alpha = agent.collab_openness(self.state)
        newp = pool(v.support, list(peers.values()), alpha, cands)
        old_l, old_v = top(p)
        new_l, new_v = top(newp)
        inbox = self._inbox_before(k, snap)
        crits = [m for m in inbox if m.kind in CHALLENGE_KINDS and m.recipients[:1] == [k]
                 and not self.state.collab.setdefault("answered", {}).get(m.message_id)]
        drafts = []
        for m in crits:
            self.state.collab["answered"][m.message_id] = True
            held, proposed = m.payload.get("your_label"), m.payload.get("proposed")
            before_h, after_h = p.get(held, 0.0), newp.get(held, 0.0)
            ids = v.ids.get(new_l, [])[:4]
            if new_l == proposed:
                kind, stance = "CONCESSION", "concede"
                text = (f"Persuaded, {NAMES[m.sender]}: weighing your {m.payload.get('method', 'evidence')} with the others, my belief in "
                        f"{held} drops from {before_h:.0%} to {after_h:.0%} and I now back {proposed} ({newp[proposed]:.0%}).")
            elif after_h < before_h - 0.02:
                kind, stance = "RESPONSE", "qualify"
                text = (f"Fair point, {NAMES[m.sender]}. I lower {held} from {before_h:.0%} to {after_h:.0%}"
                        + (f" but still lead with it: {v.why.get(held, '')}" if new_l == held else f"; my lead is now {new_l}") + ".")
            else:
                kind, stance = "RESPONSE", "retain"
                text = (f"I hold {held} at {after_h:.0%}: {v.why.get(held) or 'my method still favours it'}. "
                        f"Your argument does not move my {v.method}.")
            drafts.append(Draft(kind=kind, recipients=[m.sender] + [x for x in PARTICIPANTS if x not in (k, m.sender)],
                                topic=m.topic, text=text, evidence_ids=ids, in_reply_to=m.message_id, reply_text=m.text,
                                payload={"label": new_l, "stance": stance, "challenged_label": held,
                                         "challenger_label": proposed, "before": round(before_h, 3), "after": round(after_h, 3),
                                         **({"new_label": proposed, "old_label": held} if kind == "CONCESSION" else {})},
                                facts={"belief_before": round(before_h, 3), "belief_after": round(after_h, 3),
                                       "new_lead": new_l, "reason": v.why.get(held, "")}))
        moved_by = sorted(j for j, pj in peers.items() if top(pj)[0] == new_l and top(v.support)[0] != new_l)
        changed = new_l != old_l or abs(new_v - old_v) >= 0.03
        ids = v.ids.get(new_l, [])[:4]
        if changed:
            text = (f"Updated after reading {', '.join(NAMES[j] for j in sorted(peers)) or 'the council'}: {fmt_pos(newp)}"
                    + (f" (was {old_l} {old_v:.0%})" if new_l != old_l else f" (was {old_v:.0%})")
                    + (f". {', '.join(NAMES[j] for j in moved_by)} moved me; on my own {v.method} I would lead with {top(v.support)[0]}"
                       if moved_by else "") + ".")
            kind = "POSITION_UPDATE"
        else:
            text = f"Holding: {fmt_pos(newp)}. Nothing on the board changes my {v.method}."
            kind = "HOLD"
        drafts.append(Draft(kind=kind, recipients=self._recipients(k), topic=new_l, text=text, evidence_ids=ids,
                            payload={"label": new_l, "old_label": old_l, "confidence": round(new_v, 3),
                                     "position": compact(newp), "old_position": compact(p), "openness": round(alpha, 2),
                                     "read_positions_from": sorted(peers), "moved_by": moved_by, "method": v.method,
                                     **({"new_label": new_l} if new_l != old_l else {})},
                            facts={"position": compact(newp), "previous": compact(p, 3), "moved_by": [NAMES[j] for j in moved_by],
                                   "own_method_lead": top(v.support)[0]}))
        return drafts, newp

    def _joint(self, pos: Dict[str, Dict[str, float]], views: Dict[str, View], cands: List[str]) -> Dict[str, float]:
        active = [k for k in PARTICIPANTS if not views[k].abstain]
        if not active:
            return normalise({}, cands)
        logp = {l: sum(math.log(pos[k].get(l, 0.0) + EPS) for k in active) / len(active) for l in cands}
        m = max(logp.values())
        return normalise({l: math.exp(x - m) for l, x in logp.items()}, cands)

    def _joint_draft(self, joint, conf, pos, views, changes, dissent, converged, n_rounds, phase, snap) -> Draft:
        self._inbox_before("human_review_coordinator", snap)          # the moderator read the whole discussion
        jl, jp = top(joint)
        lines = "; ".join(f"{NAMES[k]} {top(pos[k])[0]} {top(pos[k])[1]:.0%}" if not views[k].abstain else f"{NAMES[k]} abstained"
                          for k in PARTICIPANTS)
        moved = "; ".join(f"{NAMES[c['agent']]} {c['from']} → {c['to']}" for c in changes)
        text = (f"Joint finding after {n_rounds} round(s){' (converged)' if converged else ''}: {jl} ({jp:.0%} of the joint "
                f"ranking; next {', '.join(f'{l} {v:.0%}' for l, v in ranked(joint, 3)[1:])}). Positions: {lines}. "
                f"Council confidence {conf:.2f}"
                + (f". Changed positions: {moved}" if moved else "")
                + (f". Still dissenting: {', '.join(NAMES[k] for k in dissent)}" if dissent else "")
                + ". Verification now checks this ranking against the evidence; the review gate keeps its explicit criteria.")
        return Draft(kind="SYNTHESIS", recipients=["all"], topic="joint finding", text=text,
                     payload={"label": jl, "joint": compact(joint, 6), "council_confidence": conf, "converged": converged,
                              "positions": {k: compact(p, 3) for k, p in pos.items()}, "dissent": dissent,
                              "position_changes": changes, "stage": "joint"},
                     facts={"joint": compact(joint, 4), "council_confidence": conf, "dissent": [NAMES[k] for k in dissent]})

    # apply ---------------------------------------------------------------------
    def _apply(self, pos, views, joint, cands) -> List[Dict[str, Any]]:
        st = self.state
        hyps = st.analysis.get("hypotheses", [])
        pre = {h["label"]: h["score"] for h in hyps}
        w = score_weight()
        in_c = [h for h in hyps if h["label"] in joint]
        mass = sum(h["score"] for h in in_c)
        jm = sum(joint[h["label"]] for h in in_c) or 1.0
        for h in in_c:
            h["components"] = dict(h.get("components", {}), council_joint=round(joint[h["label"]], 3))
            h["score"] = round((1 - w) * h["score"] + w * mass * joint[h["label"]] / jm, 4)
        hyps.sort(key=lambda r: -r["score"])
        st.collab["pre_scores"] = pre
        st.collab["post_scores"] = {h["label"]: h["score"] for h in hyps}
        st.collab["score_delta"] = {l: round(st.collab["post_scores"][l] - pre[l], 4) for l in pre}
        changes = []
        for k in FIRST_PASS:
            rep = getattr(st, REPORT_OF[k])
            if not rep or views[k].abstain:
                continue
            new, val = top(pos[k])
            old = rep.finding_label
            rep.extras["collab_position"] = compact(pos[k])
            rep.extras["own_view"] = compact(views[k].support)
            rep.extras.setdefault("position_history", [{"phase": "draft", "label": old}])
            rep.extras["position_history"].append({"phase": st.collab.get("phase", "collaboration"), "label": new,
                                                   "belief": round(val, 3)})
            rep.confidence = round(val, 3)
            if new != old:
                rep.finding_label = new
                rep.finding = self.agents[k].collab_finding_text(rep, new, old)
                rep.extras["revised_in_collaboration"] = True
                changes.append({"agent": k, "agent_name": NAMES[k], "from": old, "to": new, "belief": round(val, 3)})
                if self.rec:
                    from harness.agent_trace.trace_schema import HypothesisStatus
                    if old:
                        self.rec.hypothesis(k, old, HypothesisStatus.REJECTED, reason="replaced by the collaborative position")
                    self.rec.hypothesis(k, new, HypothesisStatus.MODIFIED, score=round(val, 3),
                                        reason="adopted through the collaboration")
        return changes


# ── re-executed agents keep their place in the council ──────────────────────

def reapply_position(agents: Dict[str, Any], state: DiagnosticState, ctx, key: str, rec=None) -> Optional[Dict[str, Any]]:
    """After a first-pass agent is re-executed (targeted retrieval, council re-run), its fresh report holds
    only its own-method view. Pool that view with the peers' latest council positions (same rule and
    openness as in the rounds) so the agent does not silently drop back to its independent draft."""
    c = state.collab
    positions = c.get("positions") or {}
    rep = getattr(state, REPORT_OF[key], None)
    if key not in FIRST_PASS or not positions or not rep or rep.extras.get("failed"):
        return None
    cands = [l for l in (c.get("candidates") or []) if l]
    if len(cands) < 2:
        return None
    try:
        view = agents[key].collab_view(state, ctx, cands)
    except Exception:
        return None
    if view.abstain:
        return None
    own = normalise(view.support, cands)
    peers = [normalise(p, cands) for k, p in positions.items() if k != key and p and not (c.get("views", {}).get(k, {}).get("abstain"))]
    newp = pool(own, peers, agents[key].collab_openness(state), cands)
    new, val = top(newp)
    old = rep.finding_label
    rep.extras.update({"collab_position": compact(newp), "own_view": compact(own), "reapplied_after_rerun": True})
    rep.extras.setdefault("position_history", [{"phase": "draft", "label": c.get("drafts", {}).get(key)}])
    rep.extras["position_history"].append({"phase": "rerun", "label": new, "belief": round(val, 3)})
    rep.confidence = round(val, 3)
    positions[key] = compact(newp)
    if new != old:
        rep.finding_label = new
        rep.finding = agents[key].collab_finding_text(rep, new, old)
        if rec:
            from harness.agent_trace.trace_schema import HypothesisStatus
            rec.hypothesis(key, new, HypothesisStatus.MODIFIED, score=round(val, 3),
                           reason=f"re-execution pooled with the council positions (own view led with {old})")
    return {"agent": key, "from": old, "to": new, "belief": round(val, 3)}


# ── evidence scores without the council's adjustment ────────────────────────

def evidence_scores(state: DiagnosticState) -> Dict[str, float]:
    """Current hypothesis scores minus the collaboration's adjustment.

    The joint ranking may reorder candidates, but evidence thresholds (insufficient
    evidence, evidence confidence, the gate's margin) must read the evidence itself,
    so agreement can never make weak evidence look sufficient — or strong evidence weak.
    """
    delta = state.collab.get("score_delta") or {}
    return {h["label"]: max(0.0, h["score"] - delta.get(h["label"], 0.0)) for h in state.analysis.get("hypotheses", [])}


# ── disputes ─────────────────────────────────────────────────────────────────

def close_disputes(state: DiagnosticState) -> None:
    """Settle collaboration critiques against where both agents finally stand.

    RESOLVED when the two agents end on the same label (one persuaded the other) or the
    challenged agent conceded; UNRESOLVED when they still back different labels.
    """
    ver = state.verification_output
    final = {k: (getattr(state, REPORT_OF[k]).finding_label if getattr(state, REPORT_OF[k], None) else None)
             for k in FIRST_PASS}
    final["verification"] = ver.finding_label if ver else None
    for m in state.messages:
        if m.phase not in COLLAB_PHASES or m.kind not in CHALLENGE_KINDS:
            continue
        target = m.recipients[0] if m.recipients else None
        a, b = final.get(target), final.get(m.sender)
        conceded = any(r.in_reply_to == m.message_id and r.kind == "CONCESSION" for r in state.messages)
        if conceded:
            m.resolved, outcome = True, f"{NAMES.get(target, target)} conceded and now backs {m.payload.get('proposed')}"
        elif a and a == b:
            m.resolved, outcome = True, f"{NAMES.get(target, target)} and {NAMES.get(m.sender, m.sender)} converged on {a}"
        else:
            m.resolved, outcome = False, (f"{NAMES.get(target, target)} still backs {a or 'no label'}; "
                                          f"{NAMES.get(m.sender, m.sender)} backs {b or 'no label'}")
        m.payload["outcome"] = outcome
    for m in state.messages:
        if m.phase in COLLAB_PHASES and m.kind == "QUESTION" and m.resolved is None:
            m.resolved = any(r.in_reply_to == m.message_id for r in state.messages) or m.payload.get("need") == "positions"


def summary(state: DiagnosticState) -> Dict[str, Any]:
    c = state.collab
    msgs = [m for m in state.messages if m.phase in COLLAB_PHASES]
    ch = [m for m in msgs if m.kind in CHALLENGE_KINDS]
    return {"enabled": collab_enabled(), "messages": len(msgs), "rounds": c.get("rounds", 0),
            "converged": c.get("converged"), "joint_label": c.get("joint_label"), "joint": c.get("joint"),
            "council_confidence": c.get("council_confidence"), "positions": c.get("positions"),
            "views": c.get("views"), "position_changes": c.get("position_changes", []), "dissent": c.get("dissent", []),
            "challenges": len(ch), "resolved": sum(1 for m in ch if m.resolved),
            "unresolved": sum(1 for m in ch if m.resolved is False),
            "llm_voiced": sum(1 for m in state.messages if m.payload.get("voice") == "llm"),
            "skipped": c.get("skipped")}
