"""BFF OpenAPI documents scores inference stream event variants."""

from bff.app import app
from bff.transport.inference_stream_responses import (
    InferenceStreamNoStoredRowEvent,
    InferenceStreamStoredRowEvent,
)


def test_no_stored_row_stream_event_is_documented() -> None:
    schema = InferenceStreamNoStoredRowEvent.model_json_schema()
    assert schema["properties"]["type"]["const"] == "no_stored_row"
    documented = app.openapi()["components"]["schemas"]["InferenceStreamNoStoredRowEvent"]
    assert documented["properties"]["type"]["const"] == "no_stored_row"


def test_stored_row_stream_event_is_documented_and_not_complete() -> None:
    schema = InferenceStreamStoredRowEvent.model_json_schema()
    assert schema["properties"]["type"]["const"] == "stored_row"
    documented = app.openapi()["components"]["schemas"]["InferenceStreamStoredRowEvent"]
    assert documented["properties"]["type"]["const"] == "stored_row"
    assert "status" in documented["properties"]
    assert "evidenceGeneration" in documented["properties"]
    assert "evidenceMark" in documented["properties"]
