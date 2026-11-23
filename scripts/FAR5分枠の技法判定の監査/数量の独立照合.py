"""原板の最良気配量だけからOFI30平均とE08四量平均を独立再構成する。"""

import argparse
from bisect import bisect_left
from collections import Counter, deque
from datetime import datetime, timedelta, timezone
import gzip
import hashlib
import json
import math
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
AREA = Path(__file__).parent
DECODER = json.JSONDecoder()
VOLUME_FIELDS = ("bid_refill", "ask_deplete", "ask_refill", "bid_deplete")
BAND_FIELDS = ("known", "quantity_known", "start_index", "index", "start_line", "line", "start_time", "time", "elapsed", "events", "quantity_events", "bad_quantity", *VOLUME_FIELDS)
SOURCE_FIELDS = ("reference", "time", "received", "source_index", "source_line", "last", "bid", "ask")
ABS_TOL, REL_TOL = 1e-12, 1e-10


def need(ok: bool, reason: str) -> None:
    """
    機能: 不明な量を既知0へ補正せず不整合を停止する。
    引数: ok(bool)、reason(str)は条件と説明。
    返り値: None。不成立はValueError。
    """
    if not ok:
        raise ValueError(reason)


def sha(path: Path) -> str:
    """
    機能: 明示入力の内容指紋を取得する。
    引数: path(Path)は許可済みファイル。
    返り値: strはSHA256。
    """
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def space(text: str, pos: int) -> int:
    """
    機能: JSON字句の空白だけを進める。
    引数: text(str)、pos(int)は本文と開始。
    返り値: intは非空白位置。
    """
    while pos < len(text) and text[pos].isspace():
        pos += 1
    return pos


def skip(text: str, pos: int) -> int:
    """
    機能: 禁止領域を辞書/数値へ展開せず、括弧と引用だけで読み飛ばす。
    引数: text(str)、pos(int)はJSON値の開始。
    返り値: intは値終端。字句射影は固定92の方式を限定再実装したもの。
    """
    pos = space(text, pos)
    need(pos < len(text), "JSON終端")
    if text[pos] == '"':
        pos += 1
        while pos < len(text):
            if text[pos] == "\\":
                pos += 2
            elif text[pos] == '"':
                return pos+1
            else:
                pos += 1
        raise ValueError("文字列終端")
    if text[pos] not in "[{":
        while pos < len(text) and text[pos] not in ",}]\r\n":
            pos += 1
        return pos
    stack = [text[pos]]
    pos += 1
    while stack:
        need(pos < len(text), "JSON括弧終端")
        if text[pos] == '"':
            pos = skip(text, pos)
            continue
        if text[pos] in "[{":
            stack.append(text[pos])
        elif text[pos] in "]}":
            need(stack.pop() == {"]": "[", "}": "{"}[text[pos]], "JSON括弧")
        pos += 1
    return pos


def fields(text: str, pos: int) -> dict:
    """
    機能: object名だけを展開し、各値の字句区間を得る。
    引数: text(str)、pos(int)はobject位置。
    返り値: dict[str,tuple]は値区間。Actors/PnLの値は未展開。
    """
    pos = space(text, pos)
    need(text[pos] == "{", "object開始")
    result = {}
    pos = space(text, pos+1)
    while text[pos] != "}":
        key, pos = DECODER.raw_decode(text, pos)
        need(type(key) is str and key not in result, "object名/重複")
        pos = space(text, pos)
        need(text[pos] == ":", "object区切り")
        begin = space(text, pos+1)
        pos = skip(text, begin)
        result[key] = (begin, pos)
        pos = space(text, pos)
        if text[pos] == "}":
            break
        need(text[pos] == ",", "object値区切り")
        pos = space(text, pos+1)
    return result


