"""StudyPulse MCP server: a voice-first spaced-repetition study coach.

Run:  python server.py        -> http://127.0.0.1:8000/mcp  (Streamable HTTP)
"""
import os
from datetime import date

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

import db

mcp = MCPServer(
    "StudyPulse",
    instructions=(
        "StudyPulse is a spaced-repetition study coach. To quiz the student: "
        "call quiz_me, ask ONLY the question out loud, wait for their answer, "
        "judge it against the stored answer, then call log_result with a 0-5 "
        "quality score. Never read the stored answer before the student replies."
    ),
)


def _clean(value: str, name: str, max_len: int = 500) -> str:
    value = (value or "").strip()
    if not value:
        raise ToolError(f"{name} cannot be empty")
    if len(value) > max_len:
        raise ToolError(f"{name} is too long (max {max_len} characters)")
    return value


@mcp.tool()
def add_card(topic: str, question: str, answer: str) -> dict:
    """Add a study flashcard. Use when the student wants to remember something,
    e.g. topic='dbms', question='What does ACID stand for?',
    answer='Atomicity, Consistency, Isolation, Durability'."""
    topic = _clean(topic, "topic", 60)
    question = _clean(question, "question")
    answer = _clean(answer, "answer")
    with db.connect() as conn:
        card_id = db.add_card(conn, topic, question, answer, date.today())
    return {"card_id": card_id, "topic": topic.lower(), "status": "added, due today"}


@mcp.tool()
def quiz_me(topic: str | None = None) -> dict:
    """Get the next flashcard that is due for review, optionally for one topic.
    Ask the student ONLY the question. Keep the answer hidden until they reply,
    then grade them and call log_result."""
    today = date.today()
    with db.connect() as conn:
        card = db.next_due_card(conn, today, topic)
        remaining = db.count_due(conn, today, topic)
    if card is None:
        return {"due": 0, "message": "Nothing due right now. Nice work."}
    return {
        "card_id": card["id"],
        "topic": card["topic"],
        "question": card["question"],
        "answer_for_grading_only": card["answer"],
        "cards_due_including_this": remaining,
    }


@mcp.tool()
def log_result(card_id: int, quality: int) -> dict:
    """Record how well the student answered and schedule the next review.
    quality: 5 perfect, 4 correct but hesitated, 3 correct with difficulty,
    2 wrong but familiar, 1 wrong, 0 no idea."""
    if not 0 <= quality <= 5:
        raise ToolError("quality must be an integer from 0 to 5")
    with db.connect() as conn:
        try:
            state, due = db.log_result(conn, card_id, quality, date.today())
        except LookupError as exc:
            raise ToolError(str(exc)) from exc
    return {
        "card_id": card_id,
        "next_review": due.isoformat(),
        "interval_days": state.interval_days,
        "streak": state.repetitions,
    }


@mcp.tool()
def list_topics() -> list[dict]:
    """List the student's topics with total cards and how many are due today."""
    with db.connect() as conn:
        return db.list_topics(conn, date.today())


@mcp.tool()
def weekly_review() -> dict:
    """Summarise the last 7 days: reviews done, accuracy, active days,
    weakest topics and how many cards are due now."""
    with db.connect() as conn:
        return db.weekly_review(conn, date.today())


if __name__ == "__main__":
    mcp.run(
        transport="streamable-http",
        host=os.environ.get("HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", "8000")),
    )
