"""
Multi-Agent Industrial Diagnostic AI System — FastAPI Backend
Main application entry point.

The six existing agents now run inside an orchestration *harness*
(see agents/orchestrator.py and harness/): shared DiagnosticState, evidence IDs,
multi-stage RAG, controlled feedback with targeted re-retrieval, deterministic
claim validation, measured confidence and an explicit human-review gate.
"""

import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()

from models.schemas import HealthResponse, LoadDataResponse, QueryRequest, QueryResponse  # noqa: E402
from services.dataset_summary import evaluation_results, summarise_kb  # noqa: E402
from services.runtime import INDEX_NAMES, Runtime, build_runtime  # noqa: E402
from utils.db import get_agent_aggregates, get_analyses, init_db, save_analysis  # noqa: E402
from utils.llm_client import llm_client  # noqa: E402
from utils.logger import setup_logger  # noqa: E402

logger = setup_logger(__name__)

runtime: Optional[Runtime] = None
_summary_cache: dict = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    global runtime
    logger.info("[STARTUP] Initialising Industrial Diagnostic AI System …")
    try:
        init_db()
    except Exception as exc:
        logger.warning("[WARN] Could not initialise analysis DB: %s", exc)
    runtime = build_runtime()
    for name, kb in runtime.kbs.items():
        logger.info("[OK] %s knowledge base: %s", name, {k: len(p.records) for k, p in kb.partitions.items()})
    logger.info("[OK] System ready (LLM: %s).", "configured" if llm_client.is_available() else "not configured — deterministic agents")
    yield
    logger.info("[STOP] Shutting down …")


app = FastAPI(title="Industrial Diagnostic AI System",
              description="Six-agent diagnostic harness with evidence-grounded, multi-stage RAG",
              version="3.0.0", lifespan=lifespan)

origins = os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",")
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])


def _loaded(name: str) -> bool:
    return bool(runtime and name in runtime.kbs and runtime.kbs[name].partitions)


def _bg_save_analysis(question: str, dataset: str, result: dict) -> None:
    try:
        report = result.get("analysis_report", {})
        if not report:
            return
        save_analysis(question=question, dataset=dataset, analysis_report=report,
                      final_diagnosis=result.get("final_diagnosis", ""),
                      confidence=float(result.get("confidence", 0.0)),
                      latency_ms=float(result.get("harness", {}).get("latency_ms", 0.0)))
    except Exception as exc:
        logger.error("[BG] Failed to save analysis: %s", exc, exc_info=True)


# ─── System ──────────────────────────────────────────────────────────────────

@app.get("/health", response_model=HealthResponse, tags=["System"])
async def health():
    return HealthResponse(
        status="ok", failure_iq_loaded=_loaded("failure_iq"), afrb_loaded=_loaded("afrb"),
        message="Industrial Diagnostic AI System is running",
        data_modes={k: kb.available_modes() for k, kb in (runtime.kbs.items() if runtime else [])},
        record_counts={k: {st: len(p.records) for st, p in kb.partitions.items()} for k, kb in (runtime.kbs.items() if runtime else [])},
        llm_mode="llm+deterministic" if llm_client.is_available() else "deterministic",
    )


@app.get("/index-status", tags=["System"])
async def index_status():
    report = {}
    for (kb_name, st), name in INDEX_NAMES.items():
        path = runtime.store.persist_path / f"{name}.faiss"
        idx = runtime.store.indexes.get(name)
        report[name] = {"dataset": kb_name, "source_type": st, "in_memory": idx is not None,
                        "on_disk": path.exists(), "vectors": idx.ntotal if idx is not None else 0,
                        "embedder": runtime.store.meta.get(name, {}).get("embedder"),
                        "disk_size_mb": round(path.stat().st_size / 1_048_576, 2) if path.exists() else 0}
    return {"indexes": report, "cache_directory": str(runtime.store.persist_path)}


# ─── Data ────────────────────────────────────────────────────────────────────

