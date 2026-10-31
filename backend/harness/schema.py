"""
Structured shared state for one diagnostic run.

Every agent reads from and writes to a single ``DiagnosticState``.  Agents
exchange *structured* objects (hypotheses, evidence IDs, findings) instead of
free-form strings, which is what allows the orchestrator to reason over their
outputs, the verifier to check them, and the claim validator to trace every
statement back to evidence.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, PrivateAttr

SourceType = Literal["real", "synthetic"]
ClaimStatus = Literal["SUPPORTED", "DERIVED", "UNSUPPORTED"]
ReviewDecision = Literal["AUTO_RESOLVE", "REQUIRES_HUMAN_REVIEW"]


class QueryProfile(BaseModel):
    """Output of deterministic query preparation."""
    raw_query: str
    normalized_query: str
    sensors: Dict[str, float] = Field(default_factory=dict)          # explicit numeric readings
    missing_sensors: List[str] = Field(default_factory=list)         # explicitly reported unavailable
    qualitative: Dict[str, str] = Field(default_factory=dict)        # sensor -> "high" | "low"
    equipment_type: Optional[str] = None
    equipment_phrase: Optional[str] = None
    mentioned_failure_modes: List[str] = Field(default_factory=list)
    intent: str = "diagnose"
    notes: List[str] = Field(default_factory=list)


class Evidence(BaseModel):
    """A retrieved record with a stable per-run ID (EV-001 …)."""
    evidence_id: str
    dataset: str
    record_id: str
    source_type: SourceType
    retrieval_score: float
    retrieval_method: str
    method_scores: Dict[str, float] = Field(default_factory=dict)
    label: Optional[str] = None
    content: Dict[str, Any] = Field(default_factory=dict)            # sensors + metadata
    content_text: str = ""
    selection_reason: str = ""
    retrieval_round: int = 0                                         # 0 = initial, 1+ = targeted re-RAG
    used_by: List[str] = Field(default_factory=list)


class DerivedValue(BaseModel):
    """A value computed deterministically by the harness (citable as D-xxx)."""
    derived_id: str
    description: str
    value: Optional[float] = None
    text: Optional[str] = None
    inputs: List[str] = Field(default_factory=list)


class EvidenceStatement(BaseModel):
    statement: str
    evidence_ids: List[str] = Field(default_factory=list)


class Hypothesis(BaseModel):
    label: str
    score: float = 0.0
    evidence_ids: List[str] = Field(default_factory=list)
    supporting: List[EvidenceStatement] = Field(default_factory=list)
    contradicting: List[EvidenceStatement] = Field(default_factory=list)
    missing: List[str] = Field(default_factory=list)


class AgentReport(BaseModel):
    """Evidence-grounded, structured output of one of the six agents."""
    agent: str
    display_name: str
    finding: str
    finding_label: Optional[str] = None
    hypotheses: List[Hypothesis] = Field(default_factory=list)
    evidence_ids: List[str] = Field(default_factory=list)
    supporting_evidence: List[EvidenceStatement] = Field(default_factory=list)
    contradicting_evidence: List[EvidenceStatement] = Field(default_factory=list)
    missing_information: List[str] = Field(default_factory=list)
    confidence: float = 0.0
    narrative: str = ""
    recommendation: str = ""
    mode: Literal["llm", "deterministic", "llm+deterministic"] = "deterministic"
    extras: Dict[str, Any] = Field(default_factory=dict)
    pass_number: int = 1
    claims_removed: int = 0


class ClaimCheck(BaseModel):
    claim: str
    source: str
    status: ClaimStatus
    matched: Optional[str] = None
    action: str = "kept"


class ConfidenceFactor(BaseModel):
    name: str
    value: float
    weight: float
    explanation: str


class ConfidenceBreakdown(BaseModel):
    confidence: float
    factors: List[ConfidenceFactor]
    formula: str
    evidence_confidence: Optional[float] = None   # factor formula alone (before the council blend)
    council_confidence: Optional[float] = None    # agents' agreed confidence from the collaboration


class GateCriterion(BaseModel):
    criterion_id: str
    description: str
    passed: bool
    observed: str


class ReviewGateResult(BaseModel):
    decision: ReviewDecision
    criteria: List[GateCriterion]
    reasons: List[str] = Field(default_factory=list)


class Deficiency(BaseModel):
    code: str
    detail: str
    action: str
    rerun: List[str] = Field(default_factory=list)


class AuditEvent(BaseModel):
    step: int
    stage: str
    agent: Optional[str] = None
    action: str
    reason: str = ""
    status: Literal["ok", "warning", "loop", "skipped", "error"] = "ok"
    evidence_used: List[str] = Field(default_factory=list)
    retrieval_count: int = 0
    timestamp: float = Field(default_factory=time.time)
    duration_ms: float = 0.0


MessageKind = Literal["QUESTION", "CHALLENGE", "EVIDENCE_REQUEST", "EVIDENCE_SHARE", "POSITION_UPDATE",
                      "CONCESSION", "HOLD", "RISK_FLAG", "HUMAN_INPUT_REQUEST", "SYNTHESIS",
                      # collaborative council + verification exchange (harness/collaboration.py)
                      "FINDING", "RESPONSE", "COUNTER_ARGUMENT", "UNCERTAINTY_FLAG",
                      "VERIFICATION_REQUEST", "VERIFICATION_RESULT"]


class AgentMessage(BaseModel):
    """One typed message on the agent council board (M-001 …).

    Agents talk only through these messages.  A message may carry evidence /
    derived-value IDs and a structured ``payload`` (e.g. a pairwise share) that
    the council can act on; free text alone never changes a score.
    """
    message_id: str
    round: int
    sender: str
    recipients: List[str] = Field(default_factory=list)      # agent keys; ["all"] = broadcast
    kind: MessageKind
    topic: str = ""                                          # e.g. "Bearing Wear vs Lubrication Degradation"
    text: str
    evidence_ids: List[str] = Field(default_factory=list)
    in_reply_to: Optional[str] = None
    payload: Dict[str, Any] = Field(default_factory=dict)
    resolved: Optional[bool] = None                          # for QUESTION / CHALLENGE / requests
    phase: str = "council"                                   # collaboration | resync | verification | uncertainty | council | synthesis


class DiagnosticState(BaseModel):
    """Run-level context buffer shared by all agents (no long-term memory)."""
    run_id: str
    query: str
    dataset_type: str
    data_mode: str
    profile: Optional[QueryProfile] = None

    evidence: List[Evidence] = Field(default_factory=list)
    derived: List[DerivedValue] = Field(default_factory=list)
    retrieval_stats: Dict[str, Any] = Field(default_factory=dict)
    analysis: Dict[str, Any] = Field(default_factory=dict)

    diagnostic_expert_output: Optional[AgentReport] = None
    pattern_output: Optional[AgentReport] = None
    rapid_triage_output: Optional[AgentReport] = None
    verification_output: Optional[AgentReport] = None
    ambiguity_output: Optional[AgentReport] = None
    coordinator_output: Optional[AgentReport] = None

    contradictions: List[EvidenceStatement] = Field(default_factory=list)
    missing_evidence: List[str] = Field(default_factory=list)
    deficiencies_history: List[List[Deficiency]] = Field(default_factory=list)
    feedback_rounds: int = 0

    retrieval_quality: float = 0.0
    evidence_coverage: float = 0.0
    confidence: Optional[ConfidenceBreakdown] = None
    claim_checks: List[ClaimCheck] = Field(default_factory=list)
    review: Optional[ReviewGateResult] = None

    messages: List[AgentMessage] = Field(default_factory=list)   # agent council board
    round_counter: int = 0                                         # last message round used (all phases share one sequence)
    collab: Dict[str, Any] = Field(default_factory=dict)           # collaboration state (positions, joint finding)
    council: Dict[str, Any] = Field(default_factory=dict)          # council summary (trigger, rounds, deltas)

    final_label: Optional[str] = None
    final_diagnosis: str = ""
    audit_trail: List[AuditEvent] = Field(default_factory=list)

    # AgentTrace recorder for this run (harness/agent_trace). Private: never serialised,
    # never read by agents; it only observes posts and inbox reads.
    _trace: Any = PrivateAttr(default=None)
    # Per-run retrieval options (top_k, excluded record IDs). Kept on the run, not on the shared
    # orchestrator, so concurrent analyses cannot overwrite each other's settings.
    _run_opts: Dict[str, Any] = PrivateAttr(default_factory=dict)
    _phase: str = PrivateAttr(default="council")

    # helpers -----------------------------------------------------------------
    def evidence_by_id(self) -> Dict[str, Evidence]:
        return {e.evidence_id: e for e in self.evidence}

    def derived_by_id(self) -> Dict[str, DerivedValue]:
        return {d.derived_id: d for d in self.derived}

    def next_round(self) -> int:
        self.round_counter += 1
        return self.round_counter

    def set_phase(self, phase: str) -> None:
        self._phase = phase

    def post(self, *, round: int, sender: str, kind: str, text: str, recipients: Optional[List[str]] = None,
             topic: str = "", evidence_ids: Optional[List[str]] = None, in_reply_to: Optional[str] = None,
             payload: Optional[Dict[str, Any]] = None, resolved: Optional[bool] = None,
             phase: Optional[str] = None) -> AgentMessage:
        msg = AgentMessage(message_id=f"M-{len(self.messages) + 1:03d}", round=round, sender=sender,
                           recipients=recipients or ["all"], kind=kind, topic=topic, text=text,
                           evidence_ids=list(dict.fromkeys(evidence_ids or [])), in_reply_to=in_reply_to,
                           payload=payload or {}, resolved=resolved, phase=phase or self._phase)
        self.round_counter = max(self.round_counter, round)
        self.messages.append(msg)
        if self._trace is not None:
            self._trace.on_post(self, msg)
        return msg

    def inbox(self, agent: str, round: int) -> List[AgentMessage]:
        """Messages addressed to ``agent`` in ``round``. Reading the inbox is what the trace
        records as delivery (MESSAGE_RECEIVED), so agents must read through here."""
        msgs = [m for m in self.messages if m.round == round and m.sender != agent
                and (agent in m.recipients or "all" in m.recipients)]
        if self._trace is not None and msgs:
            self._trace.on_inbox(agent, msgs)
        return msgs

    def inbox_all(self, agent: str) -> List[AgentMessage]:
        """Every message addressed to ``agent`` (all rounds), recorded as delivered."""
        msgs = [m for m in self.messages if m.sender != agent and (agent in m.recipients or "all" in m.recipients)]
        if self._trace is not None and msgs:
            self._trace.on_inbox(agent, msgs)
        return msgs

    def read_board(self, agent: str) -> List[AgentMessage]:
        """The whole board, read by ``agent`` (e.g. the coordinator's council synthesis)."""
        msgs = list(self.messages)
        if self._trace is not None:
            self._trace.on_inbox(agent, [m for m in msgs if m.sender != agent], via="board_read")
        return msgs

    def add_derived(self, description: str, value: Optional[float] = None,
                    text: Optional[str] = None, inputs: Optional[List[str]] = None) -> str:
        did = f"D-{len(self.derived) + 1:03d}"
        self.derived.append(DerivedValue(derived_id=did, description=description, value=value,
                                         text=text, inputs=inputs or []))
        return did
