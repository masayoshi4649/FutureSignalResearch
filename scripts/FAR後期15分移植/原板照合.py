"""80の保存注文を、原板の最初の正常後原行へ独立に結合する。

既定は人工gzipだけのself_test。本物は--runと対象sessionを明示する。
Goコードをimport・実行せず、原板を複製しない。取消時刻は保存注文に
含まれないため、取消理由の正しさは本検査の対象にしない。
"""

import argparse
from collections import Counter
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import gzip
import hashlib
import heapq
import json
import math
from pathlib import Path
import re
import sys
import tempfile


MODES = ("F0", "P1", "T1")
JST = timezone(timedelta(hours=9))
CLOCK = re.compile(r"^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d+))?(Z|[+-]\d{2}:\d{2})$")


def bad_constant(value: str) -> None:
    """GoのJSONが受け付けない非有限リテラルを拒否する。

    引数: value(str)はNaN等の表記。
    返り値: None。常にValueErrorを送出する。
    """
    raise ValueError("非有限JSONリテラル:" + value)


def read_json(path: Path) -> dict:
    """指定した小型正本だけをUTF-8で読む。

    引数: path(Path)は台帳又は保存結果。
    返り値: dictは保存値。市場への再生や補完をしない。
    """
    return json.loads(path.read_text(encoding="utf-8"), parse_constant=bad_constant)


def sha(path: Path) -> str:
    """圧縮ファイル又は小型正本のbyte指紋を得る。

    引数: path(Path)は既存ファイル。
    返り値: strはSHA256。gzip内容のJSON再解釈はしない。
    """
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for data in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(data)
    return digest.hexdigest()


def finite(value: object) -> bool:
    """真偽値と非有限値を通常数値から除外する。

    引数: value(object)は保存値。
    返り値: boolは有限のint又はfloatならTrue。
    """
    return type(value) in (int, float) and math.isfinite(value)


def go_number(value: object) -> float:
    """JSONの数値又はnullをGoのfloat64列と同じ値へ写す。

    引数: value(object)は価格・数量列の値。nullは構造体の初期0に対応する。
    返り値: floatは有限値。文字列等はValueErrorを送出する。
    """
    if value is None:
        return 0.0
    if not finite(value):
        raise ValueError("原板の数値列が不正")
    return float(value)


def clock(value: object) -> float | None:
    """RFC3339の原時計をナノ秒整数からfloat64秒へ写す。

    引数: value(object)は時計文字列又はnull。
    返り値: float|Noneは価格秒又は時計不正。micro秒で切り捨てない。
    """
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("価格時計が文字列又はnullではありません")
    match = CLOCK.fullmatch(value)
    if match is None:
        return None
    y, m, d, hh, mm, ss = map(int, match.groups()[:6])
    zone = match[8]
    try:
        minutes = 0 if zone == "Z" else (1 if zone[0] == "+" else -1) * (int(zone[1:3]) * 60 + int(zone[4:6]))
        at = datetime(y, m, d, hh, mm, ss, tzinfo=timezone(timedelta(minutes=minutes)))
        seconds = int(at.timestamp())
    except (ValueError, OverflowError):
        return None
    nanos = int((match[7] or "")[:9].ljust(9, "0"))
    return float(seconds * 1_000_000_000 + nanos) / 1_000_000_000


def stamp(at: float) -> str:
    """保存Tradeと同じJSTの最短ナノ秒表記を独立に構成する。

    引数: at(float)は採用済み価格秒。
    返り値: strはGoのfloat秒から再構成したRFC3339Nano表記。
    """
    seconds = math.floor(at)
    nanos = math.floor((at - seconds) * 1_000_000_000 + .5)
    if nanos == 1_000_000_000:
        seconds, nanos = seconds + 1, 0
    text = datetime.fromtimestamp(seconds, JST).strftime("%Y-%m-%dT%H:%M:%S")
    return text + (("." + str(nanos).zfill(9).rstrip("0")) if nanos else "") + "+09:00"


def bounds(session: str) -> tuple[float, float]:
    """DayとNightの場内半開区間を元コードと別に定義する。

    引数: session(str)はYYYY-MM-DD_Day又はNight。
    返り値: tuple[float,float]は開始・終了秒。
    """
    date, kind = session.rsplit("_", 1)
    day = datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=JST)
    if kind == "Day":
        return (day + timedelta(hours=8, minutes=45)).timestamp(), (day + timedelta(hours=15, minutes=45)).timestamp()
    if kind == "Night":
        return (day + timedelta(hours=17)).timestamp(), (day + timedelta(days=1, hours=6)).timestamp()
    raise ValueError("場種が不正:" + session)


def small(value: object) -> object:
    """差分をJSONで保存できる小型の表示へ限定する。

    引数: value(object)は比較した値。
    返り値: objectは最大8要素のプレビュー。比較そのものは元の全値で行う。
    """
    if isinstance(value, dict):
        return {"要素数": len(value), "先頭": [[str(k), small(v)] for k, v in list(value.items())[:8]]}
    if isinstance(value, (tuple, list)):
        return [small(v) for v in value[:8]]
    return value