def members(text: str, pos: int) -> list:
    """
    機能: 配列要素を値へ変換せず区間へ分ける。
    引数: text(str)、pos(int)は配列位置。
    返り値: list[int]は要素開始位置。
    """
    need(text[pos] == "[", "配列開始")
    result = []
    pos = space(text, pos+1)
    while text[pos] != "]":
        result.append(pos)
        pos = space(text, skip(text, pos))
        if text[pos] == "]":
            break
        need(text[pos] == ",", "配列値区切り")
        pos = space(text, pos+1)
    return result


def selected(text: str, spans: dict, names: tuple) -> dict:
    """
    機能: 許可した量/出典fieldだけをJSON値へ変換する。
    引数: text(str)、spans(dict)、names(tuple)は本文・区間・許可名。
    返り値: dictは許可射影。非有限は拒否。
    """
    def bad(value: str):
        """
        機能: 非有限定数を拒否。
        引数: value(str)。
        返り値: None、常に例外。
        """
        raise ValueError(value)
    need(all(n in spans for n in names), "許可field欠落")
    return {n: json.loads(text[slice(*spans[n])], parse_constant=bad) for n in names}


def project(path: Path) -> list:
    """
    機能: Nativeのchart_grids.Current内の量/出典だけを字句射影する。
    引数: path(Path)は明示された2場のNative JSON又はgzip。
    返り値: list[dict]は枠ID/時計/Current量。Actor/約定/損益はJSON展開0。
    """
    body = gzip.decompress(path.read_bytes()) if path.suffix == ".gz" else path.read_bytes()
    text = body.decode("utf-8-sig")
    top = fields(text, 0)
    need("chart_grids" in top, "chart_grids欠落")
    rows = []
    for start in members(text, top["chart_grids"][0]):
        f = fields(text, start)
        row = selected(text, f, ("snapshot_id", "at"))
        c = fields(text, f["current"][0])
        current = selected(text, c, SOURCE_FIELDS)
        for direction in ("buy", "sell"):
            current[direction] = selected(text, fields(text, c[direction][0]), ("ofi_known", "ofi30", "ofi_reason", "own_at"))
        n = fields(text, c["night"][0])
        current["night"] = selected(text, n, ("available", "known", "invalid", "window", "time", "index"))
        current["night"]["band"] = selected(text, fields(text, n["band"][0]), BAND_FIELDS)
        row["current"] = current
        rows.append(row)
    return rows


def finite(value) -> bool:
    """
    機能: 真偽を数値へ暗黙変換せず有限値だけを認める。
    引数: value(any)は入力値。
    返り値: boolは有限int/float。
    """
    return type(value) in (int, float) and math.isfinite(value)


def book_valid(q: dict) -> bool:
    """
    機能: 元式の正常BBOだけを判定する。
    引数: q(dict)は取込最良板。
    返り値: bool。数量不明は価格の正常性と別にする。
    """
    return finite(q["bid"]) and finite(q["ask"]) and q["bid"] > 0 and q["ask"] > q["bid"]


def qty_valid(q: dict) -> bool:
    """
    機能: 元式どおり両側の最良量が有限strict正か判定する。
    引数: q(dict)は取込板。
    返り値: bool。0/欠測相当を既知の支持量へしない。
    """
    return all(finite(q[n]) and q[n] > 0 for n in ("bq", "aq"))


