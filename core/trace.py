"""Records what an agent does, one TraceEvent per step.

Every framework (Gemini SDK, ADK, LangGraph, CrewAI) reports its steps through
a Recorder, so the CLI, the saved run files and the web UI all read one format.
"""
import json
import time
import uuid
from pathlib import Path
from typing import Callable

from core.schemas import Framework, Pattern, Run, StepType, TraceEvent

RUNS_DIR = Path("runs")


def print_event(event: TraceEvent) -> None:
    """Default listener: one line per step in the terminal."""
    if event.type == StepType.FINAL:      # the caller prints the answer itself
        return
    print(f"[{event.step}] {event.type.upper():<11} {event.content}")


class Recorder:
    def __init__(
        self,
        pattern: Pattern,
        framework: Framework,
        session_id: str = "cli",
        run_id: str | None = None,
        on_event: Callable[[TraceEvent], None] | None = None,
    ):
        self.run = Run(
            run_id=run_id or f"R-{uuid.uuid4().hex[:8]}",
            session_id=session_id,
            pattern=pattern,
            framework=framework,
        )
        self.events: list[TraceEvent] = []
        self.llm_calls = 0
        self._on_event = on_event or print_event
        self._started = time.perf_counter()

    def emit(self, type: StepType, agent: str, content: str, **fields) -> TraceEvent:
        """Record one step and notify the listener (terminal or web stream)."""
        event = TraceEvent(
            run_id=self.run.run_id,
            step=len(self.events) + 1,
            type=type,
            agent=agent,
            content=content,
            **fields,
        )
        self.events.append(event)
        self._on_event(event)
        return event

    def metrics(self) -> dict:
        return {
            "steps": len(self.events),
            "llm_calls": self.llm_calls,
            "tool_calls": sum(e.type == StepType.ACTION for e in self.events),
            "tokens": sum((e.tokens_in or 0) + (e.tokens_out or 0) for e in self.events),
            "latency_ms": int((time.perf_counter() - self._started) * 1000),
        }

    def finish(self, question: str, answer: str, directory: Path = RUNS_DIR) -> Path:
        """Write the whole run to runs/<run_id>.json."""
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{self.run.run_id}.json"
        path.write_text(json.dumps({
            "run": self.run.model_dump(mode="json"),
            "question": question,
            "answer": answer,
            "metrics": self.metrics(),
            "events": [e.model_dump(mode="json") for e in self.events],
        }, indent=2))
        return path