class Audit:
    """差分件数を全て数え、保存する差分の本文だけを上限付きにする。"""

    def __init__(self) -> None:
        """照合数と小型の差分欄を初期化する。

        引数: なし。
        返り値: None。
        """
        self.checks, self.errors, self.details = 0, 0, []

    def check(self, name: str, actual: object, expected: object, **context) -> bool:
        """独立期待値と保存値を比較し、差分を最大30件残す。

        引数: name(str)、actual/expected(object)、context(dict)は小型の識別情報。
        返り値: boolは一致したか。
        """
        self.checks += 1
        equal = actual == expected
        if not equal:
            self.errors += 1
            if len(self.details) < 30:
                self.details.append({"検査": name, "保存又は観測": small(actual), "独立期待": small(expected), **context})
        return equal


def order_key(mode: str, order: dict) -> tuple[str, str]:
    """候補を跨いで重複しない照合キーを作る。

    引数: mode(str)は実比較ID、order(dict)は保存注文。
    返り値: tuple[str,str]は候補と注文ID。
    """
    return mode, order["id"]


def verify_file(source_root: Path, info: dict) -> Path:
    """台帳の圧縮ファイル指紋を照合してから本文読取を許す。

    引数: source_root(Path)は固定入力根、info(dict)はpath/size/sha256。
    返り値: Pathは入力根内の同byteファイル。不一致はValueError。
    """
    root = source_root.resolve()
    path = (root / info["path"]).resolve()
    if not path.is_relative_to(root) or path.stat().st_size != info["size"] or sha(path) != info["sha256"]:
        raise ValueError("入力指紋又は根内パスの不一致:" + str(path))
    return path


