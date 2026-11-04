from __future__ import annotations

from pathlib import Path

from software.ui.pages import community as community_module
from software.ui.widgets import config_drawer as config_drawer_module


def test_config_drawer_opens_config_directory_via_qdesktopservices(
    monkeypatch, tmp_path, qtbot
) -> None:
    opened: list[str] = []
    monkeypatch.setattr(config_drawer_module, "get_user_config_directory", lambda: str(tmp_path))
    monkeypatch.setattr(
        config_drawer_module.QDesktopServices,
        "openUrl",
        lambda url: opened.append(url.toLocalFile()) or True,
    )

    drawer = config_drawer_module.ConfigDrawer()
    qtbot.addWidget(drawer)
    drawer._open_config_folder()

    assert [Path(path) for path in opened] == [tmp_path]


def test_config_drawer_lists_legacy_default_config_as_recovery_source(
    monkeypatch,
    tmp_path,
    qtbot,
) -> None:
    current_directory = tmp_path / "configs"
    legacy_path = tmp_path / "config.json"
    current_directory.mkdir()
    (current_directory / "manual.json").write_text("{}", encoding="utf-8")
    legacy_path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        config_drawer_module,
        "get_user_config_directory",
        lambda: str(current_directory),
    )
    monkeypatch.setattr(
        config_drawer_module,
        "get_legacy_runtime_config_path",
        lambda: str(legacy_path),
    )

    drawer = config_drawer_module.ConfigDrawer()
    qtbot.addWidget(drawer)
    drawer.refresh()

    items = [drawer.list_widget.item(index) for index in range(drawer.list_widget.count())]
    item_paths = {item.data(config_drawer_module.Qt.ItemDataRole.UserRole) for item in items}
    item_labels = [item.text() for item in items]
    assert str(legacy_path) in item_paths
    assert any("config.json（旧位置）" in label for label in item_labels)


def test_community_page_opens_qr_image_via_qdesktopservices(monkeypatch, tmp_path, qtbot) -> None:
    opened: list[str] = []
    image_path = tmp_path / "community_qr.jpg"
    image_path.write_bytes(b"jpg")
    monkeypatch.setattr(community_module, "get_assets_directory", lambda: str(tmp_path))
    monkeypatch.setattr(
        community_module.QDesktopServices,
        "openUrl",
        lambda url: opened.append(url.toLocalFile()) or True,
    )

    page = community_module.CommunityPage()
    qtbot.addWidget(page)
    page._open_qq_qr_image()

    assert [Path(path) for path in opened] == [image_path]
