"""
Tool executor for Cradlepoint R980 + Netgear GS105Ev2.

Uses the chud dashboard proxy (C binary, webhook server) instead of calling
router/switch APIs directly. chud handles all auth, CSRF, rate limiting,
MD5 challenge-response, and session management.

chud endpoints used:
  GET  /api/status          — bulk fetch all 25 router config+status sections
  POST /api/config          — patch any router config section
  GET  /api/logs            — router system log
  POST /api/switch/ports    — switch port status
  POST /api/switch/vlan     — switch VLAN config/mutation
  POST /api/switch/pvid     — switch port PVID
  POST /api/switch/login    — force re-auth (rare)
  POST /api/provision/move  — move device to VLAN

FunctionGemma routes to tool names. This class executes the calls.
The model never sees chud, auth, or HTTP — just tool_name(params).
"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional


class ChudClient:
    """
    Thin HTTP client for the chud dashboard proxy.

    chud runs as a local C binary (webhook server) that proxies to the
    Cradlepoint router and Netgear switch, handling all auth internally.
    """

    def __init__(self, base_url: str = "http://localhost:8080"):
        import requests
        self.base = base_url.rstrip("/")
        self._session = requests.Session()
        # Cache full status to avoid repeated bulk fetches within a request
        self._status_cache: Optional[Dict] = None

    def _get(self, path: str) -> Any:
        r = self._session.get(f"{self.base}/{path.lstrip('/')}", timeout=15)
        r.raise_for_status()
        return r.json()

    def _post(self, path: str, body: Dict) -> Any:
        r = self._session.post(
            f"{self.base}/{path.lstrip('/')}",
            json=body,
            timeout=15,
        )
        r.raise_for_status()
        try:
            return r.json()
        except Exception:
            return {"success": True, "raw": r.text}

    # ── Router bulk status ────────────────────────────────────────────────────

    def get_all_status(self, fresh: bool = False) -> Dict:
        """GET /api/status — returns all 25 router config+status sections."""
        if self._status_cache is None or fresh:
            self._status_cache = self._get("api/status")
        return self._status_cache

    def get_section(self, section: str, fresh: bool = False) -> Any:
        """Pull one section from the bulk status response."""
        data = self.get_all_status(fresh=fresh)
        return data.get(section, data)

    # ── Router config mutations ───────────────────────────────────────────────

    def config_patch(self, section: str, data: Dict, method: str = "PUT") -> Any:
        """POST /api/config — patch a router config section."""
        self._status_cache = None  # invalidate cache on mutation
        return self._post("api/config", {
            "section": section,
            "data": json.dumps(data),
            "method": method,
        })

    def config_post(self, section: str, data: Dict) -> Any:
        return self.config_patch(section, data, method="POST")

    def config_delete(self, section: str, data: Dict) -> Any:
        return self.config_patch(section, data, method="DELETE")

    # ── Router logs ───────────────────────────────────────────────────────────

    def get_logs(self) -> Any:
        """GET /api/logs — router system log."""
        return self._get("api/logs")

    # ── Switch proxies ────────────────────────────────────────────────────────

    def switch_ports(self) -> Any:
        """GET /api/switch/ports — switch port status."""
        return self._get("api/switch/ports")

    def switch_vlan(self, body: Dict) -> Any:
        """POST /api/switch/vlan — configure switch VLANs."""
        return self._post("api/switch/vlan", body)

    def switch_pvid(self, port: int, vid: int) -> Any:
        """POST /api/switch/pvid — set port PVID."""
        return self._post("api/switch/pvid", {"port": port, "vid": vid})

    def switch_debug(self) -> Any:
        return self._get("api/switch/debug")

    # ── Provisioning ──────────────────────────────────────────────────────────

    def provision(self, body: Dict = {}) -> Any:
        return self._post("api/provision", body)

    def provision_move(self, body: Dict) -> Any:
        return self._post("api/provision/move", body)


# ── Tool executor ─────────────────────────────────────────────────────────────

class NetworkToolExecutor:
    """
    Executes FunctionGemma tool calls via the chud dashboard proxy.

    FunctionGemma returns tool_name(params) → this class maps that to a
    chud API call. All auth, session management, and device complexity is
    handled by chud, not here.

    chud's /api/status returns all 25 sections at once. Status tools
    call get_all_status() once and pluck the relevant section — this is
    faster than 12 individual API calls while keeping tool granularity
    fine enough for FunctionGemma to route accurately.
    """

    def __init__(self, chud_url: str = "http://localhost:8080"):
        self.chud = ChudClient(base_url=chud_url)

    def execute(self, tool_name: str, params: Dict[str, Any]) -> Any:
        """Dispatch a tool call to the appropriate chud handler."""
        handler = getattr(self, f"_tool_{tool_name}", None)
        if not handler:
            return {"error": f"Unknown tool: {tool_name}"}
        try:
            return handler(**params)
        except Exception as e:
            return {"error": str(e)}

    # ── Router status tools — all via /api/status bulk fetch ─────────────────

    def _tool_router_get_lan_clients(self) -> Any:
        return self.chud.get_section("lan/clients")

    def _tool_router_get_lan_networks(self) -> Any:
        return self.chud.get_section("lan")

    def _tool_router_get_wan_status(self) -> Any:
        status = self.chud.get_all_status()
        return {
            "connection_state": status.get("wan/connection_state"),
            "ipinfo":           status.get("wan/ipinfo"),
            "primary_device":   status.get("wan/primary_device"),
        }

    def _tool_router_get_system_status(self) -> Any:
        return self.chud.get_section("system")

    def _tool_router_get_system_config(self) -> Any:
        return self.chud.get_section("config/system")

    def _tool_router_get_dhcp_leases(self) -> Any:
        return self.chud.get_section("dhcpd/leases")

    def _tool_router_get_routing_table(self) -> Any:
        return self.chud.get_section("routing/table")

    def _tool_router_get_firewall_config(self) -> Any:
        return self.chud.get_section("firewall")

    def _tool_router_get_wifi_config(self) -> Any:
        return self.chud.get_section("wlan")

    def _tool_router_get_vlan_config(self) -> Any:
        return self.chud.get_section("vlan")

    def _tool_router_get_lldp_neighbors(self) -> Any:
        return self.chud.get_section("lldp")

    def _tool_router_get_logs(self, level: str = "info") -> Any:
        entries = self.chud.get_logs()
        level_order = ["debug", "info", "warning", "error", "critical"]
        min_idx = level_order.index(level) if level in level_order else 1
        if isinstance(entries, list):
            return [e for e in entries if isinstance(e, list) and len(e) > 1
                    and e[1] in level_order and level_order.index(e[1]) >= min_idx]
        return entries

    # ── Router config mutation tools — all via /api/config POST ───────────────

    def _tool_router_create_vlan(self, vid: int, uid: str, mode: str = "lan") -> Any:
        return self.chud.config_post("vlan", {"vid": vid, "uid": uid, "mode": mode})

    def _tool_router_delete_vlan(self, idx: int) -> Any:
        return self.chud.config_delete(f"vlan/{idx}", {})

    def _tool_router_update_lan(self, idx: int, **kwargs) -> Any:
        update: Dict[str, Any] = {}
        if "ip_address" in kwargs:
            update["ip_address"] = kwargs["ip_address"]
        if "netmask" in kwargs:
            update["netmask"] = kwargs["netmask"]
        if "dhcp_start" in kwargs or "dhcp_end" in kwargs:
            dhcpd: Dict[str, Any] = {}
            if "dhcp_start" in kwargs:
                dhcpd["range_start"] = kwargs["dhcp_start"]
            if "dhcp_end" in kwargs:
                dhcpd["range_end"] = kwargs["dhcp_end"]
            update["dhcpd"] = dhcpd
        return self.chud.config_patch(f"lan/{idx}", update)

    def _tool_router_update_wifi_ssid(
        self, radio_idx: int, bss_idx: int, **kwargs
    ) -> Any:
        update = {k: v for k, v in kwargs.items()
                  if k in ("ssid", "wpapsk", "hidden", "enabled", "authmode")}
        return self.chud.config_patch(f"wlan/radio/{radio_idx}/bss/{bss_idx}", update)

    def _tool_router_update_firewall(self, **kwargs) -> Any:
        update = {k: v for k, v in kwargs.items()
                  if k in ("wan_ping", "anti_spoof")}
        return self.chud.config_patch("firewall", update)

    def _tool_router_reboot(self) -> Any:
        return self.chud.config_patch("system/reboot", {})

    def _tool_router_add_static_route(
        self, ip_network: str, gateway: str, metric: int = 0
    ) -> Any:
        return self.chud.config_post(
            "routing/tables/0/routes",
            {"ip_network": ip_network, "gw": gateway, "metric": metric},
        )

    def _tool_router_add_dns_host(self, hostname: str, ip_address: str) -> Any:
        return self.chud.config_post("dns/hosts", {"hostname": hostname, "ip_address": ip_address})

    # ── Switch tools — all via /api/switch/* ──────────────────────────────────

    def _tool_switch_get_port_status(self) -> Any:
        return self.chud.switch_ports()

    def _tool_switch_get_vlan_config(self) -> Any:
        return self.chud.switch_vlan({"action": "list"})

    def _tool_switch_create_vlan(self, vid: int) -> Any:
        return self.chud.switch_vlan({"action": "create", "vid": vid})

    def _tool_switch_delete_vlan(self, vid: int) -> Any:
        return self.chud.switch_vlan({"action": "delete", "vid": vid})

    def _tool_switch_set_vlan_membership(self, vid: int, port_config: str) -> Any:
        return self.chud.switch_vlan({
            "action":      "membership",
            "vid":         vid,
            "port_config": port_config,
        })

    def _tool_switch_set_port_pvid(self, port: int, vid: int) -> Any:
        return self.chud.switch_pvid(port=port, vid=vid)

    def _tool_switch_get_port_stats(self) -> Any:
        return self.chud.switch_debug()

    def _tool_switch_get_system_info(self) -> Any:
        return self.chud.switch_debug()

    def _tool_switch_reboot(self) -> Any:
        return self.chud.switch_vlan({"action": "reboot"})
