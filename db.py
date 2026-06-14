"""
SQLite cache for the Maharashtra Courts app.

Stores everything we've ever fetched from eCourts so we can serve it
instantly the next time. The DB file lives next to server.py at joshi.db
unless DB_PATH is set in the environment.

Tables:
  - cases              every case we've seen, keyed by CNR
  - case_details       rich detail JSON from viewHistory
  - cause_list_entries one row per (date, court, case) appearance
  - queries            log of every advocate search / cause-list scan

Convention: callers pass + receive plain dicts. The TTL helpers return
(payload, age_seconds) so callers / the UI can decide whether to refresh.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

DB_PATH = Path(os.getenv("DB_PATH", Path(__file__).parent / "joshi.db"))

# ── TTLs in seconds ────────────────────────────────────────────────────
TTL = {
    "districts": 30 * 86400,
    "complexes": 30 * 86400,
    "search_advocate": 12 * 3600,
    "case_detail": 6 * 3600,
    "cause_list_scan_future": 6 * 3600,
    "cause_list_scan_past": 365 * 86400,  # effectively forever
}


SCHEMA = """
CREATE TABLE IF NOT EXISTS cases (
  cnr            TEXT PRIMARY KEY,
  case_number    TEXT,
  case_type      TEXT,
  year           INTEGER,
  petitioner     TEXT,
  respondent     TEXT,
  court_no       TEXT,
  court_name     TEXT,
  status         TEXT,
  next_hearing   TEXT,
  case_no_id     TEXT,
  court_code     TEXT,
  advocate_seen  TEXT,
  last_seen      INTEGER,
  source_query   TEXT
);
CREATE INDEX IF NOT EXISTS idx_cases_advocate ON cases(advocate_seen);
CREATE INDEX IF NOT EXISTS idx_cases_next_hearing ON cases(next_hearing);
CREATE INDEX IF NOT EXISTS idx_cases_court ON cases(court_no);

CREATE TABLE IF NOT EXISTS case_details (
  cnr        TEXT PRIMARY KEY,
  json_blob  TEXT,
  fetched_at INTEGER
);

CREATE TABLE IF NOT EXISTS cause_list_entries (
  date            TEXT,
  court_no        TEXT,
  cnr             TEXT,
  item_number     TEXT,
  list_type       TEXT,
  adv_petitioner  TEXT,
  adv_respondent  TEXT,
  fetched_at      INTEGER,
  PRIMARY KEY (date, court_no, cnr)
);
CREATE INDEX IF NOT EXISTS idx_cl_date ON cause_list_entries(date);
CREATE INDEX IF NOT EXISTS idx_cl_cnr ON cause_list_entries(cnr);

CREATE TABLE IF NOT EXISTS queries (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  query_type   TEXT,
  cache_key    TEXT UNIQUE,
  payload      TEXT,
  result_count INTEGER,
  fetched_at   INTEGER
);
CREATE INDEX IF NOT EXISTS idx_queries_key ON queries(cache_key);
CREATE INDEX IF NOT EXISTS idx_queries_type ON queries(query_type);
"""


def _now() -> int:
    return int(time.time())


@contextmanager
def conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    try:
        yield c
        c.commit()
    finally:
        c.close()


def init():
    """Create tables if they don't exist."""
    with conn() as c:
        c.executescript(SCHEMA)


# ── generic query-result cache ─────────────────────────────────────────

def get_cached(query_type: str, key: str, ttl: int) -> tuple[object | None, int]:
    """Return (payload, age_seconds). payload is None on miss/expired."""
    with conn() as c:
        row = c.execute(
            "SELECT payload, fetched_at FROM queries WHERE cache_key = ? AND query_type = ?",
            (key, query_type),
        ).fetchone()
    if not row:
        return None, 0
    age = _now() - row["fetched_at"]
    if age > ttl:
        return None, age
    try:
        return json.loads(row["payload"]), age
    except Exception:
        return None, age


def put_cached(query_type: str, key: str, payload: object, result_count: int = 0):
    with conn() as c:
        c.execute(
            "INSERT INTO queries (query_type, cache_key, payload, result_count, fetched_at) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(cache_key) DO UPDATE SET "
            "  payload=excluded.payload, "
            "  result_count=excluded.result_count, "
            "  fetched_at=excluded.fetched_at",
            (query_type, key, json.dumps(payload), result_count, _now()),
        )


def invalidate(query_type: str, key: str):
    with conn() as c:
        c.execute(
            "DELETE FROM queries WHERE query_type = ? AND cache_key = ?",
            (query_type, key),
        )


# ── cases store ────────────────────────────────────────────────────────

