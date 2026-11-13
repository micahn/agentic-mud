"""Typed configuration for the MUD server.

Precedence: built-in defaults < ``mud.toml`` < ``MUD_*`` environment.

Environment variables use the ``MUD_`` prefix and a double underscore for
nesting, for example ``MUD_SERVER__PORT=9999`` or
``MUD_GAME__CARRY_LIMIT=20``. Values are coerced by pydantic. Unknown keys in
either source are rejected with an error naming the offending key.
"""

from __future__ import annotations

import os
import tomllib
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

DEFAULT_CONFIG_PATH = Path("mud.toml")
ENV_PREFIX = "MUD_"
ENV_NESTING = "__"


class ConfigError(Exception):
    """Raised when configuration cannot be read or is invalid."""


class _Section(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ServerConfig(_Section):
    bind: str = "127.0.0.1"
    port: int = 8765
    world_name: str = "Club MUD"
    motd: str = "Welcome. Type help."


class StorageConfig(_Section):
    db: str = "var/mud.db"


class GameConfig(_Section):
    start_room: str = "gatehouse"
    carry_limit: int = 12
    tick_hz: int = 1
    auth_timeout_s: int = 10
    idle_timeout_s: int = 90
    max_frame_bytes: int = 65536


class FeaturesConfig(_Section):
    effects: bool = False
    narration: bool = False
    generation: bool = False
    agents: bool = False


class LogConfig(_Section):
    level: str = "info"
    format: str = "json"


class Config(_Section):
    server: ServerConfig = Field(default_factory=ServerConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    game: GameConfig = Field(default_factory=GameConfig)
    features: FeaturesConfig = Field(default_factory=FeaturesConfig)
    log: LogConfig = Field(default_factory=LogConfig)


def load_config(
    path: str | os.PathLike[str] | None = None,
    *,
    env: Mapping[str, str] | None = None,
) -> Config:
    """Load the effective configuration.

    With no *path*, ``mud.toml`` in the working directory is used when present
    and built-in defaults otherwise. An explicit *path* must exist. *env*
    defaults to :data:`os.environ`; it is injectable for tests.
    """
    if env is None:
        env = os.environ

    toml_data: dict[str, Any] | None = None
    if path is not None:
        config_path = Path(path)
        if not config_path.is_file():
            raise ConfigError(f"config file not found: {config_path}")
        toml_data = _read_toml(config_path)
    elif DEFAULT_CONFIG_PATH.is_file():
        config_path = DEFAULT_CONFIG_PATH
        toml_data = _read_toml(config_path)

    if toml_data is None:
        base = Config()
    else:
        try:
            base = Config.model_validate(toml_data)
        except ValidationError as exc:
            raise ConfigError(_format_error(exc, f"config file {config_path}")) from exc

    overrides = _env_overrides(env)
    if not overrides:
        return base

    merged = _deep_merge(base.model_dump(), overrides)
    try:
        return Config.model_validate(merged)
    except ValidationError as exc:
        raise ConfigError(_format_env_error(exc, env)) from exc


def _read_toml(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as handle:
            data = tomllib.load(handle)
    except OSError as exc:
        raise ConfigError(f"cannot read config file {path}: {exc}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"invalid TOML in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"invalid config file {path}: expected a table at the top level")
    return data


def _env_overrides(env: Mapping[str, str]) -> dict[str, Any]:
    """Expand ``MUD_A__B`` variables into ``{"a": {"b": value}}``."""
    tree: dict[str, Any] = {}
    for name, value in env.items():
        if not name.startswith(ENV_PREFIX):
            continue
        path: Sequence[str] = name[len(ENV_PREFIX) :].split(ENV_NESTING)
        if any(not part for part in path):
            raise ConfigError(f"invalid environment variable {name}: empty config path segment")

        node = tree
        for part in path[:-1]:
            key = part.lower()
            child = node.setdefault(key, {})
            if not isinstance(child, dict):
                raise ConfigError(
                    f"invalid environment variable {name}: conflicting value for {part.lower()}"
                )
            node = child

        key = path[-1].lower()
        if isinstance(node.get(key), dict):
            raise ConfigError(
                f"invalid environment variable {name}: conflicting value for {key}"
            )
        node[key] = value
    return tree


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _format_error(exc: ValidationError, source: str) -> str:
    details = "; ".join(
        f"{'.'.join(str(part) for part in error['loc']) or '<root>'}: {error['msg']}"
        for error in exc.errors()
    )
    return f"invalid config in {source}: {details}"


def _format_env_error(exc: ValidationError, env: Mapping[str, str]) -> str:
    details = []
    for error in exc.errors():
        loc = error["loc"]
        candidate = ENV_PREFIX + ENV_NESTING.join(str(part).upper() for part in loc)
        label = candidate if candidate in env else ".".join(str(part) for part in loc)
        details.append(f"{label}: {error['msg']}")
    return "invalid config in environment: " + "; ".join(details)
