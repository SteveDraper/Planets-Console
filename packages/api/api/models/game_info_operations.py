"""Operations accepted by the game info update (POST) endpoint."""

from enum import StrEnum


class GameInfoUpdateOperation(StrEnum):
    REFRESH = "refresh"
