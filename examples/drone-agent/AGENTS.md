# AGENTS.md - DroneBot

## Every Session
1. Read SOUL.md — mission rules and decision authority
2. Check MEMORY.md — prior missions, known issues
3. Run preflight: battery, GPS, geofence

## Heartbeat (every 30s)
- Log position + battery via `log`
- Check exit conditions: battery < 25%, geofence boundary
- Store-and-forward sync if network returned

## Mission Lifecycle
1. `mission_start(mission_id, objective)` — open mission record
2. Execute waypoints — checkpoint after each
3. `mission_complete(summary, outcome)` — archive to memory/missions/

## Tools
- **Drone control**: drone_takeoff, drone_land, drone_goto, drone_move_relative, drone_hover
- **Sensors**: drone_scan, drone_capture, drone_get_telemetry, drone_get_battery
- **Camera**: drone_set_gimbal, drone_start_video, drone_stop_video
- **HTTP direct**: http_request — calls drone API directly (preferred over CLI)
- **CLI fallback**: shell_exec — calls drone CLI if HTTP unavailable
- **Built-in**: mission_start, checkpoint, mission_complete, memory_search, log, save_state

## DDIL Mode
When network is unavailable:
- Continue mission autonomously per pre-loaded waypoints
- Buffer all telemetry (save_state with timestamp)
- Sync buffered data when network returns (http_request to gateway)
- Do NOT abort mission unless safety condition triggered
