"""
Phase-wise evaluation engine — LLM-as-a-Judge edition.

Every metric is now computed by sending the agent's actual reasoning and
diagnosis to the same LLM that powers the diagnostic agents.  The judge
compares the agent's output against the RAG-retrieved ground-truth context
and returns a structured score with a justification.

Metrics
-------
faithfulness_score  — Are all claims traceable to retrieved documents?
reasoning_score     — Is the logical chain internally sound and correct?
agreement_score     — Does the diagnosis align with peer agents?
coverage_score      — Does the agent address all key evidence signals?
reliability_score   — Is the output consistent, actionable, and complete?
hallucination_rate  — Did the agent invent facts not present in context?
"""

import asyncio
import json
import re
from typing import Any, Dict, List, Optional

from utils.llm_client import llm_client
from utils.logger import setup_logger

logger = setup_logger(__name__)

# ---------------------------------------------------------------------------
# LLM Judge helper
# ---------------------------------------------------------------------------

_JUDGE_SYSTEM = (
    "You are an expert industrial diagnostic evaluator. "
    "Your only job is to score agent outputs against ground-truth evidence. "
    "ALWAYS respond with a single valid JSON object. No prose outside JSON."
)


async def _judge(prompt: str) -> Dict:
    """Call the LLM judge and return the parsed JSON score dict."""
    try:
        raw = await llm_client.generate(prompt, system=_JUDGE_SYSTEM)
        result = llm_client.extract_json(raw)
        return result if result else {}
    except Exception as exc:
        logger.warning("LLM judge call failed: %s", exc)
        return {}


# ---------------------------------------------------------------------------
# Per-metric judge prompts
# ---------------------------------------------------------------------------

def _make_faithfulness_prompt(agent_name: str, diagnosis: str, reasoning: str, ground_truth_context: str) -> str:
    return f"""
You are evaluating the FAITHFULNESS of an industrial diagnostic agent called "{agent_name}".

GROUND TRUTH CONTEXT (retrieved sensor records and evidence):
{ground_truth_context[:3000]}

AGENT DIAGNOSIS:
{diagnosis[:500]}

AGENT REASONING:
{reasoning[:800]}

TASK:
1. Read every claim in the agent's diagnosis and reasoning.
2. For each claim, check if it is directly supported by a specific sentence or data point in the GROUND TRUTH CONTEXT.
3. Count: how many claims are supported, how many are invented or not traceable.
4. Assign a faithfulness_score between 0.0 (pure hallucination) and 1.0 (every claim grounded).

Respond ONLY with this JSON:
{{
  "faithfulness_score": 0.0,
  "supported_claims": ["claim 1 found in context", "..."],
  "unsupported_claims": ["claim invented with no evidence", "..."],
  "justification": "One sentence explaining the score."
}}
"""


def _make_reasoning_prompt(agent_name: str, diagnosis: str, reasoning: str, ground_truth_context: str) -> str:
    return f"""
You are evaluating the REASONING QUALITY of an industrial diagnostic agent called "{agent_name}".

GROUND TRUTH CONTEXT (retrieved sensor records and evidence):
{ground_truth_context[:3000]}

AGENT DIAGNOSIS:
{diagnosis[:500]}

AGENT REASONING:
{reasoning[:800]}

TASK:
1. Does the agent's reasoning correctly interpret the sensor values and thresholds from the context?
2. Does the agent connect evidence to the diagnosis with sound causal logic (not just correlation)?
3. Are there logical leaps, contradictions, or missed steps?
4. Assign a reasoning_score between 0.0 (illogical/wrong) and 1.0 (correct, clear, causally sound).

Respond ONLY with this JSON:
{{
  "reasoning_score": 0.0,
  "correct_steps": ["step that is logically correct", "..."],
  "flawed_steps": ["step with a logical error or leap", "..."],
  "justification": "One sentence explaining the score."
}}
"""


