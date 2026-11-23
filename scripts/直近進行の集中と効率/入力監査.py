"""受け取った旧61特徴とSOURCEだけで、直近集中・効率を独立に監査する。"""

from copy import deepcopy
from fractions import Fraction
import json
import math


FIELDS = ("session", "index", "minutes", "start", "end", "confirm", "confirm_line", "publish", "missing", "open", "high", "low", "close")
SIDES = ("1", "-1")
METADATA = [
    {"id": "F62", "name": "直近一足集中率", "method": "P05", "family": "price", "scale": "m03"},
    {"id": "F63", "name": "直近方向効率", "method": "P05", "family": "price", "scale": "m03"},
    {"id": "F64", "name": "最大一足の方向", "method": "P05", "family": "price", "scale": "m03"},
]


# ----------------------------------------
def finite(value: object) -> bool:
    """保存数値の有限性を、boolを数値とみなさず判定する。

    引数: value(object)は保存値。
    返り値: boolは有限なint/floatだけ真。
    """
    return type(value) in (int, float) and math.isfinite(value)


def record(value: Fraction) -> dict:
    """独立有理数を分子分母と有限な表示値へ変換する。

    引数: value(Fraction)は正規化済みの有理数。
    返り値: dictはvalue/numerator/denominator。表示不能はValueError。
    """
    try:
        number = float(value)
    except OverflowError as exc:
        raise ValueError("独立直近値の表示範囲外") from exc
    if not math.isfinite(number):
        raise ValueError("独立直近値は有限表示が必要")
    return {"value": number, "numerator": value.numerator, "denominator": value.denominator}


def typed_equal(left: object, right: object) -> bool:
    """JSON型を含めてSOURCE投影の同値を比較する。

    引数: left/right(object)は保存JSONの構造。
    返り値: boolはkey順を除いて同じ型・値なら真。
    """
    return json.dumps(left, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=True) == json.dumps(right, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=True)


def source(row: object, session: str) -> dict:
    """一足の必須型・同場性を検査してSOURCE13へ投影する。

    引数: row(object)は元SOURCE、session(str)は判断場。
    返り値: dictは深いSOURCE13コピー。不正schemaはValueError。
    """
    if not isinstance(row, dict) or any(name not in row for name in FIELDS):
        raise ValueError("独立SOURCE13の項目不足")
    integer_fields = {"index": 0, "confirm_line": 0, "missing": 0}
    if row["session"] != session or type(row["minutes"]) is not int or row["minutes"] != 3:
        raise ValueError("独立SOURCEの場又は足幅型不正")
    if any(type(row[name]) is not int or row[name] < lower for name, lower in integer_fields.items()) or type(row["publish"]) is not bool:
        raise ValueError("独立SOURCEの番号・原行・公開型不正")
    if any(not finite(row[name]) for name in ("start", "end", "confirm")):
        raise ValueError("独立SOURCEの時計不正")
    return {name: deepcopy(row[name]) for name in FIELDS}


