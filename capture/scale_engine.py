from dataclasses import dataclass

@dataclass
class ScaleEngine:
    original_width: int
    original_height: int
    scale_percent: int  # 100 = 1.0

    @property
    def scale_factor(self) -> float:
        return self.scale_percent / 100.0

    def to_scaled(self, x: int, y: int) -> tuple[int, int]:
        f = self.scale_factor
        return int(x * f), int(y * f)

    def to_original(self, x: int, y: int) -> tuple[int, int]:
        f = self.scale_factor
        if f == 0:
            return x, y
        return int(x / f), int(y / f)
