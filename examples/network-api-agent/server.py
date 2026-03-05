"""
Network API Agent — Web UI Server

Thin FastAPI wrapper around the routing + execution pipeline.
Serves the UI at / and exposes two endpoints:
  POST /chat   { "message": "...", "demo": true }
             → { "tool_call", "api_call", "result", "response", "context_prefix", "timings" }
  GET  /health → { "status", "ur_healthy", "context_prefix" }

Usage:
    python server.py              # live mode
    python server.py --demo       # demo mode (no real devices)
    python server.py --dry-run    # route but don't execute
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
os.chdir(Path(__file__).parent)

from dotenv import load_dotenv
load_dotenv()

import requests as _requests
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn

from openhoof import ToolRouter
from tools import ALL_TOOLS
from context import DeviceContext
from api import NetworkToolExecutor

ENDPOINT     = os.getenv("LLAMAFARM_ENDPOINT", "http://localhost:11540/v1")
ROUTER_MODEL = os.getenv("ROUTER_MODEL", "ft:da674646")
CHUD_URL     = os.getenv("CHUD_URL", "http://localhost:8080")

MUTATION_TOOLS = {
    "router_create_vlan", "router_delete_vlan", "router_update_lan",
    "router_update_wifi_ssid", "router_update_firewall",
    "router_add_static_route", "router_add_dns_host",
    "switch_create_vlan", "switch_delete_vlan",
    "switch_set_vlan_membership", "switch_set_port_pvid",
}

app = FastAPI(title="Network API Agent")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# ── Globals (initialized at startup) ─────────────────────────────────────────

_router: ToolRouter | None = None
_ctx: DeviceContext | None = None
_executor: NetworkToolExecutor | None = None
_demo_mode: bool = False
_dry_run: bool = False


def _init(demo: bool, dry_run: bool):
    global _router, _ctx, _executor, _demo_mode, _dry_run
    _demo_mode = demo
    _dry_run   = dry_run

    _router = ToolRouter(
        endpoint=ENDPOINT,
        model=ROUTER_MODEL,
        temperature=0.0,
        max_tokens=64,
        strip_tool_descriptions=True,
    )

    if demo:
        _ctx = DeviceContext.demo()
        _ctx.refresh()
    else:
        _ctx = DeviceContext(chud_url=CHUD_URL)
        try:
            _ctx.refresh()
        except Exception:
            _ctx = DeviceContext.demo()
            _ctx.refresh()

    _executor = NetworkToolExecutor(chud_url=CHUD_URL) if not dry_run else None


# ── Request / Response models ─────────────────────────────────────────────────

class ChatRequest(BaseModel):
    message: str
    demo: bool = False


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    ur_ok = False
    try:
        r = _requests.get(f"{ENDPOINT.replace('/v1','')}/health", timeout=2)
        ur_ok = r.status_code == 200
    except Exception:
        pass

    return {
        "status": "ok",
        "ur_healthy": ur_ok,
        "model": ROUTER_MODEL,
        "demo_mode": _demo_mode,
        "dry_run": _dry_run,
        "context_prefix": _ctx.prefix if _ctx else "",
    }


@app.post("/chat")
def chat(req: ChatRequest):
    if not _router:
        return JSONResponse({"error": "Server not initialized"}, status_code=503)

    t0 = time.time()

    # Augment with context
    query = _ctx.augment(req.message) if _ctx else req.message
    t_augment = (time.time() - t0) * 1000

    # Route through FunctionGemma
    t_route_start = time.time()
    try:
        route_result = _router.route(query, ALL_TOOLS)
    except Exception as e:
        return JSONResponse({"error": f"Router error: {e}"}, status_code=500)
    t_route = (time.time() - t_route_start) * 1000

    tool_name = route_result.tool_name
    params    = route_result.params

    if not tool_name:
        return {
            "tool_call": None,
            "raw_router": route_result.raw_content,
            "api_call": None,
            "result": None,
            "response": "I didn't understand that. Try rephrasing.",
            "context_prefix": _ctx.prefix if _ctx else "",
            "timings": {"route_ms": round(t_route)},
        }

    params_str = ", ".join(f"{k}={v!r}" for k, v in params.items())
    tool_call_str = f"{tool_name}({params_str})"

    # Map tool → API call description
    api_call_info = _describe_api_call(tool_name, params)

    # Execute
    t_exec_start = time.time()
    result_data  = None
    exec_error   = None

    if _executor and not _dry_run:
        try:
            result_data = _executor.execute(tool_name, params)
        except Exception as e:
            exec_error = str(e)
    t_exec = (time.time() - t_exec_start) * 1000

    # Refresh context on mutations
    if _ctx and tool_name in MUTATION_TOOLS and _executor:
        try:
            _ctx.refresh(force=True)
        except Exception:
            pass

    # Build human-readable response
    response_text = _build_response(tool_name, params, result_data, exec_error)

    return {
        "tool_call": tool_call_str,
        "api_call": api_call_info,
        "result": result_data if result_data is not None else ({"error": exec_error} if exec_error else {"dry_run": True}),
        "response": response_text,
        "context_prefix": _ctx.prefix if _ctx else "",
        "timings": {
            "route_ms":  round(t_route),
            "exec_ms":   round(t_exec),
            "total_ms":  round((time.time() - t0) * 1000),
        },
    }


@app.get("/context/refresh")
def refresh_context():
    if _ctx:
        try:
            _ctx.refresh(force=True)
            return {"ok": True, "prefix": _ctx.prefix}
        except Exception as e:
            return {"ok": False, "error": str(e)}
    return {"ok": False, "error": "No context"}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _describe_api_call(tool_name: str, params: dict) -> dict:
    """Map tool name → human-readable API call description."""
    GET_TOOLS = {
        "router_get_wan_status":      ("GET",  "/api/status",        "wan"),
        "router_get_lan_clients":     ("GET",  "/api/status",        "clients"),
        "router_get_lan_networks":    ("GET",  "/api/status",        "lan"),
        "router_get_wifi_config":     ("GET",  "/api/status",        "wifi"),
        "router_get_vlan_config":     ("GET",  "/api/status",        "vlans"),
        "router_get_routing_table":   ("GET",  "/api/status",        "routes"),
        "router_get_dhcp_leases":     ("GET",  "/api/status",        "dhcp_leases"),
        "router_get_system_status":   ("GET",  "/api/status",        "system"),
        "router_get_system_config":   ("GET",  "/api/status",        "system_config"),
        "router_get_firewall_config": ("GET",  "/api/status",        "firewall"),
        "router_get_logs":            ("GET",  "/api/logs",          None),
        "router_get_lldp_neighbors":  ("GET",  "/api/status",        "lldp"),
        "switch_get_port_status":     ("GET",  "/api/switch/ports",  None),
        "switch_get_port_stats":      ("GET",  "/api/switch/ports",  "stats"),
        "switch_get_vlan_config":     ("GET",  "/api/switch/vlans",  None),
        "switch_get_system_info":     ("GET",  "/api/status",        "switch_system"),
        "router_reboot":              ("POST", "/api/config",        "system.reboot"),
        "switch_reboot":              ("POST", "/api/switch/reboot", None),
        "router_create_vlan":         ("POST", "/api/config",        "vlans.create"),
        "router_delete_vlan":         ("POST", "/api/config",        "vlans.delete"),
        "router_update_lan":          ("POST", "/api/config",        "lan.update"),
        "router_update_wifi_ssid":    ("POST", "/api/config",        "wifi.update"),
        "router_update_firewall":     ("POST", "/api/config",        "firewall.update"),
        "router_add_static_route":    ("POST", "/api/config",        "routes.add"),
        "router_add_dns_host":        ("POST", "/api/config",        "dns.add"),
        "switch_create_vlan":         ("POST", "/api/switch/vlan",   None),
        "switch_delete_vlan":         ("POST", "/api/switch/vlan",   "delete"),
        "switch_set_vlan_membership": ("POST", "/api/switch/vlan",   "membership"),
        "switch_set_port_pvid":       ("POST", "/api/switch/pvid",   None),
    }
    entry = GET_TOOLS.get(tool_name, ("POST", "/api/config", tool_name))
    method, endpoint, section = entry
    body = None
    if method == "POST" and params:
        body = params
    return {"method": method, "endpoint": endpoint, "section": section, "body": body}


def _build_response(tool_name: str, params: dict, result: object, error: str | None) -> str:
    if error:
        return f"Error: {error}"
    if _dry_run or result is None:
        params_str = ", ".join(f"{k}={v!r}" for k, v in params.items())
        return f"[dry-run] Would call: {tool_name}({params_str})"

    # Simple summarizers per tool family
    if tool_name == "router_get_wan_status" and isinstance(result, dict):
        st = result.get("connection_state", result.get("status", "unknown"))
        ip = result.get("ip_address", "")
        return f"WAN is **{st}**{f', IP: {ip}' if ip else ''}."

    if tool_name == "router_get_lan_clients" and isinstance(result, (list, dict)):
        items = result if isinstance(result, list) else result.get("clients", [])
        return f"{len(items)} device{'s' if len(items) != 1 else ''} on the LAN."

    if tool_name == "router_get_wifi_config" and isinstance(result, (list, dict)):
        radios = result if isinstance(result, list) else result.get("radios", [result])
        lines = []
        for r in radios[:4]:
            ssid = r.get("ssid", r.get("bss", {}).get("ssid", "?")) if isinstance(r, dict) else "?"
            enabled = r.get("enabled", True) if isinstance(r, dict) else True
            lines.append(f"{'✅' if enabled else '⬜'} {ssid}")
        return "Radios:\n" + "\n".join(lines)

    if tool_name in ("router_get_vlan_config", "switch_get_vlan_config") and isinstance(result, (list, dict)):
        vlans = result if isinstance(result, list) else result.get("vlans", [])
        names = [f"VLAN {v.get('vid', v.get('id', '?'))}" + (f" ({v.get('name','').strip()})" if v.get('name','').strip() else "") for v in vlans[:6]]
        return ", ".join(names) + ("…" if len(vlans) > 6 else "")

    if tool_name == "router_get_routing_table" and isinstance(result, (list, dict)):
        routes = result if isinstance(result, list) else result.get("routes", [])
        return f"{len(routes)} route{'s' if len(routes) != 1 else ''} in routing table."

    if tool_name == "router_get_dhcp_leases" and isinstance(result, (list, dict)):
        leases = result if isinstance(result, list) else result.get("leases", [])
        return f"{len(leases)} active DHCP lease{'s' if len(leases) != 1 else ''}."

    if tool_name == "router_get_system_status" and isinstance(result, dict):
        cpu = result.get("cpu_percent", result.get("cpu", "?"))
        mem = result.get("mem_percent", result.get("memory", "?"))
        up  = result.get("uptime", "")
        return f"CPU: {cpu}%  Memory: {mem}%" + (f"  Uptime: {up}" if up else "")

    if tool_name in ("switch_get_port_status", "switch_get_port_stats") and isinstance(result, (list, dict)):
        ports = result if isinstance(result, list) else result.get("ports", [])
        up_count = sum(1 for p in ports if p.get("link_state", p.get("state", "")) in ("up", "1", True))
        return f"{up_count}/{len(ports)} ports up."

    if tool_name in ("router_reboot", "switch_reboot"):
        return "Reboot initiated."

    if isinstance(result, dict) and result.get("success"):
        return "Done."

    if isinstance(result, dict) and "error" in result:
        return f"Error: {result['error']}"

    return "Done."


# ── Static UI ─────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
def index():
    return HTML_UI


HTML_UI = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Network Agent</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    background: #0f1117;
    color: #e2e8f0;
    height: 100vh;
    display: flex;
    flex-direction: column;
  }

  /* ── Top bar ── */
  .topbar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 12px 20px;
    background: #1a1d27;
    border-bottom: 1px solid #2d3148;
    flex-shrink: 0;
  }
  .topbar h1 { font-size: 15px; font-weight: 600; color: #a5b4fc; letter-spacing: 0.02em; }
  .badges { display: flex; gap: 8px; align-items: center; }
  .badge {
    font-size: 11px;
    padding: 3px 9px;
    border-radius: 12px;
    font-weight: 500;
    letter-spacing: 0.03em;
  }
  .badge-mode { background: #1e3a5f; color: #60a5fa; }
  .badge-ur   { background: #1a2e1a; color: #4ade80; }
  .badge-ur.down { background: #2e1a1a; color: #f87171; }
  .badge-model { background: #2a1f3d; color: #c084fc; font-family: monospace; font-size: 10px; }

  /* ── Main panels ── */
  .panels {
    display: flex;
    flex: 1;
    overflow: hidden;
    gap: 0;
  }

  /* ── Chat panel ── */
  .chat-panel {
    display: flex;
    flex-direction: column;
    flex: 1;
    min-width: 0;
    border-right: 1px solid #2d3148;
  }
  .chat-messages {
    flex: 1;
    overflow-y: auto;
    padding: 16px;
    display: flex;
    flex-direction: column;
    gap: 12px;
  }
  .msg {
    max-width: 80%;
    padding: 10px 14px;
    border-radius: 12px;
    font-size: 14px;
    line-height: 1.5;
    word-break: break-word;
  }
  .msg-user {
    align-self: flex-end;
    background: #3730a3;
    color: #e0e7ff;
    border-bottom-right-radius: 4px;
  }
  .msg-agent {
    align-self: flex-start;
    background: #1e2235;
    color: #cbd5e1;
    border-bottom-left-radius: 4px;
    border: 1px solid #2d3148;
  }
  .msg-agent strong { color: #94a3b8; font-size: 11px; display: block; margin-bottom: 4px; }
  .msg-typing {
    align-self: flex-start;
    background: #1e2235;
    border: 1px solid #2d3148;
    border-radius: 12px;
    border-bottom-left-radius: 4px;
    padding: 10px 18px;
    color: #64748b;
    font-size: 14px;
  }
  .dot-anim span {
    display: inline-block;
    animation: bounce 1.2s infinite;
    font-size: 18px;
    line-height: 1;
  }
  .dot-anim span:nth-child(2) { animation-delay: 0.2s; }
  .dot-anim span:nth-child(3) { animation-delay: 0.4s; }
  @keyframes bounce {
    0%, 60%, 100% { transform: translateY(0); }
    30% { transform: translateY(-6px); }
  }

  /* ── Input bar ── */
  .input-bar {
    display: flex;
    gap: 8px;
    padding: 12px 16px;
    background: #1a1d27;
    border-top: 1px solid #2d3148;
    flex-shrink: 0;
  }
  .input-bar input {
    flex: 1;
    background: #0f1117;
    border: 1px solid #2d3148;
    border-radius: 8px;
    padding: 10px 14px;
    color: #e2e8f0;
    font-size: 14px;
    outline: none;
    transition: border-color 0.15s;
  }
  .input-bar input:focus { border-color: #6366f1; }
  .input-bar input::placeholder { color: #4a5568; }
  .input-bar button {
    background: #4f46e5;
    color: #fff;
    border: none;
    border-radius: 8px;
    padding: 10px 18px;
    font-size: 14px;
    cursor: pointer;
    transition: background 0.15s;
    font-weight: 500;
  }
  .input-bar button:hover { background: #4338ca; }
  .input-bar button:disabled { background: #2d3148; color: #4a5568; cursor: not-allowed; }

  /* ── Trace panel ── */
  .trace-panel {
    width: 380px;
    flex-shrink: 0;
    display: flex;
    flex-direction: column;
    overflow: hidden;
    background: #0d1018;
  }
  .trace-header {
    padding: 12px 16px;
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.08em;
    color: #4a5568;
    text-transform: uppercase;
    border-bottom: 1px solid #1e2235;
    flex-shrink: 0;
  }
  .trace-body {
    flex: 1;
    overflow-y: auto;
    padding: 14px;
    display: flex;
    flex-direction: column;
    gap: 0;
  }
  .trace-empty {
    color: #374151;
    font-size: 13px;
    text-align: center;
    margin-top: 40px;
  }

  /* ── Trace cards ── */
  .trace-card {
    background: #131620;
    border: 1px solid #1e2538;
    border-radius: 8px;
    padding: 10px 12px;
    margin-bottom: 0;
  }
  .trace-card-label {
    font-size: 10px;
    font-weight: 600;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    margin-bottom: 6px;
    display: flex;
    align-items: center;
    gap: 6px;
  }
  .trace-card-value {
    font-family: "SF Mono", "Fira Code", monospace;
    font-size: 12px;
    color: #94a3b8;
    white-space: pre-wrap;
    word-break: break-all;
  }
  .trace-card-value.highlight { color: #a5f3fc; }
  .trace-card-value.success   { color: #86efac; }
  .trace-card-value.method-get  { color: #60a5fa; }
  .trace-card-value.method-post { color: #fbbf24; }

  .trace-arrow {
    text-align: center;
    color: #2d3148;
    font-size: 11px;
    padding: 3px 0;
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 8px;
  }
  .trace-arrow .timing {
    font-size: 10px;
    color: #374151;
    font-family: monospace;
  }

  /* ── Scrollbars ── */
  ::-webkit-scrollbar { width: 4px; }
  ::-webkit-scrollbar-track { background: transparent; }
  ::-webkit-scrollbar-thumb { background: #2d3148; border-radius: 2px; }

  /* ── Result collapse ── */
  .result-toggle {
    font-size: 10px;
    color: #4a5568;
    cursor: pointer;
    margin-top: 4px;
    display: inline-block;
    user-select: none;
  }
  .result-toggle:hover { color: #6b7280; }
  .result-json {
    display: none;
    margin-top: 6px;
    font-family: monospace;
    font-size: 11px;
    color: #6b7280;
    white-space: pre-wrap;
    word-break: break-all;
    max-height: 180px;
    overflow-y: auto;
  }
  .result-json.open { display: block; }
</style>
</head>
<body>

<div class="topbar">
  <h1>🌐 Network Agent</h1>
  <div class="badges">
    <span class="badge badge-model" id="badge-model">ft:da674646</span>
    <span class="badge badge-mode" id="badge-mode">Demo</span>
    <span class="badge badge-ur" id="badge-ur">UR ●</span>
  </div>
</div>

<div class="panels">

  <!-- Chat -->
  <div class="chat-panel">
    <div class="chat-messages" id="chat-messages">
      <div class="msg msg-agent">
        <strong>Agent</strong>
        Hi! Ask me anything about the network — radios, VLANs, ports, routes, firewall, WAN status…
      </div>
    </div>
    <div class="input-bar">
      <input type="text" id="chat-input" placeholder="switch vlans, wan status, reboot router…" autofocus>
      <button id="send-btn" onclick="sendMessage()">Send</button>
    </div>
  </div>

  <!-- Trace -->
  <div class="trace-panel">
    <div class="trace-header">Trace</div>
    <div class="trace-body" id="trace-body">
      <div class="trace-empty">Send a message to see the trace.</div>
    </div>
  </div>

</div>

<script>
const chatMessages = document.getElementById('chat-messages');
const chatInput    = document.getElementById('chat-input');
const sendBtn      = document.getElementById('send-btn');
const traceBody    = document.getElementById('trace-body');

// ── Health poll ──────────────────────────────────────────────────────────────
async function pollHealth() {
  try {
    const r = await fetch('/health');
    const d = await r.json();
    document.getElementById('badge-ur').textContent   = d.ur_healthy ? 'UR ●' : 'UR ○';
    document.getElementById('badge-ur').className     = 'badge badge-ur' + (d.ur_healthy ? '' : ' down');
    document.getElementById('badge-mode').textContent = d.demo_mode ? 'Demo' : 'Live';
    document.getElementById('badge-model').textContent = (d.model || '').replace('ft:', 'ft:');
  } catch(e) {}
}
pollHealth();
setInterval(pollHealth, 5000);

// ── Send ─────────────────────────────────────────────────────────────────────
chatInput.addEventListener('keydown', e => { if (e.key === 'Enter') sendMessage(); });

async function sendMessage() {
  const text = chatInput.value.trim();
  if (!text) return;

  chatInput.value = '';
  sendBtn.disabled = true;

  appendMsg('user', text);
  const typingEl = appendTyping();
  clearTrace();

  try {
    const resp = await fetch('/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: text }),
    });
    const data = await resp.json();
    typingEl.remove();

    if (data.error) {
      appendMsg('agent', `❌ ${data.error}`);
    } else {
      appendMsg('agent', data.response || 'Done.');
      renderTrace(text, data);
    }
  } catch(e) {
    typingEl.remove();
    appendMsg('agent', `❌ Network error: ${e.message}`);
  }

  sendBtn.disabled = false;
  chatInput.focus();
}

// ── Chat helpers ─────────────────────────────────────────────────────────────
function appendMsg(role, text) {
  const el = document.createElement('div');
  el.className = `msg msg-${role === 'user' ? 'user' : 'agent'}`;
  if (role === 'agent') {
    el.innerHTML = `<strong>Agent</strong>${escHtml(text).replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>').replace(/\n/g, '<br>')}`;
  } else {
    el.textContent = text;
  }
  chatMessages.appendChild(el);
  chatMessages.scrollTop = chatMessages.scrollHeight;
  return el;
}

function appendTyping() {
  const el = document.createElement('div');
  el.className = 'msg-typing dot-anim';
  el.innerHTML = '<span>·</span><span>·</span><span>·</span>';
  chatMessages.appendChild(el);
  chatMessages.scrollTop = chatMessages.scrollHeight;
  return el;
}

// ── Trace helpers ────────────────────────────────────────────────────────────
function clearTrace() {
  traceBody.innerHTML = '<div class="trace-empty">Routing…</div>';
}

function renderTrace(input, data) {
  const { tool_call, api_call, result, timings, context_prefix } = data;

  let html = '';

  // 1. Input
  const displayInput = context_prefix
    ? `<span style="color:#374151">${escHtml(context_prefix)}</span>\n${escHtml(input)}`
    : escHtml(input);
  html += card('📥', 'INPUT', displayInput, '');

  // Arrow + route timing
  html += arrow(timings?.route_ms ? `${timings.route_ms}ms` : '');

  // 2. Router
  const tcClass = tool_call ? 'highlight' : '';
  html += card('🔀', 'ROUTER (FunctionGemma)', tool_call || '(no match)', tcClass);

  // Arrow + exec timing
  if (api_call) {
    html += arrow(timings?.exec_ms ? `${timings.exec_ms}ms` : '');

    // 3. API call
    const methodClass = api_call.method === 'GET' ? 'method-get' : 'method-post';
    let apiText = `${api_call.method} ${api_call.endpoint}`;
    if (api_call.section) apiText += `\nsection: ${api_call.section}`;
    if (api_call.body && Object.keys(api_call.body).length > 0) {
      apiText += `\nbody: ${JSON.stringify(api_call.body, null, 2)}`;
    }
    html += card('🌐', 'API CALL (chud)', apiText, methodClass);

    // Arrow
    html += arrow('');

    // 4. Result
    const resultStr = JSON.stringify(result, null, 2);
    const short = resultStr.length > 120 ? resultStr.slice(0, 120) + '…' : resultStr;
    const resultId = 'r' + Date.now();
    html += `
      <div class="trace-card">
        <div class="trace-card-label"><span>✅</span> RESULT</div>
        <div class="trace-card-value success">${escHtml(short)}</div>
        ${resultStr.length > 120
          ? `<span class="result-toggle" onclick="toggleResult('${resultId}')">▸ expand</span>
             <div class="result-json" id="${resultId}">${escHtml(resultStr)}</div>`
          : ''}
      </div>`;
  }

  traceBody.innerHTML = html;
}

function card(icon, label, value, valueClass) {
  return `
    <div class="trace-card">
      <div class="trace-card-label"><span>${icon}</span> ${label}</div>
      <div class="trace-card-value ${valueClass}">${typeof value === 'string' ? value : escHtml(JSON.stringify(value))}</div>
    </div>`;
}

function arrow(timing) {
  return `<div class="trace-arrow">↓<span class="timing">${timing}</span></div>`;
}

function toggleResult(id) {
  const el = document.getElementById(id);
  const toggle = el.previousElementSibling;
  el.classList.toggle('open');
  toggle.textContent = el.classList.contains('open') ? '▾ collapse' : '▸ expand';
}

function escHtml(s) {
  if (s === null || s === undefined) return '';
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}
</script>
</body>
</html>
"""


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--demo",    action="store_true", help="Demo mode (no real devices)")
    parser.add_argument("--dry-run", action="store_true", help="Route but don't execute")
    parser.add_argument("--port",    type=int, default=8888)
    parser.add_argument("--host",    default="127.0.0.1")
    args = parser.parse_args()

    _init(demo=args.demo, dry_run=args.dry_run)

    mode = "demo" if args.demo else "live"
    print(f"\n  Network Agent UI → http://{args.host}:{args.port}")
    print(f"  Mode: {mode}  |  Model: {ROUTER_MODEL}\n")

    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
