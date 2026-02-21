"""Time tools."""

import time
from datetime import datetime
from typing import Dict, Any


def get_time() -> Dict[str, Any]:
    """
    Get current timestamp and formatted time info.
    """
    now = datetime.now()
    
    return {
        "timestamp": int(time.time()),
        "iso": now.isoformat(),
        "date": now.strftime("%Y-%m-%d"),
        "time": now.strftime("%H:%M:%S"),
        "day_of_week": now.strftime("%A"),
        "timezone": time.tzname[0]
    }
