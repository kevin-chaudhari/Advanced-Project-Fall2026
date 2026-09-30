"""Pydantic schemas for request/response models."""

from typing import Any, Dict, List

from pydantic import BaseModel, Field


class QueryRequest(BaseModel):
    question: str = Field(..., min_length=3, description="Natural language diagnostic question")
    dataset_type: str = Field(..., description="'failure_iq' or 'afrb'")
    top_k: int = Field(default=8, ge=1, le=20, description="Number of evidence records in the initial bundle")
    data_mode: str = Field(default="combined", description="'real' | 'synthetic' | 'combined' (falls back to what the dataset supports)")


class IndividualAgentOutput(BaseModel):
    """Full output from a single agent in the pipeline."""

    agent_name: str = Field(..., description="Display name, e.g. 'Diagnostic Expert'")
    agent_persona: str = Field(default="", description="Persona name, e.g. 'Dr. Elena Vasquez'")
    agent_emoji: str = Field(default="🤖", description="Emoji icon for the agent")
    persona_title: str = Field(default="", description="Professional title or archetype for the persona")
    persona_description: str = Field(default="", description="Detailed description of how this persona thinks")
    specialty: str = Field(default="", description="Primary technical specialty")
    decision_style: str = Field(default="", description="How this persona forms conclusions")
    execution_mode: str = Field(default="", description="Pipeline stage for this persona")
    agent_confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    diagnosis: str = Field(default="", description="This agent's individual diagnosis")
    key_findings: List[str] = Field(default_factory=list, description="Bullet-point findings")
    reasoning: str = Field(default="", description="Detailed reasoning paragraph")
    recommendation: str = Field(default="", description="What this agent recommends")


class AgentContributions(BaseModel):
    diagnostic_expert: str
    pattern_agent: str
    aggressive_agent: str
    verification: str
    ambiguity: str
    final_decision: str


# ─── System Analysis Report models ───────────────────────────────────────────

class RetrievalAnalysis(BaseModel):
    relevance_score: float = 0.0
    coverage_score: float = 0.0
    retrieval_efficiency: float = 0.0


class AgentAnalysis(BaseModel):
    diagnostic_expert: float = 0.0
    pattern_agent: float = 0.0
    aggressive_agent: float = 0.0
    verification: float = 0.0
    ambiguity: float = 0.0
    final_coordinator: float = 0.0
    agreement_score: float = 0.0


class FinalOutputAnalysis(BaseModel):
    correctness: float = 0.0
    logical_consistency: float = 0.0
    explainability: float = 0.0
    evidence_support: float = 0.0


class HallucinationAnalysis(BaseModel):
    detected: bool = False
    severity: float = 0.0


class ConfidenceAnalysis(BaseModel):
    confidence_score: float = 0.0
    calibration_error: float = 0.0


class SystemPerformance(BaseModel):
    latency_ms: float = 0.0
    efficiency_score: float = 0.0


class AggregatedScore(BaseModel):
    overall_score: float = 0.0
    risk_level: str = "unknown"


class GroundTruthSignal(BaseModel):
    document_rank: int = 0
    source: str = ""
    signal_type: str = ""
    signal: str = ""


class AgentGroundingEvaluation(BaseModel):
    agent_key: str = ""
    agent_name: str = ""
    diagnosis: str = ""
    reasoning_excerpt: str = ""
    supported_claims: int = 0
    total_claims: int = 0
    supported_steps: int = 0
    total_steps: int = 0
    faithfulness_score: float = 0.0
    reasoning_score: float = 0.0
    agreement_score: float = 0.0
    coverage_score: float = 0.0
    hallucination_rate: float = 0.0
    reliability_score: float = 0.0
    verdict: str = "unknown"
    strengths: List[str] = Field(default_factory=list)
    risks: List[str] = Field(default_factory=list)
    supported_evidence: List[str] = Field(default_factory=list)
    unsupported_claims: List[str] = Field(default_factory=list)
    ground_truth_alignment: List[str] = Field(default_factory=list)


class AgentReliabilityInsight(BaseModel):
    consistency_summary: str = ""
    strongest_agent: str = ""
    strongest_reasoning: str = ""
    conflicting_agents: List[str] = Field(default_factory=list)


