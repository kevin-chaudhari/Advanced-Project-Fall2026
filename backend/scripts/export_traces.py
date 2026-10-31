"""
Export AgentTraces to files.

Two sources, same output files:
  * the SQLite database directly (default) — the backend does not need to be running
  * a running backend over HTTP (--api http://localhost:8000)

Examples (run from the backend folder):
  python scripts/export_traces.py --list                         # what is stored
  python scripts/export_traces.py --latest                       # newest trace → JSON + transcript
  python scripts/export_traces.py --latest 10 --format all       # 10 newest, every format
  python scripts/export_traces.py --trace-id TR-20261031132237-3853e22c --format json
  python scripts/export_traces.py --analysis-id 4                # the trace of a saved analysis
  python scripts/export_traces.py --all --dataset afrb --out exports/afrb
  python scripts/export_traces.py --latest --api http://localhost:8000
  python scripts/export_traces.py --latest --db "C:/path/to/analysis_store.db"

Formats: json (complete bundle), transcript (readable .md conversation),
messages_csv, events_csv, executions_csv, evidence_csv, or all.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

FORMATS = ("json", "transcript", "messages_csv", "events_csv", "executions_csv", "evidence_csv")


def _http(api: str, path: str, params=None, raw: bool = False):
    url = api.rstrip("/") + path + (("?" + urllib.parse.urlencode(params)) if params else "")
    with urllib.request.urlopen(url, timeout=120) as r:
        data = r.read()
    return data.decode("utf-8") if raw else json.loads(data)


def main() -> int:
    ap = argparse.ArgumentParser(description="Export AgentTraces to JSON / Markdown / CSV files.")
    pick = ap.add_mutually_exclusive_group()
    pick.add_argument("--trace-id", action="append", help="trace ID (repeatable)")
    pick.add_argument("--latest", nargs="?", type=int, const=1, help="newest N traces (default 1)")
    pick.add_argument("--all", action="store_true", help="every stored trace")
    pick.add_argument("--analysis-id", type=int, help="the trace linked to a saved analysis")
    pick.add_argument("--list", action="store_true", help="list stored traces and exit")
    ap.add_argument("--format", default="json,transcript",
                    help="comma-separated: " + ", ".join(FORMATS) + ", or all (default json,transcript)")
    ap.add_argument("--out", default="exports/traces", help="output folder (default exports/traces)")
    ap.add_argument("--dataset", help="only traces of this dataset (afrb, hydraulic, failure_iq)")
    ap.add_argument("--no-prompts", action="store_true", help="leave out the rendered LLM prompts")
    ap.add_argument("--api", help="read from a running backend instead of the database, e.g. http://localhost:8000")
    ap.add_argument("--db", help="SQLite file (default: AGENT_TRACE_DB_PATH, ANALYSIS_DB_PATH or ./data/analysis_store.db)")
    a = ap.parse_args()

    fmts = list(FORMATS) if a.format == "all" else [f.strip() for f in a.format.split(",") if f.strip()]
    bad = [f for f in fmts if f not in FORMATS]
    if bad:
        ap.error(f"unknown format(s) {bad}")

    if a.db:
        os.environ["AGENT_TRACE_DB_PATH"] = a.db
    os.chdir(BACKEND)                      # the default DB path is relative to the backend folder

    # ── which traces ─────────────────────────────────────────────────────────
    if a.api:
        def listing(limit):
            p = {"limit": min(limit, 200)}
            if a.dataset:
                p["dataset"] = a.dataset
            return _http(a.api, "/traces", p)["traces"]
    else:
        from harness.agent_trace.trace_repository import TraceReader
        from harness.agent_trace import trace_export
        reader = TraceReader()

        def listing(limit):
            return reader.list_traces(limit=limit, dataset=a.dataset)[0]

    if a.list:
        rows = listing(200)
        if not rows:
            print("No traces stored yet. Ask a question in the app first.")
        for t in rows:
            print(f"{t['trace_id']}  {t['started_at'][:19]}  {t['dataset_type']:<10} {t['status']:<22} "
                  f"{str(t.get('final_label')):<26} {t.get('total_messages') or 0:>3} msgs  {t['query'][:60]}")
        return 0
    if a.trace_id:
        ids = a.trace_id
    elif a.analysis_id is not None:
        if a.api:
            ids = [_http(a.api, f"/analyses/{a.analysis_id}/trace")["trace_id"]]
        else:
            tid = reader.trace_for_analysis(a.analysis_id)
            if not tid:
                print(f"No trace is linked to analysis {a.analysis_id}.", file=sys.stderr)
                return 1
            ids = [tid]
    else:
        n = 1_000_000 if a.all else (a.latest or 1)
        ids = [t["trace_id"] for t in listing(n)][:n]
    if not ids:
        print("No traces found.", file=sys.stderr)
        return 1

    # ── write files ──────────────────────────────────────────────────────────
    out = Path(a.out)
    if not out.is_absolute():
        out = BACKEND / out
    out.mkdir(parents=True, exist_ok=True)
    ext = {"json": "json", "transcript": "md", "messages_csv": "messages.csv", "events_csv": "events.csv",
           "executions_csv": "executions.csv", "evidence_csv": "evidence.csv"}
    done = 0
    for tid in ids:
        if a.api:
            texts = {f: _http(a.api, f"/traces/{tid}/export", {"format": f, "include_prompts": str(not a.no_prompts).lower()},
                              raw=True) for f in fmts}
        else:
            try:
                b = trace_export.bundle(reader, tid, include_prompts=not a.no_prompts)
            except KeyError:
                print(f"  {tid}: not found", file=sys.stderr)
                continue
            texts = {f: trace_export.render(b, f) for f in fmts}
        for f, text in texts.items():
            path = out / f"{tid}.{ext[f]}"
            path.write_text(text, encoding="utf-8")
            print(f"  wrote {path}")
        done += 1
    print(f"Exported {done} of {len(ids)} trace(s) to {out}")
    return 0 if done == len(ids) else 1


if __name__ == "__main__":
    raise SystemExit(main())
