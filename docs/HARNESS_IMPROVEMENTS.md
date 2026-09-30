# Industrial Diagnostic AI — Orchestration Harness Upgrade

This document describes what changed, why, and what the measurements show.
The guiding rule was **no new LLM agents**: the six existing agents remain the
only reasoning components. Everything added around them (evidence checking,
targeted retrieval, claim validation, confidence and the review gate) is
deterministic harness code.

---

## 1. What the original system did (audit findings)

| Area | Finding in the original code | Consequence |
|---|---|---|
| Data loading | `AFRBLoader` filled missing numerics with the **column median** | Missing sensor values were silently invented and then cited |
| AFRB metadata | Loader looked for `asset_id`, `failure_mode`, … — none exist in the AFRB CSV, so metadata was only `{"source": "afrb"}` | No metadata filtering was possible; labels lived only in free text |
| FailureSensorIQ | ~58 % of questions ask for *non-relevant* items, but every answer was written as "Relevant Sensors (correct)"; 470/500 docs had "Equipment: industrial equipment" | Inverted facts fed to agents |
| FailureSensorIQ | 30 random "synthetic supplement" rows (random equipment × failure × sensors) mixed into the real index, unlabelled in the UI | Meaningless records in RAG |
| Retrieval | Pure FAISS top-5 on the raw question text | Numeric similarity barely used: baseline retrieval hit@5 = 17.9 % |
| Agent communication | Whole JSON outputs of earlier agents pasted into later prompts | No IDs, no traceability |
| LLM fallback | With no LLM, a keyword mock returned fixed numbers ("118 °C", "8,450 hrs", "8 mm/s", "72 hours") | 24.7 % of numeric claims unsupported; every answer said "bearing wear" |
| Confidence | LLM-reported number, later overwritten by another LLM "system analysis" | Not measurable |
| Ambiguity | Every case in the benchmark was flagged for review | The flag carried no information |
| Evaluation | 36 LLM-judge calls per query plus one large meta-evaluation call | Slow and costly; the judge graded against the same retrieved text |
| Security | `.env.example` contained what looks like a real OpenAI key | **Rotate that key** — it is in the public repository history |

## 2. Architecture after the upgrade

```
                    USER QUERY
                         │
                 QUERY PREPARATION        harness/query_prep.py (numbers, missing channels, units,
                         │                directions, equipment, mentioned failure modes)
                  MULTI-STAGE RAG         harness/retrieval.py
                         │                semantic (FAISS) · metadata · numeric · historical → rerank
                NUMERICAL ANALYSIS        harness/analysis.py (kNN vote + signature fit + equipment prior)
                         │
       ┌─────────────────┼─────────────────┐
 Diagnostic Expert   Pattern Agent   Rapid Triage          (parallel, independent)
       └─────────────────┼─────────────────┘
                   VERIFICATION           adversarial, evidence-first
                         │
                  EVIDENCE CHECK ── weak ──► TARGETED RAG ──► re-run ONLY the affected agent ──► re-verify
                         │                                   (≤ 2 rounds, each deficiency handled once)
                      strong
                         │
                     AMBIGUITY            measured uncertainty + factor-based confidence
                         │
                 FINAL COORDINATOR        claim-validated answer with EV/D citations
                         │
                 HUMAN REVIEW GATE        explicit criteria G1–G8
                         │
                    FINAL REPORT
```

Agent count: still six (Diagnostic Expert, Pattern Recognition, Rapid Triage
[formerly Aggressive Decision], Verification Analyst, Ambiguity Detection,
Human Review Coordinator). The legacy System Analysis meta-evaluator is kept
only for the stored-analysis dashboard and now runs its deterministic path by
default (`SYSTEM_ANALYSIS_LLM=false`).

## 3. How the six agents cooperate now

