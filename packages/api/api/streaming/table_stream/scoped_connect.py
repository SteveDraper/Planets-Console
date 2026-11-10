"""Stream connect entry: catalog the registries, begin the scheduler scope, then connect.

This entry sits above ``connect`` because the catalog bootstrap imports the
analytic registries, and those import the ``table_stream`` package, which
imports ``connect``.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator

from api.streaming.table_stream.connect import (
    TableStreamConnectPolicy,
    iter_table_stream_connect,
)
from api.streaming.table_stream.registry_bootstrap import (
    ensure_table_stream_registries_registered,
)


def iter_table_stream_connect_with_scope[ScheduledT, AdmissionT, EventT](
    *,
    begin_scope: Callable[[], str],
    end_scope: Callable[[str], None],
    policy_factory: Callable[
        [str],
        TableStreamConnectPolicy[ScheduledT, AdmissionT, EventT],
    ],
    player_ids: tuple[int, ...],
) -> Iterator[dict[str, object]]:
    """Catalog the registries, begin scheduler scope, then run shared connect orchestration.

    The registries are catalogued before the policy attaches its controller and
    outside every lock, so a catalog scan sees every attached controller without
    registering anything itself.
    """
    ensure_table_stream_registries_registered()
    stream_token = begin_scope()
    policy: TableStreamConnectPolicy[ScheduledT, AdmissionT, EventT] | None = None
    try:
        policy = policy_factory(stream_token)
        yield from iter_table_stream_connect(policy, player_ids)
    finally:
        end_scope(stream_token)
