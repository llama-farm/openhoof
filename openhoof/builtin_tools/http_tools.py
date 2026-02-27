"""
HTTP tools for edge agents.

Gives agents the ability to make HTTP requests directly — no CLI required.

Use case split:
- Generic agents     → shell_exec (calls CLI tools, drone CLI, etc.)
- Drone agent        → http_request (calls drone APIs directly over HTTP)
- Any HTTP API       → http_request (REST, webhooks, LlamaFarm, gateway sync)

http_request covers GET, POST, PUT, PATCH, DELETE with JSON or form body,
custom headers, and timeout. Returns parsed JSON when possible.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

try:
    import requests as _requests
    HAVE_REQUESTS = True
except ImportError:
    HAVE_REQUESTS = False


def http_request(
    agent,
    url: str,
    method: str = "GET",
    body: Optional[Dict[str, Any]] = None,
    headers: Optional[Dict[str, str]] = None,
    params: Optional[Dict[str, str]] = None,
    timeout: int = 30,
    parse_json: bool = True,
) -> Dict[str, Any]:
    """
    Make an HTTP request and return the response.

    Use for drone APIs, REST endpoints, webhooks, and gateway sync.
    This is the HTTP-direct path — no shell, no CLI, pure HTTP.

    Examples:
        http_request(url="http://drone.local/api/status")
        http_request(url="http://drone.local/api/goto",
                     method="POST",
                     body={"lat": 45.52, "lon": -122.68, "alt_m": 15})
        http_request(url="https://api.example.com/data",
                     headers={"Authorization": "Bearer token123"})

    Args:
        url:        Full URL to request
        method:     HTTP method (GET, POST, PUT, PATCH, DELETE) — default GET
        body:       Request body as dict (sent as JSON) — default None
        headers:    Additional headers dict — default None
        params:     URL query parameters dict — default None
        timeout:    Max seconds to wait (default 30)
        parse_json: Auto-parse JSON response body (default True)

    Returns:
        {
            "success":     bool,
            "status_code": int,
            "body":        dict | str,   # parsed JSON or raw text
            "headers":     dict,
            "url":         str
        }
    """
    if not HAVE_REQUESTS:
        return {
            "success": False,
            "error": "requests library not installed — pip install requests",
            "url": url,
        }

    method = method.upper()
    req_headers: Dict[str, str] = {"Content-Type": "application/json"}
    if headers:
        req_headers.update(headers)

    try:
        resp = _requests.request(
            method=method,
            url=url,
            json=body,
            headers=req_headers,
            params=params,
            timeout=timeout,
        )

        # Parse response body
        response_body: Any
        if parse_json:
            try:
                response_body = resp.json()
            except (ValueError, _requests.exceptions.JSONDecodeError):
                response_body = resp.text[:4000]  # fallback to truncated text
        else:
            response_body = resp.text[:4000]

        return {
            "success": resp.ok,
            "status_code": resp.status_code,
            "body": response_body,
            "headers": dict(resp.headers),
            "url": resp.url,
        }

    except _requests.exceptions.Timeout:
        return {
            "success": False,
            "status_code": 0,
            "error": f"Request timed out after {timeout}s",
            "url": url,
        }
    except _requests.exceptions.ConnectionError as e:
        return {
            "success": False,
            "status_code": 0,
            "error": f"Connection failed: {e}",
            "url": url,
        }
    except Exception as e:
        return {
            "success": False,
            "status_code": 0,
            "error": str(e),
            "url": url,
        }
