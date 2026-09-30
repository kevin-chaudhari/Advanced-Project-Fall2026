"""
Before/after benchmark runner.

    # baseline = the ORIGINAL code (git tag `baseline`) checked out elsewhere
    python evaluation/benchmark.py --system baseline --backend-dir /path/to/original/backend --out results/baseline.json
    # improved harness (this backend)
    python evaluation/benchmark.py --system harness --backend-dir . --out results/harness.json

Both runs use the identical held-out scenario file (data/synthetic/test_scenarios.csv)
and the identical scoring code (bench_metrics.py).  Held-out REAL AFRB records
are excluded from retrieval so a record can never retrieve itself.

LLM mode: whatever the environment configures.  With no API key / Ollama
unavailable, both systems run their offline fallback path.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import os
import re
import sys
import time
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("bench_metrics", EVAL_DIR / "bench_metrics.py")
bm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bm)  # type: ignore

import pandas as pd  # noqa: E402


def _afrb_label(content: str):
    ans = re.search(r"Correct Answer:\s*([ABCD])", content)
    if not ans:
        return None
    opt = re.search(rf"Option {ans.group(1)}:\s*(.+)", content)
    return opt.group(1).strip() if opt else None


# ─────────────────────────────────────────────────────────────────────────────
# Adapters
# ─────────────────────────────────────────────────────────────────────────────

class BaselineAdapter:
    """Runs the original pipeline exactly as main.py's /query would."""

    def __init__(self, backend_dir: Path):
        sys.path.insert(0, str(backend_dir))
        os.chdir(backend_dir)
        from rag.embedder import Embedder  # type: ignore
        from rag.faiss_store import FAISSStore  # type: ignore
        from agents.orchestrator import AgentOrchestrator  # type: ignore
        self.store = FAISSStore(Embedder())
        assert self.store._load("afrb"), "baseline AFRB index missing"
        self.orch = AgentOrchestrator()

    async def run(self, case: dict, top_k: int = 5):
        t0 = time.perf_counter()
        docs = self.store.search("afrb", case["question"], top_k=top_k + 1)
        excl = case.get("exclude_record_id") or ""
        docs = [d for d in docs if not (excl and f"Question Id: {excl}\n" in d["content"] + "\n")][:top_k]
        resp = await self.orch.run(question=case["question"], dataset_type="afrb", retrieved_docs=docs)
        latency = (time.perf_counter() - t0) * 1000
        retrieved = [{"content": d["content"], "label": _afrb_label(d["content"])} for d in docs]
        return resp, retrieved, latency, [], None, []


class HarnessAdapter:
    """Runs the improved orchestration harness (this repository)."""

    def __init__(self, backend_dir: Path, data_mode: str):
        sys.path.insert(0, str(backend_dir))
        os.chdir(backend_dir)
        from services.runtime import build_runtime  # type: ignore
        self.rt = build_runtime(load_failure_iq=False)
        self.data_mode = data_mode

    async def run(self, case: dict, top_k: int = 8):
        t0 = time.perf_counter()
        excl = [case["exclude_record_id"]] if case.get("exclude_record_id") else []
        resp = await self.rt.diagnose(case["question"], "afrb", self.data_mode, top_k=top_k,
                                      exclude_record_ids=excl)
        latency = (time.perf_counter() - t0) * 1000
        h = resp.get("harness", {})
        retrieved = [{"content": e.get("content_text", ""), "label": e.get("label"),
                      "evidence_id": e.get("evidence_id")} for e in h.get("evidence", [])]
        derived = [d.get("value") for d in h.get("derived_values", []) if isinstance(d.get("value"), (int, float))]
        return resp, retrieved, latency, derived, h.get("predicted_label"), h.get("declared_rule_thresholds", [])


async def main_async(args):
    backend = Path(args.backend_dir).resolve()
    cases = pd.read_csv(Path(args.cases).resolve(), keep_default_na=False).to_dict("records")
    if args.limit:
        cases = cases[: args.limit]
    adapter = (BaselineAdapter(backend) if args.system == "baseline"
               else HarnessAdapter(backend, args.data_mode))
    rows = []
    for i, case in enumerate(cases, 1):
        try:
            resp, retrieved, latency, derived, structured, rules = await adapter.run(case)
        except Exception as exc:  # a crash is scored as a wrong, ungrounded answer
            print(f"[{case['case_id']}] ERROR {exc}", file=sys.stderr)
            resp, retrieved, latency, derived, structured, rules = {}, [], 0.0, [], None, []
        rows.append(bm.score_case(case, resp, retrieved, latency, derived, structured, rules))
        if i % 25 == 0:
            print(f"  {i}/{len(cases)} cases", file=sys.stderr)
    summary = bm.summarise(rows)
    out = {"system": args.system, "data_mode": args.data_mode if args.system == "harness" else "real",
           "llm_provider": os.getenv("LLM_PROVIDER", "openai"),
           "llm_available": bool(os.getenv("OPENAI_API_KEY")) or os.getenv("LLM_PROVIDER") == "ollama",
           "summary": summary, "cases": rows}
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, indent=2, default=str))
    print(json.dumps({k: v for k, v in summary.items() if k != "by_category"}, indent=2))


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--system", choices=["baseline", "harness"], required=True)
    p.add_argument("--backend-dir", default=".")
    p.add_argument("--cases", default=str(EVAL_DIR.parent / "data" / "synthetic" / "test_scenarios.csv"))
    p.add_argument("--data-mode", default="combined", choices=["real", "synthetic", "combined"])
    p.add_argument("--out", required=True)
    p.add_argument("--limit", type=int, default=0)
    args = p.parse_args()
    args.out = str(Path(args.out).resolve())
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
