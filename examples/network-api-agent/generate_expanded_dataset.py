"""
Expanded training dataset generator.

Doubles the dataset with two key additions:
  1. Ambiguous natural language phrasing — "add radio2 to lan", "increase radio 3
     max people to 200", "move guest to port 3", etc.
  2. Context-prefixed examples — the app scans the device, prepends a compact
     summary of current state, and FunctionGemma routes with that context.

Context format (compact, ~20-40 tokens):
  [radios: r0=HomeNet/2.4G/8cl r1=HomeNet_5G/5G/2cl r2=Guest/2.4G/OFF r3=IoT/5G/4cl]
  [vlans: 10=mgmt 20=data 100=guest 200=iot]
  [ports: p1=up/1G/v10 p2=up/100M/v20 p3=down/v1 p4=up/1G/trunk p5=up/1G/trunk]
  [clients: 14 total - aa:bb:cc:01 MacBook/192.168.0.10 aa:bb:cc:02 iPhone/192.168.0.11]

FunctionGemma learns to ignore the context prefix for simple queries and USE it
for queries that reference radio indices, VLAN IDs, or port numbers by discovery name.
"""

from __future__ import annotations

import json
import random
from datetime import date
from pathlib import Path

TRAINING_DIR = Path(".microclaw/training")
TODAY = date.today().isoformat()
OUT_FILE = TRAINING_DIR / f"router_expanded_{TODAY}.jsonl"

random.seed(42)


def ex(human: str, gpt: str) -> dict:
    return {"conversations": [{"from": "human", "value": human}, {"from": "gpt", "value": gpt}]}


# ── Context templates ─────────────────────────────────────────────────────────
# These mimic what the app discovers before the user speaks.
# The model must learn to route correctly regardless of what context is present.

RADIO_CONTEXTS = [
    "[radios: r0=HomeNet/2.4G/8cl r1=HomeNet_5G/5G/2cl r2=Guest/2.4G/OFF r3=IoT/5G/4cl r4=HomeNet_6G/6G/1cl]",
    "[radios: r0=OfficeMain/2.4G/12cl r1=OfficeMain_5G/5G/5cl r2=OfficeGuest/2.4G/3cl]",
    "[radios: r0=Network/2.4G/ON r1=Network_5G/5G/ON r2=IoT_net/2.4G/ON r3=Guest/5G/OFF]",
    "[radios: r0=SSID_Main/2.4G/enabled r1=SSID_Fast/5G/enabled r2=SSID_Guest/2.4G/disabled]",
    "[5 radios: radio0=2.4GHz/HomeNet/MAC=aa:bb:cc:dd:00:01 radio1=5GHz/HomeNet5G/MAC=aa:bb:cc:dd:00:02 radio2=2.4GHz/Guest/MAC=aa:bb:cc:dd:00:03 radio3=5GHz/IoT/MAC=aa:bb:cc:dd:00:04 radio4=6GHz/UltraFast/MAC=aa:bb:cc:dd:00:05]",
]

VLAN_CONTEXTS = [
    "[vlans: 1=default 10=mgmt 20=data 100=guest 200=iot]",
    "[vlans on switch: vlan10=management vlan20=staff vlan30=printers vlan100=visitors]",
    "[configured vlans: 10 20 100 200]",
]

PORT_CONTEXTS = [
    "[ports: p1=up/1G/v10 p2=up/100M/v20 p3=down/v1 p4=up/1G/trunk p5=up/1G/trunk]",
    "[switch ports: 1=up/gigabit 2=up/100M 3=down 4=up/gigabit/trunk 5=up/gigabit/trunk]",
    "[5 ports: port1=link-up/1000Mbps port2=link-up/100Mbps port3=link-down port4=link-up/1000Mbps port5=link-up/1000Mbps]",
]

