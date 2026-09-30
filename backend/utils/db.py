"""
SQLite persistence layer for System Analysis results.
Uses Python's built-in sqlite3 — no extra dependencies required.
DB file: ./data/analysis_store.db
"""

import json
import os
import sqlite3
from collections import defaultdict
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from utils.logger import setup_logger

logger = setup_logger(__name__)

_DB_PATH = os.getenv("ANALYSIS_DB_PATH", "./data/analysis_store.db")

# ─── DDL ─────────────────────────────────────────────────────────────────────

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS analysis_results (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at      TEXT    NOT NULL,
    question        TEXT    NOT NULL,
    dataset         TEXT    NOT NULL,
    final_diagnosis TEXT    NOT NULL,
    confidence      REAL    NOT NULL,
    latency_ms      REAL    NOT NULL,
    overall_score   REAL    NOT NULL,
    risk_level      TEXT    NOT NULL,
    analysis_json   TEXT    NOT NULL
);
"""

_CREATE_IDX = """
CREATE INDEX IF NOT EXISTS idx_ar_created_at ON analysis_results(created_at DESC);
"""


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _db_path() -> str:
    """Ensure the data directory exists and return the DB file path."""
    os.makedirs(os.path.dirname(os.path.abspath(_DB_PATH)), exist_ok=True)
    return _DB_PATH


@contextmanager
def _conn():
    """Context manager that yields a sqlite3 connection with WAL mode."""
    con = sqlite3.connect(_db_path(), check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL;")
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


# ─── Public API ──────────────────────────────────────────────────────────────

def init_db() -> None:
    """Create the analysis_results table if it doesn't already exist."""
    with _conn() as con:
        con.execute(_CREATE_TABLE)
        con.execute(_CREATE_IDX)
    logger.info("[DB] analysis_results table ready — %s", _db_path())


