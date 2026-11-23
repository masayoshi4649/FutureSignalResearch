"""同じ価格段階の観測量と進行を、過去同時刻基準で別々に追加する。"""

from collections import Counter, defaultdict
from copy import deepcopy
from fractions import Fraction
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import sys


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent


def load(path: Path, name: str):
    """固定特徴を固有の名前空間で読む。

    引数: path(Path)はコード、name(str)は読込名。
    返り値: ModuleTypeは読取結果。旧大域値を変更しない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


OLD = load(HERE.parent / "局面強弱の複合確認/特徴.py", "量価格の固定63特徴")
I49 = OLD.I49
SOURCE = ("session", "index", "minutes", "start", "end", "confirm", "confirm_line",
    "publish", "missing", "open", "high", "low", "close")
Q_FIELDS = ("観測差分量", "数量基準完全", "直前数量足数", "直前数量合計", "直前数量平均",
    "RVOL", "数量準備済", "最終採用数量時計", "最終採用価格時計", "最終採用原行", "数量不完全理由")
QUANTITY_FILE = ROOT / "work/OBV反転/00029/全指標.jsonl.gz"
CONTENT_SHA = "a8172b96c8435c1b38bff79bab95465dc5fdfe4db8d1a8378f059a315dfb7808"
INPUT_PINS = {
    "work/OBV反転/00029/全指標.jsonl.gz": "4cb6fa91799fe9d892475f955c3e701bc99f293505ebfe3903733f60838f8074",
    "study/00029_BB内復帰とOBV非追随/作業成果物.json": "2cffc703907cc7b0b8e7b32b498d8d673564759fca6f9abd731a456924fb7bb0",
    "study/00029_BB内復帰とOBV非追随/独立監査.json": "7267b30d7a741313df210e381046e8775d5ce995907852b8af148c742a37b2fb",
    "study/00029_BB内復帰とOBV非追随/状態独立確認.json": "79e63b50d7d06b5b78c9bf099445a51f0515e1926d918ba9dff7d574937cd2d9",
    "study/00029_BB内復帰とOBV非追随/入力台帳.json": "e7f3345e1d750b5d9f2027ee530d15d5293f567edb08939beed5154d8d45508f",
    "study/00028_基準線復帰と上位一目の方向/入力台帳.json": "680b831ee6bef1ec1cf49dc6283931f5b0ca9611f15f5c19d81af6e4738aaf9b",
}
FEATURES = deepcopy(OLD.FEATURES) + [
    {"id": "F55", "name": "対応b同時刻RVOL", "method": "V01", "family": "volume", "scale": "m03"},
    {"id": "F56", "name": "対応b同足進行対現在ATR", "method": "P05", "family": "price", "scale": "m03"},
    {"id": "F57", "name": "対応r同時刻RVOL", "method": "V01", "family": "volume", "scale": "m03"},
    {"id": "F58", "name": "対応r同足進行対現在ATR", "method": "P05", "family": "price", "scale": "m03"},
    {"id": "F59", "name": "対応b量価格ペア有効", "method": "V01", "family": "volume", "scale": "m03"},
    {"id": "F60", "name": "対応r量価格ペア有効", "method": "V01", "family": "volume", "scale": "m03"},
]
RULES = deepcopy(OLD.RULES)
RULES["量と価格進行"] = {
    "旧準備": "旧63全54と教師を保持。追加未知で除外しない",
    "量": "固定29共有3分観測差分量。旧14数量基準完全を再用、旧20足RVOLは不使用",
    "基準": "同DayNight/同限月/同3分index。当場開始前終了の直近10場を先に選び、公開完全q5場以上/正平均。欠測で窓延長しない",
    "休日": "祝日別層化なし。時間帯以外の量水準の比較可能性は保証しない",
    "対応": "旧F01をfloat32化し正ならT/非正ならRのb,rを投影。実roleとDI同値WAITは旧規約",
    "価格": "s*(イベント終値-直前隣接公開終値)/現在判断ATR。イベントATRではない",
    "未知": "量価格ペア未知なら両数値0/mask0。完全q0かつ正基準は既知0",
    "追加": "bRVOL,b進行,rRVOL,r進行,bペア旗,rペア旗。生の量増減だけでは売買を選ばない",
}


def strict_equal(a: object, b: object) -> bool:
    """JSONの型・値・配列順を厳密に比較する。

    引数: a/b(object)は比較値。
    返り値: boolは再帰的な同値。
    """
    if type(a) is not type(b):
        return False
    if isinstance(a, dict):
        return a.keys() == b.keys() and all(strict_equal(a[k], b[k]) for k in a)
    if isinstance(a, list):
        return len(a) == len(b) and all(strict_equal(x, y) for x, y in zip(a, b))
    return a == b


def source(row: dict) -> dict:
    """当試行のSOURCE13を複写する。

    引数: row(dict)は3分の出典付き行。
    返り値: dictは元の価格・時計のみ。
    """
    return {key: deepcopy(row[key]) for key in SOURCE}


def load_quantity(sessions: list[dict]) -> dict:
    """固定数量と成功証明を確認し、旧63価格出典へ一対一結合する。

    引数: sessions(list[dict])は固定49inputs形式の全66場。
    返り値: dictは場別のSOURCE13とquantity。原板・教師を読まない。
    """
    for name, expected in INPUT_PINS.items():
        if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != expected:
            raise ValueError("数量の固定出典が変更:" + name)
    for name in ("独立監査.json", "状態独立確認.json"):
        proof = json.loads((ROOT / "study/00029_BB内復帰とOBV非追随" / name).read_text(encoding="utf-8"))
        if not proof["全件一致"] or proof["不一致数"] != 0:
            raise ValueError("固定29の成功証明なし")
    expected = {(s["session"], r["index"]): source({"session": s["session"], **r}) for s in sessions for r in s["frames3"]}
    if len(expected) != sum(len(s["frames3"]) for s in sessions):
        raise ValueError("旧3分出典の重複")
    found, content = {}, hashlib.sha256()
    with gzip.open(QUANTITY_FILE, "rb") as stream:
        for raw in stream:
            content.update(raw)
            row = json.loads(raw)
            projected = {"session": row["場"], **{key: row[key] for key in SOURCE if key != "session"}}
            identity = projected["session"], projected["index"]
            if identity in found or identity not in expected or not strict_equal(projected, expected[identity]):
                raise ValueError("数量SOURCEと旧63の完全結合に差")
            quantity = row["数量参照"]
            if not isinstance(quantity, dict) or set(quantity) != set(Q_FIELDS):
                raise ValueError("旧数量Q11のschema差")
            found[identity] = {**projected, "quantity": deepcopy(quantity)}
    if content.hexdigest() != CONTENT_SHA or set(found) != set(expected):
        raise ValueError("数量展開指紋又は全3分集合に差")
    return {s["session"]: [found[s["session"], r["index"]] for r in s["frames3"]] for s in sessions}


def price_ok(row: dict) -> bool:
    """同場で公開された完全な3分価格足かを判定する。

    引数: row(dict)はSOURCE13。
    返り値: boolは価格と時計が完全なこと。
    """
    return bool(row["minutes"] == 3 and row["end"] - row["start"] == 180
        and row["publish"] is True and row["missing"] == 0 and I49.valid_ohlc(row)
        and row["confirm"] >= row["end"] and type(row["confirm_line"]) is int and row["confirm_line"] >= 0)


def quantity_reason(row: dict) -> str | None:
    """当足qの完全性と採用時計を検査する。

    引数: row(dict)はSOURCEとquantity。
    返り値: str|Noneは未成立理由、Noneは既知非負量。旧RVOL20準備は課さない。
    """
    if not price_ok(row):
        return "公開完全価格でない"
    q = row["quantity"]
    if q["数量基準完全"] is not True or not I49.finite(q["観測差分量"]) or q["観測差分量"] < 0:
        return "数量基準不完全又は不正"
    qt, pt, line = (q[k] for k in ("最終採用数量時計", "最終採用価格時計", "最終採用原行"))
    if (not I49.finite(qt) or not I49.finite(pt) or not row["start"] <= pt < row["end"]
            or not row["start"] <= qt <= pt or type(line) is not int or not 0 <= line < row["confirm_line"]
            or q["数量不完全理由"] != []):
        raise ValueError("完全数量の採用時計・原行・理由が不整合")
    return None


# ----------------------------------------
# 過去窓は同種の場単位で先に選ぶ。不完全足を飛ばして古い場へ延長しない。

def build_context(sessions: list[dict], quantity: dict) -> dict:
    """当場より前の固定窓から同時刻量基準を算術する。

    引数: sessions(list[dict])は時系列の場、quantity(dict)は場別SOURCE/Q11。
    返り値: dictは同時刻基準付き3分行。損益・教師・未来場を使わない。
    """
    history, result, seen = defaultdict(list), {}, set()
    previous_begin = None
    for session in sessions:
        name, contract = session["session"], tuple(session["contract"])
        begin, end = session["begin"], session["end"]
        kind = name.rsplit("_", 1)[-1]
        if (name in seen or kind not in ("Day", "Night") or len(contract) != 1 or begin >= end
                or previous_begin is not None and begin <= previous_begin):
            raise ValueError("場の重複・順序・限月が不正")
        seen.add(name)
        previous_begin = begin
        history_key = kind, contract
        window = [past for past in history[history_key] if past["end"] < begin][-10:]
        if any(past["end"] >= begin for past in history[history_key]):
            raise ValueError("同種過去場が開始時に未完了")
        rows, indexed, previous_index = [], {}, None
        for raw in quantity[name]:
            row = deepcopy(raw)
            if row["session"] != name or previous_index is not None and row["index"] <= previous_index:
                raise ValueError("数量足の場・順序が不正")
            previous_index = row["index"]
            if len(rows) >= len(session["frames3"]) or not strict_equal(source(row), source({"session": name, **session["frames3"][len(rows)]})):
                raise ValueError("文脈作成時の旧SOURCE差")
            reason = quantity_reason(row)
            samples = []
            for past in window:
                prior = past["rows"].get(row["index"])
                if prior is not None and prior["quantity_reason"] is None:
                    if prior["confirm"] >= begin:
                        raise ValueError("過去基準足が開始時に未公開")
                    samples.append({"session": prior["session"], "index": prior["index"],
                        "key": [prior["confirm"], prior["confirm_line"]], "q": prior["quantity"]["観測差分量"]})
            total = sum((Fraction(p["q"]) for p in samples), Fraction(0))
            mean = total / len(samples) if samples else None
            baseline_valid = bool(len(samples) >= 5 and mean > 0)
            ratio = Fraction(row["quantity"]["観測差分量"]) / mean if reason is None and baseline_valid else None
            row.update(quantity_reason=reason, baseline={"window_sessions": [p["session"] for p in window],
                "samples": samples, "count": len(samples), "mean": float(mean) if mean is not None else None,
                "sum_numerator": total.numerator, "sum_denominator": total.denominator,
                "valid": baseline_valid}, rvol=float(ratio) if ratio is not None else None)
            rows.append(row)
            indexed[row["index"]] = row
        if len(rows) != len(session["frames3"]):
            raise ValueError("数量価格の全足数差")
        result[name] = rows
        history[history_key].append({"session": name, "end": end, "rows": indexed})
    if set(quantity) != seen:
        raise ValueError("数量と場集合が不一致")
    return result


def branch_role(value: float) -> str:
    """保存木と同じfloat32のDI符号で対応経路を選ぶ。

    引数: value(float)は候補方向の旧F01。
    返り値: strはT又はR。実運用roleを変更しない。
    """
    return "T" if struct.unpack("f", struct.pack("f", value))[0] > 0 else "R"


def event_pair(reference: dict | None, slot: dict, indexed: dict, side: int, atr: float) -> dict:
    """保存されたイベントと直前公開足から量・価格ペアを作る。

    引数: reference(dict|None)はb/rのindex/key、slot(dict)は判断、indexed(dict)は同場文脈、
        side(int)は候補方向、atr(float)は現在の正ATR。
    返り値: dictは安全な出典と理由・数値。未知ペアは対応2値0。
    """
    empty = {"source": None, "previous_source": None, "quantity": None, "baseline": None,
        "rvol": None, "price_delta": None, "progress": None, "valid": False,
        "values": [0.0, 0.0], "reason": "段階なし"}
    if reference is None:
        return empty
    row = indexed.get(reference["index"])
    limit = slot["time"], slot["line"]
    if (row is None or list(I49.key(row)) != reference["key"] or row["session"] != slot["session"]
            or row["end"] > slot["scheduled"] or I49.key(row) > limit or not price_ok(row)):
        raise ValueError("数量イベントの出典又は当時可視性が不一致")
    previous = indexed.get(row["index"] - 1)
    price_valid = bool(previous is not None and price_ok(previous) and I49.adjacent(previous, row)
        and previous["end"] <= slot["scheduled"] and I49.key(previous) <= limit)
    delta = side * (Fraction(row["close"]) - Fraction(previous["close"])) if price_valid else None
    progress = float(delta / Fraction(atr)) if delta is not None else None
    valid = bool(price_valid and row["rvol"] is not None)
    reason = "有効" if valid else "隣接公開価格なし" if not price_valid else row["quantity_reason"] or "同時刻基準不足又は平均0"
    return {"source": source(row), "previous_source": source(previous) if price_valid else None,
        "quantity": deepcopy(row["quantity"]), "baseline": deepcopy(row["baseline"]),
        "rvol": row["rvol"], "price_delta": float(delta) if delta is not None else None,
        "progress": progress, "valid": valid, "values": [row["rvol"], progress] if valid else [0.0, 0.0],
        "reason": reason}


def extend(slot: dict, old_feature: dict, rows: list[dict]) -> dict:
    """旧54の準備を保ち、対応経路b/rの6列だけを追加する。

    引数: slot(dict)は元完全枠、old_feature(dict)は旧63特徴、rows(list[dict])は当場文脈。
    返り値: dictは全60特徴、旧54射影、当時の量価格ペア。
    """
    result = deepcopy(old_feature)
    result["control_vectors54"] = deepcopy(old_feature["vectors"])
    result["quantity"] = {}
    if not old_feature["ready"]:
        return result
    indexed = {row["index"]: row for row in rows}
    if len(indexed) != len(rows) or not I49.finite(old_feature["atr"]) or old_feature["atr"] <= 0:
        raise ValueError("数量の番号重複又は現在ATR不正")
    for side in ("1", "-1"):
        role = branch_role(old_feature["vectors"][side][0])
        route = old_feature["paths"][side][role]
        b, r = (event_pair(route[name], slot, indexed, int(side), old_feature["atr"]) for name in ("b", "r"))
        values = b["values"] + r["values"] + [int(b["valid"]), int(r["valid"])]
        if not all(I49.finite(v) for v in values):
            raise ValueError("量価格特徴が非有限")
        result["quantity"][side] = {"role": role, "b": b, "r": r, "values": values}
        result["vectors"][side] = old_feature["vectors"][side] + values
    return result


def control_projection(feature: dict) -> dict:
    """追加量特徴を取り外し、旧54の全辞書を復元する。

    引数: feature(dict)はextend出力。
    返り値: dictは旧63完全射影。元を変更しない。
    """
    result = deepcopy(feature)
    result["vectors"] = result.pop("control_vectors54")
    result.pop("quantity")
    return result


def coverage(entries: list[dict], blocks: dict, prepared: dict) -> dict:
    """結果を使わず、準備とイベントペアの方向行数を記述する。

    引数: entries(list[dict])は全66場、blocks/prepared(dict)は旧枠と新特徴。
    返り値: dictは5区分の枠・b/rペア・理由・基準数。独立機会数ではない。
    """
    ranges = {"全66場": entries, "学習専用20場": entries[:20], "時系列20場": entries[20:40],
        "条件選択24場": entries[40:64], "既使用2場": entries[64:]}
    result = {}
    for label, group in ranges.items():
        all_features = [prepared[s["slot_id"]] for entry in group for s in blocks[entry["session"]]["slots"]]
        ready = [f for f in all_features if f["ready"]]
        pairs = [f["quantity"][side] for f in ready for side in ("1", "-1")]
        row = {"全枠": len(all_features), "準備枠": len(ready), "未準備枠": len(all_features) - len(ready),
            "方向行": len(pairs), "両ペア有効方向": sum(p["b"]["valid"] and p["r"]["valid"] for p in pairs)}
        for name in ("b", "r"):
            events = [p[name] for p in pairs]
            row[name] = {"段階あり": sum(p["source"] is not None for p in events),
                "ペア有効": sum(p["valid"] for p in events),
                "既知0量": sum(p["valid"] and p["rvol"] == 0 for p in events),
                "理由": dict(Counter(p["reason"] for p in events)),
                "基準足数": dict(Counter(str(p["baseline"]["count"]) for p in events if p["baseline"] is not None))}
        result[label] = row
    return result
