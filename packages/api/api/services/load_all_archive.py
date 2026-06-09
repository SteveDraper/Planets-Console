"""Parse Planets.nu ``/game/loadall`` ZIP archives into per-turn ``rst`` payloads."""

from __future__ import annotations

import io
import json
import re
import zipfile
from dataclasses import dataclass

from api.errors import UpstreamPlanetsError, ValidationError

_ARCHIVE_TURN_RE = re.compile(r"^player(\d+)-turn(\d+)\.trn$", re.IGNORECASE)


@dataclass(frozen=True)
class ArchiveTurnFile:
    """One turn file from a loadall archive."""

    player_slot: int
    turn_number: int
    rst: dict


def parse_load_all_zip(zip_bytes: bytes) -> list[ArchiveTurnFile]:
    """Extract ``playerN-turnT.trn`` JSON objects from a loadall ZIP.

    Slot ``0`` is the spectator / neutral view (``playerid=0``); larger games
    include those files alongside ``player1``..``playerN`` entries.
    """
    if not zip_bytes:
        raise UpstreamPlanetsError("Planets.nu loadall returned an empty response.")

    try:
        archive = zipfile.ZipFile(io.BytesIO(zip_bytes))
    except zipfile.BadZipFile as err:
        raise UpstreamPlanetsError(
            "Planets.nu loadall response is not a valid ZIP archive."
        ) from err

    entries: list[ArchiveTurnFile] = []
    for name in archive.namelist():
        match = _ARCHIVE_TURN_RE.match(name.strip())
        if not match:
            continue
        player_slot = int(match.group(1))
        turn_number = int(match.group(2))
        if player_slot < 0:
            raise ValidationError(f"Invalid player slot in loadall archive entry: {name!r}")
        if turn_number < 0:
            raise ValidationError(f"Invalid turn number in loadall archive entry: {name!r}")
        raw = archive.read(name)
        try:
            rst = json.loads(raw)
        except json.JSONDecodeError as err:
            raise ValidationError(
                f"Loadall archive entry {name!r} did not contain valid JSON."
            ) from err
        if not isinstance(rst, dict):
            raise ValidationError(f"Loadall archive entry {name!r} must be a JSON object.")
        entries.append(
            ArchiveTurnFile(
                player_slot=player_slot,
                turn_number=turn_number,
                rst=rst,
            )
        )

    if not entries:
        raise UpstreamPlanetsError("Planets.nu loadall ZIP contained no turn files.")
    return entries
