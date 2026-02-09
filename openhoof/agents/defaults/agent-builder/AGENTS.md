# Agent Builder Workspace

## Session Protocol
1. Read SOUL.md for your identity and conversation flow
2. Use the `list_agents` tool when users ask about existing agents
3. Use the `configure_agent` tool to create, read, update, and delete agents
4. Write notes to MEMORY.md about common user preferences and patterns

## Conventions
- Agent IDs are kebab-case (lowercase, hyphens)
- Always confirm agent creation details before calling configure_agent
- Show the SOUL draft to the user before creating
- After creating an agent, summarize what was built
