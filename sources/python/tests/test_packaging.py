import re
import subprocess
from email.parser import Parser
from importlib.metadata import distribution
from pathlib import Path
from zipfile import ZipFile


def test_python_package_does_not_advertise_the_skill_owned_installer():
    scripts = {
        entry.name: entry.value
        for entry in distribution("tracing-skill-observability").entry_points
        if entry.group == "console_scripts"
    }

    assert "tracing-observability-install" not in scripts


def test_built_wheel_does_not_require_prometheus_client(tmp_path):
    package_root = Path(__file__).parents[1]
    result = subprocess.run(
        [
            "uv",
            "build",
            "--wheel",
            "--out-dir",
            str(tmp_path),
            str(package_root),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr

    [wheel] = tmp_path.glob("*.whl")
    with ZipFile(wheel) as archive:
        [metadata_path] = [
            name for name in archive.namelist() if name.endswith(".dist-info/METADATA")
        ]
        metadata = Parser().parsestr(archive.read(metadata_path).decode())

    requirements = {
        re.sub(
            r"[-_.]+",
            "-",
            re.split(r"[\[ (;<>=!~]", value, maxsplit=1)[0],
        ).lower()
        for value in metadata.get_all("Requires-Dist", [])
    }
    assert "prometheus-client" not in requirements