class WholePosition:
    """閉じた部分の実純額と残量の返済評価を一つの玉で追跡する。"""

    def __init__(self, books: dict, audit: Audit) -> None:
        """正常原板でだけ更新する全玉台帳を初期化する。

        引数: books(dict)は三案保存値、audit(Audit)は独立照合。
        返り値: None。未来の最高益を現在の旗へ戻さない。
        """
        self.audit = audit
        self.saved = {mode: {lot["id"]: lot for lot in book.get("lots", [])} for mode, book in books.items()}
        self.has_saved = {mode: "lots" in book for mode, book in books.items()}
        self.all = {mode: {} for mode in MODES}
        self.active = {mode: {} for mode in MODES}
        self.reserved = {mode: Counter() for mode in MODES}
        self.reservation_requests = []
        for mode, book in books.items():
            for order in book["orders"]:
                if order["kind"] == "exit":
                    self.reservation_requests.append((order["request_line"], len(self.reservation_requests), mode, order))
        self.reservation_requests.sort(key=lambda item: (item[0], item[1]))
        self.reservation_cursor, self.reservation_heap = 0, []
        self.protection = {mode: {key: 0 for key in ("正常保有原行", "正益後保有原行", "利益床到達原行", "125pt到達原行",
            "返済義務原行", "予約不足原行", "予約不足数量")} for mode in ("P1", "T1")}

    def advance_reservations(self, line: int, at: float) -> None:
        """当原行・当時計までに要求された返済数量だけを予約へ反映する。

        引数: line(int)は物理行、at(float)は採用した価格時計。
        返り値: None。原行と時計の両条件を満たす要求だけを一度反映する。
        """
        while self.reservation_cursor < len(self.reservation_requests):
            request_line, serial, mode, order = self.reservation_requests[self.reservation_cursor]
            if request_line > line:
                break
            heapq.heappush(self.reservation_heap, (order["request_time"], serial, mode, order))
            self.reservation_cursor += 1
        while self.reservation_heap and self.reservation_heap[0][0] <= at:
            _, _, mode, order = heapq.heappop(self.reservation_heap)
            self.reserved[mode][order["position_id"]] += order["quantity"]-order["cancelled_quantity"]

    def fill(self, mode: str, order: dict, line: int, at: float, price: float) -> None:
        """原板一致済みの約定を、当行評価より先に独立台帳へ反映する。

        引数: mode(str)、order(dict)、line(int)、at/price(float)は一致済み約定。
        返り値: None。全玉純額は完結分へ往復122円/枚を控除して累計する。
        """
        identity, quantity = order["position_id"], order["filled_quantity"]
        context = {"候補": mode, "実玉": identity}
        if order["kind"] == "entry":
            if not self.audit.check("全玉の入口ID一度だけ", identity in self.all[mode], False, **context):
                return
            state = {"id": identity, "side": order["side"], "entry": Decimal(str(price)), "initial": quantity,
                "remaining": quantity, "closed": 0, "realized": Decimal(0), "first": None, "peak": None,
                "last": None, "last_line": None, "last_time": None, "entry_line": line, "entry_time": at,
                "residual_first": None, "best_gain": Decimal(0)}
            self.all[mode][identity] = state
            self.active[mode][identity] = state
            return
        state = self.active[mode].get(identity)
        if not self.audit.check("全玉返済の所有と残量", state is not None and state["side"] == order["side"] and state["remaining"] >= quantity, True, **context):
            return
        unit = Decimal(state["side"]) * (Decimal(str(price))-state["entry"]) * 10 - 122
        state["realized"] += unit * quantity
        state["remaining"] -= quantity
        state["closed"] += quantity
        self.reserved[mode][identity] -= quantity

    def observe_residual(self, line: int, index: int, at: float, bid: float, ask: float) -> None:
        """残玉単価の初回strict正益を保存旗とは独立に復元する。

        引数: line/index(int)、at/bid/ask(float)は当行の正常原板。
        返り値: None。返済fill前と全fill後に呼び、全返済直前の初回正益も残す。
        """
        for mode in MODES:
            for state in self.active[mode].values():
                if state["remaining"] <= 0:
                    continue
                mark = Decimal(str(bid if state["side"] > 0 else ask))
                gain = Decimal(state["side"]) * (mark-state["entry"])
                state["best_gain"] = max(state["best_gain"], gain)
                unit = gain * 10 - 122
                if state["residual_first"] is None and unit > 0:
                    state["residual_first"] = {"原行": line, "Index": index, "時計": at,
                        "返済側価格": float(mark), "残玉単価純額円": float(unit)}

    def inspect_protection(self, line: int, index: int, at: float, bid: float, ask: float) -> None:
        """P1/T1の利益床又は125pt保護到達時の全量返済予約を独立確認する。

        引数: line/index(int)、at/bid/ask(float)は全fill後の正常原行。
        返り値: None。理由は問わず既受理の返済も認め、次原行の要求で当行不足を補わない。
        """
        for mode in ("P1", "T1"):
            counts = self.protection[mode]
            for identity, state in self.active[mode].items():
                if state["remaining"] <= 0:
                    continue
                saved = self.saved[mode].get(identity, {})
                if not finite(saved.get("d")) or saved["d"] <= 0:
                    raise ValueError("P1/T1の保存追尾幅Dが有限正値ではありません")
                mark = Decimal(str(bid if state["side"] > 0 else ask))
                gain = Decimal(state["side"]) * (mark-state["entry"])
                flagged = state["residual_first"] is not None
                floor = max(Decimal(20), state["best_gain"]-Decimal(str(saved["d"])))
                floor_hit, hard_hit = flagged and gain <= floor, gain <= -125
                counts["正常保有原行"] += 1
                counts["正益後保有原行"] += flagged
                counts["利益床到達原行"] += floor_hit
                counts["125pt到達原行"] += hard_hit
                if not floor_hit and not hard_hit:
                    continue
                counts["返済義務原行"] += 1
                shortage = max(0, state["remaining"]-self.reserved[mode][identity])
                counts["予約不足原行"] += shortage > 0
                counts["予約不足数量"] += shortage
                self.audit.check("利益床又は125pt到達の当原行全量予約", shortage, 0, 候補=mode, 実玉=identity,
                    原行=line, Index=index, 時計=at, 方向幅=float(gain), 利益床=float(floor), 残量=state["remaining"], 既予約量=self.reserved[mode][identity])

    def mark(self, line: int, index: int, at: float, bid: float, ask: float) -> None:
        """当行の全約定反映後、正常返済BBOで全玉額を評価する。

        引数: line/index(int)、at/bid/ask(float)は独立採用した正常原行。
        返り値: None。原板軌跡を保存せず、初回正益・最高・最後だけを保持する。
        """
        for mode in MODES:
            finished = []
            for identity, state in self.active[mode].items():
                mark = Decimal(str(bid if state["side"] > 0 else ask))
                unit = Decimal(state["side"]) * (mark-state["entry"]) * 10 - 122
                net = state["realized"] + state["remaining"] * unit
                if state["first"] is None and net > 0:
                    state["first"] = {"原行": line, "時計": at, "全玉純額円": float(net)}
                if state["peak"] is None or net > state["peak"]:
                    state["peak"] = net
                state["last"], state["last_line"], state["last_time"] = net, line, at
                if state["remaining"] == 0:
                    finished.append(identity)
            for identity in finished:
                del self.active[mode][identity]

    def result(self) -> dict:
        """全玉の小型診断を作り、保存された残量・完結純額と結合する。

        引数: なし。
        返り値: dictは三案ごとの一玉一行診断。最後評価は最終正常原行で、未解消を確定益へしない。
        """
        output = {}
        for mode in MODES:
            rows = []
            if self.has_saved[mode]:
                self.audit.check("全玉診断の所有集合", sorted(self.all[mode]), sorted(self.saved[mode]), 候補=mode)
            for identity, state in sorted(self.all[mode].items(), key=lambda item: (item[1]["entry_time"], item[0])):
                saved = self.saved[mode].get(identity, {})
                if saved:
                    self.audit.check("全玉の残量・完結額", (saved["quantity"], saved["initial_quantity"], saved["closed_quantity"], saved["net_pnl"]),
                        (state["remaining"], state["initial"], state["closed"], float(state["realized"])), 候補=mode, 実玉=identity)
                    first = state["residual_first"]
                    self.audit.check("残玉初回正益の独立復元", bool(saved.get("flag")), first is not None, 候補=mode, 実玉=identity)
                    self.audit.check("残玉旗の初回Indexと時計", (saved.get("flag_index", 0), saved.get("flag_time")),
                        (first["Index"], first["時計"]) if first is not None else (0, None), 候補=mode, 実玉=identity)
                    for key, label in (("flag_mark", "返済側価格"), ("flag_net_per_unit", "残玉単価純額円")):
                        if key in saved:
                            self.audit.check("残玉初回正益の"+label, saved[key], first[label] if first is not None else None, 候補=mode, 実玉=identity)
                rows.append({"実玉ID": identity, "参照ID": saved.get("reference_id"), "方向": state["side"], "初回数量": state["initial"],
                    "新規原行": state["entry_line"], "新規時計": state["entry_time"], "残量": state["remaining"],
                    "完結部分純額円": float(state["realized"]), "全玉初回正益": state["first"],
                    "最高全玉純額円": float(state["peak"]) if state["peak"] is not None else None,
                    "最後全玉純額円": float(state["last"]) if state["last"] is not None else None,
                    "最後評価原行": state["last_line"], "最後評価時計": state["last_time"],
                    "保存残玉旗": saved.get("flag"), "残玉初回正益": state["residual_first"],
                    "保存残玉旗原行": state["residual_first"]["原行"] if state["residual_first"] is not None else None,
                    "全玉正益後に最後赤字": state["first"] is not None and state["last"] is not None and state["last"] < 0})
            output[mode] = rows
        return output


