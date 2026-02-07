"""Sub-agent registry for tracking spawned agents."""

import asyncio
import json
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Optional, Dict, List, Callable, Awaitable, Any
import uuid
import logging

logger = logging.getLogger(__name__)


@dataclass
class SubagentRun:
    """Tracks a spawned sub-agent run."""
    run_id: str
    child_session_key: str
    requester_session_key: str
    agent_id: str
    task: str
    label: Optional[str] = None
    cleanup: str = "keep"  # "keep" or "delete"
    
    created_at: float = field(default_factory=lambda: datetime.now().timestamp())
    started_at: Optional[float] = None
    ended_at: Optional[float] = None
    
    outcome: Optional[str] = None  # "completed", "failed", "timeout"
    result: Optional[str] = None
    error: Optional[str] = None


class SubagentRegistry:
    """Manages spawned sub-agents and their lifecycle."""
    
    def __init__(
        self,
        store_path: Path,
        run_agent: Callable[[str, str, str], Awaitable[str]],  # (agent_id, session_key, task) -> result
        default_timeout_seconds: int = 300,
    ):
        self.store_path = store_path
        self.run_agent = run_agent
        self.default_timeout_seconds = default_timeout_seconds
        self._runs: Dict[str, SubagentRun] = {}
        self._tasks: Dict[str, asyncio.Task] = {}
        self._load()
    
    def _load(self):
        """Load persisted runs from disk."""
        if not self.store_path.exists():
            return
        try:
            data = json.loads(self.store_path.read_text())
            for run_dict in data.get("runs", []):
                run = SubagentRun(**run_dict)
                self._runs[run.run_id] = run
        except (json.JSONDecodeError, TypeError) as e:
            logger.warning(f"Error loading subagent runs: {e}")
    
    def _save(self):
        """Persist runs to disk."""
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        data = {"runs": [asdict(r) for r in self._runs.values()]}
        self.store_path.write_text(json.dumps(data, indent=2))
    
    async def spawn(
        self,
        requester_session_key: str,
        agent_id: str,
        task: str,
        label: Optional[str] = None,
        timeout_seconds: Optional[int] = None,
        cleanup: str = "keep",
    ) -> SubagentRun:
        """Spawn a new sub-agent run."""
        run_id = str(uuid.uuid4())[:8]
        child_session_key = f"subagent:{agent_id}:{run_id}"
        
        run = SubagentRun(
            run_id=run_id,
            child_session_key=child_session_key,
            requester_session_key=requester_session_key,
            agent_id=agent_id,
            task=task,
            label=label,
            cleanup=cleanup,
        )
        
        self._runs[run_id] = run
        self._save()
        
        # Start async execution
        timeout = timeout_seconds or self.default_timeout_seconds
        task_obj = asyncio.create_task(self._execute_run(run, timeout))
        self._tasks[run_id] = task_obj
        
        logger.info(f"Spawned subagent {run_id}: {agent_id} for '{label or task[:50]}'")
        return run
    
    async def _execute_run(self, run: SubagentRun, timeout_seconds: int):
        """Execute a sub-agent run with timeout."""
        run.started_at = datetime.now().timestamp()
        self._save()
        
        try:
            result = await asyncio.wait_for(
                self.run_agent(run.agent_id, run.child_session_key, run.task),
                timeout=timeout_seconds
            )
            run.ended_at = datetime.now().timestamp()
            run.outcome = "completed"
            run.result = result
            
        except asyncio.TimeoutError:
            run.ended_at = datetime.now().timestamp()
            run.outcome = "timeout"
            run.error = f"Timed out after {timeout_seconds}s"
            
        except Exception as e:
            run.ended_at = datetime.now().timestamp()
            run.outcome = "failed"
            run.error = str(e)
            logger.error(f"Subagent {run.run_id} failed: {e}")
        
        self._save()
        
        # Cleanup task reference
        if run.run_id in self._tasks:
            del self._tasks[run.run_id]
        
        logger.info(f"Subagent {run.run_id} finished: {run.outcome}")
    
    def get_run(self, run_id: str) -> Optional[SubagentRun]:
        return self._runs.get(run_id)
    
    def list_runs(
        self,
        requester_session_key: Optional[str] = None,
        status: Optional[str] = None,  # "running", "completed", "failed"
    ) -> List[SubagentRun]:
        runs = list(self._runs.values())
        
        if requester_session_key:
            runs = [r for r in runs if r.requester_session_key == requester_session_key]
        
        if status == "running":
            runs = [r for r in runs if r.ended_at is None]
        elif status == "completed":
            runs = [r for r in runs if r.outcome == "completed"]
        elif status == "failed":
            runs = [r for r in runs if r.outcome in ("failed", "timeout")]
        
        return sorted(runs, key=lambda r: r.created_at, reverse=True)
    
    def cleanup_old_runs(self, max_age_hours: int = 24):
        """Remove old completed runs."""
        cutoff = datetime.now().timestamp() - (max_age_hours * 3600)
        to_remove = [
            run_id for run_id, run in self._runs.items()
            if run.ended_at and run.ended_at < cutoff and run.cleanup == "delete"
        ]
        for run_id in to_remove:
            del self._runs[run_id]
        if to_remove:
            self._save()
