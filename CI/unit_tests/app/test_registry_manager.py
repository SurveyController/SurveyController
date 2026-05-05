from __future__ import annotations

from types import SimpleNamespace

import software.system.registry_manager as registry_manager


class _FakeRegistryKey:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        del exc_type, exc, tb


class RegistryManagerTests:
    def test_is_confetti_played_returns_false_when_winreg_unavailable(self, patch_attrs) -> None:
        patch_attrs((registry_manager, "winreg", None))

        assert registry_manager.RegistryManager.is_confetti_played() is False

    def test_is_confetti_played_returns_false_when_key_missing(self, patch_attrs) -> None:
        fake_winreg = SimpleNamespace(
            HKEY_CURRENT_USER="HKCU",
            OpenKey=lambda *_args, **_kwargs: (_ for _ in ()).throw(FileNotFoundError()),
        )
        patch_attrs((registry_manager, "winreg", fake_winreg))

        assert registry_manager.RegistryManager.is_confetti_played() is False

    def test_is_confetti_played_reads_registry_value(self, patch_attrs) -> None:
        fake_key = _FakeRegistryKey()
        fake_winreg = SimpleNamespace(
            HKEY_CURRENT_USER="HKCU",
            OpenKey=lambda *_args, **_kwargs: fake_key,
            QueryValueEx=lambda *_args, **_kwargs: ("1", 0),
        )
        patch_attrs((registry_manager, "winreg", fake_winreg))

        assert registry_manager.RegistryManager.is_confetti_played() is True

    def test_set_confetti_played_writes_registry_value(self, patch_attrs) -> None:
        recorded: dict[str, object] = {}
        fake_key = object()

        def _create_key(*args):
            recorded["create_args"] = args
            return fake_key

        def _set_value(*args):
            recorded["set_args"] = args

        def _close_key(arg):
            recorded["closed_key"] = arg

        fake_winreg = SimpleNamespace(
            HKEY_CURRENT_USER="HKCU",
            KEY_WRITE=0x20006,
            REG_DWORD=4,
            CreateKeyEx=_create_key,
            SetValueEx=_set_value,
            CloseKey=_close_key,
        )
        patch_attrs((registry_manager, "winreg", fake_winreg))

        assert registry_manager.RegistryManager.set_confetti_played(True) is True
        assert recorded["create_args"] == ("HKCU", registry_manager.RegistryManager.REGISTRY_PATH, 0, fake_winreg.KEY_WRITE)
        assert recorded["set_args"] == (
            fake_key,
            registry_manager.RegistryManager.REGISTRY_KEY_CONFETTI_PLAYED,
            0,
            fake_winreg.REG_DWORD,
            1,
        )
        assert recorded["closed_key"] is fake_key