CLIENT_CONTEXTS = [
    "[clients: 14 total - aa:bb:cc:01=MacBook/192.168.0.10 aa:bb:cc:02=iPhone/192.168.0.11 aa:bb:cc:03=unknown/192.168.0.12]",
    "[lan clients: MacBook(aa:bb:cc:01, 192.168.0.10) iPhone(aa:bb:cc:02, 192.168.0.11) iPad(aa:bb:cc:03, 192.168.0.12)]",
    "[3 clients found: 192.168.0.10/aa:bb:cc:dd:ee:01/laptop 192.168.0.11/aa:bb:cc:dd:ee:02/phone]",
]

COMBINED_CONTEXTS = [
    "[radios: r0=HomeNet/2.4G/8cl r1=HomeNet_5G/5G/2cl r2=Guest/2.4G/OFF] [vlans: 10=mgmt 20=data 100=guest] [ports: p1=up/v10 p2=up/v20 p3=down p4=trunk p5=trunk]",
    "[3 radios: r0=2.4G/ON r1=5G/ON r2=Guest/OFF] [switch: p1-p3=access p4-p5=trunk] [vlans: 1 10 20 100]",
    "[scan: 4 radios 3 vlans 5 ports 14 clients]",
]


def rand_ctx(*pools) -> str:
    """Pick one context from each pool and join them."""
    return " ".join(random.choice(p) for p in pools)


# ── WiFi / Radio examples ─────────────────────────────────────────────────────

WIFI_EXAMPLES = [
    # No-context: simple routing
    ex("show wifi networks", "router_get_wifi_config()"),
    ex("list all SSIDs", "router_get_wifi_config()"),
    ex("what wireless networks are configured", "router_get_wifi_config()"),
    ex("wifi settings", "router_get_wifi_config()"),
    ex("wireless config", "router_get_wifi_config()"),
    ex("show all radios", "router_get_wifi_config()"),
    ex("5GHz wifi settings", "router_get_wifi_config()"),
    ex("2.4GHz radio config", "router_get_wifi_config()"),
    ex("guest wifi settings", "router_get_wifi_config()"),

    # Ambiguous radio references
    ex("add radio 2 to lan", "router_update_wifi_ssid(radio_idx=2, bss_idx=0, enabled=True)"),
    ex("enable radio2", "router_update_wifi_ssid(radio_idx=2, bss_idx=0, enabled=True)"),
    ex("turn on radio 0", "router_update_wifi_ssid(radio_idx=0, bss_idx=0, enabled=True)"),
    ex("disable radio 2", "router_update_wifi_ssid(radio_idx=2, bss_idx=0, enabled=False)"),
    ex("turn off radio 3", "router_update_wifi_ssid(radio_idx=3, bss_idx=0, enabled=False)"),
    ex("disable guest radio", "router_update_wifi_ssid(radio_idx=2, bss_idx=0, enabled=False)"),
    ex("enable the iot radio", "router_update_wifi_ssid(radio_idx=3, bss_idx=0, enabled=True)"),
    ex("turn off the 5GHz network", "router_update_wifi_ssid(radio_idx=1, bss_idx=0, enabled=False)"),
    ex("disable the guest SSID", "router_update_wifi_ssid(radio_idx=0, bss_idx=1, enabled=False)"),
    ex("hide the guest wifi", "router_update_wifi_ssid(radio_idx=0, bss_idx=1, hidden=True)"),
    ex("hide guest network", "router_update_wifi_ssid(radio_idx=0, bss_idx=1, hidden=True)"),
    ex("unhide the main SSID", "router_update_wifi_ssid(radio_idx=0, bss_idx=0, hidden=False)"),
    ex("change wifi password to securepass123", "router_update_wifi_ssid(radio_idx=0, bss_idx=0, wpapsk='securepass123')"),
    ex("set wifi password to mypassword", "router_update_wifi_ssid(radio_idx=0, bss_idx=0, wpapsk='mypassword')"),
    ex("rename wifi to MyNetwork", "router_update_wifi_ssid(radio_idx=0, bss_idx=0, ssid='MyNetwork')"),
    ex("change SSID name to CorpWiFi", "router_update_wifi_ssid(radio_idx=0, bss_idx=0, ssid='CorpWiFi')"),

    # Context-prefixed: radio discovered, ambiguous "radio N"
    ex(f"{random.choice(RADIO_CONTEXTS)} add radio 2 to lan", "router_update_wifi_ssid(radio_idx=2, bss_idx=0, enabled=True)"),
    ex(f"{random.choice(RADIO_CONTEXTS)} disable radio 0", "router_update_wifi_ssid(radio_idx=0, bss_idx=0, enabled=False)"),
    ex(f"{random.choice(RADIO_CONTEXTS)} enable radio 3", "router_update_wifi_ssid(radio_idx=3, bss_idx=0, enabled=True)"),
    ex(f"{random.choice(RADIO_CONTEXTS)} turn off radio 1", "router_update_wifi_ssid(radio_idx=1, bss_idx=0, enabled=False)"),
    ex(f"{random.choice(RADIO_CONTEXTS)} hide radio 2", "router_update_wifi_ssid(radio_idx=2, bss_idx=0, hidden=True)"),
    ex(f"{random.choice(RADIO_CONTEXTS)} rename radio 0 to MainNet", "router_update_wifi_ssid(radio_idx=0, bss_idx=0, ssid='MainNet')"),
    ex(f"{random.choice(RADIO_CONTEXTS)} change radio 1 password to newpass", "router_update_wifi_ssid(radio_idx=1, bss_idx=0, wpapsk='newpass')"),
    ex(f"{random.choice(RADIO_CONTEXTS)} show all radios", "router_get_wifi_config()"),
    ex(f"{random.choice(RADIO_CONTEXTS)} wifi config", "router_get_wifi_config()"),
    ex(f"{random.choice(COMBINED_CONTEXTS)} which radios are active", "router_get_wifi_config()"),
    ex(f"{random.choice(COMBINED_CONTEXTS)} disable radio 2", "router_update_wifi_ssid(radio_idx=2, bss_idx=0, enabled=False)"),
]

