"""Tests for API endpoints."""

import pytest
from fastapi.testclient import TestClient
from pathlib import Path
import tempfile
import os

# Set up test environment before importing app
os.environ["ATMOSPHERE_HOME"] = tempfile.mkdtemp()

from openhoof.api.app import create_app


@pytest.fixture
def client():
    """Create test client."""
    app = create_app()
    with TestClient(app) as client:
        yield client


def test_health_check(client):
    """Test health endpoint."""
    response = client.get("/api/health")
    
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"


def test_version(client):
    """Test version endpoint."""
    response = client.get("/api/version")
    
    assert response.status_code == 200
    data = response.json()
    assert "version" in data


def test_list_agents_empty(client):
    """Test listing agents when none exist."""
    response = client.get("/api/agents")
    
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)


def test_create_agent(client):
    """Test creating an agent."""
    response = client.post("/api/agents", json={
        "agent_id": "test-agent",
        "name": "Test Agent",
        "description": "A test agent",
    })
    
    assert response.status_code == 200
    data = response.json()
    assert data["agent_id"] == "test-agent"
    assert data["name"] == "Test Agent"


def test_create_duplicate_agent(client):
    """Test creating duplicate agent."""
    # Create first
    client.post("/api/agents", json={
        "agent_id": "duplicate-test",
        "name": "Agent 1",
    })
    
    # Try to create duplicate
    response = client.post("/api/agents", json={
        "agent_id": "duplicate-test",
        "name": "Agent 2",
    })
    
    assert response.status_code == 409


def test_get_agent(client):
    """Test getting agent details."""
    # Create first
    client.post("/api/agents", json={
        "agent_id": "get-test",
        "name": "Get Test",
    })
    
    response = client.get("/api/agents/get-test")
    
    assert response.status_code == 200
    data = response.json()
    assert data["agent_id"] == "get-test"


def test_get_nonexistent_agent(client):
    """Test getting non-existent agent."""
    response = client.get("/api/agents/nonexistent")
    
    assert response.status_code == 404


def test_list_workspace_files(client):
    """Test listing workspace files."""
    # Create agent first
    client.post("/api/agents", json={
        "agent_id": "workspace-test",
        "name": "Workspace Test",
    })
    
    response = client.get("/api/agents/workspace-test/workspace")
    
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert "SOUL.md" in data


def test_get_workspace_file(client):
    """Test getting workspace file content."""
    # Create agent
    client.post("/api/agents", json={
        "agent_id": "file-test",
        "name": "File Test",
    })
    
    response = client.get("/api/agents/file-test/workspace/SOUL.md")
    
    assert response.status_code == 200
    data = response.json()
    assert "content" in data
    assert "File Test" in data["content"]


def test_update_workspace_file(client):
    """Test updating workspace file."""
    # Create agent
    client.post("/api/agents", json={
        "agent_id": "update-test",
        "name": "Update Test",
    })
    
    response = client.put(
        "/api/agents/update-test/workspace/TOOLS.md",
        json={"content": "# Updated Tools"}
    )
    
    assert response.status_code == 200
    
    # Verify update
    get_response = client.get("/api/agents/update-test/workspace/TOOLS.md")
    assert "Updated Tools" in get_response.json()["content"]


def test_activity_feed(client):
    """Test activity feed endpoint."""
    response = client.get("/api/activity")
    
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)


def test_approvals_list(client):
    """Test approvals list endpoint."""
    response = client.get("/api/approvals")
    
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)


def test_delete_agent(client):
    """Test deleting an agent."""
    # Create first
    client.post("/api/agents", json={
        "agent_id": "delete-test",
        "name": "Delete Test",
    })
    
    response = client.delete("/api/agents/delete-test")
    
    assert response.status_code == 200
    
    # Verify deleted
    get_response = client.get("/api/agents/delete-test")
    assert get_response.status_code == 404
