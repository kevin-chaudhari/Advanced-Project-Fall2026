"""
AgentTrace API — read-only endpoints over persisted traces.

Every response is computed from the SQLite rows written during the run
(harness/agent_trace); nothing is taken from the live process or sample data,
so a trace reads the same after a backend restart.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

import io
import zipfile

from fastapi import APIRouter, HTTPException, Path, Query
from fastapi.responses import Response

from harness.agent_trace.trace_analyzer import (AGENT_NAMES, AGENTS, agent_histories, build_semantic,
                                                communication_graph, disagreements, evidence_view, full_timeline)
from harness.agent_trace.trace_repository import TraceReader
from harness.agent_trace import trace_export
from harness.agent_trace.trace_schema import (PagedEvents, TRACE_SCHEMA_VERSION, TraceListResponse,
                                              TraceMessageModel)

router = APIRouter(tags=["AgentTrace"])

TRACE_ID = Path(..., pattern=r"^TR-\d{14}-[0-9a-f]{8}$", description="Trace ID, e.g. TR-20261031120836-1163adc2")


def _reader() -> TraceReader:
    return TraceReader()


def _require(reader: TraceReader, trace_id: str) -> Dict[str, Any]:
    t = reader.get_trace(trace_id)
    if not t:
        raise HTTPException(status_code=404, detail=f"Trace '{trace_id}' not found.")
    return t


@router.get("/traces", response_model=TraceListResponse)
async def list_traces(limit: int = Query(default=25, ge=1, le=200), offset: int = Query(default=0, ge=0),
                      status: Optional[str] = Query(default=None, pattern="^(RUNNING|COMPLETED|COMPLETED_WITH_ERRORS|FAILED)$"),
                      dataset: Optional[str] = None):
    rows, total = _reader().list_traces(limit=limit, offset=offset, status=status, dataset=dataset)
    return {"traces": rows, "total": total, "limit": limit, "offset": offset}


@router.get("/traces/export/archive")
async def export_archive(limit: int = Query(default=20, ge=1, le=500), dataset: Optional[str] = None,
                         formats: str = Query(default="json,transcript", description="comma-separated: " + ", ".join(trace_export.FORMATS)),
                         include_prompts: bool = True):
    """Download the most recent traces as one .zip (one file per trace and format)."""
    fmts = [f.strip() for f in formats.split(",") if f.strip()]
    bad = [f for f in fmts if f not in trace_export.FORMATS]
    if bad:
        raise HTTPException(status_code=422, detail=f"unknown format(s) {bad}; choose from {list(trace_export.FORMATS)}")
    r = _reader()
    rows, _ = r.list_traces(limit=limit, dataset=dataset)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        index = []
        for t in rows:
            b = trace_export.bundle(r, t["trace_id"], include_prompts=include_prompts)
            for f in fmts:
                z.writestr(f"{t['trace_id']}/{trace_export.filename(t['trace_id'], f)}", trace_export.render(b, f))
            index.append(t)
        z.writestr("index.json", json.dumps(index, indent=1, default=str))
    return Response(buf.getvalue(), media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="agent_traces_{len(rows)}.zip"'})


@router.get("/traces/{trace_id}/export")
async def export_trace(trace_id: str = TRACE_ID, format: str = Query(default="json", pattern="^(" + "|".join(trace_export.FORMATS) + ")$"),
                       include_prompts: bool = True):
    """Download one trace as a file: full JSON bundle, Markdown transcript of the conversation, or CSV tables."""
    r = _reader()
    _require(r, trace_id)
    body = trace_export.render(trace_export.bundle(r, trace_id, include_prompts=include_prompts), format)
    return Response(body, media_type=trace_export.MEDIA.get(format, "text/csv; charset=utf-8"),
                    headers={"Content-Disposition": f'attachment; filename="{trace_export.filename(trace_id, format)}"'})


@router.get("/traces/by-run/{run_id}")
async def trace_by_run(run_id: str = Path(..., pattern=r"^[0-9a-f]{12}$")):
    tid = _reader().trace_for_run(run_id)
    if not tid:
        raise HTTPException(status_code=404, detail=f"No trace for run '{run_id}'.")
    return {"run_id": run_id, "trace_id": tid}


@router.get("/traces/{trace_id}")
async def get_trace(trace_id: str = TRACE_ID):
    """Run-level record plus the derived views (summary, graph, disagreements, agent histories)."""
    r = _reader()
    t = _require(r, trace_id)
    t.pop("semantic", None)
    sem = build_semantic(r, trace_id)       # recomputed from rows, so RUNNING / FAILED traces work too
    return {"schema_version": TRACE_SCHEMA_VERSION, "trace": t, **sem}


@router.get("/traces/{trace_id}/summary")
async def trace_summary(trace_id: str = TRACE_ID):
    r = _reader()
    t = _require(r, trace_id)
    sem = build_semantic(r, trace_id)
    return {"trace_id": trace_id, "query": t["query"], "dataset_type": t["dataset_type"],
            "data_mode": t["data_mode"], "llm_mode": t.get("llm_mode"), "started_at": t["started_at"],
            "completed_at": t.get("completed_at"), "duration_ms": t.get("duration_ms"), "error": t.get("error"),
            **sem["summary"], "disagreements": sem["disagreements"]}


@router.get("/traces/{trace_id}/events", response_model=PagedEvents)
async def trace_events(trace_id: str = TRACE_ID, limit: int = Query(default=500, ge=1, le=5000),
                       offset: int = Query(default=0, ge=0), event_type: Optional[str] = None,
                       actor: Optional[str] = None):
    r = _reader()
    _require(r, trace_id)
    events, total = r.events(trace_id, limit=limit, offset=offset, event_type=event_type, actor=actor)
    return {"trace_id": trace_id, "events": events, "total": total, "limit": limit, "offset": offset}


@router.get("/traces/{trace_id}/messages")
async def trace_messages(trace_id: str = TRACE_ID, message_type: Optional[str] = None,
                         agent: Optional[str] = None):
    r = _reader()
    _require(r, trace_id)
    msgs = [TraceMessageModel(**m).model_dump() for m in r.messages(trace_id)]
    if message_type:
        msgs = [m for m in msgs if m["message_type"] == message_type]
    if agent:
        msgs = [m for m in msgs if m["sender_agent_id"] == agent or agent in m["receiver_agent_ids"]]
    return {"trace_id": trace_id, "messages": msgs, "total": len(msgs)}


@router.get("/traces/{trace_id}/agents")
async def trace_agents(trace_id: str = TRACE_ID, include_prompts: bool = Query(default=False,
                       description="Include the full rendered model input of each LLM call")):
    r = _reader()
    _require(r, trace_id)
    execs = r.executions(trace_id, include_prompts=include_prompts)
    msgs = r.messages(trace_id)
    hist = agent_histories(execs, msgs, r.hypothesis_states(trace_id), [])
    by_agent: Dict[str, Any] = {a: {**hist[a], "execution_records": [x for x in execs if x["agent_id"] == a]}
                                for a in AGENTS}
    return {"trace_id": trace_id, "agents": by_agent, "agent_order": AGENTS, "agent_names": AGENT_NAMES}


@router.get("/traces/{trace_id}/timeline")
async def trace_timeline(trace_id: str = TRACE_ID):
    r = _reader()
    _require(r, trace_id)
    return full_timeline(r, trace_id)


@router.get("/traces/{trace_id}/graph")
async def trace_graph(trace_id: str = TRACE_ID):
    r = _reader()
    _require(r, trace_id)
    msgs = r.messages(trace_id)
    return {"trace_id": trace_id, **communication_graph(msgs), "disagreements": disagreements(msgs)}


@router.get("/traces/{trace_id}/evidence")
async def trace_evidence(trace_id: str = TRACE_ID):
    """Evidence flow: origin → retrieval stage → agent inputs → rendered prompts → citations → verification."""
    r = _reader()
    _require(r, trace_id)
    return {"trace_id": trace_id, "evidence": evidence_view(r, trace_id)}


@router.get("/traces/{trace_id}/hypotheses")
async def trace_hypotheses(trace_id: str = TRACE_ID):
    r = _reader()
    _require(r, trace_id)
    return {"trace_id": trace_id, "states": r.hypothesis_states(trace_id)}


@router.get("/analyses/{analysis_id}/trace")
async def analysis_trace(analysis_id: int = Path(..., ge=1)):
    r = _reader()
    tid = r.trace_for_analysis(analysis_id)
    if not tid:
        raise HTTPException(status_code=404, detail=f"No trace is linked to analysis {analysis_id}.")
    t = r.get_trace(tid)
    t.pop("semantic", None)
    return {"analysis_id": analysis_id, "trace_id": tid, "trace": t, **build_semantic(r, tid)}
