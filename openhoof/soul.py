"""
Soul — Agent identity and mission from SOUL.md.

The Soul defines:
- Who the agent is (identity, emoji)
- What their mission is
- Style, tone, constraints
- Hard rules

Becomes the system prompt for the agent's reasoning model.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional


class Soul:
    """Agent identity loaded from SOUL.md."""
    
    def __init__(self, content: str, path: Optional[str] = None):
        self.content = content
        self.path = path
        self._parse()
    
    def _parse(self):
        """Extract key metadata from SOUL.md if present."""
        lines = self.content.split("\n")
        self.name = "Agent"
        self.emoji = "🤖"
        
        # Simple header parsing (optional)
        for line in lines:
            if line.startswith("# SOUL.md"):
                continue
            if "**Name:**" in line or "- **Name:**" in line:
                self.name = line.split("**Name:**")[-1].strip()
            if "**Emoji:**" in line or "- **Emoji:**" in line:
                self.emoji = line.split("**Emoji:**")[-1].strip()
    
    @classmethod
    def from_file(cls, path: str) -> Soul:
        """Load SOUL.md from file."""
        p = Path(path).resolve()
        if not p.exists():
            raise FileNotFoundError(f"SOUL.md not found: {p}")
        
        content = p.read_text()
        return cls(content, str(p))
    
    @classmethod
    def from_string(cls, content: str) -> Soul:
        """Create Soul from string (testing)."""
        return cls(content)
    
    def to_system_prompt(self) -> str:
        """Convert SOUL.md into system prompt for reasoning model."""
        return f"""{self.content}

---

You are {self.name} {self.emoji}.

Follow the mission and principles in the document above.
Use your tools to complete tasks autonomously.
Check heartbeat conditions regularly.
Store data when network is unavailable.
"""
    
    def __repr__(self) -> str:
        return f"Soul(name={self.name!r}, emoji={self.emoji!r}, path={self.path!r})"
