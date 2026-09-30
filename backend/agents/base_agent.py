"""
Base agent class — shared structure for the six diagnostic agents.

Each agent now works against the shared ``DiagnosticState``:

    report = await agent.analyze(state, ctx)

* A deterministic, evidence-grounded core always runs (works offline).
* When an LLM is configured, the agent additionally sends a *compact,
  structured* prompt (evidence IDs + derived facts, never raw 50-line records)
  and merges the LLM's structured answer after validating every evidence ID,
  label and number it contains.
* The legacy ``run(question, context, extra)`` entry point is kept for
  backward compatibility.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from harness.claims import ClaimValidator
from harness.knowledge_base import KnowledgeBase, ReferenceStats
from harness.schema import AgentReport, DiagnosticState, EvidenceStatement, Hypothesis
from utils.llm_client import LLMClient, llm_client
from utils.logger import setup_logger

JSON_RULES = (
    "Rules: (1) Use ONLY the evidence records (EV-xxx), derived facts (D-xxx) and the user's readings "
    "given below. (2) Every statement must cite at least one EV-xxx or D-xxx ID. (3) Never state a sensor "
    "value that does not appear in the inputs; if a channel is missing, say it is unavailable. "
    "(4) Only use failure-mode labels from ALLOWED_LABELS. (5) Respond with ONE JSON object."
)


@dataclass
class AgentContext:
    kb: KnowledgeBase
    ref: ReferenceStats
    mode: str
    llm_enabled: bool
    known_labels: List[str]


class BaseAgent(ABC):
    """Abstract base for all diagnostic agents."""

    key: str = "agent"

    def __init__(self):
        self.llm: LLMClient = llm_client
        self.logger = setup_logger(self.__class__.__name__)

    @property
    @abstractmethod
    def role(self) -> str:
        ...

    @property
    @abstractmethod
    def goal(self) -> str:
        ...

    # ── harness API ─────────────────────────────────────────────────────────
    async def analyze(self, state: DiagnosticState, ctx: AgentContext, **kwargs) -> AgentReport:
        report = self.deterministic(state, ctx, **kwargs)
        if ctx.llm_enabled and self.uses_llm:
            try:
                report = await self._llm_refine(state, ctx, report, **kwargs)
            except Exception as exc:  # malformed LLM output must never break the run
                self.logger.warning("[%s] LLM refinement failed (%s) — keeping deterministic report.", self.role, exc)
        self._mark_usage(state, report)
        return report

    uses_llm: bool = True

    def deterministic(self, state: DiagnosticState, ctx: AgentContext, **kwargs) -> AgentReport:
        raise NotImplementedError(f"{self.__class__.__name__} does not implement the harness API")

    def llm_task(self, state: DiagnosticState, ctx: AgentContext, report: AgentReport, **kwargs) -> Optional[str]:
        """Return the task-specific part of the prompt (None = no LLM step)."""
        return None

    async def _llm_refine(self, state: DiagnosticState, ctx: AgentContext, report: AgentReport, **kwargs) -> AgentReport:
        task = self.llm_task(state, ctx, report, **kwargs)
        if not task:
            return report
        prompt = self.structured_inputs(state, ctx, report) + "\n\nTASK:\n" + task
        data = await self.llm.generate_json(prompt, system=f"You are the {self.role}. {self.goal}\n{JSON_RULES}")
        if not isinstance(data, dict):
            return report
        return self.merge_llm(state, ctx, report, data)

    def merge_llm(self, state: DiagnosticState, ctx: AgentContext, report: AgentReport, data: Dict[str, Any]) -> AgentReport:
        """Default merge: validated narrative + validated extra statements."""
        validator = ClaimValidator(state, ctx.known_labels)
        narrative = str(data.get("narrative") or data.get("analysis") or "")
        if narrative:
            clean, checks = validator.clean_text(narrative, source=f"{self.key}:llm")
            report.claims_removed += sum(1 for c in checks if c.action == "removed")
            report.narrative = clean or report.narrative
        extra_support = self._statements(data.get("supporting_evidence"), state)
        kept = []
        for st in extra_support:
            chk = validator.check_sentence(st.statement, f"{self.key}:llm")
            state.claim_checks.extend(chk)
            if any(c.status == "UNSUPPORTED" for c in chk) or not st.evidence_ids:
                report.claims_removed += 1
                continue
            kept.append(st)
        report.supporting_evidence.extend(kept[:4])
        report.mode = "llm+deterministic"
        return report

    # ── helpers ─────────────────────────────────────────────────────────────
    @staticmethod
    def _statements(items: Any, state: DiagnosticState) -> List[EvidenceStatement]:
        out = []
        valid = {e.evidence_id for e in state.evidence} | {d.derived_id for d in state.derived}
        for it in items or []:
            if isinstance(it, dict):
                text = str(it.get("statement") or it.get("text") or "")
                ids = [i for i in it.get("evidence_ids", []) if i in valid]
            else:
                text = str(it)
                import re
                ids = [i for i in re.findall(r"\b(?:EV|D)-\d{3,}\b", text) if i in valid]
            if text:
                out.append(EvidenceStatement(statement=text, evidence_ids=ids))
        return out

    def structured_inputs(self, state: DiagnosticState, ctx: AgentContext, report: AgentReport) -> str:
        prof = state.profile
        ev_rows = []
        for e in state.evidence[:10]:
            sens = {k: v for k, v in (e.content.get("sensors") or {}).items() if v is not None}
            ev_rows.append({"id": e.evidence_id, "source": e.source_type.upper(), "label": e.label,
                            "score": round(e.retrieval_score, 3), "method": e.retrieval_method,
                            "equipment": e.content.get("equipment_type"), "sensors": sens})
        derived = [{"id": d.derived_id, "fact": d.description, "value": d.value} for d in state.derived[:40]]
        hyps = [{"label": h["label"], "score": h["score"]} for h in state.analysis.get("hypotheses", [])[:5]]
        return (
            f"USER QUESTION: {state.query}\n"
            f"USER READINGS (only these values exist for the asset): {json.dumps(prof.sensors if prof else {})}\n"
            f"MISSING CHANNELS: {json.dumps(sorted(set((prof.missing_sensors if prof else [])) ))}\n"
            f"ALLOWED_LABELS: {json.dumps(ctx.known_labels)}\n"
            f"EVIDENCE: {json.dumps(ev_rows)}\n"
            f"DERIVED_FACTS: {json.dumps(derived)}\n"
            f"DETERMINISTIC_HYPOTHESIS_SCORES: {json.dumps(hyps)}\n"
            f"YOUR_DETERMINISTIC_DRAFT: {json.dumps({'finding': report.finding, 'hypotheses': [h.label for h in report.hypotheses]})}"
        )

    def _mark_usage(self, state: DiagnosticState, report: AgentReport) -> None:
        ids = set(report.evidence_ids)
        for st in report.supporting_evidence + report.contradicting_evidence:
            ids.update(st.evidence_ids)
        for h in report.hypotheses:
            ids.update(h.evidence_ids)
        for e in state.evidence:
            if e.evidence_id in ids and self.key not in e.used_by:
                e.used_by.append(self.key)

    # ── legacy API ──────────────────────────────────────────────────────────
    def build_prompt(self, question: str, context: str, extra: Dict) -> str:
        return f"QUESTION: {question}\n\nCONTEXT:\n{context}\n\nRespond in JSON."

    async def run(self, question: str, context: str, extra: Dict = None) -> Dict[str, Any]:
        extra = extra or {}
        prompt = self.build_prompt(question, context, extra)
        raw = await self.llm.generate(prompt, system=self._system_message())
        return self.llm.extract_json(raw)

    def _system_message(self) -> str:
        return (f"You are the {self.role}. Your goal: {self.goal}\n"
                "ALWAYS respond in valid JSON. Do not add prose outside the JSON object.")

    @staticmethod
    def format_context(docs: List[Dict]) -> str:
        if not docs:
            return "No relevant context found."
        return "\n\n".join(f"[{i}] {doc.get('content', '')}" for i, doc in enumerate(docs, 1))