# ----------------------------------------


def inspect_session(path: Path, session: str, result: dict, audit: Audit, whole_position: bool = False) -> dict:
    """一場の原板を一回parseし、三案の最初の約定可能原行を求める。

    引数: path(Path)はNK原板gzip、session(str)、result(dict)、audit(Audit)、whole_position(bool)は全玉診断の追加。
    返り値: dictは原板品質と三案の小型照合数。原板軌跡を返さない。
    """
    audit.check("結果の場", result["session"], session)
    audit.check("三案集合", sorted(result["books"]), sorted(MODES))
    requests, needed, expected_trades, summaries = [], {}, {}, {}
    all_keys = set()
    whole = WholePosition(result["books"], audit) if whole_position else None
    for mode in MODES:
        book = result["books"][mode]
        delay = book["fill_delay_seconds"]
        if not finite(delay) or delay < 0:
            raise ValueError("約定遅延が有限非負ではありません")
        audit.check("Bookの場と候補", (book["session"], book["mode"]), (session, mode))
        expected_trades[mode] = Counter()
        counts = Counter()
        for order in book["orders"]:
            identity = order_key(mode, order)
            if identity in all_keys:
                raise ValueError("注文ID重複")
            all_keys.add(identity)
            for name in ("quantity", "remaining", "filled_quantity", "cancelled_quantity", "request_line", "request_index", "fill_line"):
                if type(order[name]) is not int:
                    raise ValueError("注文の整数列が不正:" + name)
            quantity, remaining, filled, cancelled = (order[k] for k in ("quantity", "remaining", "filled_quantity", "cancelled_quantity"))
            context = {"候補": mode, "注文": order["id"]}
            audit.check("注文数量保存則", (quantity > 0, min(remaining, filled, cancelled) >= 0, remaining + filled + cancelled), (True, True, quantity), **context)
            if order["kind"] not in ("entry", "exit") or order["side"] not in (-1, 1) or not finite(order["request_time"]):
                raise ValueError("注文の種別・方向・時計が不正")
            status = order["status"]
            if status not in ("filled", "pending", "cancelled"):
                raise ValueError("未知の注文状態:" + status)
            counts[status] += 1
            request = {"key": identity, "order": order, "delay": float(delay)}
            if order["request_line"] > 0:
                needed.setdefault(order["request_line"], []).append(request)
            else:
                audit.check("先頭前要求の出典", (order["request_line"], order["request_index"]), (0, -1), **context)
            if status == "filled":
                audit.check("約定状態数量", (remaining, filled > 0), (0, True), **context)
                if not finite(order["fill_time"]) or not finite(order["fill_price"]):
                    raise ValueError("約定注文に有限の約定時計・価格がありません")
                typ = ("Long" if order["side"] > 0 else "Short") + ("N" if order["kind"] == "entry" else "R")
                key = (order["position_id"], order["fill_line"], stamp(order["fill_time"]), order["fill_price"], typ, filled)
                expected_trades[mode][key] += 1
                requests.append(request)
            else:
                audit.check("未約定の約定欄", (filled, order["fill_time"], order["fill_price"], order["fill_line"]), (0, None, None, 0), **context)
                audit.check("未約定の残数量", remaining > 0 if status == "pending" else (remaining == 0 and cancelled == quantity), True, **context)
                if status == "pending":
                    requests.append(request)
        trade_counter = Counter()
        for trade in book["trades"]:
            trade_counter[(trade["position_id"], trade["source_line"], trade["timestamp"], trade["price"], trade["type"], trade["qty"])] += 1
            audit.check("約定片の費用と候補", (trade["fee_yen"], trade["method_id"]), (61 * trade["qty"], mode), 候補=mode, 約定=trade["id"])
        audit.check("注文と約定片の数量価格原行", trade_counter, expected_trades[mode], 候補=mode)
        summaries[mode] = {"注文": len(book["orders"]), "約定注文": counts["filled"], "最終未約定": counts["pending"], "取消注文": counts["cancelled"], "約定片": len(book["trades"]), "遅延秒": delay}

    # ----------------------------------------
    # 原行と価格時計は別の順序制約なので、原行で有効化して時計heapへ載せる。
    requests.sort(key=lambda r: (r["order"]["request_line"], r["key"]))
    cursor, heap, answers = 0, [], {}
    start, end = bounds(session)
    previous, adopted_index = start, -1
    quality = {k: 0 for k in ("lines", "clock_missing", "outside", "backward", "bad_last", "bad_quote", "accepted")}
    contracts = set()
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        for line, text in enumerate(stream, 1):
            quality["lines"] += 1
            row = json.loads(text, parse_constant=bad_constant)
            if "Symbol" not in row or row["Symbol"] is not None and not isinstance(row["Symbol"], str):
                raise ValueError("原板のSymbol列が不正")
            contracts.add(row["Symbol"] or "")
            at = clock(row.get("CurrentPriceTime"))
            if at is None:
                quality["clock_missing"] += 1
                continue
            if not start <= at < end:
                quality["outside"] += 1
                continue
            if at < previous:
                quality["backward"] += 1
                continue
            previous = at
            adopted_index += 1
            quality["accepted"] += 1
            last = go_number(row.get("CurrentPrice"))
            levels = {}
            for side in ("Buy", "Sell"):
                for level in range(1, 11):
                    key = side + str(level)
                    if key not in row or row[key] is not None and not isinstance(row[key], dict):
                        raise ValueError("原板の段列が不正:" + key)
                    value = row[key] or {}
                    price, _ = go_number(value.get("Price")), go_number(value.get("Qty"))
                    if level == 1:
                        levels[side] = price
            bid, ask = levels["Buy"], levels["Sell"]
            quality["bad_last"] += int(last <= 0)
            quality["bad_quote"] += int(bid <= 0 or ask <= bid)
            for query in needed.pop(line, []):
                order = query["order"]
                audit.check("要求元原行と独立Index", (order["request_index"], at <= order["request_time"]), (adopted_index, True), 候補=query["key"][0], 注文=order["id"])
            while cursor < len(requests) and requests[cursor]["order"]["request_line"] < line:
                query = requests[cursor]
                heapq.heappush(heap, (query["order"]["request_time"] + query["delay"], cursor, query))
                cursor += 1
            if last <= 0 or not 0 < bid < ask:
                continue
            if whole is not None:
                whole.advance_reservations(line, at)
                whole.observe_residual(line, adopted_index, at, bid, ask)
            deferred = []
            while heap and heap[0][0] <= at:
                item = heapq.heappop(heap)
                query, order = item[2], item[2]["order"]
                if adopted_index <= order["request_index"]:
                    deferred.append(item)
                    continue
                price = ask if (order["kind"] == "entry") == (order["side"] > 0) else bid
                answers[query["key"]] = (line, at, price)
                if whole is not None and order["status"] == "filled" and (order["fill_line"], order["fill_time"], order["fill_price"]) == (line, at, price):
                    whole.fill(query["key"][0], order, line, at, price)
            for item in deferred:
                heapq.heappush(heap, item)
            if whole is not None:
                whole.observe_residual(line, adopted_index, at, bid, ask)
                whole.inspect_protection(line, adopted_index, at, bid, ask)
                whole.mark(line, adopted_index, at, bid, ask)
    quality["contracts"] = sorted(contracts)
    for line, missing in needed.items():
        for query in missing:
            audit.check("要求原行の時計採用", False, True, 候補=query["key"][0], 注文=query["key"][1], 原行=line)
    for query in requests:
        order = query["order"]
        answer = answers.get(query["key"])
        if order["status"] == "filled":
            audit.check("最初の正常後原行・時計・価格", (order["fill_line"], order["fill_time"], order["fill_price"]), answer, 候補=query["key"][0], 注文=order["id"])
        else:
            audit.check("最終未約定に約定可能後原行なし", answer, None, 候補=query["key"][0], 注文=order["id"])
    if "quality" in result:
        audit.check("独立原板採用品質", result["quality"]["NK225"], quality)
    summary = {"場": session, "原板品質": quality, "候補": summaries, "JSON本文走査回数": 1}
    if whole is not None:
        summary["全玉費用後評価"] = whole.result()
        summary["利益床の独立規範"] = whole.protection
    return summary


