"""
check_frm.py

Probe a live FRM endpoint and report whether its JSON shapes match what
world_state.py expects. Turns VERIFY_FIRST.md §2 into one command.

Usage:
    python tools/check_frm.py                 # localhost:8080
    python tools/check_frm.py 192.168.1.10    # custom host
    python tools/check_frm.py localhost 8080  # host + port

Exit code 0 if all probed endpoints look usable, 1 otherwise.
"""

from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

# Allow running from anywhere
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from world_state import FRMClient, discovered_nodes  # noqa: E402


def _get(url: str, timeout: int = 5):
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def _keys_of_first(data) -> list[str]:
    if isinstance(data, list) and data and isinstance(data[0], dict):
        return sorted(data[0].keys())
    return []


def probe(host: str, port: int) -> bool:
    base = f"http://{host}:{port}"
    ok = True

    print(f"Probing FRM at {base}\n" + "=" * 50)

    endpoints = {
        "/getResourceNode": ("resource nodes", ["ClassName", "Purity", "Exploited", "location.x"]),
        "/getExtractor":    ("placed miners/extractors", ["ClassName", "location.x"]),
        "/getRadarTower":   ("radar towers", ["location.x"]),
        "/getFactory":      ("production buildings", ["ClassName", "location.x"]),
        "/getStorageInv":   ("storage containers", ["ClassName", "Inventory[].ClassName"]),
    }

    for path, (label, expected) in endpoints.items():
        try:
            data = _get(f"{base}{path}")
        except Exception as e:
            print(f"  [FAIL] {path:<22} unreachable: {e}")
            ok = False
            continue

        n = len(data) if isinstance(data, list) else "?"
        keys = _keys_of_first(data)
        print(f"  [ OK ] {path:<22} {n} entries")
        if keys:
            print(f"         actual keys: {keys}")
        print(f"         world_state expects (any casing): {expected}")
        print()

    # Now run the parsed pipeline and report what we got
    print("Parsed via FRMClient" + "\n" + "-" * 50)
    client = FRMClient(host, port)
    try:
        nodes = client.resource_nodes()
        towers = client.radar_towers()
        extractors = client.placed_extractors()
        tier = client.detect_miner_tier()
        disc = discovered_nodes(nodes, extractors, towers)

        print(f"  resource_nodes():    {len(nodes)} parsed")
        if nodes and all(n.x == 0 and n.y == 0 for n in nodes):
            print("    [WARN] all coords are 0 — location field name likely mismatched")
            ok = False
        if nodes and all(not n.item_class for n in nodes):
            print("    [WARN] all item_class empty — ResourceClass field name mismatched")
            ok = False
        print(f"  radar_towers():      {len(towers)} parsed")
        print(f"  placed_extractors(): {len(extractors)} parsed")
        print(f"  detect_miner_tier(): Mk{tier}")
        print(f"  discovered_nodes():  {len(disc)} of {len(nodes)} discovered")
        if nodes and not disc:
            print("    [WARN] 0 discovered — no radar towers and no miners detected,")
            print("           or field mismatches above. Place a radar tower/miner.")
    except Exception as e:
        print(f"  [FAIL] pipeline error: {e}")
        ok = False

    print("\n" + "=" * 50)
    print("RESULT:", "[PASS] FRM looks usable" if ok else "[FAIL] issues found — see warnings above")
    return ok


def main():
    host = sys.argv[1] if len(sys.argv) > 1 else "localhost"
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 8080
    sys.exit(0 if probe(host, port) else 1)


if __name__ == "__main__":
    main()
