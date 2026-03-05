"""
HTTP clients for Cradlepoint R980 and Netgear GS105Ev2.

These handle all auth, session management, rate limiting, and response parsing.
The FunctionGemma model never sees any of this — it just picks tool names and params.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
import urllib.parse
from typing import Any, Dict, Optional, Tuple


# ── Cradlepoint R980 ──────────────────────────────────────────────────────────

class CradlepointSession:
    """
    Authenticated session for the Cradlepoint R980 HTTPS API.

    Auth: form-based login (NEVER use HTTP Basic — triggers PCI-DSS lockout).
    State: maintains session cookies + XSRF token automatically.
    Rate limiting: enforces per-operation intervals from the API reference.
    """

    # Rate limits from API reference (ms between calls)
    _GET_INTERVAL    = 0.25   # 250ms between GETs
    _MUTATE_INTERVAL = 0.50   # 500ms between PUT/POST/DELETE
    _POST_DEL_COOLDOWN = 1.0  # 1s cooldown after POST/DELETE (array restructuring)

    def __init__(self, host: str, username: str, password: str, verify_ssl: bool = False):
        import requests
        self.base = f"https://{host}"
        self.username = username
        self.password = password
        self.verify_ssl = verify_ssl
        self._session = requests.Session()
        self._session.verify = verify_ssl
        self._xsrf: Optional[str] = None
        self._authenticated = False
        self._last_call = 0.0

    def login(self) -> None:
        """Form-based login. Sets session cookies and XSRF token."""
        # POST to login endpoint
        encoded_pass = urllib.parse.quote(self.password, safe="")
        self._session.post(
            f"{self.base}/login/",
            data=f"cprouterusername={self.username}&cprouterpassword={encoded_pass}",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            allow_redirects=True,
        )
        # Follow redirect to /admin/ to get _xsrf cookie
        self._session.get(f"{self.base}/admin/")
        xsrf = self._session.cookies.get("_xsrf")
        if not xsrf:
            raise RuntimeError("Login failed — no _xsrf cookie received")
        self._xsrf = xsrf
        self._authenticated = True

    def _ensure_auth(self) -> None:
        if not self._authenticated:
            self.login()

    def _rate_limit(self, interval: float) -> None:
        elapsed = time.time() - self._last_call
        if elapsed < interval:
            time.sleep(interval - elapsed)
        self._last_call = time.time()

    def _headers(self) -> Dict[str, str]:
        return {
            "X-Requested-With": "XMLHttpRequest",
            "X-CSRFToken": self._xsrf or "",
        }

    def _check(self, resp) -> Any:
        """Parse response envelope. Re-auth on 302, raise on success=false."""
        if resp.status_code == 302 or "/login/" in resp.url:
            self._authenticated = False
            raise RuntimeError("Session expired — re-login required")
        data = resp.json()
        if not data.get("success"):
            raise RuntimeError(f"API error: {data.get('data', data)}")
        return data.get("data")

    def get(self, path: str) -> Any:
        self._ensure_auth()
        self._rate_limit(self._GET_INTERVAL)
        r = self._session.get(
            f"{self.base}/api/{path.lstrip('/')}",
            headers=self._headers(),
        )
        return self._check(r)

    def put(self, path: str, data: Dict) -> Any:
        self._ensure_auth()
        self._rate_limit(self._MUTATE_INTERVAL)
        encoded = urllib.parse.urlencode({"data": json.dumps(data)})
        r = self._session.put(
            f"{self.base}/api/{path.lstrip('/')}",
            data=encoded,
            headers={
                **self._headers(),
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            },
        )
        return self._check(r)

    def post(self, path: str, data: Dict) -> Any:
        self._ensure_auth()
        self._rate_limit(self._MUTATE_INTERVAL)
        encoded = urllib.parse.urlencode({"data": json.dumps(data)})
        r = self._session.post(
            f"{self.base}/api/{path.lstrip('/')}",
            data=encoded,
            headers={
                **self._headers(),
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            },
        )
        result = self._check(r)
        time.sleep(self._POST_DEL_COOLDOWN)  # array restructuring cooldown
        return result

    def delete(self, path: str) -> Any:
        self._ensure_auth()
        self._rate_limit(self._MUTATE_INTERVAL)
        r = self._session.delete(
            f"{self.base}/api/{path.lstrip('/')}",
            headers=self._headers(),
        )
        result = self._check(r)
        time.sleep(self._POST_DEL_COOLDOWN)
        return result


# ── Netgear GS105Ev2 ──────────────────────────────────────────────────────────

class NetgearSession:
    """
    Authenticated session for the Netgear GS105Ev2 HTTP CGI API (Tier 3).

    Auth: MD5 challenge-response (interleaved password + nonce).
    CSRF: hash token required in all config POSTs; rotates every response.
    Session limit: 1 concurrent session — logs out any stale session first.
    Rate limiting: 750ms between CGI calls; 3-5s after provisioning ops.
    """

    _CALL_INTERVAL    = 0.75   # 750ms between CGI calls
    _PROVISION_COOLDOWN = 4.0  # 4s after provisioning ops

    def __init__(self, host: str, password: str):
        import requests
        self.base = f"http://{host}"
        self.password = password[:20]  # switch truncates to 20 chars
        self._session = requests.Session()
        self._hash: Optional[str] = None
        self._authenticated = False
        self._last_call = 0.0

    def login(self) -> None:
        """MD5 challenge-response login."""
        # Clear any stale session
        try:
            self._session.get(f"{self.base}/logout.cgi", timeout=5)
        except Exception:
            pass

        # Get nonce
        r = self._session.get(f"{self.base}/login.cgi")
        m = re.search(r'id="rand"[^>]*value="([^"]+)"', r.text)
        if not m:
            raise RuntimeError("Could not extract nonce from login page")
        rand = m.group(1)

        # Compute MD5(interleave(password, rand))
        merged = self._interleave(self.password, rand)
        md5_hash = hashlib.md5(merged.encode()).hexdigest()

        # Submit
        r = self._session.post(
            f"{self.base}/login.cgi",
            data=f"password={md5_hash}",
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Referer": f"{self.base}/login.cgi",
            },
        )
        if "SID" not in self._session.cookies:
            raise RuntimeError("Switch login failed — no SID cookie")
        self._authenticated = True

        # Get initial hash token
        self._refresh_hash()

    @staticmethod
    def _interleave(password: str, rand: str) -> str:
        result = ""
        i1 = i2 = 0
        while i1 < len(password) or i2 < len(rand):
            if i1 < len(password):
                result += password[i1]; i1 += 1
            if i2 < len(rand):
                result += rand[i2]; i2 += 1
        return result

    def _refresh_hash(self) -> None:
        """Fetch the current CSRF hash token from a config page."""
        r = self._session.get(
            f"{self.base}/8021qCf.cgi",
            headers={"Referer": f"{self.base}/index.cgi"},
        )
        m = re.search(r'id="hash"[^>]*value="([^"]+)"', r.text)
        if m:
            self._hash = m.group(1)

    def _ensure_auth(self) -> None:
        if not self._authenticated:
            self.login()

    def _rate_limit(self) -> None:
        elapsed = time.time() - self._last_call
        if elapsed < self._CALL_INTERVAL:
            time.sleep(self._CALL_INTERVAL - elapsed)
        self._last_call = time.time()

    def _referer_headers(self) -> Dict[str, str]:
        return {"Referer": f"{self.base}/index.cgi"}

    def _extract_hash(self, html: str) -> Optional[str]:
        m = re.search(r'id="hash"[^>]*value="([^"]+)"', html)
        return m.group(1) if m else None

    def get(self, path: str) -> str:
        """GET a CGI endpoint. Returns raw HTML (caller parses as needed)."""
        self._ensure_auth()
        self._rate_limit()
        r = self._session.get(
            f"{self.base}/{path.lstrip('/')}",
            headers=self._referer_headers(),
        )
        # Update hash from response
        new_hash = self._extract_hash(r.text)
        if new_hash:
            self._hash = new_hash
        return r.text

    def post(self, path: str, data: Dict[str, Any], provision: bool = False) -> str:
        """POST to a CGI endpoint with CSRF hash. Returns raw HTML response."""
        self._ensure_auth()
        self._rate_limit()
        post_data = {**data, "hash": self._hash}
        r = self._session.post(
            f"{self.base}/{path.lstrip('/')}",
            data=post_data,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                **self._referer_headers(),
            },
        )
        new_hash = self._extract_hash(r.text)
        if new_hash:
            self._hash = new_hash
        if provision:
            time.sleep(self._PROVISION_COOLDOWN)
        return r.text


# ── Tool executor ─────────────────────────────────────────────────────────────

class NetworkToolExecutor:
    """
    Executes tool calls against the real Cradlepoint + Netgear APIs.

    FunctionGemma returns tool_name(params) → this class runs the actual HTTP calls.
    Session state (auth, cookies, CSRF) is managed here, not by the model.
    """

    def __init__(
        self,
        router: Optional[CradlepointSession] = None,
        switch: Optional[NetgearSession] = None,
    ):
        self.router = router
        self.switch = switch

    def execute(self, tool_name: str, params: Dict[str, Any]) -> Any:
        """Dispatch a tool call to the appropriate API handler."""
        handler = getattr(self, f"_tool_{tool_name}", None)
        if not handler:
            return {"error": f"Unknown tool: {tool_name}"}
        try:
            return handler(**params)
        except RuntimeError as e:
            return {"error": str(e)}

    # ── Router status tools ───────────────────────────────────────────────────

    def _tool_router_get_lan_clients(self) -> Any:
        return self.router.get("status/lan/clients/")

    def _tool_router_get_lan_networks(self) -> Any:
        return self.router.get("config/lan/")

    def _tool_router_get_wan_status(self) -> Any:
        return {
            "connection_state": self.router.get("status/wan/connection_state/"),
            "ipinfo": self.router.get("status/wan/ipinfo/"),
            "primary_device": self.router.get("status/wan/primary_device/"),
        }

    def _tool_router_get_system_status(self) -> Any:
        return self.router.get("status/system/")

    def _tool_router_get_system_config(self) -> Any:
        return self.router.get("config/system/")

    def _tool_router_get_dhcp_leases(self) -> Any:
        return self.router.get("status/dhcpd/leases/")

    def _tool_router_get_routing_table(self) -> Any:
        return self.router.get("status/routing/table/")

    def _tool_router_get_firewall_config(self) -> Any:
        return self.router.get("config/firewall/")

    def _tool_router_get_wifi_config(self) -> Any:
        return self.router.get("config/wlan/")

    def _tool_router_get_vlan_config(self) -> Any:
        return self.router.get("config/vlan/")

    def _tool_router_get_lldp_neighbors(self) -> Any:
        return self.router.get("status/lldp/")

    def _tool_router_get_logs(self, level: str = "info") -> Any:
        entries = self.router.get("status/log/")
        level_order = ["debug", "info", "warning", "error", "critical"]
        min_idx = level_order.index(level) if level in level_order else 1
        return [
            e for e in entries
            if isinstance(e, list) and len(e) > 1
            and level_order.index(e[1]) >= min_idx
            if e[1] in level_order
        ]

    # ── Router config mutation tools ──────────────────────────────────────────

    def _tool_router_create_vlan(self, vid: int, uid: str, mode: str = "lan") -> Any:
        return self.router.post("config/vlan/", {"vid": vid, "uid": uid, "mode": mode})

    def _tool_router_delete_vlan(self, idx: int) -> Any:
        return self.router.delete(f"config/vlan/{idx}/")

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
        return self.router.put(f"config/lan/{idx}/", update)

    def _tool_router_update_wifi_ssid(
        self, radio_idx: int, bss_idx: int, **kwargs
    ) -> Any:
        update = {k: v for k, v in kwargs.items()
                  if k in ("ssid", "wpapsk", "hidden", "enabled", "authmode")}
        return self.router.put(f"config/wlan/radio/{radio_idx}/bss/{bss_idx}/", update)

    def _tool_router_update_firewall(self, **kwargs) -> Any:
        update = {k: v for k, v in kwargs.items()
                  if k in ("wan_ping", "anti_spoof")}
        return self.router.put("config/firewall/", update)

    def _tool_router_reboot(self) -> Any:
        return self.router.put("control/system/reboot", {})

    def _tool_router_add_static_route(
        self, ip_network: str, gateway: str, metric: int = 0
    ) -> Any:
        # Find the main routing table index
        tables = self.router.get("config/routing/tables/")
        main_idx = next(
            (i for i, t in enumerate(tables) if t.get("name") == "main"), 0
        )
        return self.router.post(
            f"config/routing/tables/{main_idx}/routes/",
            {"ip_network": ip_network, "gw": gateway, "metric": metric},
        )

    def _tool_router_add_dns_host(self, hostname: str, ip_address: str) -> Any:
        return self.router.post("config/dns/hosts/", {"hostname": hostname, "ip_address": ip_address})

    # ── Switch tools ──────────────────────────────────────────────────────────

    def _tool_switch_get_port_status(self) -> Any:
        html = self.switch.get("status.cgi")
        # Parse port link state from HTML table
        ports = []
        for m in re.finditer(
            r'<tr class="portID">(.*?)</tr>', html, re.DOTALL
        ):
            row = m.group(1)
            vals = re.findall(r'<td[^>]*>(.*?)</td>', row, re.DOTALL)
            if len(vals) >= 3:
                ports.append({
                    "port": len(ports) + 1,
                    "link": vals[0].strip(),
                    "speed": vals[1].strip() if len(vals) > 1 else "",
                })
        return ports

    def _tool_switch_get_vlan_config(self) -> Any:
        html = self.switch.get("8021qCf.cgi")
        vlans = []
        for m in re.finditer(r'vlanck\d+.*?value="(\d+)"', html):
            vlans.append({"vid": int(m.group(1))})
        return vlans

    def _tool_switch_create_vlan(self, vid: int) -> Any:
        self.switch.post("8021qCf.cgi", {
            "ACTION": "Add",
            "ADD_VLANID": str(vid),
            "status": "Enable",
        }, provision=True)
        return {"success": True, "vid": vid}

    def _tool_switch_delete_vlan(self, vid: int) -> Any:
        # Get sorted VLAN list to find index
        html = self.switch.get("8021qCf.cgi")
        vids = [int(m.group(1)) for m in re.finditer(r'value="(\d+)".*?vlan', html)]
        vids_sorted = sorted(set(vids))
        if vid not in vids_sorted:
            return {"error": f"VLAN {vid} not found"}
        idx = vids_sorted.index(vid)
        self.switch.post("8021qCf.cgi", {
            "ACTION": "Delete",
            f"vlanck{idx}": str(vid),
            "status": "Enable",
        }, provision=True)
        return {"success": True, "vid": vid}

    def _tool_switch_set_vlan_membership(self, vid: int, port_config: str) -> Any:
        # Step 1: Switch to target VLAN
        r1 = self.switch.post("8021qMembe.cgi", {"VLAN_ID": str(vid)})
        new_hash = re.search(r'id="hash"[^>]*value="([^"]+)"', r1)
        # Step 2: Save membership (hash auto-updated in session)
        self.switch.post("8021qMembe.cgi", {
            "VLAN_ID": str(vid),
            "VLAN_ID_HD": str(vid),
            "hiddenMem": port_config,
        }, provision=True)
        return {"success": True, "vid": vid, "port_config": port_config}

    def _tool_switch_set_port_pvid(self, port: int, vid: int) -> Any:
        # port is 1-indexed to the user, 0-indexed in API
        self.switch.post("portPVID.cgi", {
            f"port{port - 1}": "checked",
            "pvid": str(vid),
        })
        return {"success": True, "port": port, "pvid": vid}

    def _tool_switch_get_port_stats(self) -> Any:
        html = self.switch.get("portStatistics.cgi")
        stats = []
        for i, m in enumerate(re.finditer(
            r'<tr class="portID">(.*?)</tr>', html, re.DOTALL
        )):
            vals = re.findall(r'<input[^>]*value="(\d+)"', m.group(1))
            if len(vals) >= 4:
                rx_turnover, rx_cur = int(vals[0]), int(vals[1])
                tx_turnover, tx_cur = int(vals[2]), int(vals[3])
                stats.append({
                    "port": i + 1,
                    "rx_bytes": rx_turnover * (2 ** 32) + rx_cur,
                    "tx_bytes": tx_turnover * (2 ** 32) + tx_cur,
                })
        return stats

    def _tool_switch_get_system_info(self) -> Any:
        html = self.switch.get("switch_info.cgi")
        info: Dict[str, str] = {}
        for field, pattern in [
            ("name",     r'id="switch_name"[^>]*value="([^"]+)"'),
            ("firmware", r'firmware[^<]*<td[^>]*>([^<]+)</td>'),
            ("mac",      r'MAC[^<]*<td[^>]*>([^<]+)</td>'),
        ]:
            m = re.search(pattern, html, re.IGNORECASE)
            if m:
                info[field] = m.group(1).strip()
        return info

    def _tool_switch_reboot(self) -> Any:
        self.switch.post("device_reboot.cgi", {"CBox": "on"})
        return {"success": True, "message": "Switch rebooting"}