class OFI30:
    """元pair順・累積浮動小数順とstrict30秒過去端を持つ独立器。"""

    def __init__(self):
        """
        機能: 当場の履歴を初期化。
        引数: なし。
        返り値: None。
        """
        self.rows, self.previous = deque(), None
        self.bad = self.count = 0
        self.total = 0.0

    def add(self, q: dict) -> dict:
        """
        機能: Native Last>0行一つの正規化OFIを追加し、その行時点のOFI30を返す。
        引数: q(dict)はtime/bid/ask/bq/aqを持つ板。
        返り値: dictはknown/value/reason/own_at。grid時刻へ再計算しない。
        """
        valid, p, pair = book_valid(q), self.previous, False
        if not valid or p is not None and q["time"]-p["time"] > 15:
            self.bad += 1
        if valid and qty_valid(q) and p is not None and book_valid(p) and qty_valid(p) and q["time"]-p["time"] <= 15:
            x = 0.0
            if q["bid"] >= p["bid"]: x += q["bq"]
            if q["bid"] <= p["bid"]: x -= p["bq"]
            if q["ask"] <= p["ask"]: x -= q["aq"]
            if q["ask"] >= p["ask"]: x += p["aq"]
            den = q["bq"]+p["bq"]+q["aq"]+p["aq"]
            v = x/den
            if math.isfinite(x) and math.isfinite(den) and math.isfinite(v) and math.isfinite(self.total+v):
                self.total += v
                self.count += 1
                pair = True
        row = {"time": q["time"], "bad": self.bad, "sum": self.total, "count": self.count}
        self.rows.append(row)
        while self.rows and self.rows[0]["time"] < q["time"]-340:
            self.rows.popleft()
        self.previous = dict(q)
        out = {"known": False, "value": 0.0, "reason": "OFI履歴不足", "own_at": q["time"]}
        if not valid:
            return out
        anchor = next((r for r in reversed(self.rows) if r["time"] < q["time"]-30), None)
        if not pair:
            out["reason"] = "現在OFI差分不成立"
        elif anchor is None:
            out["reason"] = "OFI30秒履歴不足"
        elif row["bad"] != anchor["bad"]:
            out["reason"] = "OFI窓内異常又は空白"
        elif row["count"]-anchor["count"] < 2:
            out["reason"] = "OFI差分2件未満"
        else:
            v = (row["sum"]-anchor["sum"])/(row["count"]-anchor["count"])
            if math.isfinite(v):
                out.update(known=True, value=v, reason="")
            else:
                out["reason"] = "OFI非有限"
        return out


def empty_band() -> dict:
    """
    機能: 元Goの未知bandを既知false/量0の保存表現へ正確に写す。
    引数: なし。
    返り値: dict。0は既知の支持ではなく、必ずknown/quantity_knownと共に扱う。
    """
    return {n: False if n in ("known", "quantity_known") else 0 for n in BAND_FIELDS}


class E08:
    """累積4比と価格遷移点だけを持つ独立器。10段commonDepth/holdは実装しない。"""

    def __init__(self, legacy_clock: bool = False):
        """
        機能: 当場の量履歴を初期化。
        引数: legacy_clock(bool)は旧T15人工用。
        返り値: None。
        """
        self.legacy_clock = legacy_clock
        self.previous = None
        self.latest = None
        self.points = deque(maxlen=9)
        self.clock_rows = deque()

    def add(self, q: dict) -> dict:
        """
        機能: 一原行の同価格量比を更新しE08の平均と源番号を返す。
        引数: q(dict)はindexをNative特徴連番として持つ板。
        返り値: dictはnight対象値。Clock=trueのT15は人工のlegacy区別用。
        """
        invalid = not book_valid(q)
        if invalid or self.previous is not None and (q["time"] < self.previous["time"] or q["time"]-self.previous["time"] > 60):
            self.previous, self.latest = None, None
            self.points.clear()
            self.clock_rows.clear()
        out = {"available": True, "known": False, "invalid": invalid, "window": "T15" if self.legacy_clock else "E08",
               "time": q["time"], "index": q["index"], "band": empty_band()}
        if invalid:
            return out
        p = self.previous
        frame = dict(self.latest) if self.latest is not None else {"events": 0, "quantity_events": 0, "bad_quantity": 0, **{n: 0.0 for n in VOLUME_FIELDS}}
        changed = p is None or q["bid"] != p["bid"] or q["ask"] != p["ask"]
        frame.update(index=q["index"], line=q["index"], time=q["time"])
        if p is not None:
            if changed:
                frame["events"] += 1
            if qty_valid(q) and qty_valid(p):
                if changed or q["bq"] != p["bq"] or q["aq"] != p["aq"]:
                    frame["quantity_events"] += 1
                    if q["bid"] == p["bid"]:
                        d = (q["bq"]-p["bq"])/(q["bq"]+p["bq"])
                        frame["bid_refill"] += max(d, 0)
                        frame["bid_deplete"] += max(-d, 0)
                    if q["ask"] == p["ask"]:
                        d = (q["aq"]-p["aq"])/(q["aq"]+p["aq"])
                        frame["ask_refill"] += max(d, 0)
                        frame["ask_deplete"] += max(-d, 0)
            else:
                frame["bad_quantity"] += 1
        self.latest, self.previous = frame, dict(q)
        if changed:
            self.points.append(dict(frame))
        self.clock_rows.append(dict(frame))
        while self.clock_rows and self.clock_rows[0]["time"] < q["time"]-31:
            self.clock_rows.popleft()
        anchor = None
        if self.legacy_clock:
            anchor = next((x for x in reversed(self.clock_rows) if x["time"] <= q["time"]-15), None)
            if anchor is not None and q["time"]-15-anchor["time"] > 15:
                anchor = None
        elif len(self.points) == 9 and q["time"]-self.points[0]["time"] <= 60:
            anchor = self.points[0]
        if anchor is None:
            return out
        band = empty_band()
        band.update(known=True, quantity_known=frame["bad_quantity"] == anchor["bad_quantity"],
                    start_index=anchor["index"], index=frame["index"], start_line=anchor["line"], line=frame["line"],
                    start_time=anchor["time"], time=frame["time"], elapsed=frame["time"]-anchor["time"])
        for field in ("events", "quantity_events", "bad_quantity"):
            band[field] = frame[field]-anchor[field]
        if band["quantity_events"] > 0:
            for field in VOLUME_FIELDS:
                band[field] = (frame[field]-anchor[field])/band["quantity_events"]
        out.update(known=True, band=band)
        return out


