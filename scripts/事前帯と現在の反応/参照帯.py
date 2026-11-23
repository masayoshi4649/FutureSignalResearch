"""正常気配付きLastの観測帯と、直前に収録された参照場を純粋に求める。"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import math
import re


JST = timezone(timedelta(hours=9))
RULES = {
    "帯の価格": "正常BBOかつ有限正Lastの観測OHLC。公式セッションOHLCではない",
    "区間": "begin以上end未満",
    "正常観測最小数": 2,
    "開始端最大空白秒": 300,
    "終了端最大空白秒": 300,
    "正常観測間最大空白秒": 300,
    "平坦帯": "被覆を満たせば既知。反応戦略の対象外判定は呼出側",
    "公開": "timerはendとline=None。rowは最初の有限非後退価格時計now>=endの原行",
    "直前帯": "台帳の直前収録一行だけ。同限月・異種・前end<現begin。古いgood代替なし",
    "時計除外": "49と同じ有限非後退処理。除外件数は外層の入力来歴で保持し帯へ混ぜない",
}


def _number(value: object, name: str, finite: bool = False) -> float:
    """数値の型を検査し、必要に応じて有限値を要求する。

    引数: value(object)は値、name(str)は項目名、finite(bool)は有限値を必須とする旗。
    返り値: floatは検査後の数値。不正な型又は必要な有限性の欠落は例外。
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name}は数値が必要です")
    try:
        result = float(value)
    except (OverflowError, ValueError) as error:
        raise ValueError(f"{name}をfloatへ変換できません") from error
    if finite and not math.isfinite(result):
        raise ValueError(f"{name}は有限値が必要です")
    return result


def _key(time: float, line: int | None) -> dict:
    """公開又は価格の出典keyを同じ形へ整える。

    引数: time(float)は価格時計又は終了境界、line(int|None)は原行又はタイマーの欠番。
    返り値: dictはtimeとlineの二項目。
    """
    return {"time": time, "line": line}


def _visible_interval(events: list[dict], begin: float, end: float) -> tuple[list[dict], dict | None]:
    """有限非後退の価格時計で区間と最初の終了markerまでを切り出す。

    引数: events(list[dict])は49の六列イベント原順、begin/end(float)は半開区間。
    返り値: tupleは区間内参照のlistと最初の終了marker。marker以後は読まない。
    """
    interval, previous, previous_line = [], -math.inf, 0
    for event in events:
        if not isinstance(event, dict) or "now" not in event:
            raise ValueError("イベントに価格時計がありません")
        now = _number(event["now"], "now")
        if not math.isfinite(now):
            continue
        line = event.get("line")
        if type(line) is not int or line <= previous_line:
            raise ValueError("原行は正の整数で厳密増加が必要です")
        previous_line = line
        if now < previous:
            continue
        previous = now
        if now >= end:
            return interval, _key(now, line)
        if now >= begin:
            interval.append(event)
    return interval, None


