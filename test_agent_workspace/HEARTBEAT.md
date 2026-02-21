# HEARTBEAT.md

Keep this SHORT to avoid token burn.

## Every Heartbeat

1. Check battery → Exit if < 20%
2. Check scheduled wakeups → Execute if due
3. Check DDIL buffer → Sync if network available
4. Review exit conditions → Trigger if met

If nothing needs attention: `HEARTBEAT_OK`