def progress(slot: dict, old: dict) -> dict:
    """旧局所帯履歴の六終値から、共通準備と精密診断を独立に作る。

    引数: slot(dict)は判断identity、old(dict)は既に監査された旧61特徴。
    返り値: dictはrecent_progress全診断。新入力.py・価格銀行・教師を呼ばない。
    """
    if not isinstance(old, dict) or type(old.get("ready")) is not bool or not isinstance(old.get("reason"), str) or not isinstance(old.get("vectors"), dict) or set(old["vectors"]) != set(SIDES):
        raise ValueError("独立元61特徴のschema不正")
    length = 61 if old["ready"] else 0
    if any(not isinstance(old["vectors"][side], list) or len(old["vectors"][side]) != length for side in SIDES):
        raise ValueError("独立元61特徴のvector長不正")
    result = {"n": 5, "old_ready": old["ready"], "old_reason": old["reason"], "valid": False,
        "reason": "" if old["ready"] else old["reason"], "sources": [], "deltas": [], "deltas_exact": [],
        "TV": None, "values": {side: [] for side in SIDES}, "exact": {side: [] for side in SIDES}, "largest": None}
    if old["ready"] is False:
        return result
    if not isinstance(slot, dict) or any(not isinstance(slot.get(name), str) or not slot[name] for name in ("session", "slot_id")):
        raise ValueError("独立判断identity不正")
    if any(not finite(slot.get(name)) for name in ("scheduled", "time")) or slot["time"] < slot["scheduled"] or type(slot.get("line")) is not int or slot["line"] <= 0:
        raise ValueError("独立判断時計不正")
    try:
        history = old["base"]["history"]
        reference = history["reference_sources"]
        reaction = history["reaction_sources"]
        current = old["base"]["base"]["sources"]["current"]
    except (KeyError, TypeError) as exc:
        raise ValueError("独立元61の履歴schemaなし") from exc
    if not isinstance(reference, list) or not isinstance(reaction, list):
        raise ValueError("独立元履歴のSOURCE配列不正")
    if not reference or len(reaction) != 5:
        result["reason"] = "直近六終値のSOURCE不足"
        return result
    bars = [source(row, slot["session"]) for row in [reference[-1], *reaction]]
    last = source(current, slot["session"])
    numbers = [row["index"] for row in bars]
    if len(set(numbers)) != 6:
        raise ValueError("独立直近SOURCEの番号重複")
    if not typed_equal(bars[-1], last):
        raise ValueError("独立直近最後SOURCEと旧currentの差")
    result["sources"] = bars
    # ----------------------------------------
    # schema停止と当時未準備を分け、古い足から最初に判明した理由を保存する。
    for bar in bars:
        key = bar["confirm"], bar["confirm_line"]
        if bar["end"] > slot["scheduled"] or key > (slot["time"], slot["line"]):
            result["reason"] = "直近六終値に当時未公開の足"
            return result
        if bar["publish"] is False or bar["missing"] or bar["end"] - bar["start"] != 180 or bar["confirm"] < bar["end"]:
            result["reason"] = "直近六終値に非公開・欠枠・不完全足"
            return result
        prices = [bar[name] for name in ("open", "high", "low", "close")]
        if any(not finite(price) or price <= 0 for price in prices):
            raise ValueError("独立可視足の価格不正")
        if bar["low"] > min(bar["open"], bar["close"]) or max(bar["open"], bar["close"]) > bar["high"] or bar["low"] > bar["high"]:
            raise ValueError("独立可視足のOHLC順序不正")
    for index in range(1, 6):
        left, right = bars[index-1], bars[index]
        if right["index"] - left["index"] != 1 or right["start"] != left["end"] or (right["confirm"], right["confirm_line"]) <= (left["confirm"], left["confirm_line"]):
            result["reason"] = "直近六終値の番号・終了・公開順不連続"
            return result
    # ----------------------------------------
    # 総変動は正負の移動量を別々に合算し、純進行は端点差で計算する。
    closes = tuple(Fraction(str(bar["close"])) for bar in bars)
    changes = tuple(closes[index] - closes[index-1] for index in range(1, 6))
    positive = sum((value for value in changes if value > 0), Fraction(0))
    negative = -sum((value for value in changes if value < 0), Fraction(0))
    total = positive + negative
    result["deltas_exact"] = [record(value) for value in changes]
    result["deltas"] = [item["value"] for item in result["deltas_exact"]]
    result["TV"] = record(total)
    if not total:
        result["reason"] = "直近五差分の総変動TVが0"
        return result
    top, bottom = max(changes), min(changes)
    peak = max(top, -bottom)
    direction = (1 if top > -bottom else -1 if top < -bottom else 0)
    extrema = []
    for position, value in enumerate(changes):
        if value != peak and value != -peak:
            continue
        a, b = bars[position], bars[position+1]
        extrema.append({"from_index": a["index"], "to_index": b["index"],
            "from_key": [a["confirm"], a["confirm_line"]], "to_key": [b["confirm"], b["confirm_line"]],
            "sign": 1 if value > 0 else -1 if value < 0 else 0})
    result["largest"] = {"absolute": record(peak), "max_delta": record(top), "min_delta": record(bottom),
        "direction": direction, "mixed_tie": len(set(item["sign"] for item in extrema)) > 1, "sources": extrema}
    for text in SIDES:
        side = int(text)
        exact_values = (peak / total, side * (closes[-1] - closes[0]) / total, Fraction(side * direction))
        result["exact"][text] = [record(value) for value in exact_values]
        result["values"][text] = [item["value"] for item in result["exact"][text]]
    result["valid"], result["reason"] = True, ""
    return result


def derive(slot: dict, old_feature61: dict) -> tuple:
    """同じ共通準備のB61/Q64と復元用の旧vectorを独立に再構成する。

    引数: slot(dict)は判断identity、old_feature61(dict)は旧I72から受け取る固定特徴。
    返り値: tuple[dict,dict]はpreparedB/preparedQ。引数を書き換えず外部入力を読まない。
    """
    state = progress(slot, old_feature61)
    baseline = deepcopy(old_feature61)
    baseline["control_vectors61"] = deepcopy(old_feature61["vectors"])
    baseline["recent_progress"] = state
    baseline["ready"] = old_feature61["ready"] and state["valid"]
    if not baseline["ready"]:
        baseline["reason"] = state["reason"]
        baseline["vectors"] = {side: [] for side in SIDES}
    additional = deepcopy(baseline)
    if baseline["ready"]:
        for side in SIDES:
            additional["vectors"][side].extend(state["values"][side])
    return baseline, additional