# ── VLAN examples ─────────────────────────────────────────────────────────────

VLAN_EXAMPLES = [
    # Router VLANs
    ex("show vlans on router", "router_get_vlan_config()"),
    ex("router vlan list", "router_get_vlan_config()"),
    ex("list configured vlans", "router_get_vlan_config()"),
    ex("what vlans exist", "router_get_vlan_config()"),
    ex("vlan configuration", "router_get_vlan_config()"),
    ex("create vlan 100 on router lan", "router_create_vlan(vid=100, uid='vlan100', mode='lan')"),
    ex("add wan vlan 200", "router_create_vlan(vid=200, uid='vlan200', mode='wan')"),
    ex("add vlan 50 as lan", "router_create_vlan(vid=50, uid='vlan50', mode='lan')"),
    ex("create vlan 10 for management", "router_create_vlan(vid=10, uid='mgmt', mode='lan')"),
    ex("add vlan 30 for printers", "router_create_vlan(vid=30, uid='printers', mode='lan')"),
    ex("remove vlan 100 from router", "router_delete_vlan(idx=0)"),
    ex("delete router vlan at index 1", "router_delete_vlan(idx=1)"),
    ex("remove the second router vlan", "router_delete_vlan(idx=1)"),

    # Context-prefixed router VLANs
    ex(f"{random.choice(VLAN_CONTEXTS)} show router vlans", "router_get_vlan_config()"),
    ex(f"{random.choice(VLAN_CONTEXTS)} what vlans are on the router", "router_get_vlan_config()"),
    ex(f"{random.choice(VLAN_CONTEXTS)} add vlan 300 to router", "router_create_vlan(vid=300, uid='vlan300', mode='lan')"),
    ex(f"{random.choice(COMBINED_CONTEXTS)} vlan list", "router_get_vlan_config()"),

    # Switch VLANs
    ex("switch vlans", "switch_get_vlan_config()"),
    ex("show vlans on switch", "switch_get_vlan_config()"),
    ex("list switch vlan ids", "switch_get_vlan_config()"),
    ex("add vlan 100 to switch", "switch_create_vlan(vid=100)"),
    ex("create switch vlan 20", "switch_create_vlan(vid=20)"),
    ex("add vlan 50 to the netgear switch", "switch_create_vlan(vid=50)"),
    ex("new switch vlan 200", "switch_create_vlan(vid=200)"),
    ex("remove vlan 100 from switch", "switch_delete_vlan(vid=100)"),
    ex("delete switch vlan 20", "switch_delete_vlan(vid=20)"),
    ex("delete the vlan 3 from the switch", "switch_delete_vlan(vid=3)"),
    ex("delete vlan 1 from the switch interface", "switch_delete_vlan(vid=1)"),

    # VLAN membership — this is where ambiguous phrasing matters most
    ex("port 1 untagged port 5 tagged vlan 20", "switch_set_vlan_membership(vid=20, port_config='13332')"),
    ex("untagged vlan 100 on port 1 only", "switch_set_vlan_membership(vid=100, port_config='13333')"),
    ex("configure port 1 with vlan 10 as tagged", "switch_set_vlan_membership(vid=10, port_config='21333')"),
    ex("ports 1 and 2 untagged in vlan 10", "switch_set_vlan_membership(vid=10, port_config='11333')"),
    ex("trunk port 5 tagged vlan 100", "switch_set_vlan_membership(vid=100, port_config='33332')"),
    ex("all ports untagged in vlan 1", "switch_set_vlan_membership(vid=1, port_config='11111')"),
    ex("port 4 tagged in vlan 20", "switch_set_vlan_membership(vid=20, port_config='33323')"),
    ex("ports 1-3 untagged vlan 10 port 5 tagged", "switch_set_vlan_membership(vid=10, port_config='11132')"),
    ex("set vlan 100 membership: p1 untagged p2 untagged p3-p5 not member", "switch_set_vlan_membership(vid=100, port_config='11333')"),
    ex("vlan 20 tagged on ports 4 and 5", "switch_set_vlan_membership(vid=20, port_config='33322')"),

    # Context-prefixed VLAN membership
    ex(f"{random.choice(VLAN_CONTEXTS)} {random.choice(PORT_CONTEXTS)} set vlan 10 on port 1 untagged", "switch_set_vlan_membership(vid=10, port_config='13333')"),
    ex(f"{random.choice(PORT_CONTEXTS)} trunk port 5 on vlan 20", "switch_set_vlan_membership(vid=20, port_config='33332')"),
    ex(f"{random.choice(COMBINED_CONTEXTS)} add vlan 100 to switch", "switch_create_vlan(vid=100)"),
    ex(f"{random.choice(COMBINED_CONTEXTS)} delete switch vlan 20", "switch_delete_vlan(vid=20)"),
]

