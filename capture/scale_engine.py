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
# scale_engine.py

CANVAS_WIDTH = 1280
CANVAS_HEIGHT = 720

def to_design_point(game_region: dict, page_x: int, page_y: int) -> tuple[int, int]:
    """
    Chuyển tọa độ click trên màn hình (page_x, page_y)
    -> tọa độ tương ứng trong canvas chuẩn 1280x720.
    game_region: dict {x,y,width,height} vùng game hiện tại trên màn hình.
    """
    gx = game_region.get("x", 0)
    gy = game_region.get("y", 0)
    gw = max(game_region.get("width", 1), 1)
    gh = max(game_region.get("height", 1), 1)

    # tọa độ tương đối trong game_region
    local_x = page_x - gx
    local_y = page_y - gy

    # map về 1280x720
    design_x = int(local_x * CANVAS_WIDTH / gw)
    design_y = int(local_y * CANVAS_HEIGHT / gh)
    return design_x, design_y


def from_design_point(game_region: dict, design_x: int, design_y: int) -> tuple[int, int]:
    """
    Ngược lại: từ tọa độ canvas 1280x720
    -> tọa độ click thật trên màn hình.
    """
    gx = game_region.get("x", 0)
    gy = game_region.get("y", 0)
    gw = max(game_region.get("width", 1), 1)
    gh = max(game_region.get("height", 1), 1)

    page_x = int(gx + design_x * gw / CANVAS_WIDTH)
    page_y = int(gy + design_y * gh / CANVAS_HEIGHT)
    return page_x, page_y
