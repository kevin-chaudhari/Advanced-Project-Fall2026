# Mission Control for Agentic AI

**An Observability Framework for Human Oversight of Autonomous Multi-Agent Systems**

Mission Control makes a team of autonomous AI agents observable: every message, every piece of
evidence an agent actually saw, every model call, every score change and the code version are
recorded (AgentTrace), explained in the UI, and gated by explicit human-review criteria.

The system under observation is an evidence-grounded industrial fault diagnosis council with
**six cooperating agents**, a
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
* **Agent council** for hard cases: when provisional confidence is below 0.65, the runner-up is within 0.15,
  or the first-pass agents disagree, all six agents talk through typed messages (question, challenge,
  evidence share, concession, hold, risk flag, human-input request, synthesis). Each keeps its persona and
  method. Confidence is recomputed with the same factor formula and can only move on evidence: a pair is
  re-weighted only when two independent checks (signature and focused precedent) agree, at 25 % strength.
  Settings: `COUNCIL_MODE=auto|always|off`, `COUNCIL_MAX_ROUNDS` (2). Code: `harness/council.py`.
* **Collaborative agent council** (`harness/collaboration.py`): after a one-step private draft, all six agents
  build the diagnosis together — they share positions over every candidate hypothesis, question and challenge
  each other, revise by reading the board (log-linear pooling with a persona-specific openness) and reach a
  joint finding. The joint ranking shapes the hypothesis scores; the agents' agreed confidence is blended with
  the evidence confidence and capped by it. With an LLM configured, `COUNCIL_LLM_MODEL` (default `gpt-4.1`)
  voices each message in the agent's persona, claim-validated. Accuracy on the 246-scenario benchmark is equal
  or better in all modes and wrong auto-resolutions drop (2→0 combined, 13→9 real).
* **AgentTrace observability** (`harness/agent_trace/`): every run gets a `trace_id` and is persisted to SQLite
  (append-only events with sequence numbers, messages and observed deliveries, agent executions with rendered
  model input, evidence provenance from retrieval to verification, hypothesis evolution). Browse it in the
  **Trace explorer** page or via `GET /traces/*`. Full description: **[docs/AGENT_TRACE.md](docs/AGENT_TRACE.md)**.

## Data

| Knowledge base | REAL | SYNTHETIC | Notes |
|---|---|---|---|
| AFRB sensor records | 50,000 | 6,350 | 7 sensor channels; synthetic adds normal, seal, cavitation, gearbox, severity levels, missing-sensor, ambiguous and contradictory cases |
| FailureSensorIQ | 5,629 | — | sensor ↔ failure-event relevance (text) |
| Hydraulic test rig (UCI #447) | 2,205 | — | real measured 60 s load cycles; temperature, vibration (mm/s), pressure, flow; own index and reference bands — see `backend/data/real/README.md` |

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
| `GET /traces`, `GET /traces/{id}` (+ `/summary`, `/events`, `/messages`, `/agents`, `/timeline`, `/graph`, `/evidence`, `/hypotheses`), `GET /analyses/{id}/trace` | persisted AgentTrace of each run (see [docs/AGENT_TRACE.md](docs/AGENT_TRACE.md)) |

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
