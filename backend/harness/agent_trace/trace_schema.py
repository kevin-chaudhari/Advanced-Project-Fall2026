"""
AgentTrace schema for the Industrial Diagnostic AI harness  (``ida.agenttrace/1.0``).

Adapted from the AgentTrace semantic layer (``agenttrace.semantic/0.3``, IBM_Project2):
only *observable* things are stored, raw events are kept separate from derived
views, and anything the instrumentation cannot establish is ``UNKNOWN`` rather
than guessed.

Exposure ladder used for every evidence item (EV-xxx / D-xxx) and message:

    RETRIEVED          the harness put the record into this run's evidence bundle
    IN_AGENT_INPUT     the record was in the DiagnosticState object handed to the
                       agent call (deterministic agents read the state directly)
    IN_RENDERED_INPUT  the ID occurs in the exact prompt text sent to the LLM
                       (TRUE / FALSE only when the full prompt was captured;
                       NOT_APPLICABLE when the execution made no model call)
    CITED              the agent's output (report, claim or message) references it
    VERIFIED           a verification step checked a claim that cites it

Delivered never means "used": a delivered item shows uptake only when the
agent's output cites it, and citing is recorded as CITED, not as reasoning.
A message counts as RECEIVED only when the recipient's own code read it from
its inbox (or the message ID occurs in its rendered prompt).
"""

from __future__ import annotations

import re
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

TRACE_SCHEMA_VERSION = "ida.agenttrace/1.0"


class EventType(str, Enum):
    TRACE_STARTED = "TRACE_STARTED"
    QUERY_PREPARED = "QUERY_PREPARED"
    RETRIEVAL_STARTED = "RETRIEVAL_STARTED"
    EVIDENCE_RETRIEVED = "EVIDENCE_RETRIEVED"
    HYPOTHESES_SCORED = "HYPOTHESES_SCORED"
    EVIDENCE_DELIVERED = "EVIDENCE_DELIVERED"
    AGENT_STARTED = "AGENT_STARTED"
    LLM_CALL_COMPLETED = "LLM_CALL_COMPLETED"
    AGENT_OUTPUT_GENERATED = "AGENT_OUTPUT_GENERATED"
    AGENT_FAILED = "AGENT_FAILED"
    AGENT_REEXECUTED = "AGENT_REEXECUTED"
    TOOL_CALLED = "TOOL_CALLED"
    MESSAGE_SENT = "MESSAGE_SENT"
    MESSAGE_RECEIVED = "MESSAGE_RECEIVED"
    QUESTION_RAISED = "QUESTION_RAISED"
    HYPOTHESIS_PROPOSED = "HYPOTHESIS_PROPOSED"
    HYPOTHESIS_CHALLENGED = "HYPOTHESIS_CHALLENGED"
    HYPOTHESIS_UPDATED = "HYPOTHESIS_UPDATED"
    EVIDENCE_REQUESTED = "EVIDENCE_REQUESTED"
    EVIDENCE_VERIFIED = "EVIDENCE_VERIFIED"
    FEEDBACK_LOOP_TRIGGERED = "FEEDBACK_LOOP_TRIGGERED"
    TARGETED_RETRIEVAL_STARTED = "TARGETED_RETRIEVAL_STARTED"
    COLLABORATION_STARTED = "COLLABORATION_STARTED"
    COLLABORATION_ROUND_STARTED = "COLLABORATION_ROUND_STARTED"
    COLLABORATION_ROUND_COMPLETED = "COLLABORATION_ROUND_COMPLETED"
    JOINT_FINDING_REACHED = "JOINT_FINDING_REACHED"
    VERIFICATION_EXCHANGE_COMPLETED = "VERIFICATION_EXCHANGE_COMPLETED"
    COUNCIL_CONVENED = "COUNCIL_CONVENED"
    COUNCIL_SKIPPED = "COUNCIL_SKIPPED"
    COUNCIL_ROUND_STARTED = "COUNCIL_ROUND_STARTED"
    COUNCIL_ROUND_COMPLETED = "COUNCIL_ROUND_COMPLETED"
    DISAGREEMENT_RESOLVED = "DISAGREEMENT_RESOLVED"
    DISAGREEMENT_UNRESOLVED = "DISAGREEMENT_UNRESOLVED"
    CLAIM_VALIDATED = "CLAIM_VALIDATED"
    CONFIDENCE_RECALCULATED = "CONFIDENCE_RECALCULATED"
    HUMAN_REVIEW_TRIGGERED = "HUMAN_REVIEW_TRIGGERED"
    REVIEW_GATE_PASSED = "REVIEW_GATE_PASSED"
    FINAL_SYNTHESIS_GENERATED = "FINAL_SYNTHESIS_GENERATED"
    TRACE_COMPLETED = "TRACE_COMPLETED"
    TRACE_FAILED = "TRACE_FAILED"


class MessageType(str, Enum):
    QUESTION = "QUESTION"
    FINDING = "FINDING"
    EVIDENCE_SHARE = "EVIDENCE_SHARE"
    EVIDENCE_REQUEST = "EVIDENCE_REQUEST"
    CHALLENGE = "CHALLENGE"
    RESPONSE = "RESPONSE"
    COUNTER_ARGUMENT = "COUNTER_ARGUMENT"
    CONCESSION = "CONCESSION"
    HOLD = "HOLD"
    POSITION_UPDATE = "POSITION_UPDATE"
    UNCERTAINTY_FLAG = "UNCERTAINTY_FLAG"
    RISK_FLAG = "RISK_FLAG"
    VERIFICATION_REQUEST = "VERIFICATION_REQUEST"
    VERIFICATION_RESULT = "VERIFICATION_RESULT"
    HUMAN_INPUT_REQUEST = "HUMAN_INPUT_REQUEST"
    SYNTHESIS = "SYNTHESIS"


