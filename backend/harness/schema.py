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

from pydantic import BaseModel, Field

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

    final_label: Optional[str] = None
    final_diagnosis: str = ""
    audit_trail: List[AuditEvent] = Field(default_factory=list)

    # helpers -----------------------------------------------------------------
    def evidence_by_id(self) -> Dict[str, Evidence]:
        return {e.evidence_id: e for e in self.evidence}

    def derived_by_id(self) -> Dict[str, DerivedValue]:
        return {d.derived_id: d for d in self.derived}

    def add_derived(self, description: str, value: Optional[float] = None,
                    text: Optional[str] = None, inputs: Optional[List[str]] = None) -> str:
        did = f"D-{len(self.derived) + 1:03d}"
        self.derived.append(DerivedValue(derived_id=did, description=description, value=value,
                                         text=text, inputs=inputs or []))
        return did
