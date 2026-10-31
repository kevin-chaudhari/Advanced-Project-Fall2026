"""
TraceRecorder — records one diagnostic run as an AgentTrace.

One recorder per run (``DiagnosticState`` holds it as a private attribute), so
concurrent analyses never share a sequence counter, a connection or a context.
The current agent execution is tracked in a ``ContextVar``: under
``asyncio.gather`` each agent task gets its own copy, so an LLM prompt captured
inside ``llm_client`` is attributed to the agent call that rendered it.

Tracing must never change or break a diagnosis: every public method swallows
its own errors (counted in ``write_errors``) and only *reads* the state.
"""

from __future__ import annotations

import functools
import hashlib
import itertools
import os
import threading
import time
import uuid
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from harness.agent_trace.trace_repository import TraceReader, TraceWriter, db_path
from harness.agent_trace.trace_schema import (ASK_KINDS, CHALLENGE_KINDS, EVIDENCE_REF, MESSAGE_REF,
                                              TRACE_SCHEMA_VERSION, EventType, EvidenceRelation, ExecutionStatus,
                                              HypothesisStatus, Observed, TraceStatus, hypothesis_id,
                                              hypothesis_labels_in_payload)
from utils.logger import setup_logger

logger = setup_logger("harness.agent_trace")

_CURRENT: ContextVar[Optional[Tuple["TraceRecorder", str, str]]] = ContextVar("agenttrace_execution", default=None)

AGENT_META = {
    "diagnostic_expert": ("Diagnostic Expert", "Hypothesis generation and elimination"),
    "pattern_agent": ("Pattern Recognition", "Historical signature matching"),
    "aggressive_agent": ("Rapid Triage", "Rule-based triage and severity"),
    "verification": ("Verification Analyst", "Adversarial evidence verification"),
    "ambiguity": ("Ambiguity Detection", "Uncertainty quantification"),
    "human_review_coordinator": ("Final Coordinator", "Final synthesis and human-review gate"),
}
FINDING_AGENTS = ("diagnostic_expert", "pattern_agent", "aggressive_agent", "verification")


def trace_enabled() -> bool:
    return os.getenv("AGENT_TRACE_ENABLED", "1").lower() not in ("0", "false", "off", "no")


def _store_prompts() -> bool:
    return os.getenv("AGENT_TRACE_STORE_PROMPTS", "1").lower() not in ("0", "false", "off", "no")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _safe(fn):
    @functools.wraps(fn)
    def wrapper(self, *a, **kw):
        try:
            return fn(self, *a, **kw)
        except Exception as exc:  # tracing never breaks a diagnosis
            self.write_errors += 1
            logger.warning("[agenttrace] %s failed: %s", fn.__name__, exc, exc_info=True)
            return None
    return wrapper


def claim_id(agent: str, statement: str) -> str:
    """Stable claim identity: same agent + same statement text → same claim id."""
    return f"CL-{agent}-{hashlib.sha1(statement.encode('utf-8')).hexdigest()[:8]}"


def current_execution() -> Optional[Tuple["TraceRecorder", str, str]]:
    return _CURRENT.get()


def notify_llm_call(**kw) -> None:
    """Called by utils.llm_client for every real model call (no-op outside a traced execution)."""
    cur = _CURRENT.get()
    if cur:
        rec, exec_id, _agent = cur
        rec.on_llm_call(exec_id, **kw)