def parse_clock(value) -> float | None:
    """
    機能: GoのRFC3339Nano→UnixNano float64/1e9と同じ秒数を得る。
    引数: value(any)は原板価格時計。
    返り値: float|Noneは時計又は欠測。不正価格時計は取込と同じ除外。
    """
    if not isinstance(value, str):
        return None
    match = re.fullmatch(r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:[.,](\d+))?(Z|[+-]\d{2}:\d{2})", value)
    if not match:
        return None
    try:
        base = datetime.fromisoformat(match[1]+match[3].replace("Z", "+00:00"))
        nanos = int(base.timestamp())*1_000_000_000+int(((match[2] or "")+"000000000")[:9])
        return float(nanos)/1e9
    except ValueError:
        return None


def raw_boards(path: Path, start: float, end: float, metrics: Counter):
    """
    機能: 固定Go取込のclock/10段型/最良量を明示対応で読み、同値行も保存する。
    引数: path(Path)、start/end(float)、metrics(Counter)は明示原板/場端/品質集計。
    返り値: iterator[dict]は受理価格時計の板。Last0はNative投入側で別除外。
    """
    previous = start
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        for line, text in enumerate(stream, 1):
            metrics["物理行"] += 1
            row = json.loads(text, parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)))
            need(type(row) is dict and isinstance(row.get("Symbol"), str), "Go取込Symbol型")
            clock_value = row.get("CurrentPriceTime")
            need(clock_value is None or isinstance(clock_value, str), "Go取込価格時計文字列型")
            at = parse_clock(clock_value)
            if at is None:
                metrics["clock欠測"] += 1
                continue
            if not start <= at < end:
                metrics["場外"] += 1
                continue
            if at < previous:
                metrics["clock後退"] += 1
                continue
            previous = at
            last = row.get("CurrentPrice")
            last = 0 if last is None else last
            need(finite(last), "Go取込CurrentPrice数値型")
            levels = []
            for side in ("Buy", "Sell"):
                side_rows = []
                for depth in range(1, 11):
                    name = side+str(depth)
                    need(name in row and (row[name] is None or type(row[name]) is dict), "Go取込段object")
                    raw = row[name] or {}
                    pair = []
                    for field in ("Price", "Qty"):
                        value = raw.get(field)
                        if value is None:
                            value = 0  # Go float64の零値。数量の既知性はstrict正条件で別判定する。
                            if depth == 1 and field == "Qty":
                                metrics["最良量field欠測/null"] += 1
                        need(finite(value), "Go取込段数値型")
                        pair.append(float(value))
                    side_rows.append(pair)
                levels.append(side_rows)
            metrics["受理価格時計"] += 1
            yield {"time": at, "line": line, "last": float(last), "bid": levels[0][0][0], "ask": levels[1][0][0],
                   "bq": levels[0][0][1], "aq": levels[1][0][1]}


