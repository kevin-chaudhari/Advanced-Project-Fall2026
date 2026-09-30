"""
System Analysis Agent.

This agent performs an inline evaluation of the 6-agent pipeline by grounding
each persona's answer against retrieved RAG context and dataset-specific truth
signals that can be extracted from the retrieved documents.
"""

import json
import re
from collections import Counter
from statistics import mean
from typing import Any, Dict, List, Tuple

from agents.base_agent import BaseAgent
from utils.logger import setup_logger

logger = setup_logger(__name__)

STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "has",
    "have",
    "if",
    "in",
    "into",
    "is",
    "it",
    "its",
    "of",
    "on",
    "or",
    "that",
    "the",
    "their",
    "this",
    "to",
    "was",
    "were",
    "with",
}

CAUSAL_MARKERS = (
    "because",
    "therefore",
    "thus",
    "indicates",
    "suggests",
    "shows",
    "due to",
    "based on",
    "confirms",
    "supports",
    "rules out",
)

AGENT_KEYS = [
    "diagnostic_expert",
    "pattern_agent",
    "aggressive_agent",
    "verification",
    "ambiguity",
    "human_review_coordinator",
]

AGENT_NAMES = {
    "diagnostic_expert": "Diagnostic Expert",
    "pattern_agent": "Pattern Recognition Agent",
    "aggressive_agent": "Aggressive Decision Agent",
    "verification": "Verification Analyst",
    "ambiguity": "Ambiguity Detection Agent",
    "human_review_coordinator": "Human Review Coordinator",
}