# ----------------------------------------
def fixture(closes: list | None = None) -> tuple:
    """市場と無関係なSOURCE/旧61を作る人工材料を用意する。

    引数: closes(list|None)は六終値、Noneなら同方向の単位進行。
    返り値: tuple[dict,dict]は判断と旧61特徴。原板・銀行・モデルは読まない。
    """
    prices = [100, 101, 102, 103, 104, 105] if closes is None else closes
    session = "2026-01-01_Day"
    rows = []
    for index in range(15):
        price = prices[max(0, index-9)]
        rows.append({"session": session, "index": index, "minutes": 3, "start": index*180, "end": (index+1)*180,
            "confirm": (index+1)*180+3, "confirm_line": 100+index, "publish": True, "missing": 0,
            "open": price, "high": price+1, "low": price-1, "close": price})
    current = rows[-1]
    slot = {"session": session, "slot_id": "人工73_0014", "scheduled": current["end"], "time": current["confirm"], "line": current["confirm_line"]}
    old = {"ready": True, "reason": "", "vectors": {side: [0.0]*61 for side in SIDES}, "atr": 20.0, "D": 20, "background_direction": 1,
        "base": {"history": {"reference_sources": deepcopy(rows[:10]), "reaction_sources": deepcopy(rows[10:])},
            "base": {"sources": {"current": deepcopy(current)}}}, "旧説明保存": ["人工", None, False]}
    return slot, old


