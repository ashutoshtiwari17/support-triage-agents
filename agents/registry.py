"""Which (framework, pattern) combinations exist, and where their code lives.

Every module listed here exposes:
    run(question, employee_id, history=None, recorder=None) -> str
Add one line here when a new implementation is ready; the CLI and the web UI
both pick it up.
"""
import importlib

RUNNERS = {
    ("gemini_sdk", "react"): "agents.gemini_sdk.react",
    # ("gemini_sdk", "reflect"): "agents.gemini_sdk.reflect",
    # ("adk", "react"): "agents.adk_app.react",
}


def load_runner(framework: str, mode: str):
    """Import the implementation only when it is chosen."""
    return importlib.import_module(RUNNERS[(framework, mode)])
