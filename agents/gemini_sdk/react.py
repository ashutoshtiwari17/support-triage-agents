import json
import os
import time

from dotenv import load_dotenv
from google import genai
from google.genai import types

from core.schemas import Framework, Pattern, StepType
from core.tools import tools_for
from core.trace import Recorder

load_dotenv()
MODEL = os.environ["GEMINI_MODEL"]
AGENT = "helpdesk_agent"

SYSTEM = """You are the HR, Finance and IT helpdesk agent for Kestrel Works.
Look things up with the tools. Never guess account details or policy.
The tools already know who you are talking to; you never need an employee ID.
Before each tool call, write one short sentence saying why you need it.
Answer only from tool results and cite the policy ID and section, e.g. (HR-001, section 2).
If the tools don't cover it, say so. Policy search is already limited to this person's employment 
type; you don't need their profile to search."""


def make_client(api_key: str | None = None) -> genai.Client:
    """Vertex AI by default (from env vars); AI Studio when a visitor brings their own key."""
    http = types.HttpOptions(retry_options=types.HttpRetryOptions(attempts=4, initial_delay=2.0))
    if api_key:
        return genai.Client(vertexai=False, api_key=api_key, http_options=http)
    return genai.Client(http_options=http)

def run(
    question: str,
    employee_id: str = "E001",
    max_steps: int = 6,
    history: list[dict] | None = None,
    recorder: Recorder | None = None,
    api_key: str | None = None,
) -> str:
    """Answer one message.

    `history` is earlier turns as {"role": "user"|"assistant", "text": ...}.
    `api_key` lets a visitor run on their own Gemini key; it is used for this run only.
    """
    rec = recorder or Recorder(Pattern.REACT, Framework.GEMINI_SDK)
    answer = _loop(make_client(api_key), question, employee_id, max_steps, history or [], rec)
    rec.finish(question, answer)
    return answer


def _loop(client: genai.Client, question: str, employee_id: str, max_steps: int,
          history: list[dict], rec: Recorder, final_type: StepType = StepType.FINAL) -> str:
    """The ReAct loop. `final_type` is FINAL normally; the Reflection agent passes DRAFT,
    because for it this answer is only a first version to be checked."""
    # Tools are built per run and bound to this person; the model never passes an identity.
    tools = {f.__name__: f for f in tools_for(employee_id, client)}
    config = types.GenerateContentConfig(
        system_instruction=SYSTEM,
        tools=list(tools.values()),
        # We run the loop ourselves; without this the SDK would do it silently.
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )
    contents = [
        types.Content(role="model" if turn["role"] == "assistant" else "user",
                      parts=[types.Part(text=turn["text"])])
        for turn in history
    ]
    contents.append(types.Content(role="user", parts=[types.Part(text=question)]))

    for _ in range(max_steps):
        started = time.perf_counter()
        response = client.models.generate_content(model=MODEL, contents=contents, config=config)
        rec.llm_calls += 1
        usage = response.usage_metadata
        # Cost of this model call; attached to the first step it produced.
        cost = {
            "tokens_in": usage.prompt_token_count if usage else None,
            "tokens_out": usage.candidates_token_count if usage else None,
            "latency_ms": int((time.perf_counter() - started) * 1000),
        }

        if not response.candidates or not response.candidates[0].content:
            answer = "The model returned no answer for this message."
            rec.emit(final_type, AGENT, answer, **cost)
            return answer

        reply = response.candidates[0].content
        contents.append(reply)                      # keep the model's turn exactly as returned
        text = "".join(p.text for p in (reply.parts or []) if p.text and not p.thought).strip()

        calls = response.function_calls
        if not calls:                               # no tool requested = final answer
            answer = text or "The model returned no answer for this message."
            rec.emit(final_type, AGENT, answer, **cost)
            return answer

        if text:
            rec.emit(StepType.THOUGHT, AGENT, text, **cost)
            cost = {}

        results = []
        for call in calls:
            args = dict(call.args or {})
            shown = ", ".join(f"{k}={v!r}" for k, v in args.items())
            rec.emit(StepType.ACTION, AGENT, f"{call.name}({shown})",
                     tool_name=call.name, tool_args=args, **cost)
            cost = {}

            tool_started = time.perf_counter()
            try:
                result = tools[call.name](**args)
            except Exception as e:                  # bad tool name or bad args from the model
                result = {"error": str(e)}
            rec.emit(StepType.OBSERVATION, "tool", json.dumps(result, default=str),
                     tool_name=call.name,
                     latency_ms=int((time.perf_counter() - tool_started) * 1000))
            results.append(types.Part.from_function_response(name=call.name, response={"result": result}))
        contents.append(types.Content(role="user", parts=results))

    answer = "Stopped: step limit reached."
    rec.emit(final_type, AGENT, answer)
    return answer