@app.post("/load-data", response_model=LoadDataResponse, tags=["Data"])
async def load_data(dataset_type: str = "failure_iq", file: UploadFile | None = File(None),
                    rebuild: bool = Query(default=False)):
    dataset_type = dataset_type.lower().strip()
    _summary_cache.clear()
    try:
        if dataset_type == "failure_iq":
            if rebuild:
                runtime.store.persist_path.joinpath("failure_iq.faiss").unlink(missing_ok=True)
            kb = runtime.load_failure_iq()
        elif dataset_type == "afrb":
            real_csv = None
            if file is not None:
                upload_dir = Path("./uploads")
                upload_dir.mkdir(exist_ok=True)
                csv_path = upload_dir / Path(file.filename).name
                csv_path.write_bytes(await file.read())
                real_csv = str(csv_path)
                INDEX_NAMES[("afrb", "real")] = "afrb_upload"   # never overwrite the original 50k index
            if rebuild:
                runtime.store.persist_path.joinpath(f"{INDEX_NAMES[('afrb', 'real')]}.faiss").unlink(missing_ok=True)
            kb = runtime.load_afrb(real_csv=real_csv)
        else:
            raise HTTPException(status_code=400, detail=f"Unknown dataset_type '{dataset_type}'.")
        for m in kb.available_modes():
            kb.reference(m)
        n = sum(len(p.records) for p in kb.partitions.values())
        return LoadDataResponse(success=True, dataset=dataset_type, documents_loaded=n,
                                message=f"Loaded partitions: {', '.join(f'{k}={len(p.records)}' for k, p in kb.partitions.items())}")
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Error loading %s: %s", dataset_type, exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/rebuild-index", tags=["Data"])
async def rebuild_index(dataset_type: str = "failure_iq"):
    return await load_data(dataset_type=dataset_type, file=None, rebuild=True)


@app.get("/datasets/summary", tags=["Data"])
async def datasets_summary(dataset: str = "afrb"):
    if not _loaded(dataset):
        raise HTTPException(status_code=400, detail=f"Dataset '{dataset}' not loaded.")
    if dataset not in _summary_cache:
        _summary_cache[dataset] = summarise_kb(runtime.kbs[dataset])
    return _summary_cache[dataset]


# ─── Query ───────────────────────────────────────────────────────────────────

@app.post("/query", response_model=QueryResponse, tags=["Query"])
async def query(request: QueryRequest, background_tasks: BackgroundTasks):
    dataset = request.dataset_type.lower().strip()
    if not _loaded(dataset):
        raise HTTPException(status_code=400, detail=f"Dataset '{dataset}' not loaded. POST /load-data?dataset_type={dataset} first.")
    mode = request.data_mode.lower().strip()
    if mode not in ("real", "synthetic", "combined"):
        raise HTTPException(status_code=400, detail="data_mode must be real, synthetic or combined.")
    try:
        result = await runtime.diagnose(request.question, dataset, mode, top_k=request.top_k)
    except Exception as exc:
        logger.error("Diagnosis failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Diagnosis failed: {exc}")
    background_tasks.add_task(_bg_save_analysis, request.question, dataset, result)
    return QueryResponse(**result)


@app.post("/agents/run", tags=["Agents"])
async def agents_run(request: QueryRequest, background_tasks: BackgroundTasks):
    return await query(request, background_tasks)


# ─── Analysis history & evaluation ───────────────────────────────────────────

@app.get("/analyses", tags=["Analysis"])
async def get_analysis_history(limit: int = Query(default=50, ge=1, le=200), dataset: Optional[str] = None):
    try:
        records = get_analyses(limit=limit, dataset_filter=dataset)
        return {"records": records, "count": len(records)}
    except Exception as exc:
        logger.error("Failed to fetch analyses: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Could not retrieve analysis history.")


@app.get("/analyses/agent-report", tags=["Analysis"])
async def get_agent_report(limit: int = Query(default=200, ge=1, le=500), dataset: Optional[str] = None):
    try:
        return get_agent_aggregates(limit=limit, dataset_filter=dataset)
    except Exception as exc:
        logger.error("Failed to compute agent report: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Could not compute agent performance report.")


@app.get("/evaluation/results", tags=["Analysis"])
async def get_evaluation_results():
    """Before/after benchmark summaries produced by evaluation/benchmark.py."""
    return evaluation_results()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True, log_level="info")