# ── Port / switch examples ─────────────────────────────────────────────────────

PORT_EXAMPLES = [
    ex("switch port states", "switch_get_port_status()"),
    ex("which ports are up", "switch_get_port_status()"),
    ex("port 3 link state", "switch_get_port_status()"),
    ex("are any ports down", "switch_get_port_status()"),
    ex("show port link status", "switch_get_port_status()"),
    ex("switch port summary", "switch_get_port_status()"),
    ex("all switch port states", "switch_get_port_status()"),
    ex("switch port counters", "switch_get_port_stats()"),
    ex("tx rx bytes per port", "switch_get_port_stats()"),
    ex("show port traffic statistics", "switch_get_port_stats()"),
    ex("port byte counts", "switch_get_port_stats()"),
    ex("how much traffic on each port", "switch_get_port_stats()"),
    ex("switch bandwidth per port", "switch_get_port_stats()"),
    ex("port 2 throughput", "switch_get_port_stats()"),
    ex("set port 3 PVID to 100", "switch_set_port_pvid(port=3, vid=100)"),
    ex("access vlan on port 2 is 20", "switch_set_port_pvid(port=2, vid=20)"),
    ex("port 8 PVID is 30", "switch_set_port_pvid(port=8, vid=30)"),
    ex("set default vlan for port 5 to vlan 20", "switch_set_port_pvid(port=5, vid=20)"),
    ex("untagged traffic on port 4 should be vlan 10", "switch_set_port_pvid(port=4, vid=10)"),
    ex("assign port 1 to vlan 100 as access port", "switch_set_port_pvid(port=1, vid=100)"),
    ex("port 3 native vlan 20", "switch_set_port_pvid(port=3, vid=20)"),
    ex("port 1 default vlan 10", "switch_set_port_pvid(port=1, vid=10)"),
    ex("set pvid 100 on port 2", "switch_set_port_pvid(port=2, vid=100)"),

    # Context-prefixed port examples
    ex(f"{random.choice(PORT_CONTEXTS)} show port stats", "switch_get_port_stats()"),
    ex(f"{random.choice(PORT_CONTEXTS)} which ports are up", "switch_get_port_status()"),
    ex(f"{random.choice(PORT_CONTEXTS)} set port 3 pvid to 100", "switch_set_port_pvid(port=3, vid=100)"),
    ex(f"{random.choice(PORT_CONTEXTS)} port 1 access vlan 20", "switch_set_port_pvid(port=1, vid=20)"),
    ex(f"{random.choice(COMBINED_CONTEXTS)} port traffic stats", "switch_get_port_stats()"),
    ex(f"{random.choice(COMBINED_CONTEXTS)} port 2 link state", "switch_get_port_status()"),
]

