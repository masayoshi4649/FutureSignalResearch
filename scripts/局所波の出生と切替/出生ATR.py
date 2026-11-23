"""固定49の3分銀行だけを再用し、出生足へ結合するATR参照を作る。

入力ファイル、原板、気配、教師、損益を開かない。SOURCE価格全文は保存せず、
型と非有限値も含むSOURCE13の指紋へ結ぶ。全銀行の指紋は外層で扱う。
"""

from copy import deepcopy
import hashlib
import importlib.util
import json
import math
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
FIXED_PATH = ROOT / "scripts/定時帯反応/入口.py"
FIXED_SHA256 = "f42aea5cbb7d5f46d62dff7fd7769e5328c9951c213aaeccb9a912a6f67bd373"
SOURCE_FIELDS = ("session", "index", "minutes", "start", "end", "confirm", "confirm_line",
                 "publish", "missing", "open", "high", "low", "close")
CLOCK_FIELDS = SOURCE_FIELDS[:9]
REASONS = ("出生価格足未準備", "出生ATR未準備", "出生ATR非正", "出生ATR準備済み")


def finite(value: object) -> bool:
    """真偽値を除く有限数値を判定する。

    引数: value(object)は任意の保存値。
    返り値: boolは組込みint又はfloatの有限値なら真。
    """
    return type(value) in (int, float) and math.isfinite(value)


def canonical(value: object, allow_nan: bool = False) -> str:
    """指紋用の固定JSONを作り、任意のreprへ変換しない。

    引数: value(object)はJSON値、allow_nan(bool)は源価格のNaN/Infinityを許すか。
    返り値: strはUTF-8化前の固定JSON。bytes等はTypeErrorとなる。
    """
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=allow_nan)


def source_sha256(source: dict) -> str:
    """SOURCE13全文の値とJSON型を価格不良も含めて指紋化する。

    引数: source(dict)はsessionとSOURCE12を含む元足。
    返り値: strはcanonical allow_nan=TrueのUTF-8 SHA256。余分な数値列は含めない。
    """
    if not isinstance(source, dict) or any(name not in source for name in SOURCE_FIELDS):
        raise ValueError("出生ATRのSOURCE13不足")
    if not isinstance(source["session"], str) or not source["session"]:
        raise ValueError("出生ATRのSOURCE場名不正")
    projected = {name: source[name] for name in SOURCE_FIELDS}
    return hashlib.sha256(canonical(projected, True).encode("utf-8")).hexdigest()


