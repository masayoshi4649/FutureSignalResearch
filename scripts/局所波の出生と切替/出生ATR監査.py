"""SOURCEから出生ATRを別経路で求め、固定49再用の参照行を監査する。

正式derive_atrは出生ATR.pyやNumericBankをimport・呼出ししない。
架空入力を使うself_testだけが比較対象の出生ATR.pyを読み込む。
"""

from copy import deepcopy
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import random


FIELDS = ("session", "index", "minutes", "start", "end", "confirm", "confirm_line",
          "publish", "missing", "open", "high", "low", "close")
REASONS = ("出生価格足未準備", "出生ATR未準備", "出生ATR非正", "出生ATR準備済み")


def _finite(value: object) -> bool:
    """保存JSONの有限数値を真偽値と区別する。

    引数: value(object)は任意の入力値。
    返り値: boolは組込みint/floatの有限値なら真。
    """
    return type(value) in (int, float) and math.isfinite(value)


def _text(value: object, allow_nan: bool = False) -> str:
    """独立指紋用の固定JSONを作る。

    引数: value(object)はJSON値、allow_nan(bool)は源価格の非有限値を許すか。
    返り値: strはJSON型を保つ文字列。bytes等を黙って変換しない。
    """
    return json.dumps(value, ensure_ascii=False, allow_nan=allow_nan, separators=(",", ":"), sort_keys=True)


def _digest(source: dict) -> str:
    """SOURCE13の列選択とSHA256を独立に求める。

    引数: source(dict)は場名を付けた価格足。
    返り値: strは非有限源価格も含む13項目の指紋。
    """
    return hashlib.sha256(_text({name: source[name] for name in FIELDS}, True).encode("utf-8")).hexdigest()


def _frame(frame: dict) -> None:
    """順序計算に必要なSOURCE型を検査し、価格不良はresetへ残す。

    引数: frame(dict)は3分SOURCE12。
    返り値: None。比較不能なschemaはValueError。
    """
    if not isinstance(frame, dict) or any(name not in frame for name in FIELDS[1:]):
        raise ValueError("監査SOURCE12不足")
    if type(frame["index"]) is not int or frame["index"] < 0:
        raise ValueError("監査足番号不正")
    if frame["minutes"] != 3 or type(frame["minutes"]) is bool or type(frame["publish"]) is not bool:
        raise ValueError("監査幅又は公開旗不正")
    if type(frame["missing"]) is not int or frame["missing"] < 0:
        raise ValueError("監査欠枠数不正")
    if not _finite(frame["start"]) or not _finite(frame["end"]) or frame["end"] <= frame["start"]:
        raise ValueError("監査開始終了不正")
    if frame["publish"] and (not _finite(frame["confirm"]) or type(frame["confirm_line"]) is not int
                              or frame["confirm_line"] < 0):
        raise ValueError("監査公開key不正")


def _ohlc(frame: dict) -> bool:
    """有限正OHLCと価格範囲の包含を別条件で調べる。

    引数: frame(dict)はSOURCE価格足。
    返り値: boolは銀行へ投入できるOHLCなら真。
    """
    if any(not _finite(frame[name]) or frame[name] <= 0 for name in ("open", "high", "low", "close")):
        return False
    return (frame["high"] >= frame["low"] and frame["low"] <= frame["open"] <= frame["high"]
            and frame["low"] <= frame["close"] <= frame["high"])


