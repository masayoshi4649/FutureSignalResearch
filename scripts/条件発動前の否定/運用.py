"""固定67の条件発動へ、正常Lastによる反対端否定だけを追加する。"""

from copy import deepcopy
import importlib.util
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
LEGACY_PATH = ROOT / "scripts/定時候補の価格発動/運用.py"
_SPEC = importlib.util.spec_from_file_location("発動前否定68の固定67運用", LEGACY_PATH)
LEGACY = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = LEGACY
_SPEC.loader.exec_module(LEGACY)

EVENT_FIELDS, SLOT_FIELDS, ROLES = LEGACY.EVENT_FIELDS, LEGACY.SLOT_FIELDS, LEGACY.ROLES
finite, number = LEGACY.finite, LEGACY.number
normal_bbo, normal_observation = LEGACY.normal_bbo, LEGACY.normal_observation
session_bounds, scheduled_times = LEGACY.session_bounds, LEGACY.scheduled_times
signed_distance, current_net = LEGACY.signed_distance, LEGACY.current_net
RULES = {**deepcopy(LEGACY.RULES),
    "設定": "正常BBOと有限正Last。発動線既strict外側は拒否。発動端等号は未発動だが反対端等号は設定否定、高安同値の設定等号も否定",
    "凍結": "元slotのside/role/ATR/Dと高安を固定し、途中の指標更新なし。固定反対端の否定だけを追加",
    "設定否定": "旧優先条件と設定既超過の判定後、買Last<=low又は売Last>=highなら待ち・未登録",
    "監視否定": "設定keyよりstrict後、gap>300優先、正常BBOかつ有限正Lastの時計更新後に反対端否定なら前提否定取消",
    "否定の範囲": "発動前の条件監視だけ。同枠復活・自動反対注文なし。発動後の新規pending・保有は取消さない",
    "否定と品質": "価格前提の否定は観測不足でなく品質注意なし。登録後未約定として保守待ちへ含める"}


def opposite_denied(side: int, last: float, condition: dict) -> bool:
    """実方向に対する固定反対端の否定を等号込みで判定する。

    引数: side(int)は±1、last(float)は正常観測の有限正Last、condition(dict)は固定high/lowを持つ条件。
    返り値: boolは買Last<=low又は売Last>=high。呼出側が観測正常性と時点を保証する。
    """
    return last <= condition["low"] if side == 1 else last >= condition["high"]


# ----------------------------------------


class Engine(LEGACY.Engine):
    """旧条件運用を継承し、設定時と発動前の価格否定だけを差し替える。"""

    def decide(self, index: int, event: dict | None) -> None:
        """旧定時優先を守り、既超過でない正常候補の設定否定を保存する。

        引数: index(int)は予定枠番号、event(dict|None)は当時の判断行又は欠測placeholder。
        返り値: None。否定以外は固定67へ委ね、元slotや旧大域値を変更しない。
        """
        slot = self.slots[index]
        row = self.conditions.get(slot["slot_id"])
        eligible = (index not in self.done and event is not None and normal_bbo(event)
            and self.pending is None and self.position is None and self.watch is None
            and slot["ready"] and not self.forced and slot["side"] != 0)
        if not eligible or row is None or not normal_observation(event):
            super().decide(index, event)
            return
        condition = row["condition"]
        outside = event["last"] > condition["high"] if slot["side"] == 1 else event["last"] < condition["low"]
        if outside or not opposite_denied(slot["side"], event["last"], condition):
            super().decide(index, event)
            return
        if slot["role"] not in ROLES or not finite(slot["atr"]) or slot["atr"] <= 0 or not finite(slot["D"]) or not 5 <= slot["D"] <= 125:
            raise ValueError("新規には実役割・有限正ATR・5<=D<=125が必要")
        self.done.add(index)
        reason = "設定時に反対端を否定"
        row.update(status="終了", condition_outcome="設定否定", condition_reason=reason,
            end_time=slot["time"], end_line=slot["line"])
        self.condition_log("条件未登録", slot["slot_id"], slot["time"], slot["line"], reason)
        decision = {**deepcopy(slot), "holding": False, "pending_kind": None,
            "position_id": None, "watching": False, "action": "待ち",
            "decision_reason": reason, "wait": True, "activity_valid": True}
        self.decisions.append(decision)
        self.log("定時判断", slot["time"], slot["line"], decision=decision)

    def observe_watch(self, event: dict) -> None:
        """正常な発動前監視にだけ反対端否定を挿入する。

        引数: event(dict)は有限非後退価格時計の当行。
        返り値: None。gap取消・正常時計更新・否定・strict発動の順を守る。
        """
        watch = self.watch
        if watch is not None:
            now, line = event["now"], event["line"]
            after = (now, line) > (watch["time"], watch["line"])
            if after and now - watch["last_observation_time"] <= 300 and normal_observation(event):
                slot_id = watch["slot_id"]
                row = self.conditions[slot_id]
                if opposite_denied(row["slot"]["side"], event["last"], row["condition"]):
                    watch["last_observation_time"] = now
                    row["last_observation_time"] = now
                    self.end_watch(now, line, "発動前に反対端を否定")
                    row["condition_outcome"] = "前提否定"
                    return
        super().observe_watch(event)


def replay(events, slots: list[dict], conditions: dict, session: str,
        candidate_id: str = "N0", bounds: dict | None = None) -> dict:
    """固定67と同じ公開入口で、発動前否定を持つ候補を運用する。

    引数: events(iterable[dict])は元6列原行、slots(list[dict])は純判断、conditions(dict)は固定4キー条件、session/candidate_id(str)は識別、bounds(dict|None)は人工時計。
    返り値: dictは旧67互換operation。価格否定の終端2種だけを追加する。
    """
    return Engine(slots, conditions, session, candidate_id, bounds).run(events)
