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
metrics_port = 9464
"""
    )

    config = load_config(config_file)

    assert config.service_name == "svc"
    assert config.service_version == "1.2.3"
    assert config.otlp_endpoint == "http://collector:4318"
    assert config.log_level == "DEBUG"
    assert config.metrics_port == 9464
