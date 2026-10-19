from __future__ import annotations

from software.application.ports import ConfigRepositoryPort
from software.core.config.schema import RuntimeConfig


class ConfigurationService:
    def __init__(self, repository: ConfigRepositoryPort) -> None:
        self._repository = repository

    def load(self, path: str | None = None, *, strict: bool = False) -> RuntimeConfig:
        return self._repository.load(path, strict=strict)

    def save(self, config: RuntimeConfig, path: str | None = None) -> str:
        return self._repository.save(config, path)


__all__ = ["ConfigurationService"]
