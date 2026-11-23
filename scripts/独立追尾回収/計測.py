"""固定O49の単独一枠運用を、過去状態の引継ぎと終端打切りで測る。"""

from array import array
from bisect import bisect_left
from copy import deepcopy
from decimal import Decimal
import hashlib
import importlib.util
from pathlib import Path
import sys


HERE = Path(__file__).resolve().parent
OPERATION_PATH = HERE.parent / "定時帯反応/運用.py"
OPERATION_SHA256 = "93c3a63df95558ef8c356794a773f560a20a95428887d2683a4906f7b32a899c"
if hashlib.sha256(OPERATION_PATH.read_bytes()).hexdigest() != OPERATION_SHA256:
    raise ValueError("固定O49の出典SHA256が不一致")
SPEC = importlib.util.spec_from_file_location("独立追尾回収が固定参照するO49", OPERATION_PATH)
O49 = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = O49
SPEC.loader.exec_module(O49)
EVENT_COLUMNS = ("now", "line", "last", "bid", "ask", "valid")
QUALITY_FIELDS = ("保有中長気配間隔数", "判定不能枠数", "損益注意理由", "損益確定可能", "未解消建玉数", "未解消注文数", "活動評価適格", "全枠判定可能")


def comparison_view(result: dict) -> dict:
    """全期間単独O49と高速測定を同じ経済・保有品質の射影へ写す。

    引数: result(dict)はO49標準結果又は高速測定結果。
    返り値: dictは注文/約定/完結/判断/保有追尾/損益品質/標準集計。flat後のログ・品質数は含めない。
    """
    required = {"closed", "trades", "orders", "decisions", "trail", "quality", "metrics", "final_state"}
    if not isinstance(result, dict) or not required <= set(result):
        raise ValueError("O49標準結果の必須項目が不足")
    active = [row for row in result["trail"] if row["state"]["position"] is not None or row["state"]["pending"] is not None
        or row["action"] in ("定時判断", "返済約定", "新規取消")]
    return deepcopy({"closed": result["closed"], "trades": result["trades"], "orders": result["orders"],
        "decisions": result["decisions"], "active_trail": active,
        "quality": {k: result["quality"][k] for k in QUALITY_FIELDS},
        "metrics": result["metrics"], "final_state": result["final_state"]})