def strict_support(known: bool, value: float, side: int) -> bool:
    """
    機能: 数値許容とは別にstrict同方向支持を無丸めで判定する。
    引数: known(bool)、value(float)、side(int)は量既知性・符号差・候補方向。
    返り値: boolは既知かつside*value>0。
    """
    return known and side*value > 0


def inspect_one(native: Path, entry: dict, source_root: Path,
                allowed_sessions: tuple = ("2026-09-21_Day", "2026-09-21_Night")) -> dict:
    """
    機能: 先に許可した場の量Currentだけを原板モデルへ比較し、損益を展開しない。
    引数: native(Path)、entry(dict)、source_root(Path)、allowed_sessions(tuple)は保存Current・台帳場・原板根・先に確定した許可集合。
    返り値: dictは既知/数値/strict支持の個別指標。
    """
    session = entry["id"]
    need(session in allowed_sessions, "CLIが先に確定した許可集合の場だけ")
    path_nk = source_root/entry["files"]["NK225_book"]["path"]
    path_tx = source_root/entry["files"]["TOPIX_book"]["path"]
    paths = (native, path_nk, path_tx)
    before = {str(p.resolve()): sha(p) for p in paths}
    for name, path in (("NK225_book", path_nk), ("TOPIX_book", path_tx)):
        need(sha(path) == entry["files"][name]["sha256"] and path.stat().st_size == entry["files"][name]["size"], "固定原板指紋")
    grids = project(native)
    day = session.endswith("_Day")
    tz = timezone(timedelta(hours=9))
    date = datetime.fromisoformat(session[:10]).replace(tzinfo=tz)
    start = (date+timedelta(hours=8, minutes=45) if day else date+timedelta(hours=17)).timestamp()
    end = (date+timedelta(hours=15, minutes=45) if day else date+timedelta(days=1, hours=6)).timestamp()
    tx_metrics = Counter()
    tx_end = None
    for q in raw_boards(path_tx, start, end, tx_metrics):
        tx_end = q["time"]
    metrics, comparisons = Counter(), Counter()
    max_error = 0.0
    last = state = None
    ofi, band = OFI30(), E08()
    gi = index = 0
    row_notes = []

    def equal(a, b, label: str) -> None:
        """
        機能: 既知/出典を厳密比較。
        引数: a/b(any)、label(str)。
        返り値: None。
        """
        need(a == b and (type(a) is type(b) or finite(a) and finite(b)), session+":"+label+f": {a} != {b}")
        comparisons["厳密field"] += 1

    def number(a, b, label: str) -> None:
        """
        機能: 量数値を許容付き比較。
        引数: a/b(number)、label(str)。
        返り値: None。
        """
        nonlocal max_error
        need(finite(a) and finite(b), "量非有限")
        max_error = max(max_error, abs(a-b))
        need(abs(a-b) <= ABS_TOL+REL_TOL*max(abs(a), abs(b)), session+":"+label+f": {a} != {b}")
        comparisons["数値field"] += 1

    def verify_grid(g: dict) -> None:
        """
        機能: 当枠の量Currentを直前Native値に結合。
        引数: g(dict)。
        返り値: None。
        """
        c = g["current"]
        expected_source = {"reference": "", "time": 0, "received": 0, "source_index": 0, "source_line": 0, "last": 0, "bid": 0, "ask": 0}
        if last is not None:
            expected_source = {"reference": "NK225", "time": last["time"], "received": last["time"], "source_index": last["index"], "source_line": last["line"], "last": last["last"], "bid": last["bid"], "ask": last["ask"]}
        for name, expected in expected_source.items():
            equal(c[name], expected, "Current."+name)
        if day:
            expected = state or {"known": False, "value": 0, "reason": "", "own_at": 0}
            for direction, side in (("buy", 1), ("sell", -1)):
                saved = c[direction]
                for name, target in (("ofi_known", "known"), ("ofi_reason", "reason"), ("own_at", "own_at")):
                    equal(saved[name], expected[target], direction+"."+name)
                number(saved["ofi30"], expected["value"], direction+".ofi30")
                equal(strict_support(saved["ofi_known"] and saved["own_at"] == c["time"], saved["ofi30"], side), strict_support(expected["known"], expected["value"], side), direction+".strict支持")
            comparisons["既知枠" if expected["known"] else "未知枠"] += 1
        else:
            expected = state or {"available": False, "known": False, "invalid": False, "window": "", "time": 0, "index": 0, "band": empty_band()}
            saved = c["night"]
            for name in ("available", "known", "invalid", "window", "time", "index"):
                equal(saved[name], expected[name], "night."+name)
            for name in BAND_FIELDS:
                if name in VOLUME_FIELDS:
                    number(saved["band"][name], expected["band"][name], "night.band."+name)
                else:
                    equal(saved["band"][name], expected["band"][name], "night.band."+name)
            x = saved["band"]
            y = expected["band"]
            actual_value = x["bid_refill"]+x["ask_deplete"]-x["ask_refill"]-x["bid_deplete"]
            expected_value = y["bid_refill"]+y["ask_deplete"]-y["ask_refill"]-y["bid_deplete"]
            known = expected["available"] and expected["window"] == "E08" and y["quantity_known"] and y["time"] == expected["time"] and y["index"] == expected["index"]
            actual_known = saved["available"] and saved["window"] == "E08" and x["quantity_known"] and x["time"] == c["time"] and x["index"] == c["source_index"]
            equal(actual_known, known, "night.量支持既知")
            for side in (-1, 1):
                equal(strict_support(actual_known, actual_value, side), strict_support(known, expected_value, side), "night.strict支持")
            comparisons["既知枠" if known else "未知枠"] += 1
        row_notes.append({"snapshot_id": g["snapshot_id"], "at": g["at"], "source_line": c["source_line"], "source_index": c["source_index"]})

    nk_end = None
    for q in raw_boards(path_nk, start, end, metrics):
        nk_end = q["time"]
        while gi < len(grids) and grids[gi]["at"] <= q["time"]:
            verify_grid(grids[gi]); gi += 1
        if q["last"] <= 0:
            metrics["Native Last0除外"] += 1
            continue
        q["index"] = index
        index += 1
        if not book_valid(q): metrics["Native不良BBO投入"] += 1
        if not qty_valid(q): metrics["Native量不明投入"] += 1
        state = ofi.add(q) if day else band.add(q)
        last = q
    clock_end = max(x for x in (nk_end, tx_end) if x is not None)
    while gi < len(grids):
        need(grids[gi]["at"] <= clock_end, "両市場EOF後のgrid")
        verify_grid(grids[gi]); gi += 1
    expected_clocks = [float(at) for at in range(int(start), int(end), 300) if at <= clock_end]
    equal([g["at"] for g in grids], expected_clocks, "両市場EOFまでの全grid")
    need(all(sha(Path(p)) == h for p, h in before.items()), "数量監査入力前後差")
    return {"session": session, "成功": True, "対象": "OFI30平均" if day else "E08四量平均", "枠数": len(grids),
            "照合項目数": comparisons["厳密field"]+comparisons["数値field"], "不一致数": 0, "比較": dict(comparisons),
            "最大絶対数値差": max_error, "Native NK特徴行数": index, "原板NK": dict(metrics), "原板TOPIX": dict(tx_metrics),
            "源結合": row_notes, "入力SHA256前後": before, "入力前後不変": True}


