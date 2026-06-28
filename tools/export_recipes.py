"""
export_recipes.py

Normalize the game's raw Docs export (per-locale, e.g. en-US.json) into the
flat recipe schema recipe_planner.load_recipes() expects.

The raw file is:
  - UTF-16 LE (BOM), a JSON array of {NativeClass, Classes[]} buckets.
  - Recipes live in the bucket whose NativeClass ends with `FGRecipe'`.
  - Ingredient/product lists are packed strings:
      ((ItemClass="...'/Game/.../Desc_OreIron.Desc_OreIron_C'",Amount=1),...)
  - Duration field is the (CSS-typo) `mManufactringDuration`.
  - Producer field `mProducedIn` is a packed list of Build_*_C paths (plus
    BuildGun/Workshop entries we ignore).

Output schema (one object per recipe):
  {ClassName, DisplayName, Ingredients[{Item,Amount}], Products[{Item,Amount}],
   ManufacturingDuration, ProducedIn[], IsAlternate}

Fluid amounts are left as-is (×1000 in the data); recipe_planner normalizes them.

Usage:
    python tools/export_recipes.py <raw_docs.json> [-o recipes.json] [--verify]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# (ItemClass=<blob without comma>,Amount=<number>)
_PAIR = re.compile(r"ItemClass=([^,]+),Amount=([0-9.]+)")
# last `.Something_C` token inside a class path blob
_SHORT = re.compile(r"\.([A-Za-z0-9_]+_C)")
# producer build classes
_BUILD = re.compile(r"(Build_[A-Za-z0-9_]+_C)")


def _num(s: str):
    f = float(s)
    return int(f) if f.is_integer() else f


def _parse_items(packed: str) -> list[dict]:
    out: list[dict] = []
    if not packed:
        return out
    for m in _PAIR.finditer(packed):
        blob, amt = m.group(1), m.group(2)
        shorts = _SHORT.findall(blob)
        if not shorts:
            continue
        out.append({"Item": shorts[-1], "Amount": _num(amt)})
    return out


def _read_raw(path: Path) -> list:
    head = path.read_bytes()[:2]
    enc = "utf-16" if head == b"\xff\xfe" or head == b"\xfe\xff" else "utf-8-sig"
    return json.loads(path.read_text(encoding=enc))


def normalize(raw: list) -> list[dict]:
    recipes: list[dict] = []
    for bucket in raw:
        native = bucket.get("NativeClass", "")
        if not native.rstrip("'").endswith("FGRecipe"):
            continue
        for cls in bucket.get("Classes", []):
            class_name = cls.get("ClassName", "")
            display = cls.get("mDisplayName", class_name)
            ingredients = _parse_items(cls.get("mIngredients", ""))
            products = _parse_items(cls.get("mProduct", ""))
            if not products:
                continue  # not a producible recipe
            produced_in = _BUILD.findall(cls.get("mProducedIn", ""))
            # Duration field name has varied across builds (CSS typos):
            # mManufactoringDuration (1.x) / mManufactringDuration / mManufacturingDuration
            dur_raw = (cls.get("mManufactoringDuration")
                       or cls.get("mManufactringDuration")
                       or cls.get("mManufacturingDuration") or "0")
            duration = float(dur_raw or 0)
            is_alt = class_name.startswith("Recipe_Alternate") or display.startswith("Alternate")
            recipes.append({
                "ClassName": class_name,
                "DisplayName": display,
                "Ingredients": ingredients,
                "Products": products,
                "ManufacturingDuration": duration,
                "ProducedIn": produced_in,
                "IsAlternate": is_alt,
            })
    return recipes


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("raw", help="raw Docs export (e.g. en-US.json)")
    ap.add_argument("-o", "--out", default="recipes.json")
    ap.add_argument("--verify", action="store_true",
                    help="print spot-checks (Screw/Iron Rod/Iron Ingot + a fluid)")
    args = ap.parse_args()

    raw = _read_raw(Path(args.raw))
    recipes = normalize(raw)
    Path(args.out).write_text(json.dumps(recipes, indent=2), encoding="utf-8")

    n_alt = sum(1 for r in recipes if r["IsAlternate"])
    print(f"Wrote {len(recipes)} recipes ({n_alt} alternate) -> {args.out}")

    if args.verify:
        by_class = {r["ClassName"]: r for r in recipes}
        print("\nSpot-checks (rate = product_amount / duration * 60):")
        for cn in ("Recipe_IngotIron_C", "Recipe_IronRod_C", "Recipe_Screw_C"):
            r = by_class.get(cn)
            if not r:
                print(f"  [MISS] {cn} not found")
                continue
            p = r["Products"][0]
            ing = ", ".join(f"{i['Amount']}x {i['Item']}" for i in r["Ingredients"])
            rate = p["Amount"] / r["ManufacturingDuration"] * 60
            print(f"  {cn}: {ing} -> {p['Amount']}x {p['Item']} "
                  f"in {r['ManufacturingDuration']}s = {rate:.1f}/min "
                  f"[{','.join(r['ProducedIn']) or 'NO-MACHINE'}]")
        # a fluid recipe to confirm x1000 scaling is present in raw amounts
        fluid = next((r for r in recipes
                      if any(i["Item"] == "Desc_Water_C" for i in r["Ingredients"])), None)
        if fluid:
            water = next(i for i in fluid["Ingredients"] if i["Item"] == "Desc_Water_C")
            print(f"\n  Fluid check: {fluid['ClassName']} uses Water Amount={water['Amount']} "
                  f"(expect x1000, e.g. 18000 = 18 m^3)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