class EnhancedEvaluationOutput(BaseModel):
    final_answer: str = ""
    final_diagnosis: str = ""
    reasoning: List[str] = Field(default_factory=list)
    supporting_evidence: List[str] = Field(default_factory=list)


class InlineEvaluationReport(BaseModel):
    reference_conclusion: str = ""
    ground_truth_signals: List[GroundTruthSignal] = Field(default_factory=list)
    per_agent_evaluations: List[AgentGroundingEvaluation] = Field(default_factory=list)
    faithfulness_score: float = 0.0
    reasoning_score: float = 0.0
    agreement_score: float = 0.0
    coverage_score: float = 0.0
    hallucination_rate: float = 0.0
    confidence_final: float = 0.0
    final_verdict: str = "Low Reliability"
    agent_reliability_insight: AgentReliabilityInsight = Field(
        default_factory=AgentReliabilityInsight
    )
    enhanced_output: EnhancedEvaluationOutput = Field(
        default_factory=EnhancedEvaluationOutput
    )


class AnalysisReport(BaseModel):
    """Complete structured output from the SystemAnalysisAgent."""
    retrieval: RetrievalAnalysis = Field(default_factory=RetrievalAnalysis)
    agents: AgentAnalysis = Field(default_factory=AgentAnalysis)
    final: FinalOutputAnalysis = Field(default_factory=FinalOutputAnalysis)
    hallucination: HallucinationAnalysis = Field(default_factory=HallucinationAnalysis)
    confidence: ConfidenceAnalysis = Field(default_factory=ConfidenceAnalysis)
    system: SystemPerformance = Field(default_factory=SystemPerformance)
    aggregated: AggregatedScore = Field(default_factory=AggregatedScore)
    insights: List[str] = Field(default_factory=list)
    recommendations: List[str] = Field(default_factory=list)
    inline_evaluation: InlineEvaluationReport = Field(
        default_factory=InlineEvaluationReport
    )


# ─── Query response ───────────────────────────────────────────────────────────

class QueryResponse(BaseModel):
    final_diagnosis: str
    direct_answer: str = Field(default="", description="Direct answer to the user's question")
    confidence: float = Field(..., ge=0.0, le=1.0)
    reasoning: List[str]
    supporting_evidence: List[str]
    agent_contributions: AgentContributions
    ambiguity: bool
    dataset_used: str
    retrieved_context_count: int
    agent_outputs: List[IndividualAgentOutput] = Field(
        default_factory=list,
        description="Individual detailed output from each of the 6 agents",
    )
    analysis_report: AnalysisReport = Field(
        default_factory=AnalysisReport,
        description="Full system analysis produced by the SystemAnalysisAgent",
    )
    phase_test_results: Any = Field(
        default=None,
        description="Legacy LLM-judge phase results (disabled by default; replaced by deterministic claim validation)",
    )
    review_decision: str = Field(default="", description="AUTO_RESOLVE or REQUIRES_HUMAN_REVIEW (explicit gate)")
    recommendation: str = Field(default="", description="Recommended next action")
    data_mode: str = Field(default="", description="Dataset mode used: real / synthetic / combined")
    harness: Dict[str, Any] = Field(default_factory=dict,
        description="Structured run state: evidence (EV-ids), hypotheses, agents, verification, "
                    "feedback loop, confidence factors, review gate, claim validation, audit timeline")


class LoadDataResponse(BaseModel):
    success: bool
    dataset: str
    documents_loaded: int
    message: str


class HealthResponse(BaseModel):
    status: str
    failure_iq_loaded: bool
    afrb_loaded: bool
    message: str
    data_modes: Dict[str, List[str]] = Field(default_factory=dict)
    record_counts: Dict[str, Dict[str, int]] = Field(default_factory=dict)
    llm_mode: str = ""


class RetrievedDocument(BaseModel):
    content: str
    score: float
    metadata: Dict[str, Any] = {}


class AnalysisRecord(BaseModel):
    """Single row from the analysis_results SQLite table."""
    id: int
    created_at: str
    question: str
    dataset: str
    final_diagnosis: str
    confidence: float
    latency_ms: float
    overall_score: float
    risk_level: str
    analysis_json: Any = None
