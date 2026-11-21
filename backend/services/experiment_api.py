"""
/experiments/* — Experiment Lab API.

POST /experiments/plan              readings found in a question + suggested what-if values (no runs)
POST /experiments                   create an experiment and start it in the background
GET  /experiments                   list experiments with progress
GET  /experiments/{id}              runs, progress and the analysis (step divergence, factor sweeps …)
GET  /experiments/{id}/compare      step-aligned comparison of two runs (?a=&b=)
POST /experiments/{id}/cancel       stop after the current run
POST /experiments/{id}/resume       continue pending / failed runs
DELETE /experiments/{id}
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from services import experiments as ex


class PlanRequest(BaseModel):
    question: str
    dataset_type: str = "afrb"
    data_mode: str = "combined"
    points: int = Field(default=4, ge=2, le=8)


class CreateRequest(BaseModel):
    name: str = ""
    kind: str = Field(description="sensor_sweep | settings")
    question: str
    dataset_type: str = "afrb"
    data_mode: str = "combined"
    top_k: int = Field(default=8, ge=1, le=40)
    factors: Dict[str, Any] = Field(default_factory=dict,
                                    description="sensor_sweep: {sensor: [values]}; settings: {data_mode: [...], top_k: [...], drop_evidence: n}")
    source_trace_id: Optional[str] = None


class ReviewRequest(BaseModel):
    decision: str = Field(description="approve | reject | change")
    reason: str
    final_label: Optional[str] = None
    reviewer: str = ""
    experiment_id: Optional[str] = None


def _versions(rt) -> Dict[str, Any]:
    try:
        from harness.agent_trace.code_version import code_version
        cv = code_version()
    except Exception:
        cv = None
    kbs = {k: {m: len(p.records) for m, p in kb.partitions.items()} for k, kb in getattr(rt, "kbs", {}).items()}
    return {"embedder": getattr(getattr(rt, "embedder", None), "model_id", None),
            "code_version": (cv or {}).get("id") if isinstance(cv, dict) else cv, "knowledge_bases": kbs}


def build_router(get_runtime: Callable[[], Any]) -> APIRouter:
    router = APIRouter(prefix="/experiments", tags=["Experiments"])

    def _rt():
        rt = get_runtime()
        if rt is None:
            raise HTTPException(status_code=503, detail="Runtime is still starting.")
        return rt

    def _kb(dataset: str):
        rt = _rt()
        kb = rt.kbs.get(dataset)
        if kb is None or not kb.partitions:
            raise HTTPException(status_code=400, detail=f"Dataset '{dataset}' is not loaded.")
        return kb

    def _embedder_id() -> Optional[str]:
        rt = get_runtime()
        return getattr(getattr(rt, "embedder", None), "model_id", None)

    @router.post("/plan")
    async def plan(req: PlanRequest):
        kb = _kb(req.dataset_type)
        out = ex.suggest_sweep(req.question, kb, req.data_mode, req.points)
        out["data_modes"] = kb.available_modes()
        out["max_runs"] = ex.MAX_RUNS
        return out

    @router.post("")
    async def create(req: CreateRequest):
        kb = _kb(req.dataset_type)
        modes = kb.available_modes()
        if req.data_mode not in modes:
            raise HTTPException(status_code=400, detail=f"data_mode '{req.data_mode}' is not available (has {modes})")
        spec = {"question": req.question.strip(), "dataset_type": req.dataset_type, "data_mode": req.data_mode,
                "top_k": req.top_k, "factors": req.factors, "available_modes": modes,
                "bands": ex.reading_bands(kb, req.data_mode)}
        if not spec["question"]:
            raise HTTPException(status_code=400, detail="question is required")
        try:
            exp_id = ex.create_experiment(req.name.strip(), req.kind, spec, req.source_trace_id, _versions(_rt()))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        ex.start_experiment(exp_id, _rt().diagnose)
        return {"experiment_id": exp_id}

    @router.get("")
    async def list_all(limit: int = Query(default=50, ge=1, le=200), source_trace_id: Optional[str] = None,
                       kind: Optional[str] = None) -> Dict[str, List]:
        return {"items": ex.list_experiments(limit, source_trace_id, kind)}

    @router.get("/{exp_id}")
    async def get_one(exp_id: str, light: bool = False):
        out = ex.get_experiment(exp_id, _embedder_id(), light=light)
        if not out:
            raise HTTPException(status_code=404, detail="Experiment not found")
        return out

    @router.get("/{exp_id}/compare")
    async def compare(exp_id: str, a: int, b: int):
        out = ex.compare_runs(exp_id, a, b)
        if not out:
            raise HTTPException(status_code=404, detail="Run not found")
        return out

    @router.post("/{exp_id}/cancel")
    async def cancel(exp_id: str):
        ex.cancel_experiment(exp_id)
        return {"ok": True}

    @router.post("/{exp_id}/resume")
    async def resume(exp_id: str):
        if not ex.get_experiment(exp_id):
            raise HTTPException(status_code=404, detail="Experiment not found")
        ex.start_experiment(exp_id, _rt().diagnose)
        return {"ok": True}

    @router.delete("/{exp_id}")
    async def delete(exp_id: str):
        ex.cancel_experiment(exp_id)
        if not ex.delete_experiment(exp_id):
            raise HTTPException(status_code=404, detail="Experiment not found")
        return {"ok": True}

    return router


def build_insights_router(get_runtime: Callable[[], Any]) -> APIRouter:
    """/trace-insights — step breakdown, signals and trace-to-trace compare for the Trace explorer."""
    from services import trace_insights as ti
    router = APIRouter(prefix="/trace-insights", tags=["Trace insights"])

    @router.get("/compare")
    async def compare(ids: str = Query(description="comma-separated trace ids; the first is the reference"),
                      labels: Optional[str] = Query(default=None, description="optional '|'-separated display labels")):
        out = ti.compare_many(ids.split(","), labels.split("|") if labels else None)
        if len(out["traces"]) < 2:
            raise HTTPException(status_code=404, detail="Need at least two traces with a step snapshot (diagnoses run after "
                                f"step recording was added). Missing: {', '.join(out['missing']) or 'none'}")
        return out

    @router.get("/fleet/summary")
    async def fleet(origin: str = Query(default="live", pattern="^(live|experiment|all)$"), dataset: Optional[str] = None,
                    limit: int = Query(default=500, ge=10, le=5000)):
        from services.reports import fleet as fleet_summary
        return fleet_summary(origin, dataset, limit)

    @router.get("/{trace_id}/report", response_class=HTMLResponse)
    async def report(trace_id: str):
        from services.reports import run_report
        out = run_report(trace_id)
        if out is None:
            raise HTTPException(status_code=404, detail="Trace not found")
        return HTMLResponse(out, headers={"Content-Disposition": f'inline; filename="report-{trace_id}.html"'})

    @router.get("/{trace_id}")
    async def one(trace_id: str):
        out = ti.breakdown(trace_id)
        if not out:
            raise HTTPException(status_code=404, detail="No step snapshot for this trace — it was made before step recording existed.")
        return out

    return router


def build_review_router() -> APIRouter:
    """/reviews — the human reviewer's approve / reject / change decision on a diagnosis, logged per trace."""
    router = APIRouter(prefix="/reviews", tags=["Reviews"])

    @router.post("/{trace_id}")
    async def add(trace_id: str, req: ReviewRequest):
        try:
            return ex.add_review(trace_id, req.decision, req.reason, req.final_label, req.reviewer, req.experiment_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @router.get("/{trace_id}")
    async def get(trace_id: str):
        return {"items": ex.list_reviews(trace_id)}

    return router
