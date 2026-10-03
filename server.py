"""Web server for the helpdesk: serves the page and streams agent runs to it.

Run locally:  uvicorn server:app --reload
Then open:    http://127.0.0.1:8000

There is no login yet, so keep it on 127.0.0.1. Chat history lives in memory
and is lost on restart; it moves to Firestore when this goes to Cloud Run.

Whose Gemini key pays for a run:
  - A visitor can send their own key in the X-Gemini-Key header. It is used for
    that one run and is never stored, logged or written to the run file.
  - Without that header the server's own GEMINI_API_KEY is used.
  - Set REQUIRE_USER_KEY=1 to refuse runs without a visitor key (for a public demo).
"""
import json
import logging
import os
import queue
import re
import threading
import uuid
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from agents.registry import RUNNERS, load_runner
from core.data import EMPLOYEES
from core.schemas import Framework, Pattern
from core.trace import Recorder

load_dotenv()
log = logging.getLogger("helpdesk")
WEB_DIR = Path(__file__).parent / "web"
MAX_TURNS_KEPT = 20                      # earlier turns sent back to the model
REQUIRE_USER_KEY = os.environ.get("REQUIRE_USER_KEY", "").lower() in ("1", "true", "yes")
KEY_SHAPE = re.compile(r"[A-Za-z0-9_\-]{20,200}")

app = FastAPI(title="Kestrel Works helpdesk")
SESSIONS: dict[str, list[dict]] = {}     # session_id -> [{"role", "text"}, ...]


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    employee_id: str = "E001"
    session_id: str | None = None
    framework: Framework = Framework.GEMINI_SDK
    mode: Pattern = Pattern.REACT


@app.get("/")
def page():
    return FileResponse(WEB_DIR / "index.html")


@app.get("/api/meta")
def meta():
    """What the page needs to draw its controls."""
    return {
        "employees": [{"id": eid, "name": e["name"], "team": e["team"]} for eid, e in EMPLOYEES.items()],
        "runners": [{"framework": f, "mode": m} for f, m in RUNNERS],
        "model": os.environ.get("GEMINI_MODEL", ""),
        "requires_key": REQUIRE_USER_KEY,
        "server_has_key": bool(os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")),
    }


def explain(error: Exception, user_key: str | None) -> str:
    """Turn a failure into a message a visitor can act on. Never echoes the key."""
    code = getattr(error, "code", None)
    text = str(error)
    if user_key:
        text = text.replace(user_key, "***")
    whose = "your" if user_key else "the server's"
    if code == 429:
        return (f"The Gemini quota for {whose} API key is used up for now. "
                "Try again later, or use a key from a project with billing turned on.")
    if code in (401, 403) or "API key not valid" in text or "API_KEY_INVALID" in text:
        return f"Gemini rejected {whose} API key. Check the key and try again."
    if code == 503:
        return "Gemini is overloaded right now. Try again in a minute."
    if isinstance(error, ValueError) and "api key" in text.lower():
        return "No Gemini API key is set. Add your own key with the API key button."
    return f"{type(error).__name__}: {text[:300]}"


@app.post("/api/chat")
def chat(req: ChatRequest, x_gemini_key: str | None = Header(default=None)):
    """Run the agent on one message and stream its steps as they happen.

    The response is newline-delimited JSON, one object per line:
      {"kind": "run",   "run": {...}, "session_id": "..."}
      {"kind": "event", "event": {...TraceEvent...}}        (one per step)
      {"kind": "done",  "answer": "...", "metrics": {...}}  or
      {"kind": "error", "message": "..."}
    """
    if req.employee_id not in EMPLOYEES:
        raise HTTPException(404, f"No employee {req.employee_id}")
    if (req.framework, req.mode) not in RUNNERS:
        raise HTTPException(400, f"{req.framework} does not implement '{req.mode}' yet")
    user_key = (x_gemini_key or "").strip() or None
    if user_key and not KEY_SHAPE.fullmatch(user_key):
        raise HTTPException(400, "That does not look like a Gemini API key.")
    if REQUIRE_USER_KEY and not user_key:
        raise HTTPException(401, "Add your own Gemini API key to use this demo.")

    session_id = req.session_id or f"S-{uuid.uuid4().hex[:8]}"
    history = SESSIONS.setdefault(session_id, [])
    outbox: queue.Queue = queue.Queue()
    recorder = Recorder(
        req.mode, req.framework, session_id=session_id,
        on_event=lambda e: outbox.put({"kind": "event", "event": e.model_dump(mode="json")}),
    )

    def work():
        try:
            runner = load_runner(req.framework, req.mode)
            answer = runner.run(req.message, employee_id=req.employee_id,
                                history=list(history), recorder=recorder, api_key=user_key)
            history.extend([{"role": "user", "text": req.message},
                            {"role": "assistant", "text": answer}])
            del history[:-MAX_TURNS_KEPT]
            outbox.put({"kind": "done", "answer": answer, "metrics": recorder.metrics()})
        except Exception as e:
            message = explain(e, user_key)
            log.error("run %s failed: %s", recorder.run.run_id, message)
            outbox.put({"kind": "error", "message": message})
        finally:
            outbox.put(None)

    def stream():
        yield json.dumps({"kind": "run", "session_id": session_id,
                          "run": recorder.run.model_dump(mode="json")}) + "\n"
        while (item := outbox.get()) is not None:
            yield json.dumps(item) + "\n"

    threading.Thread(target=work, daemon=True).start()
    return StreamingResponse(stream(), media_type="application/x-ndjson")
