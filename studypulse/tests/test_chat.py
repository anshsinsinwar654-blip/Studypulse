import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import asyncio

import pytest

import chat
import db
from server import mcp


def user(text):
    return {"role": "user", "content": [{"text": text}]}


@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "chat.db"))


def turn(messages):
    return asyncio.run(chat.run_turn(chat.StubBedrock(), "stub", messages, mcp.list_tools, mcp.call_tool))


def test_add_then_quiz_runs_real_tools():
    reply, msgs = turn([user("add dbms: What is ACID? = Atomicity")])
    assert "added" in reply and "card_id" in reply
    # one user msg, assistant tool call, user tool result, assistant reply
    assert [m["role"] for m in msgs] == ["user", "assistant", "user", "assistant"]
    reply, _ = turn([user("quiz me")])
    assert "What is ACID?" in reply


def test_tool_error_is_reported_not_raised():
    # quality 9 is invalid; the loop must pass the error back instead of crashing
    class BadModel(chat.StubBedrock):
        def converse(self, **kw):
            if any("toolResult" in b for b in kw["messages"][-1]["content"]):
                return self._reply("handled")
            return self._use("log_result", {"card_id": 1, "quality": 9})
    reply, msgs = asyncio.run(chat.run_turn(BadModel(), "x", [user("go")], mcp.list_tools, mcp.call_tool))
    assert reply == "handled"
    result = msgs[2]["content"][0]["toolResult"]
    assert result["status"] == "error" and "0 to 5" in result["content"][0]["text"]


def test_loop_stops_after_max_steps():
    class Looper(chat.StubBedrock):
        def converse(self, **kw):
            return self._use("list_topics", {})
    reply, _ = asyncio.run(chat.run_turn(Looper(), "x", [user("go")], mcp.list_tools, mcp.call_tool))
    assert "stuck" in reply


@pytest.mark.parametrize("bad", [
    None, [], "hi", [{"role": "system", "content": [{"text": "x"}]}],
    [{"role": "user", "content": []}],
    [{"role": "user", "content": [{"evil": 1}]}],
    [{"role": "assistant", "content": [{"text": "x"}]}],
    [user("x" * (chat.MAX_USER_CHARS + 1))],
    [user("hi")] * (chat.MAX_MESSAGES + 1),
])
def test_validation_rejects_bad_input(bad):
    with pytest.raises(chat.ChatInputError):
        chat.validate_messages(bad)


def test_validation_accepts_normal_conversation():
    msgs = [user("hi"), {"role": "assistant", "content": [{"text": "hello"}]}, user("quiz me")]
    assert chat.validate_messages(msgs) is msgs


def test_stub_understands_the_example_button_wording():
    text = "Add a card in dbms: What does ACID stand for? Atomicity, Consistency, Isolation, Durability"
    reply, _ = turn([user(text)])
    assert "added" in reply
    reply, _ = turn([user("quiz me")])
    assert "What does ACID stand for?" in reply and "Atomicity" in reply
