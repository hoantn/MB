from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Dict, List, Optional, Tuple

from ui2.tabs.strategy2.modules.auto_play_controller import (
    AutoPlayPlan,
    PROFILES,
    build_auto_play_plan,
)
from ui2.tabs.strategy2.modules.pre_render_worker import (
    _build_render_suggestions as _build_pre_render_suggestions,
    copy_suggestion,
    copy_suggestions,
)
from ui2.tabs.strategy2.modules.special_row import is_special_row
from ui2.tabs.strategy2.strategy_combo_sap_lang import SapLangCombo


@dataclass(frozen=True)
class AutoOppPlanSnapshot:
    request_id: int
    signature: tuple
    session: int
    hand_key: str
    room_context_key: str
    suggestions: Dict[str, List[dict]]
    suggestions_render: Dict[str, List[dict]]
    codes_slot_order: Dict[str, List[str]]
    hand_generation: Dict[str, int]
    ngu_suggestions: List[dict]
    applied_profile_keys: Tuple[str, ...]
    anti_sap_enabled: bool
    allow_intentional_foul: bool
    special_mode: str


@dataclass(frozen=True)
class AutoOppPlanResult:
    request_id: int
    signature: tuple
    session: int
    hand_key: str
    room_context_key: str
    plan: Optional[AutoPlayPlan]
    elapsed_ms: float
    error: Optional[str] = None


class _AutoOppPlanFacade:
    """Small data-only facade for build_auto_play_plan.

    The real StrategyTab owns UI state and timers. The worker only needs a
    stable, copied snapshot of the data read by auto_play_controller.
    """

    profiles = PROFILES

    def __init__(self, snapshot: AutoOppPlanSnapshot) -> None:
        self._snapshot = snapshot
        self._suggestions = {
            pid: copy_suggestions((snapshot.suggestions or {}).get(pid) or [])
            for pid in PROFILES
        }
        self._suggestions_render = {
            pid: copy_suggestions((snapshot.suggestions_render or {}).get(pid) or [])
            for pid in PROFILES
        }
        self._codes_slot_order = {
            pid: list((snapshot.codes_slot_order or {}).get(pid) or [])
            for pid in PROFILES
        }
        self._hand_generation = {
            pid: int((snapshot.hand_generation or {}).get(pid, 0) or 0)
            for pid in PROFILES
        }
        self._ngu_suggestions = copy_suggestions(snapshot.ngu_suggestions or [])
        self._auto_play_applied_profile_keys = set(snapshot.applied_profile_keys or ())
        self._anti_sap_enabled = bool(snapshot.anti_sap_enabled)
        self._SPECIAL_MODE = str(snapshot.special_mode or "__special13__")

    def _is_special_row(self, item: Optional[dict]) -> bool:
        return is_special_row(item, special_mode=self._SPECIAL_MODE)

    def _auto_profile_apply_key(self, pid: str) -> str:
        cards = list(self._codes_slot_order.get(pid) or [])
        generation = int(self._hand_generation.get(pid, 0) or 0)
        return f"{pid}:g{generation}:{','.join(sorted(map(str, cards)))}"

    def _build_render_suggestions(self, base_suggs: List[dict], opp: Optional[dict]) -> List[dict]:
        return _build_pre_render_suggestions(
            copy_suggestions(base_suggs or []),
            copy_suggestion(opp),
            bool(self._anti_sap_enabled),
        )


def run_auto_opp_plan_snapshot(snapshot: AutoOppPlanSnapshot) -> AutoOppPlanResult:
    start = time.perf_counter()
    try:
        facade = _AutoOppPlanFacade(snapshot)
        plan = build_auto_play_plan(
            facade,
            max_opp=3,
            allow_intentional_foul=bool(snapshot.allow_intentional_foul),
        )
        return AutoOppPlanResult(
            request_id=int(snapshot.request_id),
            signature=snapshot.signature,
            session=int(snapshot.session),
            hand_key=str(snapshot.hand_key or ""),
            room_context_key=str(snapshot.room_context_key or ""),
            plan=_copy_auto_play_plan(plan),
            elapsed_ms=(time.perf_counter() - start) * 1000.0,
        )
    except Exception as exc:
        return AutoOppPlanResult(
            request_id=int(snapshot.request_id),
            signature=snapshot.signature,
            session=int(snapshot.session),
            hand_key=str(snapshot.hand_key or ""),
            room_context_key=str(snapshot.room_context_key or ""),
            plan=None,
            elapsed_ms=(time.perf_counter() - start) * 1000.0,
            error=repr(exc),
        )


def _copy_auto_play_plan(plan: Optional[AutoPlayPlan]) -> Optional[AutoPlayPlan]:
    if plan is None:
        return None

    combo = None
    if plan.combo is not None:
        combo = SapLangCombo(
            leader=str(plan.combo.leader),
            suggestions={pid: copy_suggestion(sug) for pid, sug in (plan.combo.suggestions or {}).items()},
            score=tuple(int(x) for x in plan.combo.score),
        )

    return AutoPlayPlan(
        kind=str(plan.kind),
        opp_index=int(plan.opp_index),
        score=tuple(int(x) for x in plan.score),
        selected_index={pid: int(idx) for pid, idx in (plan.selected_index or {}).items()},
        suggestions={pid: copy_suggestion(sug) for pid, sug in (plan.suggestions or {}).items()},
        combo=combo,
        delay_each_profile=bool(plan.delay_each_profile),
        partial=bool(plan.partial),
        report_binh_pids=tuple(str(pid) for pid in (plan.report_binh_pids or ())),
        dependency_groups=tuple(tuple(str(pid) for pid in group) for group in (plan.dependency_groups or ())),
    )
