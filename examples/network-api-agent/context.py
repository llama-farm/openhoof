"""
Device context builder.

Calls /api/status (chud bulk fetch) and formats the result into a compact
prefix that gets prepended to the user's message before FunctionGemma routing.

Format goal: ~30-60 tokens, enough for the model to resolve ambiguous references
("radio 2", "port 3", "guest vlan") without burying the actual intent.

Example output:
  [radios: r0=HomeNet/2.4G/8cl r1=HomeNet_5G/5G/2cl r2=Guest/2.4G/OFF r3=IoT/5G/4cl]
  [vlans: 1=default 10=mgmt 20=data 100=guest]
  [ports: p1=up/1G/v10 p2=up/100M/v20 p3=down p4=up/trunk p5=up/trunk]
  [clients: 14]

Usage:
    ctx = DeviceContext(chud_url="http://localhost:8080")
    prefix = ctx.refresh()           # fetches live status
    full_query = ctx.augment(user_input)   # prepends context

Demo mode (no real devices):
    ctx = DeviceContext.demo()
    prefix = ctx.refresh()
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional


# ── Demo fixture ─────────────────────────────────────────────────────────────
# Realistic /api/status response for demo/testing without real devices.
# Mirrors what chud returns from the Cradlepoint R980 + Netgear GS105Ev2.

DEMO_STATUS = {
    # WiFi radios (wlan section from Cradlepoint)
    "wlan": {
        "radio": [
            {
                "radio_id": 0,
                "frequency": "2.4GHz",
                "channel": 6,
                "bss": [
                    {
                        "ssid": "HomeNet",
                        "enabled": True,
                        "wpapsk": "***",
                        "authmode": "wpa2",
                        "hidden": False,
                        "mac": "aa:bb:cc:dd:ee:00",
                    }
                ],
            },
            {
                "radio_id": 1,
                "frequency": "5GHz",
                "channel": 36,
                "bss": [
                    {
                        "ssid": "HomeNet_5G",
                        "enabled": True,
                        "wpapsk": "***",
                        "authmode": "wpa2",
                        "hidden": False,
                        "mac": "aa:bb:cc:dd:ee:01",
                    }
                ],
            },
            {
                "radio_id": 2,
                "frequency": "2.4GHz",
                "channel": 11,
                "bss": [
                    {
                        "ssid": "Guest",
                        "enabled": False,
                        "wpapsk": "***",
                        "authmode": "wpa2",
                        "hidden": False,
                        "mac": "aa:bb:cc:dd:ee:02",
                    }
                ],
            },
            {
                "radio_id": 3,
                "frequency": "5GHz",
                "channel": 149,
                "bss": [
                    {
                        "ssid": "IoT_Net",
                        "enabled": True,
                        "wpapsk": "***",
                        "authmode": "wpa2",
                        "hidden": False,
                        "mac": "aa:bb:cc:dd:ee:03",
                    }
                ],
            },
        ]
    },

    # VLANs
    "vlan": [
        {"vid": 1,   "uid": "default", "mode": "lan"},
        {"vid": 10,  "uid": "mgmt",    "mode": "lan"},
        {"vid": 20,  "uid": "data",    "mode": "lan"},
        {"vid": 100, "uid": "guest",   "mode": "lan"},
        {"vid": 200, "uid": "iot",     "mode": "lan"},
    ],

    # LAN clients
    "lan/clients": [
        {"mac": "aa:bb:cc:01:00:01", "ip": "192.168.0.10", "hostname": "MacBook-Pro",  "interface": "wlan0"},
        {"mac": "aa:bb:cc:01:00:02", "ip": "192.168.0.11", "hostname": "iPhone-14",    "interface": "wlan0"},
        {"mac": "aa:bb:cc:01:00:03", "ip": "192.168.0.12", "hostname": "iPad",         "interface": "wlan1"},
        {"mac": "aa:bb:cc:01:00:04", "ip": "192.168.0.13", "hostname": "SmartTV",      "interface": "wlan0"},
        {"mac": "aa:bb:cc:01:00:05", "ip": "192.168.0.14", "hostname": "Roku",         "interface": "wlan0"},
        {"mac": "aa:bb:cc:01:00:06", "ip": "192.168.0.20", "hostname": "NAS",          "interface": "eth0"},
        {"mac": "aa:bb:cc:01:00:07", "ip": "192.168.0.21", "hostname": "RaspberryPi",  "interface": "eth0"},
        {"mac": "aa:bb:cc:01:00:08", "ip": "192.168.0.30", "hostname": "Printer",      "interface": "wlan0"},
    ],

    # WAN
    "wan/connection_state": "connected",
    "wan/ipinfo": {
        "ip_address": "203.0.113.42",
        "gateway":    "203.0.113.1",
        "dns": ["8.8.8.8", "8.8.4.4"],
    },
    "wan/primary_device": {
        "type":   "ethernet",
        "name":   "wan0",
        "signal": -65,
    },

    # System
    "system": {
        "uptime":  172800,
        "cpu":     12,
        "mem_used": 38,
        "mem_total": 256,
        "fw_version": "7.24.10",
    },

    # Firewall
    "firewall": {
        "wan_ping":   False,
        "anti_spoof": True,
        "alg_sip":    True,
    },

    # Switch ports (from chud /api/switch/ports)
    "switch/ports": [
        {"port": 1, "link": "up",   "speed": "1000Mbps", "pvid": 10,  "tagged_vlans": []},
        {"port": 2, "link": "up",   "speed": "100Mbps",  "pvid": 20,  "tagged_vlans": []},
        {"port": 3, "link": "down", "speed": None,        "pvid": 1,   "tagged_vlans": []},
        {"port": 4, "link": "up",   "speed": "1000Mbps", "pvid": 1,   "tagged_vlans": [10, 20, 100]},
        {"port": 5, "link": "up",   "speed": "1000Mbps", "pvid": 1,   "tagged_vlans": [10, 20, 100]},
    ],
}


# ── Context formatter ─────────────────────────────────────────────────────────

class DeviceContext:
    """
    Fetches /api/status and formats a compact context prefix.

    The prefix is prepended to every user message before FunctionGemma routing.
    This lets the model resolve references like "radio 2" or "port 3" correctly
    without needing the user to specify indices.
    """

    def __init__(self, chud_url: str = "http://localhost:8080", demo: bool = False):
        self.chud_url = chud_url.rstrip("/")
        self._demo = demo
        self._status: Optional[Dict] = None
        self._prefix: str = ""

    @classmethod
    def demo(cls) -> "DeviceContext":
        """Return a context instance pre-loaded with demo fixture data."""
        ctx = cls(demo=True)
        ctx._status = DEMO_STATUS
        ctx._prefix = ctx._build_prefix(DEMO_STATUS)
        return ctx

    def refresh(self, force: bool = False) -> str:
        """Fetch /api/status and rebuild the context prefix. Returns the prefix string."""
        if self._demo:
            self._status = DEMO_STATUS
        elif self._status is None or force:
            import requests
            r = requests.get(f"{self.chud_url}/api/status", timeout=10)
            r.raise_for_status()
            self._status = r.json()
        self._prefix = self._build_prefix(self._status)
        return self._prefix

    @property
    def prefix(self) -> str:
        return self._prefix

    @property
    def status(self) -> Optional[Dict]:
        return self._status

    def augment(self, user_input: str) -> str:
        """
        Prepend the context prefix to a user message.

        If no context has been fetched yet, returns the message unchanged.
        If the message already contains a [context] prefix (e.g. from a retry),
        it is replaced with the current prefix.
        """
        if not self._prefix:
            return user_input
        # Strip any existing context prefix
        clean = user_input
        if user_input.startswith("["):
            bracket_end = user_input.find("] ")
            if bracket_end > 0:
                clean = user_input[bracket_end + 2:]
        return f"{self._prefix} {clean}"

    # ── Prefix builder ────────────────────────────────────────────────────────

    @staticmethod
    def _build_prefix(status: Dict) -> str:
        """
        Convert bulk status dict to a compact context string (~40-60 tokens).

        Format:
          [radios: r0=SSID/freq/Ncl ...]
          [vlans: ID=name ...]
          [ports: pN=state/speed/pvid ...]
          [clients: N]
        """
        parts = []

        # Radios
        radios = DeviceContext._extract_radios(status)
        if radios:
            parts.append("[radios: " + " ".join(radios) + "]")

        # VLANs
        vlans = DeviceContext._extract_vlans(status)
        if vlans:
            parts.append("[vlans: " + " ".join(vlans) + "]")

        # Switch ports
        ports = DeviceContext._extract_ports(status)
        if ports:
            parts.append("[ports: " + " ".join(ports) + "]")

        # Client count
        clients = status.get("lan/clients", [])
        if clients:
            parts.append(f"[clients: {len(clients)}]")

        return " ".join(parts)

    @staticmethod
    def _extract_radios(status: Dict) -> List[str]:
        """Format radio list as r0=SSID/freq/Ncl or r0=SSID/freq/OFF."""
        wlan = status.get("wlan", {})
        radios_raw = wlan.get("radio", []) if isinstance(wlan, dict) else []
        result = []
        for i, radio in enumerate(radios_raw):
            bss_list = radio.get("bss", [])
            if not bss_list:
                continue
            bss = bss_list[0]
            ssid    = bss.get("ssid", f"radio{i}")
            enabled = bss.get("enabled", True)
            freq    = radio.get("frequency", "?")
            # Compact frequency: "2.4GHz" → "2.4G", "5GHz" → "5G"
            freq_s = freq.replace("GHz", "G").replace("MHz", "M")
            clients = radio.get("clients", None)
            if enabled:
                cl_s = f"{clients}cl" if clients is not None else "ON"
            else:
                cl_s = "OFF"
            result.append(f"r{i}={ssid}/{freq_s}/{cl_s}")
        return result

    @staticmethod
    def _extract_vlans(status: Dict) -> List[str]:
        """Format VLAN list as ID=uid."""
        vlans_raw = status.get("vlan", [])
        if not isinstance(vlans_raw, list):
            return []
        result = []
        for v in vlans_raw:
            vid = v.get("vid", "?")
            uid = v.get("uid", str(vid))
            result.append(f"{vid}={uid}")
        return result

    @staticmethod
    def _extract_ports(status: Dict) -> List[str]:
        """Format switch port list as pN=state/speed/pvid (or trunk)."""
        ports_raw = status.get("switch/ports", [])
        if not isinstance(ports_raw, list):
            return []
        result = []
        for p in ports_raw:
            n     = p.get("port", "?")
            link  = "up" if p.get("link") == "up" else "down"
            speed = p.get("speed") or ""
            # Compact speed: "1000Mbps" → "1G", "100Mbps" → "100M"
            speed_s = speed.replace("1000Mbps", "1G").replace("100Mbps", "100M").replace("Mbps", "M")
            pvid    = p.get("pvid", 1)
            tagged  = p.get("tagged_vlans", [])
            if tagged:
                vlan_s = "trunk"
            else:
                vlan_s = f"v{pvid}"
            if link == "down":
                result.append(f"p{n}=down")
            else:
                result.append(f"p{n}={link}/{speed_s}/{vlan_s}")
        return result

    def summary(self) -> str:
        """Human-readable device summary for REPL display."""
        if not self._status:
            return "(no device status)"
        s = self._status
        lines = []

        radios = s.get("wlan", {}).get("radio", [])
        if radios:
            lines.append(f"  WiFi radios ({len(radios)}):")
            for i, r in enumerate(radios):
                bss = r.get("bss", [{}])[0]
                ssid    = bss.get("ssid", "?")
                enabled = "✅" if bss.get("enabled", True) else "❌"
                freq    = r.get("frequency", "?")
                mac     = bss.get("mac", "")
                lines.append(f"    radio{i}: {ssid} ({freq}) {enabled}  {mac}")

        vlans = s.get("vlan", [])
        if vlans:
            lines.append(f"  VLANs ({len(vlans)}): " + "  ".join(f"{v['vid']}={v.get('uid','?')}" for v in vlans))

        ports = s.get("switch/ports", [])
        if ports:
            lines.append(f"  Switch ports ({len(ports)}):")
            for p in ports:
                link  = p.get("link", "?")
                speed = p.get("speed") or "-"
                pvid  = p.get("pvid", 1)
                icon  = "🟢" if link == "up" else "🔴"
                lines.append(f"    port{p['port']}: {icon} {link}  {speed}  pvid={pvid}")

        clients = s.get("lan/clients", [])
        if clients:
            lines.append(f"  LAN clients ({len(clients)}):")
            for c in clients[:5]:
                lines.append(f"    {c.get('hostname','?'):20s}  {c.get('ip','?'):16s}  {c.get('mac','?')}")
            if len(clients) > 5:
                lines.append(f"    ... and {len(clients)-5} more")

        wan_state = s.get("wan/connection_state", "?")
        wan_ip = s.get("wan/ipinfo", {}).get("ip_address", "?")
        lines.append(f"  WAN: {wan_state}  {wan_ip}")

        return "\n".join(lines)
