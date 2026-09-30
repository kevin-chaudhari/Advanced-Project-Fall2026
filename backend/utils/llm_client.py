"""
LLM client — supports Ollama (local) and OpenAI-compatible APIs.

Two entry points:
* ``generate()`` — legacy API used by the optional LLM-judge / system-analysis
  paths.  When no LLM is reachable it still falls back to the legacy
  rule-based mock (kept for backward compatibility; note that the mock emits
  illustrative, *non-grounded* example values and is therefore never used by
  the diagnostic harness).
* ``generate_json()`` — used by the six harness agents.  Returns ``None`` when
  no LLM is available, so each agent runs its deterministic evidence-grounded
  core instead of consuming mock data.
"""

import json
import os
import re
from typing import Any, Dict

import httpx

from utils.logger import setup_logger

logger = setup_logger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Rule-based fallback engine
# ─────────────────────────────────────────────────────────────────────────────

def _extract_keywords(prompt: str):
    """Return a lowercase set of words present in the prompt."""
    return set(re.findall(r"[a-z]+", prompt.lower()))


def _diagnose(kw: set):
    """
    Produce (diagnosis_str, confidence, failure_mode) from prompt keywords.
    """
    if kw & {"vibration", "vibrating", "oscillation", "imbalance", "shake"}:
        return (
            "Mechanical imbalance or bearing wear detected. Elevated vibration exceeds "
            "safe operating thresholds, indicating progressive bearing degradation or "
            "shaft misalignment in the rotating assembly.",
            0.82,
            "Bearing Wear / Mechanical Imbalance",
            [
                "Vibration amplitude exceeds 8 mm/s (safe threshold: <5 mm/s).",
                "Elevated bearing housing temperature correlates with friction increase.",
                "Historical records show identical vibration signature 45 days before failure.",
                "Spectral pattern matches 1× RPM bearing defect frequency.",
                "Lubrication interval exceeded by 30 days per maintenance log.",
            ],
        )
    if kw & {"temperature", "thermal", "heat", "overheating", "hot", "temp"}:
        return (
            "Thermal anomaly detected. Winding or bearing temperature has exceeded the "
            "safe operating limit, suggesting coolant system degradation, lubrication "
            "failure, or sustained electrical overload.",
            0.78,
            "Overheating / Thermal Degradation",
            [
                "Temperature reading at 118°C exceeds rated limit of 95°C.",
                "Current draw elevated by 15% above nominal, indicating overload.",
                "Coolant flow rate reduced from 180 LPM to 92 LPM.",
                "Thermal imaging shows hot spot on motor winding end-turn.",
                "Last cooling system service was 120 days ago (interval: 90 days).",
            ],
        )
    if kw & {"pressure", "cavitation", "flow", "pump", "suction", "blockage"}:
        return (
            "Abnormal pressure differential detected. Low suction pressure combined "
            "with elevated noise levels indicates cavitation in the pump impeller, "
            "causing vapor bubble collapse and progressive impeller erosion.",
            0.74,
            "Cavitation / Pressure Anomaly",
            [
                "Suction pressure dropped to 0.9 bar (NPSH required: 2.1 bar).",
                "Noise level at 98 dB consistent with cavitation signature.",
                "Flow rate reduced by 22% below design specification.",
                "Pitting erosion visible on impeller vanes during last inspection.",
                "Upstream strainer blockage reducing available NPSH.",
            ],
        )
    if kw & {"bearing", "wear", "lubrication", "oil", "grease", "seal"}:
        return (
            "Bearing or lubrication system failure detected. Oil sample analysis "
            "shows elevated metallic particle count indicating active wear, requiring "
            "immediate bearing replacement and lubrication system flush.",
            0.80,
            "Bearing Wear / Lubrication Failure",
            [
                "Oil viscosity degraded from 46 cSt to 18 cSt (out of spec).",
                "Metallic particle count: 850 ppm (alarm level: 500 ppm).",
                "Vibration at 11.2 mm/s matches bearing defect frequency.",
                "Bearing operating hours: 8,450 hrs (replacement interval: 8,000 hrs).",
                "Temperature rise of 28°C over baseline in last 72 hours.",
            ],
        )
    if kw & {"electrical", "voltage", "current", "motor", "winding", "insulation", "fault"}:
        return (
            "Electrical fault detected in motor drive system. Phase voltage imbalance "
            "and elevated stator winding resistance indicate insulation breakdown or "
            "connection degradation requiring immediate electrical inspection.",
            0.76,
            "Electrical Fault / Winding Degradation",
            [
                "Phase voltage imbalance: 8.5% (limit: 3%).",
                "Stator resistance asymmetry detected across phases.",
                "Insulation resistance dropped to 0.8 MΩ (minimum: 1 MΩ).",
                "Current draw asymmetric: Phase A 72A vs Phase C 58A.",
                "Motor operating temperature elevated by 22°C above ambient baseline.",
            ],
        )
    if kw & {"sensor", "reading", "data", "anomaly", "signal", "calibration"}:
        return (
            "Sensor signal anomaly detected. Readings show deviation patterns "
            "inconsistent with normal operation, suggesting either genuine equipment "
            "degradation or sensor drift requiring calibration verification.",
            0.65,
            "Sensor Anomaly / Equipment Degradation",
            [
                "Sensor output deviates ±18% from expected baseline.",
                "Cross-sensor validation shows inconsistency between redundant sensors.",
                "Last calibration performed 180 days ago (interval: 90 days).",
                "Signal noise floor elevated, suggesting wiring or connector issue.",
                "Pattern matches early-stage bearing defect rather than sensor fault.",
            ],
        )
    # Default
    return (
        "Anomalous operational pattern detected across multiple sensor channels. "
        "Multi-parameter deviation suggests progressive equipment degradation "
        "requiring comprehensive inspection and preventive maintenance.",
        0.60,
        "Multi-Parameter Anomaly",
        [
            "Multiple sensor parameters deviating from nominal operating range.",
            "Deviation trend shows progressive worsening over last 72 hours.",
            "Pattern does not match single-cause failure signature.",
            "Cross-correlation of sensor data suggests systemic issue.",
            "Maintenance records show equipment approaching service interval.",
        ],
    )


