"""固定68の一枠条件入口を、prefix継承と条件終端打切りで独立測定する。"""

from bisect import bisect_left
from copy import deepcopy
import hashlib
import importlib.util
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
SHARED_SHA256 = {
    "scripts/独立追尾回収/計測.py": "26f1c6f846cce9286a87ee1ab54094a38d83c23c4255335c65a807bb7ccd3e01",
    "scripts/条件発動前の否定/運用.py": "0c107e406dc71531f6d25cf77c245bb96ab0174f6cdff4386645a76ae89c1d9b",
    "scripts/条件発動前の否定/先着.py": "f6546699516c008e29a6d118a319167807ab6e8747e54bbf0e654990bd09b2eb",
}


def load_fixed(relative: str, name: str):
    """固定SHAを確認して既存コードを固有名で読む。

    引数: relative(str)はroot相対コード、name(str)は固有モジュール名。
    返り値: ModuleTypeは固定コード。旧大域値・ファイルを変更しない。
    """
    path = ROOT / relative
    if hashlib.sha256(path.read_bytes()).hexdigest() != SHARED_SHA256[relative]:
        raise ValueError("固定参照SHA256差:" + relative)
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


PREFIX = load_fixed("scripts/独立追尾回収/計測.py", "条件教師69の固定55prefix")
O68 = load_fixed("scripts/条件発動前の否定/運用.py", "条件教師69の固定68運用")
LABELS = load_fixed("scripts/条件発動前の否定/先着.py", "条件教師69の固定68先着")
EVENT_COLUMNS = PREFIX.EVENT_COLUMNS
QUALITY_FIELDS = (*PREFIX.QUALITY_FIELDS, "条件監視観測不足取消数")


def comparison_view(result: dict) -> dict:
    """完全一枠再生と短区間測定を、経済・条件・保有品質の共通射影へ写す。

    引数: result(dict)は固定68標準operation又は独立測定の返り値。
    返り値: dictは注文・約定・完結・判断・条件全文と遷移・活動中追尾・損益品質・集計・最終状態。
    """
    required = {"closed", "trades", "fills", "orders", "decisions", "trail", "quality", "metrics",
        "final_state", "conditions", "condition_trace"}
    if not isinstance(result, dict) or not required <= set(result):
        raise ValueError("固定68標準結果の必須項目が不足")
    active = [row for row in result["trail"] if row["state"]["position"] is not None
        or row["state"]["pending"] is not None or row["state"]["watch"] is not None
        or row["action"] in ("定時判断", "返済約定", "新規取消")]
    return deepcopy({"closed": result["closed"], "trades": result["trades"], "fills": result["fills"],
        "orders": result["orders"], "decisions": result["decisions"], "conditions": result["conditions"],
        "condition_trace": result["condition_trace"], "active_trail": active,
        "quality": {key: result["quality"][key] for key in QUALITY_FIELDS},
        "metrics": result["metrics"], "final_state": result["final_state"]})


def verify_entry(result: dict, label: dict | None, slot_id: str) -> bool | None:
    """独立68先着と単独運用の条件結果・発動・新規BBOを照合する。

    引数: result(dict)は一枠operation、label(dict|None)は独立先着、slot_id(str)は元定時ID。
    返り値: bool|Noneは対象なら一致True、非準備又はside0等で先着対象外ならNone。不一致は例外。
    """
    if label is None:
        return None
    row = result["conditions"][slot_id]
    for key in ("condition", "origin_slot", "trigger", "request_time", "request_line", "condition_outcome", "watch_started", "watch_quality"):
        if row[key] != label[key]:
            raise ValueError("独立先着と単独条件の差:" + key)
    orders = [order for order in result["orders"] if order["kind"] == "entry" and order["status"] == "filled"]
    if bool(orders) != label["filled"] or len(orders) > 1 or row["entry_filled"] != label["filled"]:
        raise ValueError("独立先着と実新規有無の差")
    if orders:
        order = orders[0]
        if (order["fill_time"], order["fill_line"], order["fill_price"]) != (label["entry_time"], label["entry_line"], label["entry_price"]):
            raise ValueError("独立先着と実新規時刻・原行・価格の差")
        if (row["entry_time"], row["entry_line"], row["entry_price"]) != (label["entry_time"], label["entry_line"], label["entry_price"]):
            raise ValueError("条件記録と独立先着新規の差")
    elif (row["end_time"], row["end_line"]) != (label["end_time"], label["end_line"]):
        raise ValueError("非約定の条件終了keyと独立先着の差")
    return True


# ----------------------------------------


