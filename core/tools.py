from core.data import EMPLOYEES, IT_ACCOUNTS, POLICIES


def get_employee(employee_id: str) -> dict:
    """Look up an employee's profile (name, team, location) by employee ID, e.g. E001."""
    return EMPLOYEES.get(employee_id) or {"error": f"No employee {employee_id}"}


def get_it_account(employee_id: str) -> dict:
    """Get an employee's IT account state: VPN client version, VPN status, password expiry, lock status."""
    return IT_ACCOUNTS.get(employee_id) or {"error": f"No IT account for {employee_id}"}


def search_policies(query: str) -> list[dict]:
    """Search IT policy articles by keywords. Returns the best matching articles with their IDs."""
    words = set(query.lower().split())
    scored = [(len(words & set((p["title"] + " " + p["text"]).lower().split())), p) for p in POLICIES]
    return [p for score, p in sorted(scored, key=lambda x: -x[0]) if score > 0][:2]