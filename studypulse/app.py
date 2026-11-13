"""StudyPulse web app: one process serving the MCP endpoint and the chat UI.

    /mcp        MCP server (Streamable HTTP), what Alexa+ connects to
    /           chat page (simulated Alexa+ experience)
    /api/chat   chat endpoint: model on Amazon Bedrock + the same tools
    /health     liveness check
"""
import logging
import os
from pathlib import Path

import uvicorn
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse

import chat
from server import mcp

log = logging.getLogger("studypulse")
STATIC = Path(__file__).parent / "static"
_client = None


def _get_client():
    global _client
    if _client is None:
        _client = chat.make_client()
    return _client


async def index(request: Request):
    return HTMLResponse((STATIC / "index.html").read_text(encoding="utf-8"))


async def health(request: Request):
    return JSONResponse({"ok": True})


async def chat_endpoint(request: Request):
    try:
        body = await request.json()
        messages = chat.validate_messages(body.get("messages"))
    except chat.ChatInputError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    except Exception:
        return JSONResponse({"error": "Send JSON like {\"messages\": [...]}"}, status_code=400)

    stub = os.environ.get("STUDYPULSE_STUB_LLM") == "1"
    model_id = os.environ.get("BEDROCK_MODEL_ID", "")
    if not stub and not model_id:
        return JSONResponse({"error": "Server is missing BEDROCK_MODEL_ID."}, status_code=500)
    try:
        reply, messages = await chat.run_turn(
            _get_client(), model_id, messages, mcp.list_tools, mcp.call_tool)
    except Exception as exc:
        log.exception("chat turn failed")
        return JSONResponse(
            {"error": f"The model call failed ({type(exc).__name__}). "
                      "Check AWS credentials, region and Bedrock model access."},
            status_code=502)
    return JSONResponse({"reply": reply, "messages": messages})


def build_app(host: str = "127.0.0.1"):
    app = mcp.streamable_http_app(host=host)
    app.add_route("/", index, methods=["GET"])
    app.add_route("/health", health, methods=["GET"])
    app.add_route("/api/chat", chat_endpoint, methods=["POST"])
    return app


if __name__ == "__main__":
    host = os.environ.get("HOST", "127.0.0.1")
    uvicorn.run(build_app(host), host=host, port=int(os.environ.get("PORT", "8000")))
