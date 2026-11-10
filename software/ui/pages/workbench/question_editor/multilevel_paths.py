from __future__ import annotations


class MultilevelPaths:
    def __init__(self, texts: list[str], weights: list[float]) -> None:
        self.parts = [tuple(text.split(chr(0x2010))) for text in texts]
        self.values = list(weights)
        self.selected = {i for i, value in enumerate(weights) if value > 0}

    def select(self, indices: list[int], checked: bool) -> None:
        for index in indices:
            if checked:
                if index not in self.selected:
                    self.values[index] = 1.0
                self.selected.add(index)
            else:
                self.selected.discard(index)
                self.values[index] = 0.0

    def is_valid(self) -> bool:
        return any(value > 0 for value in self.values)
