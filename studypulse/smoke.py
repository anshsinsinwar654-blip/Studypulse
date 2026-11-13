"""End-to-end check: talk to the running server exactly like an MCP client would.
Start the server first (python server.py), then: python smoke.py"""
import asyncio
import json

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

URL = "http://127.0.0.1:8000/mcp"


async def main():
    async with streamable_http_client(URL) as (r, w, *_):
        async with ClientSession(r, w) as s:
            await s.initialize()
            print("TOOLS:", [t.name for t in (await s.list_tools()).tools])

            async def call(name, args):
                res = await s.call_tool(name, args)
                if res.is_error:
                    out = "ERROR: " + res.content[0].text
                elif res.structured_content:
                    out = res.structured_content
                else:
                    text = res.content[0].text
                    try:
                        out = json.loads(text)
                    except json.JSONDecodeError:
                        out = text
                print(f"{name} -> {out}")
                return out

            await call("add_card", {"topic": "DBMS", "question": "What does ACID stand for?",
                                    "answer": "Atomicity, Consistency, Isolation, Durability"})
            q = await call("quiz_me", {})
            await call("log_result", {"card_id": q["card_id"], "quality": 5})
            await call("quiz_me", {})          # nothing due now
            await call("list_topics", {})
            await call("weekly_review", {})
            await call("log_result", {"card_id": q["card_id"], "quality": 9})  # bad input


asyncio.run(main())
