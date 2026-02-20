"""
Agent — Core agent runtime with event loop and heartbeat.

The Agent class is the heart of MicroClaw. It implements:
1. Event loop (heartbeat, event polling, wait for wake)
2. Context file loading (Soul, Memory, User, Tools)
3. Tool execution with training data capture
4. Memory recall before answering
5. Store-and-forward (DDIL) buffering
6. Exit condition monitoring
7. Sub-agent spawning (Phase 2)

Usage:
    from microclaw import Agent
    from openhoof.drone_tools import DRONE_TOOLS, DroneToolExecutor
    
    agent = Agent(
        soul="SOUL.md",
        memory="MEMORY.md",
        tools=DRONE_TOOLS,
        executor=DroneToolExecutor()
    )
    
    agent.on_exit("battery_low", lambda: agent.battery < 20)
    agent.heartbeat_interval = 30
    agent.run()
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .soul import Soul
from .memory import Memory
from .heartbeat import Heartbeat
from .tool_registry import ToolRegistry  # Use simple registry
from .events import EventQueue, Event
from .ddil import DDILBuffer
from .training import TrainingDataCapture
from .models import ModelLoader


class Agent:
    """
    MicroClaw agent runtime.
    
    This is the Phase 1 Python reference implementation.
    Phase 2 will port this to Kotlin (Android).
    Phase 3 will port to Rust (cross-platform core).
    """
    
    def __init__(
        self,
        soul: str | Soul,
        memory: str | Memory,
        tools: List[Dict[str, Any]] = None,
        executor: Optional[Callable[[str, Dict], Dict]] = None,
        model: Optional[str] = None,
        llamafarm_config: Optional[str] = None,
        heartbeat_interval: float = 30.0,
        workspace: Optional[str] = None
    ):
        """
        Initialize MicroClaw agent.
        
        Args:
            soul: Path to SOUL.md or Soul instance
            memory: Path to MEMORY.md or Memory instance
            tools: List of OpenHoof-compatible tool schemas
            executor: Tool executor function: (tool_name, params) -> result
            model: Model identifier override (optional)
            llamafarm_config: Path to llamafarm.yaml (defaults to ./llamafarm.yaml)
            heartbeat_interval: Seconds between heartbeats
            workspace: Working directory (defaults to cwd)
        """
        # Context files
        self.soul = soul if isinstance(soul, Soul) else Soul.from_file(soul)
        self.memory = memory if isinstance(memory, Memory) else Memory.from_file(memory)
        
        # Tools
        self.tools = ToolRegistry(tools, executor)
        
        # Model loader (LlamaFarm integration)
        workspace_dir = workspace or os.getcwd()
        config_path = llamafarm_config or os.path.join(workspace_dir, "llamafarm.yaml")
        self.model_loader = ModelLoader(config_path)
        self.model_name = model  # Optional override
        
        # Event system
        self.events = EventQueue()
        
        # Heartbeat
        self.heartbeat = Heartbeat(self, interval=heartbeat_interval)
        
        # DDIL buffer
        workspace_dir = workspace or os.getcwd()
        self.ddil = DDILBuffer(f"{workspace_dir}/.microclaw/ddil")
        
        # Training data capture
        self.training = TrainingDataCapture(f"{workspace_dir}/.microclaw/training")
        
        # Agent state
        self.state = "initializing"
        self.running = False
        self.start_time: Optional[float] = None
        self.stop_time: Optional[float] = None
        
        # Metrics
        self.events_processed = 0
        self.tools_called = 0
        
        # Custom state (user can attach arbitrary data)
        self.custom: Dict[str, Any] = {}
        
        print(f"🐴 MicroClaw Agent initialized")
        print(f"   Soul: {self.soul.name} {self.soul.emoji}")
        print(f"   Memory: {self.memory}")
        print(f"   Tools: {len(self.tools)} registered")
        print(f"   Model: {self.model_loader}")
        print(f"   Heartbeat: every {heartbeat_interval}s")
    
    def run(self):
        """
        Run the agent event loop.
        
        This blocks until an exit condition is triggered or KeyboardInterrupt.
        """
        self.running = True
        self.start_time = time.time()
        self.state = "running"
        
        print(f"\n🟢 Agent {self.soul.name} starting event loop...")
        
        try:
            while self.running:
                # 1. Heartbeat check
                if self.heartbeat.should_beat():
                    self._do_heartbeat()
                
                # 2. Check exit conditions
                exit_reason = self.heartbeat.check_exit_conditions()
                if exit_reason:
                    print(f"\n🛑 Exit condition triggered: {exit_reason}")
                    self.shutdown(exit_reason)
                    break
                
                # 3. Poll for events (wait up to 1s for first event)
                events = self.events.poll(timeout=1.0)
                
                # 4. Process events
                for event in events:
                    self._handle_event(event)
                
                # 5. Sleep briefly if no events
                if not events:
                    time.sleep(0.1)
        
        except KeyboardInterrupt:
            print("\n⚠️ Interrupted by user")
            self.shutdown("keyboard_interrupt")
        
        except Exception as e:
            print(f"\n❌ Agent crashed: {e}")
            import traceback
            traceback.print_exc()
            self.shutdown("crash")
    
    def _do_heartbeat(self):
        """Execute a heartbeat."""
        self.heartbeat.beat()
        
        # Sync DDIL buffer if network available (Phase 2: actual network check)
        # For now, just mark as synced
        if self.ddil.get_pending():
            self.ddil.sync_to_server("http://gateway.local")
    
    def _handle_event(self, event: Event):
        """Handle a single event."""
        self.events_processed += 1
        
        print(f"📩 Event: {event.type} (priority={event.priority:.1f})")
        
        # Default event handlers
        if event.type == "tool_call":
            self._handle_tool_call(event)
        elif event.type == "shutdown":
            self.shutdown(event.data.get("reason", "unknown"))
        else:
            # User-defined event handler (Phase 2)
            pass
    
    def _handle_tool_call(self, event: Event):
        """Handle a tool call event."""
        tool_name = event.data.get("tool")
        params = event.data.get("params", {})
        context = event.data.get("context", "")
        
        if not tool_name:
            print("⚠️ Tool call event missing 'tool' field")
            return
        
        # Execute tool
        result = self.call_tool(tool_name, params, context)
        
        # Buffer result if important (telemetry, detections)
        if event.data.get("buffer", False):
            self.ddil.store(f"tool_result.{tool_name}", {
                "params": params,
                "result": result,
                "timestamp": time.time()
            })
    
    def call_tool(
        self,
        tool_name: str,
        params: Dict[str, Any],
        context: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Call a tool and capture training data.
        
        Args:
            tool_name: Name of tool to call
            params: Tool parameters
            context: Optional context (user message, situation description)
        
        Returns:
            Tool result dict
        """
        self.tools_called += 1
        
        print(f"🔧 Calling tool: {tool_name}({params})")
        
        # Execute
        result = self.tools.execute(tool_name, params)
        
        # Capture training data
        self.training.capture(
            tool_name=tool_name,
            params=params,
            result=result,
            context=context,
            system_prompt=self.soul.to_system_prompt()
        )
        
        return result
    
    def reason(self, prompt: str, max_turns: int = 10) -> Dict[str, Any]:
        """
        Use reasoning model to process a prompt with autonomous tool calling.
        The agent will loop: LLM → tool calls → results back to LLM → repeat.
        
        Args:
            prompt: User message or situation description
            max_turns: Maximum back-and-forth turns (prevents infinite loops)
        
        Returns:
            Final response dict with content
        """
        # Get tool schemas for LlamaFarm
        tool_schemas = self.tools.to_schema() if len(self.tools) > 0 else None
        system_prompt = self.soul.to_system_prompt()
        
        # Build conversation history
        messages = [{"role": "user", "content": prompt}]
        
        turn = 0
        while turn < max_turns:
            turn += 1
            print(f"\n🔄 Turn {turn}/{max_turns}")
            
            # Call reasoning model
            response = self.model_loader.reason(
                messages=messages,
                tools=tool_schemas,
                system_prompt=system_prompt
            )
            
            # Check if model wants to call tools
            tool_calls = response.get("tool_calls", [])
            
            if not tool_calls:
                # No more tool calls - we're done
                print(f"✅ Agent complete (no more tool calls)")
                return response
            
            # Execute all tool calls
            print(f"🔧 Executing {len(tool_calls)} tool call(s)...")
            
            # Add assistant message with tool calls to history
            messages.append({
                "role": "assistant",
                "content": response.get("content", ""),
                "tool_calls": tool_calls
            })
            
            # Execute each tool and collect results
            for tool_call in tool_calls:
                func = tool_call.get("function", {})
                tool_name = func.get("name")
                tool_params = json.loads(func.get("arguments", "{}"))
                tool_call_id = tool_call.get("id", f"call_{turn}")
                
                # Execute tool
                result = self.call_tool(tool_name, tool_params, context=prompt)
                
                # Add tool result to conversation
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call_id,
                    "name": tool_name,
                    "content": json.dumps(result)
                })
        
        # Max turns reached
        print(f"⚠️ Max turns ({max_turns}) reached")
        return {
            "content": f"[Agent stopped after {max_turns} turns]",
            "error": "max_turns_reached"
        }
    
    def push_event(self, event_type: str, data: Dict[str, Any], priority: float = 0.5):
        """Push an event onto the queue."""
        self.events.push(event_type, data, priority)
    
    def on_exit(self, name: str, check: Callable[[], bool]):
        """
        Register an exit condition.
        
        Example:
            agent.on_exit("battery_low", lambda: agent.custom.get("battery", 100) < 20)
        """
        self.heartbeat.add_exit_condition(name, check)
    
    def on_heartbeat(self, callback: Callable[[], None]):
        """
        Register a heartbeat callback.
        
        Example:
            agent.on_heartbeat(lambda: print("💓 Still alive"))
        """
        self.heartbeat.on_heartbeat(callback)
    
    def shutdown(self, reason: str = "unknown"):
        """Gracefully shutdown the agent."""
        self.running = False
        self.stop_time = time.time()
        self.state = "stopped"
        
        elapsed = self.stop_time - (self.start_time or self.stop_time)
        
        print(f"\n🛑 Shutdown: {reason}")
        print(f"   Runtime: {elapsed:.1f}s")
        print(f"   Events processed: {self.events_processed}")
        print(f"   Tools called: {self.tools_called}")
        print(f"   Heartbeats: {self.heartbeat.beat_count}")
        print(f"   Training data: {self.training.captured_count} samples")
        print(f"   DDIL buffer: {self.ddil.stats()['pending']} pending")
        
        # Final memory log
        self.memory.log_daily(
            f"Agent shutdown: {reason} — "
            f"runtime={elapsed:.1f}s, "
            f"events={self.events_processed}, "
            f"tools={self.tools_called}"
        )
    
    def __repr__(self) -> str:
        return (
            f"Agent(name={self.soul.name!r}, "
            f"state={self.state}, "
            f"tools={len(self.tools)}, "
            f"events={self.events_processed})"
        )
