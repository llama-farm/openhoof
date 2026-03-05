# AGENTS.md - Support Agent

## Every Session
- `memory_search` for similar past tickets before answering
- Check account status before diagnosing product issues
- Always log the outcome of each support interaction

## Ticket Workflow
1. `create_ticket` — open a record at start of new issue
2. Work the issue using available tools
3. `update_ticket` with resolution steps taken
4. `close_ticket` when resolved, or `escalate_ticket` when needed

## Tools
- `lookup_account(email)` — account status, plan, recent activity
- `search_kb(query)` — search knowledge base articles
- `create_ticket(email, subject, description)` — open support ticket
- `update_ticket(ticket_id, note)` — add a note to the ticket
- `close_ticket(ticket_id, resolution)` — resolve and close
- `escalate_ticket(ticket_id, reason)` — hand off to human agent
- `memory_search(query)` — search prior session notes
- `log(message)` — log session milestones