def _make_coverage_prompt(agent_name: str, key_findings: List[str], ground_truth_context: str) -> str:
    findings_text = "\n".join(f"- {f}" for f in key_findings) if key_findings else "No findings listed."
    return f"""
You are evaluating the EVIDENCE COVERAGE of an industrial diagnostic agent called "{agent_name}".

GROUND TRUTH CONTEXT (retrieved sensor records and evidence):
{ground_truth_context[:3000]}

AGENT KEY FINDINGS:
{findings_text}

TASK:
1. Identify the 5 most important diagnostic signals in the Ground Truth Context (sensor values, anomalies, thresholds breached).
2. Check which of those signals the agent explicitly addressed in its key findings.
3. coverage_score = (signals addressed) / (total important signals found).

Respond ONLY with this JSON:
{{
  "coverage_score": 0.0,
  "signals_found_in_context": ["signal 1", "signal 2", "..."],
  "signals_addressed_by_agent": ["signal addressed", "..."],
  "signals_missed": ["signal the agent ignored", "..."],
  "justification": "One sentence explaining the score."
}}
"""


def _make_hallucination_prompt(agent_name: str, diagnosis: str, reasoning: str, ground_truth_context: str) -> str:
    return f"""
You are a hallucination detector for an industrial diagnostic agent called "{agent_name}".

GROUND TRUTH CONTEXT (retrieved sensor records only — this is what the agent was allowed to know):
{ground_truth_context[:3000]}

AGENT DIAGNOSIS:
{diagnosis[:500]}

AGENT REASONING:
{reasoning[:800]}

TASK:
1. Find every specific fact, number, sensor value, or technical term in the agent's output.
2. Check each against the Ground Truth Context.
3. Any fact that is NOT in the context AND is stated as certain is a hallucination.
4. hallucination_rate = (hallucinated facts) / (total specific facts stated). Range: 0.0 to 1.0.

Respond ONLY with this JSON:
{{
  "hallucination_rate": 0.0,
  "hallucinated_facts": ["invented fact 1", "..."],
  "verified_facts": ["fact found in context", "..."],
  "justification": "One sentence explaining the rate."
}}
"""


def _make_agreement_prompt(agent_name: str, own_diagnosis: str, peer_diagnoses: List[str]) -> str:
    peers_text = "\n".join(f"- {d}" for d in peer_diagnoses) if peer_diagnoses else "No peer diagnoses available."
    return f"""
You are evaluating the AGREEMENT of industrial diagnostic agent "{agent_name}" with its peer agents.

THIS AGENT'S DIAGNOSIS:
{own_diagnosis[:400]}

PEER AGENT DIAGNOSES:
{peers_text}

TASK:
1. Read this agent's diagnosis and all peer diagnoses.
2. Identify the core failure mode each agent identified.
3. Check whether this agent's diagnosis agrees on the ROOT CAUSE (not wording).
4. agreement_score = 0.0 (completely contradicts peers) to 1.0 (fully agrees on root cause).

Respond ONLY with this JSON:
{{
  "agreement_score": 0.0,
  "shared_root_cause": "The failure mode all/most agents agree on, or 'None'",
  "this_agent_root_cause": "Root cause this agent identified",
  "conflicts": ["Any direct contradiction with a peer", "..."],
  "justification": "One sentence explaining the score."
}}
"""


def _make_reliability_prompt(agent_name: str, result: Dict) -> str:
    recommendation = result.get("recommendation") or result.get("immediate_action") or ""
    confidence = result.get("agent_confidence") or result.get("confidence") or result.get("verification_confidence") or result.get("overall_confidence") or 0.5
    key_findings = result.get("key_findings", [])
    return f"""
You are evaluating the RELIABILITY of industrial diagnostic agent "{agent_name}".

AGENT CONFIDENCE: {confidence}
AGENT RECOMMENDATION: {recommendation[:400]}
AGENT KEY FINDINGS COUNT: {len(key_findings)}

TASK:
1. Is the recommendation specific and actionable (not vague like "inspect equipment")?
2. Is the confidence score plausible given the complexity of the case?
3. Does the agent provide enough structured output (findings, recommendation) to be operationally useful?
4. reliability_score = 0.0 (vague, unusable) to 1.0 (specific, actionable, well-calibrated).

Respond ONLY with this JSON:
{{
  "reliability_score": 0.0,
  "is_recommendation_specific": true,
  "is_confidence_well_calibrated": true,
  "justification": "One sentence explaining the score."
}}
"""


