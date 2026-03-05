"""
Generate synthetic training data for the network-api-agent FunctionGemma router.

Usage:
    python generate_training_data.py
    python generate_training_data.py --count 300 --synonyms 6
    python generate_training_data.py --validate-only
    python generate_training_data.py --add-domain-examples

Outputs (appended, not overwritten):
    .microclaw/training/router_synthetic_<date>.jsonl   -- training set
    .microclaw/training/router_synthetic_eval_<date>.jsonl  -- held-out eval set
"""

import argparse
import json
import os
import sys
from datetime import date
from pathlib import Path

# Allow running from this directory
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
os.chdir(Path(__file__).parent)

from dotenv import load_dotenv
load_dotenv()

from openhoof import SyntheticDataGenerator
from tools import ALL_TOOLS


TRAINING_DIR = Path(".microclaw/training")
TODAY = date.today().isoformat()
TRAIN_FILE = TRAINING_DIR / f"router_synthetic_{TODAY}.jsonl"
EVAL_FILE  = TRAINING_DIR / f"router_synthetic_eval_{TODAY}.jsonl"

# ── Domain-specific examples the generator can't infer ───────────────────────
# These cover API jargon, abbreviations, and tricky intents.
# ALWAYS keep and grow this list — it's the high-value data the teacher model misses.

DOMAIN_EXAMPLES = [
    # Cradlepoint — jargon / abbreviations — status tools
    ("show lan subnets",              "router_get_lan_networks()"),
    ("what DHCP scopes are configured", "router_get_lan_networks()"),
    ("lan network settings",          "router_get_lan_networks()"),
    ("router cpu usage",              "router_get_system_status()"),
    ("how long has router been up",   "router_get_system_status()"),
    ("router memory usage",           "router_get_system_status()"),
    ("routing table",                 "router_get_routing_table()"),
    ("static routes",                 "router_get_routing_table()"),
    ("show gateway routes",           "router_get_routing_table()"),
    ("firewall settings",             "router_get_firewall_config()"),
    ("ALG settings",                  "router_get_firewall_config()"),
    ("show vlans on router",          "router_get_vlan_config()"),
    ("router vlan list",              "router_get_vlan_config()"),
    ("remove vlan 100 from router",   "router_delete_vlan(idx=0)"),
    ("delete router vlan at index 1", "router_delete_vlan(idx=1)"),
    ("change dhcp range on lan 0",    "router_update_lan(idx=0, dhcp_start=100, dhcp_end=200)"),
    ("update lan gateway to 10.0.0.1","router_update_lan(idx=0, ip_address='10.0.0.1')"),
    ("show wan ip",                   "router_get_wan_status()"),
    ("what's my WAN IP",              "router_get_wan_status()"),
    ("check internet",                "router_get_wan_status()"),
    ("uplink status",                 "router_get_wan_status()"),
    ("carrier info",                  "router_get_wan_status()"),
    ("check for PCI-DSS lockout",     "router_get_system_config()"),
    ("how many failed logins",        "router_get_system_config()"),
    ("admin timeout setting",         "router_get_system_config()"),
    ("NTP config",                    "router_get_system_config()"),
    ("who's on the network",          "router_get_lan_clients()"),
    ("list connected devices",        "router_get_lan_clients()"),
    ("how many devices online",       "router_get_lan_clients()"),
    ("dhcp table",                    "router_get_dhcp_leases()"),
    ("ip to mac mapping",             "router_get_dhcp_leases()"),
    ("dns host override for myserver 10.0.0.5", "router_add_dns_host(hostname='myserver', ip_address='10.0.0.5')"),
    ("add static route 10.1.0.0/24 via 192.168.0.254", "router_add_static_route(ip_network='10.1.0.0/24', gateway='192.168.0.254')"),
    ("disable WAN ping",              "router_update_firewall(wan_ping=False)"),
    ("allow ping from internet",      "router_update_firewall(wan_ping=True)"),
    ("enable anti-spoof",             "router_update_firewall(anti_spoof=True)"),
    ("create vlan 100 on router lan", "router_create_vlan(vid=100, uid='vlan100', mode='lan')"),
    ("add wan vlan 200",              "router_create_vlan(vid=200, uid='vlan200', mode='wan')"),
    ("LLDP neighbors",                "router_get_lldp_neighbors()"),
    ("what's plugged into each port", "router_get_lldp_neighbors()"),
    ("show bss 0 on radio 1",         "router_get_wifi_config()"),
    ("5GHz wifi settings",            "router_get_wifi_config()"),
    ("hide guest SSID",               "router_update_wifi_ssid(radio_idx=0, bss_idx=1, hidden=True)"),
    ("change wifi password to securepass123", "router_update_wifi_ssid(radio_idx=0, bss_idx=0, wpapsk='securepass123')"),
    ("disable guest network",        "router_update_wifi_ssid(radio_idx=0, bss_idx=1, enabled=False)"),
    ("show error logs",               "router_get_logs(level='error')"),
    ("critical alerts",               "router_get_logs(level='critical')"),
    ("all logs",                      "router_get_logs()"),
    ("restart the router",            "router_reboot()"),
    ("power cycle router",            "router_reboot()"),

    # Netgear switch — jargon / abbreviations
    ("switch port states",            "switch_get_port_status()"),
    ("which ports are up",            "switch_get_port_status()"),
    ("port 3 link state",             "switch_get_port_status()"),
    ("switch vlans",                  "switch_get_vlan_config()"),
    ("add vlan 100 to switch",        "switch_create_vlan(vid=100)"),
    ("create switch vlan 20",         "switch_create_vlan(vid=20)"),
    ("remove vlan 100 from switch",   "switch_delete_vlan(vid=100)"),
    ("set port 3 PVID to 100",        "switch_set_port_pvid(port=3, vid=100)"),
    ("access vlan on port 2 is 20",   "switch_set_port_pvid(port=2, vid=20)"),
    ("untagged vlan 100 on port 1 only", "switch_set_vlan_membership(vid=100, port_config='13333')"),
    ("ports 1 and 2 untagged in vlan 10", "switch_set_vlan_membership(vid=10, port_config='11333')"),
    ("trunk port 5 tagged vlan 100",  "switch_set_vlan_membership(vid=100, port_config='33332')"),
    ("port 1 untagged port 5 tagged vlan 20", "switch_set_vlan_membership(vid=20, port_config='13332')"),
    ("switch port counters",          "switch_get_port_stats()"),
    ("tx rx bytes per port",          "switch_get_port_stats()"),
    ("switch firmware version",       "switch_get_system_info()"),
    ("switch mac address",            "switch_get_system_info()"),
    ("reboot switch",                 "switch_reboot()"),
    ("restart switch",                "switch_reboot()"),
]