def self_test() -> dict:
    """人工SOURCEの手計算と主入力との全返却比較を行う。

    引数: なし。
    返り値: dictは成功・テスト件数・比較件数。不一致時は例外。本物入力/fit/市場は0。
    """
    import importlib.util
    from pathlib import Path
    import sys
    path = Path(__file__).with_name("入力.py")
    spec = importlib.util.spec_from_file_location("独立入力73の人工時だけの主比較", path)
    main = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = main
    spec.loader.exec_module(main)
    checks, tests = 0, 0

    def compare(left: object, right: object, where: str = "root") -> None:
        """返却構造を型・key・全leafまで比較する人工専用検査を行う。

        引数: left/right(object)は独立/主の値、where(str)は比較位置。
        返り値: None。不一致はAssertionError、比較件数を加算する。
        """
        nonlocal checks
        checks += 1
        if type(left) is not type(right):
            raise AssertionError((where, "型", type(left), type(right)))
        if isinstance(left, dict):
            assert set(left) == set(right), (where, "key")
            for key in left:
                compare(left[key], right[key], where+"."+key)
        elif isinstance(left, (list, tuple)):
            assert len(left) == len(right), (where, "長さ")
            for index, (a, b) in enumerate(zip(left, right)):
                compare(a, b, where+"."+str(index))
        else:
            assert left == right or type(left) is float and math.isnan(left) and math.isnan(right), (where, left, right)

    def check(slot: dict, old: dict, expected_error: bool = False) -> tuple | None:
        """架空一例の同値・例外・非改変を確認する。

        引数: slot/old(dict)は架空入力、expected_error(bool)は入力不整合の期待。
        返り値: tuple|Noneは独立返却又は期待例外。主呼出しはこの人工内だけ。
        """
        nonlocal tests
        snapshot = deepcopy((slot, old))
        results = []
        for function in (derive, main.extend):
            try:
                results.append((None, function(slot, old)))
            except ValueError as exc:
                results.append((type(exc), None))
        compare((slot, old), snapshot, "引数非改変")
        if expected_error:
            assert results[0][0] is ValueError and results[1][0] is ValueError, results
        else:
            assert results[0][0] is None and results[1][0] is None, results
            compare(results[0][1], results[1][1])
        tests += 1
        return results[0][1]

    def mutate(name: str, value: object, position: int = -1, current: bool = True) -> tuple:
        """反応足へ一つの不正/境界を入れる人工材料を作る。

        引数: name(str)/value(object)は置換項目、position(int)は反応足位置、current(bool)は末足出典も同期するか。
        返り値: tuple[dict,dict]は変更した架空材料。
        """
        slot, old = fixture()
        old["base"]["history"]["reaction_sources"][position][name] = value
        if position == -1 and current:
            old["base"]["base"]["sources"]["current"][name] = value
        return slot, old

    slot, old = fixture()
    b, q = check(slot, old)
    assert q["vectors"]["1"][-3:] == [0.2, 1.0, 1.0]
    assert q["recent_progress"]["exact"]["1"][0] == {"value": 0.2, "numerator": 1, "denominator": 5}
    assert b["vectors"] == old["vectors"] and len(q["vectors"]["-1"]) == 64
    for prices in ([100,103,100,100,100,100], [100,102,103,102,103,103], [105,104,103,102,101,100], [100]*6, [100,100,100,100,100,105], [100,105,105,105,105,105], [100.1,100.2,100.3,100.1,100.2,100.1]):
        a, f = fixture(prices); check(a, f)
    tie = derive(*fixture([100,103,100,100,100,100]))[1]["recent_progress"]
    assert tie["values"]["1"] == [0.5,0.0,0.0] and tie["largest"]["mixed_tie"] is True and len(tie["largest"]["sources"]) == 2
    decimal = derive(*fixture([100.1,100.2,100.3,100.1,100.2,100.1]))[1]["recent_progress"]
    assert decimal["TV"] == {"value":0.6,"numerator":3,"denominator":5}
    assert decimal["exact"]["1"] == [{"value":1/3,"numerator":1,"denominator":3},{"value":0.0,"numerator":0,"denominator":1},{"value":-1.0,"numerator":-1,"denominator":1}]
    early = derive(*fixture([100,105,105,105,105,105]))[1]["recent_progress"]
    late = derive(*fixture([100,100,100,100,100,105]))[1]["recent_progress"]
    assert early["values"] == late["values"] and early["largest"]["sources"] != late["largest"]["sources"]
    shifted, reflected = fixture(), fixture()
    for material, mirror in ((shifted, False), (reflected, True)):
        a, f = material
        all_rows = [*f["base"]["history"]["reference_sources"], *f["base"]["history"]["reaction_sources"], f["base"]["base"]["sources"]["current"]]
        for bar in all_rows:
            prices = {key:bar[key] for key in ("open","high","low","close")}
            for key in prices:
                bar[key] = 1000-prices[{"high":"low","low":"high"}.get(key,key)] if mirror else prices[key]+50
        _, actual = check(a, f)
        for side in SIDES:
            expected_side = str(-int(side)) if mirror else side
            assert actual["recent_progress"]["values"][side] == q["recent_progress"]["values"][expected_side]
    cases = [("missing",1), ("publish",False), ("start",2521), ("confirm",9999), ("end",9999)]
    for name,value in cases:
        a,f=mutate(name,value); result=check(a,f)
        assert result[0]["ready"] is False and result[0]["vectors"] == {"1":[],"-1":[]}
    a,f=fixture();a["line"]-=1;check(a,f)
    a,f=fixture();f["base"]["history"]["reaction_sources"].pop();check(a,f)
    a,f=fixture();f["base"]["history"]["reference_sources"]=[];check(a,f)
    a,f=fixture();f.update(ready=False,reason="人工旧準備不足",vectors={"1":[],"-1":[]},base=None);check({},f)
    for name,value in (("index",13),("confirm_line",True),("minutes",15),("confirm",float("nan")),("close",float("nan")),("high",1),("session","別場")):
        check(*mutate(name,value),expected_error=True)
    a,f=mutate("close",106,current=False);check(a,f,expected_error=True)
    a,f=fixture();a["time"]=a["scheduled"]-1;check(a,f,expected_error=True)
    a,f=fixture();a["line"]=True;check(a,f,expected_error=True)
    a,f=fixture();f["vectors"]["1"]=[];check(a,f,expected_error=True)
    a,f=fixture();f["base"]["history"]["reaction_sources"][0]["index"]+=1;check(a,f,expected_error=True)
    a,f=fixture();bars=[f["base"]["history"]["reference_sources"][-1],*f["base"]["history"]["reaction_sources"]]
    for index,bar in enumerate(bars):bar.update(confirm=4000,confirm_line=100+index)
    f["base"]["base"]["sources"]["current"]=deepcopy(bars[-1]);a.update(time=4000,line=105);check(a,f)
    bars[-1]["confirm_line"]=104;f["base"]["base"]["sources"]["current"]=deepcopy(bars[-1]);check(a,f)
    a,f=fixture();left=f["base"]["history"]["reference_sources"][-1]
    for field in ("start","end","confirm"):left[field]-=3
    check(a,f)
    a,f=fixture();a.update(side=-1,role="反転",label={"outcome":"250"},operation={"holding":True});compare(derive(a,f),derive(slot,old),"未使用属性不変");tests+=1
    return {"成功":True,"人工成功":True,"テスト件数":tests,"照合項目数":checks,"不一致数":0,"不一致":[],
        "本物入力読取":False,"新入力の正式derive呼出":False,"fit":0,"市場再生":False}


if __name__ == "__main__":
    print(json.dumps(self_test(), ensure_ascii=False, allow_nan=False))
