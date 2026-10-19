from __future__ import annotations

from software.core.config.schema import RuntimeConfig
from software.io.config.store import load_config, save_config


class JsonConfigRepository:
    """Python JSON persistence adapter for RuntimeConfig."""

    def load(self, path: str | None = None, *, strict: bool = False) -> RuntimeConfig:
        return load_config(path, strict=strict)

    def save(self, config: RuntimeConfig, path: str | None = None) -> str:
        return save_config(config, path)


__all__ = ["JsonConfigRepository"]
