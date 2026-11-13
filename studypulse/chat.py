"""Chat layer: lets a language model on Amazon Bedrock use the StudyPulse tools.

The browser keeps the conversation and sends it with every request, so the
server stays stateless. `run_turn` is the tool-use loop:

    model -> asks for a tool -> we run it -> send result back -> model replies
"""
import asyncio
import json
import os

SYSTEM_PROMPT = (
    "You are StudyPulse, a voice-first study coach. Your replies are spoken "
    "aloud, so keep them to one to three short sentences of plain text: no "
    "markdown, no lists, no emoji.\n"
    "- When the student wants to remember something, call add_card with a clear "
    "question and a short answer.\n"
    "- To quiz: call quiz_me, ask ONLY the question, and wait. When they answer, "
    "judge it against answer_for_grading_only, say if they were right (give the "
    "correct answer if not), then call log_result with a 0-5 quality score.\n"
    "- Never reveal the stored answer before the student replies.\n"
    "- For progress call weekly_review; for their topics call list_topics."
)

MAX_STEPS = 6            # tool calls per turn, a guard against loops
MAX_MESSAGES = 40        # conversation length
MAX_USER_CHARS = 1000    # one user message
MAX_TOTAL_CHARS = 60000  # whole conversation as JSON
ALLOWED_BLOCKS = {"text", "toolUse", "toolResult"}


class ChatInputError(ValueError):
    """The request was malformed; safe to show the message to the caller."""


def validate_messages(messages) -> list:
    """Accept only well-formed Converse messages; the browser sends these back."""
    if not isinstance(messages, list) or not messages:
        raise ChatInputError("messages must be a non-empty list")
    if len(messages) > MAX_MESSAGES:
        raise ChatInputError("Conversation is too long. Start a new one.")
    if len(json.dumps(messages)) > MAX_TOTAL_CHARS:
        raise ChatInputError("Conversation is too large. Start a new one.")
    for m in messages:
        if not isinstance(m, dict) or m.get("role") not in ("user", "assistant"):
            raise ChatInputError("Each message needs a role of user or assistant")
        content = m.get("content")
        if not isinstance(content, list) or not content:
            raise ChatInputError("Each message needs a non-empty content list")
        for block in content:
            if not isinstance(block, dict) or not (set(block) & ALLOWED_BLOCKS):
                raise ChatInputError("Unsupported content block")
    if messages[0]["role"] != "user" or messages[-1]["role"] != "user":
        raise ChatInputError("Conversation must start and end with a user message")
    for block in messages[-1]["content"]:
        if "text" in block and len(block["text"]) > MAX_USER_CHARS:
            raise ChatInputError(f"Keep messages under {MAX_USER_CHARS} characters")
    return messages


def _tool_config(tools) -> dict:
    return {"tools": [
        {"toolSpec": {
            "name": t.name,
            "description": t.description or t.name,
            "inputSchema": {"json": t.input_schema},
        }} for t in tools
    ]}


def _result_block(tool_use_id: str, result) -> dict:
    """Turn an MCP CallToolResult into a Bedrock toolResult block."""
    if result.is_error:
        text = result.content[0].text if result.content else "Tool failed"
        return {"toolResult": {"toolUseId": tool_use_id, "status": "error",
                               "content": [{"text": text}]}}
    if isinstance(result.structured_content, dict):
        payload = {"json": result.structured_content}
    else:
        text = result.content[0].text if result.content else ""
        try:
            parsed = json.loads(text)
            payload = {"json": parsed} if isinstance(parsed, dict) else {"json": {"result": parsed}}
        except json.JSONDecodeError:
            payload = {"text": text}
    return {"toolResult": {"toolUseId": tool_use_id, "content": [payload]}}


async def run_turn(client, model_id: str, messages: list, list_tools, call_tool):
    """Run one user turn. Returns (reply_text, updated_messages)."""
    tool_config = _tool_config(await list_tools())
    for _ in range(MAX_STEPS):
        resp = await asyncio.to_thread(
            client.converse,
            modelId=model_id,
            messages=messages,
            system=[{"text": SYSTEM_PROMPT}],
            toolConfig=tool_config,
            inferenceConfig={"maxTokens": 500},
        )
        message = resp["output"]["message"]
        messages.append(message)
        if resp.get("stopReason") != "tool_use":
            text = "".join(b.get("text", "") for b in message["content"]).strip()
            return text, messages

        results = []
        for block in message["content"]:
            use = block.get("toolUse")
            if not use:
                continue
            try:
                result = await call_tool(use["name"], use.get("input") or {})
                results.append(_result_block(use["toolUseId"], result))
            except Exception as exc:  # tool crashed: tell the model, don't 500
                results.append({"toolResult": {
                    "toolUseId": use["toolUseId"], "status": "error",
                    "content": [{"text": f"Tool error: {exc}"}]}})
        messages.append({"role": "user", "content": results})
    return "Sorry, I got stuck on that one. Please try again.", messages


class StubBedrock:
    """Offline stand-in for Bedrock, for trying the UI and tool loop without AWS.
    Enabled with STUDYPULSE_STUB_LLM=1. Not a real model: it only understands
    'quiz me', 'progress', and 'add <topic>: <question>? <answer>'."""

    def _reply(self, text):
        return {"output": {"message": {"role": "assistant", "content": [{"text": text}]}},
                "stopReason": "end_turn"}

    def _use(self, name, args):
        return {"output": {"message": {"role": "assistant", "content": [
                    {"toolUse": {"toolUseId": f"stub-{name}", "name": name, "input": args}}]}},
                "stopReason": "tool_use"}

    def converse(self, **kwargs):
        blocks = kwargs["messages"][-1]["content"]
        for b in blocks:
            if "toolResult" in b:
                c = b["toolResult"]["content"][0]
                return self._reply("(stub) " + json.dumps(c.get("json", c.get("text"))))
        text = " ".join(b.get("text", "") for b in blocks).strip()
        low = text.lower()
        if "quiz" in low:
            return self._use("quiz_me", {})
        if "progress" in low or "week" in low:
            return self._use("weekly_review", {})
        if low.startswith("add ") and ":" in text:
            head, rest = text.split(":", 1)
            topic = head[4:].strip()
            for filler in ("a card in ", "a card about ", "a card on ", "card in "):
                if topic.lower().startswith(filler):
                    topic = topic[len(filler):]
            if "=" in rest:
                q, a = rest.split("=", 1)
            elif "?" in rest:
                q, a = rest.split("?", 1)
                q += "?"
            else:
                q, a = rest, ""
            if q.strip() and a.strip():
                return self._use("add_card", {"topic": topic, "question": q.strip(), "answer": a.strip()})
        return self._reply("(stub) Try: quiz me, progress, or add dbms: What is ACID? Atomicity, Consistency, Isolation, Durability")


def make_client():
    if os.environ.get("STUDYPULSE_STUB_LLM") == "1":
        return StubBedrock()
    import boto3  # imported lazily so the MCP server runs without it
    return boto3.client("bedrock-runtime", region_name=os.environ.get("AWS_REGION", "us-east-1"))