# ── LAN / routing / DHCP examples ─────────────────────────────────────────────

NETWORK_EXAMPLES = [
    ex("who is on the network", "router_get_lan_clients()"),
    ex("show connected devices", "router_get_lan_clients()"),
    ex("list connected devices", "router_get_lan_clients()"),
    ex("how many devices online", "router_get_lan_clients()"),
    ex("what devices are connected", "router_get_lan_clients()"),
    ex("lan client list", "router_get_lan_clients()"),
    ex("who is on wifi", "router_get_lan_clients()"),
    ex("show all clients", "router_get_lan_clients()"),
    ex("dhcp table", "router_get_dhcp_leases()"),
    ex("ip to mac mapping", "router_get_dhcp_leases()"),
    ex("dhcp lease list", "router_get_dhcp_leases()"),
    ex("what IP does the macbook have", "router_get_dhcp_leases()"),
    ex("show ip assignments", "router_get_dhcp_leases()"),
    ex("find device by mac", "router_get_dhcp_leases()"),
    ex("show lan subnets", "router_get_lan_networks()"),
    ex("lan network settings", "router_get_lan_networks()"),
    ex("what DHCP scopes are configured", "router_get_lan_networks()"),
    ex("subnet configuration", "router_get_lan_networks()"),
    ex("dhcp server settings", "router_get_lan_networks()"),
    ex("lan ip range", "router_get_lan_networks()"),
    ex("change dhcp range on lan 0", "router_update_lan(idx=0, dhcp_start=100, dhcp_end=200)"),
    ex("update lan gateway to 10.0.0.1", "router_update_lan(idx=0, ip_address='10.0.0.1')"),
    ex("set dhcp start to 50 on lan 0", "router_update_lan(idx=0, dhcp_start=50)"),
    ex("change lan 0 netmask to 255.255.0.0", "router_update_lan(idx=0, netmask='255.255.0.0')"),
    ex("add static route 10.1.0.0/24 via 192.168.0.254", "router_add_static_route(ip_network='10.1.0.0/24', gateway='192.168.0.254')"),
    ex("add route to 10.0.0.0/8 through 172.16.0.1", "router_add_static_route(ip_network='10.0.0.0/8', gateway='172.16.0.1')"),
    ex("static route for 192.168.5.0/24 via 192.168.0.1", "router_add_static_route(ip_network='192.168.5.0/24', gateway='192.168.0.1')"),
    ex("routing table", "router_get_routing_table()"),
    ex("static routes", "router_get_routing_table()"),
    ex("show gateway routes", "router_get_routing_table()"),
    ex("current routes", "router_get_routing_table()"),
    ex("dns host override for myserver 10.0.0.5", "router_add_dns_host(hostname='myserver', ip_address='10.0.0.5')"),
    ex("add dns entry camera1 192.168.0.50", "router_add_dns_host(hostname='camera1', ip_address='192.168.0.50')"),
    ex("static dns for nas 10.0.0.100", "router_add_dns_host(hostname='nas', ip_address='10.0.0.100')"),

    # Context-prefixed client/network examples
    ex(f"{random.choice(CLIENT_CONTEXTS)} who is on the network", "router_get_lan_clients()"),
    ex(f"{random.choice(CLIENT_CONTEXTS)} how many devices connected", "router_get_lan_clients()"),
    ex(f"{random.choice(CLIENT_CONTEXTS)} find the macbook", "router_get_dhcp_leases()"),
    ex(f"{random.choice(CLIENT_CONTEXTS)} what ip does aa:bb:cc:01 have", "router_get_dhcp_leases()"),
    ex(f"{random.choice(COMBINED_CONTEXTS)} show clients", "router_get_lan_clients()"),
    ex(f"{random.choice(COMBINED_CONTEXTS)} dhcp leases", "router_get_dhcp_leases()"),
]