| Agent | Input from the shared state | Output (structured `AgentReport`) |
|---|---|---|
| **Diagnostic Expert** | hypothesis scores, evidence, signature statistics | ≥ 2 hypotheses, each with supporting / contradicting statements (cited), missing channels. Pass 2 (only on conflict) re-scores the two leaders on the channels that discriminate between them, using targeted evidence |
| **Pattern Recognition** | numeric neighbours, historical label support, reference bands | label distribution of nearest cases, anomalous channels, best-match distance; says **"No strong historical match found"** when the closest case is beyond the calibrated threshold |
| **Rapid Triage** | the query readings only | deterministic `rapid_signal` from explicit rules (consistency rules R-C*, band rule R-B1, signature direction), severity triage; never calls an LLM; never re-run, so it stays an independent perspective |
| **Verification Analyst** | the three reports + evidence | per candidate: what supports it, what contradicts it, what is missing, which alternative explains the same evidence, which agent claims are unsupported, which retrieved records are irrelevant. The verdict follows evidence scores, not votes; "agreement without evidence" is flagged |
| **Ambiguity Detection** | verification + retrieval statistics | flags (insufficient evidence, conflicting evidence, low-quality data, weak retrieval, multiple plausible diagnoses, missing sensors, unsupported claims, synthetic reliance) and the confidence breakdown |
| **Human Review Coordinator** | everything above | final answer composed only from verified state, claim-validated, then the explicit gate |

With an LLM configured (OpenAI or Ollama), five agents additionally send a
compact structured prompt (evidence IDs, derived facts, allowed labels) and
merge the answer only after every evidence ID, label and number has been
validated. Without an LLM they run their deterministic cores — the legacy mock
responses are never used by the harness.

## 4. Harness components

* **Shared state** — `harness/schema.py::DiagnosticState` (query profile, evidence,
  derived values, each agent's report, contradictions, missing evidence,
  deficiencies per round, confidence, claim checks, review decision, audit trail).
  It is a run-level context buffer; there is no long-term agent memory.
* **Evidence objects** — every retrieved record becomes `EV-001…` with dataset,
  record id, `source_type` (real/synthetic), fused score, dominant retrieval
  method, per-method scores, content, selection reason, retrieval round and
  `used_by`. Values computed by the harness become `D-001…`.
* **Controlled feedback** — `agents/orchestrator.py::_evidence_check` maps
  verification output to deficiencies:

  | Deficiency | Action | Re-run |
  |---|---|---|
  | HISTORICAL_EVIDENCE_WEAK | wider historical retrieval (60 neighbours) + re-score | Pattern Recognition |
  | NO_HISTORICAL_MATCH | expanded historical search | Pattern Recognition |
  | CONFLICTING_HYPOTHESES | label-filtered retrieval for the two leaders | Diagnostic Expert (pass 2) |
  | WEAK_RETRIEVAL | expanded candidate pool + rerank | Pattern Recognition |
  | METADATA_EVIDENCE_MISSING | equipment-filtered retrieval | Pattern Recognition |
  | UNSUPPORTED_CLAIMS | strip claims deterministically | none |
  | SENSOR_EVIDENCE_MISSING | recorded only — unmeasured readings cannot be retrieved | none |

  Verification always re-runs after a round. At most `MAX_FEEDBACK_ROUNDS` (2)
  rounds; each deficiency is acted on once, and what remains goes to Ambiguity.
* **Claim validation** — `harness/claims.py`. Numbers are matched *per sensor*
  (a "temperature 67 °C" claim is not supported by a record whose pressure is
  67) against the query, retrieved records, derived values and declared rule
  thresholds → SUPPORTED / DERIVED / UNSUPPORTED. Unsupported sentences are
  removed from lists or replaced by `[unverified statement removed]`; invalid
  EV/D references and unknown failure-mode labels are also rejected.

## 5. Synthetic data

* Generator: `backend/data_generator/synthetic_industrial_generator.py`
  (deterministic, seeded, no LLM). Run `python -m data_generator.synthetic_industrial_generator`.
* **Gap analysis of the original AFRB data** (50,000 rows): 7 perfectly balanced
  fault classes, **no normal class, 0 % missing values, no seal / cavitation /
  gearbox scenarios, no severity levels, no contradictory sensors, labels
  independent of equipment context**.
* **Knowledge-base records generated: 6,350** — normal 1,000; bearing / shaft /
  lubrication at mild / moderate / severe (450 each); seal, gearbox, pump
  cavitation (600 each); mild variants of cooling / electrical / valve (300);
  ambiguous pairs (600); mixed symptoms (300); missing-sensor cases (700, 1–3
  channels blank); contradictory sensors (300).
* Signatures of existing classes use the medians measured on the real data;
  the new families (Normal, Seal Failure, Pump Cavitation, Gearbox Degradation)
  are documented *scenario assumptions* for experimentation, not engineering truths.
