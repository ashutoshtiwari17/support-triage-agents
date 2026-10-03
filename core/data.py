EMPLOYEES = {
    "E001": {"name": "Priya Nair", "email": "priya@kestrel.example", "team": "Engineering", "location": "Bengaluru"},
    "E002": {"name": "Arjun Mehta", "email": "arjun@kestrel.example", "team": "Sales", "location": "Mumbai"},
    "E003": {"name": "Sara Khan", "email": "sara@kestrel.example", "team": "Finance", "location": "Pune"},
}

IT_ACCOUNTS = {
    "E001": {"vpn_client": "2.1", "vpn_status": "active", "password_expires_in_days": 3, "locked": False},
    "E002": {"vpn_client": "3.0", "vpn_status": "active", "password_expires_in_days": 41, "locked": True},
    "E003": {"vpn_client": "3.0", "vpn_status": "suspended", "password_expires_in_days": 20, "locked": False},
}

POLICIES = [
    {"id": "IT-001", "title": "VPN client versions",
     "text": "Only VPN client 3.0 or later is supported. Older clients disconnect frequently. Update from the Self Service app."},
    {"id": "IT-002", "title": "Account lockout",
     "text": "Accounts lock after 5 failed logins. Employees can unlock via the Self Service portal using MFA. If MFA is unavailable, the IT service desk must unlock it."},
    {"id": "IT-003", "title": "Password expiry",
     "text": "Passwords expire every 90 days. Change it from the Self Service portal before expiry. Expired passwords require an IT service desk reset."},
    {"id": "IT-004", "title": "Suspended VPN access",
     "text": "VPN access is suspended after 60 days of inactivity. Reactivation requires manager approval and an IT service desk ticket."},
]