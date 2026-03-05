"""
Tool schemas for Cradlepoint R980 + Netgear GS105Ev2.

Design rules (from TRAINING_LESSONS.md):
- One user-facing operation per tool — not one per HTTP verb
- Short, keyword-rich descriptions (FunctionGemma reads ~8 tokens)
- Required params only — optional params confuse 270M models
- description on every property (required by FunctionGemma Jinja2 template)
- ~25 tools total — enough coverage without hurting routing accuracy
"""

from openhoof import create_tool_schema

# ── Cradlepoint R980 — Status (read-only) ────────────────────────────────────

ROUTER_STATUS_TOOLS = [
    create_tool_schema(
        name="router_get_lan_clients",
        summary="Get all devices connected to the router LAN",
        when_to_use="User asks about connected devices, clients, or who is on the network",
        parameters={"type": "object", "properties": {}, "required": []},
    ),
    create_tool_schema(
        name="router_get_lan_networks",
        summary="Get configured LAN networks and their DHCP settings",
        when_to_use="User asks about LAN subnets, DHCP ranges, or network configuration",
        parameters={"type": "object", "properties": {}, "required": []},
    ),
    create_tool_schema(
        name="router_get_wan_status",
        summary="Get WAN connection state, IP address, and carrier info",
        when_to_use="User asks about internet connection, WAN IP, uplink, or carrier",
        parameters={"type": "object", "properties": {}, "required": []},
    ),
    create_tool_schema(
        name="router_get_system_status",
        summary="Get router CPU, memory, uptime, and firmware info",
        when_to_use="User asks about router health, uptime, memory, CPU, or firmware version",
        parameters={"type": "object", "properties": {}, "required": []},
    ),
    create_tool_schema(
        name="router_get_system_config",
        summary="Get system settings including NTP, admin timeout, and lockout policy",
        when_to_use="User asks about system settings, NTP, lockout, PCI-DSS, or admin config",
        parameters={"type": "object", "properties": {}, "required": []},
    ),
    create_tool_schema(
        name="router_get_dhcp_leases",
        summary="Get active DHCP lease table with MAC, IP, hostname, and expiry",
        when_to_use="User asks about DHCP leases, IP assignments, or device MAC lookup",
        parameters={"type": "object", "properties": {}, "required": []},
    ),
    create_tool_schema(
        name="router_get_routing_table",
        summary="Get the active routing table",
        when_to_use="User asks about routes, routing table, gateways, or static routes",
        parameters={"type": "object", "properties": {}, "required": []},
    ),
    create_tool_schema(
        name="router_get_firewall_config",
        summary="Get firewall settings including WAN ping, anti-spoof, DMZ, and ALG",
        when_to_use="User asks about firewall, WAN ping, DMZ, or application layer gateway",
        parameters={"type": "object", "properties": {}, "required": []},
    ),
    create_tool_schema(
        name="router_get_wifi_config",
        summary="Get all WiFi radios and SSIDs with their security settings",
        when_to_use="User asks about WiFi, SSIDs, wireless networks, or WPA settings",
        parameters={"type": "object", "properties": {}, "required": []},
    ),
    create_tool_schema(
        name="router_get_vlan_config",
        summary="Get all configured VLANs on the router",
        when_to_use="User asks about VLANs, VLAN list, or router VLAN configuration",
        parameters={"type": "object", "properties": {}, "required": []},
    ),
    create_tool_schema(
        name="router_get_lldp_neighbors",
        summary="Get LLDP neighbor discovery data showing connected devices by port",
        when_to_use="User asks about LLDP neighbors, connected switches, or port neighbors",
        parameters={"type": "object", "properties": {}, "required": []},
    ),
    create_tool_schema(
        name="router_get_logs",
        summary="Get recent system log entries from the router",
        when_to_use="User asks about logs, events, errors, or recent router activity",
        parameters={
            "type": "object",
            "properties": {
                "level": {
                    "type": "string",
                    "description": "Minimum log level to return: debug, info, warning, error, critical",
                },
            },
            "required": [],
        },
    ),
]

