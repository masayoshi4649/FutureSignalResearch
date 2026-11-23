"""97主H0のSource建値とActual建値を、取得時と実保有内の源返済要求に限定して比較する。"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
import gzip
import hashlib
import json
import math
from pathlib import Path
import re
from statistics import median

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
RUN = ROOT / "work/97実行/正式54場"
CONDITION = ROOT / "study/00097_初回費用後利益の全量確定/条件.json"
KEY = "H0_B5Q_P0_C0_D0"


def sha(path: Path) -> str:
    """既存入力の指紋を取得する。

    引数: path(Path)は許可済みNative/Tape/条件。
    返り値: strはSHA256。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path) -> dict:
    """指定JSONを読む。

    引数: path(Path)は許可済み保存先。
    返り値: dictは保存内容。
    """
    return json.loads(path.read_text(encoding="utf-8-sig"))


def events(path: Path):
    """Tapeのevents配列を逐次返す。

    引数: path(Path)は固定97 Tape gzip。
    返り値: iterator[dict]は一原行/定時/Force。呼出側は最終必要Indexで打ち切る。
    """
    decoder = json.JSONDecoder()
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        buffer = ""
        while True:
            chunk = stream.read(65536)
            if not chunk:
                raise ValueError("Tape events配列なし")
            buffer += chunk
            match = re.search(r'"events"\s*:\s*\[', buffer)
            if match:
                position = match.end()
                break
        while True:
            while position < len(buffer) and buffer[position] in " \r\n\t,":
                position += 1
            if position < len(buffer) and buffer[position] == "]":
                return
            try:
                value, end = decoder.raw_decode(buffer, position)
            except json.JSONDecodeError:
                chunk = stream.read(65536)
                if not chunk:
                    raise ValueError("Tapeイベントの途中欠測")
                buffer = buffer[position:] + chunk
                position = 0
                continue
            yield value
            position = end
            if position > 65536:
                buffer, position = buffer[position:], 0


def sign_name(value: float) -> str:
    """Actual建値の方向付き差を分類する。

    引数: value(float)はs×(Actual建値−Source建値)。
    返り値: strは不利/同値/有利。価格差を金額へ変換しない。
    """
    return "不利" if value > 0 else "有利" if value < 0 else "同値"


def price_location(value: float | None) -> str:
    """返済側気配が建値に対してどちら側かを表す。

    引数: value(float|None)は方向付き価格差。
    返り値: strは順行側/建値/逆行側/気配未知。
    """
    return "気配未知" if value is None else "順行側" if value > 0 else "逆行側" if value < 0 else "建値"


def compact_quote(q: dict) -> dict:
    """実使用した気配だけを小型化する。

    引数: q(dict)は保存QuoteStamp。
    返り値: dictは時計/Index/物理行/BBO/正常性。将来値は加えない。
    """
    return {k: q[k] for k in ("time", "index", "source_line", "bid", "ask", "quote_ok")}


def compare_quote(left: dict, right: dict) -> None:
    """NativeとTapeの使用原行を厳密照合する。

    引数: left/right(dict)は同じFeaturesIndexの保存気配。
    返り値: なし。BBO/Last/時計/物理行が違えば失敗。
    """
    for key in ("time", "index", "source_line", "last", "bid", "ask", "quote_ok"):
        assert left[key] == right[key], (key, left, right)


def source_entry(scene: dict, position: dict) -> dict:
    """実際に選ばれた元所有の新規Fillを結ぶ。

    引数: scene/position(dict)は許可済みNativeと主H0実玉。
    返り値: dictはSource新規Fill。返済価格/元経路の峰は抽出しない。
    """
    identity = position["source"]
    method = identity["method"].removeprefix("NK225_")
    shadow = scene["shadows"][method]
    signals = [s for s in shadow["signals"] if s["signal"]["action"] == "new" and s["signal"]["id"] == identity["signal_id"]]
    assert len(signals) == 1
    signal = signals[0]["signal"]
    evidence = signal["evidence"]
    assert (evidence["source_id"], evidence["kind"], evidence["parent"], signal["side"], signal["quantity"]) == (identity["source_id"], identity["kind"], identity["parent"], position["side"], identity["birth_quantity"])
    fills = [f for f in shadow["fills"] if f["action"] == "new" and f["fill"]["SignalID"] == identity["signal_id"] and f["fill"]["HoldID"] == position["source_hold_id"]]
    assert len(fills) == 1
    fill = fills[0]
    assert fill["side"] == position["side"] and fill["fill"]["Time"] <= position["entry_quote"]["time"] and fill["quote"]["index"] <= position["entry_quote"]["index"]
    assert fill["fill"]["Quantity"] == identity["birth_quantity"]
    for quote, price in ((fill["quote"], fill["fill"]["Price"]), (position["entry_quote"], position["entry_price"])):
        assert quote["quote_ok"] and 0 < quote["bid"] < quote["ask"]
        assert price == quote["ask" if position["side"] > 0 else "bid"]
    return fill


