# Industrial Diagnostic AI System

Evidence-grounded industrial fault diagnosis with **six cooperating agents**, a
deterministic orchestration harness, multi-stage RAG over FAISS, and a clearly
labelled synthetic dataset for coverage and hallucination testing.

> Full design notes, before/after measurements and the file-by-file change list:
> **[docs/HARNESS_IMPROVEMENTS.md](docs/HARNESS_IMPROVEMENTS.md)**

## What it does

```
Query → query preparation → multi-stage RAG (semantic · metadata · numeric · historical → rerank)
      → Diagnostic Expert ‖ Pattern Recognition ‖ Rapid Triage      (independent perspectives)
      → Verification (adversarial) → Evidence check ─weak→ targeted RAG → re-run only the affected agent
      → Ambiguity (measured uncertainty) → Final coordinator (claim-validated) → Human-review gate
```

* Six agents, no agent explosion. Evidence checking, targeted retrieval, claim
  validation, confidence and the review gate are deterministic code.
* Every retrieved record is an evidence object (`EV-001…`) with REAL / SYNTHETIC
  provenance; harness calculations are `D-001…`. Agents cite IDs.
* Unsupported numbers, invalid IDs and unknown labels are removed before the answer.
* Confidence is computed from visible factors; agreement never substitutes for evidence.
* `AUTO_RESOLVE` vs `REQUIRES_HUMAN_REVIEW` is decided by explicit criteria (G1–G8).
* Works with OpenAI, Ollama, or **no LLM at all** (deterministic agents).

## Data

| Knowledge base | REAL | SYNTHETIC | Notes |
|---|---|---|---|
| AFRB sensor records | 50,000 | 6,350 | 7 sensor channels; synthetic adds normal, seal, cavitation, gearbox, severity levels, missing-sensor, ambiguous and contradictory cases |
| FailureSensorIQ | 5,629 | — | sensor ↔ failure-event relevance (text) |

Synthetic rows are generated deterministically by
`backend/data_generator/synthetic_industrial_generator.py`, carry
`Source_Type=synthetic` / `Synthetic_Scenario` / `Synthetic_Generator_Version` /
`Synthetic_Record_ID`, live in a separate FAISS index, and are selectable with the
dataset mode **real / synthetic / combined**.

## Setup

```bash
# backend
cd backend
pip install -r requirements.txt
cp .env.example .env          # choose LLM_PROVIDER / key, or leave the key empty for deterministic mode
uvicorn main:app --host 0.0.0.0 --port 8000
```

Startup loads the persisted FAISS indexes (`faiss_indexes/`). The original
50,000-vector AFRB index is reused as-is; the synthetic and FailureSensorIQ
indexes are shipped prebuilt. If an index is missing it is rebuilt once.

```bash
# frontend
cd frontend
npm install
npm run dev                   # http://localhost:5173
```

## API

| Endpoint | Purpose |
|---|---|
| `GET /health` | status, available dataset modes, record counts, LLM mode |
| `POST /query` | `{"question", "dataset_type": "afrb"\|"failure_iq", "data_mode": "real"\|"synthetic"\|"combined", "top_k"}` → final diagnosis, confidence, `review_decision`, and the full `harness` state (evidence, hypotheses, agents, feedback loop, confidence factors, gate, claim validation, timeline) |
| `GET /datasets/summary?dataset=afrb` | composition and data-quality statistics |
| `GET /evaluation/results` | before/after benchmark summaries |
| `POST /load-data`, `POST /rebuild-index`, `GET /index-status` | data management (an uploaded AFRB CSV becomes a new REAL partition; the original index is never overwritten) |
| `GET /analyses`, `GET /analyses/agent-report` | stored analyses |

## Tests and evaluation

```bash
cd backend
python -m pytest tests -q                                           # 23 offline tests
python -m data_generator.synthetic_industrial_generator             # regenerate synthetic data + validation report
python evaluation/benchmark.py --system harness --data-mode combined --out evaluation/results/harness_combined.json
```

Headline results on 246 held-out cases (no LLM in either system — see the caveats
in the docs): diagnostic accuracy 25.6 % → 94.3 %, accuracy on held-out real
records 14.3 % → 94.3 %, unsupported numeric claims 24.7 % → 0 %, retrieval
hit@5 17.9 % → 96.1 %.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `LLM_PROVIDER` | `openai` | `openai` or `ollama` |
| `OPENAI_API_KEY` / `OLLAMA_*` | — | LLM access; without it agents run deterministically |
| `HARNESS_USE_LLM` | `auto` | `false` forces deterministic agents |
| `MAX_FEEDBACK_ROUNDS` | `2` | targeted re-retrieval rounds |
| `EMBEDDING_MODEL` | `all-MiniLM-L6-v2` | hub name or local path |
| `AFRB_CSV_PATH`, `AFRB_SYNTHETIC_CSV_PATH` | `./data/…` | knowledge-base sources |
| `SYSTEM_ANALYSIS_LLM` | `false` | legacy per-query LLM meta-evaluation |
