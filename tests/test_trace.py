import json

import pytest
from pydantic import ValidationError

from core.schemas import Framework, Pattern, StepType
from core.trace import Recorder


def make_recorder(seen=None):
    seen = [] if seen is None else seen
    return Recorder(Pattern.REACT, Framework.GEMINI_SDK, on_event=seen.append), seen


def test_steps_are_numbered_in_order_and_sent_to_listener():
    rec, seen = make_recorder()
    rec.emit(StepType.THOUGHT, "it_agent", "Check the account", tokens_in=100, tokens_out=20)
    rec.emit(StepType.ACTION, "it_agent", "get_it_account(...)", tool_name="get_it_account", tool_args={"employee_id": "E001"})
    assert [e.step for e in rec.events] == [1, 2]
    assert seen == rec.events
    assert all(e.run_id == rec.run.run_id for e in rec.events)


def test_metrics_count_tools_and_tokens():
    rec, _ = make_recorder()
    rec.llm_calls = 2
    rec.emit(StepType.THOUGHT, "it_agent", "t", tokens_in=100, tokens_out=20)
    rec.emit(StepType.ACTION, "it_agent", "a", tool_name="search_policies")
    rec.emit(StepType.OBSERVATION, "tool", "[]", tool_name="search_policies")
    rec.emit(StepType.FINAL, "it_agent", "done", tokens_in=200, tokens_out=30)
    m = rec.metrics()
    assert (m["steps"], m["llm_calls"], m["tool_calls"], m["tokens"]) == (4, 2, 1, 350)


def test_action_without_tool_name_is_rejected():
    rec, _ = make_recorder()
    with pytest.raises(ValidationError, match="tool_name"):
        rec.emit(StepType.ACTION, "it_agent", "no tool given")
    assert rec.events == []


def test_finish_writes_the_run_file(tmp_path):
    rec, _ = make_recorder()
    rec.emit(StepType.FINAL, "it_agent", "Update your VPN client.")
    path = rec.finish("My VPN drops", "Update your VPN client.", directory=tmp_path)
    saved = json.loads(path.read_text())
    assert saved["run"]["run_id"] == rec.run.run_id
    assert saved["question"] == "My VPN drops"
    assert len(saved["events"]) == 1