def run(manifest_path: Path, result_dir: Path, sessions: list[str], whole_position: bool = False) -> dict:
    """許可された対象場だけを入力指紋と最初の正常原行へ照合する。

    引数: manifest_path(Path)、result_dir(Path)、sessions(list[str])は明示対象、whole_position(bool)は全玉診断。
    返り値: dictは指紋・対象場・差分の小型正本。元入力と結果は変更しない。
    """
    manifest = read_json(manifest_path)
    entries = {row["id"]: row for row in manifest["sessions"]}
    if not sessions or len(set(sessions)) != len(sessions) or not set(sessions) <= set(entries):
        raise ValueError("対象場は台帳内の重複しない明示集合が必要です")
    audit, details, pins = Audit(), [], {str(manifest_path): sha(manifest_path)}
    for session in sessions:
        entry = entries[session]
        paths = {key: verify_file(Path(manifest["source_root"]), info) for key, info in entry["files"].items()}
        result_path = result_dir / (session + ".json")
        before = sha(result_path)
        saved = read_json(result_path)
        detail = inspect_session(paths["NK225_book"], session, saved, audit, whole_position)
        audit.check("NK限月", detail["原板品質"]["contracts"], [entry["contract"]], 場=session)
        audit.check("結果読取前後不変", sha(result_path), before, 場=session)
        detail["結果SHA256"] = before
        detail["入力照合ファイル数"] = len(paths)
        details.append(detail)
        pins[str(result_path)] = before
    return {"成功": audit.errors == 0, "照合項目数": audit.checks, "不一致数": audit.errors, "不一致": audit.details,
        "対象場": details, "正本SHA256": pins, "監査コードSHA256": sha(Path(__file__)), "新再生": 0,
        "限定": "注文生成理由・取消時刻は対象外。取消は非約定欄と数量だけを確認。原板全行は各場一回parseし、同値行を省略しない。",
        "全玉評価定義": "原板一致済み約定を当行先に反映し、完結部分純額+残量×(方向価格差×10−122)を正常BBOで評価。最後評価時計を明記し、未解消評価を確定利益へしない。" if whole_position else None}


# ----------------------------------------


