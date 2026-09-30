"""Audit trail recorder for orchestration steps."""

from __future__ import annotations

import time
from contextlib import contextmanager
from typing import List, Optional

from harness.schema import AuditEvent, DiagnosticState
from utils.logger import setup_logger

logger = setup_logger("harness.audit")


class AuditRecorder:
    def __init__(self, state: DiagnosticState):
        self.state = state

    @contextmanager
    def step(self, stage: str, action: str, agent: Optional[str] = None, reason: str = ""):
        ev = AuditEvent(step=len(self.state.audit_trail) + 1, stage=stage, agent=agent, action=action, reason=reason)
        t0 = time.perf_counter()
        try:
            yield ev
        except Exception as exc:
            ev.status = "error"
            ev.reason = f"{ev.reason} | error: {exc}".strip(" |")
            raise
        finally:
            ev.duration_ms = round((time.perf_counter() - t0) * 1000, 2)
            self.state.audit_trail.append(ev)
            logger.info("[audit] #%d %-18s %-28s %s (%.1f ms) %s", ev.step, stage, action, ev.status,
                        ev.duration_ms, ev.reason[:120])

    def note(self, stage: str, action: str, reason: str = "", status: str = "ok",
             agent: Optional[str] = None, evidence_used: Optional[List[str]] = None) -> None:
        self.state.audit_trail.append(AuditEvent(step=len(self.state.audit_trail) + 1, stage=stage, agent=agent,
                                                 action=action, reason=reason, status=status,
                                                 evidence_used=evidence_used or []))