def select_sessions(manifest: dict, completion: dict, limit: int, filenames: set) -> list:
    """
    機能: 既使用54を先に抽出し、完了とNative実ファイルの集合を一致させる。
    引数: manifest/completion(dict)、limit(int)、filenames(set[str])は固定台帳・完了証拠・2/54・Native名。
    返り値: list[dict]は許可された先頭2又は全54場。未完/余剰/重複は拒否。
    """
    need(type(limit) is int and limit in (2, 54), "limitは2/54")
    selected = [s for s in manifest["sessions"] if "2026-09-21" <= s["id"][:10] <= "2026-10-27"]
    need(len(selected) == 54 and len({s["id"] for s in selected}) == 54, "既使用54の一意集合")
    need(all(re.fullmatch(r"2026-\d{2}-\d{2}_(Day|Night)", s["id"]) for s in selected), "場名形式")
    selected.sort(key=lambda s: s["id"])
    selected = selected[:limit]
    expected = {s["id"]+".json" for s in selected}
    need(completion.get("試行") == 96 and completion.get("Actor数") == 16 and completion.get("場数") == limit, "96/16Actor/場数の完了")
    need(all(completion.get(k) is True for k in ("G0対95全文一致", "Shadow93全文一致", "助走対本再生の場末公開値一致")), "Native三比較の完了")
    need(completion.get("台帳SHA256") == "b939bc91b33fd86e933534c3b991d844b8a0200a5f14710e1bd5004edc1aab42", "完了/台帳指紋")
    need(isinstance(completion.get("結果SHA256"), dict) and set(completion["結果SHA256"]) == expected == filenames, "完了/選択/実Native集合")
    need(all(type(h) is str and re.fullmatch(r"[0-9a-f]{64}", h) for h in completion["結果SHA256"].values()), "Native指紋形式")
    need(isinstance(completion.get("終了"), str) and bool(completion["終了"]), "Native未完了")
    return selected


