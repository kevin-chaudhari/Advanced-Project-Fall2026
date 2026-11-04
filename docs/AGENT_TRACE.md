# Collaborative agent council and AgentTrace

How the six agents build a diagnosis **together**, how every message between them is recorded as an
**AgentTrace**, and how to inspect it (API and the **Trace explorer** page).

The tracing design is adapted from the AgentTrace semantic layer in
[IBM_Project2](https://github.com/DevikaVishnu/IBM_Project2) (`agenttrace.semantic/0.3`): only observable
things are recorded (inputs, outputs, messages, tool calls, evidence references, decisions — no hidden
reasoning); raw records are kept apart from derived views; anything the system cannot establish is
`UNKNOWN` / `NOT_APPLICABLE`, never guessed. A real exported trace is in
[`docs/examples/agent_trace_example.json`](examples/agent_trace_example.json).

---

## 1. From independent first pass to a collaborative council

| Before | Now |
|---|---|
| Diagnostic Expert, Pattern Recognition and Rapid Triage worked independently and handed their verdicts to Verification. | Each writes a **one-step private draft**, then all six agents work as one **council**: they share positions over every candidate hypothesis, question and challenge each other, and revise by reading the board until they converge. |
| Agents talked only in the escalation council on hard cases. | The collaboration runs on **every** diagnosis; the escalation council still convenes on hard cases. |
| Confidence came only from evidence factors. | The agents' **agreed confidence** is blended with the evidence confidence, **capped by it**. |
| The first pass's agreement was only a confidence factor. | The council's **joint ranking** is blended into the hypothesis scores Verification checks. Each first-pass agent's finding is its post-discussion position. |

**Why keep a private draft.** If the agents start from each other's views, they agree for the wrong
reason (herding). Disagreement between the independent drafts still signals contested evidence: if
the drafts disagreed, Verification flags it even when the council has since converged, so the feedback
loop still goes looking for more evidence.

### Results on the 246-scenario benchmark (offline knowledge base, deterministic agents)

| Mode | Accuracy before → after | Auto-resolved (correct) before → after | Wrong but auto-resolved |
|---|---|---|---|
| combined | 227 → 227 | 163 (161) → 133 (133) | 2 → **0** |
| real | 181 → **182** | 130 (117) → 112 (103) | 13 → **9** |
| synthetic | 188 → **190** | 102 (89) → 85 (73) | 13 → **12** |

Accuracy is equal or better in every mode. The council's confidence blend makes the gate more
cautious: fewer cases auto-resolve, and fewer of those are wrong. The cost is that more correct cases
are sent to a person; review alignment with the scenarios' expected ambiguity drops from 0.82 to 0.74
(combined). `COLLAB_CONF_WEIGHT=0.25` auto-resolves 147 combined cases (146 correct) with the same accuracy.

Tuning used `COLLAB_SCORE_WEIGHT` ∈ {0.15, 0.25, 0.35, 0.5} × `COLLAB_CONF_WEIGHT` ∈ {0.25, 0.35, 0.5}.
It also surfaced and fixed three issues:
- council bookkeeping counted collaboration-phase questions;
- re-executed agents dropped back to their draft;
- evidence thresholds read council-adjusted scores.

---

## 2. How the council works

```
draft        DE · PR · RT write private drafts (parallel, no messages)
open         Coordinator → QUESTION: the candidates on the table
share        DE, PR, RT → FINDING with a full position (belief over every candidate, from their own method)
             Verification → EVIDENCE_SHARE with its evidence-balance position
separate     Ambiguity reads the positions; if the top two are within 0.15 → QUESTION to DE and PR;
             DE answers with a discriminating-channel test (and folds it into its own view), PR with precedent
critique     each participant reads the others' positions and CHALLENGEs / COUNTER_ARGUEs any leading label
             its own method gives < 60 % of its own lead (once per pair)
update       each participant reads positions, critiques and answers from its inbox and revises:
                 position = own view^(1−α) · Π peer positions^(α/n)        (log-linear pooling)
             then answers each critique (RESPONSE retain/qualify, or CONCESSION) and posts POSITION_UPDATE / HOLD
repeat       critique + update until all leads agree and nothing moves > 2 points, or COLLAB_MAX_ROUNDS (3)
joint        Coordinator → SYNTHESIS: joint ranking (geometric mean of positions), council confidence
             (mean belief in the joint label), dissent, changes of mind
verify       Verification checks the joint ranking; agents send VERIFICATION_REQUESTs, get claim-by-claim
             VERIFICATION_RESULTs, and qualify/withdraw where claims fail
re-sync      after targeted retrieval, the agents resume from where the council left them plus the new evidence
uncertainty  Ambiguity → UNCERTAINTY_FLAGs; escalation council on hard cases (unchanged rules)
synthesis    Coordinator reads its inbox → SYNTHESIS on what the final decision rests on
```

| Agent | Own-method view | Openness α | Critiques with | Answers |
|---|---|---|---|---|
| Diagnostic Expert | hypothesis evidence scores (signature fit + case vote) | 0.50 (integrator) | COUNTER_ARGUMENT | discriminating-channel test |
| Pattern Recognition | similarity-weighted precedent shares; abstains when there is no historical match | 0.35 | COUNTER_ARGUMENT | precedent split |
| Rapid Triage | signature-direction rule on out-of-band channels; consistency rules → Sensor Malfunction | 0.25, **0 when a safety rule fires** | CHALLENGE | — |
| Verification | evidence balance (supporting vs contradicting items × score) | 0.20 (evidence-first) | CHALLENGE | claim checks |
| Ambiguity Detection | — (measures the split, asks the separating question) | — | — | — |
| Final Coordinator | — (opens, moderates, states the joint finding) | — | — | — |

Positions travel only as messages. An agent updates from what it read in its inbox: the trace records
the read before the update, and every update names whose positions it read and who moved it. Within a
step, every agent decides from the board as it stood when the step began, so the speaking order never
changes the outcome. A failed agent abstains instead of voting.

**What the council changes, and what it never changes.**
- Changes: the hypothesis ranking (`score' = (1−w)·score + w·mass·joint`, w = 0.5), each first-pass
  agent's finding, and the confidence (`final = min(evidence, (1−β)·evidence + β·council)`, β = 0.5).
- Never changes: claim validation, the evidence-confidence factors, the review-gate criteria, and the
  evidence thresholds. "Insufficient evidence", the gate margin and evidence confidence read the scores
  with the council's adjustment removed, so agreement cannot make weak evidence look sufficient.

### GPT voicing (`COUNCIL_LLM_MODEL`, default `gpt-4.1`)

When an LLM is configured, every council message is reworded by `COUNCIL_LLM_MODEL` in the agent's
persona: Dr. Vasquez's reasoning, Dr. Patel's statistics, Commander Chen's terse safety-first style,
and so on. The positions and numbers still come from the methods. The voiced text is rejected and the
method text kept if it:
- drops the leading label;
- cites an ID not in the facts;
- states a number the facts don't contain;
- fails the deterministic claim validator.

Each message records `voice` (`llm` or `method`), `voice_model`, the original `method_text`, and the
rejection reason when there is one. The exact prompt of every voicing call is stored on the agent's
execution. Reasoning models (`o4-mini`, `o3`, `gpt-5*`) are supported: the request drops `temperature`
and uses `max_completion_tokens`. Without an LLM, agents speak in their method text.

### Real example (trace `TR-20261031132237-3853e22c`, AFRB combined, full knowledge base)

| # | From → To | Type | Content (abridged) |
|---|---|---|---|
| draft | — | — | DE Bearing Wear 37 %, PR Bearing Wear 53 %, **RT Rotor Imbalance 39 %**, Verification Bearing Wear 37 % |
| M-006 | Ambiguity → DE, PR | QUESTION | split between Bearing Wear (42 %) and Rotor Imbalance (36 %): which channels separate them? |
| M-007 | DE → all | EVIDENCE_SHARE | current 71.5 A closer to Bearing Wear, temperature 78.3 °C closer to Rotor Imbalance … |
| M-008 | PR → all | EVIDENCE_SHARE | precedent 56 % Bearing Wear vs 44 % Rotor Imbalance |
| M-011 | RT → all | POSITION_UPDATE | Bearing Wear 38 %, Rotor Imbalance 37 % (was Rotor Imbalance 39 %); DE, PR and Verification moved me |
| M-021 | Coordinator → all | SYNTHESIS | joint finding Bearing Wear 39 % (next Rotor Imbalance 35 %), converged |
| M-025…27 | Verification → each | VERIFICATION_RESULT | all claims SUPPORTED; Bearing Wear is the best-supported hypothesis |
| re-sync | — | — | after targeted retrieval, RT's rules pull it back to Rotor Imbalance 37 %: recorded as **dissent** |
| M-049 | Coordinator → all | SYNTHESIS | Bearing Wear, confidence 0.17 (evidence 0.17, council 0.39), REQUIRES_HUMAN_REVIEW |

---

## 3. AgentTrace architecture

```
backend/harness/agent_trace/
  trace_schema.py      enums (EventType, MessageType, Observed, EvidenceRelation, HypothesisStatus), API models
  trace_manager.py     TraceRecorder: one per run; sequence numbers, ContextVar for the current agent execution,
                       hooks for posts / inbox reads / LLM calls / tools, completion and failure
  trace_repository.py  SQLite DDL, TraceWriter (write-through, append-only events), TraceReader
  trace_analyzer.py    derived views: graph, timeline segments, disagreements, evidence flow, agent histories, summary
backend/harness/collaboration.py  the collaborative council (views, pooling, rounds, joint finding, disputes)
backend/services/trace_api.py FastAPI router for /traces/*
```

**How it is wired in:**

- `DiagnosticState` holds the recorder as a private attribute.
- `state.post()`, `state.inbox()`, `state.inbox_all()` and `state.read_board()` report to it. Reading an inbox is what makes a message RECEIVED.
- The orchestrator wraps every `analyze`, `deliberate`, collaboration step (`collab_share`, `collab_critique`, `collab_update`, …) and verification-exchange step as an *execution*.
- `utils/llm_client.generate_json` reports the exact rendered prompt of every model call. The ContextVar attributes it to the right agent even under `asyncio.gather`.

**Failure handling:**

- Tracing never breaks a diagnosis. Each recorder method catches its own errors and counts them in `write_errors`.
- A failing agent becomes an execution with status `FAILED` and an `AGENT_FAILED` event, and the trace finishes as `COMPLETED_WITH_ERRORS`.
- An exception that aborts the pipeline marks the trace `FAILED` with a `TRACE_FAILED` event. Everything recorded before it is already committed.

**Concurrency:**

- Each run has its own recorder, sequence counter, SQLite connection and context.
- Per-run retrieval options (`top_k`, excluded record IDs) moved from the shared orchestrator onto the run (`state._run_opts`). Previously two concurrent requests could overwrite each other's settings.

### Distinctions preserved

| Level | Meaning | Where recorded |
|---|---|---|
| Available | In the knowledge base | not enumerated (the KB holds ~64k records) |
| Retrieved | Put in this run's bundle by a retrieval action | `trace_evidence`, `RETRIEVED` link, `EVIDENCE_RETRIEVED` event |
| Delivered (state) | In the `DiagnosticState` handed to the agent call | `IN_AGENT_INPUT` link, `EVIDENCE_DELIVERED` event |
| Delivered (prompt) | The ID occurs in the exact text sent to the model | `IN_RENDERED_INPUT` link, TRUE/FALSE. FALSE is recorded only because the complete prompt was captured; deterministic executions report `NOT_APPLICABLE` |
| Referenced | The agent's output, claim or message cites it | `CITED_BY_AGENT`, `CITED_BY_CLAIM`, `CITED_IN_MESSAGE` |
| Asserted | A claim the agent made (claim ID is stable per agent and statement) | `claims_json` on the execution |
| Verified | Verification checked a claim citing it | `VERIFIED` link (SUPPORTED / DERIVED / UNSUPPORTED / UNCHECKABLE) |

- **Messages:** "addressed to" is separate from "read by". A delivery row exists only when the recipient's code read it (`inbox_read`, `board_read`) or the message ID occurred in its rendered prompt (`rendered_prompt`). Unread messages show as dashed edges in the graph.
- **Unknown evidence IDs** in a message are kept as written, flagged in `payload._trace_unknown_evidence_ids`, and never turned into evidence records.

---

## 4. Trace schema (`ida.agenttrace/1.1`)

**Tables** (in the analysis SQLite file):

| Table | Key | Content |
|---|---|---|
| `agent_traces` | `trace_id` | run-level record: query, dataset, data mode, LLM provider/model, config, **code version** (`code_version`, `code_version_json`), status, timestamps, final label/confidence/review, totals, error, `semantic_json` snapshot |
| `trace_events` | (`trace_id`, `seq`) | **append-only** raw events; `event_id` unique; `UNIQUE(trace_id, dedup_key)` makes repeated observations no-ops |
| `trace_messages` | (`trace_id`, `message_id`) | every agent message (global ID = `trace_id:M-xxx`) with sender execution, recipients, type, evidence, hypothesis IDs, parent / response-to, challenge and resolution status |
| `trace_message_deliveries` | (`trace_id`, `message_id`, `receiver`, `via`) | observed reads |
| `trace_agent_executions` | (`trace_id`, `execution_id`) | one per analyze / deliberate / exchange step: input summary, evidence in input, rendered model input, LLM calls (sha256, sizes, duration), output, finding, confidence, hypotheses, claims, messages sent/read, tool calls, status, error |
| `trace_evidence` | (`trace_id`, `evidence_id`) | EV records (provenance REAL/SYNTHETIC, dataset, record ID, label, retrieval action/method/round/score, full selection reason) and D values, each with its **full content**: `content_json` (sensors + every metadata field; for D values `value`/`text`/`inputs`), `content_text` and `content_sha256` |
| `trace_evidence_links` | (`trace_id`, `evidence_id`, `relation`, `subject_id`) | the relations in §3 |
| `trace_hypothesis_states` | (`trace_id`, `seq`) | PROPOSED / RETAINED / CHALLENGED / QUALIFIED / MODIFIED / REJECTED / UNRESOLVED / FINAL per agent, with the message or execution that caused it |
| `trace_llm_calls` | (`trace_id`, `execution_id`, `call_index`) | one row per model call: the **complete raw response** (never truncated) with its length and sha256, token usage (`prompt_tokens`, `completion_tokens`, `total_tokens`, full `usage_json` incl. cached / reasoning tokens), `finish_reason`, model requested and model that answered, request parameters (temperature, max tokens, response format — never the headers or key), response metadata (OpenAI `id`, `created`, `system_fingerprint`, `service_tier`, HTTP status, `x-request-id`, processing ms; Ollama timings), error text with the HTTP error body, duration, input sha256 |
| `trace_score_changes` | (`trace_id`, `seq`) | hypothesis scores (or confidence) **immediately before and after** every operation that changes them, the per-label `delta` (after − before), ranks before/after, top label before/after, max \|Δ\|, the operation's parameters (weights, joint ranking, pair shares, formula), stage, phase, round, actor |

**Message fields:** `message_id`, `global_message_id`, `trace_id`, `round_id`, `seq`, `sender_agent_id`, `receiver_agent_ids`, `message_type`, `timestamp`, `topic`, `message_content`, `related_hypothesis_ids`, `evidence_ids`, `parent_message_id`, `response_to_message_id`, `challenge_status` (OPEN / RESPONDED / HELD / CONCEDED / NOT_APPLICABLE), `resolution_status` (RESOLVED / UNRESOLVED / PENDING / AWAITING_HUMAN / NOT_APPLICABLE), `stage` (the message phase), `sender_execution_id`, `payload` (positions, `voice` = method | llm, `voice_model`, `method_text` when voiced), `deliveries`.

**Event fields:** `event_id`, `trace_id`, `seq` (total order, safe under concurrency), `event_type`, `timestamp`, `actor`, `execution_id`, `message_id`, `evidence_ids`, `parent_event_id`, `payload` (always includes `stage`).

**Message types:** QUESTION, FINDING, EVIDENCE_SHARE, EVIDENCE_REQUEST, CHALLENGE, RESPONSE, COUNTER_ARGUMENT, CONCESSION, HOLD, POSITION_UPDATE, UNCERTAINTY_FLAG, RISK_FLAG, VERIFICATION_REQUEST, VERIFICATION_RESULT, HUMAN_INPUT_REQUEST, SYNTHESIS.

**Event types:** SCORES_ADJUSTED (mirrors each `trace_score_changes` row), TRACE_STARTED, QUERY_PREPARED, RETRIEVAL_STARTED, EVIDENCE_RETRIEVED, HYPOTHESES_SCORED, EVIDENCE_DELIVERED, AGENT_STARTED, LLM_CALL_COMPLETED, AGENT_OUTPUT_GENERATED, AGENT_FAILED, AGENT_REEXECUTED, TOOL_CALLED, MESSAGE_SENT, MESSAGE_RECEIVED, QUESTION_RAISED, HYPOTHESIS_PROPOSED, HYPOTHESIS_CHALLENGED, HYPOTHESIS_UPDATED, EVIDENCE_REQUESTED, EVIDENCE_VERIFIED, FEEDBACK_LOOP_TRIGGERED, TARGETED_RETRIEVAL_STARTED, COLLABORATION_STARTED, COLLABORATION_ROUND_STARTED, COLLABORATION_ROUND_COMPLETED, JOINT_FINDING_REACHED, VERIFICATION_EXCHANGE_COMPLETED, COUNCIL_CONVENED, COUNCIL_SKIPPED, COUNCIL_ROUND_STARTED, COUNCIL_ROUND_COMPLETED (with `reached_max_rounds`), DISAGREEMENT_RESOLVED, DISAGREEMENT_UNRESOLVED, CLAIM_VALIDATED, CONFIDENCE_RECALCULATED, HUMAN_REVIEW_TRIGGERED, REVIEW_GATE_PASSED, FINAL_SYNTHESIS_GENERATED, TRACE_COMPLETED, TRACE_FAILED.

### Score changes recorded (`trace_score_changes` / `SCORES_ADJUSTED`)

| Operation | Where | What changes |
|---|---|---|
| `initial_scoring` | orchestrator, after the first retrieval | scores created (before = `{}`) |
| `council_blend` | every collaboration pass (collaboration, re-sync, escalation council) | joint ranking blended into the scores, weight `COLLAB_SCORE_WEIGHT` |
| `council_blend_reverted` | start of a later pass, when the scores are still the blended ones | previous blend undone |
| `conflict_rescore` | Diagnostic Expert pass 2 (conflicting hypotheses) | contested pair re-weighted on discriminating channels |
| `targeted_evidence_rescore` | feedback loop after targeted retrieval | scores recomputed from the enlarged evidence (replaces any blend) |
| `council_pair_rescore` | escalation council joint pair resolution | contested pair re-weighted from the shares agents posted |
| `council_confidence_blend` | Ambiguity Detection (`quantity = confidence`) | evidence confidence → `min(evidence, (1−β)·evidence + β·council)` |

Consecutive hypothesis-score rows chain exactly (each `after` equals the next `before`), so no score change goes unrecorded; the tests check this.

### Code version

Every trace stores `code_version` = `<commit7>[-dirty]+src.<sha256 of backend Python source, 12 hex>` (e.g. `72f97d6-dirty+src.f92790b584e3`) and `code_version_json` with the full commit SHA, branch, `git describe`, commit time, whether tracked files had uncommitted changes (and which), the full source hash and file count, trace schema and Python version. The source hash identifies the exact code even for runs on uncommitted edits or without git. `CODE_VERSION=<label>` in the environment (CI, a deployment) replaces the commit prefix. `GET /agenttrace/code-version` shows what the running backend stamps on new traces. Older databases are migrated in place on first use; traces made before schema 1.1 show `code_version: null` and have no LLM-call or score-change rows.

API keys, headers and credentials are never passed to the recorder. Prompts contain only the query, evidence summaries and peer messages. Set `AGENT_TRACE_STORE_PROMPTS=0` to keep only their hash and length.

---

## 5. API

All endpoints are read-only and computed from persisted rows, so they work the same after a restart. `/query` responses now include `harness.trace_id` and `harness.exchange`; every existing field is unchanged.

| Endpoint | Returns |
|---|---|
| `GET /traces?limit&offset&status&dataset` | paged list (`traces`, `total`) |
| `GET /traces/{trace_id}` | run record + `summary` (incl. `collaboration`), `graph`, `disagreements`, `positions` (each agent's position per round + joint findings), `agents` |
| `GET /traces/{trace_id}/summary` | totals, confidence progression, disagreements |
| `GET /traces/{trace_id}/events?limit&offset&event_type&actor` | raw events in `seq` order (paged) |
| `GET /traces/{trace_id}/messages?message_type&agent` | messages with deliveries |
| `GET /traces/{trace_id}/agents?include_prompts` | per-agent execution histories (rendered prompts on request) |
| `GET /traces/{trace_id}/timeline` | contiguous segments by phase: Collaboration round n → Claim verification → Re-sync → Uncertainty flags → Escalation council round n → Final synthesis |
| `GET /traces/{trace_id}/graph` | nodes, directed edges (count, addressed, delivered, types, rounds) |
| `GET /traces/{trace_id}/evidence` | evidence flow per item |
| `GET /traces/{trace_id}/hypotheses` | hypothesis state transitions |
| `GET /traces/by-run/{run_id}` | trace ID for a harness run ID |
| `GET /analyses/{analysis_id}/trace` | the trace linked to a stored analysis (linked automatically when the analysis is saved) |

Malformed trace IDs return 422 and unknown ones return 404.

Example (`GET /traces/{id}` → `trace`, real):

```json
{"trace_id": "TR-20261031132237-3853e22c", "run_id": "c860b9995b2f", "analysis_id": 1, "schema_version": "ida.agenttrace/1.0", "dataset_type": "afrb", "data_mode": "combined", "llm_mode": "deterministic", "status": "COMPLETED", "final_label": "Bearing Wear", "final_confidence": 0.167, "review_decision": "REQUIRES_HUMAN_REVIEW", "communication_rounds": 12, "total_messages": 49, "total_events": 453, "duration_ms": 284.3}
```

Example message (`GET /traces/{id}/messages`, one item, real — Rapid Triage changing its mind in collaboration round 1):

```json
{
 "message_id": "M-011",
 "global_message_id": "TR-20261031132237-3853e22c:M-011",
 "trace_id": "TR-20261031132237-3853e22c",
 "round_id": 1,
 "seq": 184,
 "sender_agent_id": "aggressive_agent",
 "receiver_agent_ids": [
  "diagnostic_expert",
  "pattern_agent",
  "verification",
  "ambiguity",
  "human_review_coordinator"
 ],
 "message_type": "POSITION_UPDATE",
 "timestamp": "2026-10-31T13:22:37.745803+00:00",
 "topic": "Bearing Wear",
 "message_content": "Updated after reading Diagnostic Expert, Pattern Recognition, Verification: Bearing Wear 38%, Rotor Imbalance 37%, Gearbox Degradation 13% (was Rotor Imbalance 39%). Diagnostic Expert, Pattern Recognition, Verification moved me; on my own signature-direction rule (R-SIG) on out-of-band channels I would lead with Rotor Imbalance.",
 "related_hypothesis_ids": [
  "HYP-bearing-wear",
  "HYP-rotor-imbalance"
 ],
 "evidence_ids": [
  "D-004"
 ],
 "parent_message_id": null,
 "response_to_message_id": null,
 "challenge_status": "NOT_APPLICABLE",
 "resolution_status": "NOT_APPLICABLE",
 "stage": "collaboration",
 "sender_execution_id": "X-018",
 "payload": {
  "label": "Bearing Wear",
  "old_label": "Rotor Imbalance",
  "confidence": 0.383,
  "position": {
   "Bearing Wear": 0.383,
   "Rotor Imbalance": 0.371,
   "Gearbox Degradation": 0.126,
   "Lubrication Degradation": 0.12
  },
  "old_position": {
   "Rotor Imbalance": 0.386,
   "Bearing Wear": 0.373,
   "Gearbox Degradation": 0.122,
   "Lubrication Degradation": 0.119
  },
  "openness": 0.25,
  "read_positions_from": [
   "diagnostic_expert",
   "pattern_agent",
   "verification"
  ],
  "moved_by": [
   "diagnostic_expert",
   "pattern_agent",
   "verification"
  ],
  "method": "signature-direction rule (R-SIG) on out-of-band channels",
  "new_label": "Bearing Wear",
  "voice": "method"
 },
 "deliveries": [
  {
   "receiver": "diagnostic_expert",
   "via": "inbox_read",
   "seq": 202,
   "execution_id": "X-020",
   "timestamp": "2026-10-31T13:22:37.746968+00:00"
  },
  {
   "receiver": "pattern_agent",
   "via": "inbox_read",
   "seq": 210,
   "execution_id": "X-021",
   "timestamp": "2026-10-31T13:22:37.748340+00:00"
  }
 ]
}
```

---

## 6. Exporting traces to files

Every route produces the same files from the SQLite trace store:

| Format | File | Contents |
|---|---|---|
| `json` | `TR-….json` | the complete trace: code version, run record, summary (incl. token usage), graph, positions, disagreements, every message with deliveries, timeline, hypothesis states, agent executions (with rendered prompts), every model call with its full raw response and metadata (`llm_calls`), every score change (`score_changes`), evidence flow with full record content, every raw event |
| `transcript` | `TR-….md` | readable conversation log, phase by phase: who said what to whom, positions, evidence, who read it, outcomes |
| `messages_csv`, `events_csv`, `executions_csv`, `evidence_csv` | `TR-….<name>.csv` | flat tables for Excel / pandas (`evidence.csv` includes `content_text` and `content`) |
| `llm_calls_csv` | `TR-….llm_calls.csv` | one row per model call: tokens, finish reason, response id, full `response_raw` |
| `scores_csv` | `TR-….scores.csv` | long format, one row per (score change, label): before, after, delta, ranks |

**Script (backend can be stopped)**, run from `backend/`:

```bash
python scripts/export_traces.py --list                          # stored traces
python scripts/export_traces.py --latest                        # newest → exports/traces/TR-….json + .md
python scripts/export_traces.py --latest 10 --format all        # 10 newest, every format
python scripts/export_traces.py --trace-id TR-20261031132237-3853e22c --format json,messages_csv
python scripts/export_traces.py --analysis-id 4                 # trace of a saved analysis
python scripts/export_traces.py --all --dataset afrb --out exports/afrb
python scripts/export_traces.py --latest --api http://localhost:8000   # via the running backend
python scripts/export_traces.py --latest --no-prompts           # leave out rendered LLM prompts
```

**API:**
- `GET /traces/{trace_id}/export?format=json|transcript|messages_csv|events_csv|executions_csv|evidence_csv|llm_calls_csv|scores_csv&include_prompts=true` downloads one file (`include_prompts=false` also leaves out raw responses).
- `GET /traces/{trace_id}/llm-calls?include_responses=true` and `GET /traces/{trace_id}/scores` return the model calls and score changes as JSON.
- `GET /traces/export/archive?limit=20&formats=json,transcript` downloads a `.zip` with one folder per trace plus `index.json`.

**Browser:** Trace explorer has **Download this trace** buttons under the question, and **Download recent** (a zip of the 20 newest) above the trace list.

**From your own Python code:**

```python
from harness.agent_trace.trace_repository import TraceReader
from harness.agent_trace import trace_export

r = TraceReader()                                   # or TraceReader("path/to/analysis_store.db")
tid = r.list_traces(limit=1)[0][0]["trace_id"]
bundle = trace_export.bundle(r, tid)                # dict: everything in the trace
open(f"{tid}.json", "w", encoding="utf-8").write(trace_export.render(bundle, "json"))
```

---

## 7. Frontend: Trace Explorer

Open **Trace explorer** in the top bar (`/traces`, or `/traces/{trace_id}`); it opens on your latest diagnosis.

| Area | What it shows |
|---|---|
| **How they agreed** (first tab) | a grid of agents × rounds. The first column is each agent's private draft, then its stated position in every collaboration / re-sync round; a dark border marks a change of mind; click a cell to read the message. Below: the joint ranking handed to Verification, dissent, and evidence vs council vs final confidence |
| Who talked to whom | communication graph: arrow weight = messages, colour = statement / request / answer / dispute / flag, dashed = some addressed messages never read |
| Message inspector | sender, addressees, who actually read it, the position it states and what it was before, whose positions the agent read and its openness, the wording source (method or GPT, with the method text), evidence, reply chain, resolution, resulting hypothesis states |
| Timeline | every message in sequence order, grouped by phase and round; GPT-voiced messages are marked |
| Header | code version (commit, branch, uncommitted changes) and download buttons for every format |
| Agents | per agent: executions (including each collaboration step), hypothesis evolution, confidence, token usage per execution; **Load model inputs and full responses** shows each rendered prompt and every raw model response with usage, request parameters and response metadata |
| Score changes | every blend and re-score in order: before, after, Δ per hypothesis, top-label changes, formula |
| Evidence flow | per EV/D item: origin, who received it, whether it was in a rendered prompt, who cited it, verification; expand a row for the full record text and content |
| Disagreements | every challenge with its replies and outcome |
| Raw events | the append-only event log |

---

## 8. Configuration

| Variable | Default | Effect |
|---|---|---|
| `COLLAB_MODE` | `on` | `off` = the previous independent first pass (no council collaboration) |
| `COLLAB_MAX_ROUNDS` | `3` | maximum critique + update rounds |
| `COLLAB_SCORE_WEIGHT` | `0.5` | weight of the joint ranking in the hypothesis scores |
| `COLLAB_CONF_WEIGHT` | `0.5` | β in `final = min(evidence, (1−β)·evidence + β·council)` |
| `COUNCIL_LLM_MODEL` | `gpt-4.1` (OpenAI) / `OLLAMA_MODEL` | model that voices the agents' messages |
| `COLLAB_LLM_VOICE` | `on` | `off` keeps the LLM for agent analysis but not for council messages |
| `AGENT_TRACE_ENABLED` | `1` | `0` turns tracing off |
| `AGENT_TRACE_DB_PATH` | `ANALYSIS_DB_PATH` | SQLite file for traces (default `./data/analysis_store.db`) |
| `AGENT_TRACE_STORE_PROMPTS` | `1` | `0` stores only hash and length of rendered prompts |
| `CODE_VERSION` | unset | label recorded as the code version prefix instead of the git commit |
| `COUNCIL_MODE`, `COUNCIL_MAX_ROUNDS` | `auto`, `2` | escalation council (unchanged) |

---

## 9. Running and inspecting

```bash
cd backend && uvicorn main:app --reload        # trace tables are created on startup
cd frontend && npm run dev                      # http://localhost:5173/traces
```

Ask a question in **Diagnostic chat**, then open **Trace explorer**. The response carries `harness.trace_id`
and a `harness.collaboration` summary: joint label and ranking, council confidence, positions, changes of
mind, dissent, and the number of GPT-voiced messages.

### Tests

```bash
cd backend && python -m pytest -q        # 59 tests
```

`tests/test_agent_trace.py` covers:
- the pooling rule;
- all six agents taking part;
- positions read before every update;
- challenges answered;
- questions, evidence shares and verification requests;
- a change of mind traceable to its message;
- dissent left open;
- an unsupported claim and a missing ID;
- re-sync after targeted retrieval;
- collaboration and council round limits;
- agent failure (the agent abstains) and pipeline failure;
- persistence across a restart;
- concurrent runs;
- deterministic trace validity;
- LLM voicing with a fake model (voiced and rejected messages, decisions unchanged, model configurable);
- council confidence capped by evidence;
- `COLLAB_MODE=off`;
- duplicate events;
- every API endpoint.

Tests that pick a scenario search the scenario file for one that shows the behaviour, so they don't
depend on tuning.

Note: LLM voicing was tested against a fake model in this environment (no API key). Run one question
with your key and check the **Wording** row in the message inspector.