def aggregate(events: list[dict], begin: float, end: float, publication: str = "timer") -> dict:
    """半開区間の正常気配付きLastから観測帯と被覆を純集約する。

    引数: events(list[dict])はnow/line/last/bid/ask/validの六列原順、begin/end(float)は区間、
    publication(str)は終了境界timer又は原行確認row。timerの終了済み保証は呼出側が行う。
    返り値: dictは公開、ready、OHLC/mid、出典、被覆、区間内品質。未公開なら価格と被覆を隠す。
    """
    if not isinstance(events, list):
        raise ValueError("eventsはlistが必要です")
    begin, end = _number(begin, "begin", True), _number(end, "end", True)
    if end <= begin or publication not in ("timer", "row"):
        raise ValueError("帯の区間又は公開方式が不正です")
    interval, marker = _visible_interval(events, begin, end)
    result = {"begin": begin, "end": end, "publication": publication,
              "published": publication == "timer" or marker is not None,
              "publication_key": _key(end, None) if publication == "timer" else marker,
              "ready": False, "reason": "帯未公開", "open": None, "high": None,
              "low": None, "close": None, "mid": None, "sources": None,
              "coverage": None, "quality": None}
    if not result["published"]:
        return result

    # ----------------------------------------
    # 公開済み区間の価格だけを読む。markerの価格と未来suffixは集約しない。
    quality = {"interval_rows": len(interval), "invalid_bbo": 0, "invalid_last": 0}
    accepted = []
    for event in interval:
        if any(field not in event for field in ("last", "bid", "ask", "valid")):
            raise ValueError("イベントの六列が不足しています")
        if type(event["valid"]) is not bool:
            raise ValueError("validはboolが必要です")
        last = _number(event["last"], "last")
        bid, ask = _number(event["bid"], "bid"), _number(event["ask"], "ask")
        normal = event["valid"] and math.isfinite(bid) and math.isfinite(ask) and 0 < bid < ask
        positive = math.isfinite(last) and last > 0
        quality["invalid_bbo"] += int(not normal)
        quality["invalid_last"] += int(not positive)
        if normal and positive:
            accepted.append((last, _key(float(event["now"]), event["line"])))
    count = len(accepted)
    coverage = {"normal_count": count, "first_key": None, "last_key": None,
                "head_gap": None, "tail_gap": None, "max_gap": None,
                "covered": False, "flat": None}
    result.update(quality=quality, coverage=coverage)
    if not accepted:
        result["reason"] = "正常Last観測なし"
        return result
    first, last = accepted[0], accepted[-1]
    high = max(accepted, key=lambda item: item[0])
    low = min(accepted, key=lambda item: item[0])
    head, tail = first[1]["time"] - begin, end - last[1]["time"]
    maximum = max((b[1]["time"] - a[1]["time"] for a, b in zip(accepted, accepted[1:])), default=None)
    covered = count >= 2 and head <= 300 and tail <= 300 and maximum is not None and maximum <= 300
    coverage.update(first_key=deepcopy(first[1]), last_key=deepcopy(last[1]),
                    head_gap=head, tail_gap=tail, max_gap=maximum, covered=covered,
                    flat=high[0] == low[0])
    reasons = []
    if count < 2:
        reasons.append("正常観測2件未満")
    if head > 300:
        reasons.append("開始端空白300秒超")
    if tail > 300:
        reasons.append("終了端空白300秒超")
    if maximum is not None and maximum > 300:
        reasons.append("正常観測間空白300秒超")
    result.update(ready=covered, reason="準備済み" if covered else "・".join(reasons),
                  open=first[0], high=high[0], low=low[0], close=last[0],
                  mid=high[0] / 2 + low[0] / 2,
                  sources={"open": deepcopy(first[1]), "high": deepcopy(high[1]),
                           "low": deepcopy(low[1]), "close": deepcopy(last[1])})
    return result


# ----------------------------------------
# 直前収録の対応はmetadataだけで決める。価格や集約済み全場結果は受け取らない。

def bounds(session: str) -> tuple[float, float]:
    """開始日基準の場名から49の連続区間を独立に計算する。

    引数: session(str)はYYYY-MM-DD_Day又はYYYY-MM-DD_Night。
    返り値: tuple[float,float]はJST開始と終了のUnix秒。不正な場名は例外。
    """
    if not isinstance(session, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}_(Day|Night)", session):
        raise ValueError("場名が不正です")
    date = datetime.fromisoformat(session[:10]).replace(tzinfo=JST)
    if session.endswith("_Day"):
        return ((date + timedelta(hours=8, minutes=45)).timestamp(),
                (date + timedelta(hours=15, minutes=40)).timestamp())
    return ((date + timedelta(hours=17)).timestamp(),
            (date + timedelta(days=1, hours=5, minutes=55)).timestamp())


def _metadata(entry: dict) -> dict:
    """台帳から参照に必要な識別だけを射影する。

    引数: entry(dict)は生台帳の一行。数量監査や他の価格材料は読み出さない。
    返り値: dictは場名、限月、境界及び存在するsource/cache識別。
    """
    if not isinstance(entry, dict) or entry.get("symbol") != "NK225":
        raise ValueError("NK225台帳行が必要です")
    begin, end = bounds(entry.get("session"))
    contract = entry.get("in_session_contract_codes")
    if not isinstance(contract, (list, tuple)) or any(not isinstance(code, str) or not code for code in contract):
        raise ValueError("限月は空でない文字列のlist又はtupleが必要です")
    result = {"session": entry["session"], "symbol": entry["symbol"],
              "contract": list(contract), "begin": begin, "end": end}
    for field in ("source_path", "source_size", "source_mtime_ns", "sha256_uncompressed",
                  "cache_path", "cache_size", "sha256_cache"):
        if field in entry:
            result[field] = deepcopy(entry[field])
    return result