class SystemAnalysisAgent(BaseAgent):
    """Grounded evaluator for the full pipeline."""

    @property
    def role(self) -> str:
        return "System Analysis Agent"

    @property
    def goal(self) -> str:
        return (
            "Evaluate the six-agent diagnostic pipeline against retrieved RAG "
            "context, extract dataset truth signals, score grounded reasoning, "
            "and return a structured system performance report."
        )

    def _system_message(self) -> str:
        return (
            "You are an elite AI evaluation specialist for mission-critical industrial diagnostic systems. "
            "Your job is to rigorously evaluate a 6-agent RAG diagnostic pipeline using ONLY the retrieved context "
            "as the ground truth — never rely on outside knowledge. "
            "Be thorough, precise, and uncompromising: score every metric accurately, identify every unsupported claim, "
            "and provide actionable insights. This evaluation will determine system reliability for industrial safety decisions. "
            "Respond with a single valid JSON object only — no prose, no markdown."
        )

    def build_prompt(self, question: str, context: str, extra: Dict) -> str:
        agent_payloads = extra.get("agent_payloads", [])
        ground_truth_signals = extra.get("ground_truth_signals", [])
        reference_conclusion = extra.get("reference_conclusion", "")

        agent_block = json.dumps(agent_payloads, indent=2)
        truth_block = json.dumps(ground_truth_signals, indent=2)
        final_result = json.dumps(extra.get("final_result", {}), indent=2)

        return f"""
ORIGINAL QUESTION: {question}

RETRIEVED CONTEXT:
{context[:5000]}

EXTRACTED GROUND-TRUTH-LIKE SIGNALS FROM RETRIEVED DOCS:
{truth_block}

REFERENCE CONCLUSION BUILT ONLY FROM RETRIEVED CONTEXT:
{reference_conclusion}

SIX AGENT OUTPUTS TO EVALUATE:
{agent_block}

FINAL COORDINATED RESULT:
{final_result}

TASK:
Perform INLINE EVALUATION using these signals:

1. RAG FAITHFULNESS
- Check whether claims in each agent's reasoning are supported by the retrieved context.
- faithfulness_score = supported_claims / total_claims

2. REASONING ANALYSIS
- Evaluate logical flow, missing steps, contradictions, and causal correctness.
- reasoning_score in [0, 1]

3. LLM SELF-CHECK
- Re-evaluate the query using ONLY the retrieved context.
- Compare the reference conclusion with the system's final answer.
- agreement_score in [0, 1]

4. HALLUCINATION DETECTION
- hallucination_rate = unsupported_claims / total_claims

5. EVIDENCE COVERAGE
- coverage_score = supported_steps / total_steps

6. FINAL CONFIDENCE RECALIBRATION
- confidence_final =
  0.4 * faithfulness_score +
  0.3 * reasoning_score +
  0.2 * agreement_score +
  0.1 * (1 - hallucination_rate)

Return ONLY valid JSON with this structure:
{{
  "reference_conclusion": "short independent conclusion using retrieved context only",
  "ground_truth_signals": [
    {{
      "document_rank": 1,
      "source": "afrb",
      "signal_type": "ground_truth_label",
      "signal": "Cooling System Failure"
    }}
  ],
  "per_agent_evaluations": [
    {{
      "agent_key": "diagnostic_expert",
      "agent_name": "Diagnostic Expert",
      "diagnosis": "agent answer",
      "reasoning_excerpt": "short reasoning summary",
      "supported_claims": 4,
      "total_claims": 5,
      "supported_steps": 3,
      "total_steps": 4,
      "faithfulness_score": 0.8,
      "reasoning_score": 0.75,
      "agreement_score": 0.7,
      "coverage_score": 0.75,
      "hallucination_rate": 0.2,
      "reliability_score": 0.76,
      "verdict": "Strong",
      "strengths": ["..."],
      "risks": ["..."],
      "supported_evidence": ["..."],
      "unsupported_claims": ["..."],
      "ground_truth_alignment": ["..."]
    }}
  ],
  "faithfulness_score": 0.0,
  "reasoning_score": 0.0,
  "agreement_score": 0.0,
  "coverage_score": 0.0,
  "hallucination_rate": 0.0,
  "confidence_final": 0.0,
  "final_verdict": "Reliable",
  "agent_reliability_insight": {{
    "consistency_summary": "Are agents consistent or conflicting?",
    "strongest_agent": "agent name",
    "strongest_reasoning": "why it is strongest",
    "conflicting_agents": ["agent A", "agent B"]
  }},
  "enhanced_output": {{
    "final_answer": "direct answer",
    "final_diagnosis": "final diagnosis",
    "reasoning": ["step 1", "step 2"],
    "supporting_evidence": ["evidence 1", "evidence 2"]
  }}
}}

RULES:
- Evaluate ALL 6 agents individually. Missing evaluations = invalid response.
- Keep ALL numeric scores strictly in [0.0, 1.0].
- final_verdict must be exactly one of: Reliable, Moderately Reliable, Low Reliability.
- Base agreement_score on comparing the final coordinated answer vs. the reference conclusion.
- Do NOT invent evidence — ground every judgment in retrieved context only.
- Be RIGOROUS: if a claim is not traceable to the retrieved context, mark it as unsupported.
- Provide detailed, specific strengths and risks for each agent — not generic phrases.
- Your enhanced_output should synthesize the best available evidence into a clear, operator-ready answer.
"""

    def _clip(self, value: Any) -> float:
        try:
            return max(0.0, min(1.0, float(value)))
        except Exception:
            return 0.0

    def _normalise(self, text: Any) -> str:
        return re.sub(r"\s+", " ", str(text or "").strip()).lower()

    def _tokenise(self, text: Any) -> List[str]:
        return [
            token
            for token in re.findall(r"[a-z0-9]+", self._normalise(text))
            if token not in STOPWORDS and len(token) > 1
        ]

    def _safe_list(self, value: Any) -> List[str]:
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        if isinstance(value, str) and value.strip():
            return [value.strip()]
        return []

    def _split_claims(self, text: str) -> List[str]:
        if not text:
            return []
        pieces = re.split(r"(?<=[.!?])\s+|\n+", text)
        claims = []
        for piece in pieces:
            cleaned = re.sub(r"^[\-\*\d\.\)\s]+", "", piece).strip()
            if len(cleaned) >= 18:
                claims.append(cleaned)
        return claims[:8]

    def _parse_doc_fields(self, content: str) -> Dict[str, str]:
        fields: Dict[str, str] = {}
        for line in str(content or "").splitlines():
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            norm_key = re.sub(r"[^a-z0-9]+", "_", key.lower()).strip("_")
            fields[norm_key] = value.strip()
        return fields

    def _extract_ground_truth_signals(self, retrieved_docs: List[Dict]) -> List[Dict[str, Any]]:
        signals: List[Dict[str, Any]] = []
        seen: set[Tuple[int, str, str]] = set()

        for rank, doc in enumerate(retrieved_docs, 1):
            metadata = doc.get("metadata", {}) or {}
            source = str(metadata.get("source", "rag"))
            fields = self._parse_doc_fields(doc.get("content", ""))

            def add_signal(signal_type: str, signal: str) -> None:
                signal = str(signal or "").strip()
                key = (rank, signal_type, signal.lower())
                if not signal or key in seen:
                    return
                seen.add(key)
                signals.append(
                    {
                        "document_rank": rank,
                        "source": source,
                        "signal_type": signal_type,
                        "signal": signal,
                    }
                )

            failure_mode = fields.get("failure_mode") or metadata.get("failure_mode")
            if failure_mode:
                add_signal("failure_mode", failure_mode)

            failure_event = fields.get("failure_event") or metadata.get("failure_event")
            if failure_event:
                add_signal("failure_event", failure_event)

            correct_sensors = (
                fields.get("relevant_sensors_correct")
                or fields.get("relevant_sensors")
                or metadata.get("correct_sensors")
            )
            if correct_sensors:
                add_signal("correct_sensors", correct_sensors)

            option_map = {
                "A": fields.get("option_a", ""),
                "B": fields.get("option_b", ""),
                "C": fields.get("option_c", ""),
                "D": fields.get("option_d", ""),
                "E": fields.get("option_e", ""),
            }
            correct_answer_key = fields.get("correct_answer", "").upper()
            correct_answer_value = option_map.get(correct_answer_key) or fields.get("correct_answer", "")
            if correct_answer_value:
                add_signal("ground_truth_label", correct_answer_value)

            correct_reasoning = fields.get("correct_answer_reasoning")
            if correct_reasoning:
                add_signal("ground_truth_reasoning", correct_reasoning)

            human_review = fields.get("human_intervention_recommended")
            if human_review:
                add_signal("human_intervention_recommended", human_review)

        return signals

    def _derive_reference_conclusion(
        self,
        question: str,
        retrieved_docs: List[Dict],
        ground_truth_signals: List[Dict[str, Any]],
    ) -> str:
        label_counter = Counter(
            signal["signal"]
            for signal in ground_truth_signals
            if signal.get("signal_type") in {"ground_truth_label", "failure_mode"}
        )
        if label_counter:
            label, _ = label_counter.most_common(1)[0]
            reason = next(
                (
                    signal["signal"]
                    for signal in ground_truth_signals
                    if signal.get("signal_type") == "ground_truth_reasoning"
                ),
                "",
            )
            return (
                f"The retrieved context most strongly supports '{label}'. {reason}".strip()
            )

        event_counter = Counter(
            signal["signal"]
            for signal in ground_truth_signals
            if signal.get("signal_type") == "failure_event"
        )
        sensor_counter = Counter(
            signal["signal"]
            for signal in ground_truth_signals
            if signal.get("signal_type") == "correct_sensors"
        )
        if event_counter or sensor_counter:
            event = event_counter.most_common(1)[0][0] if event_counter else "the retrieved failure event"
            sensors = sensor_counter.most_common(1)[0][0] if sensor_counter else "the listed relevant sensors"
            return (
                f"For '{event}', the retrieved context points to the relevant sensors or signals: {sensors}."
            )

        if retrieved_docs:
            top_doc = self._parse_doc_fields(retrieved_docs[0].get("content", ""))
            equipment = top_doc.get("equipment") or top_doc.get("system_context") or "the retrieved asset"
            return f"The top retrieved document for {equipment} should be treated as the primary context reference."

        return f"No strong reference conclusion could be derived for: {question}"

    def _text_similarity(self, left: str, right: str) -> float:
        left_tokens = set(self._tokenise(left))
        right_tokens = set(self._tokenise(right))
        if not left_tokens or not right_tokens:
            return 0.0
        overlap = len(left_tokens & right_tokens)
        union = len(left_tokens | right_tokens)
        return overlap / union if union else 0.0

    def _claim_supported(self, claim: str, evidence_text: str) -> bool:
        claim_tokens = self._tokenise(claim)
        if not claim_tokens:
            return False

        evidence_tokens = set(self._tokenise(evidence_text))
        overlap = sum(1 for token in claim_tokens if token in evidence_tokens)
        overlap_ratio = overlap / max(len(claim_tokens), 1)

        numeric_tokens = re.findall(r"\d+(?:\.\d+)?", claim)
        numeric_supported = all(token in evidence_text for token in numeric_tokens) if numeric_tokens else True

        phrase_supported = self._normalise(claim) in self._normalise(evidence_text)
        return numeric_supported and (phrase_supported or overlap_ratio >= 0.34 or overlap >= 3)

    def _reasoning_score(self, reasoning_text: str, claims: List[str], unsupported_count: int) -> float:
        if not reasoning_text:
            return 0.25

        score = 0.45
        if len(claims) >= 3:
            score += 0.15
        if any(marker in self._normalise(reasoning_text) for marker in CAUSAL_MARKERS):
            score += 0.15
        if re.search(r"\d", reasoning_text):
            score += 0.1
        if unsupported_count == 0:
            score += 0.1
        elif unsupported_count >= max(2, len(claims) // 2):
            score -= 0.15
        return self._clip(score)

    def _matched_signals(self, text: str, ground_truth_signals: List[Dict[str, Any]]) -> List[str]:
        matches = []
        for signal in ground_truth_signals:
            if self._text_similarity(text, signal.get("signal", "")) >= 0.2:
                matches.append(signal["signal"])
        deduped = []
        for item in matches:
            if item not in deduped:
                deduped.append(item)
        return deduped[:3]

    def _build_agent_payloads(self, final_result: Dict[str, Any], extra: Dict) -> List[Dict[str, Any]]:
        payloads: List[Dict[str, Any]] = []

        def add_payload(agent_key: str, result: Dict[str, Any], diagnosis_keys: List[str], reasoning_keys: List[str]) -> None:
            diagnosis = next((result.get(key) for key in diagnosis_keys if result.get(key)), "")
            reasoning_parts: List[str] = []
            for key in reasoning_keys:
                value = result.get(key)
                if isinstance(value, list):
                    reasoning_parts.extend(self._safe_list(value))
                elif value:
                    reasoning_parts.append(str(value))
            payloads.append(
                {
                    "agent_key": agent_key,
                    "agent_name": AGENT_NAMES[agent_key],
                    "diagnosis": str(diagnosis or ""),
                    "reasoning_text": " ".join(reasoning_parts).strip(),
                    "reasoning_steps": self._safe_list(result.get("reasoning", [])),
                    "key_findings": self._safe_list(result.get("key_findings", [])),
                }
            )

        add_payload(
            "diagnostic_expert",
            extra.get("diagnostic_expert", {}),
            ["primary_hypothesis", "diagnosis"],
            ["analysis", "reasoning_detail", "reasoning"],
        )
        add_payload(
            "pattern_agent",
            extra.get("pattern_agent", {}),
            ["dominant_failure_signature", "diagnosis"],
            ["reasoning", "trend_analysis", "reasoning_detail"],
        )
        add_payload(
            "aggressive_agent",
            extra.get("aggressive_agent", {}),
            ["decision", "diagnosis"],
            ["reasoning", "reasoning_detail", "immediate_action"],
        )
        add_payload(
            "verification",
            extra.get("verification", {}),
            ["verified_diagnosis", "diagnosis"],
            ["reasoning", "reasoning_detail"],
        )
        add_payload(
            "ambiguity",
            extra.get("ambiguity", {}),
            ["ambiguity_summary", "diagnosis"],
            ["reasoning", "ambiguity_summary", "reasoning_detail"],
        )
        add_payload(
            "human_review_coordinator",
            final_result,
            ["final_diagnosis", "direct_answer", "diagnosis"],
            ["reasoning_detail", "direct_answer"],
        )
        payloads[-1]["reasoning_steps"] = self._safe_list(final_result.get("reasoning", []))
        payloads[-1]["key_findings"] = self._safe_list(final_result.get("key_findings", []))

        return payloads

    def _evaluate_agent(
        self,
        payload: Dict[str, Any],
        reference_conclusion: str,
        evidence_text: str,
        ground_truth_signals: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        diagnosis = payload.get("diagnosis", "")
        reasoning_text = payload.get("reasoning_text", "")
        findings = payload.get("key_findings", [])
        step_claims = payload.get("reasoning_steps", [])

        claim_pool = self._split_claims(" ".join([diagnosis, reasoning_text, *findings]))
        step_pool = step_claims or self._split_claims(reasoning_text)

        supported_claims = [claim for claim in claim_pool if self._claim_supported(claim, evidence_text)]
        unsupported_claims = [claim for claim in claim_pool if claim not in supported_claims]
        supported_steps = [step for step in step_pool if self._claim_supported(step, evidence_text)]

        total_claims = max(len(claim_pool), 1)
        total_steps = max(len(step_pool), 1)
        faithfulness_score = len(supported_claims) / total_claims
        coverage_score = len(supported_steps) / total_steps
        agreement_score = max(
            self._text_similarity(diagnosis, reference_conclusion),
            self._text_similarity(reasoning_text, reference_conclusion),
        )
        hallucination_rate = len(unsupported_claims) / total_claims
        reasoning_score = self._reasoning_score(reasoning_text, claim_pool, len(unsupported_claims))
        reliability_score = self._clip(
            0.4 * faithfulness_score
            + 0.3 * reasoning_score
            + 0.2 * agreement_score
            + 0.1 * (1 - hallucination_rate)
        )

        if reliability_score >= 0.75:
            verdict = "Strong"
        elif reliability_score >= 0.55:
            verdict = "Mixed"
        else:
            verdict = "Weak"

        strengths = []
        if faithfulness_score >= 0.7:
            strengths.append("Most major claims are grounded in retrieved context.")
        if reasoning_score >= 0.7:
            strengths.append("Reasoning flow is coherent and causally structured.")
        if agreement_score >= 0.65:
            strengths.append("Answer aligns closely with the context-only reference conclusion.")
        if not strengths:
            strengths.append("Provides at least a partially usable signal for synthesis.")

        risks = []
        if hallucination_rate > 0.25:
            risks.append("Several claims are not clearly supported by retrieved evidence.")
        if coverage_score < 0.5:
            risks.append("Important reasoning steps are insufficiently grounded.")
        if agreement_score < 0.45:
            risks.append("Conclusion diverges from the context-only reference answer.")
        if not risks:
            risks.append("Residual risk remains because agreement is not perfect.")

        ground_truth_alignment = self._matched_signals(" ".join([diagnosis, reasoning_text]), ground_truth_signals)
        supported_evidence = self._matched_signals(" ".join(supported_claims), ground_truth_signals)

        return {
            "agent_key": payload.get("agent_key", ""),
            "agent_name": payload.get("agent_name", ""),
            "diagnosis": diagnosis,
            "reasoning_excerpt": reasoning_text[:320],
            "supported_claims": len(supported_claims),
            "total_claims": total_claims,
            "supported_steps": len(supported_steps),
            "total_steps": total_steps,
            "faithfulness_score": round(faithfulness_score, 3),
            "reasoning_score": round(reasoning_score, 3),
            "agreement_score": round(agreement_score, 3),
            "coverage_score": round(coverage_score, 3),
            "hallucination_rate": round(hallucination_rate, 3),
            "reliability_score": round(reliability_score, 3),
            "verdict": verdict,
            "strengths": strengths[:3],
            "risks": risks[:3],
            "supported_evidence": supported_evidence[:3],
            "unsupported_claims": unsupported_claims[:3],
            "ground_truth_alignment": ground_truth_alignment[:3],
        }

    def _build_inline_evaluation(
        self,
        question: str,
        retrieved_docs: List[Dict],
        final_result: Dict[str, Any],
        extra: Dict,
    ) -> Dict[str, Any]:
        ground_truth_signals = self._extract_ground_truth_signals(retrieved_docs)
        reference_conclusion = self._derive_reference_conclusion(
            question,
            retrieved_docs,
            ground_truth_signals,
        )
        evidence_text = "\n".join(doc.get("content", "") for doc in retrieved_docs)
        payloads = self._build_agent_payloads(final_result, extra)

        per_agent = [
            self._evaluate_agent(payload, reference_conclusion, evidence_text, ground_truth_signals)
            for payload in payloads
        ]

        total_claims = max(sum(item["total_claims"] for item in per_agent), 1)
        total_supported_claims = sum(item["supported_claims"] for item in per_agent)
        total_steps = max(sum(item["total_steps"] for item in per_agent), 1)
        total_supported_steps = sum(item["supported_steps"] for item in per_agent)

        faithfulness_score = total_supported_claims / total_claims
        reasoning_score = mean(item["reasoning_score"] for item in per_agent) if per_agent else 0.0

        final_agent = next(
            (item for item in per_agent if item["agent_key"] == "human_review_coordinator"),
            per_agent[-1] if per_agent else {},
        )
        agreement_score = float(final_agent.get("agreement_score", 0.0))
        coverage_score = total_supported_steps / total_steps
        hallucination_rate = (total_claims - total_supported_claims) / total_claims
        confidence_final = self._clip(
            0.4 * faithfulness_score
            + 0.3 * reasoning_score
            + 0.2 * agreement_score
            + 0.1 * (1 - hallucination_rate)
        )

        if confidence_final >= 0.75:
            final_verdict = "Reliable"
        elif confidence_final >= 0.55:
            final_verdict = "Moderately Reliable"
        else:
            final_verdict = "Low Reliability"

        strongest = max(per_agent, key=lambda item: item["reliability_score"]) if per_agent else None
        conflicting_agents = [
            item["agent_name"]
            for item in per_agent
            if item["agreement_score"] < 0.45 and item["agent_key"] != "human_review_coordinator"
        ]

        aligned = sum(1 for item in per_agent if item["agreement_score"] >= 0.55)
        consistency_summary = (
            f"{aligned} of {len(per_agent)} agents align well with the context-only reference conclusion."
            if per_agent
            else "No agent evaluations available."
        )

        return {
            "reference_conclusion": reference_conclusion,
            "ground_truth_signals": ground_truth_signals,
            "per_agent_evaluations": per_agent,
            "faithfulness_score": round(faithfulness_score, 3),
            "reasoning_score": round(reasoning_score, 3),
            "agreement_score": round(agreement_score, 3),
            "coverage_score": round(coverage_score, 3),
            "hallucination_rate": round(hallucination_rate, 3),
            "confidence_final": round(confidence_final, 3),
            "final_verdict": final_verdict,
            "agent_reliability_insight": {
                "consistency_summary": consistency_summary,
                "strongest_agent": strongest["agent_name"] if strongest else "",
                "strongest_reasoning": (
                    strongest["reasoning_excerpt"] if strongest and strongest.get("reasoning_excerpt") else ""
                ),
                "conflicting_agents": conflicting_agents[:3],
            },
            "enhanced_output": {
                "final_answer": final_result.get("direct_answer", final_result.get("final_diagnosis", "")),
                "final_diagnosis": final_result.get("final_diagnosis", ""),
                "reasoning": self._safe_list(final_result.get("reasoning", []))[:6],
                "supporting_evidence": self._safe_list(final_result.get("supporting_evidence", []))[:5],
            },
        }

    def _normalise_inline_result(
        self,
        inline_eval: Dict[str, Any],
        deterministic: Dict[str, Any],
    ) -> Dict[str, Any]:
        base = json.loads(json.dumps(deterministic))

        base["reference_conclusion"] = inline_eval.get(
            "reference_conclusion",
            base["reference_conclusion"],
        )
        base["final_verdict"] = inline_eval.get("final_verdict", base["final_verdict"])

        for key in [
            "faithfulness_score",
            "reasoning_score",
            "agreement_score",
            "coverage_score",
            "hallucination_rate",
            "confidence_final",
        ]:
            base[key] = round(self._clip(inline_eval.get(key, base[key])), 3)

        raw_signals = inline_eval.get("ground_truth_signals", [])
        normalised_signals = []
        if isinstance(raw_signals, list):
            for index, signal in enumerate(raw_signals, 1):
                if isinstance(signal, dict):
                    normalised_signals.append(
                        {
                            "document_rank": int(signal.get("document_rank", index)),
                            "source": str(signal.get("source", "rag")),
                            "signal_type": str(signal.get("signal_type", "retrieved_context")),
                            "signal": str(signal.get("signal", "")).strip(),
                        }
                    )
                elif str(signal).strip():
                    normalised_signals.append(
                        {
                            "document_rank": index,
                            "source": "rag",
                            "signal_type": "retrieved_context",
                            "signal": str(signal).strip(),
                        }
                    )
        if normalised_signals:
            base["ground_truth_signals"] = normalised_signals

        default_agent_map = {
            item["agent_key"]: item for item in base.get("per_agent_evaluations", [])
        }
        raw_agents = inline_eval.get("per_agent_evaluations", [])
        normalised_agents = []
        if isinstance(raw_agents, list):
            for idx, raw_agent in enumerate(raw_agents):
                if not isinstance(raw_agent, dict):
                    continue
                agent_key = str(raw_agent.get("agent_key", AGENT_KEYS[min(idx, len(AGENT_KEYS) - 1)]))
                seed = default_agent_map.get(agent_key, {})
                normalised_agents.append(
                    {
                        "agent_key": agent_key,
                        "agent_name": str(raw_agent.get("agent_name", seed.get("agent_name", AGENT_NAMES.get(agent_key, agent_key)))),
                        "diagnosis": str(raw_agent.get("diagnosis", seed.get("diagnosis", ""))),
                        "reasoning_excerpt": str(raw_agent.get("reasoning_excerpt", seed.get("reasoning_excerpt", "")))[:320],
                        "supported_claims": int(raw_agent.get("supported_claims", seed.get("supported_claims", 0))),
                        "total_claims": max(1, int(raw_agent.get("total_claims", seed.get("total_claims", 1)))),
                        "supported_steps": int(raw_agent.get("supported_steps", seed.get("supported_steps", 0))),
                        "total_steps": max(1, int(raw_agent.get("total_steps", seed.get("total_steps", 1)))),
                        "faithfulness_score": round(self._clip(raw_agent.get("faithfulness_score", seed.get("faithfulness_score", 0.0))), 3),
                        "reasoning_score": round(self._clip(raw_agent.get("reasoning_score", seed.get("reasoning_score", 0.0))), 3),
                        "agreement_score": round(self._clip(raw_agent.get("agreement_score", seed.get("agreement_score", 0.0))), 3),
                        "coverage_score": round(self._clip(raw_agent.get("coverage_score", seed.get("coverage_score", 0.0))), 3),
                        "hallucination_rate": round(self._clip(raw_agent.get("hallucination_rate", seed.get("hallucination_rate", 0.0))), 3),
                        "reliability_score": round(self._clip(raw_agent.get("reliability_score", seed.get("reliability_score", 0.0))), 3),
                        "verdict": str(raw_agent.get("verdict", seed.get("verdict", "unknown"))),
                        "strengths": self._safe_list(raw_agent.get("strengths", seed.get("strengths", [])))[:3],
                        "risks": self._safe_list(raw_agent.get("risks", seed.get("risks", [])))[:3],
                        "supported_evidence": self._safe_list(raw_agent.get("supported_evidence", seed.get("supported_evidence", [])))[:3],
                        "unsupported_claims": self._safe_list(raw_agent.get("unsupported_claims", seed.get("unsupported_claims", [])))[:3],
                        "ground_truth_alignment": self._safe_list(raw_agent.get("ground_truth_alignment", seed.get("ground_truth_alignment", [])))[:3],
                    }
                )
        if len(normalised_agents) == len(AGENT_KEYS):
            base["per_agent_evaluations"] = normalised_agents

        insight = inline_eval.get("agent_reliability_insight", {})
        if isinstance(insight, dict):
            base["agent_reliability_insight"] = {
                "consistency_summary": str(
                    insight.get(
                        "consistency_summary",
                        base["agent_reliability_insight"]["consistency_summary"],
                    )
                ),
                "strongest_agent": str(
                    insight.get(
                        "strongest_agent",
                        base["agent_reliability_insight"]["strongest_agent"],
                    )
                ),
                "strongest_reasoning": str(
                    insight.get(
                        "strongest_reasoning",
                        base["agent_reliability_insight"]["strongest_reasoning"],
                    )
                ),
                "conflicting_agents": self._safe_list(
                    insight.get(
                        "conflicting_agents",
                        base["agent_reliability_insight"]["conflicting_agents"],
                    )
                )[:3],
            }

        enhanced = inline_eval.get("enhanced_output", {})
        if isinstance(enhanced, dict):
            base["enhanced_output"] = {
                "final_answer": str(
                    enhanced.get("final_answer", base["enhanced_output"]["final_answer"])
                ),
                "final_diagnosis": str(
                    enhanced.get(
                        "final_diagnosis",
                        base["enhanced_output"]["final_diagnosis"],
                    )
                ),
                "reasoning": self._safe_list(
                    enhanced.get("reasoning", base["enhanced_output"]["reasoning"])
                )[:6],
                "supporting_evidence": self._safe_list(
                    enhanced.get(
                        "supporting_evidence",
                        base["enhanced_output"]["supporting_evidence"],
                    )
                )[:5],
            }

        return base

    def _compose_report(
        self,
        retrieved_docs: List[Dict],
        final_result: Dict[str, Any],
        inline_eval: Dict[str, Any],
        latency_ms: float,
    ) -> Dict[str, Any]:
        doc_scores = [float(doc.get("score", 0.0)) for doc in retrieved_docs]
        avg_doc_score = mean(doc_scores) if doc_scores else 0.0
        truth_signal_count = len(inline_eval.get("ground_truth_signals", []))
        retrieval_coverage = self._clip(
            0.6 * inline_eval.get("coverage_score", 0.0)
            + 0.4 * min(1.0, truth_signal_count / max(len(retrieved_docs) * 2, 1))
        )
        retrieval_efficiency = self._clip(
            0.55 * avg_doc_score + 0.45 * retrieval_coverage
        )

        agent_map = {
            item["agent_key"]: item for item in inline_eval.get("per_agent_evaluations", [])
        }
        final_agent = agent_map.get("human_review_coordinator", {})

        correctness = self._clip(
            0.55 * final_agent.get("faithfulness_score", inline_eval.get("faithfulness_score", 0.0))
            + 0.45 * inline_eval.get("agreement_score", 0.0)
        )
        logical_consistency = self._clip(
            final_agent.get("reasoning_score", inline_eval.get("reasoning_score", 0.0))
        )
        evidence_support = self._clip(
            final_agent.get("coverage_score", inline_eval.get("coverage_score", 0.0))
        )
        explainability = self._clip((logical_consistency + evidence_support) / 2)

        hallucination_rate = inline_eval.get("hallucination_rate", 0.0)
        hallucination_detected = hallucination_rate >= 0.18 or any(
            item.get("hallucination_rate", 0.0) >= 0.4
            for item in inline_eval.get("per_agent_evaluations", [])
        )

        previous_confidence = self._clip(final_result.get("confidence", 0.0))
        confidence_final = self._clip(inline_eval.get("confidence_final", 0.0))
        calibration_error = round(abs(previous_confidence - confidence_final), 3)

        quality_anchor = mean(
            [
                confidence_final,
                inline_eval.get("reasoning_score", 0.0),
                inline_eval.get("coverage_score", 0.0),
            ]
        )
        if latency_ms <= 3000:
            efficiency_score = self._clip(quality_anchor + 0.12)
        elif latency_ms <= 8000:
            efficiency_score = self._clip(quality_anchor)
        else:
            efficiency_score = self._clip(quality_anchor - 0.12)

        overall_score = self._clip(
            mean(
                [
                    retrieval_efficiency,
                    confidence_final,
                    correctness,
                    logical_consistency,
                    1 - hallucination_rate,
                    efficiency_score,
                ]
            )
        )
        risk_level = "low" if overall_score >= 0.75 else "medium" if overall_score >= 0.55 else "high"

        insights = []
        if inline_eval.get("faithfulness_score", 0.0) < 0.7:
            insights.append("Some agent claims are only partially supported by the retrieved context.")
        if inline_eval.get("agreement_score", 0.0) < 0.6:
            insights.append("The final coordinated answer does not fully align with the context-only reference conclusion.")
        if hallucination_rate > 0.2:
            insights.append("Hallucination risk is elevated because several claims cannot be traced back to retrieved evidence.")
        conflicting = inline_eval.get("agent_reliability_insight", {}).get("conflicting_agents", [])
        if conflicting:
            insights.append(f"Conflicting reasoning detected in: {', '.join(conflicting)}.")
        if not insights:
            insights.append("The six-agent pipeline is broadly aligned with the retrieved evidence.")

        recommendations = []
        if inline_eval.get("coverage_score", 0.0) < 0.65:
            recommendations.append("Expand or sharpen retrieval so more reasoning steps can be tied directly to context.")
        if inline_eval.get("agreement_score", 0.0) < 0.6:
            recommendations.append("Add a stricter final-verification pass that compares the coordinator output against the context-only reference answer.")
        if hallucination_rate > 0.2:
            recommendations.append("Add claim-level grounding checks before returning final reasoning to the UI.")
        if not recommendations:
            recommendations.append("Keep monitoring per-agent reliability and recalibrated confidence across saved analyses.")

        return {
            "retrieval": {
                "relevance_score": round(self._clip(avg_doc_score), 3),
                "coverage_score": round(retrieval_coverage, 3),
                "retrieval_efficiency": round(retrieval_efficiency, 3),
            },
            "agents": {
                "diagnostic_expert": round(agent_map.get("diagnostic_expert", {}).get("reliability_score", 0.0), 3),
                "pattern_agent": round(agent_map.get("pattern_agent", {}).get("reliability_score", 0.0), 3),
                "aggressive_agent": round(agent_map.get("aggressive_agent", {}).get("reliability_score", 0.0), 3),
                "verification": round(agent_map.get("verification", {}).get("reliability_score", 0.0), 3),
                "ambiguity": round(agent_map.get("ambiguity", {}).get("reliability_score", 0.0), 3),
                "final_coordinator": round(agent_map.get("human_review_coordinator", {}).get("reliability_score", 0.0), 3),
                "agreement_score": round(self._clip(inline_eval.get("agreement_score", 0.0)), 3),
            },
            "final": {
                "correctness": round(correctness, 3),
                "logical_consistency": round(logical_consistency, 3),
                "explainability": round(explainability, 3),
                "evidence_support": round(evidence_support, 3),
            },
            "hallucination": {
                "detected": hallucination_detected,
                "severity": round(self._clip(hallucination_rate), 3),
            },
            "confidence": {
                "confidence_score": round(confidence_final, 3),
                "calibration_error": calibration_error,
            },
            "system": {
                "latency_ms": round(latency_ms, 1),
                "efficiency_score": round(efficiency_score, 3),
            },
            "aggregated": {
                "overall_score": round(overall_score, 3),
                "risk_level": risk_level,
            },
            "insights": insights[:4],
            "recommendations": recommendations[:4],
            "inline_evaluation": inline_eval,
        }

    def deterministic_report(self, question: str, retrieved_docs: List[Dict], extra: Dict) -> Dict[str, Any]:
        """Instant, LLM-free meta-evaluation used by the harness."""
        final_result = extra.get("final_result", {})
        inline = self._build_inline_evaluation(question, retrieved_docs, final_result, extra)
        return self._compose_report(retrieved_docs, final_result, inline, float(extra.get("latency_ms", 0.0)))

    async def run(  # type: ignore[override]
        self,
        question: str,
        context: str,
        extra: Dict = None,
    ) -> Dict[str, Any]:
        extra = extra or {}
        retrieved_docs = extra.get("retrieved_docs", [])
        final_result = extra.get("final_result", {})
        latency_ms = float(extra.get("latency_ms", 0.0))

        # Always build the deterministic baseline first (instant, no API cost)
        deterministic_inline = self._build_inline_evaluation(
            question,
            retrieved_docs,
            final_result,
            extra,
        )
        deterministic_report = self._compose_report(
            retrieved_docs,
            final_result,
            deterministic_inline,
            latency_ms,
        )

        import os
        if os.getenv("SYSTEM_ANALYSIS_LLM", "false").lower() not in ("1", "true", "yes"):
            return deterministic_report

        # ── Vigorous OpenAI Evaluation (opt-in: SYSTEM_ANALYSIS_LLM=true) ──
        # Use a high token budget so the LLM can evaluate all 6 agents deeply.
        # The deterministic report is ONLY the fallback if OpenAI is unavailable.
        try:
            prompt = self.build_prompt(
                question,
                context,
                {
                    **extra,
                    "agent_payloads": self._build_agent_payloads(final_result, extra),
                    "ground_truth_signals": deterministic_inline["ground_truth_signals"],
                    "reference_conclusion": deterministic_inline["reference_conclusion"],
                },
            )

            # Override token budget for system analysis — needs room for 6 agent evals
            original_max_tokens = self.llm.openai_max_tokens
            self.llm.openai_max_tokens = 8192

            try:
                raw = await self.llm.generate(prompt, system=self._system_message())
            finally:
                self.llm.openai_max_tokens = original_max_tokens

            llm_inline = self.llm.extract_json(raw)

            required_keys = {
                "reference_conclusion",
                "ground_truth_signals",
                "per_agent_evaluations",
                "faithfulness_score",
                "reasoning_score",
                "agreement_score",
                "coverage_score",
                "hallucination_rate",
                "confidence_final",
                "final_verdict",
                "agent_reliability_insight",
                "enhanced_output",
            }
            if required_keys.issubset(llm_inline.keys()):
                merged_inline = self._normalise_inline_result(
                    llm_inline,
                    deterministic_inline,
                )
                logger.info("[SystemAnalysis] OpenAI vigorous evaluation complete — %d agent evals, verdict: %s.",
                            len(merged_inline.get('per_agent_evaluations', [])),
                            merged_inline.get('final_verdict', 'unknown'))
                return self._compose_report(
                    retrieved_docs,
                    final_result,
                    merged_inline,
                    latency_ms,
                )

            logger.warning(
                "[SystemAnalysis] OpenAI evaluation missing required keys (%s) — using deterministic fallback.",
                required_keys - llm_inline.keys(),
            )
            return deterministic_report

        except Exception as exc:
            logger.warning(
                "[SystemAnalysis] OpenAI evaluation failed (%s) — using deterministic fallback.",
                exc,
            )
            return deterministic_report