def fmt_example(human: str, gpt: str) -> dict:
    return {"conversations": [
        {"from": "human", "value": human},
        {"from": "gpt",   "value": gpt},
    ]}


def load_existing(path: Path) -> list:
    if not path.exists():
        return []
    items = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                items.append(json.loads(line))
    return items


def check_conflicts(examples: list) -> list:
    """Return list of (human, gpt1, gpt2) tuples where same input → different output."""
    seen: dict = {}
    conflicts = []
    for ex in examples:
        convs = ex.get("conversations", [])
        if len(convs) < 2:
            continue
        h = convs[0]["value"].lower().strip()
        g = convs[1]["value"].strip()
        if h in seen and seen[h] != g:
            conflicts.append((h, seen[h], g))
        else:
            seen[h] = g
    return conflicts


def distribution(examples: list) -> dict:
    from collections import Counter
    counts = Counter()
    for ex in examples:
        convs = ex.get("conversations", [])
        if len(convs) >= 2:
            gpt = convs[1]["value"]
            tool = gpt.split("(")[0]
            counts[tool] += 1
    return dict(counts.most_common())


def validate_file(path: Path):
    print(f"\nValidating {path} ...")
    examples = load_existing(path)
    print(f"  Total examples: {len(examples)}")

    conflicts = check_conflicts(examples)
    if conflicts:
        print(f"  ⚠️  CONFLICTS ({len(conflicts)}):")
        for h, g1, g2 in conflicts[:10]:
            print(f"     '{h}' → '{g1}' vs '{g2}'")
    else:
        print("  ✅ No conflicts")

    dist = distribution(examples)
    print(f"\n  Coverage ({len(dist)} tools):")
    for tool, n in dist.items():
        bar = "█" * min(n // 5, 30)
        warn = "  ⚠️  LOW" if n < 8 else ""
        print(f"    {n:4d}  {bar:<30s}  {tool}{warn}")

    missing = [t.get("function", t).get("name") for t in ALL_TOOLS
               if t.get("function", t).get("name") not in dist]
    if missing:
        print(f"\n  ⚠️  Tools with NO examples:")
        for m in missing:
            print(f"       {m}")
    else:
        print(f"\n  ✅ All {len(ALL_TOOLS)} tools covered")


def generate(count: int, synonyms: int, teacher_model: str, endpoint: str):
    TRAINING_DIR.mkdir(parents=True, exist_ok=True)

    print(f"\nGenerating ~{count} examples (target total, synonym explosion × {synonyms})")
    print(f"Teacher: {teacher_model}  Endpoint: {endpoint}")
    print(f"Output:  {TRAIN_FILE}")

    gen = SyntheticDataGenerator(
        model=teacher_model,
        endpoint=endpoint,
    )

    stats = gen.generate_router(
        tools=ALL_TOOLS,
        count=count,
        output_dir=str(TRAINING_DIR),
        output_format="text",         # tool_name(param=val) — best for FunctionGemma 270M
        synonyms_per_example=synonyms,
        holdout_pct=0.1,
        verbose=True,
    )

    return stats


def add_domain_examples():
    """Append hand-curated domain examples to the training file."""
    import random as _random
    TRAINING_DIR.mkdir(parents=True, exist_ok=True)

    # Shuffle before splitting so we don't always lose the last tools to eval.
    # Domain examples are ordered by tool — without shuffling, the last N tools
    # (e.g. switch_reboot) always end up in eval only.
    shuffled = list(DOMAIN_EXAMPLES)
    _random.seed(99)  # deterministic for reproducibility
    _random.shuffle(shuffled)

    # Per-tool capped eval split (max 1 per tool) — mirrors the synth generator fix
    from collections import defaultdict
    by_tool: dict = defaultdict(list)
    for h, g in shuffled:
        tool = g.split("(")[0]
        by_tool[tool].append((h, g))

    train_exx_raw, eval_exx_raw = [], []
    for tool, exs in by_tool.items():
        eval_exx_raw.append(exs[0])     # 1 per tool to eval
        train_exx_raw.extend(exs[1:])   # rest to train

    train_exx = [fmt_example(h, g) for h, g in train_exx_raw]
    eval_exx  = [fmt_example(h, g) for h, g in eval_exx_raw]

    with open(TRAIN_FILE, "a") as f:
        for ex in train_exx:
            f.write(json.dumps(ex) + "\n")

    with open(EVAL_FILE, "a") as f:
        for ex in eval_exx:
            f.write(json.dumps(ex) + "\n")

    print(f"\n✅ Domain examples appended:")
    print(f"   {len(train_exx)} train  → {TRAIN_FILE}")
    print(f"   {len(eval_exx)} eval   → {EVAL_FILE}")


def main():
    parser = argparse.ArgumentParser(description="Generate FunctionGemma training data")
    parser.add_argument("--count",          type=int,  default=15,  help="Examples per tool (default 15)")
    parser.add_argument("--synonyms",       type=int,  default=8,   help="Synonym rephrasings per intent (default 8)")
    parser.add_argument("--validate-only",  action="store_true",    help="Only validate existing files")
    parser.add_argument("--add-domain-examples", action="store_true", help="Append hand-curated domain examples only")
    parser.add_argument("--skip-domain",    action="store_true",    help="Skip domain examples after generation")
    args = parser.parse_args()

    endpoint = os.getenv("LLAMAFARM_ENDPOINT", "http://localhost:11540/v1")
    teacher  = os.getenv("TEACHER_MODEL", "unsloth/Qwen3-1.7B-GGUF")

    if args.validate_only:
        # Find the file to validate
        target = None
        if TRAIN_FILE.exists():
            target = TRAIN_FILE
        else:
            files = sorted(TRAINING_DIR.glob("router_synthetic_[0-9]*.jsonl"))
            if files:
                target = files[-1]
        if target:
            validate_file(target)
            # Also run schema validation via SyntheticDataGenerator
            print(f"\nRunning schema validation...")
            SyntheticDataGenerator.validate_file(str(target), ALL_TOOLS)
        else:
            print("No training files found yet.")
        return

    if args.add_domain_examples:
        add_domain_examples()
        return

    # Generate synthetic data
    generate(args.count, args.synonyms, teacher, endpoint)

    # Always append domain examples after generation
    if not args.skip_domain:
        print("\nAppending domain-specific examples...")
        add_domain_examples()

    # Validate the combined output
    validate_file(TRAIN_FILE)


if __name__ == "__main__":
    main()