def matched_availability(native: Path, day: bool) -> dict:
    """
    機能: 独立数値照合後の許可Currentだけから可用性とstrict支持の件数をまとめる。
    引数: native(Path)、day(bool)は検証済みNativeと場種。
    返り値: dictは既知正/負/中立/未知と理由。新しい量条件は追加しない。
    """
    classes, reasons = Counter(), Counter()
    for g in project(native):
        c = g["current"]
        if day:
            v = c["buy"]
            known = v["ofi_known"] and v["own_at"] == c["time"]
            value = v["ofi30"]
            reason = v["ofi_reason"] if not known else ""
        else:
            n, v = c["night"], c["night"]["band"]
            known = n["available"] and n["window"] == "E08" and v["quantity_known"] and v["time"] == c["time"] and v["index"] == c["source_index"]
            value = v["bid_refill"]+v["ask_deplete"]-v["ask_refill"]-v["bid_deplete"]
            reason = ("Native未観測" if not n["available"] else "E08以外のwindow" if n["window"] != "E08" else
                      "E08窓未形成/期限切れ/reset（保存band.known=false）" if not v["known"] else
                      "E08窓内の数量既知条件不成立" if not v["quantity_known"] else "量出典Time/Indexの不一致") if not known else ""
        classes["既知正（買い支持）" if known and value > 0 else "既知負（売り支持）" if known and value < 0 else "既知中立" if known else "未知"] += 1
        if not known:
            reasons[reason] += 1
    return {"分類": dict(classes), "未知理由": dict(reasons),
            "理由の種類": "保存OFIReason" if day else "保存flagsからの区分（元にreason字段はない）",
            "strict支持": {"買い": classes["既知正（買い支持）"], "売り": classes["既知負（売り支持）"], "既知両方向不支持": classes["既知中立"]}}