def fixture(path: Path) -> tuple[str, dict]:
    """人工のgzip原板と、手で固定した期待約定列を作る。

    引数: path(Path)は一時gzipの保存先。
    返り値: tuple[str,dict]は人工場IDと三案保存結果。
    """
    session = "2026-09-21_Day"
    start, end = bounds(session)
    rows = []
    for at, last, bid, ask in [(start-1,105,100,110),(None,105,100,110),(start,0,100,110),
        (start,105,110,100),(start,105,100,110),(start,105,100,110),(start+.5,106,101,111),
        (start+.4,106,101,111),(start+1,107,102,112),(end,105,100,110),("不正",105,100,110),
        (start+2,0,100,110),(start+2,105,110,100)]:
        row = {"Symbol":"人工限月", "CurrentPrice":last}
        if at is not None:
            row["CurrentPriceTime"] = at if isinstance(at,str) else stamp(at)
        for side, price in (("Buy",bid),("Sell",ask)):
            for level in range(1,11):
                row[side+str(level)] = {"Price":price,"Qty":100}
        rows.append(row)
    with gzip.open(path,"wt",encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row,ensure_ascii=False)+"\n")
    result = {"session":session,"books":{}}
    specifications = {"F0":[("entry",1,2,4,1,start,5,start,110),("entry",-1,1,5,2,start,6,start,100),
        ("exit",1,2,6,3,start,7,start+.5,101),("exit",-1,1,7,4,start+.5,9,start+1,112)],
        "P1":[("entry",1,1,4,1,start,9,start+1,112)],"T1":[("entry",1,3,6,3,start,7,start+.5,111)]}
    for mode in MODES:
        book = {"session":session,"mode":mode,"fill_delay_seconds":int(mode=="P1"),"orders":[],"trades":[]}
        for i,(kind,side,n,reqline,reqindex,request,fillline,at,price) in enumerate(specifications[mode],1):
            position = i-2 if mode=="F0" and kind=="exit" else i
            order = {"id":mode+str(i),"kind":kind,"side":side,"position_id":"位置"+str(position),"quantity":n,"remaining":0,
                "filled_quantity":n,"cancelled_quantity":0,"request_time":request,"request_line":reqline,"request_index":reqindex,
                "fill_line":fillline,"fill_time":at,"fill_price":price,"status":"filled"}
            if mode=="T1":
                order["quantity"],order["cancelled_quantity"] = 5,2
            book["orders"].append(order)
            book["trades"].append({"id":mode+"約定"+str(i),"position_id":order["position_id"],"source_line":fillline,
                "timestamp":stamp(at),"price":price,"type":("Long" if side>0 else "Short")+("N" if kind=="entry" else "R"),"qty":n,"fee_yen":61*n,"method_id":mode})
        result["books"][mode]=book
    for status,line,index,at in (("pending",13,7,start+2),("cancelled",3,0,start)):
        result["books"]["F0"]["orders"].append({"id":status,"kind":"entry","side":1,"position_id":status,"quantity":2,
            "remaining":2 if status=="pending" else 0,"filled_quantity":0,"cancelled_quantity":2 if status=="cancelled" else 0,
            "request_time":at,"request_line":line,"request_index":index,"fill_line":0,"fill_time":None,"fill_price":None,"status":status})
    result["quality"]={"NK225":{"lines":13,"clock_missing":2,"outside":2,"backward":1,"bad_last":2,"bad_quote":2,"accepted":8,"contracts":["人工限月"]}}
    return session,result


def whole_fixture(path: Path, side: int, final_first: bool = False) -> tuple[str, dict]:
    """部分赤字後の残玉正益と全玉正益を分ける人工経路を作る。

    引数: path(Path)は一時gzip、side(int)は買い1又は売り-1、final_first(bool)は全返済直前だけで初回正益。
    返り値: tuple[str,dict]は人工場と保存会計。売りは同じ経路を価格反射する。
    """
    session = "2026-09-21_Day"
    start = bounds(session)[0]
    rows = []
    for i, (bid, ask) in enumerate(((90,100),(50,60),(120,130),(400,410),(350,360))):
        if final_first and i in (2, 3):
            bid, ask = 90, 100
        if side < 0:
            bid, ask = 1000-ask, 1000-bid
        row = {"Symbol":"人工限月", "CurrentPrice":(bid+ask)/2, "CurrentPriceTime":stamp(start+i)}
        for name, price in (("Buy",bid),("Sell",ask)):
            for level in range(1,11):
                row[name+str(level)] = {"Price":price,"Qty":100}
        rows.append(row)
    with gzip.open(path,"wt",encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row,ensure_ascii=False)+"\n")
    result = {"session":session,"books":{mode:{"session":session,"mode":mode,"fill_delay_seconds":0,"orders":[],"trades":[],"lots":[]} for mode in MODES}}
    book=result["books"]["F0"]
    for i,(kind,n,requestline,requestindex,request,fillline,fill,price) in enumerate((("entry",10,0,-1,start,1,start,100),
        ("exit",8,1,0,start,2,start+1,50),("exit",2,4,3,start+3,5,start+4,350)),1):
        if side < 0:
            price=1000-price
        order={"id":"全玉注文"+str(i),"kind":kind,"side":side,"position_id":"全玉","quantity":n,"remaining":0,"filled_quantity":n,
            "cancelled_quantity":0,"request_time":request,"request_line":requestline,"request_index":requestindex,
            "fill_line":fillline,"fill_time":fill,"fill_price":price,"status":"filled"}
        book["orders"].append(order)
        book["trades"].append({"id":"全玉約定"+str(i),"position_id":"全玉","source_line":fillline,"timestamp":stamp(fill),"price":price,
            "type":("Long" if side>0 else "Short")+("N" if kind=="entry" else "R"),"qty":n,"fee_yen":61*n,"method_id":"F0"})
    book["lots"]=[{"id":"全玉","reference_id":"参照全玉","quantity":0,"initial_quantity":10,"closed_quantity":10,"net_pnl":-220,
        "flag":True,"flag_time":start+(4 if final_first else 2),"flag_index":4 if final_first else 2}]
    return session,result