# ---------------------------------------------------------------------------
# Core per-agent evaluator
# ---------------------------------------------------------------------------

async def evaluate_agent_llm(
    agent_key: str,
    agent_name: str,
    result: Dict[str, Any],
    peer_results: List[Dict[str, Any]],
    ground_truth_context: str,
) -> Dict[str, Any]:
    """
    Score a single agent using LLM-as-a-Judge calls for all 5 metrics.
    All judge calls run in parallel for speed.
    """
    diagnosis = str(
        result.get("diagnosis") or result.get("primary_hypothesis") or
        result.get("dominant_failure_signature") or result.get("decision") or
        result.get("verified_diagnosis") or result.get("ambiguity_summary") or
        result.get("final_diagnosis") or ""
    )
    reasoning = str(
        result.get("reasoning_detail") or result.get("reasoning") or
        result.get("analysis") or result.get("trend_analysis") or ""
    )
    if isinstance(reasoning, list):
        reasoning = " ".join(str(r) for r in reasoning)

    key_findings = result.get("key_findings", [])
    peer_diagnoses = [
        str(p.get("diagnosis") or p.get("primary_hypothesis") or
            p.get("dominant_failure_signature") or p.get("decision") or "")
        for p in peer_results
        if p
    ]

    # Run all judge prompts in parallel
    (
        faith_raw,
        reason_raw,
        coverage_raw,
        halluc_raw,
        agree_raw,
        rely_raw,
    ) = await asyncio.gather(
        _judge(_make_faithfulness_prompt(agent_name, diagnosis, reasoning, ground_truth_context)),
        _judge(_make_reasoning_prompt(agent_name, diagnosis, reasoning, ground_truth_context)),
        _judge(_make_coverage_prompt(agent_name, key_findings, ground_truth_context)),
        _judge(_make_hallucination_prompt(agent_name, diagnosis, reasoning, ground_truth_context)),
        _judge(_make_agreement_prompt(agent_name, diagnosis, peer_diagnoses)),
        _judge(_make_reliability_prompt(agent_name, result)),
    )

    faithfulness   = float(faith_raw.get("faithfulness_score",  0.60))
    reasoning_sc   = float(reason_raw.get("reasoning_score",     0.60))
    coverage       = float(coverage_raw.get("coverage_score",    0.60))
    hallucination  = float(halluc_raw.get("hallucination_rate",  0.20))
    agreement      = float(agree_raw.get("agreement_score",      0.65))
    reliability    = float(rely_raw.get("reliability_score",     0.60))

    # Clamp all scores
    faithfulness  = max(0.0, min(1.0, faithfulness))
    reasoning_sc  = max(0.0, min(1.0, reasoning_sc))
    coverage      = max(0.0, min(1.0, coverage))
    hallucination = max(0.0, min(1.0, hallucination))
    agreement     = max(0.0, min(1.0, agreement))
    reliability   = max(0.0, min(1.0, reliability))

    overall = round(
        (faithfulness + reasoning_sc + agreement + coverage + reliability) / 5.0, 3
    )

    if overall >= 0.78:
        verdict = "PASS ✅"
        verdict_color = "green"
    elif overall >= 0.60:
        verdict = "PARTIAL ⚠️"
        verdict_color = "yellow"
    else:
        verdict = "FAIL ❌"
        verdict_color = "red"

    # Collect judge explanations for the UI
    strengths, risks = _derive_strengths_risks_llm(
        faithfulness, reasoning_sc, agreement, coverage, reliability, hallucination,
        faith_raw, reason_raw, coverage_raw, agree_raw,
    )

    return {
        "agent_key":           agent_key,
        "agent_name":          agent_name,
        "faithfulness_score":  faithfulness,
        "reasoning_score":     reasoning_sc,
        "agreement_score":     agreement,
        "coverage_score":      coverage,
        "reliability_score":   reliability,
        "hallucination_rate":  hallucination,
        "overall_score":       overall,
        "verdict":             verdict,
        "verdict_color":       verdict_color,
        "diagnosis_excerpt":   diagnosis[:200],
        "reasoning_excerpt":   reasoning[:300],
        "strengths":           strengths,
        "risks":               risks,
        # LLM judge detail (for transparency in the UI)
        "judge_detail": {
            "faithfulness":  faith_raw.get("justification", ""),
            "reasoning":     reason_raw.get("justification", ""),
            "coverage":      coverage_raw.get("justification", ""),
            "hallucination": halluc_raw.get("justification", ""),
            "agreement":     agree_raw.get("justification", ""),
            "reliability":   rely_raw.get("justification", ""),
            "supported_claims":    faith_raw.get("supported_claims", []),
            "unsupported_claims":  faith_raw.get("unsupported_claims", []),
            "hallucinated_facts":  halluc_raw.get("hallucinated_facts", []),
            "signals_missed":      coverage_raw.get("signals_missed", []),
            "shared_root_cause":   agree_raw.get("shared_root_cause", ""),
        },
    }


