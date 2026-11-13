"""SQLite storage for StudyPulse. Standard library only."""
import os
import sqlite3
from contextlib import contextmanager
from datetime import date, timedelta

from scheduler import CardState, review

DB_PATH = os.environ.get("STUDYPULSE_DB", "studypulse.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS cards (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    topic         TEXT NOT NULL,
    question      TEXT NOT NULL,
    answer        TEXT NOT NULL,
    repetitions   INTEGER NOT NULL DEFAULT 0,
    interval_days INTEGER NOT NULL DEFAULT 0,
    ease          REAL NOT NULL DEFAULT 2.5,
    due           TEXT NOT NULL,
    created       TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reviews (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    card_id     INTEGER NOT NULL REFERENCES cards(id),
    reviewed_on TEXT NOT NULL,
    quality     INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_cards_due ON cards(due);
"""


@contextmanager
def connect(path: str | None = None):
    conn = sqlite3.connect(path or DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def add_card(conn, topic: str, question: str, answer: str, today: date) -> int:
    cur = conn.execute(
        "INSERT INTO cards (topic, question, answer, due, created) VALUES (?,?,?,?,?)",
        (topic.strip().lower(), question.strip(), answer.strip(),
         today.isoformat(), today.isoformat()),
    )
    return cur.lastrowid


def next_due_card(conn, today: date, topic: str | None = None):
    sql = "SELECT * FROM cards WHERE due <= ?"
    params: list = [today.isoformat()]
    if topic:
        sql += " AND topic = ?"
        params.append(topic.strip().lower())
    sql += " ORDER BY due ASC, ease ASC, id ASC LIMIT 1"  # most overdue, hardest first
    return conn.execute(sql, params).fetchone()


def count_due(conn, today: date, topic: str | None = None) -> int:
    sql = "SELECT COUNT(*) FROM cards WHERE due <= ?"
    params: list = [today.isoformat()]
    if topic:
        sql += " AND topic = ?"
        params.append(topic.strip().lower())
    return conn.execute(sql, params).fetchone()[0]


def log_result(conn, card_id: int, quality: int, today: date):
    card = conn.execute("SELECT * FROM cards WHERE id = ?", (card_id,)).fetchone()
    if card is None:
        raise LookupError(f"No card with id {card_id}")
    state = CardState(card["repetitions"], card["interval_days"], card["ease"])
    new_state, due = review(state, quality, today)
    conn.execute(
        "UPDATE cards SET repetitions=?, interval_days=?, ease=?, due=? WHERE id=?",
        (new_state.repetitions, new_state.interval_days, new_state.ease,
         due.isoformat(), card_id),
    )
    conn.execute(
        "INSERT INTO reviews (card_id, reviewed_on, quality) VALUES (?,?,?)",
        (card_id, today.isoformat(), quality),
    )
    return new_state, due


def list_topics(conn, today: date):
    rows = conn.execute(
        """SELECT topic, COUNT(*) AS cards,
                  SUM(CASE WHEN due <= ? THEN 1 ELSE 0 END) AS due
           FROM cards GROUP BY topic ORDER BY topic""",
        (today.isoformat(),),
    ).fetchall()
    return [dict(r) for r in rows]


def weekly_review(conn, today: date) -> dict:
    start = (today - timedelta(days=6)).isoformat()
    end = today.isoformat()
    rows = conn.execute(
        """SELECT r.reviewed_on, r.quality, c.topic
           FROM reviews r JOIN cards c ON c.id = r.card_id
           WHERE r.reviewed_on BETWEEN ? AND ?""",
        (start, end),
    ).fetchall()

    total = len(rows)
    correct = sum(1 for r in rows if r["quality"] >= 3)
    days_active = len({r["reviewed_on"] for r in rows})

    by_topic: dict[str, list[int]] = {}
    for r in rows:
        by_topic.setdefault(r["topic"], []).append(r["quality"])
    topic_stats = [
        {"topic": t, "reviews": len(q),
         "accuracy_pct": round(100 * sum(1 for x in q if x >= 3) / len(q))}
        for t, q in by_topic.items()
    ]
    # Weakest first; ignore topics with too few reviews to judge.
    weakest = sorted((s for s in topic_stats if s["reviews"] >= 3),
                     key=lambda s: s["accuracy_pct"])[:3]

    return {
        "period": f"{start} to {end}",
        "reviews": total,
        "accuracy_pct": round(100 * correct / total) if total else None,
        "days_active": days_active,
        "weakest_topics": weakest,
        "due_now": count_due(conn, today),
    }
