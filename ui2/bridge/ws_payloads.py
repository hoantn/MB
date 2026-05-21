# ui2/bridge/ws_payloads.py
from __future__ import annotations

import json
from typing import Any

# Các hằng số lấy từ log WebSocket
ZONE_NAME = "Simms"          # tham số thứ 2 trong mọi frame
CHANNEL_PLUGIN = "channelPlugin"
GAME_GID = 4                 # gid=4 cho ChinesePoker / Mậu Binh
ACCOUNT_ID = "1"             # aid="1" trong log


def _dumps(payload: list[Any]) -> str:
  """
  Chuẩn hoá JSON string giống client:
  - Không có khoảng trắng thừa.
  - Trả về string để gửi qua WebSocket.
  """
  return json.dumps(payload, separators=(",", ":"))


def build_ws_payload_update_room_list() -> str:
  """
  Yêu cầu server gửi danh sách phòng (cmd=300).
  Từ log:
    [6,"Simms","channelPlugin",{"cmd":300,"aid":"1","gid":4}]
  """
  frame: list[Any] = [
      6,
      ZONE_NAME,
      CHANNEL_PLUGIN,
      {"cmd": 300, "aid": ACCOUNT_ID, "gid": GAME_GID},
  ]
  return _dumps(frame)


def build_ws_payload_join_room(room_id: int) -> str:
  """
  Join phòng theo rid.

  Từ log:
    [3,"Simms",54,""]   → join phòng rid=54
  """
  frame: list[Any] = [
      3,
      ZONE_NAME,
      int(room_id),
      "",
  ]
  return _dumps(frame)


def build_ws_payload_leave_room() -> str:
  """
  Thoát khỏi phòng về lobby.

  Từ log:
    [4,"Simms",-1]
  """
  frame: list[Any] = [
      4,
      ZONE_NAME,
      -1,
  ]
  return _dumps(frame)