def _derive_strengths_risks_llm(
    f: float, r: float, a: float, c: float, rel: float, h: float,
    faith_raw: Dict, reason_raw: Dict, coverage_raw: Dict, agree_raw: Dict,
) -> tuple:
    strengths = []
    risks = []

    if f >= 0.75:
        strengths.append(f"Well-grounded: {faith_raw.get('justification', 'Strong evidence grounding.')}")
    if r >= 0.75:
        strengths.append(f"Sound reasoning: {reason_raw.get('justification', 'Causally correct reasoning chain.')}")
    if a >= 0.70:
        strengths.append(f"Peer consensus: {agree_raw.get('justification', 'Agrees with peer agents.')}")
    if c >= 0.72:
        strengths.append(f"Good coverage: {coverage_raw.get('justification', 'Addressed key evidence signals.')}")
    if rel >= 0.75:
        strengths.append("Highly reliable and actionable output.")
    if not strengths:
        strengths.append("Adequate baseline performance.")

    if f < 0.65:
        risks.append(f"Low faithfulness: {faith_raw.get('justification', 'Claims not fully grounded.')}")
    if r < 0.60:
        risks.append(f"Weak reasoning: {reason_raw.get('justification', 'Logical gaps detected.')}")
    if a < 0.55:
        risks.append(f"Low agreement: {agree_raw.get('justification', 'Contradicts peer agents.')}")
    if h > 0.25:
        risks.append(f"Hallucination risk: agent stated facts not found in retrieved context.")
    if not risks:
        risks.append("No critical risks identified by LLM judge.")

    return strengths, risks


# ---------------------------------------------------------------------------
# Phase evaluators (now async)
# ---------------------------------------------------------------------------

