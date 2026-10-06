"""Breakpoint document store used by backends and migrations.

A store owns whole breakpoint documents. It does not resolve an in-document
suffix. ``read_document`` returns a copy. ``document_lock`` serializes one
logical read-modify-write of a breakpoint document.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import AbstractContextManager
from typing import Protocol

from api.storage.base import JSONValue


class DocumentStore(Protocol):
    """Raw breakpoint documents. Callers do not resolve logical suffixes.

    ``read_document`` returns a defensive copy. Mutation of the returned value
    does not change the stored document. ``load_document`` returns the stored
    object; callers must not mutate it. ``document_lock`` is held across a
    logical read-modify-write of one breakpoint.
    """

    def iter_document_paths(self) -> Iterator[str]: ...

    def has_document(self, breakpoint_path: str) -> bool: ...

    def load_document(self, breakpoint_path: str) -> JSONValue: ...

    def read_document(self, breakpoint_path: str) -> JSONValue: ...

    def replace_document(self, breakpoint_path: str, value: JSONValue) -> None: ...

    def write_document(self, breakpoint_path: str, value: JSONValue) -> None: ...

    def remove_document(self, breakpoint_path: str) -> None: ...

    def child_names(self, prefix: str) -> list[str]: ...

    def document_lock(self, breakpoint_path: str) -> AbstractContextManager[None]: ...