def protection_fixture(path: Path, side: int, case: str) -> tuple[str, dict]:
    """利益床・追尾等号・125pt・正益0等号を分けた人工原板を作る。

    引数: path(Path)は一時gzip、side(int)は買売符号、case(str)は人工経路の識別子。
    返り値: tuple[str,dict]はP1/T1に同じ規範を適用する人工会計。
    """
    session = "2000-01-01_Day"
    start = bounds(session)[0]
    quotes = {"floor": [(990,1000),(1015,1025),(980,990),(1020,1010),(980,990)],
        "trailing": [(990,1000),(1150,1160),(1025,1035)],
        "hard": [(990,1000),(875,885)], "zero": [(990,1000),(1012.2,1022.2)],
        "pending": [(990,1000),(1015,1025)]}[case]
    rows=[]
    for i,(bid,ask) in enumerate(quotes):
        if side < 0:
            bid,ask=2000-ask,2000-bid
        row={"Symbol":"人工限月","CurrentPrice":0 if case=="floor" and i==2 else (bid+ask)/2,
            "CurrentPriceTime":stamp(start+i)}
        for name,price in (("Buy",bid),("Sell",ask)):
            for level in range(1,11):
                row[name+str(level)]={"Price":price,"Qty":100}
        rows.append(row)
    with gzip.open(path,"wt",encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row,ensure_ascii=False)+"\n")
    result={"session":session,"books":{m:{"session":session,"mode":m,"fill_delay_seconds":0,"orders":[],"trades":[],"lots":[]} for m in MODES}}
    specs=[("entry",3,0,-1,0,1,0,1000)]
    if case=="floor": specs.append(("exit",3,2,1,1,5,4,980))
    elif case=="trailing": specs.extend((("exit",1,2,1,1,3,2,1025),("exit",2,3,2,2,0,None,None)))
    elif case in ("hard","pending"): specs.append(("exit",3,2,1,1,0,None,None))
    for mode in ("P1","T1"):
        book=result["books"][mode]
        for serial,(kind,n,reqline,reqindex,reqoffset,fillline,filloffset,price) in enumerate(specs,1):
            actual_price=(2000-price if side<0 else price) if price is not None else None
            filled=n if fillline else 0
            order={"id":mode+str(serial),"kind":kind,"side":side,"position_id":"規範玉","quantity":n,
                "remaining":n-filled,"filled_quantity":filled,"cancelled_quantity":0,"request_time":start+reqoffset,
                "request_line":reqline,"request_index":reqindex,"fill_line":fillline,
                "fill_time":start+filloffset if filloffset is not None else None,"fill_price":actual_price,"status":"filled" if fillline else "pending"}
            book["orders"].append(order)
            if filled:
                book["trades"].append({"id":mode+"約定"+str(serial),"position_id":"規範玉","source_line":fillline,
                    "timestamp":stamp(start+filloffset),"price":actual_price,"type":("Long" if side>0 else "Short")+("N" if kind=="entry" else "R"),
                    "qty":filled,"fee_yen":61*filled,"method_id":mode})
        closed=3 if case=="floor" else 1 if case=="trailing" else 0
        net=-966 if case=="floor" else 128 if case=="trailing" else 0
        flagged=case in ("floor","trailing","pending")
        book["lots"]=[{"id":"規範玉","reference_id":"規範参照","quantity":3-closed,"initial_quantity":3,"closed_quantity":closed,
            "net_pnl":net,"flag":flagged,"flag_time":start+1 if flagged else None,"flag_index":1 if flagged else 0,"d":125}]
    return session,result


