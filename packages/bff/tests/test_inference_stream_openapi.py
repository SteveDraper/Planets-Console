"""BFF OpenAPI documents scores inference stream event variants."""

from bff.app import app
from bff.transport.inference_stream_responses import InferenceStreamNoStoredRowEvent


def test_no_stored_row_stream_event_is_documented() -> None:
    schema = InferenceStreamNoStoredRowEvent.model_json_schema()
    assert schema["properties"]["type"]["const"] == "no_stored_row"
    documented = app.openapi()["components"]["schemas"]["InferenceStreamNoStoredRowEvent"]
    assert documented["properties"]["type"]["const"] == "no_stored_row"