class TraceRecorder:
    enabled = True

    def __init__(self, *, run_id: str, query: str, dataset_type: str, data_mode: str, llm_mode: str,
                 llm_provider: Optional[str] = None, llm_model: Optional[str] = None,
                 config: Optional[Dict[str, Any]] = None, path: Optional[str] = None):
        self.trace_id = f"TR-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8]}"
        self.run_id = run_id
        self.query = query
        self.dataset_type = dataset_type
        self.data_mode = data_mode
        self.llm_mode = llm_mode
        self.writer = TraceWriter(path or db_path())
        self._seq = itertools.count(1)
        self._lock = threading.Lock()
        self._dedup: Set[str] = set()
        self._evidence: Set[str] = set()
        self._exec_counter = itertools.count(1)
        self._exec: Dict[str, Dict[str, Any]] = {}
        self._tokens: Dict[str, Any] = {}
        self._agent_label: Dict[str, str] = {}
        self._agent_execs: Dict[str, int] = {}
        self._delivered: Set[Tuple[str, str, str]] = set()
        self._stage = "init"
        self._t0 = time.perf_counter()
        self.state = None
        self.write_errors = 0
        self.failed_executions = 0
        self.finished = False
        self.writer.insert_trace({"trace_id": self.trace_id, "run_id": run_id, "schema_version": TRACE_SCHEMA_VERSION,
                                  "query": query, "dataset_type": dataset_type, "data_mode": data_mode,
                                  "llm_mode": llm_mode, "llm_provider": llm_provider, "llm_model": llm_model,
                                  "config": config or {}, "status": TraceStatus.RUNNING.value,
                                  "started_at": _now()})
        self.event(EventType.TRACE_STARTED, actor="harness",
                   payload={"query": query, "dataset_type": dataset_type, "data_mode": data_mode.upper(),
                            "llm_mode": llm_mode, "llm_provider": llm_provider, "llm_model": llm_model,
                            "config": config or {}, "schema_version": TRACE_SCHEMA_VERSION})

    # ── core ─────────────────────────────────────────────────────────────────
    def next_seq(self) -> int:
        with self._lock:
            return next(self._seq)

    def set_stage(self, stage: str) -> None:
        self._stage = stage

    @property
    def stage(self) -> str:
        return self._stage

    @_safe
    def event(self, event_type: EventType, *, actor: Optional[str] = None, payload: Optional[Dict[str, Any]] = None,
              message_id: Optional[str] = None, evidence_ids: Optional[Iterable[str]] = None,
              parent_event_id: Optional[str] = None, execution_id: Optional[str] = None,
              dedup_key: Optional[str] = None) -> Optional[str]:
        """Append one raw event. A repeated ``dedup_key`` is ignored (returns None)."""
        if dedup_key:
            with self._lock:
                if dedup_key in self._dedup:
                    return None
                self._dedup.add(dedup_key)
        if execution_id is None:
            cur = _CURRENT.get()
            if cur and cur[0] is self:
                execution_id = cur[1]
        ev_id = f"{self.trace_id}:E{uuid.uuid4().hex[:10]}"
        p = dict(payload or {})
        p.setdefault("stage", self._stage)
        ok = self.writer.insert_event({"trace_id": self.trace_id, "seq": self.next_seq(), "event_id": ev_id,
                                       "event_type": event_type.value, "ts": _now(), "actor": actor,
                                       "execution_id": execution_id, "message_id": message_id,
                                       "evidence_ids": list(dict.fromkeys(evidence_ids or [])),
                                       "parent_event_id": parent_event_id, "payload": p, "dedup_key": dedup_key})
        return ev_id if ok else None

    def attach(self, state) -> None:
        self.state = state
        state._trace = self

    def event_collab(self, name: str, payload: Dict[str, Any]) -> Optional[str]:
        return self.event(EventType(name), actor="human_review_coordinator" if name == "JOINT_FINDING_REACHED" else "harness",
                          payload=payload)

    def suspend_execution(self, exec_id: Optional[str]) -> None:
        """Detach the current context from an open execution (it stays open in the store)."""
        _CURRENT.set(None)

    def resume_execution(self, exec_id: Optional[str]) -> None:
        x = self._exec.get(exec_id or "")
        if x:
            _CURRENT.set((self, exec_id, x["agent"]))

    # ── evidence registry ────────────────────────────────────────────────────
    @_safe
    def evidence_added(self, evidence: Iterable[Any], action: str, round_no: int) -> None:
        items = [e for e in evidence if e.evidence_id not in self._evidence]
        if not items:
            return
        ev_ids = [e.evidence_id for e in items]
        parent = self.event(EventType.EVIDENCE_RETRIEVED, actor="harness", evidence_ids=ev_ids,
                            payload={"action": action, "round": round_no, "count": len(items),
                                     "provenance": {e.evidence_id: e.source_type.upper() for e in items},
                                     "methods": {e.evidence_id: e.retrieval_method for e in items}})
        links = []
        for e in items:
            seq = self.next_seq()
            self.writer.insert_evidence({
                "trace_id": self.trace_id, "evidence_id": e.evidence_id, "kind": "record",
                "provenance": e.source_type.upper(), "dataset": e.dataset, "record_id": e.record_id,
                "label": e.label, "retrieval_action": action, "retrieval_method": e.retrieval_method,
                "retrieval_round": e.retrieval_round, "retrieval_score": e.retrieval_score,
                "method_scores": e.method_scores, "description": (e.selection_reason or "")[:300], "first_seq": seq})
            links.append({"trace_id": self.trace_id, "evidence_id": e.evidence_id,
                          "relation": EvidenceRelation.RETRIEVED.value, "subject_id": f"retrieval:{action}",
                          "value": Observed.TRUE.value, "actor": "harness", "seq": seq,
                          "detail": {"method": e.retrieval_method, "round": round_no, "event_id": parent,
                                     "selection_reason": (e.selection_reason or "")[:200]}})
            self._evidence.add(e.evidence_id)
        self.writer.insert_links(links)

    @_safe
    def sync_derived(self, state) -> None:
        for d in state.derived:
            if d.derived_id in self._evidence:
                continue
            self.writer.insert_evidence({"trace_id": self.trace_id, "evidence_id": d.derived_id, "kind": "derived",
                                         "provenance": "DERIVED", "description": d.description[:300],
                                         "retrieval_action": "harness_computation", "first_seq": self.next_seq()})
            self._evidence.add(d.derived_id)

    def known_ids(self) -> Set[str]:
        return set(self._evidence)

    # ── agent executions ─────────────────────────────────────────────────────
    @_safe
    def begin_execution(self, agent: str, *, stage: str, kind: str, state, pass_number: Optional[int] = None,
                        round_no: Optional[int] = None, input_summary: Optional[Dict[str, Any]] = None) -> Optional[str]:
        self.sync_derived(state)
        exec_id = f"X-{next(self._exec_counter):03d}"
        n_prev = self._agent_execs.get(agent, 0)
        self._agent_execs[agent] = n_prev + 1
        in_input = [e.evidence_id for e in state.evidence] + [d.derived_id for d in state.derived]
        name, role = AGENT_META.get(agent, (agent, ""))
        seq = self.next_seq()
        self._exec[exec_id] = {"agent": agent, "stage": stage, "kind": kind, "t0": time.perf_counter(),
                               "seq_start": seq, "llm_calls": [], "rendered": [], "systems": [],
                               "received": [], "sent": [], "tools": [], "in_input": set(in_input)}
        self.writer.insert_execution({"trace_id": self.trace_id, "execution_id": exec_id, "agent_id": agent,
                                      "agent_name": name, "role": role, "stage": stage, "kind": kind,
                                      "pass_number": pass_number, "round_id": round_no, "seq_start": seq,
                                      "started_at": _now(), "status": ExecutionStatus.RUNNING.value,
                                      "input": input_summary or {}, "evidence_in_input": in_input})
        self._tokens[exec_id] = _CURRENT.set((self, exec_id, agent))
        self.event(EventType.AGENT_STARTED, actor=agent, execution_id=exec_id,
                   payload={"kind": kind, "stage": stage, "pass_number": pass_number, "round": round_no,
                            "execution_index": n_prev + 1})
        if n_prev and kind == "analyze":
            self.event(EventType.AGENT_REEXECUTED, actor=agent, execution_id=exec_id,
                       payload={"stage": stage, "execution_index": n_prev + 1, "pass_number": pass_number})
        if kind == "analyze" and in_input:
            ev_ids = [i for i in in_input if i.startswith("EV-")]
            self.event(EventType.EVIDENCE_DELIVERED, actor=agent, execution_id=exec_id, evidence_ids=in_input,
                       payload={"relation": EvidenceRelation.IN_AGENT_INPUT.value, "records": len(ev_ids),
                                "derived": len(in_input) - len(ev_ids),
                                "meaning": "present in the DiagnosticState passed to analyze(); not proof of use"})
            self.writer.insert_links({"trace_id": self.trace_id, "evidence_id": i,
                                      "relation": EvidenceRelation.IN_AGENT_INPUT.value, "subject_id": exec_id,
                                      "value": Observed.TRUE.value, "actor": agent, "seq": seq} for i in in_input
                                     if i in self._evidence)
        return exec_id

    def _report_claims(self, agent: str, report) -> List[Dict[str, Any]]:
        claims, seen = [], set()
        stmts = [("supporting", s) for s in report.supporting_evidence] + \
                [("contradicting", s) for s in report.contradicting_evidence]
        for h in report.hypotheses[:3]:
            stmts += [("supporting", s) for s in h.supporting[:4]] + [("contradicting", s) for s in h.contradicting[:3]]
        for polarity, s in stmts:
            cid = claim_id(agent, s.statement)
            if cid in seen:
                continue
            seen.add(cid)
            claims.append({"claim_id": cid, "statement": s.statement, "polarity": polarity,
                           "evidence_ids": list(s.evidence_ids)})
        return claims

    @_safe
    def end_execution(self, exec_id: Optional[str], state, *, report=None, status: str = "COMPLETED",
                      error: Optional[str] = None, extra_output: Optional[Dict[str, Any]] = None) -> None:
        if not exec_id or exec_id not in self._exec:
            return
        x = self._exec[exec_id]
        agent = x["agent"]
        self.sync_derived(state)
        fields: Dict[str, Any] = {"status": status, "error": error, "completed_at": _now(),
                                  "duration_ms": round((time.perf_counter() - x["t0"]) * 1000, 2)}
        claims: List[Dict[str, Any]] = []
        if report is not None:
            claims = self._report_claims(agent, report)
            cited = set(report.evidence_ids)
            for c in claims:
                cited.update(c["evidence_ids"])
            for h in report.hypotheses:
                cited.update(h.evidence_ids)
            cited_known = sorted(i for i in cited if i in self._evidence)
            seq = self.next_seq()
            self.writer.insert_links(
                [{"trace_id": self.trace_id, "evidence_id": i, "relation": EvidenceRelation.CITED_BY_AGENT.value,
                  "subject_id": exec_id, "value": Observed.TRUE.value, "actor": agent, "seq": seq,
                  "detail": {"in_agent_input": i in x["in_input"]}} for i in cited_known] +
                [{"trace_id": self.trace_id, "evidence_id": i, "relation": EvidenceRelation.CITED_BY_CLAIM.value,
                  "subject_id": c["claim_id"], "value": c["polarity"], "actor": agent, "seq": seq,
                  "detail": {"statement": c["statement"][:400], "execution_id": exec_id}}
                 for c in claims for i in c["evidence_ids"] if i in self._evidence])
            hyps = [{"hypothesis_id": hypothesis_id(h.label), "label": h.label, "score": h.score,
                     "evidence_ids": h.evidence_ids, "supporting": len(h.supporting),
                     "contradicting": len(h.contradicting), "missing": h.missing[:4]} for h in report.hypotheses[:6]]
            fields.update({"output_json": {"finding": report.finding, "narrative": report.narrative[:1500],
                                           "recommendation": report.recommendation, "mode": report.mode,
                                           "missing_information": report.missing_information[:6],
                                           "claims_removed": report.claims_removed,
                                           "evidence_ids": report.evidence_ids[:20],
                                           "extras": _compact_extras(report.extras), **(extra_output or {})},
                           "finding_label": report.finding_label, "confidence": float(report.confidence),
                           "hypotheses_json": hyps, "claims_json": claims})
            self.event(EventType.AGENT_OUTPUT_GENERATED, actor=agent, execution_id=exec_id, evidence_ids=cited_known,
                       payload={"finding": report.finding, "finding_label": report.finding_label,
                                "confidence": round(float(report.confidence), 4), "mode": report.mode,
                                "claims": len(claims), "hypotheses": [h["label"] for h in hyps]})
            self._finding_transition(agent, report, exec_id, x["stage"])
        elif extra_output is not None:
            fields["output_json"] = extra_output
        if status == ExecutionStatus.FAILED.value:
            self.failed_executions += 1
            self.event(EventType.AGENT_FAILED, actor=agent, execution_id=exec_id,
                       payload={"error": (error or "")[:500], "stage": x["stage"], "kind": x["kind"]})
        fields.update({"llm_calls_json": x["llm_calls"], "messages_sent_json": x["sent"],
                       "messages_received_json": x["received"], "tool_calls_json": x["tools"],
                       "seq_end": self.next_seq()})
        if x["rendered"] and _store_prompts():
            fields["rendered_input"] = "\n\n----- next model call -----\n\n".join(x["rendered"])
            fields["rendered_system"] = "\n\n----- next model call -----\n\n".join(x["systems"])
        self.writer.update_execution(self.trace_id, exec_id, fields)
        tok = self._tokens.pop(exec_id, None)
        if tok is not None:
            try:
                _CURRENT.reset(tok)
            except ValueError:  # pragma: no cover - reset from another context
                _CURRENT.set(None)

    def _finding_transition(self, agent: str, report, exec_id: str, stage: str) -> None:
        label = report.finding_label
        if agent not in FINDING_AGENTS or not label:
            return
        prev = self._agent_label.get(agent)
        score = next((h.score for h in report.hypotheses if h.label == label), None)
        ids = next((h.evidence_ids for h in report.hypotheses if h.label == label), report.evidence_ids[:4])
        if prev is None:
            self.hypothesis(agent, label, HypothesisStatus.PROPOSED, execution_id=exec_id, score=score,
                            evidence_ids=ids, reason=f"{stage}: initial finding")
        elif prev != label:
            self.hypothesis(agent, prev, HypothesisStatus.REJECTED, execution_id=exec_id,
                            reason=f"{stage}: replaced by {label}")
            self.hypothesis(agent, label, HypothesisStatus.MODIFIED, execution_id=exec_id, score=score,
                            evidence_ids=ids, reason=f"{stage}: finding changed from {prev}")
        else:
            self.hypothesis(agent, label, HypothesisStatus.RETAINED, execution_id=exec_id, score=score,
                            evidence_ids=ids, reason=f"{stage}: re-execution kept the same finding")
        self._agent_label[agent] = label

    @_safe
    def hypothesis(self, agent: str, label: str, status: HypothesisStatus, *, execution_id: Optional[str] = None,
                   message_id: Optional[str] = None, round_no: Optional[int] = None, score: Optional[float] = None,
                   evidence_ids: Optional[List[str]] = None, reason: str = "") -> None:
        hid = hypothesis_id(label)
        ev_type = {HypothesisStatus.PROPOSED: EventType.HYPOTHESIS_PROPOSED,
                   HypothesisStatus.CHALLENGED: EventType.HYPOTHESIS_CHALLENGED}.get(status, EventType.HYPOTHESIS_UPDATED)
        if status != HypothesisStatus.CHALLENGED:   # the CHALLENGE message already emits HYPOTHESIS_CHALLENGED
            self.event(ev_type, actor=agent, execution_id=execution_id, message_id=message_id,
                       evidence_ids=evidence_ids or [],
                       payload={"hypothesis_id": hid, "label": label, "status": status.value, "reason": reason,
                                "score": score})
        self.writer.insert_hypothesis_state({"trace_id": self.trace_id, "seq": self.next_seq(), "hypothesis_id": hid,
                                             "label": label, "agent_id": agent, "status": status.value,
                                             "execution_id": execution_id, "message_id": message_id,
                                             "round_id": round_no, "score": score,
                                             "evidence_ids": evidence_ids or [], "reason": reason, "ts": _now()})
        if status in (HypothesisStatus.MODIFIED, HypothesisStatus.PROPOSED, HypothesisStatus.FINAL):
            self._agent_label[agent] = label

    # ── messages ─────────────────────────────────────────────────────────────
    @_safe
    def on_post(self, state, msg) -> None:
        cur = _CURRENT.get()
        exec_id = cur[1] if cur and cur[0] is self and cur[2] == msg.sender else None
        labels = hypothesis_labels_in_payload(msg.payload)
        hyp_ids = [hypothesis_id(l) for l in labels]
        unknown = [i for i in msg.evidence_ids if i not in self._evidence]
        if unknown:
            self.sync_derived(state)
            unknown = [i for i in msg.evidence_ids if i not in self._evidence]
        payload = dict(msg.payload)
        if unknown:
            payload["_trace_unknown_evidence_ids"] = unknown
        seq = self.next_seq()
        parent = msg.payload.get("parent_message_id")
        self.writer.insert_message({
            "trace_id": self.trace_id, "message_id": msg.message_id, "seq": seq, "round_id": msg.round,
            "stage": getattr(msg, "phase", None) or self._stage, "sender": msg.sender, "sender_execution_id": exec_id, "recipients": msg.recipients,
            "message_type": msg.kind, "topic": msg.topic, "content": msg.text, "evidence_ids": msg.evidence_ids,
            "hypothesis_ids": hyp_ids, "parent_message_id": parent or msg.in_reply_to,
            "response_to_message_id": msg.in_reply_to, "payload": payload, "ts": _now(), "resolved": msg.resolved,
            "challenge_status": "OPEN" if msg.kind in CHALLENGE_KINDS else "NOT_APPLICABLE",
            "resolution_status": _resolution(msg)})
        sent = self.event(EventType.MESSAGE_SENT, actor=msg.sender, message_id=msg.message_id, execution_id=exec_id,
                          evidence_ids=msg.evidence_ids,
                          payload={"message_type": msg.kind, "round": msg.round, "recipients": msg.recipients,
                                   "phase": getattr(msg, "phase", None), "voice": msg.payload.get("voice"),
                                   "topic": msg.topic, "in_reply_to": msg.in_reply_to,
                                   "hypothesis_ids": hyp_ids, "unknown_evidence_ids": unknown},
                          dedup_key=f"SENT:{msg.message_id}")
        if exec_id and exec_id in self._exec:
            self._exec[exec_id]["sent"].append(msg.message_id)
        known = [i for i in msg.evidence_ids if i in self._evidence]
        self.writer.insert_links({"trace_id": self.trace_id, "evidence_id": i,
                                  "relation": EvidenceRelation.CITED_IN_MESSAGE.value, "subject_id": msg.message_id,
                                  "value": Observed.TRUE.value, "actor": msg.sender, "seq": seq,
                                  "detail": {"message_type": msg.kind}} for i in known)
        explicit = [r for r in msg.recipients if r not in ("all", "harness")]
        target = explicit[:1]          # challenges/responses address their target first; later entries are CCs
        kind = msg.kind
        if kind == "QUESTION":
            self.event(EventType.QUESTION_RAISED, actor=msg.sender, message_id=msg.message_id, parent_event_id=sent,
                       payload={"to": msg.recipients, "need": msg.payload.get("need"), "topic": msg.topic})
        elif kind in CHALLENGE_KINDS:
            self.event(EventType.HYPOTHESIS_CHALLENGED, actor=msg.sender, message_id=msg.message_id,
                       parent_event_id=sent, evidence_ids=msg.evidence_ids,
                       payload={"challenged": target, "cc": explicit[1:],
                                "challenged_label": msg.payload.get("your_label"),
                                "challenger_label": msg.payload.get("proposed") or msg.payload.get("verified"),
                                "message_type": kind})
            if msg.payload.get("your_label"):
                for r in target:
                    self.hypothesis(r, msg.payload["your_label"], HypothesisStatus.CHALLENGED, message_id=msg.message_id,
                                    round_no=msg.round, reason=f"{kind} from {msg.sender}")
        elif kind in ("EVIDENCE_REQUEST", "VERIFICATION_REQUEST"):
            self.event(EventType.EVIDENCE_REQUESTED, actor=msg.sender, message_id=msg.message_id,
                       parent_event_id=sent, evidence_ids=msg.evidence_ids,
                       payload={"to": msg.recipients, "message_type": kind,
                                "claims": len(msg.payload.get("claims") or []), "label": msg.payload.get("label")})
        elif kind == "VERIFICATION_RESULT":
            res = msg.payload.get("results") or []
            self.event(EventType.EVIDENCE_VERIFIED, actor=msg.sender, message_id=msg.message_id, parent_event_id=sent,
                       evidence_ids=msg.evidence_ids,
                       payload={"for": explicit, "claims_checked": len(res),
                                "statuses": {s: sum(1 for r in res if r.get("status") == s)
                                             for s in ("SUPPORTED", "DERIVED", "UNSUPPORTED")},
                                "label_status": msg.payload.get("label_status")})
            links = []
            for r in res:
                for i in r.get("evidence_ids", []):
                    if i in self._evidence:
                        links.append({"trace_id": self.trace_id, "evidence_id": i,
                                      "relation": EvidenceRelation.VERIFIED.value, "subject_id": r["claim_id"],
                                      "value": r.get("status"), "actor": msg.sender, "seq": seq,
                                      "detail": {"message_id": msg.message_id, "reasons": r.get("reasons", [])[:4]}})
            self.writer.insert_links(links)
        elif kind == "RESPONSE":
            lab, stance = msg.payload.get("label"), msg.payload.get("stance")
            if lab and stance in ("retain", "qualify"):
                self.hypothesis(msg.sender, lab,
                                HypothesisStatus.RETAINED if stance == "retain" else HypothesisStatus.QUALIFIED,
                                execution_id=exec_id, message_id=msg.message_id, round_no=msg.round,
                                evidence_ids=msg.evidence_ids, reason=f"response to {msg.in_reply_to}")
        elif kind in ("POSITION_UPDATE", "CONCESSION") and getattr(msg, "phase", "") in ("collaboration", "resync"):
            new, old = msg.payload.get("new_label") or msg.payload.get("label"), msg.payload.get("old_label")
            conf = msg.payload.get("confidence") or (msg.payload.get("position") or {}).get(new)
            if new and old and new != old:
                self.hypothesis(msg.sender, old, HypothesisStatus.REJECTED, execution_id=exec_id,
                                message_id=msg.message_id, round_no=msg.round, reason=f"{kind} in {msg.phase}")
                self.hypothesis(msg.sender, new, HypothesisStatus.MODIFIED, execution_id=exec_id, message_id=msg.message_id,
                                round_no=msg.round, score=conf, evidence_ids=msg.evidence_ids,
                                reason=f"{kind} after reading the council")
            elif new and kind == "POSITION_UPDATE":
                self.hypothesis(msg.sender, new, HypothesisStatus.RETAINED, execution_id=exec_id, message_id=msg.message_id,
                                round_no=msg.round, score=conf, reason="belief revised, same lead")
        elif kind == "HOLD":
            lab = msg.payload.get("label")
            if lab:
                self.hypothesis(msg.sender, lab, HypothesisStatus.RETAINED, execution_id=exec_id,
                                message_id=msg.message_id, round_no=msg.round, evidence_ids=msg.evidence_ids,
                                reason=f"held against {msg.in_reply_to}")

    @_safe
    def on_inbox(self, agent: str, msgs: List[Any], via: str = "inbox_read") -> None:
        cur = _CURRENT.get()
        exec_id = cur[1] if cur and cur[0] is self and cur[2] == agent else None
        for m in msgs:
            key = (m.message_id, agent, via)
            if key in self._delivered:
                continue
            self._delivered.add(key)
            seq = self.next_seq()
            self.writer.insert_delivery({"trace_id": self.trace_id, "message_id": m.message_id, "receiver": agent,
                                         "via": via, "seq": seq, "execution_id": exec_id, "ts": _now()})
            self.event(EventType.MESSAGE_RECEIVED, actor=agent, message_id=m.message_id, execution_id=exec_id,
                       evidence_ids=m.evidence_ids,
                       payload={"from": m.sender, "message_type": m.kind, "via": via, "round": m.round},
                       dedup_key=f"RECV:{m.message_id}:{agent}:{via}")
            if exec_id and exec_id in self._exec:
                self._exec[exec_id]["received"].append(m.message_id)

    # ── model calls & tools ──────────────────────────────────────────────────
    @_safe
    def on_llm_call(self, exec_id: str, *, provider: str, model: str, system: str, prompt: str,
                    response: Optional[str], ok: bool, error: Optional[str], duration_ms: float) -> None:
        x = self._exec.get(exec_id)
        if not x:
            return
        rendered = f"{system}\n\n{prompt}" if system else prompt
        digest = hashlib.sha256(rendered.encode("utf-8")).hexdigest()
        call = {"index": len(x["llm_calls"]) + 1, "provider": provider, "model": model, "ok": ok,
                "error": (error or "")[:300] or None, "duration_ms": round(duration_ms, 1),
                "input_sha256": digest, "input_chars": len(rendered),
                "response_chars": len(response or ""), "response_excerpt": (response or "")[:2000]}
        x["llm_calls"].append(call)
        x["rendered"].append(prompt)
        x["systems"].append(system)
        agent = x["agent"]
        state = self.state
        present_ids = set(EVIDENCE_REF.findall(rendered))
        seq = self.next_seq()
        if state is not None:
            self.sync_derived(state)
            universe = [e.evidence_id for e in state.evidence] + [d.derived_id for d in state.derived]
            self.writer.insert_links(
                {"trace_id": self.trace_id, "evidence_id": i, "relation": EvidenceRelation.IN_RENDERED_INPUT.value,
                 "subject_id": exec_id, "value": (Observed.TRUE if i in present_ids else Observed.FALSE).value,
                 "actor": agent, "seq": seq,
                 "detail": {"llm_call": call["index"], "call_ok": ok, "input_sha256": digest,
                            "basis": "token search over the complete captured model input"}}
                for i in universe if i in self._evidence)
            msg_ids = set(MESSAGE_REF.findall(rendered))
            delivered = [m for m in state.messages if m.message_id in msg_ids]
            if delivered:
                self.on_inbox(agent, delivered, via="rendered_prompt")
        self.event(EventType.LLM_CALL_COMPLETED, actor=agent, execution_id=exec_id,
                   evidence_ids=sorted(present_ids & self._evidence),
                   payload={k: v for k, v in call.items() if k != "response_excerpt"})

    @_safe
    def tool_call(self, agent: str, tool: str, args: Dict[str, Any], result: Dict[str, Any]) -> None:
        cur = _CURRENT.get()
        exec_id = cur[1] if cur and cur[0] is self else None
        rec = {"tool": tool, "args": args, "result": result}
        if exec_id and exec_id in self._exec:
            self._exec[exec_id]["tools"].append(rec)
        self.event(EventType.TOOL_CALLED, actor=agent, execution_id=exec_id,
                   evidence_ids=result.get("evidence_ids") or [], payload=rec)

    # ── completion ───────────────────────────────────────────────────────────
    @_safe
    def sync_message_status(self, state) -> None:
        by_reply: Dict[str, List[Any]] = {}
        for m in state.messages:
            if m.in_reply_to:
                by_reply.setdefault(m.in_reply_to, []).append(m)
        for m in state.messages:
            cs = "NOT_APPLICABLE"
            if m.kind in CHALLENGE_KINDS:
                replies = by_reply.get(m.message_id, [])
                kinds = {r.kind for r in replies}
                cs = ("CONCEDED" if "CONCESSION" in kinds else "HELD" if "HOLD" in kinds
                      else "RESPONDED" if kinds else "OPEN")
            payload = dict(m.payload)
            self.writer.update_message_status(self.trace_id, m.message_id, m.resolved, cs, _resolution(m),
                                              payload if m.kind in CHALLENGE_KINDS else None)
            if m.kind in CHALLENGE_KINDS:
                et = EventType.DISAGREEMENT_RESOLVED if m.resolved else EventType.DISAGREEMENT_UNRESOLVED
                self.event(et, actor="harness", message_id=m.message_id,
                           payload={"challenge_status": cs, "outcome": m.payload.get("outcome"),
                                    "challenged": [x for x in m.recipients if x not in ("all", "harness")][:1],
                                    "challenger": m.sender},
                           dedup_key=f"DISAGREE:{m.message_id}")

    @_safe
    def complete(self, state, result: Dict[str, Any]) -> None:
        if self.finished:
            return
        self.sync_derived(state)
        self.sync_message_status(state)
        final = state.final_label
        if final:
            self.hypothesis("human_review_coordinator", final, HypothesisStatus.FINAL,
                            evidence_ids=(state.coordinator_output.evidence_ids[:6] if state.coordinator_output else []),
                            reason="final validated diagnosis")
            for m in state.messages:
                if m.kind in CHALLENGE_KINDS and m.resolved is False and m.payload.get("your_label"):
                    for r in [x for x in m.recipients if x not in ("all", "harness")][:1]:
                        self.hypothesis(r, m.payload["your_label"], HypothesisStatus.UNRESOLVED,
                                        message_id=m.message_id, round_no=m.round,
                                        reason=m.payload.get("outcome") or "challenge left open")
        status = TraceStatus.COMPLETED_WITH_ERRORS if self.failed_executions else TraceStatus.COMPLETED
        self.event(EventType.TRACE_COMPLETED, actor="harness",
                   payload={"status": status.value, "final_label": final,
                            "confidence": result.get("confidence"), "review_decision": result.get("review_decision"),
                            "failed_executions": self.failed_executions, "trace_write_errors": self.write_errors})
        self._finish(state, status, result=result)

    @_safe
    def fail(self, state, exc: BaseException) -> None:
        if self.finished:
            return
        for exec_id, x in list(self._exec.items()):
            if exec_id in self._tokens:
                self.end_execution(exec_id, state, status=ExecutionStatus.FAILED.value, error=f"aborted: {exc}")
        if state is not None:
            self.sync_message_status(state)
        self.event(EventType.TRACE_FAILED, actor="harness",
                   payload={"error": f"{type(exc).__name__}: {exc}"[:800], "stage": self._stage})
        self._finish(state, TraceStatus.FAILED, error=f"{type(exc).__name__}: {exc}"[:800])

    def _finish(self, state, status: TraceStatus, result: Optional[Dict[str, Any]] = None,
                error: Optional[str] = None) -> None:
        from harness.agent_trace.trace_analyzer import build_semantic
        self.finished = True
        fields: Dict[str, Any] = {"status": status.value, "completed_at": _now(), "updated_at": _now(),
                                  "duration_ms": round((time.perf_counter() - self._t0) * 1000, 1), "error": error}
        if state is not None:
            fields.update({"final_label": state.final_label, "final_diagnosis": (state.final_diagnosis or "")[:1000],
                           "final_confidence": state.confidence.confidence if state.confidence else None,
                           "review_decision": state.review.decision if state.review else None,
                           "communication_rounds": len({m.round for m in state.messages}),
                           "total_messages": len(state.messages)})
        self.writer.update_trace(self.trace_id, fields)
        try:
            sem = build_semantic(TraceReader(self.writer.path), self.trace_id)
            self.writer.update_trace(self.trace_id, {
                "semantic_json": sem, "total_events": sem["summary"]["total_events"],
                "total_evidence_refs": sem["summary"]["total_evidence_references"]})
        except Exception as exc:
            self.write_errors += 1
            logger.warning("[agenttrace] semantic snapshot failed: %s", exc, exc_info=True)
        self.writer.close()