def choose_previous(entries: list[dict]) -> dict:
    """開始昇順の台帳で直前収録一行だけを参照帯候補に対応させる。

    引数: entries(list[dict])は生台帳。現在場の価格・全場帯は受け取らない。
    返り値: dictはsessionごとのready/reason/直前metadata/空白。readyは帯の被覆合格を意味しない。
    """
    if not isinstance(entries, list):
        raise ValueError("entriesはlistが必要です")
    result, previous = {}, None
    for entry in entries:
        current = _metadata(entry)
        if current["session"] in result or previous is not None and current["begin"] <= previous["begin"]:
            raise ValueError("台帳は一意な場の開始昇順が必要です")
        item = {"ready": False, "reason": "前収録なし", "current_session": current["session"],
                "contract": deepcopy(current["contract"]), "current_begin": current["begin"],
                "current_end": current["end"], "prior_session": None, "prior_begin": None,
                "prior_end": None, "gap_seconds": None, "calendar_adjacency": "未確認",
                "prior": None}
        if previous is not None:
            item.update(prior_session=previous["session"], prior_begin=previous["begin"],
                        prior_end=previous["end"], gap_seconds=current["begin"] - previous["end"],
                        prior=deepcopy(previous))
            if len(previous["contract"]) != 1 or len(current["contract"]) != 1:
                item["reason"] = "限月が一意でない"
            elif previous["contract"] != current["contract"]:
                item["reason"] = "限月不一致"
            elif previous["session"].rsplit("_", 1)[1] == current["session"].rsplit("_", 1)[1]:
                item["reason"] = "前収録の区分不一致"
            elif not previous["end"] < current["begin"]:
                item["reason"] = "前帯が現在場開始より前に終了していない"
            else:
                item.update(ready=True, reason="直前収録参照可能")
        result[current["session"]] = item
        previous = current
    return result


# ----------------------------------------
# 人工データだけで契約を確認する。市場入力・台帳・cacheのファイルは開かない。

def _artificial_event(now: float, line: int, last: float = 100., **changes: object) -> dict:
    """参照帯の人工用に正常な六列観測を一件作る。

    引数: now(float)は時計、line(int)は原行、last(float)はLast、changes(object)は置換項目。
    返り値: dictは架空イベント。
    """
    result = {"now": now, "line": line, "last": last, "bid": last - 1,
              "ask": last + 1, "valid": True}
    result.update(changes)
    return result