def notices_before_exit(book: dict, p: dict) -> list[dict]:
    """実保有中のSource返済通知だけを抽出する。

    引数: book/p(dict)は主H0会計とNo-u玉。
    返り値: list[dict]は同原行fill後も残玉がある時点の通知。退出後の気配を参照しない。
    """
    found = []
    closed = [f for f in book["fills"] if f["position_id"] == p["id"] and f["action"] == "close"]
    for e in book["source_events"]:
        if e["kind"] != "close_notice" or e["hold_id"] != p["source_hold_id"]:
            continue
        if not p["entry_quote"]["time"] <= e["at"] <= p["closed_quote"]["time"]:
            continue
        index = e["quote"]["index"]
        if not p["entry_quote"]["index"] <= index <= p["closed_quote"]["index"]:
            continue
        remaining = p["initial_quantity"] - sum(f["quantity"] for f in closed if f["quote"]["index"] <= index)
        if remaining <= 0:
            continue
        found.append(dict(e, remaining_after_fill=remaining))
    return found


def statistics(rows: list[dict]) -> dict:
    """取得時だけの特徴を符号分類して要約する。

    引数: rows(list[dict])は重複除去した元所有とActualの組。
    返り値: dictは数/中央値/範囲。新戦略損益を生成しない。
    """
    diffs = [r["delta_points"] for r in rows]
    ratios = [r["delta_over_entry_ATR"] for r in rows if r["delta_over_entry_ATR"] is not None]
    return {"玉数": len(rows), "取得枚数": sum(r["quantity"] for r in rows), "分類": dict(Counter(r["delta_class"] for r in rows)),
            "差pt_中央値": median(diffs) if diffs else None, "差pt_最小": min(diffs) if diffs else None, "差pt_最大": max(diffs) if diffs else None,
            "取得時ATR既知": len(ratios), "取得時ATR未知": len(rows) - len(ratios), "差ATR_中央値": median(ratios) if ratios else None,
            "差ATR_最小": min(ratios) if ratios else None, "差ATR_最大": max(ratios) if ratios else None}


