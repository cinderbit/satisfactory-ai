"""
factory_geometry.py

Machine footprint and connection-port geometry for Satisfactory, extracted from
the FactorySpawner mod (MIT License, Copyright (c) 2025 Simon Steinhauser).

This is the spatial foundation for a siting/layout planner. It captures, as pure
data:
  - every machine's footprint (width x length, in 1m grid units)
  - the indexed belt/pipe connection ports on each machine, with their offsets
  - the multiple "port variants" a machine exposes depending on how many solid
    (belt) vs liquid (pipe) inputs/outputs its recipe needs
  - the coordinate conventions the mod uses when laying out a row of machines

UNITS / COORDINATE CONVENTIONS (mirrors the mod):
  - Config Width/Length are in GRID UNITS of 1m. The mod multiplies by 100 to get
    Unreal "uu" (centimeters): 1 grid unit = 100 uu = 1 meter.
  - A "row" is N copies of one machine type laid side by side along +X.
    XCursor advances by (Width * 100) per machine.
    YCursor advances by (InputLength * 100) before a row and (OutputLength * 100)
    after it, so rows stack along +Y with belt-routing space between them.
  - Connector.LocationX is an along-width offset (grid units) of the port from the
    machine center. LocationY is a height/depth index used for stacked ports.
  - Port "Index" is the position of that connector within the actor's connection
    component array (the order GetConnections returns them in-game).

PORT VARIANTS:
  A machine lists several InputConnections / OutputConnections entries. Which one
  is used depends on the recipe: the mod counts solid ingredients (-> belt ports)
  and liquid ingredients (-> pipe ports), then selects a variant via:

      index = (MaxPipe - NeededPipe) * (MaxBelt + 1) + (MaxBelt - NeededBelt)

  Variants are ordered by pipe count (desc), then belt count (desc). Variant 0 is
  always the fully-populated one (max belts + max pipes), which is what you use
  when you don't yet know the recipe's fluid/solid split.
"""

from __future__ import annotations
from dataclasses import dataclass, field


GRID_UU = 100  # 1 grid unit (1 meter) = 100 Unreal units (cm)


@dataclass(frozen=True)
class Connector:
    """A single belt or pipe port on a machine.

    index:      position in the machine's connection-component array in-game
    location_x: along-width offset from machine center, in grid units
    location_y: height/stack index for vertically stacked ports, in grid units
    """
    index: int
    location_x: int
    location_y: int = 0


@dataclass(frozen=True)
class MachineConnections:
    """One port-variant: the set of belt + pipe ports active for some recipe shape.

    length: the along-Y extent (grid units) this variant occupies, used by the
            layout cursor to reserve routing space before/after the machine.
    """
    length: int
    belt: tuple[Connector, ...] = ()
    pipe: tuple[Connector, ...] = ()


@dataclass(frozen=True)
class MachineConfig:
    """Full geometry for one machine type."""
    width: int
    length: int
    inputs: tuple[MachineConnections, ...]   # index 0 = max belts + max pipes
    outputs: tuple[MachineConnections, ...]

    def max_belt_inputs(self) -> int:
        return len(self.inputs[0].belt)

    def max_pipe_inputs(self) -> int:
        return len(self.inputs[0].pipe)

    def max_belt_outputs(self) -> int:
        return len(self.outputs[0].belt)

    def max_pipe_outputs(self) -> int:
        return len(self.outputs[0].pipe)


def port_variant_index(max_belt: int, max_pipe: int,
                       needed_belt: int, needed_pipe: int) -> int:
    """Select the port-variant index for a recipe's solid/liquid port needs.

    Mirrors GetPortVariantIndex in the mod. Variants ordered by pipe count (desc),
    then belt count (desc).
    """
    num_belt_variants = max_belt + 1
    belt_offset = max_belt - needed_belt
    pipe_offset = max_pipe - needed_pipe
    return pipe_offset * num_belt_variants + belt_offset


def C(index: int, x: int, y: int = 0) -> Connector:          # noqa: N802 (terse helper)
    return Connector(index, x, y)


def MC(length: int, belt=(), pipe=()) -> MachineConnections:  # noqa: N802
    return MachineConnections(length, tuple(belt), tuple(pipe))