def self_test() -> dict:
    """手で定めた期待値と鏡像・公開prefixの反例で純集約を検査する。

    引数: なし。市場ファイルや本物台帳を読み込まない。
    返り値: dictは成功、テスト件数、照合件数と不一致。失敗時はAssertionError。
    """
    tests, checks = 0, 0

    def equal(actual: object, expected: object) -> None:
        """人工の実値と独立に置いた期待値を比較する。

        引数: actual/expected(object)は比較する値。
        返り値: None。不一致なら例外。
        """
        nonlocal checks
        checks += 1
        assert actual == expected, (actual, expected)

    def rejects(function: object, *args: object, **kwargs: object) -> None:
        """人工の不整合入力が例外で拒否されることを確認する。

        引数: function(object)は呼出対象、args/kwargs(object)は架空引数。
        返り値: None。拒否されなければ例外。
        """
        nonlocal checks
        checks += 1
        try:
            function(*args, **kwargs)
        except ValueError:
            return
        raise AssertionError("不整合入力が拒否されませんでした")

    event = _artificial_event
    rows = [event(0., 1, 100.), event(300., 2, 140.), event(600., 3, 90.), event(899., 4, 110.)]
    base = aggregate(rows, 0, 900)
    equal([base[k] for k in ("open", "high", "low", "close", "mid", "ready", "reason")],
          [100., 140., 90., 110., 115., True, "準備済み"])
    equal(base["coverage"], {"normal_count": 4, "first_key": {"time": 0., "line": 1},
          "last_key": {"time": 899., "line": 4}, "head_gap": 0., "tail_gap": 1.,
          "max_gap": 300., "covered": True, "flat": False})
    equal(base["sources"], {"open": {"time": 0., "line": 1}, "high": {"time": 300., "line": 2},
          "low": {"time": 600., "line": 3}, "close": {"time": 899., "line": 4}})
    equal(base["publication_key"], {"time": 900., "line": None})
    equal(base["quality"], {"interval_rows": 4, "invalid_bbo": 0, "invalid_last": 0})
    tests += 1

    at_end = event(900., 5, 999999.)
    equal(aggregate(rows + [at_end], 0, 900), base)
    row_band = aggregate(rows + [at_end], 0, 900, "row")
    equal(row_band["publication_key"], {"time": 900., "line": 5})
    equal(row_band["high"], 140.)
    tests += 1

    unknown = aggregate(rows, 0, 900, "row")
    equal(unknown["reason"], "帯未公開")
    equal([unknown[k] for k in ("ready", "published", "publication_key", "open", "high", "low",
                               "close", "mid", "sources", "coverage", "quality")],
          [False, False, None, None, None, None, None, None, None, None, None])
    tests += 1

    marker = {"now": 901., "line": 5, "last": None, "bid": None, "ask": None, "valid": None}
    late = aggregate(rows + [marker], 0, 900, "row")
    equal(late["publication_key"], {"time": 901., "line": 5})
    equal(late["coverage"], base["coverage"])
    equal(late["quality"], base["quality"])
    tests += 1

    same = aggregate([event(0, 1, 100), event(0, 2, 140), event(0, 3, 140),
                      event(299, 4, 90), event(299, 5, 90)], 0, 300)
    equal(same["sources"], {"open": {"time": 0., "line": 1}, "high": {"time": 0., "line": 2},
          "low": {"time": 299., "line": 4}, "close": {"time": 299., "line": 5}})
    equal(same["coverage"]["normal_count"], 5)
    tests += 1

    excluded = [event(float("nan"), 1), event(-1, 2)]
    excluded += [event(0, 3, 100), event(-.1, 4, 9999), event(299, 5, 110)]
    filtered = aggregate(excluded, 0, 300)
    clean = aggregate([event(0, 3, 100), event(299, 5, 110)], 0, 300)
    equal(filtered, clean)
    equal(set(filtered["quality"]), {"interval_rows", "invalid_bbo", "invalid_last"})
    tests += 1

    exact_gap = aggregate([event(0, 1), event(300, 2)], 0, 600)
    equal(exact_gap["ready"], True)
    equal(exact_gap["coverage"]["max_gap"], 300.)
    beyond_gap = aggregate([event(0, 1), event(300.01, 2), event(599, 3)], 0, 600)
    equal(beyond_gap["reason"], "正常観測間空白300秒超")
    tests += 1

    head_exact = aggregate([event(300, 1), event(599, 2)], 0, 600)
    equal(head_exact["ready"], True)
    equal(aggregate([event(300.01, 1), event(599, 2)], 0, 600)["reason"], "開始端空白300秒超")
    tests += 1

    equal(exact_gap["coverage"]["tail_gap"], 300.)
    equal(aggregate([event(0, 1), event(299.99, 2)], 0, 600)["reason"], "終了端空白300秒超")
    tests += 1

    one = aggregate([event(1, 1)], 0, 2)
    equal(one["reason"], "正常観測2件未満")
    equal(one["coverage"]["max_gap"], None)
    equal(one["coverage"]["flat"], True)
    tests += 1

    bad = [event(0, 1, float("inf"), bid=99, ask=101), event(1, 2, -1, bid=99, ask=101), event(2, 3, valid=False),
           event(3, 4, bid=102, ask=101), event(4, 5, bid=float("nan"))]
    empty = aggregate(bad, 0, 5)
    equal(empty["reason"], "正常Last観測なし")
    equal(empty["quality"], {"interval_rows": 5, "invalid_bbo": 3, "invalid_last": 2})
    equal([empty[k] for k in ("high", "low", "open", "close", "sources")], [None] * 5)
    tests += 1

    flat = aggregate([event(0, 1), event(299, 2)], 0, 300)
    equal([flat["ready"], flat["coverage"]["flat"], flat["high"], flat["low"]], [True, True, 100., 100.])
    tests += 1

    reflected = [{**r, "last": 400 - r["last"], "bid": 400 - r["ask"], "ask": 400 - r["bid"]} for r in rows]
    mirror = aggregate(reflected, 0, 900)
    equal([mirror[k] for k in ("open", "high", "low", "close", "mid")], [300., 310., 260., 290., 285.])
    equal(mirror["sources"]["high"], base["sources"]["low"])
    equal(mirror["sources"]["low"], base["sources"]["high"])
    equal(mirror["coverage"], base["coverage"])
    shifted = aggregate([{**r, "last": r["last"] + 7, "bid": r["bid"] + 7, "ask": r["ask"] + 7} for r in rows], 0, 900)
    equal([shifted[k] for k in ("open", "high", "low", "close", "mid")], [107., 147., 97., 117., 122.])
    tests += 1

    suffix = [None, {"now": "不正", "line": False}, event(899, -7, -999)]
    equal(aggregate(rows + [at_end] + suffix, 0, 900, "row"), row_band)
    equal(aggregate(rows + [at_end] + suffix, 0, 900, "timer"), base)
    tests += 1

    prior_bad_prices = {"now": -1., "line": 1, "last": "不読", "bid": None}
    equal(aggregate([prior_bad_prices, event(0, 2), event(299, 3)], 0, 300)["ready"], True)
    concealed = aggregate([{"now": 0., "line": 1, "last": "未公開は不読"}], 0, 300, "row")
    equal(concealed["quality"], None)
    tests += 1

    before = repr(rows)
    aggregate(rows, 0, 900)
    equal(repr(rows), before)
    altered = deepcopy(base)
    altered["sources"]["open"]["line"] = -1
    equal(rows[0]["line"], 1)
    tests += 1

    entries = [{"symbol": "NK225", "session": session, "in_session_contract_codes": ["契約A"],
                "cache_path": f"{session}.npz", "volume_audit": {"未参照": object()}}
               for session in ("2026-10-01_Day", "2026-10-01_Night", "2026-10-02_Day")]
    selected = choose_previous(entries)
    equal(selected[entries[0]["session"]]["reason"], "前収録なし")
    equal(selected[entries[1]["session"]]["gap_seconds"], 4800.)
    equal(selected[entries[2]["session"]]["gap_seconds"], 10200.)
    equal(selected[entries[2]["session"]]["prior_session"], entries[1]["session"])
    equal(selected[entries[2]["session"]]["ready"], True)
    equal("volume_audit" in selected[entries[2]["session"]]["prior"], False)
    tests += 1

    weekend = deepcopy(entries[:2])
    weekend[0]["session"], weekend[1]["session"] = "2026-10-02_Night", "2026-10-05_Day"
    weekend_result = choose_previous(weekend)["2026-10-05_Day"]
    equal([weekend_result[k] for k in ("ready", "gap_seconds", "calendar_adjacency")], [True, 183000., "未確認"])
    tests += 1

    wrong = deepcopy(entries)
    wrong[1]["session"] = "2026-10-02_Day"
    wrong.pop()
    equal(choose_previous(wrong)["2026-10-02_Day"]["reason"], "前収録の区分不一致")
    roll = deepcopy(entries)
    roll[1]["in_session_contract_codes"] = ["契約B"]
    equal(choose_previous(roll)[entries[2]["session"]]["reason"], "限月不一致")
    equal(choose_previous(roll)[entries[2]["session"]]["prior_session"], entries[1]["session"])
    tests += 1

    for changes in ({"line": True}, {"line": 0}, {"line": 1.0}, {"now": True}):
        rejects(aggregate, [{**event(0, 1), **changes}], 0, 300)
    rejects(aggregate, [event(0, 1), event(1, 1)], 0, 300)
    rejects(aggregate, [event(0, 2), event(1, 1)], 0, 300)
    rejects(aggregate, [], 0, 0)
    rejects(aggregate, [], 0, float("inf"))
    rejects(aggregate, [], 0, 300, "不正公開")
    rejects(aggregate, [event(0, 1, valid=1)], 0, 300)
    rejects(aggregate, [event(0, 1, last=True)], 0, 300)
    tests += 1

    rejects(choose_previous, entries[::-1])
    rejects(choose_previous, [entries[0], entries[0]])
    rejects(choose_previous, [{**entries[0], "symbol": "TOPIX"}])
    rejects(choose_previous, [{**entries[0], "session": "2026-10-01_不明"}])
    rejects(choose_previous, [{**entries[0], "in_session_contract_codes": [True]}])
    multi = deepcopy(entries[:2])
    multi[0]["in_session_contract_codes"] = ["契約A", "契約B"]
    equal(choose_previous(multi)[multi[1]["session"]]["reason"], "限月が一意でない")
    tests += 1

    selected[entries[1]["session"]]["prior"]["contract"].append("出力変更")
    equal(entries[0]["in_session_contract_codes"], ["契約A"])
    equal(bounds("2026-10-01_Day")[1] - bounds("2026-10-01_Day")[0], 24900.)
    equal(bounds("2026-10-01_Night")[1] - bounds("2026-10-01_Night")[0], 46500.)
    tests += 1

    return {"成功": True, "人工成功": True, "テスト件数": tests, "照合項目数": checks,
            "不一致数": 0, "不一致": [], "本物入力読取": False, "新fit": 0, "市場再生": False}


def 人工() -> dict:
    """市場入力を使わない参照帯の人工検査を実行する。

    引数: なし。
    返り値: dictはself_testの小型成功要約。
    """
    return self_test()