# ── Cradlepoint R980 — Config mutations ──────────────────────────────────────

ROUTER_CONFIG_TOOLS = [
    create_tool_schema(
        name="router_create_vlan",
        summary="Create a new VLAN on the router",
        when_to_use="User asks to add or create a VLAN on the router",
        parameters={
            "type": "object",
            "properties": {
                "vid":  {"type": "integer", "description": "VLAN ID (1-4094)"},
                "uid":  {"type": "string",  "description": "Short unique identifier e.g. vlan100"},
                "mode": {"type": "string",  "description": "VLAN mode: wan or lan"},
            },
            "required": ["vid", "uid", "mode"],
        },
    ),
    create_tool_schema(
        name="router_delete_vlan",
        summary="Delete a VLAN from the router by its index",
        when_to_use="User asks to remove or delete a VLAN from the router",
        parameters={
            "type": "object",
            "properties": {
                "idx": {"type": "integer", "description": "VLAN array index to delete"},
            },
            "required": ["idx"],
        },
    ),
    create_tool_schema(
        name="router_update_lan",
        summary="Update LAN network settings such as DHCP range or gateway IP",
        when_to_use="User asks to change DHCP range, gateway IP, or LAN network settings",
        parameters={
            "type": "object",
            "properties": {
                "idx":         {"type": "integer", "description": "LAN array index to update"},
                "ip_address":  {"type": "string",  "description": "Gateway IP address"},
                "netmask":     {"type": "string",  "description": "Subnet mask"},
                "dhcp_start":  {"type": "integer", "description": "DHCP range start host offset"},
                "dhcp_end":    {"type": "integer", "description": "DHCP range end host offset"},
            },
            "required": ["idx"],
        },
    ),
    create_tool_schema(
        name="router_update_wifi_ssid",
        summary="Update WiFi SSID settings such as passphrase, visibility, or auth mode",
        when_to_use="User asks to change WiFi password, SSID name, hide network, or change security",
        parameters={
            "type": "object",
            "properties": {
                "radio_idx": {"type": "integer", "description": "Radio index: 0=2.4GHz 1=5GHz"},
                "bss_idx":   {"type": "integer", "description": "BSS index on the radio"},
                "ssid":      {"type": "string",  "description": "Network name"},
                "wpapsk":    {"type": "string",  "description": "WPA passphrase"},
                "hidden":    {"type": "boolean", "description": "Hide the SSID"},
                "enabled":   {"type": "boolean", "description": "Enable or disable this SSID"},
            },
            "required": ["radio_idx", "bss_idx"],
        },
    ),
    create_tool_schema(
        name="router_update_firewall",
        summary="Update router firewall settings such as WAN ping or anti-spoofing",
        when_to_use="User asks to enable or disable WAN ping, anti-spoof, or DMZ",
        parameters={
            "type": "object",
            "properties": {
                "wan_ping":   {"type": "boolean", "description": "Allow ping from WAN"},
                "anti_spoof": {"type": "boolean", "description": "Enable anti-spoofing"},
            },
            "required": [],
        },
    ),
    create_tool_schema(
        name="router_reboot",
        summary="Reboot the Cradlepoint router",
        when_to_use="User asks to reboot, restart, or power cycle the router",
        parameters={"type": "object", "properties": {}, "required": []},
    ),
    create_tool_schema(
        name="router_add_static_route",
        summary="Add a static route to the router routing table",
        when_to_use="User asks to add a route, static route, or network path",
        parameters={
            "type": "object",
            "properties": {
                "ip_network": {"type": "string",  "description": "Destination network in CIDR e.g. 10.1.0.0/24"},
                "gateway":    {"type": "string",  "description": "Gateway IP address"},
                "metric":     {"type": "integer", "description": "Route metric"},
            },
            "required": ["ip_network", "gateway"],
        },
    ),
    create_tool_schema(
        name="router_add_dns_host",
        summary="Add a static DNS host override entry",
        when_to_use="User asks to add a DNS entry, hostname override, or static DNS record",
        parameters={
            "type": "object",
            "properties": {
                "hostname":   {"type": "string", "description": "Hostname to resolve"},
                "ip_address": {"type": "string", "description": "IP address to return"},
            },
            "required": ["hostname", "ip_address"],
        },
    ),
]

