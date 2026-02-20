"""
DDIL — Store-and-forward buffer for Denied, Degraded, Intermittent, Limited networks.

When the agent loses network:
1. Buffer data locally (telemetry, detections, logs)
2. Continue mission autonomously
3. When network returns, sync buffered data to server

The buffer:
- Stores events as JSONL
- Tracks sync status
- Automatically flushes when network available
- Configurable size limits

Integration with OpenClaw Gateway:
- POST buffered data to gateway /api/agent/sync
- Gateway routes to appropriate agents/channels
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional


class DDILBuffer:
    """Store-and-forward buffer for offline operation."""
    
    def __init__(self, buffer_dir: str = ".microclaw/ddil"):
        self.buffer_dir = Path(buffer_dir)
        self.buffer_dir.mkdir(parents=True, exist_ok=True)
        
        self.buffer_file = self.buffer_dir / "buffer.jsonl"
        self.synced_file = self.buffer_dir / "synced.jsonl"
        
        self.buffered_count = 0
        self.synced_count = 0
        self.last_sync: Optional[float] = None
    
    def store(self, event_type: str, data: Dict[str, Any]):
        """Store an event in the buffer."""
        entry = {
            "type": event_type,
            "data": data,
            "timestamp": time.time(),
            "synced": False
        }
        
        with open(self.buffer_file, "a") as f:
            f.write(json.dumps(entry) + "\n")
        
        self.buffered_count += 1
    
    def get_pending(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Get pending (unsynced) events from buffer."""
        if not self.buffer_file.exists():
            return []
        
        pending = []
        with open(self.buffer_file, "r") as f:
            for line in f:
                if not line.strip():
                    continue
                
                try:
                    entry = json.loads(line)
                    if not entry.get("synced", False):
                        pending.append(entry)
                        
                        if len(pending) >= limit:
                            break
                except json.JSONDecodeError:
                    continue
        
        return pending
    
    def mark_synced(self, entries: List[Dict[str, Any]]):
        """Mark entries as synced and move to synced log."""
        # Append to synced log
        with open(self.synced_file, "a") as f:
            for entry in entries:
                entry["synced"] = True
                entry["synced_at"] = time.time()
                f.write(json.dumps(entry) + "\n")
        
        self.synced_count += len(entries)
        self.last_sync = time.time()
    
    def sync_to_server(self, server_url: str, timeout: float = 10.0) -> bool:
        """
        Sync buffered data to OpenClaw gateway.
        
        Returns True if sync successful, False otherwise.
        Phase 1: Mock implementation (just marks as synced).
        Phase 2: Actual HTTP POST to gateway.
        """
        pending = self.get_pending(limit=100)
        if not pending:
            return True
        
        # TODO Phase 2: Actual HTTP POST
        # try:
        #     response = requests.post(
        #         f"{server_url}/api/agent/sync",
        #         json={"events": pending},
        #         timeout=timeout
        #     )
        #     if response.status_code == 200:
        #         self.mark_synced(pending)
        #         return True
        # except requests.RequestException:
        #     return False
        
        # Phase 1: Just mark as synced
        self.mark_synced(pending)
        return True
    
    def clear(self):
        """Clear all buffered data (dangerous!)."""
        if self.buffer_file.exists():
            self.buffer_file.unlink()
        self.buffered_count = 0
    
    def stats(self) -> Dict[str, Any]:
        """Get buffer statistics."""
        pending = len(self.get_pending())
        
        return {
            "pending": pending,
            "total_buffered": self.buffered_count,
            "total_synced": self.synced_count,
            "last_sync": self.last_sync,
            "buffer_file": str(self.buffer_file),
        }
    
    def __repr__(self) -> str:
        stats = self.stats()
        return (
            f"DDILBuffer(pending={stats['pending']}, "
            f"synced={self.synced_count}, "
            f"last_sync={self.last_sync or 'never'})"
        )
