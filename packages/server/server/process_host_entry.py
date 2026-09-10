"""Freeze and ``python -m`` entry for the packaged process host."""

from server.process_host.runtime import main

if __name__ == "__main__":
    raise SystemExit(main())
