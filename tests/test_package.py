"""The package entry point and the --check-config CLI."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"


def clean_env() -> dict[str, str]:
    """Copy the environment without MUD_* variables and with src importable."""
    env = {key: value for key, value in os.environ.items() if not key.startswith("MUD_")}
    existing = env.get("PYTHONPATH")
    env["PYTHONPATH"] = os.pathsep.join(part for part in (str(SRC), existing) if part)
    return env


def run_cli(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "mud", *args],
        cwd=cwd,
        env=clean_env(),
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def test_check_config_exits_zero_and_prints_effective_config(tmp_path: Path) -> None:
    result = run_cli("--check-config", cwd=tmp_path)

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["server"]["port"] == 8765
    assert payload["server"]["world_name"] == "Club MUD"
    # --check-config must not create the database or any state directory.
    assert not (tmp_path / "var").exists()


def test_check_config_missing_explicit_file_fails(tmp_path: Path) -> None:
    result = run_cli(
        "--check-config", "--config", str(tmp_path / "absent.toml"), cwd=tmp_path
    )

    assert result.returncode != 0
    assert "not found" in result.stderr
