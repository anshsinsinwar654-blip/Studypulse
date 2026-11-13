import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from datetime import date, timedelta

import pytest

import db
from scheduler import CardState, review

D0 = date(2026, 10, 14)


def test_intervals_grow_on_perfect_answers():
    s = CardState()
    s, due = review(s, 5, D0)
    assert s.interval_days == 1 and due == D0 + timedelta(days=1)
    s, _ = review(s, 5, D0)
    assert s.interval_days == 6
    s, _ = review(s, 5, D0)
    assert s.interval_days == round(6 * 2.7)  # ease rose 2.5 -> 2.6 -> 2.7


def test_failure_resets_progress_but_keeps_history_of_ease():
    s = CardState(repetitions=4, interval_days=30, ease=2.5)
    s, due = review(s, 1, D0)
    assert s.repetitions == 0 and s.interval_days == 1
    assert due == D0 + timedelta(days=1)
    assert s.ease < 2.5


def test_ease_never_below_floor():
    s = CardState()
    for _ in range(30):
        s, _ = review(s, 0, D0)
    assert s.ease == 1.3


def test_invalid_quality_rejected():
    with pytest.raises(ValueError):
        review(CardState(), 6, D0)


@pytest.fixture
def conn(tmp_path):
    with db.connect(str(tmp_path / "t.db")) as c:
        yield c


def test_card_due_today_then_scheduled_forward(conn):
    cid = db.add_card(conn, "DBMS", "ACID?", "A C I D", D0)
    assert db.next_due_card(conn, D0)["id"] == cid
    db.log_result(conn, cid, 5, D0)
    assert db.next_due_card(conn, D0) is None
    assert db.next_due_card(conn, D0 + timedelta(days=1))["id"] == cid


def test_topic_filter_is_case_insensitive(conn):
    db.add_card(conn, "DBMS", "q1", "a1", D0)
    db.add_card(conn, "os", "q2", "a2", D0)
    assert db.next_due_card(conn, D0, "Os")["question"] == "q2"
    assert db.count_due(conn, D0, "dbms") == 1


def test_unknown_card_raises(conn):
    with pytest.raises(LookupError):
        db.log_result(conn, 999, 3, D0)


def test_weekly_review_numbers(conn):
    cid = db.add_card(conn, "os", "q", "a", D0)
    for q in (5, 4, 1):
        db.log_result(conn, cid, q, D0)
    r = db.weekly_review(conn, D0)
    assert r["reviews"] == 3
    assert r["accuracy_pct"] == 67
    assert r["days_active"] == 1
    assert r["weakest_topics"][0]["topic"] == "os"