def _fixed_module():
    """停止SHAの49純モジュールだけを固有名で読み込む。

    引数: なし。
    返り値: ModuleTypeはNumericBankを公開する固定49入口。
    """
    if hashlib.sha256(FIXED_PATH.read_bytes()).hexdigest() != FIXED_SHA256:
        raise ValueError("固定49入口のSHA256不一致")
    spec = importlib.util.spec_from_file_location("出生ATR_固定49", FIXED_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if tuple(module.SOURCE_FIELDS) != SOURCE_FIELDS[1:]:
        raise ValueError("固定49のSOURCE12不一致")
    return module


def _sessions(sessions: list[dict]) -> None:
    """元順の場識別・区間・限月を銀行計算前に検査する。

    引数: sessions(list[dict])はC49.inputs由来の場配列又は人工配列。
    返り値: None。重複・後退・型不正はValueError。
    """
    if not isinstance(sessions, list):
        raise ValueError("出生ATRのsessionsは配列")
    seen, previous_end = set(), None
    for item in sessions:
        if not isinstance(item, dict):
            raise ValueError("出生ATRの場は辞書")
        name, begin, end = item.get("session"), item.get("begin"), item.get("end")
        contract, frames = item.get("contract"), item.get("frames3")
        if not isinstance(name, str) or not name or name in seen:
            raise ValueError("出生ATRの場名不正又は重複")
        if not finite(begin) or not finite(end) or end <= begin or previous_end is not None and begin < previous_end:
            raise ValueError("出生ATRの場区間又は元順不正")
        if not isinstance(contract, tuple) or not contract or not all(isinstance(code, str) for code in contract):
            raise ValueError("出生ATRの限月は空でない文字列tuple")
        if not isinstance(frames, list):
            raise ValueError("出生ATRのframes3は配列")
        seen.add(name)
        previous_end = end


def _pack(row: dict, signature: str) -> dict:
    """49数値行を価格全文なしのJSON安全な参照行へ縮約する。

    引数: row(dict)は49数値行、signature(str)は元SOURCE13のSHA256。
    返り値: dictは時計・源指紋・ATR・準備状態・reset根拠。
    """
    result = {name: deepcopy(row[name]) for name in CLOCK_FIELDS}
    result["confirm"] = row["confirm"] if finite(row["confirm"]) else None
    result["confirm_line"] = row["confirm_line"] if type(row["confirm_line"]) is int else None
    atr, valid = row["atr"], row["valid"]
    if atr is not None and not finite(atr):
        raise ValueError("固定49が非有限ATRを生成")
    ready = bool(valid and atr is not None and atr > 0)
    reason = REASONS[0] if not valid else REASONS[1] if atr is None else REASONS[2] if atr <= 0 else REASONS[3]
    result.update(source_sha256=signature, atr=atr, valid=valid, numeric_count=row["numeric_count"],
                  reset_reasons=deepcopy(row["reset_reasons"]), ready=ready, reason=reason)
    return result


def build(sessions: list[dict]) -> dict:
    """元66場順に固定3分銀行だけを動かし、場別出生ATR参照を返す。

    引数: sessions(list[dict])はsession/contract/begin/end/frames3を持つ元順入力。
    返り値: dictはsessionからrows/quality/源指紋列指紋への写像。人工では場数を固定しない。
    """
    _sessions(sessions)
    module = _fixed_module()
    bank, output = module.NumericBank(3), {}
    for item in sessions:
        name = item["session"]
        signatures = []
        for frame in item["frames3"]:
            if "session" in frame and frame["session"] != name:
                raise ValueError("出生ATRの元SOURCE場名差")
            signatures.append(source_sha256({**frame, "session": name}))
        rows, quality = bank.build(item["frames3"], name, item["contract"], item["begin"], item["end"])
        output[name] = {"session": name, "contract": list(item["contract"]), "begin": item["begin"], "end": item["end"],
                        "rows": [_pack(row, signature) for row, signature in zip(rows, signatures)],
                        "quality": quality,
                        "source_sha256": hashlib.sha256(canonical(signatures).encode("utf-8")).hexdigest()}
    if hashlib.sha256(FIXED_PATH.read_bytes()).hexdigest() != FIXED_SHA256:
        raise ValueError("出生ATR生成中に固定49入口が変更")
    canonical(output)
    return output


# ----------------------------------------
def bind(row: dict, source: dict) -> None:
    """縮約行を元SOURCE全文・時計へ厳密結合する。

    引数: row(dict)は出生ATR参照、source(dict)はSOURCE13の元足。
    返り値: None。価格・JSON型・index/end/keyの差はValueError。
    """
    if row.get("source_sha256") != source_sha256(source):
        raise ValueError("出生ATRとSOURCE13全文指紋が不一致")
    for name in CLOCK_FIELDS:
        expected = source[name]
        if name == "confirm" and not finite(expected):
            expected = None
        if name == "confirm_line" and type(expected) is not int:
            expected = None
        if canonical(row.get(name)) != canonical(expected):
            raise ValueError("出生ATRとSOURCE時計が不一致:" + name)


def visible_rows(package: dict, scheduled: float, time: float, line: int) -> list[dict]:
    """将来行を除外し、当時位置が分かるNP行も未準備のまま返す。

    引数: package(dict)はbuildの一場、scheduled/time(float)とline(int)は判断時計。
    返り値: list[dict]はend<=予定かつ公開位置key<=実判断の行。公開位置不明を補完しない。
    """
    if not finite(scheduled) or not finite(time) or time < scheduled or type(line) is not int or line < 0:
        raise ValueError("出生ATRの可視判断時計不正")
    rows = []
    for row in package["rows"]:
        if row["end"] > scheduled:
            continue
        if not finite(row["confirm"]) or type(row["confirm_line"]) is not int or row["confirm_line"] < 0:
            continue
        if (row["confirm"], row["confirm_line"]) <= (time, line):
            rows.append(deepcopy(row))
    return rows


# ----------------------------------------
def self_test() -> dict:
    """架空足だけで手計算・carry・reset・公開・指紋境界を検査する。

    引数: なし。
    返り値: dictは成功/テスト件数/照合項目数/不一致数。実入力と市場は開かない。
    """
    checks, groups = 0, 0

    def equal(actual: object, expected: object) -> None:
        """人工期待値を値とJSON型まで比較する。

        引数: actual/expected(object)は観測と独立に指定した期待。
        返り値: None。差があればAssertionError。
        """
        nonlocal checks
        checks += 1
        assert canonical(actual) == canonical(expected), (actual, expected)

    def rejects(function, *args) -> None:
        """不正入力が停止することを確認する。

        引数: function(Callable)とargs(tuple)は架空呼出し。
        返り値: None。例外がなければAssertionError。
        """
        nonlocal checks
        checks += 1
        try:
            function(*args)
        except (ValueError, TypeError, KeyError):
            return
        raise AssertionError("不正入力を受理")

    def scene(name: str, begin: float, count: int, contract: str = "A") -> dict:
        """一定2pt TRの架空場を作る。

        引数: name(str)/begin(float)/count(int)/contract(str)は人工識別と区間。
        返り値: dictは価格本文に依存しない銀行入力。
        """
        frames = [{"index": i, "minutes": 3, "start": begin + 180 * i, "end": begin + 180 * (i + 1),
                   "confirm": begin + 180 * (i + 1), "confirm_line": i + 1, "publish": True, "missing": 0,
                   "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0} for i in range(count)]
        return {"session": name, "contract": (contract,), "begin": begin, "end": begin + max(1, count) * 180,
                "frames3": frames}

    item = scene("種", 0, 15)
    item["frames3"][-1].update(high=105.0, low=95.0)
    before = canonical(item)
    rows = build([item])["種"]["rows"]
    equal([row["atr"] for row in rows[:13]], [None] * 13)
    equal(rows[13]["atr"], 2.0)
    equal(rows[14]["atr"], (13 * 2.0 + 10.0) / 14)
    equal(canonical(item), before)
    equal(rows[13]["ready"], True)
    groups += 1

    first, second = scene("前", 0, 13), scene("後", 10000, 2)
    pair = build([first, second])
    equal(pair["後"]["rows"][0]["atr"], 2.0)
    equal(pair["後"]["rows"][0]["numeric_count"], 14)
    second["frames3"][0].update(open=110.0, high=111.0, low=109.0, close=110.0)
    jumped = build([first, second])
    equal(jumped["後"]["rows"][0]["atr"], (13 * 2.0 + 11.0) / 14)
    second["contract"] = ("B",)
    rolled = build([first, second])
    equal(rolled["後"]["rows"][0]["atr"], None)
    equal(rolled["後"]["rows"][0]["reset_reasons"], ["限月変更"])
    groups += 1

    gap = scene("欠足", 0, 17)
    del gap["frames3"][14]
    gr = build([gap])["欠足"]["rows"]
    equal(gr[14]["numeric_count"], 1)
    equal(gr[14]["valid"], True)
    equal(gr[14]["reset_reasons"], ["足番号又は終了時刻の欠枠"])
    np = scene("NP", 0, 17)
    np["frames3"][14]["publish"] = False
    nr = build([np])["NP"]["rows"]
    equal(nr[14]["atr"], None)
    equal(nr[14]["numeric_count"], 0)
    equal(nr[15]["numeric_count"], 1)
    equal(nr[14]["reason"], REASONS[0])
    groups += 1

    tail = scene("尾欠", 0, 13)
    tail["end"] += 180
    nxt = scene("尾後", 10000, 1)
    result = build([tail, nxt])
    equal(result["尾欠"]["quality"]["tail_missing"], 1)
    equal(result["尾後"]["rows"][0]["numeric_count"], 1)
    flat = scene("平坦", 0, 14)
    for frame in flat["frames3"]:
        frame.update(open=100, high=100, low=100, close=100)
    fr = build([flat])["平坦"]["rows"][-1]
    equal(fr["atr"], 0.0)
    equal(fr["ready"], False)
    equal(fr["reason"], REASONS[2])
    groups += 1

    known = scene("公開", 0, 15)
    package = build([known])["公開"]
    equal(len(visible_rows(package, 2520, 2520, 13)), 13)
    equal(len(visible_rows(package, 2520, 2520, 14)), 14)
    equal(len(visible_rows(package, 2519, 2520, 14)), 13)
    rejects(visible_rows, package, 2520, 2520, True)
    source = {"session": "公開", **known["frames3"][13]}
    bind(package["rows"][13], source)
    changed = deepcopy(source)
    changed["close"] = 100
    rejects(bind, package["rows"][13], changed)
    changed["close"] = b"100"
    rejects(source_sha256, changed)
    groups += 1

    future = deepcopy(known)
    future["frames3"][-1].update(open=200.0, high=205.0, low=195.0, close=200.0)
    future_package = build([future])["公開"]
    equal(visible_rows(package, 2520, 2520, 14), visible_rows(future_package, 2520, 2520, 14))
    equal(build([known])["公開"]["rows"][:14], build([{**known, "frames3": known["frames3"][:14]}])["公開"]["rows"])
    bad = scene("不良", 0, 2)
    bad["frames3"][0]["close"] = float("nan")
    bad["frames3"][1].update(publish=False, confirm=float("nan"), confirm_line=None)
    br = build([bad])["不良"]
    equal(br["rows"][0]["atr"], None)
    equal(br["rows"][1]["confirm"], None)
    equal(len(visible_rows(br, 360, 360, 2)), 1)
    canonical(br)
    groups += 1

    invalid = scene("不正", 0, 2)
    duplicate = deepcopy(invalid)
    duplicate["frames3"][1]["index"] = 0
    rejects(build, [duplicate])
    duplicate = deepcopy(invalid)
    duplicate["frames3"][1].update(confirm=180, confirm_line=1)
    rejects(build, [duplicate])
    rejects(build, [invalid, invalid])
    rejects(build, [{**invalid, "contract": ["A"]}])
    equal(build([]), {})
    groups += 1
    return {"成功": True, "テスト件数": groups, "照合項目数": checks, "不一致数": 0,
            "固定49コードSHA256": FIXED_SHA256, "本物入力": False, "新15分計算": False}


if __name__ == "__main__":
    print(json.dumps(self_test(), ensure_ascii=False, allow_nan=False))
