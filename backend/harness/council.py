"""
Agent council — structured agent-to-agent communication for hard cases.

The three first-pass agents still work independently (that independence is
what makes their agreement meaningful).  When the provisional assessment is
weak — low confidence, a close runner-up, or disagreeing agents — the
orchestrator convenes a council in which all six agents talk to each other
through typed messages on a shared board (``DiagnosticState.messages``):

    Ambiguity Detection   opens the agenda: turns each uncertainty flag into a question
                          for the agent that owns it, or a human-input request
    Verification Analyst  challenges agents whose finding is not the best-supported one
    Diagnostic Expert     answers with a discriminating-channel test of the contested pair
    Pattern Recognition   answers with a focused precedent check on those same channels
    Rapid Triage          concedes or holds according to its rules (safety first)
    Human Review Coord.   closes with a synthesis and the open items that need a person

Each agent keeps its persona and its own method; the council only routes
messages and acts on *structured* payloads (pairwise shares, evidence
requests).  Confidence is recomputed with the unchanged factor formula, so it
can only move when the discussion produced evidence: agents agreeing with each
other is never, by itself, a reason for higher confidence.  If the evidence
points the other way, confidence goes down, and the transcript says so.

Environment:
    COUNCIL_MODE        auto (default) | always | off
    COUNCIL_MAX_ROUNDS  default 2
"""

from __future__ import annotations

import copy
import os
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from harness.schema import AgentMessage, DiagnosticState
from harness.statements import derived_id

COUNCIL_MODE = os.getenv("COUNCIL_MODE", "auto").lower()
COUNCIL_MAX_ROUNDS = int(os.getenv("COUNCIL_MAX_ROUNDS", "2"))
COUNCIL_RESCORE = os.getenv("COUNCIL_RESCORE", "1") == "1"          # ablation switch
COUNCIL_CONCESSIONS = os.getenv("COUNCIL_CONCESSIONS", "1") == "1"  # ablation switch
COUNCIL_RESCORE_RULE = os.getenv("COUNCIL_RESCORE_RULE", "agree")
COUNCIL_RESCORE_WEIGHT = float(os.getenv("COUNCIL_RESCORE_WEIGHT", "0.25"))
CONVENE_CONFIDENCE = 0.65      # same threshold as review-gate criterion G1
CONVENE_MARGIN = 0.15          # same threshold as review-gate criterion G2

FIRST_PASS = ("diagnostic_expert", "pattern_agent", "aggressive_agent")
REPORT_SLOT = {"diagnostic_expert": "diagnostic_expert_output", "pattern_agent": "pattern_output",
               "aggressive_agent": "rapid_triage_output", "verification": "verification_output",
               "ambiguity": "ambiguity_output", "human_review_coordinator": "coordinator_output"}


def pair_key(a: str, b: str) -> str:
    return " vs ".join(sorted([a, b]))


@dataclass
class CouncilTools:
    """Harness services the agents may call while deliberating (read-mostly)."""
    focused_precedent: Callable[..., Optional[Dict[str, Any]]]
    request_label_evidence: Callable[[str], List[str]]
    reported_channels: List[str] = field(default_factory=list)


def should_convene(state: DiagnosticState, has_numeric: bool) -> Tuple[bool, List[str]]:
    if COUNCIL_MODE == "off":
        return False, ["council disabled (COUNCIL_MODE=off)"]
    prof = state.profile
    if not has_numeric or not prof or (not prof.sensors and not prof.qualitative):
        return False, ["no sensor readings to deliberate on"]
    ver = state.verification_output
    conf = state.confidence.confidence if state.confidence else 0.0
    reasons = []
    if conf < CONVENE_CONFIDENCE:
        reasons.append(f"provisional confidence {conf:.2f} < {CONVENE_CONFIDENCE:.2f}")
    if ver and float(ver.extras.get("margin", 1.0)) < CONVENE_MARGIN:
        reasons.append(f"runner-up within {float(ver.extras.get('margin', 0)):.2f} of the leading hypothesis")
    if ver and ver.extras.get("agents_disagree"):
        reasons.append("first-pass agents disagree")
    if COUNCIL_MODE == "always" and not reasons:
        reasons.append("COUNCIL_MODE=always")
    return bool(reasons), reasons


def contested_pair(state: DiagnosticState) -> Optional[Tuple[str, str]]:
    ver = state.verification_output
    if ver and ver.extras.get("verified_label") and ver.extras.get("alternative"):
        return ver.extras["verified_label"], ver.extras["alternative"]
    hyps = state.analysis.get("hypotheses", [])
    if len(hyps) >= 2:
        return hyps[0]["label"], hyps[1]["label"]
    return None