# ── WAN / system / firewall examples ──────────────────────────────────────────

SYSTEM_EXAMPLES = [
    ex("show wan ip", "router_get_wan_status()"),
    ex("what's my WAN IP", "router_get_wan_status()"),
    ex("check internet", "router_get_wan_status()"),
    ex("uplink status", "router_get_wan_status()"),
    ex("carrier info", "router_get_wan_status()"),
    ex("is the internet up", "router_get_wan_status()"),
    ex("wan connection state", "router_get_wan_status()"),
    ex("router cpu usage", "router_get_system_status()"),
    ex("how long has router been up", "router_get_system_status()"),
    ex("router memory usage", "router_get_system_status()"),
    ex("router uptime", "router_get_system_status()"),
    ex("router health", "router_get_system_status()"),
    ex("system resources", "router_get_system_status()"),
    ex("check for PCI-DSS lockout", "router_get_system_config()"),
    ex("how many failed logins", "router_get_system_config()"),
    ex("NTP config", "router_get_system_config()"),
    ex("admin timeout setting", "router_get_system_config()"),
    ex("system configuration", "router_get_system_config()"),
    ex("firewall settings", "router_get_firewall_config()"),
    ex("ALG settings", "router_get_firewall_config()"),
    ex("show firewall rules", "router_get_firewall_config()"),
    ex("DMZ settings", "router_get_firewall_config()"),
    ex("application layer gateway config", "router_get_firewall_config()"),
    ex("wan firewall config", "router_get_firewall_config()"),
    ex("disable WAN ping", "router_update_firewall(wan_ping=False)"),
    ex("allow ping from internet", "router_update_firewall(wan_ping=True)"),
    ex("enable anti-spoof", "router_update_firewall(anti_spoof=True)"),
    ex("block wan ping", "router_update_firewall(wan_ping=False)"),
    ex("turn on anti spoofing", "router_update_firewall(anti_spoof=True)"),
    ex("LLDP neighbors", "router_get_lldp_neighbors()"),
    ex("what is plugged into each router port", "router_get_lldp_neighbors()"),
    ex("lldp discovery", "router_get_lldp_neighbors()"),
    ex("show lldp", "router_get_lldp_neighbors()"),
    ex("connected devices by port", "router_get_lldp_neighbors()"),
    ex("which switch is connected to the router", "router_get_lldp_neighbors()"),
    ex("show error logs", "router_get_logs(level='error')"),
    ex("critical alerts", "router_get_logs(level='critical')"),
    ex("all logs", "router_get_logs()"),
    ex("recent system logs", "router_get_logs()"),
    ex("show warnings", "router_get_logs(level='warning')"),
    ex("debug logs", "router_get_logs(level='debug')"),
    ex("restart the router", "router_reboot()"),
    ex("power cycle router", "router_reboot()"),
    ex("reboot the cradlepoint", "router_reboot()"),

    # Context-prefixed
    ex(f"{random.choice(COMBINED_CONTEXTS)} check internet", "router_get_wan_status()"),
    ex(f"{random.choice(COMBINED_CONTEXTS)} show error logs", "router_get_logs(level='error')"),
    ex(f"{random.choice(COMBINED_CONTEXTS)} lldp neighbors", "router_get_lldp_neighbors()"),
    ex(f"{random.choice(COMBINED_CONTEXTS)} reboot router", "router_reboot()"),
]

