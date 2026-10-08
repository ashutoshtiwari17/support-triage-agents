from datetime import datetime, timezone
from enum import StrEnum
import enum
from pydantic import BaseModel, Field, model_validator


def now():
    return datetime.now(timezone.utc)


# ================= Enums =================

class Department(StrEnum):
    HR = "hr"
    FINANCE = "finance"
    IT = "it"


class HumanQueue(StrEnum):
    """Tickets only ever go to human teams. Never to an agent."""
    HR_TEAM = "hr-team"
    FINANCE_TEAM = "finance-team"
    IT_SERVICE_DESK = "it-service-desk"


QUEUE_FOR = {
    Department.HR: HumanQueue.HR_TEAM,
    Department.FINANCE: HumanQueue.FINANCE_TEAM,
    Department.IT: HumanQueue.IT_SERVICE_DESK
}


class Priority(StrEnum):
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"
    P4 = "P4"


class EscalationReason(StrEnum):
    SENSITIVE_TOPIC = "sensitive_topic"   # rule 1: human only, agent must not attempt
    NEEDS_APPROVAL = "needs_approval"     # rule 2: agent collects details, human approves
    AGENT_FAILED   = "agent_failed"       # rule 3: agent tried, didn't work
    USER_REQUESTED = "user_requested"     # rule 4: user asked for a human

class OutcomeStatus(StrEnum):
    RESOLVED = "resolved"
    ESCALATED = "escalated"
    ABANDONED = "abandoned"


class Pattern(StrEnum):
    REACT = "react"
    REFLECT = "reflect"
    HIERARCHICAL = "hierarchical"


class Framework(StrEnum):
    GEMINI_SDK = "gemini_sdk"
    ADK = "adk"
    LANGGRAPH = "langgraph"
    CREWAI = "crewai"


class Role(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"


class StepType(StrEnum):
    THOUGHT = "thought"
    ACTION = "action"
    OBSERVATION = "observation"
    PLAN = "plan"
    DELEGATE = "delegate"
    RETURN = "return"
    DRAFT = "draft"
    CRITIQUE = "critique"
    REVISE = "revise"
    FINAL = "final"

class EmploymentType(StrEnum):
    EMPLOYEE = "employee"
    CONTRACTOR = "contractor"

# ================= Models =================



class Employee(BaseModel):
    id: str = Field(pattern=r"^E\d{3}$")          # e.g. E042
    name: str
    email: str
    team: str                                     # e.g. "Engineering"
    location: str
    employment_type: EmploymentType
    manager_id: str | None = None


class ChatMessage(BaseModel):
    session_id: str
    role: Role
    content: str = Field(min_length=1)
    run_id: str | None = None                     # which agent run produced this reply
    timestamp: datetime = Field(default_factory=now)

    @model_validator(mode="after")
    def check_rules(self):
        if self.role == Role.ASSISTANT and not self.run_id:
            raise ValueError("ASSISTANT messages must have a run_id")
        if self.role == Role.USER and self.run_id is not None:
            raise ValueError("USER messages must not have a run_id")
        return self


class Run(BaseModel):
    """One run = the agent's work to answer one user message."""
    run_id: str
    session_id: str
    pattern: Pattern
    framework: Framework
    started_at: datetime = Field(default_factory=now)


class TraceEvent(BaseModel):
    run_id: str
    step: int = Field(ge=1)
    type: StepType
    agent: str
    parent_agent: str | None = None               # set when a sub-agent is working
    content: str
    tool_name: str | None = None
    tool_args: dict | None = None
    tokens_in: int | None = Field(default=None, ge=0)
    tokens_out: int | None = Field(default=None, ge=0)
    latency_ms: int | None = Field(default=None, ge=0)
    timestamp: datetime = Field(default_factory=now)

    @model_validator(mode="after")
    def check_rules(self):
        # ACTION -> tool_name required
        if self.type == StepType.ACTION and not self.tool_name:
            raise ValueError("ACTION events must have a tool_name") 
        return self


class Ticket(BaseModel):
    id: str = Field(pattern=r"^TKT-\d{4}$")       # e.g. TKT-0001
    session_id: str                               # chat that raised it
    employee_id: str
    department: Department
    category: str                                 # e.g. "leave", "vpn", "reimbursement"
    priority: Priority
    summary: str = Field(min_length=10)
    escalation_reason: EscalationReason
    attempted_steps: list[str] = []
    assigned_queue: HumanQueue
    created_at: datetime = Field(default_factory=now)

    @model_validator(mode="after")
    def check_rules(self):
        # Rule A: queue must match department
        if self.assigned_queue != QUEUE_FOR[self.department]:
            raise ValueError(
                f"{self.department} tickets must go to {QUEUE_FOR[self.department]}"
            )
        #  Rule B: SENSITIVE_TOPIC -> attempted_steps must be empty
        if self.escalation_reason == EscalationReason.SENSITIVE_TOPIC and len(self.attempted_steps) > 0:
            raise ValueError(
                "If the tickets are marked as SENSITIVE_TOPIC, attempted_steps must be empty"
            )
        #  Rule C: SENSITIVE_TOPIC -> priority must be P1 or P2
        if self.escalation_reason == EscalationReason.SENSITIVE_TOPIC and self.priority not in [Priority.P1, Priority.P2]:
            raise ValueError(
                "If the tickets are marked as SENSITIVE_TOPIC, priority must be P1 or P2"
            )
        #  Rule D: AGENT_FAILED    -> attempted_steps must NOT be empty
        if self.escalation_reason == EscalationReason.AGENT_FAILED and not any(s.strip() for s in self.attempted_steps):
            raise ValueError("AGENT_FAILED tickets must list at least one attempted step")
        return self


class ChatOutcome(BaseModel):
    session_id: str
    employee_id: str
    status: OutcomeStatus
    user_confirmed: bool = False
    ticket_id: str | None = None
    turns: int = Field(ge=1)

    @model_validator(mode="after")
    def check_rules(self):
        if self.status == OutcomeStatus.ESCALATED and not self.ticket_id:
            raise ValueError("Escalated outcome requires a ticket_id")
        if self.status == OutcomeStatus.RESOLVED and not self.user_confirmed:
            raise ValueError("Resolved outcome requires user confirmation")
        if self.status == OutcomeStatus.RESOLVED and self.ticket_id:
            raise ValueError("Resolved outcome must not have a ticket_id")
        return self