async def evaluate_phase1(
    diag_result: Dict,
    aggr_result: Dict,
    pattern_result: Dict,
    ground_truth_context: str = "",
) -> Dict[str, Any]:
    """Evaluate the 3 Phase-1 specialist agents with LLM judge."""
    diag_eval, aggr_eval, pattern_eval = await asyncio.gather(
        evaluate_agent_llm("diagnostic_expert", "Diagnostic Expert",
                           diag_result, [aggr_result, pattern_result], ground_truth_context),
        evaluate_agent_llm("aggressive_agent",  "Aggressive Decision Agent",
                           aggr_result, [diag_result, pattern_result], ground_truth_context),
        evaluate_agent_llm("pattern_agent",     "Pattern Recognition Agent",
                           pattern_result, [diag_result, aggr_result], ground_truth_context),
    )

    per_agent = [diag_eval, aggr_eval, pattern_eval]
    phase_score = round(sum(e["overall_score"] for e in per_agent) / 3.0, 3)
    passed = sum(1 for e in per_agent if "PASS" in e["verdict"])

    all_diagnoses = " | ".join([
        str(diag_result.get("primary_hypothesis", "")),
        str(aggr_result.get("decision", "")),
        str(pattern_result.get("dominant_failure_signature", "")),
    ])

    return {
        "phase":             1,
        "phase_name":        "Specialist Analysis",
        "phase_description": "Three specialist agents analyze the evidence in parallel. LLM judge scores each against the ground-truth RAG context.",
        "agent_evaluations": per_agent,
        "phase_score":       phase_score,
        "agents_passed":     passed,
        "agents_total":      3,
        "phase_verdict":     "PASS ✅" if phase_score >= 0.70 else ("PARTIAL ⚠️" if phase_score >= 0.55 else "FAIL ❌"),
        "consensus_excerpt": all_diagnoses[:300],
        "recommendations_for_next_phase": _p1_recommendations(diag_eval, aggr_eval, pattern_eval),
    }


def _p1_recommendations(diag: Dict, aggr: Dict, pattern: Dict) -> List[str]:
    recs = []
    if diag["faithfulness_score"] < 0.70:
        recs.append("Verification should carefully re-examine Diagnostic Expert — LLM judge found unsupported claims.")
    if aggr["agreement_score"] < 0.55:
        recs.append("Aggressive Decision Agent diverged from peers — Verification must resolve the discrepancy.")
    if pattern["coverage_score"] < 0.65:
        recs.append("Pattern Agent missed key evidence signals — Verification should seek additional pattern evidence.")
    if any(e["hallucination_rate"] > 0.25 for e in [diag, aggr, pattern]):
        recs.append("One or more Phase 1 agents showed elevated hallucination — Verification must cross-check all facts against context.")
    if not recs:
        recs.append("Phase 1 outputs are well-grounded and coherent — Verification can proceed with high confidence.")
    return recs


async def evaluate_phase2(
    ver_result: Dict,
    phase1_evals: List[Dict],
    ground_truth_context: str = "",
) -> Dict[str, Any]:
    """Evaluate Phase-2: Verification Analyst with LLM judge."""
    p1_best = max(phase1_evals, key=lambda e: e["overall_score"]) if phase1_evals else {}
    peer_proxy = [{"diagnosis": p1_best.get("diagnosis_excerpt", "")}] if p1_best else []

    ver_eval = await evaluate_agent_llm(
        "verification", "Verification Analyst",
        ver_result, peer_proxy, ground_truth_context,
    )

    # Bonus for resolving contradictions
    contradictions_resolved = len(ver_result.get("contradictions_resolved", []))
    bonus = min(0.08, contradictions_resolved * 0.025)
    ver_eval["overall_score"] = round(min(1.0, ver_eval["overall_score"] + bonus), 3)

    phase_score = ver_eval["overall_score"]
    p1_avg = round(sum(e["overall_score"] for e in phase1_evals) / max(len(phase1_evals), 1), 3) if phase1_evals else 0.65
    improvement = round(phase_score - p1_avg, 3)

    return {
        "phase":             2,
        "phase_name":        "Verification & Cross-Validation",
        "phase_description": "Verification Analyst audits Phase 1 outputs. LLM judge checks if its reasoning correctly resolves contradictions.",
        "agent_evaluations": [ver_eval],
        "phase_score":       phase_score,
        "agents_passed":     1 if "PASS" in ver_eval["verdict"] else 0,
        "agents_total":      1,
        "phase_verdict":     "PASS ✅" if phase_score >= 0.70 else ("PARTIAL ⚠️" if phase_score >= 0.55 else "FAIL ❌"),
        "phase1_avg_score":           p1_avg,
        "improvement_over_phase1":    improvement,
        "contradictions_resolved":    contradictions_resolved,
        "agreements_found":           len(ver_result.get("agreements", [])),
        "recommendations_for_next_phase": _p2_recommendations(ver_eval, ver_result),
    }


