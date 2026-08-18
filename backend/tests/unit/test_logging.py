from __future__ import annotations

import json
import logging

from placepulse.logging import JsonFormatter, request_id_context


def test_json_log_has_utc_contract_and_redacts_sensitive_fields() -> None:
    record = logging.LogRecord("test", logging.INFO, __file__, 1, "ignored body", (), None)
    record.event = "security_test"
    record.password = "do-not-print"
    record.latitude = 32.777691
    record.safe_count = 2
    token = request_id_context.set("a39905ef-a7b5-4616-a8e1-3d754fd0b369")
    try:
        payload = json.loads(JsonFormatter("test").format(record))
    finally:
        request_id_context.reset(token)
    assert payload["timestamp"].endswith("Z")
    assert payload["severity"] == "INFO"
    assert payload["service"] == "placepulse-api"
    assert payload["event"] == "security_test"
    assert payload["password"] == "[REDACTED]"
    assert payload["latitude"] == "[REDACTED]"
    assert payload["safe_count"] == 2
    assert "do-not-print" not in json.dumps(payload)
    assert "32.777691" not in json.dumps(payload)
