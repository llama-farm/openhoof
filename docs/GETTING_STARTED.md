# Getting Started with OpenHoof

<p align="center">
  <img src="openhoof-logo.png" alt="OpenHoof Logo" width="200">
</p>

This guide will get you from zero to running agents in about 5 minutes.

## Prerequisites

Before starting, make sure you have:

- **Python 3.10+** — `python3 --version`
- **Node.js 18+** — `node --version` (for the web UI)
- **LlamaFarm** — Running on `localhost:14345` ([setup guide](https://github.com/llama-farm/llamafarm))

## Step 1: Install OpenHoof

```bash
# Clone the repository
git clone https://github.com/llama-farm/openhoof.git
cd openhoof

# Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install the package
pip install -e .
```

## Step 2: Initialize Your Workspace

```bash
openhoof init
```

This creates `~/.openhoof/` with:
- `config.yaml` — Your configuration
- `agents/` — Where agent workspaces live
- `data/` — Session data and transcripts

## Step 3: Start the Server

```bash
openhoof start
```

You should see:
```
Starting OpenHoof on 0.0.0.0:18765
API: http://localhost:18765/api
Health: http://localhost:18765/api/health
```

Verify it's running:
```bash
curl http://localhost:18765/api/health
# {"status":"healthy","components":{"api":true,"inference":true}}
```

## Step 4: Start the Web UI (Optional)

In a new terminal:
```bash
cd openhoof/ui
npm install
npm run dev
```

Open http://localhost:13456 in your browser.

## Step 5: Create Your First Agent

### Via CLI
```bash
openhoof agents create my-assistant \
  --name "My Assistant" \
  --description "A helpful AI assistant"
```

### Via API
```bash
curl -X POST http://localhost:18765/api/agents \
  -H "Content-Type: application/json" \
  -d '{
    "agent_id": "my-assistant",
    "name": "My Assistant",
    "description": "A helpful AI assistant"
  }'
```

### Via Web UI
1. Go to http://localhost:13456/agents
2. Click "New Agent"
3. Fill in the details and save

## Step 6: Chat with Your Agent

### Via CLI
```bash
openhoof chat my-assistant
# You: Hello!
# Agent: Hello! How can I help you today?
```

### Via API
```bash
curl -X POST http://localhost:18765/api/agents/my-assistant/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Hello!"}'
```

### Via Web UI
1. Go to http://localhost:13456/agents/my-assistant
2. Click "Chat"
3. Start talking!

## Step 7: Customize Your Agent

Navigate to your agent's workspace:
```bash
cd ~/.openhoof/agents/my-assistant/
```

Edit `SOUL.md` to define your agent's personality and capabilities:

```markdown
# SOUL.md

You are a helpful AI assistant named Max.

## Your Personality
- Friendly and approachable
- Clear and concise in explanations
- Always ask clarifying questions when needed

## Your Capabilities
- Answer questions on a wide range of topics
- Help with writing and editing
- Provide recommendations

## Your Limitations
- You cannot access the internet in real-time
- You should not make up information
```

The agent will read this file at the start of each session.

## Next Steps

Now that you have OpenHoof running:

1. **[Create specialized agents](AGENTS.md)** — Build domain-specific assistants
2. **[Set up triggers](TRIGGERS.md)** — Make agents respond to external events
3. **[Add custom tools](TOOLS.md)** — Extend what agents can do
4. **[Connect to your app](../integrations/)** — Integrate with your systems

## Troubleshooting

### "Connection refused" when starting
Make sure no other service is using port 18765:
```bash
lsof -i :18765
# Kill any existing process if needed
```

### "Inference unhealthy" in health check
LlamaFarm isn't reachable. Verify it's running:
```bash
curl http://localhost:14345/health
```

### Agent not responding
Check the logs:
```bash
tail -f ~/.openhoof/data/logs/openhoof.log
```

## Getting Help

- **GitHub Issues**: [github.com/llama-farm/openhoof/issues](https://github.com/llama-farm/openhoof/issues)
- **Documentation**: [docs/](.)
- **Examples**: [examples/](../examples/)
