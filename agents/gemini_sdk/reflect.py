"""ReAct + Reflection: draft an answer, have a critic check it against the evidence, revise.

    DRAFT     the ReAct loop answers as usual (tools, policy search)
    CRITIQUE  a separate model call checks the draft against the observations only
    REVISE    if the critic found problems, one call rewrites the answer to fix them
    ...       critique again, at most MAX_ROUNDS times, then stop

The critic sees exactly what the drafting agent saw: the question and the tool results.
It does not search again and is told not to use outside knowledge, so it can only judge
whether the draft matches the evidence. Every extra round costs two model calls, which
is why the rounds are capped.
"""
import time
from typing import Literal

from google import genai
from google.genai import types
from pydantic import BaseModel, Field

from agents.gemini_sdk.react import MODEL, _loop, make_client
from core.data import EMPLOYEES
from core.schemas import Framework, Pattern, StepType
from core.trace import Recorder

MAX_ROUNDS = 2          # critique rounds; each one that fails adds a revision

CRITIC_PROMPT = """You check a helpdesk answer before it is sent to a person who works at Kestrel Works.
That person is either an employee or a contractor; PERSON below says which. Rules differ between the two.
You get the person's question, the evidence (tool results the agent retrieved) and the draft answer.
Judge the draft ONLY against the evidence. Do not use outside knowledge and do not ask for new searches.

Find problems of these kinds:
- unsupported: a claim, number or rule that is not in the evidence
- assumption: something assumed about the person that the evidence does not say (e.g. full-time, a grade, a city)
- missing: information in the evidence that directly answers the question but is left out
- citation: a claim without a citation, or cited to the wrong policy ID or section
- wrong_audience: the answer gives rules meant for a different employment type than the one in PERSON
  (contractor rules are correct for a contractor; employee rules are correct for an employee)

Report a problem only if fixing it would change what the person should do or believe.
Style and wording are not problems. If there are no problems, the verdict is "pass"."""

REVISER_PROMPT = """You revise a helpdesk answer for a person who works at Kestrel Works.
PERSON says whether they are an employee or a contractor; answer for that employment type only.
Fix every listed problem using only the evidence. Keep everything that was correct.
Cite the policy ID and section for each rule, e.g. (HR-001, section 2).
If the evidence does not cover something, say so instead of guessing.
Return only the revised answer, written to the person."""


class Problem(BaseModel):
    kind: Literal["unsupported", "assumption", "missing", "citation", "wrong_audience"]
    detail: str = Field(description="What is wrong and how to fix it, in one sentence.")


class Critique(BaseModel):
    verdict: Literal["pass", "revise"]
    problems: list[Problem] = Field(default_factory=list)


def run(
    question: str,
    employee_id: str = "E001",
    max_steps: int = 6,
    history: list[dict] | None = None,
    recorder: Recorder | None = None,
    api_key: str | None = None,
) -> str:
    rec = recorder or Recorder(Pattern.REFLECT, Framework.GEMINI_SDK)
    client = make_client(api_key)
    # Who the answer is for, from the server's record (never from the model). Without this
    # the critic cannot judge wrong_audience and assumes everyone is an employee.
    profile = EMPLOYEES[employee_id]
    person = f"{profile['name']}, employment type: {profile['employment_type']}"

    # 1. DRAFT: the normal ReAct loop, with its answer marked as a draft.
    answer = _loop(client, question, employee_id, max_steps, history or [], rec,
                   final_type=StepType.DRAFT)
    evidence = [e.content for e in rec.events if e.type == StepType.OBSERVATION]
    if not evidence:
        # Nothing was looked up (greeting, out-of-scope question): nothing to check against.
        rec.emit(StepType.FINAL, "helpdesk_agent", answer)
        rec.finish(question, answer)
        return answer

    # 2-3. CRITIQUE, and REVISE while the critic finds problems.
    for _ in range(MAX_ROUNDS):
        critique = _critique(client, rec, person, question, evidence, answer)
        if critique.verdict == "pass" or not critique.problems:
            break
        answer = _revise(client, rec, person, question, evidence, answer, critique)

    rec.emit(StepType.FINAL, "helpdesk_agent", answer)
    rec.finish(question, answer)
    return answer


def _critique(client: genai.Client, rec: Recorder, person: str, question: str,
              evidence: list[str], draft: str) -> Critique:
    prompt = _context(person, question, evidence) + f"\n\nDRAFT ANSWER:\n{draft}"
    config = types.GenerateContentConfig(
        system_instruction=CRITIC_PROMPT,
        response_mime_type="application/json",
        response_schema=Critique,          # the model must return this exact shape
        temperature=0,
    )
    response, cost = _call(client, rec, prompt, config)
    critique = response.parsed if isinstance(response.parsed, Critique) else \
        Critique.model_validate_json(response.text or '{"verdict": "pass"}')

    if critique.verdict == "pass" or not critique.problems:
        shown = "PASS: the draft matches the evidence."
    else:
        shown = "REVISE:\n" + "\n".join(f"- [{p.kind}] {p.detail}" for p in critique.problems)
    rec.emit(StepType.CRITIQUE, "critic", shown, **cost)
    return critique


def _revise(client: genai.Client, rec: Recorder, person: str, question: str,
            evidence: list[str], draft: str, critique: Critique) -> str:
    problems = "\n".join(f"- [{p.kind}] {p.detail}" for p in critique.problems)
    prompt = (_context(person, question, evidence)
              + f"\n\nCURRENT ANSWER:\n{draft}\n\nPROBLEMS TO FIX:\n{problems}")
    config = types.GenerateContentConfig(system_instruction=REVISER_PROMPT)
    response, cost = _call(client, rec, prompt, config)
    revised = (response.text or "").strip() or draft
    rec.emit(StepType.REVISE, "helpdesk_agent", revised, **cost)
    return revised


def _context(person: str, question: str, evidence: list[str]) -> str:
    blocks = "\n\n".join(f"[{i}] {e}" for i, e in enumerate(evidence, 1))
    return f"PERSON:\n{person}\n\nQUESTION:\n{question}\n\nEVIDENCE (tool results):\n{blocks}"


def _call(client: genai.Client, rec: Recorder, prompt: str,
          config: types.GenerateContentConfig):
    """One model call, counted and timed like the ReAct loop's calls."""
    # No tools here; switching AFC off explicitly also silences the SDK's AFC warning.
    config.automatic_function_calling = types.AutomaticFunctionCallingConfig(disable=True)
    started = time.perf_counter()
    response = client.models.generate_content(model=MODEL, contents=prompt, config=config)
    rec.llm_calls += 1
    usage = response.usage_metadata
    cost = {
        "tokens_in": usage.prompt_token_count if usage else None,
        "tokens_out": usage.candidates_token_count if usage else None,
        "latency_ms": int((time.perf_counter() - started) * 1000),
    }
    return response, cost
