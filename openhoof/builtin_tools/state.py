"""State persistence tools."""

import json
import time
from pathlib import Path
from typing import Dict, Any


def save_state(agent, key: str, value: Any) -> Dict[str, Any]:
    """
    Save agent state to .microclaw/state.json.
    """
    workspace = Path(agent.workspace)
    state_dir = workspace / ".microclaw"
    state_dir.mkdir(exist_ok=True)
    
    state_file = state_dir / "state.json"
    
    # Load existing state
    if state_file.exists():
        with open(state_file, "r") as f:
            state = json.load(f)
    else:
        state = {}
    
    # Update
    state[key] = {
        "value": value,
        "updated": int(time.time())
    }
    
    # Save
    with open(state_file, "w") as f:
        json.dump(state, f, indent=2)
    
    return {
        "success": True,
        "key": key,
        "updated": state[key]["updated"]
    }


def load_state(agent, key: str) -> Dict[str, Any]:
    """
    Load saved state.
    """
    workspace = Path(agent.workspace)
    state_file = workspace / ".microclaw" / "state.json"
    
    if not state_file.exists():
        return {"value": None, "message": "No state file found"}
    
    with open(state_file, "r") as f:
        state = json.load(f)
    
    if key not in state:
        return {"value": None, "message": f"Key not found: {key}"}
    
    return {
        "key": key,
        "value": state[key]["value"],
        "updated": state[key]["updated"]
    }


def list_state(agent) -> Dict[str, Any]:
    """
    List all saved state keys.
    """
    workspace = Path(agent.workspace)
    state_file = workspace / ".microclaw" / "state.json"
    
    if not state_file.exists():
        return {"keys": [], "message": "No state file found"}
    
    with open(state_file, "r") as f:
        state = json.load(f)
    
    keys = [
        {
            "key": k,
            "updated": v["updated"],
            "type": type(v["value"]).__name__
        }
        for k, v in state.items()
    ]
    
    return {
        "keys": keys,
        "count": len(keys)
    }