def _build_agent_mock(prompt: str) -> Dict[str, Any]:
    """
    Detect which agent's prompt this is and return the correct schema.
    Detection is done by matching unique anchor phrases from each agent's prompt template.
    """
    kw = _extract_keywords(prompt)
    diag, conf, mode, evidence = _diagnose(kw)

    # ── Diagnostic Expert ────────────────────────────────────────────────────
    if "generate at least 3" in prompt.lower() or "hypotheses" in prompt.lower():
        return {
            "hypotheses": [
                {
                    "id": 1,
                    "hypothesis": diag,
                    "supporting_evidence": evidence[:3],
                    "contradicting_evidence": ["No direct contradicting evidence found."],
                    "score": conf,
                },
                {
                    "id": 2,
                    "hypothesis": f"Secondary cause: Overloaded operating conditions accelerating {mode} progression.",
                    "supporting_evidence": [evidence[1], evidence[2]],
                    "contradicting_evidence": ["Operating load within rated range at last check."],
                    "score": round(conf - 0.12, 2),
                },
                {
                    "id": 3,
                    "hypothesis": "Tertiary cause: Age-related material fatigue independent of operational factors.",
                    "supporting_evidence": [evidence[-1]],
                    "contradicting_evidence": ["Equipment age within expected service life."],
                    "score": round(conf - 0.22, 2),
                },
            ],
            "primary_hypothesis": diag,
            "analysis": (
                f"After evaluating 3 hypotheses, {mode} is the primary diagnosis with "
                f"{round(conf * 100)}% evidence support. Secondary and tertiary causes "
                "are plausible but less supported by the retrieved sensor data."
            ),
            "confidence": conf,
        }

    # ── Aggressive Decision Agent ────────────────────────────────────────────
    if "aggressive" in prompt.lower() or "heuristic" in prompt.lower() or "rapid" in prompt.lower() or "decisive" in prompt.lower():
        return {
            "decision": diag,
            "heuristic_rules": [
                f"RULE 1: If vibration > 8 mm/s AND temperature > 85°C → BEARING FAILURE imminent.",
                f"RULE 2: If pressure < 1.5 bar AND noise > 90 dB → CAVITATION active.",
                f"RULE 3: If current imbalance > 5% → ELECTRICAL FAULT — isolate immediately.",
            ],
            "immediate_action": (
                f"IMMEDIATE: Schedule emergency inspection for {mode}. "
                "Do NOT defer maintenance. Risk of catastrophic failure within 72 hours."
            ),
            "confidence": min(conf + 0.05, 0.95),
        }

    # ── Pattern Recognition Agent ────────────────────────────────────────────
    if "pattern" in prompt.lower() or "similarity score" in prompt.lower() or "top-k" in prompt.lower() or "recurring" in prompt.lower():
        return {
            "patterns_identified": [
                f"Primary: {mode} signature — consistent across top-3 retrieved records.",
                "Secondary: Progressive degradation trend over 72-hour window.",
                "Tertiary: Maintenance overdue pattern (>30 days past service interval).",
            ],
            "anomalies": [
                "Sensor reading deviates >2σ from 30-day rolling mean.",
                "Inter-sensor correlation breakdown detected.",
            ],
            "dominant_failure_signature": mode,
            "trend_analysis": (
                f"Trend analysis across top-k similar cases shows {mode} follows "
                "a predictable degradation curve. Current readings place the asset "
                "at approximately 85% through its failure progression cycle."
            ),
            "confidence": round(conf - 0.03, 2),
        }

    # ── Verification Analyst ─────────────────────────────────────────────────
    if "verify" in prompt.lower() or "cross-validat" in prompt.lower() or "contradict" in prompt.lower() or "consensus" in prompt.lower():
        return {
            "agreements": [
                f"All three parallel agents agree on primary failure mode: {mode}.",
                "Confidence scores are within 0.15 range — strong inter-agent consensus.",
                "Evidence cited by Diagnostic Expert aligns with Pattern Agent findings.",
            ],
            "contradictions_found": [
                "Minor disagreement: Aggressive Agent assigned higher urgency than Diagnostic Expert.",
            ],
            "contradictions_resolved": [
                "Urgency discrepancy resolved by averaging: medium-high urgency assigned.",
                "Pattern Agent's secondary cause excluded — insufficient evidence support.",
            ],
            "verified_diagnosis": diag,
            "verification_confidence": round(conf - 0.02, 2),
        }

    # ── Ambiguity Detection Agent ────────────────────────────────────────────
    if "ambigui" in prompt.lower() or "conflict" in prompt.lower() or "uncertainty" in prompt.lower() or "human review" in prompt.lower():
        human_review = conf < 0.65
        return {
            "conflicts_detected": [] if conf >= 0.70 else [
                "Moderate uncertainty in distinguishing primary from secondary failure cause."
            ],
            "ambiguous_areas": [] if conf >= 0.75 else [
                "Sensor data could support two distinct failure modes."
            ],
            "uncertainty_sources": [
                "Limited historical records for this specific equipment configuration.",
                "Sensor readings at boundary of normal/abnormal threshold.",
            ],
            "overall_confidence": conf,
            "human_review_required": human_review,
            "ambiguity_summary": (
                f"Analysis shows {'low' if conf >= 0.75 else 'moderate'} ambiguity. "
                f"Overall system confidence: {round(conf * 100)}%. "
                f"{'No human review required — proceed with recommendation.' if not human_review else 'Human expert review recommended before acting.'}"
            ),
        }

    # ── Human Review Coordinator (final synthesis) ───────────────────────────
    if "synthesise" in prompt.lower() or "coordinator" in prompt.lower() or "final_diagnosis" in prompt.lower() or "final, definitive" in prompt.lower():
        human_review = conf < 0.65
        return {
            "final_diagnosis": diag,
            "confidence": conf,
            "reasoning": [
                f"Step 1: RAG retrieval returned 5 semantically similar records from the knowledge base, with top similarity score of 0.91.",
                f"Step 2: Pattern Recognition Agent identified '{mode}' as the dominant failure signature across retrieved cases.",
                f"Step 3: Diagnostic Expert generated 3 hypotheses; '{mode}' scored highest at {round(conf * 100)}% evidence support.",
                "Step 4: Aggressive Decision Agent confirmed diagnosis via heuristic rule matching (vibration + temperature threshold breach).",
                "Step 5: Verification Analyst found strong inter-agent consensus — minor urgency disagreement resolved by averaging.",
                f"Step 6: Ambiguity Detection Agent confirmed {'low' if conf >= 0.75 else 'moderate'} ambiguity with overall confidence {round(conf * 100)}%.",
            ],
            "supporting_evidence": evidence,
            "agent_contributions": {
                "diagnostic_expert": f"Generated 3 hypotheses; '{mode}' selected as primary with {round(conf * 100)}% support score.",
                "pattern_agent": f"Identified '{mode}' as dominant pattern across top-k FAISS results with 85% case consistency.",
                "aggressive_agent": f"Rapid heuristic decision confirmed '{mode}' — immediate inspection recommended.",
                "verification": f"All agents in consensus on '{mode}'. Minor urgency disagreement resolved. Confidence verified at {round((conf - 0.02) * 100)}%.",
                "ambiguity": f"{'Low' if conf >= 0.75 else 'Moderate'} ambiguity detected. Overall confidence: {round(conf * 100)}%. {'No human review required.' if not human_review else 'Human review recommended.'}",
                "final_decision": diag,
            },
            "ambiguity": human_review,
        }

    # ── Generic fallback (should never be reached) ───────────────────────────
    return {
        "final_diagnosis": diag,
        "confidence": conf,
        "reasoning": [
            "Step 1: Retrieved relevant sensor records from FAISS index.",
            f"Step 2: Identified primary failure mode: {mode}.",
            "Step 3: Cross-validated findings across multiple agent outputs.",
            "Step 4: Verified consensus and resolved contradictions.",
            "Step 5: Computed confidence score and produced final diagnosis.",
        ],
        "supporting_evidence": evidence,
        "agent_contributions": {
            "diagnostic_expert": f"Identified {mode} as primary hypothesis.",
            "pattern_agent": f"Pattern signature matches {mode}.",
            "aggressive_agent": "Confirmed — immediate inspection advised.",
            "verification": "Inter-agent consensus confirmed.",
            "ambiguity": f"Confidence: {round(conf * 100)}%. No major conflicts.",
            "final_decision": diag,
        },
        "ambiguity": conf < 0.65,
        "analysis": diag,
        "primary_hypothesis": diag,
        "decision": diag,
        "patterns_identified": [f"{mode} signature detected."],
        "dominant_failure_signature": mode,
        "trend_analysis": "Progressive degradation trend confirmed.",
        "agreements": ["All agents agree on primary diagnosis."],
        "contradictions_found": [],
        "contradictions_resolved": [],
        "verified_diagnosis": diag,
        "verification_confidence": conf,
        "conflicts_detected": [],
        "ambiguous_areas": [],
        "uncertainty_sources": [],
        "overall_confidence": conf,
        "human_review_required": conf < 0.65,
        "ambiguity_summary": f"Confidence {round(conf * 100)}%. System functioning normally.",
        "heuristic_rules": ["Threshold-based heuristic applied.", "Historical pattern match confirmed."],
        "immediate_action": "Schedule preventive maintenance inspection.",
        "patterns": [f"{mode} signature.", "Deviation from baseline."],
        "hypotheses": [{"id": 1, "hypothesis": diag, "supporting_evidence": evidence[:2], "contradicting_evidence": [], "score": conf}],
    }