def apply_pair_resolution(state: DiagnosticState, a: str, b: str, shares: Dict[str, Dict[str, float]],
                          round_no: int) -> Optional[Dict[str, Any]]:
    """Re-weight the contested pair using the shares the agents shared.

    Same rule the Diagnostic Expert already uses in the feedback loop: half the
    old score, half the pair total split by the new evidence.  Applied at most
    once per pair, and a share that the feedback loop already applied (the
    signature share) is not counted twice.
    """
    if not COUNCIL_RESCORE:
        return None
    usable = {k: v for k, v in shares.items() if v and (a in v and b in v) and (v[a] + v[b]) > 0}
    if not usable:
        return None
    done = state.council.setdefault("applied_pairs", [])
    if pair_key(a, b) in done:
        return None
    if COUNCIL_RESCORE_RULE == "agree":
        if len(usable) < 2:
            return None
        fav = {k: (v[a] / (v[a] + v[b])) >= 0.5 for k, v in usable.items()}
        if len(set(fav.values())) != 1:
            return None
    joint_a = sum(v[a] / (v[a] + v[b]) for v in usable.values()) / len(usable)
    hyps = state.analysis.get("hypotheses", [])
    by = {h["label"]: h for h in hyps}
    if a not in by or b not in by:
        return None
    total = by[a]["score"] + by[b]["score"]
    old_a, old_b = by[a]["score"], by[b]["score"]
    w = COUNCIL_RESCORE_WEIGHT
    by[a] = dict(by[a], score=round((1 - w) * old_a + w * total * joint_a, 4))
    by[b] = dict(by[b], score=round((1 - w) * old_b + w * total * (1 - joint_a), 4))
    rescored = sorted([by.get(h["label"], h) for h in hyps], key=lambda r: -r["score"])
    state.analysis["hypotheses"] = rescored
    done.append(pair_key(a, b))
    did = derived_id(state, f"council:{pair_key(a, b)}:r{round_no}",
                     f"Council joint share for {a} in {a} vs {b} (mean of {', '.join(sorted(usable))})",
                     value=round(joint_a, 3))
    res = {"pair": [a, b], "joint_share": {a: round(joint_a, 3), b: round(1 - joint_a, 3)},
           "sources": sorted(usable), "before": {a: old_a, b: old_b},
           "after": {a: by[a]["score"], b: by[b]["score"]}, "derived_id": did, "round": round_no}
    state.council.setdefault("resolutions", []).append(res)
    return res


def mark_resolved(state: DiagnosticState, round_no: int) -> None:
    """Close the loop on this round's questions and challenges from the outcome."""
    ver = state.verification_output
    margin = float(ver.extras.get("margin", 0.0)) if ver else 0.0
    verified = ver.extras.get("verified_label") if ver else None
    for m in state.messages:
        if m.round != round_no or m.resolved is not None:
            continue
        if m.kind == "QUESTION" and m.payload.get("need") == "separate":
            m.resolved = margin >= CONVENE_MARGIN
        elif m.kind == "CHALLENGE":
            target = m.recipients[0] if m.recipients else None
            rep = getattr(state, REPORT_SLOT.get(target, ""), None) if target else None
            m.resolved = bool(rep and rep.finding_label == verified)
        elif m.kind in ("HUMAN_INPUT_REQUEST",):
            m.resolved = False
        elif m.kind in ("QUESTION", "EVIDENCE_REQUEST"):
            replies = [r for r in state.messages if r.in_reply_to == m.message_id]
            m.resolved = bool(replies)


def summary(state: DiagnosticState) -> Dict[str, Any]:
    msgs = [m for m in state.messages if m.phase == "council"]  # escalation council only
    open_items = [m for m in msgs if m.kind in ("QUESTION", "CHALLENGE", "HUMAN_INPUT_REQUEST", "EVIDENCE_REQUEST")]
    return {
        "convened": bool(state.council.get("convened")),
        "reasons": state.council.get("reasons", []),
        "rounds": state.council.get("rounds", 0),
        "messages": len(msgs),
        "resolved": sum(1 for m in open_items if m.resolved),
        "unresolved": sum(1 for m in open_items if m.resolved is False),
        "confidence_before": state.council.get("confidence_before"),
        "confidence_after": state.council.get("confidence_after"),
        "verified_before": state.council.get("verified_before"),
        "verified_after": state.council.get("verified_after"),
        "position_changes": state.council.get("position_changes", []),
        "resolutions": state.council.get("resolutions", []),
        "human_inputs": state.council.get("human_inputs", []),
        "first_pass_findings": state.council.get("first_pass_findings", {}),
        "mode": COUNCIL_MODE,
        "collaboration_messages": sum(1 for m in state.messages if m.phase in ("collaboration", "resync")),
        "total_messages": len(state.messages),
    }


def profile_with_channels(profile, channels: List[str]):
    """A copy of the query profile restricted to the given reported channels."""
    p = copy.deepcopy(profile)
    p.sensors = {k: v for k, v in profile.sensors.items() if k in channels}
    p.qualitative = {k: v for k, v in profile.qualitative.items() if k in channels}
    return p