class NullRecorder:
    """Used when AGENT_TRACE_ENABLED=0 — same interface, records nothing."""
    enabled = False
    trace_id = None
    stage = "init"
    write_errors = 0

    def __getattr__(self, name):
        return lambda *a, **kw: None

    def attach(self, state) -> None:
        state._trace = None


def _resolution(msg) -> str:
    if msg.kind not in ASK_KINDS:
        return "NOT_APPLICABLE"
    if msg.kind == "HUMAN_INPUT_REQUEST" and not msg.resolved:
        return "AWAITING_HUMAN"
    if msg.resolved is True:
        return "RESOLVED"
    if msg.resolved is False:
        return "UNRESOLVED"
    return "PENDING"


def _compact_extras(extras: Dict[str, Any]) -> Dict[str, Any]:
    keep = {}
    for k, v in (extras or {}).items():
        if isinstance(v, (str, int, float, bool)) or v is None:
            keep[k] = v
        elif isinstance(v, (list, dict)) and len(str(v)) <= 1500:
            keep[k] = v
    return keep


def start_trace(**kw):
    if not trace_enabled():
        return NullRecorder()
    try:
        return TraceRecorder(**kw)
    except Exception as exc:
        logger.warning("[agenttrace] could not start trace (%s) — continuing untraced.", exc, exc_info=True)
        return NullRecorder()