def inspect_scene(scene: dict) -> tuple[list[dict], list[dict], dict]:
    """一場の取得時情報とNo-u保有内通知だけを結ぶ。

    引数: scene(dict)は97主H0を含む許可済みNative。
    返り値: tupleはNo-u行/正益群の取得時行/走査範囲。金融を再生しない。
    """
    book = scene["books"][KEY]
    positions = book["positions"]
    rows, source_fills, quote_targets, desired = [], {}, {}, {}
    seen = set()
    for p in positions:
        key = p["source"]["method"], p["source"]["signal_id"], p["source_hold_id"]
        assert key not in seen
        seen.add(key)
        fill = source_entry(scene, p)
        source_fills[p["source_hold_id"]] = fill
        quote_targets[fill["quote"]["index"]] = fill["quote"]
        quote_targets[p["entry_quote"]["index"]] = p["entry_quote"]
        no_u = p["marks"]["first_unit_positive"] is None
        assert p["quantity"] == p["reserved"] == 0
        if no_u:
            assert not p["protection_active"]
        delta = p["side"] * (p["entry_price"] - fill["fill"]["Price"])
        row = {"session": scene["session"], "position_id": p["id"], "method": p["source"]["method"], "kind": p["source"]["kind"], "parent": p["source"]["parent"], "signal_id": p["source"]["signal_id"], "source_id": p["source"]["source_id"], "hold_id": p["source_hold_id"], "side": p["side"], "quantity": p["initial_quantity"], "source_entry_price": fill["fill"]["Price"], "source_entry_quote": compact_quote(fill["quote"]), "actual_entry_price": p["entry_price"], "actual_entry_quote": compact_quote(p["entry_quote"]), "entry_delay_seconds": p["entry_quote"]["time"] - fill["fill"]["Time"], "delta_points": delta, "delta_class": sign_name(delta), "no_u": no_u, "notices": []}
        row["_native_entry_atr"] = p["atr"] if p["atr"] is not None and not p["atr"]["after_entry"] else None
        if no_u:
            row["actual_realized_net_yen"] = p["realized_net"]
            row["actual_exit_bound"] = {"time": p["closed_quote"]["time"], "index": p["closed_quote"]["index"], "source_line": p["closed_quote"]["source_line"]}
            for notice in notices_before_exit(book, p):
                nk = notice["notice_id"], notice["at"], notice["quote"]["index"]
                assert nk not in desired
                desired[nk] = (row, notice)
                quote_targets[notice["quote"]["index"]] = notice["quote"]
        rows.append(row)
    tape_path = Path(scene["input96_provenance"]["tape_path"])
    assert sha(tape_path) == scene["input96_provenance"]["tape_sha256"]
    last_index = max(quote_targets, default=-1)
    observed_quotes, observed_sources, observed_notices = {}, set(), set()
    scanned = 0
    iterator = events(tape_path)
    try:
        for event in iterator:
            scanned += 1
            if event["kind"] == "quote":
                q = event["quote"]
                if q["index"] in quote_targets:
                    compare_quote(quote_targets[q["index"]], q)
                    observed_quotes[q["index"]] = q
            for batch in event.get("non_empty", []):
                delta = batch["delta"]
                for fill in delta.get("fills", []):
                    if fill["action"] != "new":
                        continue
                    hold = fill["fill"]["HoldID"]
                    if hold in source_fills:
                        assert fill == source_fills[hold]
                        observed_sources.add(hold)
                for notice in delta.get("closes", []):
                    possible = [(key, value) for key, value in desired.items() if key[0] == notice["id"] and key[1] == delta["at"]]
                    for key, (row, saved) in possible:
                        signal = next(s for s in delta["signals"] if s["signal"]["id"] == saved["signal_id"])
                        q = signal["quote"]
                        assert q["index"] == key[2]
                        compare_quote(saved["quote"], q)
                        assert (notice["before"], notice["quantity"], notice["reference_id"]) == (saved["before"], saved["quantity"], row["hold_id"])
                        valid = q["quote_ok"] and all(math.isfinite(q[k]) and q[k] > 0 for k in ("bid", "ask")) and q["bid"] < q["ask"]
                        mark = (q["bid"] if row["side"] > 0 else q["ask"]) if valid else None
                        source_gain = row["side"] * (mark - row["source_entry_price"]) if mark is not None else None
                        actual_gain = row["side"] * (mark - row["actual_entry_price"]) if mark is not None else None
                        if mark is not None:
                            assert actual_gain == source_gain - row["delta_points"]
                        row["notices"].append({"notice_id": notice["id"], "at": delta["at"], "origin": delta["origin"], "quote": compact_quote(q), "quote_age_seconds": delta["at"] - q["time"], "source_before": notice["before"], "source_quantity": notice["quantity"], "actual_remaining": saved["remaining_after_fill"], "actual_exit_requested": saved["actual_exit_requested"], "source_gain_points": source_gain, "actual_gain_points": actual_gain, "source_location": price_location(source_gain), "actual_location": price_location(actual_gain), "reason": saved["reason"]})
                        observed_notices.add(key)
            if event["kind"] == "quote" and event["quote"]["index"] == last_index:
                break
    finally:
        iterator.close()
    assert set(quote_targets) == set(observed_quotes)
    assert set(source_fills) == observed_sources
    assert set(desired) == observed_notices
    for row in rows:
        q = observed_quotes[row["actual_entry_quote"]["index"]]
        value, available, nominal = q["atr"], q["atr_available"], q["atr_nominal"]
        assert all(math.isfinite(x) for x in (value, available, nominal)) and value >= 0
        if value > 0:
            assert available > 0 and nominal > 0 and available <= q["time"] and nominal <= q["time"]
        known = value > 0 and available > 0 and nominal > 0 and available <= q["time"] and nominal <= q["time"]
        row["entry_ATR"] = {"known": known, "value": value if known else None, "available": available if known else None, "nominal": nominal if known else None, "age_seconds": q["time"] - available if known else None, "fixed_2ATR_width": math.ceil(2 * value / 5) * 5 if known else None}
        row["delta_over_entry_ATR"] = row["delta_points"] / value if known else None
        saved_atr = row.pop("_native_entry_atr")
        if known:
            assert saved_atr is not None
            assert (saved_atr["value"], saved_atr["available"], saved_atr["nominal"], saved_atr["width"]) == (value, available, nominal, row["entry_ATR"]["fixed_2ATR_width"])
    no_u_rows = [r for r in rows if r["no_u"]]
    positive_rows = [r for r in rows if not r["no_u"]]
    for r in positive_rows:
        assert not r["notices"] and "actual_exit_bound" not in r and "actual_realized_net_yen" not in r
    return no_u_rows, positive_rows, {"session": scene["session"], "tape": str(tape_path.relative_to(ROOT)), "tape_events_examined": scanned, "last_required_index": last_index, "source_entries": len(observed_sources), "entry_and_request_quotes": len(observed_quotes), "no_u_source_notices": len(observed_notices), "post_actual_exit_source_price_queries": 0}


