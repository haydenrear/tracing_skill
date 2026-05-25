import asyncio

from tracing_skill_observability import traced_span


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
