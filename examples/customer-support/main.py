#!/usr/bin/env python3
"""
customer-support — Support agent with CRM-style tool chaining.

Demonstrates:
- Multi-turn dependent tool calls (lookup → ticket → update → close)
- Memory search for similar past issues before answering
- Escalation path when agent can't resolve

Usage:
    cd examples/customer-support
    pip install openhoof
    python main.py
"""

import random
import string
from pathlib import Path
from openhoof import Agent, get_builtin_tool_schemas, builtin_executor, create_tool_schema

HERE = Path(__file__).parent

# ── Simulated CRM / KB backend (swap for real API calls) ─────────────────────

_ACCOUNTS = {
    "alice@example.com": {"name": "Alice", "plan": "Pro", "status": "active", "tickets": 2},
    "bob@example.com":   {"name": "Bob",   "plan": "Free", "status": "active", "tickets": 0},
}

_TICKETS: dict = {}

_KB_ARTICLES = {
    "login": "AUTH-001: Clear browser cache, check MFA app time sync. If SSO, verify IdP config.",
    "slow":  "PERF-001: Dashboard slowness often indicates plan limits. Check usage in Settings > Billing.",
    "api":   "API-002: 429 errors = rate limit exceeded. Free plan: 100 req/min. Pro: 1000 req/min.",
    "reset": "AUTH-002: Password reset via /forgot-password. Link expires in 15 minutes.",
}


def lookup_account(email: str) -> dict:
    acct = _ACCOUNTS.get(email.lower())
    if not acct:
        return {"found": False, "email": email}
    return {"found": True, "email": email, **acct}


def search_kb(query: str) -> dict:
    query_lower = query.lower()
    results = [
        {"article": k, "content": v}
        for k, v in _KB_ARTICLES.items()
        if k in query_lower or any(w in query_lower for w in v.lower().split()[:5])
    ]
    return {"results": results, "count": len(results)}


def create_ticket(email: str, subject: str, description: str) -> dict:
    ticket_id = "TKT-" + "".join(random.choices(string.digits, k=5))
    _TICKETS[ticket_id] = {
        "email": email, "subject": subject,
        "description": description, "status": "open", "notes": [],
    }
    return {"ticket_id": ticket_id, "status": "open"}


def update_ticket(ticket_id: str, note: str) -> dict:
    if ticket_id not in _TICKETS:
        return {"success": False, "error": f"Ticket {ticket_id} not found"}
    _TICKETS[ticket_id]["notes"].append(note)
    return {"success": True, "ticket_id": ticket_id}


def close_ticket(ticket_id: str, resolution: str) -> dict:
    if ticket_id not in _TICKETS:
        return {"success": False, "error": f"Ticket {ticket_id} not found"}
    _TICKETS[ticket_id]["status"] = "closed"
    _TICKETS[ticket_id]["resolution"] = resolution
    return {"success": True, "ticket_id": ticket_id, "status": "closed"}


def escalate_ticket(ticket_id: str, reason: str) -> dict:
    if ticket_id not in _TICKETS:
        return {"success": False, "error": f"Ticket {ticket_id} not found"}
    _TICKETS[ticket_id]["status"] = "escalated"
    _TICKETS[ticket_id]["escalation_reason"] = reason
    print(f"\n🔴 ESCALATED {ticket_id}: {reason}\n")
    return {"success": True, "ticket_id": ticket_id, "status": "escalated", "assigned_to": "support-lead@acme.example.com"}


# ── Tool schemas ──────────────────────────────────────────────────────────────

SUPPORT_TOOLS = [
    create_tool_schema(
        name="lookup_account",
        summary="Look up a customer account by email",
        when_to_use="First step when customer identifies themselves",
        parameters={
            "type": "object",
            "properties": {"email": {"type": "string"}},
            "required": ["email"],
        },
    ),
    create_tool_schema(
        name="search_kb",
        summary="Search the knowledge base for solutions",
        when_to_use="Before answering any product question — always check KB first",
        parameters={
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    ),
    create_tool_schema(
        name="create_ticket",
        summary="Open a new support ticket",
        when_to_use="When starting a new issue that requires tracking",
        parameters={
            "type": "object",
            "properties": {
                "email":       {"type": "string"},
                "subject":     {"type": "string"},
                "description": {"type": "string"},
            },
            "required": ["email", "subject", "description"],
        },
    ),
    create_tool_schema(
        name="update_ticket",
        summary="Add a note to an existing ticket",
        when_to_use="After each step taken toward resolution",
        parameters={
            "type": "object",
            "properties": {
                "ticket_id": {"type": "string"},
                "note":      {"type": "string"},
            },
            "required": ["ticket_id", "note"],
        },
    ),
    create_tool_schema(
        name="close_ticket",
        summary="Resolve and close a ticket",
        when_to_use="When the issue is confirmed resolved by the customer",
        parameters={
            "type": "object",
            "properties": {
                "ticket_id":  {"type": "string"},
                "resolution": {"type": "string"},
            },
            "required": ["ticket_id", "resolution"],
        },
    ),
    create_tool_schema(
        name="escalate_ticket",
        summary="Escalate ticket to a human support agent",
        when_to_use="Customer angry + unresolved, billing dispute, security issue, or no documented solution",
        parameters={
            "type": "object",
            "properties": {
                "ticket_id": {"type": "string"},
                "reason":    {"type": "string"},
            },
            "required": ["ticket_id", "reason"],
        },
    ),
]

ALL_TOOLS = get_builtin_tool_schemas() + SUPPORT_TOOLS

TOOL_FNS = {
    "lookup_account":  lookup_account,
    "search_kb":       search_kb,
    "create_ticket":   create_ticket,
    "update_ticket":   update_ticket,
    "close_ticket":    close_ticket,
    "escalate_ticket": escalate_ticket,
}


def executor(agent, tool_name: str, params: dict) -> dict:
    if tool_name in TOOL_FNS:
        return TOOL_FNS[tool_name](**params)
    return builtin_executor(agent, tool_name, params)


def main():
    agent = Agent(
        soul=str(HERE / "SOUL.md"),
        memory=str(HERE / "MEMORY.md"),
        tools=ALL_TOOLS,
        executor=lambda name, params: executor(agent, name, params),
        workspace=str(HERE),
        max_turns=10,
    )

    print("🎧 Support Agent ready.\n")
    print("Test accounts: alice@example.com (Pro), bob@example.com (Free)")
    print("Try: 'I'm alice@example.com and I can't log in'\n")

    while True:
        try:
            user_input = input("Customer: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nSession ended.")
            break

        if not user_input:
            continue
        if user_input.lower() in ("quit", "exit"):
            break

        response = agent.reason(user_input)
        print(f"\nAgent: {response.get('content', '')}\n")


if __name__ == "__main__":
    main()