class MeasurementBank:
    """一場の有限非後退6列を一回索引化し、任意枠を独立に測定する。"""

    def __init__(self, events: list[dict], session: str, bounds: dict | None = None):
        """場内入力を変更せず保持し、各原行直前のflat状態を構築する。

        引数: events(list[dict])はC49.events_for相当の6列、session(str)は場名、bounds(dict|None)は人工時計用。
        返り値: None。原板/キャッシュ/教師を開かず、正常気配は元validも含めて判定する。
        """
        if not isinstance(events, list):
            raise ValueError("eventsは場内6列のlistが必要")
        self.session = session
        self.bounds = O49.session_bounds(session) if bounds is None else {k: O49.number(bounds[k], k) for k in ("start", "force", "end")}
        if not self.bounds["start"] < self.bounds["force"] < self.bounds["end"]:
            raise ValueError("開始<強制<終了が必要")
        self._records, self._lines, self._times = [], [], array("d")
        self._last_normal, self._bad, self._flat_gap = array("q", [-1]), array("Q", [0]), array("Q", [0])
        previous_time, previous_line, last_normal = None, 0, -1
        for index, source in enumerate(events):
            if not isinstance(source, dict) or set(source) != set(EVENT_COLUMNS) or type(source["valid"]) is not bool or type(source["line"]) is not int or source["line"] <= previous_line:
                raise ValueError("6列schema/valid/原行strict昇順が不正")
            if not O49.finite(source["now"]):
                raise ValueError("prefix入力は有限価格時計に限定")
            now = float(source["now"])
            if previous_time is not None and now < previous_time or not self.bounds["start"] <= now < self.bounds["end"]:
                raise ValueError("prefix入力は場内・非後退時計に限定")
            if any(not isinstance(source[k], (int, float, Decimal, str, type(None))) for k in ("last", "bid", "ask")):
                raise ValueError("価格列は不変の数値/欠測値が必要")
            record = (now, source["line"], source["last"], source["bid"], source["ask"], source["valid"])
            normal = O49.normal_bbo(source)
            gap = normal and last_normal >= 0 and now - self._records[last_normal][0] > 300
            if normal:
                last_normal = index
            self._records.append(record)
            self._lines.append(source["line"])
            self._times.append(now)
            self._last_normal.append(last_normal)
            self._bad.append(self._bad[-1] + int(not normal))
            self._flat_gap.append(self._flat_gap[-1] + int(gap))
            previous_time, previous_line = now, source["line"]
        self._records = tuple(self._records)

    def _prefix(self, index: int) -> dict:
        """切出原行よりstrict前のO49時計・正常気配・flat品質を取り出す。

        引数: index(int)は最初に供給する原行の配列位置。
        返り値: dictは未来を含まないseed。切出前の前正常気配も保持する。
        """
        previous = self._records[index - 1] if index else None
        normal_index = self._last_normal[index]
        return {"last_time": previous[0] if previous else None, "last_line": previous[1] if previous else None,
            "raw_line": previous[1] if previous else 0,
            "last_quote_time": self._records[normal_index][0] if normal_index >= 0 else None,
            "非正常BBO行数": int(self._bad[index]), "空き時間長気配間隔数": int(self._flat_gap[index])}

    def measure(self, slot: dict, candidate_id: str = "独立測定", *, background_direction: int | None = None) -> dict:
        """一枠をflatから独立運用し、最初の完結又は新規取消の後を省略する。

        引数: slot(dict)は純O49判断、candidate_id(str)は比較時も共通の識別子、background_direction(int|None)はDI同値仮役割の説明用。
        返り値: dictはO49標準結果一式とmeasurement。単独損益品質は全期間singletonと同じ。
        """
        if not isinstance(candidate_id, str) or not candidate_id:
            raise ValueError("測定識別子が必要")
        if background_direction is not None and (type(background_direction) is not int or background_direction not in (-1, 0, 1)):
            raise ValueError("説明用DI方向は±1/0/None")
        if background_direction == 0 and slot.get("side") in (-1, 1) and slot.get("role") != "順行":
            raise ValueError("DI同値の測定用仮役割は順行")
        engine = O49.Engine([slot], self.session, candidate_id, self.bounds)
        normalized = engine.slots[0]
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
        engine.last_time, engine.last_line, engine.raw_line, engine.last_quote_time = (prefix[k] for k in ("last_time", "last_line", "raw_line", "last_quote_time"))
        engine.quality["非正常BBO行数"] = prefix["非正常BBO行数"]
        engine.quality["空き時間長気配間隔数"] = prefix["空き時間長気配間隔数"]
        scanned, cut = {"count": 0, "last": None}, {"reason": "入力末尾"}

        def shortened():
            """O49が処理した後だけ終端を確認し、将来の価格で停止を決めない。

            引数: なし。closure内のengineと開始indexを参照する。
            返り値: generator[dict]は必要な原行。タイマーと最終処理はO49に委ねる。
            """
            for index in range(start, len(self._records)):
                if engine.closed:
                    cut["reason"] = "初回完結"
                    break
                if engine.done and engine.position is None and engine.pending is None:
                    cut["reason"] = "新規取消" if any(o["status"] == "cancelled" for o in engine.orders) else "無新規判断終了"
                    break
                scanned["count"] += 1
                scanned["last"] = index
                yield dict(zip(EVENT_COLUMNS, self._records[index]))

        result = engine.run(shortened())
        last_scanned = self._records[scanned["last"]] if scanned["last"] is not None else None
        result["measurement"] = {"独立一枠測定": True, "同時実行可能な全体売買ではない": True,
            "予定枠分母": 1, "全予定枠活動の評価には使わない": True,
            "入力イベント数": len(self._records), "prefixイベント数": start, "供給イベント数": scanned["count"],
            "切出開始key": list(self._records[start][:2]) if start < len(self._records) else None,
            "走査最終key": list(last_scanned[:2]) if last_scanned else None, "打切理由": cut["reason"],
            "prefix": prefix, "background_direction": background_direction,
            "役割説明": "DI同値・測定用順行仮置。後段のDI0WAITは変更しない" if background_direction == 0 else "引数の測定役割。DI同値か不明なら推測しない",
            "一致範囲": "comparison_view: 注文/約定/完結/判断/実取引追尾/保有中注意/損益確定/標準metrics",
            "非一致範囲": "打切後のflat品質件数とflat強制ログ。終了時の価格時計出典は未走査分を補わない",
            "固定運用SHA256": OPERATION_SHA256}
        return result


def measure(events: list[dict], slot: dict, session: str, candidate_id: str = "独立測定", bounds: dict | None = None, *, background_direction: int | None = None) -> dict:
    """単発用に銀行を作り、同じ独立一枠測定を呼ぶ。

    引数: events(list[dict])は場内6列、slot(dict)は純判断、session/candidate_id(str)は識別、bounds(dict|None)は人工時計、background_direction(int|None)は説明用。
    返り値: dictは標準O49結果とmeasurement。多数枠ではMeasurementBankを再利用する。
    """
    return MeasurementBank(events, session, bounds).measure(slot, candidate_id, background_direction=background_direction)