# ---------------------------------------------------------------------------
# The machine geometry table. Values transcribed verbatim from MachineConfigList
# in BuildPlanGenerator.cpp (FactorySpawner, MIT). Comments mark the solid/liquid
# port-variant each entry corresponds to where the source annotated them.
# ---------------------------------------------------------------------------
MACHINE_CONFIG: dict[str, MachineConfig] = {
    "Constructor": MachineConfig(
        8, 10,
        inputs=(MC(9, belt=[C(1, 0)]),),
        outputs=(MC(9, belt=[C(0, 0)]),),
    ),
    "Smelter": MachineConfig(
        5, 10,
        inputs=(MC(9, belt=[C(0, 0)]),),
        outputs=(MC(8, belt=[C(1, 0)]),),
    ),
    "Foundry": MachineConfig(
        10, 10,
        inputs=(MC(11, belt=[C(2, -2), C(0, 2, 2)]),),
        outputs=(MC(8, belt=[C(1, -2)]),),
    ),
    "Assembler": MachineConfig(
        9, 16,
        inputs=(MC(14, belt=[C(1, -2), C(2, 2, 2)]),),
        outputs=(MC(11, belt=[C(0, 0)]),),
    ),
    "OilRefinery": MachineConfig(
        10, 30,
        inputs=(
            MC(17, belt=[C(0, -2, 4)], pipe=[C(1, 2)]),  # 1 solid + 1 liquid
            MC(15, pipe=[C(1, 2)]),                       # 0 solid + 1 liquid
            MC(15, belt=[C(0, -2)]),                      # 1 solid + 0 liquid
        ),
        outputs=(
            MC(17, belt=[C(1, -2, 4)], pipe=[C(0, 2)]),
            MC(15, pipe=[C(0, 2)]),
            MC(15, belt=[C(1, -2)]),
        ),
    ),
    "Blender": MachineConfig(
        18, 16,
        inputs=(
            MC(15, belt=[C(1, 2, 6), C(2, 6, 8)], pipe=[C(2, -6), C(0, -2, 2)]),  # 2S,2L
            MC(15, belt=[C(1, 2, 6)],            pipe=[C(2, -6), C(0, -2, 2)]),  # 1S,2L
            MC(14,                                pipe=[C(2, -6), C(0, -2, 2)]),  # 0S,2L
            MC(15, belt=[C(1, 2, 4), C(2, 6, 6)], pipe=[C(2, -6)]),              # 2S,1L
            MC(15, belt=[C(1, 2, 4)],            pipe=[C(2, -6)]),              # 1S,1L
            MC(12,                                pipe=[C(2, -6)]),              # 0S,1L
        ),
        outputs=(
            MC(15, belt=[C(0, -2, 4)], pipe=[C(1, -6)]),
            MC(12,                      pipe=[C(1, -6)]),
            MC(12, belt=[C(0, -2)]),
        ),
    ),
    "Manufacturer": MachineConfig(
        18, 20,
        inputs=(
            MC(17, belt=[C(4, -6), C(2, -2, 2), C(1, 2, 4), C(0, 6, 6)]),  # 4 solid
            MC(17, belt=[C(4, -6), C(2, -2, 2), C(1, 2, 4)]),             # 3 solid
        ),
        outputs=(MC(13, belt=[C(3, 0)]),),
    ),
    "Converter": MachineConfig(
        16, 16,
        inputs=(
            MC(15, belt=[C(0, -2), C(2, 2, 2)]),  # 2 solid
            MC(12, belt=[C(0, -2)]),             # 1 solid
            MC(8),                                # 0 solid
        ),
        outputs=(
            MC(15, belt=[C(1, 2, 4)], pipe=[C(0, -2)]),
            MC(12,                     pipe=[C(0, -2)]),
            MC(12, belt=[C(1, 2)]),
        ),
    ),
    "ParticleAccelerator": MachineConfig(
        37, 35,
        inputs=(
            MC(19, belt=[C(0, 12, 4), C(1, 16, 6)], pipe=[C(0, 8)]),  # 2S,1L
            MC(19, belt=[C(0, 12, 4)],              pipe=[C(0, 8)]),  # 1S,1L
            MC(16,                                   pipe=[C(0, 8)]),  # 0S,1L
            MC(19, belt=[C(0, 12, 0), C(1, 16, 2)]),                  # 2S,0L
            MC(17, belt=[C(0, 12)]),                                  # 1S,0L
        ),
        outputs=(MC(17, belt=[C(2, 14)]),),
    ),
    "QuantumEncoder": MachineConfig(
        22, 50,
        inputs=(MC(33, belt=[C(2, -6, 4), C(1, -2, 6), C(3, 2, 8)], pipe=[C(0, 6)]),),
        outputs=(MC(29, belt=[C(0, -2, 4)], pipe=[C(1, 2)]),),
    ),
    "CoalGenerator": MachineConfig(
        10, 26,
        inputs=(MC(20, belt=[C(0, -2, 4)], pipe=[C(0, 2)]),),
        outputs=(MC(13),),
    ),
    "FuelGenerator": MachineConfig(
        20, 20,
        inputs=(MC(14, pipe=[C(0, 0)]),),
        outputs=(MC(10),),
    ),
    "NuclearReactor": MachineConfig(
        36, 43,
        inputs=(MC(28, belt=[C(0, 2, 2)]),),
        outputs=(MC(22, belt=[C(1, -2, 0)]),),
    ),
    "Packager": MachineConfig(
        8, 8,
        inputs=(
            MC(9, belt=[C(1, 0)], pipe=[C(0, 0, 2)]),
            MC(9,                  pipe=[C(0, 0, 2)]),
            MC(9, belt=[C(1, 0)]),
        ),
        outputs=(
            MC(9, belt=[C(0, 0)], pipe=[C(1, 0, 2)]),
            MC(9,                  pipe=[C(1, 0, 2)]),
            MC(9, belt=[C(0, 0)]),
        ),
    ),
}


def row_footprint(machine: str, count: int, variant: int = 0) -> tuple[int, int]:
    """Footprint (width_uu, length_uu) of a row of `count` machines of one type.

    Width grows along +X with the count; length is input+output reserve along +Y.
    Useful for the siting planner to reserve ground space before committing a build.
    """
    cfg = MACHINE_CONFIG[machine]
    in_len = cfg.inputs[variant].length if variant < len(cfg.inputs) else cfg.inputs[0].length
    out_len = cfg.outputs[variant].length if variant < len(cfg.outputs) else cfg.outputs[0].length
    width_uu = cfg.width * GRID_UU * count
    length_uu = (in_len + out_len) * GRID_UU
    return width_uu, length_uu


if __name__ == "__main__":
    # Quick sanity demo: footprint of a screws row (Constructors making Screw).
    for n in (1, 4, 8):
        w, l = row_footprint("Constructor", n)
        print(f"{n}x Constructor row: {w/100:.0f}m wide x {l/100:.0f}m deep "
              f"({w} x {l} uu)")
    # Show variant selection for a 1-solid-input, 0-liquid recipe on a Constructor:
    cfg = MACHINE_CONFIG["Constructor"]
    idx = port_variant_index(cfg.max_belt_inputs(), cfg.max_pipe_inputs(), 1, 0)
    print(f"Constructor input variant for (1 solid, 0 liquid): {idx}")