def main() -> int:
    """
    機能: 完了指紋付きの既使用2/54場の量と出典だけを検査する。
    引数: --input/--manifest/--completion/--out(Path)、--limit(int、既定2)はNative・台帳・完了証拠・新規出力・範囲。
    返り値: intは成功0/不一致1。Actor/PnL/他12や新日は展開しない。
    """
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("input", "manifest", "out"):
        parser.add_argument("--"+name, type=Path, required=True)
    parser.add_argument("--completion", type=Path)
    parser.add_argument("--limit", type=int, choices=(2, 54), default=2)
    args = parser.parse_args()
    need(not args.out.exists(), "新規証拠先")
    design_path = AREA/"読取設計.json"
    design = json.loads(design_path.read_bytes())
    before = {str(Path(__file__).resolve()): sha(Path(__file__)), str(design_path.resolve()): sha(design_path), str(args.manifest.resolve()): sha(args.manifest)}
    need(before[str(args.manifest.resolve())] == "b939bc91b33fd86e933534c3b991d844b8a0200a5f14710e1bd5004edc1aab42", "固定80台帳SHA")
    for p, expected in design["指紋"].items():
        need(sha(Path(p)) == expected, "元Go定義の指紋差")
        before[p] = expected
    try:
        manifest = json.loads(args.manifest.read_bytes())
        completion_path = args.completion or args.input/"完了.json"
        before[str(completion_path.resolve())] = sha(completion_path)
        completion = json.loads(completion_path.read_bytes())
        native_files = [p for p in args.input.glob("*.json") if re.fullmatch(r"\d{4}-\d{2}-\d{2}_(Day|Night)\.json", p.name)]
        selected_rows = select_sessions(manifest, completion, args.limit, {p.name for p in native_files})
        allowed = tuple(s["id"] for s in selected_rows)
        for name, expected in completion["結果SHA256"].items():
            path = args.input/name
            need(sha(path) == expected, "完了とNative SHA一致:"+name)
            before[str(path.resolve())] = expected
        rows = []
        totals = {kind: {"分類": Counter(), "未知理由": Counter(), "strict支持": Counter()} for kind in ("Day", "Night")}
        for entry in selected_rows:
            session = entry["id"]
            path = args.input/(session+".json")
            row = inspect_one(path, entry, Path(manifest["source_root"]), allowed)
            availability = matched_availability(path, session.endswith("_Day"))
            row["量可用性"] = availability
            for field in ("分類", "未知理由", "strict支持"):
                totals[session.split("_")[1]][field].update(availability[field])
            rows.append(row)
            print(f"数量監査 {len(rows)}/{args.limit} {session} 差0", flush=True)
        need(all(sha(Path(p)) == h for p, h in before.items()), "Go/コード/台帳前後差")
        result = {"成功": True, "scope": "接続2場" if args.limit == 2 else "正式既使用54場", "セッション数": args.limit, "枠数": sum(r["枠数"] for r in rows),
                  "照合項目数": sum(r["照合項目数"] for r in rows), "不一致数": 0, "details": rows,
                  "数値許容": {"絶対": ABS_TOL, "相対": REL_TOL}, "strict支持採否": "既知かつ符号積>0を許容差と別に比較・丸めなし",
                  "入力コードSHA256前後": before, "入力前後不変": True, "Actors/PnLのJSON展開": 0,
                  "Source数値転記/Go計算器実行": 0, "未読新日/他12場": 0,
                  "Native完了": {"path": str(completion_path.resolve()), "sha256": before[str(completion_path.resolve())], "試行": 96, "Actor数": 16, "G0/Shadow/助走一致": True},
                  "Day/Night量可用性": {kind: {k: dict(v) for k, v in fields.items()} for kind, fields in totals.items()},
                  "限界": "表示量の変化の再構成。取消/約定を識別せず、価格時計を真受信時刻と扱わない。commonDepth/hold/他指標は対象外。未知値の0は元Go保存表現であり既知の支持0とは分ける。"}
    except Exception as error:
        result = {"成功": False, "不整合": str(error), "入力コードSHA256前後": before}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2)+"\n", encoding="utf-8", newline="\n")
    print(json.dumps({k: result[k] for k in ("成功", "不整合", "枠数", "照合項目数") if k in result}, ensure_ascii=False))
    return 0 if result["成功"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