CHALLENGE_KINDS = {"CHALLENGE", "COUNTER_ARGUMENT"}
ASK_KINDS = {"QUESTION", "CHALLENGE", "COUNTER_ARGUMENT", "EVIDENCE_REQUEST", "VERIFICATION_REQUEST",
             "HUMAN_INPUT_REQUEST"}


class Observed(str, Enum):
    """Tri-state used wherever the trace may not be able to establish a fact."""
    TRUE = "TRUE"
    FALSE = "FALSE"
    UNKNOWN = "UNKNOWN"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class EvidenceRelation(str, Enum):
    RETRIEVED = "RETRIEVED"                  # subject: retrieval action
    IN_AGENT_INPUT = "IN_AGENT_INPUT"        # subject: execution
    IN_RENDERED_INPUT = "IN_RENDERED_INPUT"  # subject: execution, value TRUE/FALSE
    CITED_BY_AGENT = "CITED_BY_AGENT"        # subject: execution
    CITED_BY_CLAIM = "CITED_BY_CLAIM"        # subject: claim id
    CITED_IN_MESSAGE = "CITED_IN_MESSAGE"    # subject: message id
    VERIFIED = "VERIFIED"                    # subject: claim id, value SUPPORTED/DERIVED/UNSUPPORTED/MISSING


class HypothesisStatus(str, Enum):
    PROPOSED = "PROPOSED"
    RETAINED = "RETAINED"
    CHALLENGED = "CHALLENGED"
    QUALIFIED = "QUALIFIED"
    MODIFIED = "MODIFIED"
    REJECTED = "REJECTED"
    UNRESOLVED = "UNRESOLVED"
    FINAL = "FINAL"


class ExecutionStatus(str, Enum):
    RUNNING = "RUNNING"          # persisted at start; stays RUNNING if the process dies mid-call
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class TraceStatus(str, Enum):
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    COMPLETED_WITH_ERRORS = "COMPLETED_WITH_ERRORS"   # an agent failed but the pipeline finished
    FAILED = "FAILED"


# ── helpers ──────────────────────────────────────────────────────────────────

_SLUG = re.compile(r"[^a-z0-9]+")
EVIDENCE_REF = re.compile(r"\b(?:EV|D)-\d{3,}\b")
MESSAGE_REF = re.compile(r"\bM-\d{3,}\b")


def hypothesis_id(label: Optional[str]) -> Optional[str]:
    """Holder-independent hypothesis identity (a proposition: 'the fault is <label>')."""
    if not label:
        return None
    return "HYP-" + _SLUG.sub("-", str(label).lower()).strip("-")


_LABEL_KEYS = ("label", "your_label", "verified", "proposed", "new_label", "old_label", "favours", "final_label")


def hypothesis_labels_in_payload(payload: Dict[str, Any]) -> List[str]:
    """Hypothesis labels named in a message's *structured* payload (never parsed from prose)."""
    out: List[str] = []
    for k in _LABEL_KEYS:
        v = payload.get(k)
        if isinstance(v, str) and v:
            out.append(v)
    for k in ("pair", "hypotheses", "labels"):
        v = payload.get(k)
        if isinstance(v, (list, tuple)):
            out += [x for x in v if isinstance(x, str) and x]
    return list(dict.fromkeys(out))


# ── API response models ──────────────────────────────────────────────────────

class TraceEventModel(BaseModel):
    event_id: str
    trace_id: str
    seq: int
    event_type: str
    timestamp: str
    actor: Optional[str] = None
    execution_id: Optional[str] = None
    message_id: Optional[str] = None
    evidence_ids: List[str] = Field(default_factory=list)
    parent_event_id: Optional[str] = None
    payload: Dict[str, Any] = Field(default_factory=dict)


class TraceMessageModel(BaseModel):
    message_id: str
    global_message_id: str
    trace_id: str
    round_id: int
    seq: int
    sender_agent_id: str
    receiver_agent_ids: List[str]
    message_type: str
    timestamp: str
    topic: str = ""
    message_content: str
    related_hypothesis_ids: List[str] = Field(default_factory=list)
    evidence_ids: List[str] = Field(default_factory=list)
    parent_message_id: Optional[str] = None
    response_to_message_id: Optional[str] = None
    challenge_status: str = "NOT_APPLICABLE"
    resolution_status: str = "NOT_APPLICABLE"
    stage: Optional[str] = None
    sender_execution_id: Optional[str] = None
    payload: Dict[str, Any] = Field(default_factory=dict)
    deliveries: List[Dict[str, Any]] = Field(default_factory=list)


class TraceListItem(BaseModel):
    trace_id: str
    run_id: Optional[str] = None
    analysis_id: Optional[int] = None
    query: str
    dataset_type: str
    data_mode: str
    status: str
    started_at: str
    completed_at: Optional[str] = None
    duration_ms: Optional[float] = None
    final_label: Optional[str] = None
    final_confidence: Optional[float] = None
    review_decision: Optional[str] = None
    communication_rounds: Optional[int] = None
    total_messages: Optional[int] = None
    llm_mode: Optional[str] = None


class TraceListResponse(BaseModel):
    traces: List[TraceListItem]
    total: int
    limit: int
    offset: int


class PagedEvents(BaseModel):
    trace_id: str
    events: List[TraceEventModel]
    total: int
    limit: int
    offset: int
