import json
import logging

from tracing_skill_observability.logging import JsonLogFormatter


def test_json_formatter_includes_extra_fields():
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="hello",
        args=(),
        exc_info=None,
    )
    record.job_id = "job-1"

    payload = json.loads(JsonLogFormatter(service_name="svc").format(record))

    assert payload["message"] == "hello"
    assert payload["service_name"] == "svc"
    assert payload["job_id"] == "job-1"
