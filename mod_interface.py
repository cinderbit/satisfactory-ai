"""
mod_interface.py

HTTP client for the forked FactorySpawner mod (Step 5).

The forked mod exposes a single endpoint:
  POST http://<host>:<port>/build
  Body: BuildRequest JSON (see schema below)

This module builds that payload from the advisor's approved plan and POSTs it.
The mod validates that all referenced resource nodes are in the player's
discovered set before spawning anything.
"""

from __future__ import annotations

import json
import urllib.request
import urllib.error
from dataclasses import dataclass, asdict
from typing import Optional

from recipe_planner import PlanResult
from miner_planner import MinerPlan


# ---------------------------------------------------------------------------
# Token schema — the contract between this client and the mod
# ---------------------------------------------------------------------------

@dataclass
class ExtractorToken:
    """Place one miner/extractor on a specific resource node."""
    machineType: str       # "Miner" | "WaterExtractor" | "ResourceExtractor"
    minerTier: int         # 1/2/3
    itemClass: str         # e.g. "Desc_OreIron_C"
    clockSpeed: float      # 1.0–250.0 (percent)
    nodeX: float           # world coordinates of the resource node
    nodeY: float
    nodeZ: float


@dataclass
class ManufacturerToken:
    """Place a row of one machine type running a given recipe."""
    machineType: str       # e.g. "Smelter", "Constructor"
    count: int
    recipe: str            # display name or class name — mod accepts both
    clockSpeed: float = 100.0


@dataclass
class BuildRequest:
    """Full payload POSTed to /build on the forked mod."""
    extractors: list[ExtractorToken]
    manufacturers: list[ManufacturerToken]
    # Origin for the manufacturer rows (top-left corner of the factory block).
    # The mod builds outward from here along +X, stacking rows along +Y.
    originX: float
    originY: float
    originZ: float
    # If true the mod writes a Blueprint and destroys the source buildables
    # (player stamps it). If false it places directly (hands-off).
    writeBlueprint: bool = False


def build_request(
    result: PlanResult,
    miner_plan: Optional[MinerPlan],
    origin_x: float,
    origin_y: float,
    origin_z: float,
    write_blueprint: bool = False,
) -> BuildRequest:
    """Assemble a BuildRequest from the planner outputs."""
    extractors: list[ExtractorToken] = []
    if miner_plan:
        for a in miner_plan.assignments:
            extractors.append(ExtractorToken(
                machineType=a.extractor_type,
                minerTier=a.miner_tier,
                itemClass=a.item_class,
                clockSpeed=a.clock_pct,
                nodeX=a.node.x,
                nodeY=a.node.y,
                nodeZ=a.node.z,
            ))

    manufacturers: list[ManufacturerToken] = []
    for row in result.token_rows:
        manufacturers.append(ManufacturerToken(
            machineType=row.machine_type,
            count=row.count,
            recipe=row.recipe_name,
        ))

    return BuildRequest(
        extractors=extractors,
        manufacturers=manufacturers,
        originX=origin_x,
        originY=origin_y,
        originZ=origin_z,
        writeBlueprint=write_blueprint,
    )


class ModClient:
    """HTTP client for the forked FactorySpawner mod endpoint."""

    def __init__(self, host: str = "localhost", port: int = 8082, timeout: int = 30):
        self.base = f"http://{host}:{port}"
        self.timeout = timeout

    def health(self) -> bool:
        try:
            req = urllib.request.Request(f"{self.base}/health")
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status == 200
        except Exception:
            return False

    def send(self, request: BuildRequest) -> dict:
        """POST the build request to the mod. Returns the mod's response dict."""
        payload = json.dumps(asdict(request)).encode()
        req = urllib.request.Request(
            f"{self.base}/build",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            body = e.read().decode(errors="replace")
            raise RuntimeError(f"Mod returned {e.code}: {body}") from e
        except urllib.error.URLError as e:
            raise RuntimeError(
                f"Could not reach mod at {self.base}/build — "
                f"is the forked FactorySpawner running? ({e.reason})"
            ) from e

    def send_and_report(self, request: BuildRequest) -> None:
        """Send the request and print a human-readable result."""
        print(f"\n[Mod] POSTing build request to {self.base}/build ...")
        print(f"      {len(request.extractors)} extractor(s), "
              f"{len(request.manufacturers)} manufacturer row(s)")
        print(f"      Origin: X={request.originX:.0f} Y={request.originY:.0f} "
              f"Z={request.originZ:.0f}")
        resp = self.send(request)
        status = resp.get("status", "unknown")
        message = resp.get("message", "")
        if status == "ok":
            print(f"[Mod] Success. {message}")
        else:
            print(f"[Mod] Error: {message}")
            errors = resp.get("errors", [])
            for err in errors:
                print(f"      - {err}")
