"""Thin OS process host for the packaged one-process console server."""

from __future__ import annotations


def main() -> int:
    from server.process_host.runtime import main as run_process_host

    return run_process_host()


__all__ = ["main"]
