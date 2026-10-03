import os
from dotenv import load_dotenv
from google import genai
from google.genai import types
from core.tools import get_employee, get_it_account, search_policies

load_dotenv()
client = genai.Client(
    http_options=types.HttpOptions(
        retry_options=types.HttpRetryOptions(attempts=4, initial_delay=2.0)
    )
)
MODEL = os.environ["GEMINI_MODEL"]
TOOLS = {f.__name__: f for f in (get_employee, get_it_account, search_policies)}

SYSTEM = """You are the IT helpdesk agent for Kestrel Works.
You are talking to employee {employee_id}.
Look things up with the tools. Never guess account details or policy.
Before each tool call, write one short sentence saying why you need it.
Answer only from tool results and cite policy IDs. If the tools don't cover it, say so."""


def run(question: str, employee_id: str = "E001", max_steps: int = 6) -> str:
    config = types.GenerateContentConfig(
        system_instruction=SYSTEM.format(employee_id=employee_id),
        tools=list(TOOLS.values()),
        # We run the loop ourselves; without this the SDK would do it silently.
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )
    contents = [types.Content(role="user", parts=[types.Part(text=question)])]

    for step in range(1, max_steps + 1):
        response = client.models.generate_content(model=MODEL, contents=contents, config=config)
        reply = response.candidates[0].content
        contents.append(reply)                      # keep the model's turn exactly as returned

        calls = response.function_calls
        if not calls:                               # no tool requested = final answer
            return response.text

        for part in reply.parts:
            if part.text:
                print(f"[{step}] THOUGHT  {part.text.strip()}")

        results = []
        for call in calls:
            print(f"[{step}] ACTION   {call.name}({dict(call.args)})")
            try:
                result = TOOLS[call.name](**call.args)
            except Exception as e:                  # bad tool name or bad args from the model
                result = {"error": str(e)}
            print(f"[{step}] OBSERVE  {result}")
            results.append(types.Part.from_function_response(name=call.name, response={"result": result}))
        contents.append(types.Content(role="user", parts=results))

    return "Stopped: step limit reached."