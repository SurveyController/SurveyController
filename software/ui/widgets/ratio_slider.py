from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QVBoxLayout, QHBoxLayout, QWidget
from qfluentwidgets import BodyLabel, Slider as QfSlider


class RatioSlider(QWidget):
    

    valueChanged = Signal(dict)  

    def __init__(self, labels: dict, parent=None):
        
        super().__init__(parent)

        if len(labels) != 3:
            raise ValueError("RatioSlider 必须包含恰好3个滑块")

        self.keys = list(labels.keys())
        self.labels = labels
        self._updating = False  

        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        
        self.sliders = {}
        self.value_labels = {}

        for key in self.keys:
            row = QHBoxLayout()
            row.setSpacing(12)

            
            label = BodyLabel(labels[key], self)
            label.setFixedWidth(100)
            row.addWidget(label)

            
            slider = QfSlider(Qt.Orientation.Horizontal, self)
            slider.setRange(0, 100)
            slider.setValue(33)  
            slider.setMinimumWidth(250)
            slider.valueChanged.connect(lambda v, k=key: self._on_slider_changed(k, v))
            self.sliders[key] = slider
            row.addWidget(slider, 1)

            
            value_label = BodyLabel("33%", self)
            value_label.setFixedWidth(50)
            value_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.value_labels[key] = value_label
            row.addWidget(value_label)

            layout.addLayout(row)

        
        self._set_values_silently({key: 33 for key in self.keys})
        self._normalize_values()

    def _on_slider_changed(self, changed_key: str, new_value: int):
        
        if self._updating:
            return

        self._updating = True

        
        values = {key: self.sliders[key].value() for key in self.keys}
        values[changed_key] = new_value

        
        other_keys = [k for k in self.keys if k != changed_key]

        
        remaining = 100 - new_value

        if remaining < 0:
            remaining = 0

        
        other_values = [values[k] for k in other_keys]
        other_sum = sum(other_values)

        
        if other_sum > 0:
            
            for k in other_keys:
                ratio = values[k] / other_sum
                values[k] = int(remaining * ratio)
        else:
            
            for i, k in enumerate(other_keys):
                if i == 0:
                    values[k] = remaining // 2
                else:
                    values[k] = remaining - values[other_keys[0]]

        
        total = sum(values.values())
        if total != 100:
            diff = 100 - total
            
            values[other_keys[0]] += diff

        
        for key in self.keys:
            self.sliders[key].setValue(values[key])
            self.value_labels[key].setText(f"{values[key]}%")

        self._updating = False

        
        self.valueChanged.emit(values)

    def _set_values_silently(self, values: dict):
        
        self._updating = True
        for key, value in values.items():
            if key in self.sliders:
                self.sliders[key].setValue(value)
                self.value_labels[key].setText(f"{value}%")
        self._updating = False

    def _normalize_values(self):
        
        values = {key: self.sliders[key].value() for key in self.keys}
        total = sum(values.values())

        if total == 100:
            return

        
        if total > 0:
            for key in self.keys:
                values[key] = int(values[key] * 100 / total)
        else:
            
            for i, key in enumerate(self.keys):
                if i < 2:
                    values[key] = 33
                else:
                    values[key] = 34

        
        total = sum(values.values())
        if total != 100:
            diff = 100 - total
            values[self.keys[0]] += diff

        self._set_values_silently(values)

    def getValues(self) -> dict:
        
        return {key: self.sliders[key].value() for key in self.keys}

    def setValues(self, values: dict):
        
        
        total = sum(values.values())
        if total != 100:
            raise ValueError(f"滑块值总和必须为100%，当前为{total}%")

        self._set_values_silently(values)
        self.valueChanged.emit(values)

    def setEnabled(self, arg__1: bool):
        
        super().setEnabled(arg__1)
        for slider in self.sliders.values():
            slider.setEnabled(arg__1)