def _p2_recommendations(ver_eval: Dict, ver_result: Dict) -> List[str]:
    recs = []
    if ver_eval["overall_score"] < 0.65:
        recs.append("Ambiguity Detection should flag this case for human review — verification confidence is low.")
    if len(ver_result.get("contradictions_found", [])) > 2:
        recs.append(f"{len(ver_result['contradictions_found'])} contradictions found — Ambiguity Agent must probe carefully.")
    if ver_eval.get("hallucination_rate", 0) > 0.20:
        recs.append("Verification Analyst introduced new unsupported claims — Ambiguity Agent should flag these.")
    if ver_eval["reasoning_score"] < 0.60:
        recs.append("Weak causal reasoning in verification — Ambiguity Agent should treat conclusions conservatively.")
    if not recs:
        recs.append("Verification passed cleanly — Ambiguity Detection can focus on confidence calibration.")
    return recs


async def evaluate_phase3(
    amb_result: Dict,
    phase2_eval: Dict,
    ground_truth_context: str = "",
) -> Dict[str, Any]:
    """Evaluate Phase-3: Ambiguity Detection Agent with LLM judge."""
    amb_eval = await evaluate_agent_llm(
        "ambiguity", "Ambiguity Detection Agent",
        amb_result, [], ground_truth_context,
    )

    # Bonus for correct human-review calibration
    ver_conf = float(amb_result.get("overall_confidence", 0.65))
    human_review = bool(amb_result.get("human_review_required", False))
    calibration_bonus = 0.05 if (ver_conf < 0.65) == human_review else 0.0
    amb_eval["overall_score"] = round(min(1.0, amb_eval["overall_score"] + calibration_bonus), 3)

    return {
        "phase":             3,
        "phase_name":        "Ambiguity & Uncertainty Detection",
        "phase_description": "Ambiguity Agent calibrates confidence. LLM judge checks if uncertainty claims are grounded in context gaps.",
        "agent_evaluations": [amb_eval],
        "phase_score":       amb_eval["overall_score"],
        "agents_passed":     1 if "PASS" in amb_eval["verdict"] else 0,
        "agents_total":      1,
        "phase_verdict":     "PASS ✅" if amb_eval["overall_score"] >= 0.70 else ("PARTIAL ⚠️" if amb_eval["overall_score"] >= 0.55 else "FAIL ❌"),
        "confidence_calibrated":  ver_conf,
        "risk_level":             str(amb_result.get("risk_level", "MEDIUM")),
        "human_review_required":  human_review,
        "conflicts_detected":     len(amb_result.get("conflicts_detected", [])),
        "phase2_score":           phase2_eval.get("phase_score", 0.65),
        "recommendations_for_next_phase": _p3_recommendations(amb_eval, amb_result),
    }


def _p3_recommendations(amb_eval: Dict, amb_result: Dict) -> List[str]:
    recs = []
    if amb_result.get("human_review_required"):
        recs.append("Human Coordinator must escalate to a human expert — review is required.")
    if float(amb_result.get("overall_confidence", 0.65)) < 0.60:
        recs.append("Critically low confidence — Coordinator must communicate uncertainty prominently.")
    if amb_eval["faithfulness_score"] < 0.65:
        recs.append("Ambiguity Agent made unsupported uncertainty claims — Coordinator should verify before acting.")
    if not recs:
        recs.append("Ambiguity assessment complete and grounded — Coordinator can proceed with confidence.")
    return recs


