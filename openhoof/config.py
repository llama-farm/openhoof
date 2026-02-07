"""Configuration management for Atmosphere Agents."""

from pathlib import Path
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings
import yaml


class InferenceConfig(BaseModel):
    """Configuration for the inference backend."""
    type: str = "llamafarm"  # llamafarm, openai, ollama
    base_url: str = "http://localhost:14345"
    namespace: str = "atmosphere"
    project: str = "agents"
    default_model: Optional[str] = None
    api_key: Optional[str] = None


class HeartbeatConfig(BaseModel):
    """Global heartbeat configuration."""
    default_interval_seconds: int = 1800  # 30 minutes
    quiet_hours_start: Optional[str] = "23:00"
    quiet_hours_end: Optional[str] = "07:00"


class UIConfig(BaseModel):
    """UI server configuration."""
    enabled: bool = True
    port: int = 13456
    host: str = "0.0.0.0"


class APIConfig(BaseModel):
    """API server configuration."""
    port: int = 18765
    host: str = "0.0.0.0"
    cors_origins: List[str] = ["*"]


class ToolConfig(BaseModel):
    """Tool-specific configuration."""
    notify_requires_approval: bool = True
    exec_allowed: bool = True
    exec_timeout_seconds: int = 30


class Config(BaseModel):
    """Main configuration model."""
    inference: InferenceConfig = Field(default_factory=InferenceConfig)
    heartbeat: HeartbeatConfig = Field(default_factory=HeartbeatConfig)
    ui: UIConfig = Field(default_factory=UIConfig)
    api: APIConfig = Field(default_factory=APIConfig)
    tools: ToolConfig = Field(default_factory=ToolConfig)
    
    autostart_agents: List[str] = Field(default_factory=list)
    domain_pack: Optional[str] = None
    
    @classmethod
    def load(cls, path: Path) -> "Config":
        """Load configuration from YAML file."""
        if not path.exists():
            return cls()
        
        with open(path) as f:
            data = yaml.safe_load(f) or {}
        
        return cls(**data)
    
    def save(self, path: Path) -> None:
        """Save configuration to YAML file."""
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            yaml.dump(self.model_dump(), f, default_flow_style=False)


class Settings(BaseSettings):
    """Environment-based settings."""
    atmosphere_home: Path = Path.home() / ".atmosphere"
    atmosphere_port: int = 18765
    atmosphere_ui_port: int = 13456
    atmosphere_debug: bool = False
    
    # Inference defaults
    llamafarm_url: str = "http://localhost:14345"
    llamafarm_namespace: str = "atmosphere"
    llamafarm_project: str = "agents"
    
    class Config:
        env_prefix = ""
        case_sensitive = False


# Global settings instance
settings = Settings()


def get_config() -> Config:
    """Get the current configuration."""
    config_path = settings.atmosphere_home / "config.yaml"
    return Config.load(config_path)


def get_agents_dir() -> Path:
    """Get the agents directory."""
    return settings.atmosphere_home / "agents"


def get_plugins_dir() -> Path:
    """Get the plugins directory."""
    return settings.atmosphere_home / "plugins"


def get_data_dir() -> Path:
    """Get the data directory."""
    return settings.atmosphere_home / "data"
