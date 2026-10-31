"""
SQLite persistence for AgentTrace.

Lives in the same SQLite file as the existing analysis history
(``ANALYSIS_DB_PATH``, default ``./data/analysis_store.db``) unless
``AGENT_TRACE_DB_PATH`` points elsewhere — no new infrastructure.

Design:
* **Raw, append-only**: ``trace_events`` rows are only ever inserted, each with a
  per-trace sequence number (``seq``) that gives a total order even when agents
  run concurrently; a ``dedup_key`` UNIQUE constraint makes re-recording the same
  observation a no-op.
* **Write-through**: every row is committed as it is recorded, so a failing agent
  (or a crashing process) never loses events already observed.
* **Structured tables** for messages, deliveries, agent executions, evidence,
  evidence links and hypothesis states — queried by the API and the analyzer.
* **Semantic snapshot** (``agent_traces.semantic_json``) is written once at the
  end and is clearly separate from the raw rows it is derived from.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from typing import Any, Dict, Iterable, List, Optional, Tuple

from utils.logger import setup_logger

logger = setup_logger("harness.agent_trace.repository")

_DDL = [
    """CREATE TABLE IF NOT EXISTS agent_traces (
        trace_id TEXT PRIMARY KEY, run_id TEXT, analysis_id INTEGER, schema_version TEXT NOT NULL,
        query TEXT NOT NULL, dataset_type TEXT NOT NULL, data_mode TEXT NOT NULL,
        llm_mode TEXT, llm_provider TEXT, llm_model TEXT, config_json TEXT,
        status TEXT NOT NULL, started_at TEXT NOT NULL, completed_at TEXT, duration_ms REAL,
        final_label TEXT, final_diagnosis TEXT, final_confidence REAL, review_decision TEXT,
        communication_rounds INTEGER, total_messages INTEGER, total_events INTEGER,
        total_evidence_refs INTEGER, error TEXT, semantic_json TEXT, updated_at TEXT)""",
    "CREATE INDEX IF NOT EXISTS idx_at_started ON agent_traces(started_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_at_analysis ON agent_traces(analysis_id)",
    "CREATE INDEX IF NOT EXISTS idx_at_run ON agent_traces(run_id)",
    """CREATE TABLE IF NOT EXISTS trace_events (
        trace_id TEXT NOT NULL, seq INTEGER NOT NULL, event_id TEXT NOT NULL UNIQUE, event_type TEXT NOT NULL,
        ts TEXT NOT NULL, actor TEXT, execution_id TEXT, message_id TEXT, evidence_ids_json TEXT,
        parent_event_id TEXT, payload_json TEXT, dedup_key TEXT,
        PRIMARY KEY (trace_id, seq), UNIQUE (trace_id, dedup_key))""",
    "CREATE INDEX IF NOT EXISTS idx_te_type ON trace_events(trace_id, event_type)",
    """CREATE TABLE IF NOT EXISTS trace_messages (
        trace_id TEXT NOT NULL, message_id TEXT NOT NULL, seq INTEGER NOT NULL, round_id INTEGER NOT NULL,
        stage TEXT, sender TEXT NOT NULL, sender_execution_id TEXT, recipients_json TEXT NOT NULL,
        message_type TEXT NOT NULL, topic TEXT, content TEXT NOT NULL, evidence_ids_json TEXT,
        hypothesis_ids_json TEXT, parent_message_id TEXT, response_to_message_id TEXT, payload_json TEXT,
        ts TEXT NOT NULL, resolved INTEGER, challenge_status TEXT, resolution_status TEXT,
        PRIMARY KEY (trace_id, message_id))""",
    """CREATE TABLE IF NOT EXISTS trace_message_deliveries (
        trace_id TEXT NOT NULL, message_id TEXT NOT NULL, receiver TEXT NOT NULL, via TEXT NOT NULL,
        seq INTEGER NOT NULL, execution_id TEXT, ts TEXT NOT NULL,
        PRIMARY KEY (trace_id, message_id, receiver, via))""",
    """CREATE TABLE IF NOT EXISTS trace_agent_executions (
        trace_id TEXT NOT NULL, execution_id TEXT NOT NULL, agent_id TEXT NOT NULL, agent_name TEXT,
        role TEXT, stage TEXT, kind TEXT, pass_number INTEGER, round_id INTEGER,
        seq_start INTEGER, seq_end INTEGER, started_at TEXT, completed_at TEXT, duration_ms REAL,
        status TEXT NOT NULL, error TEXT, input_json TEXT, evidence_in_input_json TEXT,
        rendered_system TEXT, rendered_input TEXT, llm_calls_json TEXT, output_json TEXT,
        finding_label TEXT, confidence REAL, hypotheses_json TEXT, claims_json TEXT,
        messages_sent_json TEXT, messages_received_json TEXT, tool_calls_json TEXT,
        PRIMARY KEY (trace_id, execution_id))""",
    """CREATE TABLE IF NOT EXISTS trace_evidence (
        trace_id TEXT NOT NULL, evidence_id TEXT NOT NULL, kind TEXT NOT NULL, provenance TEXT,
        dataset TEXT, record_id TEXT, label TEXT, retrieval_action TEXT, retrieval_method TEXT,
        retrieval_round INTEGER, retrieval_score REAL, method_scores_json TEXT, description TEXT,
        first_seq INTEGER, PRIMARY KEY (trace_id, evidence_id))""",
    """CREATE TABLE IF NOT EXISTS trace_evidence_links (
        trace_id TEXT NOT NULL, evidence_id TEXT NOT NULL, relation TEXT NOT NULL, subject_id TEXT NOT NULL,
        value TEXT, actor TEXT, seq INTEGER NOT NULL, detail_json TEXT,
        PRIMARY KEY (trace_id, evidence_id, relation, subject_id))""",
    "CREATE INDEX IF NOT EXISTS idx_tel_rel ON trace_evidence_links(trace_id, relation)",
    """CREATE TABLE IF NOT EXISTS trace_hypothesis_states (
        trace_id TEXT NOT NULL, seq INTEGER NOT NULL, hypothesis_id TEXT NOT NULL, label TEXT NOT NULL,
        agent_id TEXT NOT NULL, status TEXT NOT NULL, execution_id TEXT, message_id TEXT, round_id INTEGER,
        score REAL, evidence_ids_json TEXT, reason TEXT, ts TEXT NOT NULL,
        PRIMARY KEY (trace_id, seq))""",
]


def db_path() -> str:
    """Resolved at call time so tests and deployments can redirect it."""
    p = os.getenv("AGENT_TRACE_DB_PATH") or os.getenv("ANALYSIS_DB_PATH", "./data/analysis_store.db")
    os.makedirs(os.path.dirname(os.path.abspath(p)), exist_ok=True)
    return p


def _j(v: Any) -> Optional[str]:
    return None if v is None else json.dumps(v, default=str)


def _l(s: Optional[str], default: Any = None) -> Any:
    if s is None:
        return default
    try:
        return json.loads(s)
    except (TypeError, ValueError):
        return default


_initialised: set = set()
_init_lock = threading.Lock()


def connect(path: Optional[str] = None) -> sqlite3.Connection:
    path = path or db_path()
    con = sqlite3.connect(path, check_same_thread=False, timeout=10.0)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL;")
    con.execute("PRAGMA synchronous=NORMAL;")
    con.execute("PRAGMA busy_timeout=10000;")
    with _init_lock:
        if path not in _initialised:
            for stmt in _DDL:
                con.execute(stmt)
            con.commit()
            _initialised.add(path)
    return con


def init_trace_tables(path: Optional[str] = None) -> None:
    con = connect(path)
    con.close()


class TraceWriter:
    """Write side, owned by one TraceRecorder (one diagnostic run)."""

    def __init__(self, path: Optional[str] = None):
        self.path = path or db_path()
        self.con = connect(self.path)
        self.lock = threading.Lock()

    def _exec(self, sql: str, params: Tuple) -> int:
        with self.lock:
            cur = self.con.execute(sql, params)
            self.con.commit()
            return cur.rowcount

    def close(self) -> None:
        with self.lock:
            try:
                self.con.close()
            except Exception:  # pragma: no cover
                pass

    # ── trace row ────────────────────────────────────────────────────────────
    def insert_trace(self, row: Dict[str, Any]) -> None:
        self._exec("""INSERT INTO agent_traces (trace_id, run_id, analysis_id, schema_version, query, dataset_type,
                      data_mode, llm_mode, llm_provider, llm_model, config_json, status, started_at, updated_at)
                      VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                   (row["trace_id"], row.get("run_id"), row.get("analysis_id"), row["schema_version"], row["query"],
                    row["dataset_type"], row["data_mode"], row.get("llm_mode"), row.get("llm_provider"),
                    row.get("llm_model"), _j(row.get("config")), row["status"], row["started_at"], row["started_at"]))

    def update_trace(self, trace_id: str, fields: Dict[str, Any]) -> None:
        cols = {k: (_j(v) if k.endswith("_json") and not isinstance(v, str) else v) for k, v in fields.items()}
        sets = ", ".join(f"{k}=?" for k in cols)
        self._exec(f"UPDATE agent_traces SET {sets} WHERE trace_id=?", (*cols.values(), trace_id))

    # ── raw events (append-only) ─────────────────────────────────────────────
    def insert_event(self, e: Dict[str, Any]) -> bool:
        n = self._exec("""INSERT OR IGNORE INTO trace_events (trace_id, seq, event_id, event_type, ts, actor,
                          execution_id, message_id, evidence_ids_json, parent_event_id, payload_json, dedup_key)
                          VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                       (e["trace_id"], e["seq"], e["event_id"], e["event_type"], e["ts"], e.get("actor"),
                        e.get("execution_id"), e.get("message_id"), _j(e.get("evidence_ids") or []),
                        e.get("parent_event_id"), _j(e.get("payload") or {}), e.get("dedup_key")))
        return n > 0

    # ── messages ─────────────────────────────────────────────────────────────
    def insert_message(self, m: Dict[str, Any]) -> bool:
        n = self._exec("""INSERT OR IGNORE INTO trace_messages (trace_id, message_id, seq, round_id, stage, sender,
                          sender_execution_id, recipients_json, message_type, topic, content, evidence_ids_json,
                          hypothesis_ids_json, parent_message_id, response_to_message_id, payload_json, ts, resolved,
                          challenge_status, resolution_status) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                       (m["trace_id"], m["message_id"], m["seq"], m["round_id"], m.get("stage"), m["sender"],
                        m.get("sender_execution_id"), _j(m["recipients"]), m["message_type"], m.get("topic"),
                        m["content"], _j(m.get("evidence_ids") or []), _j(m.get("hypothesis_ids") or []),
                        m.get("parent_message_id"), m.get("response_to_message_id"), _j(m.get("payload") or {}),
                        m["ts"], None if m.get("resolved") is None else int(bool(m["resolved"])),
                        m.get("challenge_status"), m.get("resolution_status")))
        return n > 0

    def update_message_status(self, trace_id: str, message_id: str, resolved: Optional[bool],
                              challenge_status: str, resolution_status: str, payload: Optional[Dict] = None) -> None:
        if payload is None:
            self._exec("""UPDATE trace_messages SET resolved=?, challenge_status=?, resolution_status=?
                          WHERE trace_id=? AND message_id=?""",
                       (None if resolved is None else int(bool(resolved)), challenge_status, resolution_status,
                        trace_id, message_id))
        else:
            self._exec("""UPDATE trace_messages SET resolved=?, challenge_status=?, resolution_status=?, payload_json=?
                          WHERE trace_id=? AND message_id=?""",
                       (None if resolved is None else int(bool(resolved)), challenge_status, resolution_status,
                        _j(payload), trace_id, message_id))

    def insert_delivery(self, d: Dict[str, Any]) -> bool:
        n = self._exec("""INSERT OR IGNORE INTO trace_message_deliveries (trace_id, message_id, receiver, via, seq,
                          execution_id, ts) VALUES (?,?,?,?,?,?,?)""",
                       (d["trace_id"], d["message_id"], d["receiver"], d["via"], d["seq"], d.get("execution_id"), d["ts"]))
        return n > 0

    # ── executions ───────────────────────────────────────────────────────────
    def insert_execution(self, x: Dict[str, Any]) -> None:
        self._exec("""INSERT OR IGNORE INTO trace_agent_executions (trace_id, execution_id, agent_id, agent_name, role,
                      stage, kind, pass_number, round_id, seq_start, started_at, status, input_json,
                      evidence_in_input_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                   (x["trace_id"], x["execution_id"], x["agent_id"], x.get("agent_name"), x.get("role"), x.get("stage"),
                    x.get("kind"), x.get("pass_number"), x.get("round_id"), x["seq_start"], x["started_at"],
                    x["status"], _j(x.get("input")), _j(x.get("evidence_in_input") or [])))

    def update_execution(self, trace_id: str, execution_id: str, fields: Dict[str, Any]) -> None:
        cols = {}
        for k, v in fields.items():
            cols[k] = _j(v) if (k.endswith("_json") and not isinstance(v, str)) else v
        sets = ", ".join(f"{k}=?" for k in cols)
        self._exec(f"UPDATE trace_agent_executions SET {sets} WHERE trace_id=? AND execution_id=?",
                   (*cols.values(), trace_id, execution_id))

    # ── evidence ─────────────────────────────────────────────────────────────
    def insert_evidence(self, ev: Dict[str, Any]) -> bool:
        n = self._exec("""INSERT OR IGNORE INTO trace_evidence (trace_id, evidence_id, kind, provenance, dataset,
                          record_id, label, retrieval_action, retrieval_method, retrieval_round, retrieval_score,
                          method_scores_json, description, first_seq) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                       (ev["trace_id"], ev["evidence_id"], ev["kind"], ev.get("provenance"), ev.get("dataset"),
                        ev.get("record_id"), ev.get("label"), ev.get("retrieval_action"), ev.get("retrieval_method"),
                        ev.get("retrieval_round"), ev.get("retrieval_score"), _j(ev.get("method_scores")),
                        ev.get("description"), ev["first_seq"]))
        return n > 0

    def insert_links(self, rows: Iterable[Dict[str, Any]]) -> int:
        rows = list(rows)
        if not rows:
            return 0
        with self.lock:
            cur = self.con.executemany(
                """INSERT OR IGNORE INTO trace_evidence_links (trace_id, evidence_id, relation, subject_id, value,
                   actor, seq, detail_json) VALUES (?,?,?,?,?,?,?,?)""",
                [(r["trace_id"], r["evidence_id"], r["relation"], r["subject_id"], r.get("value"), r.get("actor"),
                  r["seq"], _j(r.get("detail"))) for r in rows])
            self.con.commit()
            return cur.rowcount

    def insert_hypothesis_state(self, h: Dict[str, Any]) -> None:
        self._exec("""INSERT OR IGNORE INTO trace_hypothesis_states (trace_id, seq, hypothesis_id, label, agent_id,
                      status, execution_id, message_id, round_id, score, evidence_ids_json, reason, ts)
                      VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                   (h["trace_id"], h["seq"], h["hypothesis_id"], h["label"], h["agent_id"], h["status"],
                    h.get("execution_id"), h.get("message_id"), h.get("round_id"), h.get("score"),
                    _j(h.get("evidence_ids") or []), h.get("reason"), h["ts"]))


# ── read side (used by the API and the analyzer) ─────────────────────────────

class TraceReader:
    def __init__(self, path: Optional[str] = None):
        self.path = path or db_path()

    def _q(self, sql: str, params: Tuple = ()) -> List[sqlite3.Row]:
        con = connect(self.path)
        try:
            return con.execute(sql, params).fetchall()
        finally:
            con.close()

    # traces
    def list_traces(self, limit: int = 50, offset: int = 0, status: Optional[str] = None,
                    dataset: Optional[str] = None) -> Tuple[List[Dict[str, Any]], int]:
        where, params = [], []
        if status:
            where.append("status=?"); params.append(status)
        if dataset:
            where.append("dataset_type=?"); params.append(dataset)
        w = ("WHERE " + " AND ".join(where)) if where else ""
        total = self._q(f"SELECT COUNT(*) AS n FROM agent_traces {w}", tuple(params))[0]["n"]
        rows = self._q(f"""SELECT trace_id, run_id, analysis_id, query, dataset_type, data_mode, status, started_at,
                           completed_at, duration_ms, final_label, final_confidence, review_decision,
                           communication_rounds, total_messages, llm_mode FROM agent_traces {w}
                           ORDER BY started_at DESC, rowid DESC LIMIT ? OFFSET ?""", (*params, limit, offset))
        return [dict(r) for r in rows], int(total)

    def get_trace(self, trace_id: str) -> Optional[Dict[str, Any]]:
        rows = self._q("SELECT * FROM agent_traces WHERE trace_id=?", (trace_id,))
        if not rows:
            return None
        d = dict(rows[0])
        d["config"] = _l(d.pop("config_json"), {})
        d["semantic"] = _l(d.pop("semantic_json"), None)
        return d

    def trace_for_analysis(self, analysis_id: int) -> Optional[str]:
        rows = self._q("SELECT trace_id FROM agent_traces WHERE analysis_id=? ORDER BY started_at DESC LIMIT 1",
                       (analysis_id,))
        return rows[0]["trace_id"] if rows else None

    def trace_for_run(self, run_id: str) -> Optional[str]:
        rows = self._q("SELECT trace_id FROM agent_traces WHERE run_id=? LIMIT 1", (run_id,))
        return rows[0]["trace_id"] if rows else None

    # events
    def events(self, trace_id: str, limit: int = 5000, offset: int = 0, event_type: Optional[str] = None,
               actor: Optional[str] = None) -> Tuple[List[Dict[str, Any]], int]:
        where, params = ["trace_id=?"], [trace_id]
        if event_type:
            where.append("event_type=?"); params.append(event_type)
        if actor:
            where.append("actor=?"); params.append(actor)
        w = " AND ".join(where)
        total = self._q(f"SELECT COUNT(*) AS n FROM trace_events WHERE {w}", tuple(params))[0]["n"]
        rows = self._q(f"SELECT * FROM trace_events WHERE {w} ORDER BY seq LIMIT ? OFFSET ?", (*params, limit, offset))
        out = []
        for r in rows:
            out.append({"event_id": r["event_id"], "trace_id": r["trace_id"], "seq": r["seq"],
                        "event_type": r["event_type"], "timestamp": r["ts"], "actor": r["actor"],
                        "execution_id": r["execution_id"], "message_id": r["message_id"],
                        "evidence_ids": _l(r["evidence_ids_json"], []), "parent_event_id": r["parent_event_id"],
                        "payload": _l(r["payload_json"], {})})
        return out, int(total)

    # messages
    def messages(self, trace_id: str) -> List[Dict[str, Any]]:
        deliveries: Dict[str, List[Dict[str, Any]]] = {}
        for d in self._q("SELECT * FROM trace_message_deliveries WHERE trace_id=? ORDER BY seq", (trace_id,)):
            deliveries.setdefault(d["message_id"], []).append(
                {"receiver": d["receiver"], "via": d["via"], "seq": d["seq"], "execution_id": d["execution_id"],
                 "timestamp": d["ts"]})
        out = []
        for r in self._q("SELECT * FROM trace_messages WHERE trace_id=? ORDER BY seq", (trace_id,)):
            out.append({
                "message_id": r["message_id"], "global_message_id": f"{trace_id}:{r['message_id']}",
                "trace_id": trace_id, "round_id": r["round_id"], "seq": r["seq"], "stage": r["stage"],
                "sender_agent_id": r["sender"], "sender_execution_id": r["sender_execution_id"],
                "receiver_agent_ids": _l(r["recipients_json"], []), "message_type": r["message_type"],
                "timestamp": r["ts"], "topic": r["topic"] or "", "message_content": r["content"],
                "related_hypothesis_ids": _l(r["hypothesis_ids_json"], []),
                "evidence_ids": _l(r["evidence_ids_json"], []), "parent_message_id": r["parent_message_id"],
                "response_to_message_id": r["response_to_message_id"],
                "challenge_status": r["challenge_status"] or "NOT_APPLICABLE",
                "resolution_status": r["resolution_status"] or "NOT_APPLICABLE",
                "payload": _l(r["payload_json"], {}), "deliveries": deliveries.get(r["message_id"], [])})
        return out

    # executions
    def executions(self, trace_id: str, include_prompts: bool = True) -> List[Dict[str, Any]]:
        out = []
        for r in self._q("SELECT * FROM trace_agent_executions WHERE trace_id=? ORDER BY seq_start", (trace_id,)):
            d = dict(r)
            for k in list(d):
                if k.endswith("_json"):
                    d[k[:-5]] = _l(d.pop(k), None)
            if not include_prompts:
                d["rendered_input"] = None if d.get("rendered_input") is None else f"<{len(d['rendered_input'])} chars>"
                d["rendered_system"] = None if d.get("rendered_system") is None else f"<{len(d['rendered_system'])} chars>"
            out.append(d)
        return out

    def evidence(self, trace_id: str) -> List[Dict[str, Any]]:
        out = []
        for r in self._q("SELECT * FROM trace_evidence WHERE trace_id=? ORDER BY first_seq", (trace_id,)):
            d = dict(r)
            d["method_scores"] = _l(d.pop("method_scores_json"), {})
            out.append(d)
        return out

    def evidence_links(self, trace_id: str) -> List[Dict[str, Any]]:
        out = []
        for r in self._q("SELECT * FROM trace_evidence_links WHERE trace_id=? ORDER BY seq", (trace_id,)):
            d = dict(r)
            d["detail"] = _l(d.pop("detail_json"), None)
            out.append(d)
        return out

    def hypothesis_states(self, trace_id: str) -> List[Dict[str, Any]]:
        out = []
        for r in self._q("SELECT * FROM trace_hypothesis_states WHERE trace_id=? ORDER BY seq", (trace_id,)):
            d = dict(r)
            d["evidence_ids"] = _l(d.pop("evidence_ids_json"), [])
            out.append(d)
        return out


def link_analysis(trace_id: str, analysis_id: int, path: Optional[str] = None) -> None:
    con = connect(path)
    try:
        con.execute("UPDATE agent_traces SET analysis_id=? WHERE trace_id=?", (analysis_id, trace_id))
        con.commit()
    finally:
        con.close()
