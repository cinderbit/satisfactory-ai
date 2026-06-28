"""
world_state.py

World-state reader (spec §4.3).

Reads resource node locations + purities from FRM, and optionally player
inventory / storage from the official dedicated-server API.

FRM docs: https://github.com/porisius/FRM
Official API: https://<host>:7777/api/v1/

All field names here are best-effort from the FRM source + community docs.
Run the VERIFY_FIRST checklist to confirm the actual shapes against your live
server before relying on this in production.
"""

from __future__ import annotations

import json
import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass
from enum import IntEnum
from typing import Any, Optional


class Purity(IntEnum):
    IMPURE = 1
    NORMAL = 2
    PURE   = 3

    @classmethod
    def from_str(cls, s: str) -> "Purity":
        mapping = {
            "impure": cls.IMPURE,
            "normal": cls.NORMAL,
            "pure":   cls.PURE,
        }
        return mapping.get(s.lower(), cls.NORMAL)


@dataclass
class ResourceNode:
    item_class: str      # e.g. "Desc_OreIron_C"
    purity: Purity
    x: float             # world X (Unreal units)
    y: float             # world Y
    z: float             # world Z


@dataclass
class StorageItem:
    item_class: str
    amount: float        # normalized (fluids already ÷1000 if needed)


def _get(url: str, timeout: int = 10, verify_ssl: bool = True) -> Any:
    """HTTP GET, returns parsed JSON."""
    ctx = None
    if not verify_ssl:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
        return json.loads(resp.read())


def _post(url: str, body: dict, timeout: int = 10, verify_ssl: bool = True) -> Any:
    """HTTP POST JSON, returns parsed JSON."""
    ctx = None
    if not verify_ssl:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
        return json.loads(resp.read())


class FRMClient:
    """Thin client for the Ficsit Remote Monitoring HTTP API.

    Default port is 8080 (FRM default).  Probe /frm/resourcesink for a
    health check; resource nodes are at /frm/resourcenode (verify against
    your actual FRM version — see VERIFY_FIRST.md).
    """

    def __init__(self, host: str = "localhost", port: int = 8080,
                 timeout: int = 10, verify_ssl: bool = True):
        self.base = f"http://{host}:{port}"
        self.timeout = timeout
        self.verify_ssl = verify_ssl

    def _get(self, path: str) -> Any:
        return _get(f"{self.base}{path}", self.timeout, self.verify_ssl)

    def resource_nodes(self) -> list[ResourceNode]:
        """Return all resource extraction nodes in the world."""
        raw = self._get("/frm/resourcenode")
        nodes: list[ResourceNode] = []
        for entry in raw:
            # Field names verified from FRM source; update if your version differs
            item_class = entry.get("ResourceClass") or entry.get("resource_class", "")
            purity_str = entry.get("Purity") or entry.get("purity", "normal")
            loc = entry.get("location") or entry.get("Location") or {}
            x = float(loc.get("x", loc.get("X", 0)))
            y = float(loc.get("y", loc.get("Y", 0)))
            z = float(loc.get("z", loc.get("Z", 0)))
            nodes.append(ResourceNode(
                item_class=item_class,
                purity=Purity.from_str(str(purity_str)),
                x=x, y=y, z=z,
            ))
        return nodes

    def player_inventory(self) -> list[StorageItem]:
        """Return items in the local player's inventory."""
        raw = self._get("/frm/player")
        items: list[StorageItem] = []
        for entry in raw:
            inv = entry.get("Inventory", [])
            for slot in inv:
                ic = slot.get("ItemClass") or slot.get("item_class", "")
                amt = float(slot.get("Amount") or slot.get("amount", 0))
                if ic:
                    items.append(StorageItem(item_class=ic, amount=amt))
        return items

    def storage_contents(self) -> list[StorageItem]:
        """Return aggregate contents across all storage containers FRM tracks."""
        raw = self._get("/frm/storagecontainer")
        items: list[StorageItem] = []
        for container in raw:
            for slot in container.get("Inventory", []):
                ic = slot.get("ItemClass", "")
                amt = float(slot.get("Amount", 0))
                if ic and amt > 0:
                    items.append(StorageItem(item_class=ic, amount=amt))
        return items

    def placed_buildings(self) -> list[dict]:
        """Return all buildable actors FRM knows about.

        Used to infer unlocked tiers from what's already built in the world.
        FRM endpoint: /frm/factory (returns all production buildings).
        Field names are best-effort — verify against your FRM version.
        """
        try:
            return self._get("/frm/factory") or []
        except Exception:
            return []

    def detect_miner_tier(self) -> int:
        """Scan placed buildings to find the highest miner tier in the world.

        Class name patterns (Unreal):
          Mk1: Build_MinerMk1_C
          Mk2: Build_MinerMk2_C
          Mk3: Build_MinerMk3_C

        Returns 1, 2, or 3.  Falls back to 1 if nothing is found (safest
        assumption — never suggests a machine the player might not have).
        """
        buildings = self.placed_buildings()
        highest = 1
        for b in buildings:
            cls = (
                b.get("ClassName") or b.get("className") or
                b.get("BuildingType") or b.get("building_type") or ""
            )
            if "MinerMk3" in cls or "Miner_Mk3" in cls:
                return 3
            if "MinerMk2" in cls or "Miner_Mk2" in cls:
                highest = max(highest, 2)
        return highest


class DedicatedServerClient:
    """Client for the official Satisfactory dedicated-server API (:7777/api/v1/).

    Uses HTTPS with a self-signed cert by default; set verify_ssl=False if
    you haven't installed a trusted cert (common for home servers).
    """

    def __init__(self, host: str, port: int = 7777,
                 token: Optional[str] = None, verify_ssl: bool = False):
        self.base = f"https://{host}:{port}/api/v1"
        self.token = token
        self.verify_ssl = verify_ssl

    def _post(self, function: str, data: dict | None = None) -> Any:
        body = {"function": function, "data": data or {}}
        url = self.base
        ctx = None
        if not self.verify_ssl:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
        payload = json.dumps(body).encode()
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=10, context=ctx) as resp:
            return json.loads(resp.read())

    def server_info(self) -> dict:
        return self._post("QueryServerState")

    def health(self) -> bool:
        try:
            self._post("HealthCheck", {"ClientCustomData": ""})
            return True
        except Exception:
            return False


def availability_check(frm_host: str = "localhost", frm_port: int = 8080) -> dict[str, bool]:
    """Quick liveness probe for use in the advisor CLI."""
    results: dict[str, bool] = {}
    try:
        _get(f"http://{frm_host}:{frm_port}/frm/resourcenode", timeout=3)
        results["frm"] = True
    except Exception:
        results["frm"] = False
    return results
