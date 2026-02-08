"""FastAPI application for Atmosphere Agents."""

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional
import logging

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from ..config import get_config, settings, get_agents_dir, get_data_dir
from ..inference import LlamaFarmAdapter
from ..agents import AgentManager
from ..core.events import event_bus
from ..tools import ToolRegistry
from ..tools.builtin import register_builtin_tools

from .dependencies import set_manager
from .routes import agents, chat, activity, approvals, health, triggers, logs, tools, training

logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan - startup and shutdown."""
    
    # Initialize on startup
    config = get_config()
    
    # Ensure directories exist
    agents_dir = get_agents_dir()
    data_dir = get_data_dir()
    agents_dir.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)
    
    # Create inference adapter
    inference = LlamaFarmAdapter(
        base_url=config.inference.base_url,
        namespace=config.inference.namespace,
        project=config.inference.project,
        api_key=config.inference.api_key,
        default_model=config.inference.default_model,
    )
    
    # Create tool registry
    tool_registry = ToolRegistry()
    register_builtin_tools(tool_registry)
    
    # Create agent manager
    manager = AgentManager(
        agents_dir=agents_dir,
        data_dir=data_dir,
        inference=inference,
        tool_registry=tool_registry,
    )
    
    # Set global manager
    set_manager(manager)
    
    # Auto-start configured agents
    for agent_id in config.autostart_agents:
        try:
            await manager.start_agent(agent_id)
            logger.info(f"Auto-started agent: {agent_id}")
        except Exception as e:
            logger.error(f"Failed to auto-start agent {agent_id}: {e}")
    
    logger.info("Atmosphere Agents API started")
    
    yield
    
    # Cleanup on shutdown
    for agent_id in list(manager._agents.keys()):
        await manager.stop_agent(agent_id)
    
    logger.info("Atmosphere Agents API stopped")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="Atmosphere Agents",
        description="A standalone, extensible agentic AI platform",
        version="0.1.0",
        lifespan=lifespan,
    )
    
    # CORS
    config = get_config()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.api.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    # Include routers
    app.include_router(health.router, prefix="/api", tags=["health"])
    app.include_router(agents.router, prefix="/api/agents", tags=["agents"])
    app.include_router(chat.router, prefix="/api/agents", tags=["chat"])
    app.include_router(activity.router, prefix="/api/activity", tags=["activity"])
    app.include_router(approvals.router, prefix="/api/approvals", tags=["approvals"])
    app.include_router(triggers.router, prefix="/api", tags=["triggers"])
    app.include_router(logs.router, prefix="/api", tags=["logs"])
    app.include_router(tools.router, tags=["tools"])
    app.include_router(training.router, tags=["training"])
    
    # WebSocket for real-time events
    @app.websocket("/api/events")
    async def websocket_events(websocket: WebSocket):
        client = await event_bus.connect_websocket(websocket)
        try:
            while True:
                # Keep connection alive, handle incoming commands
                data = await websocket.receive_text()
                # Could handle subscription commands here
        except WebSocketDisconnect:
            await event_bus.disconnect_websocket(client)
    
    return app


# Create default app instance
app = create_app()
