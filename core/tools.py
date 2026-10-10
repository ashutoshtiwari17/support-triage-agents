"""The tools an agent can call, bound to the person it is talking to.

`tools_for(employee_id, client)` returns functions that already know who the user is.
None of them takes an employee ID as an argument, so the model cannot look up someone
else's account or widen its own policy access, whatever the user types.
"""
from google import genai

from core.data import EMPLOYEES, IT_ACCOUNTS
from core.retrieval import search_chunks
from core.schemas import EmploymentType


def tools_for(employee_id: str, client: genai.Client) -> list:
    profile = EMPLOYEES[employee_id]                     # the server checked the ID already
    audience = EmploymentType(profile["employment_type"])

    def get_my_profile() -> dict:
        """Profile of the person you are helping: name, team, location and employment type (employee or contractor)."""
        return {"id": employee_id, **profile}

    def get_my_it_account() -> dict:
        """IT account state of the person you are helping: VPN client version, VPN status, password expiry, lock status."""
        return IT_ACCOUNTS.get(employee_id) or {"error": "No IT account on record"}

    def search_policies(query: str) -> list[dict]:
        """Search Kestrel Works HR, Finance and IT policies by meaning. Returns the closest passages,
        each with its policy ID, section and source. Only policies that apply to this person are searched.
        Write the query as a plain question or topic, e.g. 'earned leave carry forward'."""
        return search_chunks(client, query, audience)

    return [get_my_profile, get_my_it_account, search_policies]
