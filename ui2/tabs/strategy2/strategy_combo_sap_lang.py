from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple

from .strategy_anti_sap import _codes_to_threechi, _eval_vs_opp, _EvalInfo


PROFILES = ("P1", "P2", "P3")


@dataclass(frozen=True)
class SapLangCombo:
    leader: str
    suggestions: Dict[str, dict]
    score: Tuple[int, int, int, int]


def _is_playable(s: Optional[dict]) -> bool:
    if not s:
        return False
    return (
        len(list(s.get("chi1_codes") or [])) == 5
        and len(list(s.get("chi2_codes") or [])) == 5
        and len(list(s.get("chi3_codes") or [])) == 3
    )


def _split_key(s: dict) -> Tuple[str, ...]:
    return tuple(
        list(s.get("chi1_codes") or [])
        + list(s.get("chi2_codes") or [])
        + list(s.get("chi3_codes") or [])
    )


def _candidate_pool(items: Iterable[dict], ws_codes: List[str], max_items: int = 24) -> List[dict]:
    """Collect playable candidates that use exactly the current 13 cards."""
    out: List[dict] = []
    seen = set()
    ws_counter = Counter(map(str, ws_codes or []))
    for item in items or []:
        if not _is_playable(item):
            continue
        key = _split_key(item)
        if key in seen:
            continue
        if len(key) != 13 or Counter(map(str, key)) != ws_counter:
            continue
        seen.add(key)
        out.append(dict(item))
        if len(out) >= max_items:
            break
    return out


def _score_vs_opp(info: _EvalInfo) -> Tuple[int, int, int, int]:
    return (int(info.wins), -int(info.losses), int(info.draws), int(info.total_money))


def _best_follower_candidate(
    *,
    candidates: List[dict],
    leader_suggestion: dict,
    opp_suggestion: dict,
) -> Optional[Tuple[dict, Tuple[int, int, int, int]]]:
    leader_three = _codes_to_threechi(leader_suggestion)
    opp_three = _codes_to_threechi(opp_suggestion)
    if leader_three is None or opp_three is None:
        return None

    best: Optional[Tuple[dict, Tuple[int, int, int, int]]] = None
    for cand in candidates:
        cand_three = _codes_to_threechi(cand)
        if cand_three is None:
            continue

        # Follower must lose all 3 chis to the leader so the leader can sap-lang.
        vs_leader = _eval_vs_opp(cand_three, leader_three)
        if not vs_leader.lose_all:
            continue

        # Among valid "nhuong" candidates, keep the one best versus OPP.
        vs_opp = _eval_vs_opp(cand_three, opp_three)
        score = _score_vs_opp(vs_opp)
        if best is None or score > best[1]:
            best = (cand, score)
    return best


def find_sap_lang_combo(
    *,
    suggestions_by_pid: Dict[str, List[dict]],
    ws_codes_by_pid: Dict[str, List[str]],
    opp_suggestion: Optional[dict],
) -> Optional[SapLangCombo]:
    """Find a 3P combo where one P sweeps OPP and both other P hands."""
    if not _is_playable(opp_suggestion):
        return None
    opp_three = _codes_to_threechi(opp_suggestion or {})
    if opp_three is None:
        return None

    pools: Dict[str, List[dict]] = {}
    for pid in PROFILES:
        ws_codes = list(ws_codes_by_pid.get(pid) or [])
        if len(ws_codes) != 13:
            return None
        pool = _candidate_pool(suggestions_by_pid.get(pid) or [], ws_codes)
        if not pool:
            return None
        pools[pid] = pool

    best_combo: Optional[SapLangCombo] = None

    for leader in PROFILES:
        followers = [pid for pid in PROFILES if pid != leader]
        for leader_s in pools[leader]:
            leader_three = _codes_to_threechi(leader_s)
            if leader_three is None:
                continue

            leader_vs_opp = _eval_vs_opp(leader_three, opp_three)
            if not leader_vs_opp.win_all:
                continue

            follower_picks: Dict[str, dict] = {}
            follower_scores: List[Tuple[int, int, int, int]] = []
            ok = True
            for follower in followers:
                picked = _best_follower_candidate(
                    candidates=pools[follower],
                    leader_suggestion=leader_s,
                    opp_suggestion=opp_suggestion or {},
                )
                if picked is None:
                    ok = False
                    break
                follower_picks[follower] = picked[0]
                follower_scores.append(picked[1])

            if not ok:
                continue

            total_score = (
                int(leader_vs_opp.total_money) + sum(s[3] for s in follower_scores),
                int(leader_vs_opp.wins) + sum(s[0] for s in follower_scores),
                -int(leader_vs_opp.losses) + sum(s[1] for s in follower_scores),
                int(leader_vs_opp.draws) + sum(s[2] for s in follower_scores),
            )
            suggestions = {leader: dict(leader_s)}
            suggestions.update(follower_picks)
            combo = SapLangCombo(leader=leader, suggestions=suggestions, score=total_score)
            if best_combo is None or combo.score > best_combo.score:
                best_combo = combo

    return best_combo
