from tracing_skill_observability import http_requests_total, metrics_app


def test_metrics_api_is_importable():
    http_requests_total.labels(method="GET", route="/health", status="200").inc()

    assert metrics_app() is not None