def save_analysis(
    question: str,
    dataset: str,
    analysis_report: Dict[str, Any],
    final_diagnosis: str,
    confidence: float,
    latency_ms: float,
) -> Optional[int]:
    """
    Insert a new analysis row.  Returns the new row id, or None on failure.
    """
    try:
        aggregated = analysis_report.get("aggregated", {})
        overall_score = float(aggregated.get("overall_score", 0.0))
        risk_level = str(aggregated.get("risk_level", "unknown"))

        with _conn() as con:
            cur = con.execute(
                """
                INSERT INTO analysis_results
                  (created_at, question, dataset, final_diagnosis,
                   confidence, latency_ms, overall_score, risk_level, analysis_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    datetime.now(timezone.utc).isoformat(),
                    question[:512],
                    dataset,
                    final_diagnosis[:512],
                    round(confidence, 4),
                    round(latency_ms, 1),
                    round(overall_score, 4),
                    risk_level,
                    json.dumps(analysis_report),
                ),
            )
            return cur.lastrowid
    except Exception as exc:
        logger.error("[DB] Failed to save analysis: %s", exc, exc_info=True)
        return None


def get_analyses(
    limit: int = 50,
    dataset_filter: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Return the most recent `limit` analyses as plain dicts.
    Optionally filter by dataset name.
    """
    try:
        with _conn() as con:
            if dataset_filter:
                rows = con.execute(
                    """
                    SELECT id, created_at, question, dataset, final_diagnosis,
                           confidence, latency_ms, overall_score, risk_level, analysis_json
                    FROM analysis_results
                    WHERE dataset = ?
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (dataset_filter, limit),
                ).fetchall()
            else:
                rows = con.execute(
                    """
                    SELECT id, created_at, question, dataset, final_diagnosis,
                           confidence, latency_ms, overall_score, risk_level, analysis_json
                    FROM analysis_results
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()

        results = []
        for row in rows:
            row_dict = dict(row)
            try:
                row_dict["analysis_json"] = json.loads(row_dict["analysis_json"])
            except Exception:
                pass
            results.append(row_dict)
        return results

    except Exception as exc:
        logger.error("[DB] Failed to fetch analyses: %s", exc, exc_info=True)
        return []


# ─── Trait dimension definitions ─────────────────────────────────────────────
# 8 standardised dimensions scored 1-10 per agent.
# Grounded in AGENT_PERSONAS backstory, role, and reasoning_style.
#
#   speed              – How quickly the agent produces a decision (1=slow, 10=instant)
#   analytical_depth   – Depth of multi-hypothesis step-by-step reasoning
#   evidence_rigor     – How strictly claims are grounded in retrieved evidence
#   pattern_matching   – Ability to spot recurring sensor/signal patterns
#   uncertainty_handling – Explicitly detects and flags ambiguous cases
#   decision_confidence  – Assertiveness and commitment to a final answer
#   consensus_building   – Integrates multiple agent perspectives
#   risk_awareness       – Safety-first conservative stance on edge cases
# ─────────────────────────────────────────────────────────────────────────────
TRAIT_DIMENSIONS = [
    "speed",
    "analytical_depth",
    "evidence_rigor",
    "pattern_matching",
    "uncertainty_handling",
    "decision_confidence",
    "consensus_building",
    "risk_awareness",
]

TRAIT_LABELS = {
    "speed":                 "Speed",
    "analytical_depth":      "Analytical Depth",
    "evidence_rigor":        "Evidence Rigor",
    "pattern_matching":      "Pattern Matching",
    "uncertainty_handling":  "Uncertainty Handling",
    "decision_confidence":   "Decision Confidence",
    "consensus_building":    "Consensus Building",
    "risk_awareness":        "Risk Awareness",
}

# ─── Trait → Evaluation Metric influence map ──────────────────────────────────
# Maps each of the 5 evaluation metrics to which persona trait dimensions
# most strongly govern its expected value for a given agent.
#
#   faithfulness_score  ← evidence_rigor (primary), analytical_depth (secondary)
#   reasoning_score     ← analytical_depth (primary), pattern_matching (secondary)
#                          speed has a NEGATIVE influence (speed ↑ → depth ↓)
#   agreement_score     ← consensus_building (primary), decision_confidence (secondary)
#   coverage_score      ← pattern_matching (primary), risk_awareness (secondary)
#                          uncertainty_handling also contributes (cautious agents cover more)
#   reliability_score   ← decision_confidence (primary), risk_awareness (secondary)
#                          uncertainty_handling has moderate positive influence
# ─────────────────────────────────────────────────────────────────────────────
TRAIT_TO_METRIC_WEIGHTS = {
    "faithfulness_score": {
        "evidence_rigor":        0.60,   # dominant – strict grounding in context
        "analytical_depth":      0.25,   # supporting – deeper analysis = fewer hallucinations
        "speed":                -0.15,   # negative  – faster agents skip evidence checks
    },
    "reasoning_score": {
        "analytical_depth":      0.55,   # dominant – step-by-step causal reasoning
        "pattern_matching":      0.25,   # supporting – pattern recognition enriches reasoning
        "speed":                -0.20,   # negative  – speed trades off reasoning depth
    },
    "agreement_score": {
        "consensus_building":    0.55,   # dominant – integrating multiple agent views
        "decision_confidence":   0.30,   # supporting – confident agents align with consensus
        "uncertainty_handling":  0.15,   # supporting – cautious agents flag divergence
    },
    "coverage_score": {
        "pattern_matching":      0.40,   # dominant – detecting all sensor signal patterns
        "risk_awareness":        0.35,   # supporting – risk-aware agents check every signal
        "uncertainty_handling":  0.25,   # supporting – uncertainty-aware agents are comprehensive
    },
    "reliability_score": {
        "decision_confidence":   0.40,   # dominant – committed answers reduce flip-flopping
        "risk_awareness":        0.35,   # supporting – conservative agents are more consistent
        "uncertainty_handling":  0.25,   # supporting – knowing uncertainty limits prevents overreach
    },
}

METRIC_TRAIT_DESCRIPTIONS = {
    "faithfulness_score": (
        "Governed by Evidence Rigor — how strictly the agent grounds every claim in "
        "retrieved sensor data. Speed negatively impacts this: faster agents skip validation steps."
    ),
    "reasoning_score": (
        "Governed by Analytical Depth — the ability to build step-by-step causal reasoning chains. "
        "Pattern Matching enriches the depth, while Speed trades off reasoning quality."
    ),
    "agreement_score": (
        "Governed by Consensus Building — how well an agent integrates other perspectives into its output. "
        "High Decision Confidence anchors the agent's answer to a coherent position."
    ),
    "coverage_score": (
        "Governed by Pattern Matching — the ability to detect all relevant sensor signal combinations. "
        "Risk Awareness ensures edge-case signals are not missed during analysis."
    ),
    "reliability_score": (
        "Governed by Decision Confidence and Risk Awareness — consistent, well-calibrated agents "
        "produce reliable outputs across diverse fault scenarios without over- or under-committing."
    ),
}

AGENT_PERSONA_MATRIX: Dict[str, Any] = {
    # ── Diagnostic Expert ────────────────────────────────────────────────────
    "diagnostic_expert": {
        "name": "Diagnostic Expert",
        "role": "Senior Industrial Diagnostic Engineer",
        "traits": [
            "analytical",
            "evidence-driven",
            "multi-hypothesis thinker",
            "causality-focused",
            "high-precision reasoning",
        ],
        # Original 8-dimension scores (1-10 integer scale, cross-agent comparison)
        "trait_scores": {
            "speed":                4,
            "analytical_depth":     10,
            "evidence_rigor":       10,
            "pattern_matching":     7,
            "uncertainty_handling": 7,
            "decision_confidence":  7,
            "consensus_building":   6,
            "risk_awareness":       8,
        },
        # ── Persona trait encoding (0.0 – 1.0 float, per AGENT_PERSONAS definition)
        # Includes 5 original traits + 3 inferred from reasoning_style
        "persona_trait_scores": {
            # --- original traits ---
            "analytical":               0.90,  # strong — exhaustive signal interpretation
            "evidence-driven":          1.00,  # dominant — explicitly compares supporting vs contradicting evidence
            "multi-hypothesis thinker": 1.00,  # dominant — generates multiple plausible failure modes before concluding
            "causality-focused":        0.90,  # strong — validates using physical principles and causal chains
            "high-precision reasoning": 1.00,  # dominant — never jumps to conclusions; structured elimination
            # --- inferred from reasoning_style: multi-hypothesis, evidence-weighted, causality-driven ---
            "systematic":               0.85,  # strong — follows strict engineering diagnostic methodology
            "exhaustive":               0.80,  # strong — checks ALL observed sensor patterns for consistency
            "deliberate":               0.75,  # moderate-strong — intentionally slow to avoid premature conclusions
        },
        "trait_vector": [0.90, 1.00, 1.00, 0.90, 1.00, 0.85, 0.80, 0.75],
        "dominant_traits": [
            "evidence-driven",
            "multi-hypothesis thinker",
            "high-precision reasoning",
        ],
        "normalization_note": (
            "Scores 1.0 assigned to traits that are explicitly stated as primary drivers "
            "('never jumps to conclusions', 'explicitly compares evidence'). "
            "Causality-focused and analytical scored 0.9 as strong but secondary to evidence-weighting. "
            "Three traits inferred from reasoning_style: systematic (0.85), exhaustive (0.8), deliberate (0.75)."
        ),
        "baseline_scores": {
            "faithfulness_score": 0.78, "reasoning_score": 0.82,
            "agreement_score": 0.70,    "coverage_score": 0.75,
            "hallucination_rate": 0.18, "reliability_score": 0.77,
        },
        # ── Persona-trait influence on each evaluation metric ─────────────────
        # Trait score (1-10) × weight → expected metric lift/drag for this agent
        "trait_metric_influence": {
            "faithfulness_score": {"evidence_rigor": 10, "analytical_depth": 10, "speed": 4},
            "reasoning_score":    {"analytical_depth": 10, "pattern_matching": 7, "speed": 4},
            "agreement_score":    {"consensus_building": 6, "decision_confidence": 7, "uncertainty_handling": 7},
            "coverage_score":     {"pattern_matching": 7, "risk_awareness": 8, "uncertainty_handling": 7},
            "reliability_score":  {"decision_confidence": 7, "risk_awareness": 8, "uncertainty_handling": 7},
        },
    },

    # ── Pattern Recognition Agent ─────────────────────────────────────────────
    "pattern_agent": {
        "name": "Pattern Recognition Agent",
        "role": "Sensor Analytics Expert",
        "traits": [
            "pattern-focused",
            "correlation-aware",
            "data-driven",
            "statistical",
            "signal-analysis expert",
        ],
        "trait_scores": {
            "speed":                6,
            "analytical_depth":     7,
            "evidence_rigor":       7,
            "pattern_matching":     10,
            "uncertainty_handling": 5,
            "decision_confidence":  7,
            "consensus_building":   5,
            "risk_awareness":       6,
        },
        "persona_trait_scores": {
            # --- original traits ---
            "pattern-focused":      1.00,  # dominant — entire role built on pattern identification
            "correlation-aware":    0.95,  # dominant — explicitly focuses on vibration/temp/pressure relationships
            "data-driven":          0.90,  # strong — interprets sensor readings as multidimensional signals
            "statistical":          0.85,  # strong — ranks failure modes by similarity scores
            "signal-analysis expert": 0.95, # dominant — detects co-occurring and subtle isolated anomalies
            # --- inferred from reasoning_style: pattern-matching, correlation, similarity scoring ---
            "similarity-scoring":   0.90,  # strong — core of ranking mechanism
            "multidimensional":     0.80,  # strong — simultaneous multi-sensor correlation
            "anomaly-sensitive":    0.80,  # strong — detects patterns not obvious in isolation
        },
        "trait_vector": [1.00, 0.95, 0.90, 0.85, 0.95, 0.90, 0.80, 0.80],
        "dominant_traits": [
            "pattern-focused",
            "signal-analysis expert",
            "correlation-aware",
        ],
        "normalization_note": (
            "Pattern-focused and signal-analysis expert scored 1.0/0.95 as the defining operational traits. "
            "Correlation-aware scored 0.95 because multi-sensor correlation is explicitly stated as the core method. "
            "Statistical scored 0.85 — important but subordinate to pattern recognition. "
            "Three inferred traits from reasoning_style: similarity-scoring (0.9), multidimensional (0.8), anomaly-sensitive (0.8)."
        ),
        "baseline_scores": {
            "faithfulness_score": 0.72, "reasoning_score": 0.70,
            "agreement_score": 0.68,    "coverage_score": 0.80,
            "hallucination_rate": 0.22, "reliability_score": 0.73,
        },
        "trait_metric_influence": {
            "faithfulness_score": {"evidence_rigor": 7, "analytical_depth": 7, "speed": 6},
            "reasoning_score":    {"analytical_depth": 7, "pattern_matching": 10, "speed": 6},
            "agreement_score":    {"consensus_building": 5, "decision_confidence": 7, "uncertainty_handling": 5},
            "coverage_score":     {"pattern_matching": 10, "risk_awareness": 6, "uncertainty_handling": 5},
            "reliability_score":  {"decision_confidence": 7, "risk_awareness": 6, "uncertainty_handling": 5},
        },
    },

    # ── Aggressive Decision Agent ─────────────────────────────────────────────
    "aggressive_agent": {
        "name": "Aggressive Decision Agent",
        "role": "Rapid Response Operator",
        "traits": [
            "fast",
            "decisive",
            "signal-prioritization",
            "pragmatic",
            "action-oriented",
        ],
        "trait_scores": {
            "speed":                10,
            "analytical_depth":     4,
            "evidence_rigor":       5,
            "pattern_matching":     6,
            "uncertainty_handling": 2,
            "decision_confidence":  10,
            "consensus_building":   3,
            "risk_awareness":       5,
        },
        "persona_trait_scores": {
            # --- original traits ---
            "fast":                   1.00,  # dominant — speed is the explicit design goal
            "decisive":               1.00,  # dominant — commits fully; does not hedge
            "signal-prioritization":  0.95,  # dominant — focuses only on strongest abnormal signals
            "pragmatic":              0.85,  # strong — provides actionable diagnosis even if not exhaustive
            "action-oriented":        0.90,  # strong — pushes immediate response as primary output
            # --- inferred from reasoning_style: dominant-signal heuristic, fast pattern mapping ---
            "heuristic-based":        0.90,  # strong — maps dominant symptoms directly to known failure modes
            "risk-tolerant":          0.80,  # strong — intentionally ignores ambiguous signals
            "threshold-driven":       0.85,  # strong — acts when dominant signal crosses decision threshold
        },
        "trait_vector": [1.00, 1.00, 0.95, 0.85, 0.90, 0.90, 0.80, 0.85],
        "dominant_traits": [
            "fast",
            "decisive",
            "signal-prioritization",
        ],
        "normalization_note": (
            "Fast and decisive scored 1.0 as the twin design objectives of rapid-triage. "
            "Signal-prioritization scored 0.95 — the core filtering mechanism. "
            "Action-oriented (0.9) ranked above pragmatic (0.85) as it is the stated primary output goal. "
            "Inferred: heuristic-based (0.9) from dominant-signal reasoning; risk-tolerant (0.8) because "
            "weak/ambiguous signals are intentionally ignored; threshold-driven (0.85) from fast pattern mapping."
        ),
        "baseline_scores": {
            "faithfulness_score": 0.60, "reasoning_score": 0.65,
            "agreement_score": 0.58,    "coverage_score": 0.55,
            "hallucination_rate": 0.30, "reliability_score": 0.62,
        },
        # Speed=10, DecisionConfidence=10 → high reliability but low faithfulness/reasoning
        "trait_metric_influence": {
            "faithfulness_score": {"evidence_rigor": 5, "analytical_depth": 4, "speed": 10},
            "reasoning_score":    {"analytical_depth": 4, "pattern_matching": 6, "speed": 10},
            "agreement_score":    {"consensus_building": 3, "decision_confidence": 10, "uncertainty_handling": 2},
            "coverage_score":     {"pattern_matching": 6, "risk_awareness": 5, "uncertainty_handling": 2},
            "reliability_score":  {"decision_confidence": 10, "risk_awareness": 5, "uncertainty_handling": 2},
        },
    },

    # ── Verification Analyst ──────────────────────────────────────────────────
    "verification": {
        "name": "Verification Analyst",
        "role": "Quality Assurance Specialist",
        "traits": [
            "skeptical",
            "logical",
            "elimination-driven",
            "consistency-checking",
            "precision-focused",
        ],
        "trait_scores": {
            "speed":                3,
            "analytical_depth":     9,
            "evidence_rigor":       10,
            "pattern_matching":     5,
            "uncertainty_handling": 8,
            "decision_confidence":  7,
            "consensus_building":   7,
            "risk_awareness":       9,
        },
        "persona_trait_scores": {
            # --- original traits ---
            "skeptical":              1.00,  # dominant — does not attempt to find the answer; only disprove
            "logical":                0.95,  # dominant — systematic check of every hypothesis against signals
            "elimination-driven":     1.00,  # dominant — sole mechanism: reject what contradicts evidence
            "consistency-checking":   0.95,  # dominant — validates each failure mode against ALL conditions
            "precision-focused":      0.90,  # strong — rejects hypothesis if even one critical condition violated
            # --- inferred from reasoning_style: falsification-based, contradiction analysis ---
            "falsification-oriented": 0.95,  # dominant — Popperian approach; prove hypotheses wrong first
            "contradiction-aware":    0.90,  # strong — actively seeks sensor contradictions
            "rigorous":               0.85,  # strong — exhaustive single-condition violation checks
        },
        "trait_vector": [1.00, 0.95, 1.00, 0.95, 0.90, 0.95, 0.90, 0.85],
        "dominant_traits": [
            "skeptical",
            "elimination-driven",
            "falsification-oriented",
        ],
        "normalization_note": (
            "Skeptical and elimination-driven scored 1.0 — the agent's entire purpose is disproval not discovery. "
            "Logical and consistency-checking scored 0.95 as the structural mechanisms of falsification. "
            "Precision-focused scored 0.90 — strong but slightly below consistency-checking since one violated "
            "condition suffices for rejection (doesn't require counting all violations). "
            "Inferred: falsification-oriented (0.95), contradiction-aware (0.9), rigorous (0.85) "
            "from reasoning_style: falsification-based reasoning with contradiction analysis."
        ),
        "baseline_scores": {
            "faithfulness_score": 0.80, "reasoning_score": 0.78,
            "agreement_score": 0.75,    "coverage_score": 0.72,
            "hallucination_rate": 0.15, "reliability_score": 0.79,
        },
        # EvidenceRigor=10, AnalyticalDepth=9 → strong faithfulness/reasoning
        "trait_metric_influence": {
            "faithfulness_score": {"evidence_rigor": 10, "analytical_depth": 9, "speed": 3},
            "reasoning_score":    {"analytical_depth": 9, "pattern_matching": 5, "speed": 3},
            "agreement_score":    {"consensus_building": 7, "decision_confidence": 7, "uncertainty_handling": 8},
            "coverage_score":     {"pattern_matching": 5, "risk_awareness": 9, "uncertainty_handling": 8},
            "reliability_score":  {"decision_confidence": 7, "risk_awareness": 9, "uncertainty_handling": 8},
        },
    },

    # ── Ambiguity Detection Agent ─────────────────────────────────────────────
    "ambiguity": {
        "name": "Ambiguity Detection Agent",
        "role": "Uncertainty Assessment Specialist",
        "traits": [
            "risk-aware",
            "uncertainty-focused",
            "conservative",
            "conflict-detection",
            "safety-oriented",
        ],
        "trait_scores": {
            "speed":                4,
            "analytical_depth":     7,
            "evidence_rigor":       8,
            "pattern_matching":     6,
            "uncertainty_handling": 10,
            "decision_confidence":  3,
            "consensus_building":   6,
            "risk_awareness":       10,
        },
        "persona_trait_scores": {
            # --- original traits ---
            "risk-aware":           1.00,  # dominant — risk evaluation is the core output
            "uncertainty-focused":  1.00,  # dominant — specialises in identifying diagnostic uncertainty
            "conservative":         0.90,  # strong — recommends human review when confidence is low
            "conflict-detection":   0.95,  # dominant — explicitly analyses conflicting signals and patterns
            "safety-oriented":      0.95,  # dominant — flags ambiguous cases before they become safety risks
            # --- inferred from reasoning_style: uncertainty-aware, conflict detection ---
            "escalation-prone":     0.85,  # strong — default outcome when uncertain is to escalate
            "evidence-skeptical":   0.80,  # strong — questions whether evidence clearly supports one mode
            "threshold-cautious":   0.80,  # strong — acts at lower confidence threshold than other agents
        },
        "trait_vector": [1.00, 1.00, 0.90, 0.95, 0.95, 0.85, 0.80, 0.80],
        "dominant_traits": [
            "risk-aware",
            "uncertainty-focused",
            "conflict-detection",
        ],
        "normalization_note": (
            "Risk-aware and uncertainty-focused scored 1.0 — both are the explicit mission of this agent. "
            "Conflict-detection and safety-oriented scored 0.95 — direct operational outputs of the uncertainty evaluation. "
            "Conservative scored 0.90 — strong but slightly below conflict-detection since it is the response "
            "to detected uncertainty rather than the detection itself. "
            "Inferred: escalation-prone (0.85) — default action under uncertainty; evidence-skeptical (0.8) and "
            "threshold-cautious (0.8) from uncertainty-aware evaluation reasoning_style."
        ),
        "baseline_scores": {
            "faithfulness_score": 0.70, "reasoning_score": 0.73,
            "agreement_score": 0.65,    "coverage_score": 0.68,
            "hallucination_rate": 0.20, "reliability_score": 0.70,
        },
        # UncertaintyHandling=10, RiskAwareness=10 → high coverage but low confidence/agreement
        "trait_metric_influence": {
            "faithfulness_score": {"evidence_rigor": 8, "analytical_depth": 7, "speed": 4},
            "reasoning_score":    {"analytical_depth": 7, "pattern_matching": 6, "speed": 4},
            "agreement_score":    {"consensus_building": 6, "decision_confidence": 3, "uncertainty_handling": 10},
            "coverage_score":     {"pattern_matching": 6, "risk_awareness": 10, "uncertainty_handling": 10},
            "reliability_score":  {"decision_confidence": 3, "risk_awareness": 10, "uncertainty_handling": 10},
        },
    },

    # ── Human Review Coordinator ──────────────────────────────────────────────
    "human_review_coordinator": {
        "name": "Human Review Coordinator",
        "role": "Consensus Manager & Final Decision Authority",
        "traits": [
            "integrative",
            "balanced",
            "decision-making",
            "consensus-driven",
            "evidence-weighted",
        ],
        "trait_scores": {
            "speed":                6,
            "analytical_depth":     7,
            "evidence_rigor":       8,
            "pattern_matching":     5,
            "uncertainty_handling": 7,
            "decision_confidence":  9,
            "consensus_building":   10,
            "risk_awareness":       7,
        },
        "persona_trait_scores": {
            # --- original traits ---
            "integrative":        1.00,  # dominant — synthesises ALL agent outputs into one decision
            "balanced":           0.90,  # strong — weighs agreements and disagreements without bias
            "decision-making":    0.90,  # strong — final decision authority; must commit to an answer
            "consensus-driven":   1.00,  # dominant — reinforces decisions supported by multiple agents
            "evidence-weighted":  0.95,  # dominant — prioritises decisions backed by strongest evidence
            # --- inferred from reasoning_style: ensemble reasoning, consensus, evidence weighting ---
            "synthesizing":       0.95,  # dominant — combines multiple diagnostic perspectives into one
            "conflict-resolving": 0.85,  # strong — selects most evidence-backed option when agents conflict
            "authoritative":      0.85,  # strong — escalates to human intervention as final backstop
        },
        "trait_vector": [1.00, 0.90, 0.90, 1.00, 0.95, 0.95, 0.85, 0.85],
        "dominant_traits": [
            "integrative",
            "consensus-driven",
            "synthesizing",
        ],
        "normalization_note": (
            "Integrative and consensus-driven scored 1.0 — the agent exists to merge multiple perspectives into one final decision. "
            "Evidence-weighted and synthesizing scored 0.95 — critical operational mechanisms; lower than 1.0 because "
            "they serve the consensus goal rather than being the goal itself. "
            "Balanced and decision-making scored 0.90 — strong but secondary to integration. "
            "Inferred: synthesizing (0.95) from ensemble reasoning; conflict-resolving (0.85) and authoritative (0.85) "
            "from 'selects most evidence-backed option' and 'escalate for human intervention' in backstory."
        ),
        "baseline_scores": {
            "faithfulness_score": 0.76, "reasoning_score": 0.80,
            "agreement_score": 0.85,    "coverage_score": 0.78,
            "hallucination_rate": 0.16, "reliability_score": 0.80,
        },
        # ConsensusBuilding=10, DecisionConfidence=9 → highest agreement and reliability
        "trait_metric_influence": {
            "faithfulness_score": {"evidence_rigor": 8, "analytical_depth": 7, "speed": 6},
            "reasoning_score":    {"analytical_depth": 7, "pattern_matching": 5, "speed": 6},
            "agreement_score":    {"consensus_building": 10, "decision_confidence": 9, "uncertainty_handling": 7},
            "coverage_score":     {"pattern_matching": 5, "risk_awareness": 7, "uncertainty_handling": 7},
            "reliability_score":  {"decision_confidence": 9, "risk_awareness": 7, "uncertainty_handling": 7},
        },
    },
}



def get_agent_aggregates(
    limit: int = 200,
    dataset_filter: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Aggregate per-agent metrics across all stored analysis records.
    Each agent entry now includes:
      - trait_scores    : numeric 1-10 scores for 8 standardised dimensions
      - trait_comparison: per-dimension winner across all agents
      - baseline_scores : expected RAG metric baselines (0-1)
      - actual_scores   : averaged from real pipeline runs
      - per_question    : per-query breakdown for charts
      - verdict         : best_at / worst_at / overall_verdict
    """
    try:
        records = get_analyses(limit=limit, dataset_filter=dataset_filter)
    except Exception as exc:
        logger.error("[DB] get_agent_aggregates failed: %s", exc)
        records = []

    _METRIC_KEYS = [
        "faithfulness_score", "reasoning_score", "agreement_score",
        "coverage_score", "hallucination_rate", "reliability_score",
    ]

    sums: Dict[str, Dict[str, float]] = defaultdict(lambda: defaultdict(float))
    counts: Dict[str, int] = defaultdict(int)
    per_question: Dict[str, List[Dict]] = defaultdict(list)
    questions_seen: List[str] = []

    for row in records:
        report = row.get("analysis_json", {})
        if not isinstance(report, dict):
            continue
        inline = report.get("inline_evaluation", {})
        if not isinstance(inline, dict):
            continue
        per_agent_evals = inline.get("per_agent_evaluations", [])
        if not isinstance(per_agent_evals, list):
            continue

        question_short = str(row.get("question", ""))[:60]
        if question_short not in questions_seen:
            questions_seen.append(question_short)

        for agent_eval in per_agent_evals:
            if not isinstance(agent_eval, dict):
                continue
            key = str(agent_eval.get("agent_key", ""))
            if not key:
                continue
            counts[key] += 1
            q_scores = {}
            for metric in _METRIC_KEYS:
                val = agent_eval.get(metric)
                try:
                    val = float(val)
                except (TypeError, ValueError):
                    val = 0.0
                sums[key][metric] += val
                q_scores[metric] = round(val, 3)
            per_question[key].append({
                "question": question_short,
                "scores": q_scores,
                "verdict": str(agent_eval.get("verdict", "")),
            })

    result: Dict[str, Any] = {}
    for key, persona in AGENT_PERSONA_MATRIX.items():
        n = counts.get(key, 0)
        if n > 0:
            actual = {
                metric: round(sums[key][metric] / n, 3)
                for metric in _METRIC_KEYS
            }
        else:
            actual = dict(persona["baseline_scores"])

        scored = {m: actual[m] for m in ["faithfulness_score", "reasoning_score", "agreement_score", "coverage_score"]}
        scored["low_hallucination"] = round(1.0 - actual.get("hallucination_rate", 0.0), 3)
        best_metric = max(scored, key=scored.__getitem__)
        worst_metric = min(scored, key=scored.__getitem__)

        metric_labels = {
            "faithfulness_score": "RAG Faithfulness",
            "reasoning_score": "Reasoning Quality",
            "agreement_score": "Answer Agreement",
            "coverage_score": "Evidence Coverage",
            "low_hallucination": "Low Hallucination Rate",
        }

        reliability = actual.get("reliability_score", 0.0)
        if reliability >= 0.75:
            overall_verdict = "Strong Performer"
        elif reliability >= 0.55:
            overall_verdict = "Moderate Performer"
        else:
            overall_verdict = "Needs Improvement"

        # Compute persona-trait weighted expected scores for each metric
        trait_weighted_expected: Dict[str, Any] = {}
        for metric, weights in TRAIT_TO_METRIC_WEIGHTS.items():
            trait_scores = persona["trait_scores"]
            positive_weight_sum = sum(w for w in weights.values() if w > 0)
            weighted_sum = 0.0
            for trait, weight in weights.items():
                raw_trait_score = trait_scores.get(trait, 5)  # 1-10 scale
                normalised = raw_trait_score / 10.0           # convert to 0-1
                weighted_sum += normalised * weight
            # Normalise by positive weight sum only (negative weights are penalties)
            if positive_weight_sum > 0:
                trait_weighted_expected[metric] = round(
                    max(0.0, min(1.0, weighted_sum / positive_weight_sum)), 3
                )
            else:
                trait_weighted_expected[metric] = 0.0

        result[key] = {
            "agent_key": key,
            "name": persona["name"],
            "role": persona["role"],
            "traits": persona["traits"],
            # 8-dimension cross-agent scores (1-10 integer)
            "trait_scores": persona["trait_scores"],
            # Per-trait 0.0-1.0 encoding + inferred traits from reasoning_style
            "persona_trait_scores": persona.get("persona_trait_scores", {}),
            "trait_vector": persona.get("trait_vector", []),
            "dominant_traits": persona.get("dominant_traits", []),
            "normalization_note": persona.get("normalization_note", ""),
            "baseline_scores": persona["baseline_scores"],
            "actual_scores": actual,
            # Persona-trait weighted expected scores — what the agent SHOULD score
            # given its trait profile (e.g. Aggressive should have low faithfulness)
            "trait_weighted_expected": trait_weighted_expected,
            # Per-metric: which traits drive the score and their raw values for this agent
            "trait_metric_influence": persona.get("trait_metric_influence", {}),
            "total_questions": n,
            "per_question": per_question.get(key, []),
            "verdict": {
                "best_at": metric_labels.get(best_metric, best_metric),
                "worst_at": metric_labels.get(worst_metric, worst_metric),
                "overall_verdict": overall_verdict,
                "reliability_score": actual.get("reliability_score", 0.0),
            },
        }

    # ── Trait comparison: for each dimension find winner, runner-up, weakest ──
    trait_comparison: Dict[str, Any] = {}
    for dim in TRAIT_DIMENSIONS:
        ranked = sorted(
            [(key, AGENT_PERSONA_MATRIX[key]["trait_scores"][dim], AGENT_PERSONA_MATRIX[key]["name"])
             for key in AGENT_PERSONA_MATRIX],
            key=lambda x: x[1],
            reverse=True,
        )
        all_scores = {key: AGENT_PERSONA_MATRIX[key]["trait_scores"][dim] for key in AGENT_PERSONA_MATRIX}
        trait_comparison[dim] = {
            "label": TRAIT_LABELS[dim],
            "winner_key": ranked[0][0],
            "winner_name": ranked[0][2],
            "winner_score": ranked[0][1],
            "runner_up_key": ranked[1][0] if len(ranked) > 1 else None,
            "runner_up_name": ranked[1][2] if len(ranked) > 1 else None,
            "runner_up_score": ranked[1][1] if len(ranked) > 1 else None,
            "weakest_key": ranked[-1][0],
            "weakest_name": ranked[-1][2],
            "weakest_score": ranked[-1][1],
            "all_scores": all_scores,
        }

    return {
        "agents": result,
        "trait_comparison": trait_comparison,
        "trait_dimensions": TRAIT_DIMENSIONS,
        "trait_labels": TRAIT_LABELS,
        "trait_to_metric_weights": TRAIT_TO_METRIC_WEIGHTS,
        "metric_trait_descriptions": METRIC_TRAIT_DESCRIPTIONS,
        "total_records": len(records),
        "questions_analysed": questions_seen,
    }