def upsert_case(case: dict):
    """Insert/update one case row. Idempotent on cnr."""
    if not case.get("cnr"):
        return
    with conn() as c:
        c.execute(
            """
            INSERT INTO cases (
              cnr, case_number, case_type, year,
              petitioner, respondent,
              court_no, court_name, status, next_hearing,
              case_no_id, court_code, advocate_seen, last_seen, source_query
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(cnr) DO UPDATE SET
              case_number   = COALESCE(excluded.case_number,   cases.case_number),
              case_type     = COALESCE(excluded.case_type,     cases.case_type),
              year          = COALESCE(excluded.year,          cases.year),
              petitioner    = COALESCE(excluded.petitioner,    cases.petitioner),
              respondent    = COALESCE(excluded.respondent,    cases.respondent),
              court_no      = COALESCE(excluded.court_no,      cases.court_no),
              court_name    = COALESCE(excluded.court_name,    cases.court_name),
              status        = COALESCE(excluded.status,        cases.status),
              next_hearing  = COALESCE(excluded.next_hearing,  cases.next_hearing),
              case_no_id    = COALESCE(excluded.case_no_id,    cases.case_no_id),
              court_code    = COALESCE(excluded.court_code,    cases.court_code),
              advocate_seen = COALESCE(excluded.advocate_seen, cases.advocate_seen),
              last_seen     = excluded.last_seen,
              source_query  = COALESCE(excluded.source_query,  cases.source_query)
            """,
            (
                case.get("cnr"),
                case.get("case_number"),
                case.get("case_type"),
                _to_int(case.get("year")),
                case.get("petitioner"),
                case.get("respondent"),
                case.get("court_no"),
                case.get("court_name"),
                case.get("status"),
                case.get("next_hearing"),
                case.get("case_no_id"),
                case.get("court_code"),
                case.get("advocate_seen"),
                _now(),
                case.get("source_query"),
            ),
        )


def list_cases(advocate: str | None = None, limit: int = 1000) -> list[dict]:
    q = "SELECT * FROM cases"
    args = []
    if advocate:
        q += " WHERE advocate_seen LIKE ?"
        args.append(f"%{advocate}%")
    q += " ORDER BY (next_hearing IS NULL), next_hearing ASC, last_seen DESC LIMIT ?"
    args.append(limit)
    with conn() as c:
        return [dict(r) for r in c.execute(q, args).fetchall()]


def case_count() -> int:
    with conn() as c:
        return c.execute("SELECT COUNT(*) FROM cases").fetchone()[0]


# ── case detail store ──────────────────────────────────────────────────

def get_case_detail(cnr: str, ttl: int) -> tuple[dict | None, int]:
    with conn() as c:
        row = c.execute(
            "SELECT json_blob, fetched_at FROM case_details WHERE cnr = ?",
            (cnr,),
        ).fetchone()
    if not row:
        return None, 0
    age = _now() - row["fetched_at"]
    if age > ttl:
        return None, age
    try:
        return json.loads(row["json_blob"]), age
    except Exception:
        return None, age


def put_case_detail(cnr: str, detail: dict):
    with conn() as c:
        c.execute(
            "INSERT INTO case_details (cnr, json_blob, fetched_at) VALUES (?, ?, ?) "
            "ON CONFLICT(cnr) DO UPDATE SET json_blob = excluded.json_blob, "
            "  fetched_at = excluded.fetched_at",
            (cnr, json.dumps(detail), _now()),
        )


# ── cause list entries ─────────────────────────────────────────────────

def upsert_cause_list_entry(entry: dict):
    if not (entry.get("date") and entry.get("court_no") and entry.get("cnr")):
        return
    with conn() as c:
        c.execute(
            """
            INSERT INTO cause_list_entries (
              date, court_no, cnr, item_number, list_type,
              adv_petitioner, adv_respondent, fetched_at
            ) VALUES (?,?,?,?,?,?,?,?)
            ON CONFLICT(date, court_no, cnr) DO UPDATE SET
              item_number    = excluded.item_number,
              list_type      = excluded.list_type,
              adv_petitioner = excluded.adv_petitioner,
              adv_respondent = excluded.adv_respondent,
              fetched_at     = excluded.fetched_at
            """,
            (
                entry["date"], entry["court_no"], entry["cnr"],
                entry.get("item_number"), entry.get("list_type"),
                entry.get("adv_petitioner"), entry.get("adv_respondent"),
                _now(),
            ),
        )


# ── stats ──────────────────────────────────────────────────────────────

def stats() -> dict:
    with conn() as c:
        cases = c.execute("SELECT COUNT(*) FROM cases").fetchone()[0]
        details = c.execute("SELECT COUNT(*) FROM case_details").fetchone()[0]
        cl_entries = c.execute("SELECT COUNT(*) FROM cause_list_entries").fetchone()[0]
        cached_queries = c.execute("SELECT COUNT(*) FROM queries").fetchone()[0]
    return {
        "db_path": str(DB_PATH),
        "cases": cases,
        "case_details_cached": details,
        "cause_list_entries": cl_entries,
        "cached_queries": cached_queries,
    }


def _to_int(v):
    try:
        return int(v) if v not in (None, "") else None
    except Exception:
        return None