def main() -> None:
    """54場の許可済み保存だけから建値差を記述集計する。

    引数: なし。入力と主条件を固定する。
    返り値: なし。欠測/未来/結合不一致は失敗する。新売買は作らない。
    """
    output = HERE / "結果.json"
    if output.exists():
        raise FileExistsError(output)
    condition = read(CONDITION)
    assert sha(CONDITION) == "f7421f26a306eb0a49387b9dfa2104621350fac5c6ceba035a84bb3661d42c05"
    code_expected = {str((ROOT / p).resolve()): value for p, value in condition["コードSHA256"].items()}
    code_before = {p: sha(Path(p)) for p in code_expected}
    assert len(code_before) == 155 and code_before == code_expected
    completion_path = RUN / "完了.json"
    completion = read(completion_path)
    assert completion["成功"] is True and completion["場数"] == 54 and len(completion["結果"]) == 54
    inputs = {str(CONDITION.relative_to(ROOT)): sha(CONDITION), str(completion_path.relative_to(ROOT)): sha(completion_path)}
    no_u, positive, scopes = [], [], []
    for i, saved in enumerate(completion["結果"], 1):
        path = (ROOT / saved["path"]).resolve()
        assert path.parent == RUN.resolve() and re.fullmatch(r"2026-\d\d-\d\d_(Day|Night)", saved["session"])
        assert sha(path) == saved["sha256"]
        inputs[str(path.relative_to(ROOT))] = sha(path)
        scene = read(path)
        assert scene["session"] == saved["session"] and scene["actual_run_complete"] is True
        tape = Path(scene["input96_provenance"]["tape_path"])
        assert tape.resolve().is_relative_to((ROOT / "work/97正式Tape").resolve())
        inputs[str(tape.relative_to(ROOT))] = sha(tape)
        negative_rows, positive_rows, scope = inspect_scene(scene)
        no_u.extend(negative_rows)
        positive.extend(positive_rows)
        scopes.append(scope)
        if i % 9 == 0:
            print(f"建値差の保存照合 {i}/54", flush=True)
    assert len(no_u) == 49 and len(positive) == 253
    assert len({(r["session"], r["signal_id"], r["hold_id"]) for r in no_u + positive}) == 302
    after = {p: sha(ROOT / p) for p in inputs}
    code_after = {p: sha(Path(p)) for p in code_expected}
    assert inputs == after and code_before == code_after
    notices = [n for r in no_u for n in r["notices"]]
    matrix = Counter((n["source_location"], n["actual_location"]) for n in notices)
    by_delta = {kind: {**statistics([r for r in no_u if r["delta_class"] == kind]), "実現額円": sum(r["actual_realized_net_yen"] for r in no_u if r["delta_class"] == kind)} for kind in ("不利", "同値", "有利")}
    report = {"成功": True, "記録時刻": datetime.now().astimezone().isoformat(), "口座": KEY,
              "定義": {"差": "δ=s×(Actual建値−Source新規Fill建値)。正はActual不利、負は有利、0は同値。差を仮想利益へ換算しない。", "要求時位置": "返済側Bid/Askから各建値を引いた符号付きpt。指定費用控除後の損益と同一ではない。", "No_u": "保存されたfirst_unit_positiveがnull。正益253は事後の比較群だが特徴量は取得時既知情報だけ。", "期限": "No-uのSource通知はActual実保有内の当行fill後残玉正だけ。正益群は取得時のみ。ピーク/退出後価格/未参加は抽出しない。"},
              "取得時比較": {"No-u": statistics(no_u), "u正益": statistics(positive)}, "No-u差分類": by_delta,
              "Source返済通知": {"通知数": len(notices), "通知あり玉": sum(bool(r["notices"]) for r in no_u), "通知なし玉": sum(not r["notices"] for r in no_u), "両建値の位置": [{"Source": a, "Actual": b, "通知数": n} for (a, b), n in sorted(matrix.items())]},
              "元手法別": {method: {"No-u": statistics([r for r in no_u if r["method"] == method]), "u正益": statistics([r for r in positive if r["method"] == method])} for method in sorted({r["method"] for r in no_u + positive})},
              "No-u全49玉": no_u, "走査範囲": scopes, "入力SHA256前後一致": True, "入力SHA256": inputs,
              "固定155前後一致": code_before == code_after == code_expected, "固定155群SHA256": hashlib.sha256(json.dumps(code_before, sort_keys=True).encode()).hexdigest(),
              "診断コードSHA256": sha(Path(__file__)), "Raw/新日/売買再生/退出後価格評価/Source差の利益換算": 0,
              "限界": "元建値とActual建値の不一致を記述しただけでSourceの全退出基準依存や損失原因を立証しない。旧Source/金融/条件は変更0。98のATR追尾案とは別資料。"}
    output.write_text(json.dumps(report, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"成功": True, "No-u": len(no_u), "u正益": len(positive), "比較": report["取得時比較"], "通知": report["Source返済通知"], "JSON_SHA256": sha(output)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
