#!/usr/bin/env python3
"""
Multi-tool scenario: Tools that depend on each other.
The LLM must call them in sequence, using results from previous calls.

Scenario: Payment system
1. get_user_id(name) -> user_id
2. get_balance(user_id) -> current balance
3. make_payment(user_id, amount) -> confirmation

Example flow:
User: "Pay $50 for Rob"
→ LLM calls get_user_id("Rob") → 123
→ LLM calls get_balance(123) → $200
→ LLM calls make_payment(123, 50) → "Payment successful"
→ LLM responds: "Paid $50 to Rob. New balance: $150"
"""

import time
from openhoof import Agent

# Fake user database
USER_DB = {
    "Rob": {"id": 123, "balance": 200.0},
    "Alice": {"id": 456, "balance": 150.0},
    "Bob": {"id": 789, "balance": 75.0}
}

# Tool implementations
def get_user_id(name: str) -> dict:
    """Look up user ID by name."""
    print(f"   🔍 get_user_id({name!r})")
    
    for user_name, data in USER_DB.items():
        if user_name.lower() == name.lower():
            user_id = data["id"]
            print(f"      → Found user_id: {user_id}")
            return {"user_id": user_id, "name": user_name}
    
    print(f"      → User not found")
    return {"error": f"User {name!r} not found"}


def get_balance(user_id: int) -> dict:
    """Get current balance for a user."""
    print(f"   💰 get_balance({user_id})")
    
    for user_name, data in USER_DB.items():
        if data["id"] == user_id:
            balance = data["balance"]
            print(f"      → Balance: ${balance:.2f}")
            return {"user_id": user_id, "balance": balance}
    
    print(f"      → User not found")
    return {"error": f"User ID {user_id} not found"}


def make_payment(user_id: int, amount: float) -> dict:
    """Process a payment (deduct from balance)."""
    print(f"   💸 make_payment(user_id={user_id}, amount=${amount})")
    
    for user_name, data in USER_DB.items():
        if data["id"] == user_id:
            if data["balance"] < amount:
                print(f"      → Insufficient funds (${data['balance']:.2f} < ${amount})")
                return {"error": "Insufficient funds", "balance": data["balance"]}
            
            # Process payment
            data["balance"] -= amount
            new_balance = data["balance"]
            print(f"      → Payment successful! New balance: ${new_balance:.2f}")
            return {
                "success": True,
                "amount_paid": amount,
                "new_balance": new_balance,
                "user_id": user_id
            }
    
    print(f"      → User not found")
    return {"error": f"User ID {user_id} not found"}


def add_funds(user_id: int, amount: float) -> dict:
    """Add funds to a user's balance."""
    print(f"   💵 add_funds(user_id={user_id}, amount=${amount})")
    
    for user_name, data in USER_DB.items():
        if data["id"] == user_id:
            data["balance"] += amount
            new_balance = data["balance"]
            print(f"      → Funds added! New balance: ${new_balance:.2f}")
            return {
                "success": True,
                "amount_added": amount,
                "new_balance": new_balance,
                "user_id": user_id
            }
    
    print(f"      → User not found")
    return {"error": f"User ID {user_id} not found"}


# Tool schemas (OpenAI format)
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_user_id",
            "description": "Look up a user's ID by their name. Must be called first before other user operations.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "User's name (e.g. 'Rob', 'Alice', 'Bob')"
                    }
                },
                "required": ["name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_balance",
            "description": "Get current balance for a user. Requires user_id from get_user_id.",
            "parameters": {
                "type": "object",
                "properties": {
                    "user_id": {
                        "type": "integer",
                        "description": "User ID (from get_user_id)"
                    }
                },
                "required": ["user_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "make_payment",
            "description": "Process a payment (deduct from user's balance). Requires user_id and checks balance first.",
            "parameters": {
                "type": "object",
                "properties": {
                    "user_id": {
                        "type": "integer",
                        "description": "User ID (from get_user_id)"
                    },
                    "amount": {
                        "type": "number",
                        "description": "Amount to pay in dollars"
                    }
                },
                "required": ["user_id", "amount"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "add_funds",
            "description": "Add funds to a user's balance. Requires user_id.",
            "parameters": {
                "type": "object",
                "properties": {
                    "user_id": {
                        "type": "integer",
                        "description": "User ID (from get_user_id)"
                    },
                    "amount": {
                        "type": "number",
                        "description": "Amount to add in dollars"
                    }
                },
                "required": ["user_id", "amount"]
            }
        }
    }
]


# Tool executor
def execute_tool(tool_name: str, params: dict) -> dict:
    """Execute a tool by name."""
    if tool_name == "get_user_id":
        return get_user_id(**params)
    elif tool_name == "get_balance":
        return get_balance(**params)
    elif tool_name == "make_payment":
        return make_payment(**params)
    elif tool_name == "add_funds":
        return add_funds(**params)
    else:
        return {"error": f"Unknown tool: {tool_name}"}


# Context files
SOUL_CONTENT = """# SOUL.md
- **Name:** PaymentBot
- **Emoji:** 💳
- **Mission:** Help users manage payments and check balances

## Guidelines
- Always look up user_id first using get_user_id
- Check balance before making payments
- Confirm all transactions clearly
- Handle errors gracefully
"""

MEMORY_CONTENT = """# MEMORY.md
PaymentBot created 2026-02-20.
Users: Rob ($200), Alice ($150), Bob ($75)
"""


if __name__ == "__main__":
    print("🐴 OpenHoof v2.0 — Multi-Tool Test\n")
    print("Scenario: Payment system with dependent tools\n")
    
    # Write context files
    with open("SOUL.md", "w") as f:
        f.write(SOUL_CONTENT)
    with open("MEMORY.md", "w") as f:
        f.write(MEMORY_CONTENT)
    
    # Create agent
    agent = Agent(
        soul="SOUL.md",
        memory="MEMORY.md",
        tools=TOOLS,
        executor=execute_tool,
        heartbeat_interval=30.0
    )
    
    print("\n" + "=" * 70)
    print("Test 1: Simple payment (requires 3 tool calls)")
    print("=" * 70)
    print("Request: 'Pay $50 for Rob'\n")
    
    response = agent.reason("Pay $50 for Rob")
    print(f"\n📤 Response:\n{response.get('content', response)}\n")
    
    print("\n" + "=" * 70)
    print("Test 2: Check balance (requires 2 tool calls)")
    print("=" * 70)
    print("Request: 'What is Alice's balance?'\n")
    
    response = agent.reason("What is Alice's balance?")
    print(f"\n📤 Response:\n{response.get('content', response)}\n")
    
    print("\n" + "=" * 70)
    print("Test 3: Insufficient funds (requires 3 tool calls + error handling)")
    print("=" * 70)
    print("Request: 'Pay $100 for Bob'\n")
    
    response = agent.reason("Pay $100 for Bob")
    print(f"\n📤 Response:\n{response.get('content', response)}\n")
    
    print("\n" + "=" * 70)
    print("Test 4: Add funds then pay (requires 4+ tool calls)")
    print("=" * 70)
    print("Request: 'Add $50 to Bob then pay $100'\n")
    
    response = agent.reason("Add $50 to Bob then pay $100")
    print(f"\n📤 Response:\n{response.get('content', response)}\n")
    
    print("\n✅ Multi-tool tests complete!")
    print(f"   Total tools called: {agent.tools_called}")
    print(f"   Training samples: {agent.training.captured_count}")
    
    print("\n📊 Final balances:")
    for name, data in USER_DB.items():
        print(f"   {name}: ${data['balance']:.2f}")
