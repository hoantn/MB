# engine/phom/state.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Set, Any, TYPE_CHECKING, List

if TYPE_CHECKING:
    from .analyzer import AnalysisResult

@dataclass
class PhomProfileState:
    # Bài trên tay (cmd 852: sAC)
    hand: Set[int] = field(default_factory=set)
    # Lá đã đánh ra (cmd 851: dCs)
    discards: Set[int] = field(default_factory=set)
    # Lá seen từ cmd 850 (nếu có)
    init_seen: Set[int] = field(default_factory=set)
    my_uid: str | None = None
    my_dn: str | None = None
    my_gold: int | None = None

    # "Đánh cho ai": "P1"|"P2"|"P3"|"OPP"
    play_for: str = "OPP"

    # Kết quả phân tích Phase 2A (melds/trash/suggest)
    analysis: "AnalysisResult|None" = None
    # Log sự kiện WS trong ván để UI render realtime theo thứ tự
    events: list[dict] = field(default_factory=list)

@dataclass
class PhomState:
    profiles: Dict[str, PhomProfileState] = field(default_factory=dict)
    turn_order_uids: List[str] = field(default_factory=list)
    uid_to_profile: Dict[str, str] = field(default_factory=dict)

    def get_profile(self, profile_id: str) -> PhomProfileState:
        if profile_id not in self.profiles:
            st = PhomProfileState()
            # mặc định: P1 đánh cho P1, P2 đánh cho P2, P3 đánh cho P3
            st.play_for = profile_id if profile_id in ("P1", "P2", "P3") else "OPP"
            self.profiles[profile_id] = st
        else:
            st = self.profiles[profile_id]
            # nếu state cũ chưa có play_for thì set 1 lần cho khỏi rỗng
            if getattr(st, "play_for", None) in (None, ""):
                st.play_for = profile_id if profile_id in ("P1", "P2", "P3") else "OPP"
        return st

    def as_debug_dict(self) -> Dict[str, Any]:
        out = {}
        for pid, st in self.profiles.items():
            out[pid] = {
                "hand": sorted(st.hand),
                "discards": sorted(st.discards),
                "init_seen": sorted(st.init_seen),
                "has_analysis": st.analysis is not None,
            }
        return out