# ── Switch system examples ─────────────────────────────────────────────────────

SWITCH_SYSTEM_EXAMPLES = [
    ex("switch firmware version", "switch_get_system_info()"),
    ex("switch mac address", "switch_get_system_info()"),
    ex("what firmware is the switch running", "switch_get_system_info()"),
    ex("switch hardware info", "switch_get_system_info()"),
    ex("switch model and version", "switch_get_system_info()"),
    ex("netgear switch info", "switch_get_system_info()"),
    ex("switch ip address", "switch_get_system_info()"),
    ex("reboot switch", "switch_reboot()"),
    ex("restart switch", "switch_reboot()"),
    ex("power cycle the netgear switch", "switch_reboot()"),
    ex("switch reboot", "switch_reboot()"),

    # Context-prefixed
    ex(f"{random.choice(PORT_CONTEXTS)} switch info", "switch_get_system_info()"),
    ex(f"{random.choice(COMBINED_CONTEXTS)} reboot switch", "switch_reboot()"),
    ex(f"{random.choice(COMBINED_CONTEXTS)} switch firmware", "switch_get_system_info()"),
    ex(f"{random.choice(COMBINED_CONTEXTS)} switch port stats", "switch_get_port_stats()"),
    ex(f"{random.choice(COMBINED_CONTEXTS)} show switch vlans", "switch_get_vlan_config()"),
]

# ── Ambiguous cross-device phrasing ───────────────────────────────────────────
# These are the tricky cases: "add radio2 to lan", "increase max clients",
# "move guest network to vlan 100", etc.

AMBIGUOUS_EXAMPLES = [
    # Radio-as-LAN-client-limit (fictional but maps to wifi ssid update)
    ex("increase radio 0 max clients to 50", "router_update_wifi_ssid(radio_idx=0, bss_idx=0)"),
    ex("set radio 2 max users to 25", "router_update_wifi_ssid(radio_idx=2, bss_idx=0)"),
    ex("limit radio 1 to 10 clients", "router_update_wifi_ssid(radio_idx=1, bss_idx=0)"),

    # "Move X to vlan Y" — switch membership update
    ex("move port 3 to vlan 100", "switch_set_port_pvid(port=3, vid=100)"),
    ex("put port 2 on vlan 20", "switch_set_port_pvid(port=2, vid=20)"),
    ex("assign port 1 to management vlan", "switch_set_port_pvid(port=1, vid=10)"),
    ex("port 4 should be on the data vlan", "switch_set_port_pvid(port=4, vid=20)"),
    ex("move the server port to vlan 10", "switch_set_port_pvid(port=1, vid=10)"),
    ex("put the printer port on vlan 30", "switch_set_port_pvid(port=3, vid=30)"),

    # "add X to lan" — context dependent
    ex("add vlan 100 to the lan", "router_create_vlan(vid=100, uid='vlan100', mode='lan')"),
    ex("add vlan 10 for management traffic", "router_create_vlan(vid=10, uid='mgmt', mode='lan')"),
    ex("add new network segment vlan 50", "router_create_vlan(vid=50, uid='vlan50', mode='lan')"),

    # MAC / device lookups
    ex("what IP does MAC aa:bb:cc:dd:ee:ff have", "router_get_dhcp_leases()"),
    ex("find device with MAC address", "router_get_dhcp_leases()"),
    ex("look up aa:bb:cc:01", "router_get_dhcp_leases()"),
    ex("which IP is assigned to this mac aa:bb:cc:dd:00:01", "router_get_dhcp_leases()"),

    # Context-prefixed ambiguous
    ex(f"{random.choice(RADIO_CONTEXTS)} add radio 2 to lan", "router_update_wifi_ssid(radio_idx=2, bss_idx=0, enabled=True)"),
    ex(f"{random.choice(RADIO_CONTEXTS)} disable the guest radio", "router_update_wifi_ssid(radio_idx=2, bss_idx=0, enabled=False)"),
    ex(f"{random.choice(RADIO_CONTEXTS)} how many clients on radio 0", "router_get_wifi_config()"),
    ex(f"{random.choice(RADIO_CONTEXTS)} rename radio 1 SSID to FastNet", "router_update_wifi_ssid(radio_idx=1, bss_idx=0, ssid='FastNet')"),
    ex(f"{random.choice(PORT_CONTEXTS)} move port 3 to vlan 100", "switch_set_port_pvid(port=3, vid=100)"),
    ex(f"{random.choice(PORT_CONTEXTS)} put port 1 on management vlan", "switch_set_port_pvid(port=1, vid=10)"),
    ex(f"{random.choice(CLIENT_CONTEXTS)} what IP does the macbook have", "router_get_dhcp_leases()"),
    ex(f"{random.choice(CLIENT_CONTEXTS)} find aa:bb:cc:01", "router_get_dhcp_leases()"),
    ex(f"{random.choice(COMBINED_CONTEXTS)} move port 2 to vlan 20", "switch_set_port_pvid(port=2, vid=20)"),
    ex(f"{random.choice(COMBINED_CONTEXTS)} add radio 3 to lan", "router_update_wifi_ssid(radio_idx=3, bss_idx=0, enabled=True)"),
    ex(f"{random.choice(COMBINED_CONTEXTS)} how many people on guest wifi", "router_get_wifi_config()"),
    ex(f"{random.choice(COMBINED_CONTEXTS)} who is on the guest network", "router_get_lan_clients()"),
]