class MeasurementBank(PREFIX.MeasurementBank):
    """一場のprefix銀行と独立先着索引を一度だけ作り、両方向を別々に測る。"""

    def __init__(self, events: list[dict], session: str, bounds: dict | None = None):
        """固定55の厳密前prefixを再用し、68先着の索引を一度構築する。

        引数: events(list[dict])はC49.events_for相当の場内6列、session(str)は場名、bounds(dict|None)は人工時計。
        返り値: None。原板・キャッシュ・特徴・教師・モデルは開かない。
        """
        super().__init__(events, session, bounds)
        self._label_index = LABELS.prepare_events(dict(zip(EVENT_COLUMNS, row)) for row in self._records)

    def measure(self, slot: dict, condition: dict, candidate_id: str = "独立条件測定",
            background_direction: int | None = None) -> dict:
        """一枠をflatから測定し、条件とポジションが終結した後だけ省略する。

        引数: slot(dict)はsession/policy/feature等の追加を許す元判断、condition(dict)は固定4キー条件、candidate_id(str)は識別、background_direction(int|None)は説明用DI方向。
        返り値: dictは68標準operationとmeasurement。独立先着をmeasurement['独立先着']へ保存する。
        """
        if not isinstance(slot, dict) or not isinstance(candidate_id, str) or not candidate_id:
            raise ValueError("元判断辞書と測定識別子が必要")
        if "session" in slot and slot["session"] != self.session:
            raise ValueError("元判断と銀行の場名が不一致")
        if background_direction is not None and (type(background_direction) is not int or background_direction not in (-1, 0, 1)):
            raise ValueError("説明用DI方向は±1/0/None")
        if background_direction == 0 and slot.get("side") in (-1, 1) and slot.get("role") != "順行":
            raise ValueError("DI同値の測定用仮役割は順行")
        pure = {key: deepcopy(slot[key]) for key in O68.SLOT_FIELDS if key in slot}
        if not (O68.SLOT_FIELDS - {"slot_id"}) <= set(pure):
            raise ValueError("固定68純判断のフィールドが不足")
        engine = O68.Engine([pure], {pure.get("slot_id", candidate_id + "_定時0001"): condition}, self.session, candidate_id, self.bounds)
        normalized = engine.slots[0]
        slot_id = normalized["slot_id"]
        first_at_schedule = bisect_left(self._times, normalized["scheduled"])
        if normalized["line"] is None:
            start = first_at_schedule
        else:
            start = bisect_left(self._lines, normalized["line"])
            if start == len(self._records) or self._records[start][1] != normalized["line"] or self._records[start][0] != normalized["time"]:
                raise ValueError("実判断の原行/時計が入力に見つからない")
            if start != first_at_schedule:
                raise ValueError("slotは予定以後最初の価格時計原行が必要。正常BBOまで待ち直さない")
        prefix = self._prefix(start)
        engine.last_time, engine.last_line, engine.raw_line, engine.last_quote_time = (prefix[key] for key in ("last_time", "last_line", "raw_line", "last_quote_time"))
        engine.quality["非正常BBO行数"] = prefix["非正常BBO行数"]
        engine.quality["空き時間長気配間隔数"] = prefix["空き時間長気配間隔数"]
        scanned, cut = {"count": 0, "last": None}, {"reason": "入力末尾"}

        def shortened():
            """処理後にwatch・条件・注文・保有の全終結を確認する。

            引数: なし。closure内のengineと開始indexを使う。
            返り値: generator[dict]は必要な原行。登録しただけのflatを終端にしない。
            """
            for index in range(start, len(self._records)):
                ended = engine.done and engine.watch is None and engine.position is None and engine.pending is None
                ended = ended and all(row["status"] == "終了" for row in engine.conditions.values())
                if ended:
                    cut["reason"] = "初回完結" if engine.closed else "条件終了:" + engine.conditions[slot_id]["condition_outcome"]
                    break
                scanned["count"] += 1
                scanned["last"] = index
                yield dict(zip(EVENT_COLUMNS, self._records[index]))

        result = engine.run(shortened())
        label = None
        if normalized["ready"] and normalized["side"] in (-1, 1) and normalized["line"] is not None:
            label_slot = {**deepcopy(normalized), "session": self.session, "policy": slot.get("policy", candidate_id)}
            label = LABELS.label(self._label_index, label_slot, condition, self.bounds["force"], self.bounds["end"])
        matched = verify_entry(result, label, slot_id)
        last_scanned = self._records[scanned["last"]] if scanned["last"] is not None else None
        result["measurement"] = {"独立一枠測定": True, "同時実行可能な全体売買ではない": True,
            "予定枠分母": 1, "全予定枠活動の評価には使わない": True,
            "入力イベント数": len(self._records), "prefixイベント数": start, "供給イベント数": scanned["count"],
            "切出開始key": list(self._records[start][:2]) if start < len(self._records) else None,
            "走査最終key": list(last_scanned[:2]) if last_scanned else None, "打切理由": cut["reason"],
            "prefix": prefix, "background_direction": background_direction,
            "役割説明": "DI同値・測定用順行仮置。後段DI0WAITは変更しない" if background_direction == 0 else "引数の測定役割。DI同値か不明なら推測しない",
            "独立先着": label, "独立先着約定一致": matched,
            "一致範囲": "comparison_view: 注文/約定/完結/判断/条件/条件遷移/活動中追尾/保有・条件監視中注意/損益確定/標準metrics",
            "非一致範囲": "条件と建玉の終結後のflat品質件数・flat強制ログ。未走査の原行をtimer出典へ補わない",
            "教師の確定": "独立先着の既知・未知と、operationの損益品質を別に判定する。設定観測不足を無取引0へ補完しない",
            "固定参照SHA256": deepcopy(SHARED_SHA256)}
        return result
