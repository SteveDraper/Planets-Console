"""Component display names for annotated prior weight YAML output."""

from __future__ import annotations

from dataclasses import dataclass, field

from api.models.game import TurnInfo


@dataclass(frozen=True)
class ComponentNameCatalog:
    hulls: dict[int, str]
    engines: dict[int, str]
    beams: dict[int, str]
    torpedoes: dict[int, str]
    races: dict[int, str]

    def hull_name(self, hull_id: int) -> str | None:
        return self.hulls.get(hull_id)

    def engine_name(self, engine_id: int) -> str | None:
        return self.engines.get(engine_id)

    def beam_name(self, beam_id: int) -> str | None:
        return self.beams.get(beam_id)

    def torpedo_name(self, torpedo_id: int) -> str | None:
        return self.torpedoes.get(torpedo_id)

    def race_name(self, race_id: int) -> str | None:
        return self.races.get(race_id)


@dataclass
class ComponentNameCatalogBuilder:
    """Accumulates id -> name mappings from turn catalogs as games are mined."""

    hulls: dict[int, str] = field(default_factory=dict)
    engines: dict[int, str] = field(default_factory=dict)
    beams: dict[int, str] = field(default_factory=dict)
    torpedoes: dict[int, str] = field(default_factory=dict)
    races: dict[int, str] = field(default_factory=dict)

    def absorb_turn(self, turn: TurnInfo) -> None:
        """Add any component names from this turn's host catalog tables."""
        for hull in turn.hulls:
            self.hulls.setdefault(hull.id, hull.name)
        for engine in turn.engines:
            self.engines.setdefault(engine.id, engine.name)
        for beam in turn.beams:
            self.beams.setdefault(beam.id, beam.name)
        for torpedo in turn.torpedos:
            self.torpedoes.setdefault(torpedo.id, torpedo.name)
        for race in turn.races:
            self.races.setdefault(race.id, race.name)

    def build(self) -> ComponentNameCatalog:
        return ComponentNameCatalog(
            hulls=dict(self.hulls),
            engines=dict(self.engines),
            beams=dict(self.beams),
            torpedoes=dict(self.torpedoes),
            races=dict(self.races),
        )

    def absorb_catalog(self, catalog: ComponentNameCatalog) -> None:
        for hull_id, name in catalog.hulls.items():
            self.hulls.setdefault(hull_id, name)
        for engine_id, name in catalog.engines.items():
            self.engines.setdefault(engine_id, name)
        for beam_id, name in catalog.beams.items():
            self.beams.setdefault(beam_id, name)
        for torpedo_id, name in catalog.torpedoes.items():
            self.torpedoes.setdefault(torpedo_id, name)
        for race_id, name in catalog.races.items():
            self.races.setdefault(race_id, name)
