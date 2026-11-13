"""Configuration loading: defaults, TOML, environment, and rejection."""

from __future__ import annotations

from pathlib import Path

import pytest

from mud.config import ConfigError, load_config


@pytest.fixture
def empty_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Run in an empty directory so no mud.toml is discovered."""
    monkeypatch.chdir(tmp_path)
    return tmp_path


def write_config(directory: Path, text: str) -> Path:
    path = directory / "mud.toml"
    path.write_text(text, encoding="utf-8")
    return path


def test_builtin_defaults_without_config_file(empty_cwd: Path) -> None:
    config = load_config(env={})

    assert config.server.bind == "127.0.0.1"
    assert config.server.port == 8765
    assert config.server.world_name == "Club MUD"
    assert config.server.motd == "Welcome. Type help."
    assert config.storage.db == "var/mud.db"
    assert config.game.start_room == "gatehouse"
    assert config.game.carry_limit == 12
    assert config.game.tick_hz == 1
    assert config.game.auth_timeout_s == 10
    assert config.game.idle_timeout_s == 90
    assert config.game.max_frame_bytes == 65536
    assert config.features.effects is False
    assert config.features.narration is False
    assert config.features.generation is False
    assert config.features.agents is False
    assert config.log.level == "info"
    assert config.log.format == "json"


def test_default_config_path_is_loaded(empty_cwd: Path) -> None:
    write_config(empty_cwd, "[server]\nport = 9100\n")

    config = load_config(env={})

    assert config.server.port == 9100


def test_toml_file_overrides_defaults(empty_cwd: Path) -> None:
    path = write_config(
        empty_cwd,
        """
[server]
port = 9100
world_name = "Test MUD"

[game]
carry_limit = 30
""",
    )

    config = load_config(path, env={})

    assert config.server.port == 9100
    assert config.server.world_name == "Test MUD"
    assert config.game.carry_limit == 30
    # Untouched settings keep their built-in defaults.
    assert config.server.bind == "127.0.0.1"
    assert config.game.tick_hz == 1


def test_env_overrides_default_port(empty_cwd: Path) -> None:
    config = load_config(env={"MUD_SERVER__PORT": "9999"})

    assert config.server.port == 9999


def test_env_values_are_type_coerced(empty_cwd: Path) -> None:
    config = load_config(
        env={
            "MUD_GAME__CARRY_LIMIT": "20",
            "MUD_GAME__TICK_HZ": "5",
            "MUD_FEATURES__EFFECTS": "true",
        }
    )

    assert config.game.carry_limit == 20
    assert config.game.tick_hz == 5
    assert config.features.effects is True


def test_env_overrides_toml(empty_cwd: Path) -> None:
    path = write_config(empty_cwd, "[server]\nport = 9100\n")

    config = load_config(
        path,
        env={"MUD_SERVER__PORT": "9999", "MUD_GAME__CARRY_LIMIT": "20"},
    )

    assert config.server.port == 9999
    assert config.game.carry_limit == 20


def test_unknown_toml_key_is_rejected(empty_cwd: Path) -> None:
    path = write_config(empty_cwd, "[server]\nprot = 9999\n")

    with pytest.raises(ConfigError, match=r"server\.prot"):
        load_config(path, env={})


def test_unknown_env_key_is_rejected(empty_cwd: Path) -> None:
    with pytest.raises(ConfigError, match="MUD_SERVER__PORTT"):
        load_config(env={"MUD_SERVER__PORTT": "9999"})


def test_missing_default_file_falls_back_to_defaults(empty_cwd: Path) -> None:
    assert not (empty_cwd / "mud.toml").exists()

    config = load_config(env={})

    assert config.server.port == 8765
    assert config.server.world_name == "Club MUD"


def test_missing_explicit_config_path_is_an_error(empty_cwd: Path) -> None:
    with pytest.raises(ConfigError, match="not found"):
        load_config(empty_cwd / "absent.toml", env={})


def test_invalid_toml_value_is_rejected(empty_cwd: Path) -> None:
    path = write_config(empty_cwd, '[server]\nport = "eighty"\n')

    with pytest.raises(ConfigError, match=r"server\.port"):
        load_config(path, env={})


def test_malformed_toml_is_reported(empty_cwd: Path) -> None:
    path = write_config(empty_cwd, "[server\nport = 8765\n")

    with pytest.raises(ConfigError, match="invalid TOML"):
        load_config(path, env={})