async def evaluate_phase4(
    final_result: Dict,
    phase3_eval: Dict,
    all_phase_evals: List[Dict],
    ground_truth_context: str = "",
) -> Dict[str, Any]:
    """Evaluate Phase-4: Human Review Coordinator with LLM judge."""
    coord_eval = await evaluate_agent_llm(
        "human_review_coordinator", "Human Review Coordinator",
        final_result, [], ground_truth_context,
    )

    synthesis_quality = float(final_result.get("confidence", 0.65))
    coord_eval["overall_score"] = round(
        min(1.0, coord_eval["overall_score"] * 0.85 + synthesis_quality * 0.15), 3
    )

    all_phase_scores = [p.get("phase_score", 0.0) for p in all_phase_evals if p]
    pipeline_avg = round(sum(all_phase_scores) / max(len(all_phase_scores), 1), 3) if all_phase_scores else 0.65

    return {
        "phase":             4,
        "phase_name":        "Final Synthesis & Coordination",
        "phase_description": "Coordinator synthesizes all prior outputs. LLM judge verifies the final diagnosis is grounded and causally complete.",
        "agent_evaluations": [coord_eval],
        "phase_score":       coord_eval["overall_score"],
        "agents_passed":     1 if "PASS" in coord_eval["verdict"] else 0,
        "agents_total":      1,
        "phase_verdict":     "PASS ✅" if coord_eval["overall_score"] >= 0.70 else ("PARTIAL ⚠️" if coord_eval["overall_score"] >= 0.55 else "FAIL ❌"),
        "pipeline_average_score": pipeline_avg,
        "final_confidence":       synthesis_quality,
        "all_phases_summary": [
            {"phase": p.get("phase"), "name": p.get("phase_name"),
             "score": p.get("phase_score"), "verdict": p.get("phase_verdict")}
            for p in all_phase_evals
        ],
    }


# ---------------------------------------------------------------------------
# Pipeline-level summary
# ---------------------------------------------------------------------------

def build_pipeline_test_summary(phase_results: List[Dict]) -> Dict[str, Any]:
    """Aggregate all 4 phase results into a top-level pipeline test report."""
    scores = [p.get("phase_score", 0.0) for p in phase_results]
    pipeline_score = round(sum(scores) / max(len(scores), 1), 3)

    total_agents  = sum(p.get("agents_total",  0) for p in phase_results)
    agents_passed = sum(p.get("agents_passed", 0) for p in phase_results)

    all_evals: List[Dict] = []
    for p in phase_results:
        all_evals.extend(p.get("agent_evaluations", []))

    best_agent  = max(all_evals, key=lambda e: e["overall_score"])  if all_evals else {}
    worst_agent = min(all_evals, key=lambda e: e["overall_score"]) if all_evals else {}

    if pipeline_score >= 0.75:
        overall_verdict = "PIPELINE PASSED ✅"
        verdict_color   = "green"
    elif pipeline_score >= 0.58:
        overall_verdict = "PIPELINE PARTIAL ⚠️"
        verdict_color   = "yellow"
    else:
        overall_verdict = "PIPELINE FAILED ❌"
        verdict_color   = "red"

    # Aggregate hallucination across all agents
    avg_hallucination = round(
        sum(e.get("hallucination_rate", 0.0) for e in all_evals) / max(len(all_evals), 1), 3
    )

    return {
        "pipeline_score":        pipeline_score,
        "overall_verdict":       overall_verdict,
        "verdict_color":         verdict_color,
        "total_agents_tested":   total_agents,
        "agents_passed":         agents_passed,
        "best_agent":            best_agent.get("agent_name", "N/A"),
        "best_agent_score":      best_agent.get("overall_score", 0.0),
        "worst_agent":           worst_agent.get("agent_name", "N/A"),
        "worst_agent_score":     worst_agent.get("overall_score", 0.0),
        "avg_hallucination_rate": avg_hallucination,
        "evaluation_method":     "LLM-as-a-Judge (ground-truth context grounding)",
        "phase_summaries": [
            {
                "phase":         p.get("phase"),
                "name":          p.get("phase_name"),
                "score":         p.get("phase_score"),
                "verdict":       p.get("phase_verdict"),
                "agents_passed": p.get("agents_passed"),
                "agents_total":  p.get("agents_total"),
            }
            for p in phase_results
        ],
    }
