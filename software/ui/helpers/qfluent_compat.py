from PySide6.QtWidgets import QApplication, QWidget


class QFluentCompat:
    @staticmethod
    def set_indeterminate_progress_active(ring, active: bool) -> None:
        set_indeterminate_progress_ring_active(ring, active)

    @staticmethod
    def mask_parent(parent: QWidget | None) -> QWidget:
        return resolve_mask_dialog_parent(parent)


def set_indeterminate_progress_ring_active(ring, active: bool) -> None:
    if active and not ring.property("surveycontroller_active"):
        ring.start()
        ring.setProperty("surveycontroller_active", True)
    elif not active and ring.property("surveycontroller_active"):
        ring.stop()
        ring.setProperty("surveycontroller_active", False)
    ring.setVisible(bool(active))


def resolve_mask_dialog_parent(parent: QWidget | None) -> QWidget:
    if parent is not None:
        return parent.window()
    active = QApplication.activeWindow()
    if active is None:
        raise ValueError("弹窗必须指定所属窗口")
    return active
