from pathlib import Path

from tracing_skill_observability.config import load_config


def test_load_config_from_toml(tmp_path: Path):
    config_file = tmp_path / "observability.toml"
    config_file.write_text(
        """
[observability]
service_name = "svc"
service_version = "1.2.3"
otlp_endpoint = "http://collector:4318"
log_level = "DEBUG"
log_mode = "otlp-only"
logs_endpoint = "http://logs-collector:4318/v1/logs"
metrics_enabled = true
metrics_port = 9464
metrics_addr = "127.0.0.1"
metrics_export_interval_seconds = 2.5
"""
    )

    config = load_config(config_file)

    assert config.service_name == "svc"
    assert config.service_version == "1.2.3"
    assert config.otlp_endpoint == "http://collector:4318"
    assert config.log_level == "DEBUG"
    assert config.log_mode == "otlp-only"
    assert config.logs_endpoint == "http://logs-collector:4318/v1/logs"
    assert config.metrics_enabled is True
    assert config.metrics_port == 9464
    assert config.metrics_addr == "127.0.0.1"
    assert config.metrics_export_interval_seconds == 2.5