* **Provenance** on every row: `Source_Type=synthetic`, `Synthetic=True`,
  `Synthetic_Scenario`, `Synthetic_Generator_Version=v1`, `Synthetic_Record_ID=SYN-000001…`.
  Provenance columns are never embedded as evidence text; the embedded text ends
  with `Source Type: SYNTHETIC`.
* **Validation** (`data/synthetic/validation_report.json`): value ranges,
  missing-value rate (~3.5 % per sensor), duplicate rate (0), label / scenario /
  severity distributions, and relationship checks (e.g. bearing vibration and
  temperature above normal, imbalance temperature below bearing, seal pressure
  below normal, gearbox scenarios only on gear-driven contexts). All passed.
* **Same pipeline**: the synthetic CSV has the AFRB column schema and goes
  through the same `AFRBLoader` → canonical record → embedding → FAISS
  (separate index `afrb_synthetic`) → multi-stage RAG → six agents.
* **Dataset modes**: `real`, `synthetic`, `combined` (`data_mode` on `/query`).
  In combined mode synthetic neighbours are down-weighted (×0.8) in the
  historical vote, and a `synthetic_reliance` confidence penalty applies when
  > 70 % of the evidence is synthetic — synthetic data never *raises* confidence.
* **Held-out test set** (`data/synthetic/test_scenarios.csv`, different seed,
  never indexed): 176 synthetic cases with known ground truth (clear faults,
  normal equipment, missing temperature, conflicting signals, no historical
  match, ambiguous bearing-vs-imbalance, contradictory sensors, mixed symptoms)
  + 70 real AFRB records that are excluded from retrieval when evaluated.

## 6. RAG

1. **Semantic** — FAISS `IndexFlatL2` over all-MiniLM-L6-v2 (unchanged model;
   the original 50,000-vector index is reused because the canonical text is
   byte-identical to what was embedded — verified at startup by a 3-row
   alignment check).
2. **Metadata** — equipment type, mentioned failure modes, label filters;
   for the text-only FailureSensorIQ KB, a metadata-filter pass that scores
   filtered records by reconstructing their FAISS vectors.
3. **Numeric** — weighted robust distance over the channels the user reported
   (median/IQR scaling from the real data; channel weights = share of variance
   explained by the label, learned from data, so e.g. RPM is down-weighted).
   Missing channels are skipped and penalised through a coverage term.
   Qualitative cues ("elevated vibration") use direction matching.
4. **Historical** — similarity-weighted label vote among the nearest 25 cases;
   a "no strong historical match" threshold is calibrated from the
   nearest-neighbour distance distribution (99.5th percentile × 1.25).
5. **Rerank** — weighted fusion (numeric 0.50, semantic 0.20, historical 0.15,
   metadata 0.15 when numbers are present) and diversification so the two
   best-supported labels are both represented for verification.

## 7. Hallucination reduction

* No imputation anywhere; missing channels stay "unavailable".
* Units handled explicitly (bar → PSI, °F → °C; vibration in mm/s is refused
  because the KB uses a normalised index).
* Deterministic agent cores produce only cited statements.
* LLM output is merged only after ID / label / number validation.
* Final-text claim validation plus gate criterion G7.
* Measured confidence (`harness/confidence.py`):
  `confidence = min(0.95, Π factorᵢ^(wᵢ/2))` over evidence quality, hypothesis
  separation, historical similarity, data completeness, contradictions,
  retrieval quality and agent agreement. Agreement only counts when the
  evidence quality factor is ≥ 0.6.
* Review gate (`harness/review_gate.py`), AUTO_RESOLVE only if all pass:
  G1 confidence ≥ 0.65 · G2 margin ≥ 0.15 · G3 no consistency-rule violation ·
  G4 historical match exists · G5 no channel needed to confirm the diagnosis is
  missing · G6 numeric readings present · G7 all final claims evidence-backed ·
  G8 CRITICAL severity needs confidence ≥ 0.80.

## 8. Frontend

Bright industrial theme (white cards on `#F7F9FC`, blue `#2563EB` / cyan
`#06B6D4` accents, status colours reserved for status). Pages:

* **Overview** — live record counts, benchmark headline numbers, the harness diagram.
* **Diagnose** — dataset-mode selector (REAL / SYNTHETIC / COMBINED with counts),
  scenario shortcuts, and per result:
  * headline (final diagnosis with evidence chips, decision badge, measured confidence, REAL/SYNTHETIC counts, gate reasons, recommendation);
  * **Agent orchestration** view built from the real audit trail — six agents plus harness stages, pass counts, and the feedback-loop narrative (deficiency → action → re-run → re-verify);
  * tabs: **Hypotheses** (actual scores, conflict resolution, adversarial Q&A, candidate table) · **Evidence explorer** (filters: supporting, contradicting, historical, targeted re-RAG, REAL, SYNTHETIC; each card shows record id, dataset, provenance badge, sensor values, score, method, why selected, which agents used it) · **Confidence & gate** (every factor with explanation, the formula, all gate criteria) · **Agents** (six structured reports) · **Sensors** (reading vs reference band, missing channels) · **Audit & claims** (measured execution timeline, claim-validation counts, removed claims, derived values).
* **Data & evaluation** — data-quality panel (total / real / synthetic records,
  classes, missing values, duplicates, components, sensor coverage), failure-mode
  distribution REAL vs SYNTHETIC, synthetic scenario / severity / component
  coverage, sensor distributions (small multiples, normalised), sensor
  signatures by failure mode, before/after benchmark chart + table, recent diagnoses.

All values shown are computed by the backend; nothing is simulated.

## 9. Testing

`cd backend && python -m pytest tests -q` → **23 tests** (≈ 6 s, offline):
query preparation (values, missing channels, units, directions); synthetic data
(provenance, determinism, validation, gap coverage, held-out separation);
loaders (no imputation, provenance not embedded, FailureSensorIQ polarity);
harness end-to-end (clear case with valid citations, missing temperature never
invented, no-match abstention after a targeted retrieval, contradictory sensors
→ review, normal equipment not forced into a fault, feedback loop re-runs only
affected agents, real/synthetic mode isolation, empty-profile handling);
confidence (agreement cannot raise weak evidence); gate criteria; claim
validator; an **adversarial fake LLM** that invents readings, labels and
evidence IDs and returns malformed payloads — none of its fabrications reach
the output; agent crash containment.

## 10. Evaluation — before vs after

Command: `python evaluation/benchmark.py --system {baseline|harness} …`
(identical 246 held-out cases and identical scoring code in
`evaluation/bench_metrics.py`; results in `backend/evaluation/results/`).

**Important caveat:** no LLM was available in the evaluation environment, so
both systems ran their offline paths — the original pipeline its rule-based
mock, the harness its deterministic agents. LLM-mode quality was **not**
measured. The baseline therefore reflects the original fallback behaviour, not
the original pipeline with GPT-4o.

| Metric | Original (baseline) | Harness · REAL | Harness · SYNTHETIC | Harness · COMBINED | COMBINED, no feedback loop |
|---|---|---|---|---|---|
| Diagnostic accuracy (all 246) | 25.6 % | 72.8 % | 62.6 % | **94.3 %** | 94.3 % |
| Accuracy on held-out REAL records | 14.3 % | 92.9 % | 20.0 % | **94.3 %** | 94.3 % |
| Accuracy on synthetic scenarios | 30.1 % | 64.8 % | 79.5 % | **94.3 %** | 94.3 % |
| Unsupported numeric claims | 24.7 % (828 / 3,352) | 0 % | 0 % | **0 %** (0 / 4,105) | 0 % |
| Missing-sensor fabrication | 41.7 % | 0 % | 0 % | **0 %** | 0 % |
| Evidence grounding of cited items | 17.5 % | 100 % | 100 % | **100 %** | 100 % |
| Retrieval precision@5 | 11.5 % | 67.3 % | 81.1 % | **90.8 %** | 90.8 % |
| Retrieval hit@5 | 17.9 % | 70.9 % | 86.6 % | **96.1 %** | 96.1 % |
| Ambiguous cases sent to review | 100 % | 74.2 % | 88.7 % | 77.4 % | 77.4 % |
| Clear cases sent to review | 100 % | 36.4 % | 66.3 % | 20.7 % | 16.3 % |
| Accuracy when auto-resolved | n/a (never) | 94.7 % | 92.8 % | **98.8 %** | 98.2 % |
| Wrong answers caught by the gate | 100 % (flags all) | 89.6 % | 94.6 % | 85.7 % | 78.6 % |
| Median latency | 124 ms | 115 ms | 88 ms | 114 ms | 107 ms |

How to read it honestly:

* The numeric evidence engine and multi-stage retrieval account for most of the
  accuracy gain; with real data only, held-out real accuracy goes 14.3 % → 92.9 %.
* The synthetic data adds coverage the real data lacks (normal equipment,
  seal, cavitation, gearbox, abstention cases): synthetic-scenario accuracy
  64.8 % (real KB) → 94.3 % (combined). On its own it is **not** a substitute
  for real data (20 % on real hold-out in synthetic-only mode).
* The **feedback loop did not change top-1 accuracy** in this benchmark
  (94.3 % with and without). What it changed is safety: wrong answers caught
  by the gate 78.6 % → 85.7 % and auto-resolved accuracy 98.2 % → 98.8 %, at
  the cost of more clear cases being routed to review (16.3 % → 20.7 %).
* "0 % unsupported numeric claims" is expected for the deterministic path,
  which only emits templated, cited statements. The claim validator's value is
  in LLM mode; it is exercised by the adversarial-LLM test, not by this benchmark.
  38 numbers in harness output are thresholds of the declared consistency
  rules (R-C1…R-C3) and are reported separately rather than counted as supported.
* The synthetic test scenarios come from the same generator family as the
  synthetic knowledge base (different seed). Synthetic-scenario accuracy is
  therefore an optimistic estimate; the 70 held-out real records are the more
  meaningful accuracy figure.
* The baseline scores 100 % on some ambiguous categories only because its
  fallback always answered "bearing wear", which happens to be an acceptable label there.
* The FailureSensorIQ knowledge base is a relevance benchmark, not asset
  telemetry; its answers are rankings of associated failure events and always
  go to human review.

## 11. Files changed

**New**
* `backend/harness/` — `schema.py` (state & models), `canonical.py` (shared schema, FailureSensorIQ parser), `knowledge_base.py` (partitions, reference stats, numeric distance, calibration), `query_prep.py`, `retrieval.py` (multi-stage RAG), `analysis.py` (hypothesis scoring, signatures, discriminating channels), `rules.py` (declared rules), `statements.py` (cited statements), `claims.py` (claim validator), `confidence.py`, `review_gate.py`, `audit.py`.
* `backend/services/runtime.py` (wiring shared by API, benchmark and tests), `services/dataset_summary.py`.
* `backend/data_generator/synthetic_industrial_generator.py`; `backend/data/synthetic/` (`afrb_synthetic.csv`, `test_scenarios.csv`, `validation_report.json`).
* `backend/evaluation/` (`benchmark.py`, `bench_metrics.py`, `results/*.json`).
* `backend/tests/` (23 tests).
* `backend/faiss_indexes/afrb_synthetic.*` (prebuilt, 6,350 vectors) and a rebuilt `failure_iq.*` (5,629 vectors).
* Frontend: `components/ui.jsx`, `AppShell.jsx`, `OrchestrationFlow.jsx`, `EvidenceExplorer.jsx`, `ReportPanels.jsx`, `DiagnosisReport.jsx`.

**Modified**
* `agents/*.py` — all six agents rewritten around `analyze(state, ctx)`; `orchestrator.py` is the harness; `base_agent.py` adds the structured-prompt / validated-merge path; `system_analysis_agent.py` gains a deterministic entry point and makes its LLM call opt-in.
* `data_loader/afrb_loader.py` (no imputation, canonical records, provenance), `data_loader/failure_iq_loader.py` (polarity, all rows, supplement disabled).
* `rag/embedder.py` (local model path, labelled offline fallback), `rag/faiss_store.py` (`search_raw`, index metadata, vectors-only load).
* `utils/llm_client.py` (`is_available`, `generate_json` without mock data).
* `models/schemas.py` (`data_mode`, `review_decision`, `harness`, richer health), `main.py` (runtime, `/datasets/summary`, `/evaluation/results`).
* `.env.example` (key removed, harness settings), `requirements.txt` (pytest), `rebuild_index.bat`.
* Frontend: `tailwind.config.js`, `index.css`, `services/api.js`, `App.jsx`, all three pages; `framer-motion` removed.

**Removed** (replaced by the new components): `AgentContributions`, `AgentPerformanceReport`, `ChatMessage`, `ConfidenceBar`, `DatasetCard`, `DiagnosisCard`, `LoadingSpinner`, `PersonaOutputs`, `PhaseTestPanel`, `ReasoningAccordion`. The `/analyses/agent-report` API is still available.
