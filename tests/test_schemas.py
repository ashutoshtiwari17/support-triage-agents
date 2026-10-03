import pytest
from pydantic import ValidationError
from core.schemas import (
    Ticket, ChatOutcome, ChatMessage, TraceEvent,
    Department, HumanQueue, Priority, EscalationReason,
    OutcomeStatus, Role, StepType,
)


def valid_ticket(**overrides):
    data = dict(
        id="TKT-0001", session_id="S1", employee_id="E001",
        department=Department.IT, category="vpn", priority=Priority.P3,
        summary="VPN disconnects every 10 minutes",
        escalation_reason=EscalationReason.AGENT_FAILED,
        attempted_steps=["Suggested reinstalling the VPN client"],
        assigned_queue=HumanQueue.IT_SERVICE_DESK,
    )
    data.update(overrides)
    return Ticket(**data)


def valid_message(**overrides):
    data = dict(session_id="S1", role=Role.USER, content="My VPN is down")
    data.update(overrides)
    return ChatMessage(**data)


def valid_outcome(**overrides):
    data = dict(session_id="S1", employee_id="E001",
                status=OutcomeStatus.RESOLVED, user_confirmed=True, turns=2)
    data.update(overrides)
    return ChatOutcome(**data)


def valid_event(**overrides):
    data = dict(run_id="R1", step=1, type=StepType.THOUGHT,
                agent="it_agent", content="Check VPN status")
    data.update(overrides)
    return TraceEvent(**data)

def test_valid_ticket_passes():
    assert valid_ticket().id == "TKT-0001"


def test_wrong_queue_rejected():
    with pytest.raises(ValidationError):
        valid_ticket(assigned_queue=HumanQueue.HR_TEAM)