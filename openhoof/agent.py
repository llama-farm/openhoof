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
        max_turns: int = 10,
        workspace: Optional[str] = None,
        router_confidence_threshold: float = 0.85,
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
            max_turns: Maximum reasoning turns (prevents infinite loops)
            workspace: Working directory (defaults to cwd)
            router_confidence_threshold: Min router confidence to use its normalized params.
                Resolution order (highest priority first):
                  1. This param (explicit override)
                  2. llamafarm.yaml → models.router.confidence_threshold
                  3. Hard default: 0.85
                Can also be changed at runtime: agent.router_confidence_threshold = 0.9
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

        # Router — FunctionGemmaRouter (None when not configured)
        from .router import FunctionGemmaRouter
        router_cfg = self.model_loader.config.get_model_config("router")
        reasoning_cfg = self.model_loader.config.get_model_config("reasoning")
        router_model = router_cfg.get("model", "")
        reasoning_model = reasoning_cfg.get("model", "")
        if router_model and router_model != reasoning_model:
            self.router: Optional[FunctionGemmaRouter] = FunctionGemmaRouter(
                endpoint=self.model_loader.config.endpoint,
                model=router_model,
                confidence_threshold=router_cfg.get("confidence_threshold", 0.85),
            )
        else:
            self.router = None
        
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
        
        # Configuration
        self.max_turns = max_turns

        # Confidence threshold — resolution order:
        #   1. Agent(router_confidence_threshold=X) param (explicit override)
        #   2. llamafarm.yaml router.confidence_threshold
        #   3. Hard default: 0.85
        if router_confidence_threshold != 0.85:
            # Explicit non-default passed in — use it
            self.router_confidence_threshold = router_confidence_threshold
        else:
            # Use config value (may also be 0.85 if not set, that's fine)
            self.router_confidence_threshold = getattr(
                self.model_loader, "config_confidence_threshold", 0.85
            )

        # Custom state (user can attach arbitrary data)
        self.custom: Dict[str, Any] = {}
        
        router_status = (
            f"two-model (threshold={self.router.confidence_threshold})"
            if self.router is not None
            else "single-model"
        )
        print("🐴 MicroClaw Agent initialized")
        print(f"   Soul: {self.soul.name} {self.soul.emoji}")
        print(f"   Memory: {self.memory}")
        print(f"   Tools: {len(self.tools)} registered")
        print(f"   Model: {self.model_loader}")
        print(f"   Orchestration: {router_status}")
        print(f"   Heartbeat: every {heartbeat_interval}s")
        print(f"   Max turns: {max_turns}")
    
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
    
    # ──────────────────────────────────────────────────────────────────────────
    # Two-model orchestration helpers
    # ──────────────────────────────────────────────────────────────────────────

    def _has_router(self) -> bool:
        """True if a FunctionGemmaRouter is configured."""
        return self.router is not None

    def _strip_meta(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Strip internal metadata keys (_by, _confidence, _model) from messages
        before sending to any LLM. Both models see clean OpenAI-format history.
        """
        return [
            {k: v for k, v in msg.items() if not k.startswith("_")}
            for msg in messages
        ]

    def _execute_with_router(
        self,
        tool_call: Dict[str, Any],
        messages: List[Dict[str, Any]],
    ) -> tuple:
        """
        Execute a tool call, optionally routing through FunctionGemma first.

        Single-model mode:  Executes the tool directly with Reasoner's params.
        Two-model mode:     Asks FunctionGemma to validate/normalize params first.
                            High confidence → use FunctionGemma's normalized params.
                            Low confidence  → fall back to Reasoner's params as-is.

        Args:
            tool_call: Tool call dict from Reasoner response
            messages:  Full conversation history (for FunctionGemma context)

        Returns:
            (result_dict, confidence_or_None)
            confidence is None in single-model mode (no router involved)
        """
        func = tool_call.get("function", {})
        tool_name = func.get("name")
        try:
            params = json.loads(func.get("arguments", "{}"))
        except (json.JSONDecodeError, TypeError):
            params = {}

        # ── Single-model mode ─────────────────────────────────────────────────
        if not self._has_router():
            result = self.call_tool(tool_name, params)
            return result, None

        # ── Two-model mode: FunctionGemma validates/normalizes ────────────────
        #
        # Step intent: extract from Reasoner's last assistant message (its thinking),
        # NOT the original user task. Multi-step tasks need per-step intent.
        #
        # Priority: Reasoner's text content → tool name as fallback
        step_intent = next(
            (
                (m.get("content") or "").strip()
                for m in reversed(messages)
                if m.get("role") == "assistant" and (m.get("content") or "").strip()
                and not m.get("tool_calls")  # text-only assistant message = thinking
            ),
            f"Call {tool_name}",  # fallback: at least correct tool name
        ) or f"Call {tool_name} with params: {params}"

        router_result = self.router.validate(
            tool_name=tool_name,
            params=params,
            intent=step_intent,
            tools=self.tools.to_schema() if len(self.tools) > 0 else [],
        )

        # Capture router sample: single-turn intent → tool call (FunctionGemma format)
        self.training.capture_router(
            user_intent=step_intent,
            tool_name=router_result.tool_name if router_result.agreed else tool_name,
            tool_params=router_result.params if router_result.agreed else params,
            confidence=router_result.confidence,
            agreed=router_result.agreed,
        )

        threshold = self.router.confidence_threshold
        if router_result.confidence >= threshold:
            # FunctionGemma validated — use its normalized params
            print(
                f"   🚀 Router: {tool_name} "
                f"(confidence={router_result.confidence:.0%}, "
                f"{'agreed' if router_result.agreed else 'NORMALIZED'})"
            )
            result = self.call_tool(router_result.tool_name, router_result.params)
            return result, router_result.confidence
        else:
            # Low confidence — use Reasoner's params as-is
            print(
                f"   ↩️  Router low confidence ({router_result.confidence:.0%}) "
                f"— using Reasoner params directly"
            )
            result = self.call_tool(tool_name, params)
            return result, 0.0

    def reason(self, prompt: str, max_turns: Optional[int] = None) -> Dict[str, Any]:
        """
        Use reasoning model to process a prompt with autonomous tool calling.
        The agent will loop: LLM → tool calls → results back to LLM → repeat.
        
        Args:
            prompt: User message or situation description
            max_turns: Maximum back-and-forth turns (defaults to agent.max_turns)
        
        Returns:
            Final response dict with content
        """
        tool_schemas = self.tools.to_schema() if len(self.tools) > 0 else None
        system_prompt = self.soul.to_system_prompt()
        max_turns = max_turns if max_turns is not None else self.max_turns

        # Shared message history — both models read from this.
        # Internal metadata (_by, _confidence) stripped before each LLM call.
        messages: List[Dict[str, Any]] = [{"role": "user", "content": prompt}]

        mode = "two-model" if self._has_router() else "single-model"
        print(f"\n🧠 Reasoning [{mode}] — max {max_turns} turns")

        for turn in range(max_turns):
            print(f"\n🔄 Turn {turn + 1}/{max_turns}")

            # ── Step 1: Reasoner decides what to do next ──────────────────────
            response = self.model_loader.reason(
                messages=self._strip_meta(messages),
                tools=tool_schemas,
                system_prompt=system_prompt,
            )

            tool_calls = response.get("tool_calls", [])

            if not tool_calls:
                # Reasoner is done — capture full chain as reasoner training sample
                print("✅ Agent complete")
                messages.append({
                    "role": "assistant",
                    "content": response.get("content", ""),
                })
                self.training.capture_reasoner(
                    messages=self._strip_meta(messages),
                    system_prompt=self.soul.to_system_prompt(),
                )
                return response

            # Record Reasoner's decision in shared history (with metadata).
            # Use None (not "") for content when tool_calls are present — some
            # runtimes (incl. Universal Runtime) behave differently with empty
            # string vs null content alongside tool_calls.
            assistant_content = response.get("content") or None
            messages.append({
                "role": "assistant",
                "content": assistant_content,
                "tool_calls": tool_calls,
                "_by": "reasoner",
            })

            print(f"🔧 {len(tool_calls)} tool call(s) — "
                  f"{'validating via router' if self._has_router() else 'executing directly'}")

            # ── Step 2: Execute each tool (router validates if available) ──────
            for tool_call in tool_calls:
                result, confidence = self._execute_with_router(tool_call, messages)

                tool_call_id = tool_call.get("id", f"call_{turn}")
                tool_name = tool_call.get("function", {}).get("name", "unknown")

                # Record result in shared history (confidence metadata for training)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call_id,
                    "name": tool_name,
                    "content": json.dumps(result),
                    **({"_confidence": confidence} if confidence is not None else {}),
                })

        print(f"⚠️ Max turns ({max_turns}) reached")
        return {
            "content": f"[Agent stopped after {max_turns} turns]",
            "error": "max_turns_reached",
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