def self_test() -> dict:
    """人工gzipだけで正常後行・境界・不正・数量・拒否を検査する。

    引数: なし。
    返り値: dictは成功と人工検査数。実市場ファイルの読取は0。
    """
    tests = 0
    with tempfile.TemporaryDirectory(prefix="far80_raw_") as temporary:
        path=Path(temporary)/"人工.jsonl.gz"
        session,result=fixture(path)
        audit=Audit()
        detail=inspect_session(path,session,result,audit)
        assert audit.errors==0,audit.details
        assert detail["原板品質"]["accepted"]==8
        tests+=1
        for kind in ("first","price","quantity","time","request_index","pending","trade"):
            broken=deepcopy(result)
            o=broken["books"]["F0"]["orders"][0]
            if kind=="first": o["fill_line"]=6
            elif kind=="price": o["fill_price"]=999
            elif kind=="quantity": o["filled_quantity"]+=1
            elif kind=="time": o["fill_time"]+=.5
            elif kind=="request_index": o["request_index"]=999
            elif kind=="pending":
                o=broken["books"]["F0"]["orders"][-2]
                o.update(request_line=5,request_index=2,request_time=bounds(session)[0])
            else: broken["books"]["F0"]["trades"][0]["qty"]+=1
            bad=Audit()
            inspect_session(path,session,broken,bad)
            assert bad.errors>0,kind
            tests+=1
        pin={"path":path.name,"size":path.stat().st_size,"sha256":sha(path)}
        assert verify_file(path.parent,pin)==path
        try:
            verify_file(path.parent,{**pin,"sha256":"0"*64})
        except ValueError:
            tests+=1
        else:
            raise AssertionError("入力指紋差を受理")
        assert clock("2026-09-21T08:45:00.123456789+09:00")==float(int(bounds(session)[0])*1_000_000_000+123456789)/1_000_000_000
        assert bounds("2026-09-21_Night")[1]-bounds("2026-09-21_Night")[0]==13*3600
        tests+=1
        for side in (1,-1):
            session,whole=whole_fixture(path,side)
            check=Audit()
            detail=inspect_session(path,session,whole,check,True)
            assert check.errors==0,check.details
            position=detail["全玉費用後評価"]["F0"][0]
            assert position["保存残玉旗原行"]==3
            assert position["全玉初回正益"]["原行"]==4
            assert position["最高全玉純額円"]==780
            assert position["最後全玉純額円"]==-220
            assert position["全玉正益後に最後赤字"] is True
            assert position["完結部分純額円"]==-220 and position["残量"]==0
            tests+=1
            for kind in ("late", "early", "missing"):
                broken=deepcopy(whole)
                saved=broken["books"]["F0"]["lots"][0]
                if kind=="late": saved.update(flag_index=3,flag_time=bounds(session)[0]+3)
                elif kind=="early": saved.update(flag_index=1,flag_time=bounds(session)[0]+1)
                else: saved.update(flag=False,flag_index=0,flag_time=None)
                bad=Audit()
                inspect_session(path,session,broken,bad,True)
                assert bad.errors>0,kind
                tests+=1
            session,last_only=whole_fixture(path,side,True)
            check=Audit()
            detail=inspect_session(path,session,last_only,check,True)
            assert check.errors==0,check.details
            position=detail["全玉費用後評価"]["F0"][0]
            assert position["残玉初回正益"]["原行"]==5
            assert position["保存残玉旗原行"]==5 and position["全玉初回正益"] is None
            assert position["最後全玉純額円"]==-220 and position["残量"]==0
            tests+=1
        session,whole=whole_fixture(path,-1)
        broken=deepcopy(whole)
        broken["books"]["F0"]["lots"][0]["net_pnl"]+=1
        check=Audit()
        inspect_session(path,session,broken,check,True)
        assert check.errors>0
        json.dumps(check.details,ensure_ascii=False,allow_nan=False)
        tests+=1
        for side in (1,-1):
            for case in ("floor","trailing","hard","zero","pending"):
                session,value=protection_fixture(path,side,case)
                check=Audit()
                detail=inspect_session(path,session,value,check,True)
                assert check.errors==0,(case,side,check.details)
                for mode in ("P1","T1"):
                    counts=detail["利益床の独立規範"][mode]
                    assert counts["予約不足原行"]==counts["予約不足数量"]==0
                    assert counts["返済義務原行"]==int(case!="zero")
                    assert counts["125pt到達原行"]==int(case=="hard")
                tests+=1
                if case=="zero":
                    continue
                broken=deepcopy(value)
                for mode in ("P1","T1"):
                    orders=broken["books"][mode]["orders"]
                    if case=="floor":
                        orders[-1].update(request_line=3,request_index=2,request_time=bounds(session)[0]+2)
                    elif case=="trailing":
                        orders[-1]["quantity"]-=1
                        orders[-1]["remaining"]-=1
                    else:
                        orders[-1]["request_time"]+=.5
                bad=Audit()
                inspect_session(path,session,broken,bad,True)
                assert any(r["検査"]=="利益床又は125pt到達の当原行全量予約" for r in bad.details),(case,side,bad.details)
                tests+=1
    return {"成功":True,"人工テスト数":tests,"不一致数":0,"実市場読取":0,"新再生":0}


def main() -> None:
    """人工又は対象明示の読取監査を選び、小型JSONだけを保存する。

    引数: CLIの--run/--whole-position(bool)、--manifest/--results/--output(Path)、--session(list[str])。
    返り値: None。既存出力を上書きせず、不一致は終了コード1。
    """
    parser=argparse.ArgumentParser(description="80の独立原板約定照合")
    parser.add_argument("--run",action="store_true")
    parser.add_argument("--self-test",action="store_true")
    parser.add_argument("--manifest",type=Path)
    parser.add_argument("--results",type=Path)
    parser.add_argument("--output",type=Path)
    parser.add_argument("--session",action="append",default=[])
    parser.add_argument("--whole-position",action="store_true")
    args=parser.parse_args()
    if args.run and args.self_test:
        parser.error("人工と本物は同時指定できません")
    if args.run:
        if not args.manifest or not args.results or not args.output or not args.session:
            parser.error("本物はmanifest/results/outputと対象sessionが必要です")
        if args.output.exists():
            raise FileExistsError("監査正本は上書きしません")
        report=run(args.manifest,args.results,args.session,args.whole_position)
        with args.output.open("x",encoding="utf-8",newline="\n") as stream:
            json.dump(report,stream,ensure_ascii=False,indent=2,allow_nan=False)
            stream.write("\n")
        print(json.dumps({k:report[k] for k in ("成功","照合項目数","不一致数","新再生")},ensure_ascii=False))
        print("保存先:"+str(args.output))
        if not report["成功"]:
            raise SystemExit(1)
    else:
        print(json.dumps(self_test(),ensure_ascii=False))


if __name__=="__main__":
    main()