# ── Combine and write ─────────────────────────────────────────────────────────

ALL_EXPANDED = (
    WIFI_EXAMPLES
    + VLAN_EXAMPLES
    + PORT_EXAMPLES
    + NETWORK_EXAMPLES
    + SYSTEM_EXAMPLES
    + SWITCH_SYSTEM_EXAMPLES
    + AMBIGUOUS_EXAMPLES
)

# Deduplicate by human input
seen: set = set()
deduped = []
for e in ALL_EXPANDED:
    h = e["conversations"][0]["value"].lower().strip()
    if h not in seen:
        seen.add(h)
        deduped.append(e)

# Shuffle deterministically
random.shuffle(deduped)

# 90/10 train/eval split, capped at 2 per tool in eval
from collections import defaultdict
by_tool: dict = defaultdict(list)
for e in deduped:
    g = e["conversations"][1]["value"]
    t = g.split("(")[0]
    by_tool[t].append(e)

train_exs, eval_exs = [], []
for tool, exs in by_tool.items():
    n_eval = min(2, max(1, len(exs) // 10))
    eval_exs.extend(exs[:n_eval])
    train_exs.extend(exs[n_eval:])

TRAINING_DIR.mkdir(parents=True, exist_ok=True)
train_file = TRAINING_DIR / f"router_expanded_{TODAY}.jsonl"
eval_file  = TRAINING_DIR / f"router_expanded_eval_{TODAY}.jsonl"

with open(train_file, "w") as f:
    for e in train_exs:
        f.write(json.dumps(e) + "\n")
with open(eval_file, "w") as f:
    for e in eval_exs:
        f.write(json.dumps(e) + "\n")

print(f"Expanded dataset:")
print(f"  Total examples (deduped): {len(deduped)}")
print(f"  Train: {len(train_exs)} → {train_file.name}")
print(f"  Eval:  {len(eval_exs)} → {eval_file.name}")
print(f"  Tools covered: {len(by_tool)}")
from collections import Counter
dist = Counter(e['conversations'][1]['value'].split('(')[0] for e in train_exs)
print("\n  Distribution:")
for tool, n in sorted(dist.items(), key=lambda x: -x[1]):
    print(f"    {n:3d}  {tool}")


if __name__ == "__main__":
    pass
