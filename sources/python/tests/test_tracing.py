import asyncio
from contextlib import contextmanager

import pytest

from tracing_skill_observability import traced_span
from tracing_skill_observability import tracing


def test_traced_span_decorator_wraps_sync_function():
    @traced_span("unit.sync", kind="test")
    def add_one(value: int) -> int:
        return value + 1

    assert add_one(1) == 2


def test_traced_span_decorator_wraps_sync_function_without_args():
    @traced_span
    def add_one(value: int) -> int:
        return value + 1

    assert add_one(1) == 2


def test_traced_span_decorator_wraps_async_function():
    @traced_span("unit.async")
    async def add_one(value: int) -> int:
        return value + 1

    assert asyncio.run(add_one(1)) == 2


def test_traced_span_records_sync_exception(monkeypatch: pytest.MonkeyPatch):
    fake_span = FakeSpan()
    monkeypatch.setattr(tracing, "get_tracer", lambda name=None: FakeTracer(fake_span))

    @traced_span("unit.fail")
    def fail():
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        fail()

    assert fake_span.exceptions
    assert fake_span.status is not None
    assert fake_span.status.status_code.name == "ERROR"


def test_traced_span_records_async_exception(monkeypatch: pytest.MonkeyPatch):
    fake_span = FakeSpan()
    monkeypatch.setattr(tracing, "get_tracer", lambda name=None: FakeTracer(fake_span))

    @traced_span("unit.async.fail")
    async def fail():
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        asyncio.run(fail())

    assert fake_span.exceptions
    assert fake_span.status is not None
    assert fake_span.status.status_code.name == "ERROR"


class FakeSpan:
    def __init__(self):
        self.attributes = {}
        self.exceptions = []
        self.status = None

    def set_attribute(self, key, value):
        self.attributes[key] = value

    def record_exception(self, exc):
        self.exceptions.append(exc)

    def set_status(self, status):
        self.status = status


class FakeTracer:
    def __init__(self, span):
        self.span = span

    @contextmanager
    def start_as_current_span(self, name):
        yield self.span