# ── Netgear GS105Ev2 Switch ───────────────────────────────────────────────────

SWITCH_TOOLS = [
    create_tool_schema(
        name="switch_get_port_status",
        summary="Get all switch port link states, speeds, and VLAN membership",
        when_to_use="User asks about switch ports, link state, port speed, or which ports are up",
        parameters={"type": "object", "properties": {}, "required": []},
    ),
    create_tool_schema(
        name="switch_get_vlan_config",
        summary="Get all VLANs configured on the switch",
        when_to_use="User asks about switch VLANs, VLAN list, or switch VLAN configuration",
        parameters={"type": "object", "properties": {}, "required": []},
    ),
    create_tool_schema(
        name="switch_create_vlan",
        summary="Create a new VLAN on the switch",
        when_to_use="User asks to add or create a VLAN on the switch",
        parameters={
            "type": "object",
            "properties": {
                "vid": {"type": "integer", "description": "VLAN ID to create (1-4094)"},
            },
            "required": ["vid"],
        },
    ),
    create_tool_schema(
        name="switch_delete_vlan",
        summary="Delete a VLAN from the switch",
        when_to_use="User asks to remove or delete a VLAN from the switch",
        parameters={
            "type": "object",
            "properties": {
                "vid": {"type": "integer", "description": "VLAN ID to delete"},
            },
            "required": ["vid"],
        },
    ),
    create_tool_schema(
        name="switch_set_vlan_membership",
        summary="Set which ports belong to a VLAN and whether they are tagged or untagged",
        when_to_use="User assigns ports to a VLAN, sets tagged/untagged, or configures trunk ports",
        parameters={
            "type": "object",
            "properties": {
                "vid":         {"type": "integer", "description": "VLAN ID to configure"},
                "port_config": {
                    "type": "string",
                    "description": "5-char membership string, one per port: 1=untagged 2=tagged 3=not-member. e.g. 21333",
                },
            },
            "required": ["vid", "port_config"],
        },
    ),
    create_tool_schema(
        name="switch_set_port_pvid",
        summary="Set the default VLAN (PVID) for one or more switch ports",
        when_to_use="User asks to set port PVID, default VLAN for untagged traffic, or access VLAN",
        parameters={
            "type": "object",
            "properties": {
                "port": {"type": "integer", "description": "Physical port number 1-5"},
                "vid":  {"type": "integer", "description": "VLAN ID to assign as default"},
            },
            "required": ["port", "vid"],
        },
    ),
    create_tool_schema(
        name="switch_get_port_stats",
        summary="Get TX/RX byte counters per switch port",
        when_to_use="User asks about port traffic, bandwidth, byte counts, or port statistics",
        parameters={"type": "object", "properties": {}, "required": []},
    ),
    create_tool_schema(
        name="switch_get_system_info",
        summary="Get switch MAC address, firmware version, IP address, and hostname",
        when_to_use="User asks about switch info, switch firmware, switch IP, or MAC address",
        parameters={"type": "object", "properties": {}, "required": []},
    ),
    create_tool_schema(
        name="switch_reboot",
        summary="Reboot the Netgear switch",
        when_to_use="User asks to reboot, restart, or power cycle the switch",
        parameters={"type": "object", "properties": {}, "required": []},
    ),
]

# ── Combined export ───────────────────────────────────────────────────────────

ALL_TOOLS = ROUTER_STATUS_TOOLS + ROUTER_CONFIG_TOOLS + SWITCH_TOOLS

__all__ = ["ALL_TOOLS", "ROUTER_STATUS_TOOLS", "ROUTER_CONFIG_TOOLS", "SWITCH_TOOLS"]