def derive_atr(sessions: list[dict]) -> dict:
    """固定銀行を使わずTR列・Wilder漸化式・resetから全参照行を求める。

    引数: sessions(list[dict])は元順session/contract/begin/end/frames3の配列。
    返り値: dictは出生ATR.buildと同schemaの場別参照。入力ファイルを開かない。
    """
    if not isinstance(sessions, list):
        raise ValueError("監査sessionsは配列")
    output, seen, previous_end, contract = {}, set(), None, None
    previous_close, tr_seed, smooth, n = None, [], None, 0
    for item in sessions:
        if not isinstance(item, dict):
            raise ValueError("監査場は辞書")
        name, begin, end = item.get("session"), item.get("begin"), item.get("end")
        new_contract, frames = item.get("contract"), item.get("frames3")
        if not isinstance(name, str) or not name or name in seen:
            raise ValueError("監査場名不正又は重複")
        if not _finite(begin) or not _finite(end) or end <= begin or previous_end is not None and begin < previous_end:
            raise ValueError("監査場区間又は順序不正")
        if not isinstance(new_contract, tuple) or not new_contract or any(not isinstance(c, str) for c in new_contract):
            raise ValueError("監査限月不正")
        if not isinstance(frames, list):
            raise ValueError("監査frames3は配列")
        seen.add(name)
        changed = contract is not None and new_contract != contract
        if changed:
            previous_close, tr_seed, smooth, n = None, [], None, 0
        contract = new_contract
        clear_count = int(changed)
        source_before, public_before, rows, signatures = None, None, [], []
        for i, frame in enumerate(frames):
            _frame(frame)
            if "session" in frame and frame["session"] != name:
                raise ValueError("監査SOURCE場名差")
            full = {"session": name, **{k: frame[k] for k in FIELDS[1:]}}
            signature = _digest(full)
            signatures.append(signature)
            if source_before is not None and frame["index"] <= source_before["index"]:
                raise ValueError("監査番号重複又は後退")
            if frame["publish"]:
                public_now = (frame["confirm"], frame["confirm_line"])
                if public_before is not None and not public_before < public_now:
                    raise ValueError("監査公開key非strict")
                public_before = public_now
            flags = []
            if changed and i == 0:
                flags.append("限月変更")
            sequential = (frame["index"] == 0 if source_before is None else
                          frame["index"] == source_before["index"] + 1 and frame["start"] == source_before["end"])
            if not sequential:
                flags.append("足番号又は終了時刻の欠枠")
            grid = frame["start"] == begin + frame["index"] * 180
            if not grid:
                flags.append("場内時刻格子不整合")
            if not frame["publish"]:
                flags.append("非公開足")
            if frame["missing"] != 0:
                flags.append("欠枠")
            whole = frame["end"] - frame["start"] == 180
            if not whole:
                flags.append("部分幅")
            prices = _ohlc(frame)
            if not prices:
                flags.append("OHLC不正")
            late = not frame["publish"] or frame["confirm"] >= frame["end"]
            if not late:
                flags.append("足終了前公開")
            inside = frame["start"] >= begin and frame["end"] <= end
            if not inside:
                flags.append("場外足")
            if any(flag != "限月変更" for flag in flags):
                previous_close, tr_seed, smooth, n = None, [], None, 0
                clear_count += 1
            valid = bool(frame["publish"] and frame["missing"] == 0 and whole and prices and late and grid and inside)
            if valid:
                high, low = frame["high"], frame["low"]
                tr = high - low if previous_close is None else max(high, previous_close) - min(low, previous_close)
                n += 1
                if smooth is None:
                    tr_seed.append(tr)
                    if n == 14:
                        smooth = sum(tr_seed) / 14
                else:
                    smooth = (smooth * 13 + tr) / 14
                atr, count = smooth, n
                previous_close = frame["close"]
            else:
                atr, count = None, 0
            if atr is not None and not _finite(atr):
                raise ValueError("監査ATRが非有限")
            ready = bool(valid and atr is not None and atr > 0)
            reason = REASONS[0] if not valid else REASONS[1] if atr is None else REASONS[2] if atr <= 0 else REASONS[3]
            row = {k: deepcopy(full[k]) for k in FIELDS[:9]}
            row["confirm"] = frame["confirm"] if _finite(frame["confirm"]) else None
            row["confirm_line"] = frame["confirm_line"] if type(frame["confirm_line"]) is int else None
            row.update(source_sha256=signature, atr=atr, valid=valid, numeric_count=count,
                       reset_reasons=flags, ready=ready, reason=reason)
            rows.append(row)
            source_before = frame
        full_count = int((end - begin) // 180)
        tail_missing = max(0, full_count - rows[-1]["index"] - 1) if rows else full_count
        if tail_missing:
            previous_close, tr_seed, smooth, n = None, [], None, 0
            clear_count += 1
        output[name] = {"session": name, "contract": list(contract), "begin": begin, "end": end, "rows": rows,
                        "quality": {"minutes": 3, "rows": len(rows), "valid_rows": sum(row["valid"] for row in rows),
                                    "clear_count": clear_count, "tail_missing": tail_missing},
                        "source_sha256": hashlib.sha256(_text(signatures).encode("utf-8")).hexdigest()}
        previous_end = end
    _text(output)
    return output


# ----------------------------------------
def self_test() -> dict:
    """架空系列だけで別算術・reset理由・型・鏡像・未来suffixを比較する。

    引数: なし。
    返り値: dictは人工成功/テスト件数/照合項目数/不一致数。正式入力を開かない。
    """
    spec = importlib.util.spec_from_file_location("出生ATR監査_人工対象", Path(__file__).with_name("出生ATR.py"))
    target = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(target)
    rng, checks, groups = random.Random(76), 0, 0

    def compare(actual: object, expected: object, path: str = "根") -> None:
        """全返却項目をJSON型と値まで再帰比較する。

        引数: actual/expected(object)は比較値、path(str)は人工差の位置。
        返り値: None。差があればAssertionError。
        """
        nonlocal checks
        checks += 1
        assert type(actual) is type(expected), (path, type(actual), type(expected))
        if isinstance(actual, dict):
            assert set(actual) == set(expected), path
            for name in actual:
                compare(actual[name], expected[name], path + "." + name)
        elif isinstance(actual, list):
            assert len(actual) == len(expected), path
            for index, (a, b) in enumerate(zip(actual, expected)):
                compare(a, b, path + "." + str(index))
        else:
            assert actual == expected, (path, actual, expected)

    def scene(name: str, begin: float, count: int, code: str = "A") -> dict:
        """四分の一刻みの架空OHLCを作る。

        引数: name(str)/begin(float)/count(int)/code(str)は人工識別と区間。
        返り値: dictは固定入力と無関係な場。
        """
        frames, close = [], 100.0
        for index in range(count):
            opening = close
            close += rng.randint(-8, 8) / 4
            frames.append({"index": index, "minutes": 3, "start": begin + index * 180,
                           "end": begin + (index + 1) * 180, "confirm": begin + (index + 1) * 180 + index % 3,
                           "confirm_line": index + 1, "publish": True, "missing": 0, "open": opening,
                           "high": max(opening, close) + rng.randint(0, 8) / 4,
                           "low": min(opening, close) - rng.randint(0, 8) / 4, "close": close})
        return {"session": name, "contract": (code,), "begin": begin, "end": begin + max(1, count) * 180,
                "frames3": frames}

    for case in range(24):
        sessions = [scene("a", 0, 28), scene("b", 10000, 21), scene("c", 20000, 17, "B" if case % 2 else "A")]
        if case % 8 == 1:
            del sessions[0]["frames3"][16]
        elif case % 8 == 2:
            sessions[0]["frames3"][16]["publish"] = False
        elif case % 8 == 3:
            sessions[0]["frames3"][16]["missing"] = 1
        elif case % 8 == 4:
            sessions[0]["frames3"][16]["close"] = float("nan")
        elif case % 8 == 5:
            sessions[0]["end"] += 180
        elif case % 8 == 6:
            sessions[0]["frames3"][16]["end"] -= 1
        elif case % 8 == 7:
            sessions[0]["frames3"][16]["start"] += 1
        compare(derive_atr(sessions), target.build(sessions))
        mirrored = deepcopy(sessions)
        for item in mirrored:
            for frame in item["frames3"]:
                old = dict(frame)
                for name in ("open", "close"):
                    frame[name] = 400 - old[name]
                frame["high"], frame["low"] = 400 - old["low"], 400 - old["high"]
        observed, mirror = derive_atr(sessions), derive_atr(mirrored)
        for name in observed:
            compare([r["atr"] for r in observed[name]["rows"]], [r["atr"] for r in mirror[name]["rows"]])
        groups += 1

    sample = scene("可視", 0, 20)
    original = target.build([sample])["可視"]
    suffix = deepcopy(sample)
    for frame in suffix["frames3"][15:]:
        frame.update(open=500.0, high=510.0, low=490.0, close=500.0)
    changed = derive_atr([suffix])["可視"]
    compare(target.visible_rows(original, 2700, 2702, 15), target.visible_rows(changed, 2700, 2702, 15))
    compare(len(target.visible_rows(original, 2700, 2702, 14)), 14)
    translated = deepcopy(sample)
    for frame in translated["frames3"]:
        for field in ("open", "high", "low", "close"):
            frame[field] += 200
    compare([r["atr"] for r in derive_atr([sample])["可視"]["rows"]],
            [r["atr"] for r in derive_atr([translated])["可視"]["rows"]])
    groups += 1

    sample["frames3"][3].update(publish=False, confirm=float("nan"), confirm_line=None)
    sample["frames3"][4]["open"] = None
    compare(derive_atr([sample]), target.build([sample]))
    compare(derive_atr([]), {})
    groups += 1

    def reject_both(sessions: list[dict]) -> None:
        """不正な架空schemaを両経路が拒否することを確かめる。

        引数: sessions(list[dict])は一箇所を壊した人工入力。
        返り値: None。いずれかが受理したらAssertionError。
        """
        nonlocal checks
        for function in (derive_atr, target.build):
            checks += 1
            try:
                function(sessions)
            except (ValueError, TypeError, KeyError):
                continue
            raise AssertionError("不正schemaを受理")

    invalid_base = scene("型", 0, 2)
    for field, value in (("index", True), ("minutes", True), ("publish", 1), ("missing", True),
                         ("confirm", True), ("end", -1), ("close", b"100")):
        invalid = deepcopy(invalid_base)
        invalid["frames3"][0][field] = value
        reject_both([invalid])
    reject_both([invalid_base, invalid_base])
    reject_both([{**invalid_base, "contract": ["A"]}])
    groups += 1
    return {"成功": True, "人工成功": True, "テスト件数": groups, "照合項目数": checks, "不一致数": 0,
            "不一致": [], "本物入力": False, "正式deriveの固定銀行呼出し": False}


if __name__ == "__main__":
    print(json.dumps(self_test(), ensure_ascii=False, allow_nan=False))