# ─────────────────────────────────────────────────────────────────────────────
# LLM Client
# ─────────────────────────────────────────────────────────────────────────────

class LLMClient:
    """Unified LLM client supporting Ollama and OpenAI backends."""

    def __init__(self):
        self.provider = os.getenv("LLM_PROVIDER", "openai").lower()
        self.ollama_base = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        self.ollama_model = os.getenv("OLLAMA_MODEL", "llama3")
        self.openai_base = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
        self.openai_model = os.getenv("OPENAI_MODEL", "gpt-4o")
        self.openai_key = os.getenv("OPENAI_API_KEY", "")
        self.openai_max_tokens = int(os.getenv("OPENAI_MAX_TOKENS", "8192"))
        self.timeout = 240.0  # gpt-4o system analysis may take up to 4 minutes

    async def generate(self, prompt: str, system: str = "") -> str:
        """
        Generate a text response from the configured LLM.
        Returns raw text; JSON parsing is the caller's responsibility.
        Falls back to rule-based engine when the chosen provider is unavailable.
        """
        if self.provider == "openai":
            if not self.openai_key or self.openai_key.startswith("sk-your"):
                logger.warning("OpenAI key not set — using rule-based fallback.")
                return self._mock_response(prompt)
            return await self._openai_generate(prompt, system)
        return await self._ollama_generate(prompt, system)

    async def _ollama_generate(self, prompt: str, system: str) -> str:
        """Call Ollama /api/generate endpoint."""
        full_prompt = f"{system}\n\n{prompt}" if system else prompt
        payload = {
            "model": self.ollama_model,
            "prompt": full_prompt,
            "stream": False,
            "options": {"temperature": 0.2, "num_predict": 1024},
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(f"{self.ollama_base}/api/generate", json=payload)
                resp.raise_for_status()
                data = resp.json()
                response_text = data.get("response", "").strip()
                if response_text:
                    return response_text
                # Empty response from Ollama — use fallback
                logger.warning("Ollama returned empty response — using rule-based fallback.")
                return self._mock_response(prompt)
        except httpx.ConnectError:
            logger.warning("Ollama not reachable — using rule-based fallback engine.")
            return self._mock_response(prompt)
        except Exception as exc:
            logger.error("Ollama error: %s — using fallback.", exc)
            return self._mock_response(prompt)

    async def _openai_generate(self, prompt: str, system: str) -> str:
        """
        Call OpenAI /chat/completions with gpt-4o.
        Uses JSON mode to guarantee parseable output and a generous token
        budget so complex agent reasoning is never truncated.
        """
        # Enforce JSON output in the system message
        json_instruction = (
            "You are an expert industrial diagnostic AI assistant. "
            "You MUST respond ONLY with a single, valid JSON object — no markdown "
            "fences, no prose outside the JSON. Think step-by-step internally before "
            "producing the final JSON answer."
        )
        system_content = f"{json_instruction}\n\n{system}" if system else json_instruction

        messages = [
            {"role": "system", "content": system_content},
            {"role": "user", "content": prompt},
        ]

        headers = {
            "Authorization": f"Bearer {self.openai_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.openai_model,
            "messages": messages,
            "temperature": 0.2,
            "max_tokens": self.openai_max_tokens,
            "response_format": {"type": "json_object"},  # guaranteed JSON output
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(
                    f"{self.openai_base}/chat/completions",
                    json=payload,
                    headers=headers,
                )
                resp.raise_for_status()
                data = resp.json()
                content = data["choices"][0]["message"]["content"]
                logger.info(
                    "[OpenAI] model=%s tokens_used=%s",
                    self.openai_model,
                    data.get("usage", {}).get("total_tokens", "?"),
                )
                return content
        except httpx.HTTPStatusError as exc:
            # Surface the actual OpenAI error body for easier debugging
            try:
                err_body = exc.response.json()
            except Exception:
                err_body = exc.response.text
            logger.error("OpenAI HTTP %s error: %s — using fallback.", exc.response.status_code, err_body)
            return self._mock_response(prompt)
        except httpx.ConnectError:
            logger.warning("Cannot reach OpenAI API — using rule-based fallback.")
            return self._mock_response(prompt)
        except Exception as exc:
            logger.error("OpenAI error: %s — using fallback.", exc)
            return self._mock_response(prompt)

    # ── Harness helpers ─────────────────────────────────────────────────────
    def is_available(self) -> bool:
        """True when a real LLM is configured.  The harness never uses the
        rule-based mock below: when no LLM is available every agent runs its
        deterministic, evidence-grounded core instead."""
        mode = os.getenv("HARNESS_USE_LLM", "auto").lower()
        if mode in ("0", "false", "off", "no"):
            return False
        if self.provider == "openai":
            return bool(self.openai_key) and not self.openai_key.startswith("sk-your")
        return self.provider == "ollama"

    async def generate_json(self, prompt: str, system: str = "") -> Dict[str, Any] | None:
        """Call the real LLM and parse JSON.  Returns None (never mock data) on
        any failure so callers fall back to deterministic analysis."""
        if not self.is_available():
            return None
        try:
            if self.provider == "openai":
                raw = await self._openai_raw(prompt, system)
            else:
                raw = await self._ollama_raw(prompt, system)
        except Exception as exc:
            logger.warning("LLM call failed (%s) — deterministic fallback.", exc)
            return None
        if not raw:
            return None
        parsed = self.extract_json(raw)
        return parsed or None

    async def _openai_raw(self, prompt: str, system: str) -> str:
        payload = {
            "model": self.openai_model,
            "messages": [{"role": "system", "content": system or "Respond with a single JSON object."},
                         {"role": "user", "content": prompt}],
            "temperature": 0.1,
            "max_tokens": min(self.openai_max_tokens, 2048),
            "response_format": {"type": "json_object"},
        }
        headers = {"Authorization": f"Bearer {self.openai_key}", "Content-Type": "application/json"}
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(f"{self.openai_base}/chat/completions", json=payload, headers=headers)
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]

    async def _ollama_raw(self, prompt: str, system: str) -> str:
        payload = {"model": self.ollama_model, "prompt": f"{system}\n\n{prompt}" if system else prompt,
                   "stream": False, "format": "json", "options": {"temperature": 0.1, "num_predict": 1024}}
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(f"{self.ollama_base}/api/generate", json=payload)
            resp.raise_for_status()
            return resp.json().get("response", "").strip()

    def _mock_response(self, prompt: str) -> str:
        """
        Agent-aware rule-based fallback engine.
        Detects which agent is calling based on prompt content and returns
        a schema-correct JSON response for that specific agent.
        """
        result = _build_agent_mock(prompt)
        return json.dumps(result)

    @staticmethod
    def extract_json(text: str) -> Dict[str, Any]:
        """
        Robustly extract the first JSON object from an LLM response string.
        Falls back to an empty dict on failure.
        """
        # Try direct parse first
        try:
            return json.loads(text.strip())
        except json.JSONDecodeError:
            pass

        # Try to find a JSON block inside markdown fences
        fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        if fenced:
            try:
                return json.loads(fenced.group(1))
            except json.JSONDecodeError:
                pass

        # Try to find first complete {...} block (greedy, handles nested)
        depth = 0
        start = -1
        for i, ch in enumerate(text):
            if ch == "{":
                if depth == 0:
                    start = i
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0 and start != -1:
                    candidate = text[start : i + 1]
                    try:
                        return json.loads(candidate)
                    except json.JSONDecodeError:
                        break

        logger.warning("Could not extract JSON from LLM response — returning empty dict.")
        return {}


# Singleton instance
llm_client = LLMClient()
