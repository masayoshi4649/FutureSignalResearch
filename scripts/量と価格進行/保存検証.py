"""64のDI一根と54/60特徴・過去同時刻量価格・新184保存運用を独立に照合する。"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from copy import deepcopy
from datetime import datetime
from decimal import Decimal
from fractions import Fraction
import gzip
import hashlib
import importlib.util
import json
import math
import struct
from pathlib import Path
from urllib.parse import urlencode, urljoin

ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT / "study/00064_再試験の量と価格進行を別々に確認"
WORK = ROOT / "work/量と価格進行/00064"
OLD = ROOT / "study/00063_方向と再開確認へ局面の強弱を追加"
OLDWORK = ROOT / "work/局面強弱の複合確認/00063"
COMPLETE = ROOT / "work/局面強弱の複合確認/63完了記録.json"
MEASUREMENTS = ROOT / "work/独立追尾回収/00055/独立測定.jsonl.gz"
FRAMES = ROOT / "work/一目基準線/00028/全指標.jsonl.gz"
SLOTS50 = ROOT / "work/局所再開/00050/定時判断と運用.jsonl.gz"
POLICIES, CONTROLS = ("B0", "B1", "Q0", "Q1"), ("J0", "J1")
PERIODS = ("学習", "条件選択", "後続検査")
BINDING = ("slot_id", "session", "scheduled", "time", "line")
COUNTS = {"B0": 54, "B1": 54, "Q0": 60, "Q1": 60}
FIXED_NODES = [{"id": 0, "feature": "F01", "index": 0, "threshold": 0.}]
QUANTITY_PATH = ROOT / "work/OBV反転/00029/全指標.jsonl.gz"
Q_FIELDS = ("観測差分量", "数量基準完全", "直前数量足数", "直前数量合計", "直前数量平均", "RVOL", "数量準備済",
    "最終採用数量時計", "最終採用価格時計", "最終採用原行", "数量不完全理由")
FINGERPRINT_FIELDS = ("input_rows_sha256", "used_rows_sha256", "row_ids_sha256", "target_rows_sha256", "period_sha256", "used_barrier_rows_sha256")



def load(path: Path, name: str):
    """固定純補助を独自名で読み、旧大域値を変更しない。

    引数: path(Path)はPython、name(str)は固有名。
    返り値: ModuleTypeは読込結果。新主処理を正式監査でimportしない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


R63 = load(ROOT / "scripts/局面強弱の複合確認/保存検証.py", "量価格監査_固定63")
S63 = load(ROOT / "scripts/局面強弱の複合確認/接続を補足する.py", "量価格監査_固定63接続")
R62, R61 = R63.R62, R63.R61
R60, R59, R58, R56, A, P, R55 = R63.R60, R63.R59, R63.R58, R63.R56, R63.A, R63.P, R63.R55
fingerprint = A.fingerprint
path_coverage, episode_counts = R60.path_coverage, R60.episode_counts
prior_supplement = R62.prior_supplement
I49 = R63.I49


# ----------------------------------------
# 旧54列は固定独立算術、追加6列は過去量と公開価格ペアから別算する。

def feature_metadata(count: int = 60) -> list[dict]:
    """旧54列と数量・価格・共同有効旗の6列を独立に定義する。

    引数: count(int)はB木の54又はQ木の60。
    返り値: list[dict]は政策のmetadata。新Fの値を期待値にしない。
    """
    if count not in (54, 60):
        raise ValueError("54又は60列が必要")
    names = ("対応b同時刻RVOL", "対応b同足進行対現在ATR", "対応r同時刻RVOL",
        "対応r同足進行対現在ATR", "対応b量価格ペア有効", "対応r量価格ペア有効")
    additional = [{"id": f"F{55+i:02d}", "name": name, "method": "P05" if i in (1, 3) else "V01",
        "family": "price" if i in (1, 3) else "volume", "scale": "m03"} for i, name in enumerate(names)]
    return R63.feature_metadata() + (additional if count == 60 else [])


def float32(values: list, count: int | None = None) -> list[float]:
    """旧54と新共同maskの領域を検査して政策次元のfloat32へ写す。

    引数: values(list)は54/60有限値、count(int|None)は明示列数又は長さ採用。
    返り値: list[float]は有限なfloat32値。共同mask0は量・価格とも定義0。
    """
    count = len(values) if isinstance(values, list) and count is None else count
    if count not in (54, 60) or not isinstance(values, list) or len(values) != count:
        raise ValueError("政策に対応する54又は60列が必要")
    output = R63.float32(values[:54])
    if count == 54:
        return output
    if not all(A.finite(value) for value in values[54:]):
        raise ValueError("追加量価格値が非有限")
    for q, progress, mask in ((54, 55, 58), (56, 57, 59)):
        if values[q] < 0 or type(values[mask]) is bool or values[mask] not in (0, 1):
            raise ValueError("非負RVOLと数値0/1maskが必要")
        if values[mask] == 0 and (values[q] != 0 or values[progress] != 0):
            raise ValueError("共同mask0で非零の量価格")
    for value in values[54:]:
        try:
            converted = struct.unpack(">f", struct.pack(">f", value))[0]
        except (OverflowError, struct.error) as exc:
            raise ValueError("追加列float32範囲外") from exc
        if not math.isfinite(converted):
            raise ValueError("追加列float32非有限")
        output.append(converted)
    return output


def band_width(prices: list[float]) -> float | None:
    """20価格の全対差二乗から母分散を別算して4σを得る。

    引数: prices(list[float])は過去順の終値窓。
    返り値: float|Noneは価格単位の全幅。20本未満はNone、定幅は既知0。
    """
    if len(prices) != 20:
        return None
    values = [Fraction(v) for v in prices]
    variance = sum(((values[i] - values[j]) ** 2 for i in range(20) for j in range(i)), Fraction()) / 400
    width = 4 * math.sqrt(float(variance))
    if not A.finite(width):
        raise ValueError("BB全幅が非有限")
    return width


def numeric_context(sessions: list[dict]) -> dict:
    """固定49の上位銀行と別算BB窓を66場の価格順に構築する。

    引数: sessions(list[dict])はsession/contract/begin/end/frames15。
    返り値: dictは場別上位足。新Fと新主の数値計算は呼ばない。
    """
    bank, prices, identities, result = I49.NumericBank(15), [], [], {}
    previous_end = None
    for item in sessions:
        if item["session"] in result or previous_end is not None and item["begin"] < previous_end:
            raise ValueError("場の重複又は順序不正")
        rows, _ = bank.build(item["frames15"], item["session"], item["contract"], item["begin"], item["end"])
        output = []
        for row in rows:
            if row["valid"] is not True or row["numeric_count"] <= 1:
                prices, identities = [], []
            if row["valid"]:
                prices = (prices + [row["close"]])[-20:]
                identities = (identities + [[row["session"], row["index"], row["confirm"], row["confirm_line"]]])[-20:]
            window_sha = hashlib.sha256(json.dumps(identities, ensure_ascii=False,
                separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()
            output.append({**deepcopy(row), "bb_width": band_width(prices), "bb_count": len(prices), "bb_window_sha256": window_sha})
        result[item["session"]], previous_end = output, item["end"]
    return result


def control_projection(feature: dict) -> dict:
    """追加6列だけを除き旧63全54辞書を完全に復元する。

    引数: feature(dict)は60列の保存又は期待特徴。
    返り値: dictは旧54辞書。元の値を変更しない。
    """
    value = deepcopy(feature)
    value["vectors"] = value.pop("control_vectors54")
    value.pop("quantity")
    return value


def price_complete(row: dict) -> bool:
    """価格・公開・完全幅を量の数値可否から独立に判定する。

    引数: row(dict)はSOURCE13。
    返り値: boolは公開完全180秒・missing0・有限OHLCと確認時計の成立。
    """
    return not bool(A.source_reason(row, row["session"], 3, row["end"], (row.get("confirm"), row.get("confirm_line"))))


def quantity_reason(row: dict) -> str | None:
    """固定qの完全旗と最終採用時計・原行を別に検査する。

    引数: row(dict)はSOURCE13とquantity(Q11)。
    返り値: str|Noneは理由、Noneは既知q。完全旗と時計の矛盾は例外。
    """
    if not price_complete(row):
        return "公開完全価格でない"
    q = row["quantity"]
    if q["数量基準完全"] is not True or not A.finite(q["観測差分量"]) or q["観測差分量"] < 0:
        return "数量基準不完全又は不正"
    qt, pt, line = [q[key] for key in ("最終採用数量時計", "最終採用価格時計", "最終採用原行")]
    if (not A.finite(qt) or not A.finite(pt) or not row["start"] <= qt <= pt < row["end"]
            or type(line) is not int or not 0 <= line < row["confirm_line"] or q["数量不完全理由"] != []):
        raise ValueError("完全数量の採用時計・原行・理由の矛盾")
    return None


def join_quantity(sessions: list[dict], rows: list[dict]) -> dict:
    """固定29数量を全旧SOURCE13へ型値一対一で結ぶ。

    引数: sessions(list[dict])は旧価格場、rows(list[dict])は数量付き旧29行。
    返り値: dictは場別SOURCE/Q11のみ。欠落・余剰・重複・型差を拒否する。
    """
    expected, found = {}, {}
    for item in sessions:
        for frame in item["frames3"]:
            row = {"session": item["session"], **frame}
            identity = item["session"], row["index"]
            if identity in expected:
                raise ValueError("価格SOURCEの重複")
            expected[identity] = {key: deepcopy(row[key]) for key in A.SOURCE}
    for raw in rows:
        source = {"session": raw["場"], **{key: deepcopy(raw[key]) for key in A.SOURCE if key != "session"}}
        identity = source["session"], source["index"]
        if identity in found or identity not in expected or not S63.strict_equal(source, expected[identity]):
            raise ValueError("固定数量と価格SOURCEの重複・欠落・型値差")
        q = raw["数量参照"]
        if not isinstance(q, dict) or set(q) != set(Q_FIELDS):
            raise ValueError("Q11の項目差")
        found[identity] = {**source, "quantity": deepcopy(q)}
    if set(expected) != set(found):
        raise ValueError("固定数量の集合差")
    return {item["session"]: [found[item["session"], row["index"]] for row in item["frames3"]] for item in sessions}


def read_quantity(sessions: list[dict], source, audit) -> dict:
    """旧29の成功証明・圧縮/展開指紋を照合して既存Q11だけを読む。

    引数: sessions(list[dict])は旧3分価格、source(ModuleType)は固定読取、audit(Audit)は照合記録。
    返り値: dictは場別の数量。元原板や旧数量算出を再実行しない。
    """
    pins = {
        "work/OBV反転/00029/全指標.jsonl.gz": "4cb6fa91799fe9d892475f955c3e701bc99f293505ebfe3903733f60838f8074",
        "study/00029_BB内復帰とOBV非追随/作業成果物.json": "2cffc703907cc7b0b8e7b32b498d8d673564759fca6f9abd731a456924fb7bb0",
        "study/00029_BB内復帰とOBV非追随/独立監査.json": "7267b30d7a741313df210e381046e8775d5ce995907852b8af148c742a37b2fb",
        "study/00029_BB内復帰とOBV非追随/状態独立確認.json": "79e63b50d7d06b5b78c9bf099445a51f0515e1926d918ba9dff7d574937cd2d9",
        "study/00029_BB内復帰とOBV非追随/入力台帳.json": "e7f3345e1d750b5d9f2027ee530d15d5293f567edb08939beed5154d8d45508f",
        "study/00028_基準線復帰と上位一目の方向/入力台帳.json": "680b831ee6bef1ec1cf49dc6283931f5b0ca9611f15f5c19d81af6e4738aaf9b"}
    for name, digest in pins.items():
        audit.check("数量固定出典:"+name, source.sha(ROOT/name), digest)
        if source.sha(ROOT/name) != digest:
            raise ValueError("固定数量出典の変更")
    for name in ("独立監査.json", "状態独立確認.json"):
        proof = source.read(ROOT/"study/00029_BB内復帰とOBV非追随"/name)
        audit.check("数量29成功:"+name, (proof["全件一致"], proof["不一致数"]), (True,0))
    digest, rows = hashlib.sha256(), []
    with gzip.open(QUANTITY_PATH, "rb") as stream:
        for raw in stream:
            digest.update(raw)
            rows.append(json.loads(raw))
    audit.check("数量29展開内容", digest.hexdigest(), "a8172b96c8435c1b38bff79bab95465dc5fdfe4db8d1a8378f059a315dfb7808")
    return join_quantity(sessions, rows)


def quantity_context(sessions: list[dict], quantities: dict) -> dict:
    """各場で過去候補10場を先に選び、同indexの完全qだけを別和で集計する。

    引数: sessions(list[dict])は価格時系列、quantities(dict)は正確に結合済みQ11。
    返り値: dictは当時窓・採用足・精密総和・RVOL。未来場を基準に使わない。
    """
    names = [item["session"] for item in sessions]
    if len(set(names)) != len(names) or set(names) != set(quantities):
        raise ValueError("数量と場の重複又は集合差")
    indexes, result = {}, {}
    for position, item in enumerate(sessions):
        name, contract = item["session"], tuple(item["contract"])
        kind = name.rsplit("_", 1)[-1]
        if kind not in ("Day", "Night") or len(contract) != 1 or item["begin"] >= item["end"]:
            raise ValueError("場種・限月・始終の不正")
        if position and item["begin"] <= sessions[position-1]["begin"]:
            raise ValueError("場の時間順違い")
        compatible = [old for old in sessions[:position] if old["session"].rsplit("_", 1)[-1] == kind and tuple(old["contract"]) == contract]
        if any(old["end"] >= item["begin"] for old in compatible):
            raise ValueError("同種過去場が未完了")
        window = [old for old in compatible if old["end"] < item["begin"]][-10:]
        if len(quantities[name]) != len(item["frames3"]):
            raise ValueError("数量足数差")
        built, seen = [], set()
        for position_row, raw in enumerate(quantities[name]):
            row = deepcopy(raw)
            target = {"session": name, **item["frames3"][position_row]}
            if (row["index"] in seen or seen and row["index"] <= max(seen)
                    or not S63.strict_equal({key: row[key] for key in A.SOURCE}, {key: target[key] for key in A.SOURCE})):
                raise ValueError("数量SOURCE順序・型値差")
            seen.add(row["index"])
            reason, samples = quantity_reason(row), []
            for old in window:
                prior = indexes[old["session"]].get(row["index"])
                if prior is None or prior["quantity_reason"] is not None:
                    continue
                if prior["confirm"] >= item["begin"]:
                    raise ValueError("過去基準が開始時点で未公開")
                samples.append({"session": prior["session"], "index": prior["index"],
                    "key": [prior["confirm"], prior["confirm_line"]], "q": prior["quantity"]["観測差分量"]})
            fractions = [Fraction(sample["q"]) for sample in samples]
            total = sum(fractions, Fraction())
            mean = total/len(fractions) if fractions else None
            valid = bool(len(fractions) >= 5 and mean > 0)
            rvol = float(Fraction(row["quantity"]["観測差分量"])*len(fractions)/total) if reason is None and valid else None
            row.update(quantity_reason=reason, baseline={"window_sessions": [old["session"] for old in window],
                "samples": samples, "count": len(samples), "mean": float(mean) if mean is not None else None,
                "sum_numerator": total.numerator, "sum_denominator": total.denominator, "valid": valid}, rvol=rvol)
            built.append(row)
        result[name], indexes[name] = built, {row["index"]: row for row in built}
    return result


def expected_pair(reference: dict | None, slot: dict, rows: list[dict], side: int, atr: float) -> dict:
    """公開イベントとindex前足から当時の量価格ペアを独立に作る。

    引数: reference(dict|None)はb/r参照、slot(dict)は判断、rows(list[dict])は数量文脈、
        side(int)は実候補方向、atr(float)は現在の正ATR。
    返り値: dictは出典・理由・2値。欠測ペアは両値0だが診断値は区別する。
    """
    empty = {"source": None, "previous_source": None, "quantity": None, "baseline": None, "rvol": None,
        "price_delta": None, "progress": None, "valid": False, "values": [0.0, 0.0], "reason": "段階なし"}
    if reference is None:
        return empty
    found = [row for row in rows if row["index"] == reference["index"]]
    if len(found) != 1:
        raise ValueError("数量イベント参照の集合差")
    current = found[0]
    key = [current["confirm"], current["confirm_line"]]
    limit = slot["time"], slot["line"]
    if (key != reference["key"] or A.source_reason(current, slot["session"], 3, slot["scheduled"], limit)):
        raise ValueError("数量イベントの公開出典差")
    previous = next((row for row in rows if row["index"] == current["index"]-1), None)
    valid_price = bool(previous is not None and not A.source_reason(previous, slot["session"], 3, slot["scheduled"], limit)
        and A.adjacent(previous, current))
    delta = Fraction(side)*(Fraction(current["close"])-Fraction(previous["close"])) if valid_price else None
    progress = float(delta/Fraction(atr)) if delta is not None else None
    valid = valid_price and current["rvol"] is not None
    reason = "有効" if valid else "隣接公開価格なし" if not valid_price else current["quantity_reason"] or "同時刻基準不足又は平均0"
    return {"source": {key: deepcopy(current[key]) for key in A.SOURCE},
        "previous_source": {key: deepcopy(previous[key]) for key in A.SOURCE} if valid_price else None,
        "quantity": deepcopy(current["quantity"]), "baseline": deepcopy(current["baseline"]), "rvol": current["rvol"],
        "price_delta": float(delta) if delta is not None else None, "progress": progress, "valid": bool(valid),
        "values": [current["rvol"], progress] if valid else [0.0, 0.0], "reason": reason}


def expected_feature(old: dict, slot: dict, rows: list[dict]) -> dict:
    """検算済み54列の対応経路b/rへ量価格6値だけを付加する。

    引数: old(dict)は独立54、slot(dict)は元完全枠、rows(list[dict])は当場数量文脈。
    返り値: dictは旧準備・全付随辞書を維持した60特徴。
    """
    output = deepcopy(old)
    output.update(control_vectors54=deepcopy(old["vectors"]), quantity={})
    if not old["ready"]:
        return output
    if len({row["index"] for row in rows}) != len(rows) or not A.finite(old["atr"]) or old["atr"] <= 0:
        raise ValueError("数量番号重複又は現在ATR不正")
    for side in ("1", "-1"):
        role = "T" if struct.unpack(">f",struct.pack(">f",old["vectors"][side][0]))[0] > 0 else "R"
        route = old["paths"][side][role]
        b, r = [expected_pair(route[event], slot, rows, int(side), old["atr"]) for event in ("b", "r")]
        additional = b["values"] + r["values"] + [int(b["valid"]), int(r["valid"])]
        if not all(A.finite(value) for value in additional):
            raise ValueError("数量価格特徴が非有限")
        output["quantity"][side] = {"role": role, "b": b, "r": r, "values": additional}
        output["vectors"][side] += additional
    return output


def prepare_features(old_slots: dict, features: dict, source, audit) -> tuple:
    """縮約旧46と完全旧50slotを明示接続し、独立54から量6列を再構築する。

    引数: old_slots/features(dict)は縮約BINDINGと旧18、source(ModuleType)/audit(Audit)は固定読取。
    返り値: tuple[dict,dict]は全2442期待特徴と全数量足集計。新F/新L/新主を呼ばない。
    """
    old54, _ = S63.prepare_connected(old_slots, features, source, audit)
    sessions = []
    frames = defaultdict(list)
    for row in source.json_rows(FRAMES):
        if row["minutes"] == 3:
            frames[row["場"]].append({key: deepcopy(row[key]) for key in A.SOURCE if key != "session"})
    for entry in source.read(source.MANIFEST)["entries"]:
        name = entry["session"]
        begin, _, end, _ = source.calendar(name)
        sessions.append({"session": name, "contract": tuple(entry["in_session_contract_codes"]), "begin": begin, "end": end, "frames3": frames[name]})
    quantity = read_quantity(sessions, source, audit)
    contexts = quantity_context(sessions, quantity)
    rows = [slot for block in source.json_rows(SLOTS50) if block["policy"] == "P0" for slot in block["slots"]]
    prior46 = {identity: R63.control_projection(feature) for identity, feature in old54.items()}
    complete = S63.bind_full_slots(old_slots, rows, prior46)
    result = {identity: expected_feature(feature, complete[identity], contexts[complete[identity]["session"]]) for identity, feature in old54.items()}
    for identity, feature in result.items():
        audit.check("旧54全辞書射影", control_projection(feature), old54[identity])
    return result, {"数量出典接続足数":sum(len(rows) for rows in contexts.values()),
        "公開完全数量足数":sum(row["quantity_reason"] is None for rows in contexts.values() for row in rows),
        "同時刻量既知足数":sum(row["rvol"] is not None for rows in contexts.values() for row in rows)}


# ----------------------------------------
# 分岐DIはfloat32、実運用のDI役割は旧規約のraw符号を維持する。

def group_key(values: list) -> str:
    """float32のDI符号だけから二群を確定する。

    引数: values(list)は54/60特徴。
    返り値: strはD0又はD1。rawによる実roleを変更しない。
    """
    return "D1" if float32(values)[0] > 0 else "D0"


def expected_rules() -> dict:
    """旧63規約の固定kを外しDI一根と政策別列数を定義する。

    引数: なし。
    返り値: dictはB/Q全政策規約。資格を緩めない。
    """
    rules = R63.expected_rules()
    rules.pop("J0固定段")
    rules.pop("J1")
    rules.update({"政策深さ": {"B0": 4, "Q0": 4}, "政策特徴数": {"B0": 54, "Q0": 60},
        "固定DI根": {"根": {"feature": "F01", "index": 0, "threshold": 0.0}, "群": ["D0", "D1"],
            "子深さ": 3, "子特徴数": {"B0": 53, "Q0": 59},
            "子特徴列index": {"B0": list(range(1, 54)), "Q0": list(range(1, 60))}, "除外index": [0], "MSE最適固定段ではない": True},
        "B1": "同一B0木に従来の回収支持とstrict正額を後段追加",
        "Q1": "同一Q0木に従来の回収支持とstrict正額を後段追加",
        "群の意味": "float32 DI非正側D0と正側D1。k旗は子へ戻し、厳密DI0WAITは後段保持",
        "群の除外": "両方向群を残す。全pair除外は先に行い、枝内pair成立は要求しない",
        "複数技法": "固定根はtrendだけ。実pathのfamily2以上かつtrend又はoscを従来通り要求",
        "追加指標": "選択経路のb/rそれぞれのTOD RVOLと実方向終値差/現在ATRを別列、共同有効mask0なら両0",
        "mask限定": "新量maskもV01/volume。同じ資格関数だが新6列でmaskだけを使うpathは診断で別記",
        "比較の限定": "B0は旧54をDI一段根で再fit。Q0は同じ根/教師へ6列追加。量単独又は心理因果の証明ではない"})
    return rules


def recovery_training(rows: list[dict], evaluation_start: float, count: int = 60) -> tuple:
    """旧54のpair・回収・過去境界を維持し同じIDを54/60へ写す。

    引数: rows(list[dict])は政策教師、evaluation_start(float)は評価開始、count(int)は54/60。
    返り値: tuple[list,dict]は使用canonicalとbase54を含む全指紋。
    """
    projected = []
    for row in rows:
        float32(row["features"], count)
        projected.append({**row, "features": row["features"][:54]})
    old_used, training = R63.recovery_training(projected, evaluation_start)
    training["base54_fingerprints"] = {key: training[key] for key in FINGERPRINT_FIELDS}
    if count == 54:
        training["feature_missing_handling"] = "旧63全54準備の同じ教師pair。基礎54の再fit、追加情報・追加除外なし"
        return old_used, training
    ids = {(r["session"], r["slot_id"], r["side"]) for r in old_used}
    canonical = []
    for original in rows:
        row = {key: deepcopy(original[key]) for key in A.TEACHER_FIELDS}
        row["features"] = [float(v) for v in row["features"]]
        row.update(entry_time=original.get("entry_time"), entry_line=original.get("entry_line"), recovery_end_time=original.get("recovery_end_time"))
        row.update({f"pnl{f}": R56.decimal_text(Decimal(str(original[f"pnl{f}"]))) if original.get(f"pnl{f}") is not None else None for f in (0, 5, 10)})
        canonical.append(row)
    used = [row for row in canonical if (row["session"], row["slot_id"], row["side"]) in ids]
    training.update(input_rows_sha256=fingerprint(canonical), used_rows_sha256=fingerprint(used),
        used_barrier_rows_sha256=fingerprint([{key: row[key] for key in (*A.TEACHER_FIELDS, "entry_time", "entry_line")} for row in used]),
        feature_missing_handling="旧63全54準備の同じ教師pair。追加6列は未知0＋共同有効mask、追加除外なし")
    return used, training


def expected_counts(inherited: dict, count54: int, closed: int, quantity_counts: dict) -> dict:
    """旧八キーと新五キーを完全な集合として検査・構成する。

    引数: inherited(dict)は旧63、count54/closed(int)は旧54・新同一完結数、quantity_counts(dict)は全足量集計。
    返り値: dictは全13項目。旧38や量欠測を黙って省略しない。
    """
    expected = {"測定特徴方向一致":4884,"旧評価特徴完全一致":3404,"旧18特徴完全一致":2442,
        "旧38特徴保存一致":3404,"旧46特徴保存一致":3404,"旧46射影一致":2442,"旧62特徴保存一致":3404}
    if set(inherited) != {*expected,"同一新規完結一致"} or any(inherited[k] != v for k,v in expected.items()):
        raise ValueError("継承八キーの欠落・追加・数値差")
    keys={"数量出典接続足数","公開完全数量足数","同時刻量既知足数"}
    if (count54 != 3404 or type(closed) is not int or closed < 0 or set(quantity_counts)!=keys
            or any(type(value) is not int or value<0 for value in quantity_counts.values())):
        raise ValueError("64の照合カウンタ不正")
    if max(quantity_counts.values())>quantity_counts["数量出典接続足数"]:
        raise ValueError("数量足数の包含差")
    return {**inherited,"同一新規完結一致":closed,"旧54射影一致":2442,"旧63特徴保存一致":count54,**quantity_counts}


def state_distribution(used: list[dict], prepared: dict) -> dict:
    """木の二群とは別に旧DI×対応k四群を診断として維持する。

    引数: used(list[dict])は使用教師、prepared(dict)は当時60列特徴。
    返り値: dictは旧63と同型のD0_K0等四群。支持gateには使わない。
    """
    projected = [{**row,"features":row["features"][:54]} for row in used]
    return R63.state_distribution(projected,prepared)



def walk(model: dict, values: list) -> tuple:
    """政策別54/60列の保存木を独立に走査する。

    引数: model(dict)はB0/Q0保存木、values(list)は同列数の特徴。
    返り値: tupleはleaf/path/全所属node。新L.walkは呼ばない。
    """
    count = COUNTS.get(model.get("policy"))
    values, index, path, visits = float32(values, count), 0, [], []
    while True:
        if type(index) is not int or not 0 <= index < len(model["nodes"]) or index in visits:
            raise ValueError("保存木の循環又は範囲外")
        node = model["nodes"][index]
        if node["id"] != index:
            raise ValueError("node ID不整合")
        visits.append(index)
        if node["left"] == node["right"] == -1:
            return index, path, visits
        feature = node["feature"]
        if type(feature) is not int or not 0 <= feature < count or not A.finite(node["threshold"]):
            raise ValueError("分岐値不正")
        branch = "left" if values[feature] <= node["threshold"] else "right"
        meta = model["feature_meta"][feature]
        path.append({"node": index, "feature": feature, "feature_id": meta["id"], "method": meta["method"], "family": meta["family"],
            "threshold": node["threshold"], "comparison": "<=" if branch == "left" else ">", "branch": branch})
        index = node[branch]


def check_reused_proof(source, audit) -> tuple:
    """63初回失敗と接続補足成功を両方残した版連鎖から旧保存対照を再用する。

    引数: source(ModuleType)は固定読取、audit(Audit)は照合記録。
    返り値: tupleは旧63結果/成功proof/完了台帳。旧監査を再実行しない。
    """
    R63.check_reused_proof(source, audit)
    previous, proof, done = [source.read(path) for path in (OLD/"結果.json", OLD/"保存物確認.json", COMPLETE)]
    audit.check("63完了単一実行", (done["試行"],done["市場実行終了"],done["本物実行回数"]), (63,True,1))
    audit.check("63保存監査成功", (proof["全件一致"],proof["不一致数"]), (True,0))
    audit.check("63結果bind", source.sha(OLD/"結果.json"), proof["結果SHA256"])
    initial, supplement = proof["初回監査"], proof["接続補足"]
    audit.check("63初回未完を保持", (initial["terminal_exit"],initial["完了"],initial["proof生成"]), (1,False,False))
    audit.check("63補足限定", (supplement["凍結A変更"],supplement["凍結A大域値変更"],supplement["主結果変更"],supplement["市場再生"],supplement["fit"]), (False,)*5)
    audit.check("63補足合計", supplement["凍結A範囲の照合項目数"]+supplement["追加接続照合項目数"], proof["照合項目数"])
    audit.check("63初回log保全", source.sha(ROOT/initial["ログ"]), initial["ログSHA256"])
    audit.check("63補足code保全", source.sha(ROOT/supplement["補足コード"]["パス"]), supplement["補足コード"]["SHA256"])
    paths = [OLD/name for name in ("結果.json","固定.json","保存物確認.json","一覧.resources.json")]
    paths += [OLDWORK/name for name in ("定時判断と運用.jsonl.gz","入口先着.jsonl.gz")]
    paths += [ROOT/meta["path"] for meta in previous["モデル"]+previous["回収集計"]]
    for path in paths:
        name, digest = path.relative_to(ROOT).as_posix(), source.sha(path)
        audit.check("63完了SHA:"+name, digest, done["成果物SHA256"][name])
        if path != OLD/"保存物確認.json":
            audit.check("63成功監査SHA:"+name, digest, {**proof["参照SHA256"],**proof["モデルSHA256"]}[name])
    audit.check("55測定の63bind", source.sha(MEASUREMENTS), proof["参照SHA256"][MEASUREMENTS.relative_to(ROOT).as_posix()])
    return previous, proof, done


def check_model(model: dict, used: list[dict], training: dict, meta: list[dict], identity: str, learner_sha: str, audit) -> None:
    """新回帰木の全所属・二群・先着率と回収統計を独立再構成する。

    引数: model(dict)は保存木、used/trainingは独立教師、meta(list[dict])は54/60列、
        identity/learner_sha(str)はID/版、audit(Audit)は記録。
    返り値: None。最良閾値の探索や別fitはせず、固定段の最適性を要求しない。
    """
    expected_policy = identity.split("_",1)[0]
    if expected_policy not in ("B0","Q0"):
        raise ValueError("B0/Q0木以外はfit対象でない")
    policy, count = expected_policy, COUNTS[expected_policy]
    projection = list(range(1, count))
    audit.check(identity + ":schema", (model["schema_version"], model["model_id"], model["policy"]), (1, identity, policy))
    audit.check(identity + ":metadata", model["feature_meta"], meta)
    audit.check(identity + ":metadata指紋", model["feature_meta_sha256"], fingerprint(meta))
    audit.check(identity + ":学習code", model["source_sha256"], learner_sha)
    audit.check(identity + ":library", model["versions"]["scikit-learn"], "1.9.1")
    audit.check(identity + ":本体引数", model["parameters"], R56.regressor_parameters(4))
    audit.check(identity + ":子引数", model["subtree_parameters"], R56.regressor_parameters(3))
    audit.check(identity + ":構造", model["structure"], {"kind": "fixed_direction_only", "fixed_nodes": FIXED_NODES,
        "child_depth": 3, "child_features": count-1, "child_feature_indices": projection, "excluded_feature_indices": [0],
        "feature_count": count, "max_depth": 4, "fixed_mse_optimized": False,
        "child_estimator": "DecisionTreeRegressor", "target": "pnl5"})
    audit.check(identity + ":規約", model["rules"], expected_rules())
    shared = [ROOT / "scripts/方向局面分岐/学習.py", ROOT / "scripts/局所帯分岐/学習.py", ROOT / "scripts/回収目的分岐/学習.py", ROOT / "scripts/波の区間分離/学習.py", ROOT / "scripts/現行経路の状態分岐/学習.py", ROOT / "scripts/方向と再開確認/学習.py", ROOT / "scripts/局面強弱の複合確認/学習.py"]
    audit.check(identity + ":旧純補助bind", model["shared_source_sha256"], {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in shared})
    nodes, paths = model["nodes"], {0: []}
    for index, node in enumerate(nodes):
        if index not in paths:
            raise ValueError("到達不能node")
        audit.check(identity + ":node順", node["id"], index)
        audit.check(identity + ":depth4", len(paths[index]) <= 4, True)
        audit.check(identity + ":path", node["path"], paths[index])
        if index == 0:
            fixed = FIXED_NODES[index]
            audit.check(identity + ":固定node", (node["feature"], node["feature_id"], node["threshold"]), (fixed["index"], fixed["feature"], fixed["threshold"]))
            audit.check(identity + ":固定内部保持", node["left"] >= 0 and node["right"] >= 0, True)
        if node["left"] == node["right"] == -1:
            audit.check(identity + ":葉記号", (node["feature"], node["feature_id"], node["family"], node["threshold"]), (-2, None, None, -2.))
            continue
        feature = node["feature"]
        if type(feature) is not int or not 0 <= feature < count or not A.finite(node["threshold"]):
            raise ValueError("分岐値不正")
        if index >= 1:
            audit.check(identity + ":子投影index0除外", feature in projection, True)
        audit.check(identity + ":分岐metadata", (node["feature_id"], node["family"]), (meta[feature]["id"], meta[feature]["family"]))
        for branch, comparison in (("left", "<="), ("right", ">")):
            child = node[branch]
            if type(child) is not int or not index < child < len(nodes) or child in paths:
                raise ValueError("子ID又は重複親不正")
            paths[child] = paths[index] + [{"node": index, "feature": feature, "feature_id": meta[feature]["id"], "method": meta[feature]["method"],
                "family": meta[feature]["family"], "threshold": node["threshold"], "comparison": comparison, "branch": branch}]
    audit.check(identity + ":全node到達可能", set(paths), set(range(len(nodes))))
    membership = defaultdict(list)
    for row in used:
        leaf, path, visits = walk(model, row["features"])
        audit.check(identity + ":方向行path", path, nodes[leaf]["path"])
        for index in visits:
            membership[index].append(row)
    partition, offset = {}, 1
    for d in (0, 1):
        key = f"D{d}"
        selected = [row for row in used if group_key(row["features"]) == key]
        root = nodes[0]["right" if d else "left"]
        descendants = [i for i, path in paths.items() if path and path[0]["branch"] == ("right" if d else "left")]
        audit.check(identity + key + ":子offset", root, offset)
        audit.check(identity + key + ":連続ID", sorted(descendants), list(range(offset, offset + len(descendants))))
        audit.check(identity + key + ":子depth3", all(len(paths[i])-1 <= 3 for i in descendants), True)
        audit.check(identity + key + ":所属", membership[root], selected)
        if not selected:
            audit.check(identity + key + ":空群一未知leaf", (len(descendants), nodes[root]["left"], nodes[root]["right"], nodes[root]["data_absent"]), (1, -1, -1, True))
        ids = [{k: r[k] for k in ("session", "slot_id", "side")} for r in selected]
        partition[key] = {"d": d, "route": "T" if d else "R", "policy": policy,
            "excluded_feature_indices": [0], "child_feature_indices": projection,
            "direction_rows": len(selected), "pair_unique": len({(r["session"], r["slot_id"]) for r in selected}),
            "days": len({r["session"][:10] for r in selected}), "sessions": len({r["session"] for r in selected}), "row_ids_sha256": fingerprint(ids),
            "fit_performed": bool(selected), "root": root, "node_count": len(descendants), "fit_parameters": R56.regressor_parameters(3)}
        offset += len(descendants)
    audit.check(identity + ":二群全方向", sum(p["direction_rows"] for p in partition.values()), len(used))
    audit.check(identity + ":全training", model["training"], {**deepcopy(training), "partition": partition})
    roots = {p["root"] for p in partition.values()}
    for index, node in enumerate(nodes):
        rows = membership[index]
        successes = sum(A.TARGETS[r["outcome"]] for r in rows)
        score = successes / len(rows) if rows else None
        expected = {"direction_rows": len(rows), "weighted_rows": len(rows) / 2, "success_weight": successes / 2, "total_weight": len(rows) / 2,
            "score": score, "barrier_gini": 2 * score * (1 - score) if score is not None else None, "impurity_kind": "squared_error",
            "unique_slots": len({(r["session"], r["slot_id"]) for r in rows}), "days": len({r["session"][:10] for r in rows}), "sessions": len({r["session"] for r in rows}),
            "methods": sorted({p["method"] for p in paths[index]}), "families": sorted({p["family"] for p in paths[index]}), "data_absent": not bool(rows),
            "training_ids_sha256": fingerprint([{k: r[k] for k in ("session", "slot_id", "side")} for r in rows])}
        statistics = R56.decimal_statistics(rows)
        second = statistics.pop("second_moment")
        for key in ("regression_value", "impurity"):
            value = statistics.pop(key)
            if index == 0:
                audit.check(identity + str(index) + ":固定段" + key, node[key], value)
            else:
                audit.check(identity + str(index) + ":生回帰器" + key, R56.numeric_match(node[key], value, "mean" if key == "regression_value" else "mse", second), True)
        for key, value in {**expected, **statistics}.items():
            audit.check(identity + str(index) + ":" + key, node[key], value)
        audit.check(identity + ":data_absent型", type(node["data_absent"]) is bool, True)
        eligibility = A.eligibility(node, paths[index])
        audit.check(identity + ":支持旗", (node["leaf_support"], node["method_support"]), (eligibility["leaf_support"], eligibility["method_support"]))
        if index >= 1 and node["left"] != -1:
            audit.check(identity + ":通常子minleaf60", min(len(membership[node["left"]]), len(membership[node["right"]])) >= 60, True)
        if not rows and index >= 1:
            audit.check(identity + ":空は群root一葉", index in roots and node["left"] == node["right"] == -1, True)


def predict(model: dict, vectors: dict) -> dict:
    """保存木の両方向を独立採点し、未知枝では既知側への救済も行わない。

    引数: model(dict)は検算済みB0/Q0木、vectors(dict)は政策列数×両方向。
    返り値: dictは全予測。未知側だけscore/eligibilityをNoneとしraw既知値を保持する。
    """
    if not isinstance(vectors, dict) or set(vectors) != {"1", "-1"}:
        raise ValueError("両方向特徴が必要")
    if vectors["1"] == vectors["-1"] == []:
        return {"scores": {side: None for side in ("1", "-1")}, "leafs": {side: None for side in ("1", "-1")},
                "side": 0, "winner_side": 0, "reason": "特徴未準備WAIT", "eligibility": {side: None for side in ("1", "-1")}}
    scores, leafs, qualifications = {}, {}, {}
    for side in ("1", "-1"):
        leaf, path, _ = walk(model, vectors[side])
        node = model["nodes"][leaf]
        if node["path"] != path:
            raise ValueError("保存pathとwalk不一致")
        absent = node.get("data_absent") is True
        if absent and (node["score"] is not None or node["direction_rows"] != 0):
            raise ValueError("未知枝のscore0補完又は行数不整合")
        if not absent and (not A.finite(node["score"]) or not 0 <= node["score"] <= 1):
            raise ValueError("既知枝のscore不正")
        scores[side], leafs[side] = node["score"], leaf
        qualifications[side] = None if absent else A.eligibility(node, path)
    result = {"scores": scores, "leafs": leafs, "side": 0, "winner_side": 0, "reason": "同点WAIT", "eligibility": qualifications}
    if any(value is None for value in scores.values()):
        result["reason"] = "未学習枝WAIT"
        return result
    if scores["1"] != scores["-1"]:
        winner = "1" if scores["1"] > scores["-1"] else "-1"
        failures = [label for key, label in (("score", "最高側score下限未達"), ("leaf_support", "最高側葉支持不足"),
                    ("method_support", "最高側複数技法不足")) if not qualifications[winner][key]]
        result.update(winner_side=int(winner), side=0 if failures else int(winner), reason="/".join(failures) if failures else "採用")
    return result


def expected_calibration(model: dict, measurements: dict, evaluation_start: float) -> dict:
    """新B0/Q0の使用教師へ確定回収pairを結び、全葉を独立集計する。

    引数: model(dict)は新B0/Q0木、measurements(dict)は枠/side→測定、evaluation_start(float)は後続開始。
    返り値: dictは全葉の支持・十進純額・平均・採否符号・教師指紋。新fitをしない。
    """
    identities = model["training"]["row_ids"]
    pairs = {}
    for identity in identities:
        key = identity["slot_id"], identity["side"]
        row = measurements[key]
        if row["session"] != identity["session"] or row["ready"] is not True:
            raise ValueError("旧教師の準備又は場が不一致")
        barrier = row["barrier"]
        if barrier is None or barrier["outcome"] not in ("250", "125", "期限"):
            raise ValueError("旧使用教師の障壁結果が未知")
        if not A.finite(barrier["end_time"]) or not A.finite(row["recovery_end_time"]) or max(barrier["end_time"], row["recovery_end_time"]) >= evaluation_start:
            raise ValueError("障壁又は回収が評価開始よりstrict前ではない")
        pair = pairs.setdefault(identity["slot_id"], {})
        if identity["side"] in pair:
            raise ValueError("過去教師の重複")
        pair[identity["side"]] = row
    if any(set(pair) != {-1, 1} for pair in pairs.values()):
        raise ValueError("過去教師の片側抜け")
    excluded = [{"slot_id": key, "states": {str(s): pair[s]["status"] for s in (1, -1)}}
                for key, pair in pairs.items() if any(pair[s]["status"] != "確定完結" for s in (1, -1))]
    blocked = {row["slot_id"] for row in excluded}
    leaf_rows = {node["id"]: [] for node in model["nodes"] if node["left"] == -1}
    used = []
    for identity in identities:
        if identity["slot_id"] in blocked:
            continue
        row = measurements[identity["slot_id"], identity["side"]]
        if len(row["operation"]["closed"]) != 1:
            raise ValueError("確定回収は単独一完結が必要")
        leaf, _, _ = walk(model, row["features"])
        closed = row["operation"]["closed"][0]
        value = {**identity, "leaf": leaf, "recovery_end_time": row["recovery_end_time"], "barrier_end_time": row["barrier"]["end_time"],
                 **{f"pnl{fee}": closed[f"pnl{fee}"] for fee in (0, 5, 10)}}
        leaf_rows[leaf].append(value)
        used.append(value)
    leaves = {}
    for leaf, selected in leaf_rows.items():
        sums = {str(f): sum((Decimal(str(r[f"pnl{f}"])) for r in selected), Decimal(0)) for f in (0, 5, 10)}
        unique, days, sessions = len({r["slot_id"] for r in selected}), len({r["session"][:10] for r in selected}), len({r["session"] for r in selected})
        leaves[str(leaf)] = {"leaf": leaf, "direction_rows": len(selected), "unique_slots": unique, "days": days, "sessions": sessions,
            "sum_yen": {f: str(v) for f, v in sums.items()}, "mean_yen": {f: float(v / len(selected)) if selected else None for f, v in sums.items()},
            "support": unique >= 60 and days >= 6 and sessions >= 10, "positive": bool(selected) and sums["5"] > 0, "rows": selected,
            "max_teacher_end": max((max(r["barrier_end_time"], r["recovery_end_time"]) for r in selected), default=None)}
    return {"model_id": model["model_id"], "evaluation_start": evaluation_start, "old_teacher_direction_rows": len(identities),
        "old_teacher_ids_sha256": fingerprint(identities), "input_pairs": len(pairs), "used_pairs": len(pairs) - len(excluded),
        "excluded_pairs": excluded, "used_direction_rows": len(used), "weight_per_direction": .5, "used_rows_sha256": fingerprint(used),
        "leaves": leaves, "classifier_fit_count": 0,
        "meaning": "旧木の全過去教師と回収確定pairの共通部分による葉内記述。未来確率の校正ではない"}


def expected_prediction(model: dict, calibration: dict, vectors: dict, policy: str) -> dict:
    """障壁score最高側へ回収支持と政策別のstrict正額だけを追加する。

    引数: model/calibration(dict)は同じ過去木・葉、vectors(dict)は当時特徴、policy(str)はB0/B1/Q0/Q1。
    返り値: dictは全採否。回帰平均で順位を変えず次点を救済しない。
    """
    if policy not in POLICIES or model["policy"] != policy[0]+"0" or calibration["model_id"] != model["model_id"]:
        raise ValueError("候補又は回収木の対応不正")
    prior = predict(model, vectors)
    side, reason, leaf = prior["side"], prior["reason"], None
    if side:
        leaf = calibration["leaves"][str(prior["leafs"][str(side)])]
        if not leaf["support"]:
            side, reason = 0, "回収支持不足WAIT"
        elif policy.endswith("1") and not leaf["positive"]:
            side, reason = 0, "過去回収平均非正WAIT"
    return {"side": side, "reason": reason, "prior": prior, "recovery_leaf": leaf["leaf"] if leaf else None,
        "recovery_support": leaf["support"] if leaf else None, "recovery_mean5": leaf["mean_yen"]["5"] if leaf else None}


def check_periods(accounts: list[dict], labels: dict, result: dict, source, summary, audit) -> None:
    """旧二対照と新四候補の先着・費用・活動を別集計する。

    引数: accounts/labelsは会計と先着、result(dict)は保存結果、source/summary(ModuleType)/audit(Audit)は純補助。
    返り値: None。単独測定の重複利益や分母1を活動へ流用しない。
    """
    for policy in (*CONTROLS, *POLICIES):
        selected = [row for row in accounts if row["candidate"] == policy]
        for period in PERIODS:
            entry = source.entry_summary(labels[policy], period)
            operation = summary.operation_summary(selected, period, source)
            audit.check(policy + period + ":入口", result["候補"][policy][period]["入口"], entry)
            audit.check(policy + period + ":運用", result["候補"][policy][period]["運用"], operation)
            audit.check(policy + period + ":同時適格", result["候補"][policy][period]["同時適格"], entry["70目標"] and operation["活動適格"] and operation["費用適格"])
            for role in ("順行", "反転"):
                audit.check(policy + period + role, result["役割別入口"][policy][period][role], source.entry_summary([r for r in labels[policy] if r["role"] == role], period))
            if policy in POLICIES:
                reasons = Counter(d["reason"] for row in selected if source.span(row["session"]) == period for d in row["decisions"])
                audit.check(policy + period + ":判断理由", result["判断理由"][policy][period], dict(reasons))
    audit.check("新四候補だけの採用", result["採用"], [p for p in POLICIES if all(result["候補"][p][s]["同時適格"] for s in PERIODS[:2])])


def check_api(base: str | None, resources: list[dict], accounts: list[dict], source, audit) -> dict:
    """276資源と新四候補一代表のAPI約定・台帳を照合する。

    引数: base(str|None)はAPI、resources/accounts(list[dict])は保存値、source(ModuleType)/audit(Audit)は純補助。
    返り値: dictはAPI実行範囲。未指定なら未検証を明記する。
    """
    if not base:
        return {"実行": False, "理由": "--viewer-url未指定。API未検証、新184保存約定は全件照合"}
    query = {"catalog_path": (STUDY / "一覧.resources.json").relative_to(ROOT).as_posix()}
    listing, _, _ = source.fetch_json(base + "/api/resources?" + urlencode(query))
    audit.check("API276全集合", {r["id"] for r in listing["resources"]}, {r["id"] for r in resources})
    audit.check("API資源数", len(listing["resources"]), 276)
    representatives = []
    for policy in POLICIES:
        account = sorted([a for a in accounts if a["candidate"] == policy], key=lambda a: (-abs(a["ledger"]["5"]), a["session"]))[0]
        resource = next(r for r in resources if r["method_id"] == policy and r["session"] == account["session"])
        parameters = {**query, "resource": resource["id"], "interval": "5", "price": "last", "width": 1000, "height": 700}
        meta, _, _ = source.fetch_json(base + "/api/chart?" + urlencode(parameters))
        data, raw, headers = source.fetch_json(urljoin(base + "/", meta["data_url"]))
        audit.check("API本文SHA", hashlib.sha256(raw).hexdigest(), meta["data_sha256"])
        audit.check("APIヘッダSHA", headers.get("x-chart-data-sha256"), meta["data_sha256"])
        audit.check("API集計alias", data["summary"], meta["summary"])
        audit.check("API台帳純額5", Decimal(str(data["summary"]["realized_pnl_yen"])), Decimal(str(account["ledger"]["5"])))
        trades = list(source.json_rows(ROOT / resource["pnl_path"]))
        audit.check("API約定片数", len(data["events"]), len(trades))
        for sequence, (trade, event) in enumerate(zip(trades, data["events"]), 1):
            for key in ("type", "qty", "position_id", "method_id", "price"):
                audit.check("API約定" + key, event[key], trade[key])
            audit.check("API順", event["sequence"], sequence)
            audit.check("API時刻", abs(event["timestamp_ms"] - datetime.fromisoformat(trade["timestamp"]).timestamp() * 1000) <= .001, True)
        representatives.append({"候補": policy, "場": account["session"], "資源ID": resource["id"], "台帳観測5円": account["ledger"]["5"], "数値SHA256": meta["data_sha256"]})
    return {"実行": True, "全資源数": 276, "新政策代表": representatives, "代表規約": "候補別最大絶対台帳観測額。採否へ不使用"}


def episode_support(model: dict, used: list[dict], prepared: dict) -> dict:
    """政策次元で全教師を走査し葉ごとのT/R反復を集計する。

    引数: model(dict)はB0/Q0木、used(list)は使用教師、prepared(dict)は当時60列特徴。
    返り値: dictは全葉統計。slot支持を独立episode支持へ置換しない。
    """
    selected = {node["id"]: [] for node in model["nodes"] if node["left"] == -1}
    for row in used:
        feature, side = prepared[row["slot_id"]], str(row["side"])
        vectors = feature["control_vectors54"] if model["policy"] == "B0" else feature["vectors"]
        leaf, _, _ = walk(model, vectors[side])
        selected[leaf].append(feature["paths"][side])
    return {str(leaf): {"方向行": len(paths), **{role: episode_counts([path[role] for path in paths]) for role in ("T", "R")}}
        for leaf, paths in selected.items()}


def regime_coverage(entries: list, blocks: dict, prepared: dict) -> dict:
    """旧局面八列の既検算被覆をそのまま再集計する。

    引数: entries(list)は66場、blocks/prepared(dict)は旧枠と60特徴。
    返り値: dictは旧63同型の5区間。量の欠測で旧readyを変えない。
    """
    return R63.regime_coverage(entries,blocks,prepared)


def quantity_coverage(entries: list, blocks: dict, prepared: dict) -> dict:
    """全ready方向の段階・共同有効・理由・基準標本数を数える。

    引数: entries(list)は時系列66場、blocks/prepared(dict)は全枠と60特徴。
    返り値: dictは5区間。方向行と独立形成を混同しない。
    """
    ranges = {"全66場":entries,"学習専用20場":entries[:20],"時系列20場":entries[20:40],"条件選択24場":entries[40:64],"既使用2場":entries[64:]}
    output = {}
    for label, selected in ranges.items():
        full = [prepared[s["slot_id"]] for entry in selected for s in blocks[entry["session"]]["slots"]]
        ready = [f for f in full if f["ready"]]
        directions = [f["quantity"][side] for f in ready for side in ("1","-1")]
        item = {"全枠":len(full),"準備枠":len(ready),"未準備枠":len(full)-len(ready),"方向行":len(directions),
            "両ペア有効方向":sum(p["b"]["valid"] and p["r"]["valid"] for p in directions)}
        for event in ("b","r"):
            rows = [p[event] for p in directions]
            item[event] = {"段階あり":sum(r["source"] is not None for r in rows),"ペア有効":sum(r["valid"] for r in rows),
                "既知0量":sum(r["valid"] and r["rvol"] == 0 for r in rows),"理由":dict(Counter(r["reason"] for r in rows)),
                "基準足数":dict(Counter(str(r["baseline"]["count"]) for r in rows if r["baseline"] is not None))}
        output[label] = item
    return output


def run(viewer_url: str | None = None) -> dict:
    """保存された六木と新184運用をfit・市場再生なしで独立監査する。

    引数: viewer_url(str|None)は任意のViewer API。
    返り値: dictは全差・原典と結果の指紋・Viewer範囲。既存proofは上書きしない。
    """
    destination = STUDY/"保存物確認.json"
    if destination.exists():
        raise FileExistsError("保存物確認.jsonを上書きしません")
    source,label_helper,summary=A.helpers()
    audit=source.Audit()
    files=[STUDY/name for name in ("結果.json","固定.json","条件.json","入力台帳.json","一覧.resources.json")]
    files += [WORK/name for name in ("定時判断と運用.jsonl.gz","入口先着.jsonl.gz")]
    files += [ROOT/"work/量と価格進行/教師接続確認.json",COMPLETE,MEASUREMENTS,FRAMES,SLOTS50,QUANTITY_PATH,source.MANIFEST]
    files += [OLD/name for name in ("結果.json","固定.json","保存物確認.json","一覧.resources.json")]
    files += [OLDWORK/name for name in ("定時判断と運用.jsonl.gz","入口先着.jsonl.gz","保存検証_実行.log")]
    files += [Path(__file__),Path(__file__).with_name("学習.py"),Path(__file__).with_name("特徴.py"),Path(__file__).with_name("監査人工.py"),Path(__file__).with_name("監査仕様.md")]
    before={path.relative_to(ROOT).as_posix():source.sha(path) for path in files}
    fixed,result=source.read(STUDY/"固定.json"),source.read(STUDY/"結果.json")
    for name,digest in fixed["ファイルSHA256"].items():
        audit.check("固定出典:"+name,source.sha(ROOT/name),digest)
    audit.check("監査自己の固定包含",Path(__file__).relative_to(ROOT).as_posix() in fixed["ファイルSHA256"],True)
    audit.check("完全50slot固定包含",fixed["ファイルSHA256"][SLOTS50.relative_to(ROOT).as_posix()],source.sha(SLOTS50))
    audit.check("試行・固定bind",(result["試行"],result["固定SHA256"]),(64,source.sha(STUDY/"固定.json")))
    audit.check("全六候補",set(result["候補"]),{*CONTROLS,*POLICIES})
    audit.check("新fit種別・独立・運用",(result["新分類器fit"],result["新独立計測"],result["新運用数"]),(0,0,184))
    previous,previous_proof,_=check_reused_proof(source,audit)
    entries=source.read(source.MANIFEST)["entries"]
    phases=A.phases(entries,source)
    evaluated=[entry["session"] for entry in entries[20:]]
    audit.check("評価46場順",result["評価場"],evaluated)
    audit.check("初期20場学習専用",result["学習専用場"],[e["session"] for e in entries[:20]])
    audit.check("旧63モデルmetadata",result["対照モデル"],previous["モデル"])
    audit.check("旧準備比較全辞書",result["準備比較"],previous["準備比較"])
    audit.check("測定保存再用",result["独立測定"],previous["独立測定"])
    audit.check("旧63対照参照",result["対照参照"],{"候補":list(CONTROLS),"元試行":63,"同じ評価46場":True,"市場再生":False})
    audit.check("測定参照",result["独立測定参照"],{"元試行":55,"path":MEASUREMENTS.relative_to(ROOT).as_posix(),"sha256":source.sha(MEASUREMENTS),"再計測":False})
    measurements,old_slots,features,baseline=R56.saved_measurements(source,audit)
    prepared,quantity_counts=prepare_features(old_slots,features,source,audit)
    variants={"B0":{identity:control_projection(feature) for identity,feature in prepared.items()},"Q0":prepared}
    measured={policy:{key:{**row,"features":variants[policy][row["slot_id"]]["vectors"][str(row["side"])]} for key,row in measurements.items()} for policy in ("B0","Q0")}
    teacher_blocks={e["session"]:{"slots":[slot for slot in old_slots.values() if slot["session"]==e["session"]]} for e in entries}
    preflight=source.read(ROOT/"work/量と価格進行/教師接続確認.json")
    audit.check("fit前全特徴指紋",fingerprint(prepared),preflight["全特徴SHA256"])
    for key,value in (("価格経路分布",path_coverage(entries,teacher_blocks,prepared)),("局面分布",regime_coverage(entries,teacher_blocks,prepared)),("数量分布",quantity_coverage(entries,teacher_blocks,prepared))):
        audit.check("fit前"+key,value,preflight[key])
        audit.check("結果"+key,value,result[key])
    old_blocks,saved_features,old_matches={}, {},0
    for block in source.json_rows(OLDWORK/"定時判断と運用.jsonl.gz"):
        key=block["session"],block["policy"]
        if key in old_blocks or block["policy"] not in CONTROLS:
            raise ValueError("旧63場候補の重複又は範囲外")
        old_blocks[key]=block
        for slot in block["slots"]:
            identity,feature=slot["slot_id"],slot["feature"]["base"]
            audit.check("旧63保存54全辞書",control_projection(prepared[identity]),slot["feature"])
            old_matches+=1
            audit.check("55検証済み18必要項目",{key:feature[key] for key in features[identity]},features[identity])
            if identity in saved_features:
                audit.check("旧二候補特徴全同値",feature,saved_features[identity])
            saved_features[identity]=feature
    audit.check("旧92集合",set(old_blocks),{(session,policy) for session in evaluated for policy in CONTROLS})
    detail=defaultdict(list)
    for block in source.json_rows(WORK/"定時判断と運用.jsonl.gz"):
        detail[block["session"]].append(block)
    audit.check("新詳細46場",set(detail),set(evaluated))
    labels={policy:[] for policy in (*CONTROLS,*POLICIES)}
    for row in source.json_rows(OLDWORK/"入口先着.jsonl.gz"):
        labels[row["policy"]].append(row)
    sequence=list(source.json_rows(WORK/"入口先着.jsonl.gz"))
    labels_by_session=defaultdict(list)
    for row in sequence:
        labels_by_session[row["session"]].append(row)
    resources=source.read(STUDY/"一覧.resources.json")["resources"]
    resource_map={(row["session"],row["method_id"]):row for row in resources}
    audit.check("276資源全集合",set(resource_map),{(session,policy) for session in evaluated for policy in (*CONTROLS,*POLICIES)})
    audit.check("276資源一意",(len(resources),len({row["id"] for row in resources})),(276,276))
    for row in source.read(OLD/"一覧.resources.json")["resources"]:
        if row["method_id"] in CONTROLS:
            audit.check("旧92資源全属性",resource_map[row["session"],row["method_id"]],row)
            audit.check("旧Viewer固定包含",row["pnl_path"] in fixed["ファイルSHA256"],True)
    model_pins,models,calibrations,teacher_matches,set_matches={},{},{},{},{}
    for meta in previous["モデル"]+previous["対照モデル"]+previous["回収集計"]:
        model_pins[meta["path"]]=source.sha(ROOT/meta["path"])
    manifests={(meta["phase"],meta["policy"]):meta for meta in result["モデル"]}
    cal_manifests={(meta["phase"],meta["policy"]):meta for meta in result["回収集計"]}
    audit.check("六木順",[(m["phase"],m["policy"]) for m in result["モデル"]],[(p["id"],policy) for p in phases for policy in ("B0","Q0")])
    audit.check("六回収順",[(m["phase"],m["policy"]) for m in result["回収集計"]],[(p["id"],policy) for p in phases for policy in ("B0","Q0")])
    fits=0
    for phase in phases:
        phase_id=phase["id"]
        old_path=OLD/"models"/("J0_"+phase_id+".json")
        old_model=source.read(old_path)
        relative=old_path.relative_to(ROOT).as_posix()
        model_pins[relative]=source.sha(old_path)
        audit.check("旧63木成功bind",model_pins[relative],previous_proof["モデルSHA256"][relative])
        _,barrier_training,_=A.training_rows(phase["train"],teacher_blocks,features,baseline,phase["evaluation_start"],18)
        keys=("input_rows_sha256","used_rows_sha256","row_ids_sha256","period_sha256")
        teacher_matches[phase_id]={key:barrier_training[key]==old_model["training"]["barrier_fingerprints"][key] for key in keys}
        audit.check("旧教師四指紋:"+phase_id,teacher_matches[phase_id],dict.fromkeys(keys,True))
        raw60=R56.recovery_input(phase["train"],teacher_blocks,prepared,measured["Q0"])
        cal_old=source.read(OLD/"models"/("回収_"+phase_id+".json"))
        old_cal_ids=[{key:row[key] for key in ("session","slot_id","side")} for leaf in cal_old["leaves"].values() for row in leaf["rows"]]
        phase_ids=None
        for policy,count in (("B0",54),("Q0",60)):
            identity=policy+"_"+phase_id
            raw=[{**row,"features":row["features"][:count]} for row in raw60]
            used,training=recovery_training(raw,phase["evaluation_start"],count)
            for key in (*FINGERPRINT_FIELDS,"base18_fingerprints","base30_fingerprints","base38_fingerprints","base46_fingerprints","base54_fingerprints"):
                audit.check("fit前教師:"+identity+key,training[key],preflight["期間"][phase_id][policy][key])
            ids=[{key:row[key] for key in ("session","slot_id","side")} for row in used]
            audit.check("同一旧木使用ID:"+identity,ids,old_model["training"]["row_ids"])
            audit.check("同一旧回収ID集合:"+identity,sorted(ids,key=lambda r:(r["slot_id"],r["side"])),sorted(old_cal_ids,key=lambda r:(r["slot_id"],r["side"])))
            if phase_ids is not None:
                audit.check("B/Q同一教師順:"+phase_id,ids,phase_ids)
            phase_ids=ids
            set_matches[phase_id]=ids==old_model["training"]["row_ids"]
            for key in ("base18_fingerprints","base30_fingerprints","base38_fingerprints","base46_fingerprints"):
                audit.check("旧prefix全指紋:"+identity+key,training[key],old_model["training"][key])
            audit.check("旧54六指紋:"+identity,training["base54_fingerprints"],{key:old_model["training"][key] for key in FINGERPRINT_FIELDS})
            if policy=="Q0":
                distribution=state_distribution(used,prepared)
                audit.check("fit前旧四群診断:"+phase_id,distribution,preflight["状態分布"][phase_id])
                audit.check("結果旧四群診断:"+phase_id,distribution,result["状態分布"][phase_id])
            path=STUDY/"models"/(identity+".json")
            model=source.read(path)
            digest=source.sha(path)
            model_pins[path.relative_to(ROOT).as_posix()]=digest
            check_model(model,used,training,feature_metadata(count),identity,source.sha(Path(__file__).with_name("学習.py")),audit)
            audit.check("全葉episode:"+identity,result["経路支持"][identity],episode_support(model,used,prepared))
            audit.check("新木metadata",manifests[phase_id,policy],{"id":identity,"policy":policy,"phase":phase_id,"path":path.relative_to(ROOT).as_posix(),"SHA256":digest,
                "学習場":[e["session"] for e in phase["train"]],"評価場":[e["session"] for e in phase["evaluation"]],"特徴数":count,"評価開始":phase["evaluation_start"]})
            fits+=sum(part["fit_performed"] for part in model["training"]["partition"].values())
            cal_path=STUDY/"models"/("回収_"+identity+".json")
            calibration=expected_calibration(model,measured[policy],phase["evaluation_start"])
            calibration.update(policy=policy,phase=phase_id,base_model_path=path.relative_to(ROOT).as_posix(),base_model_sha256=digest)
            audit.check("新全葉回収",source.read(cal_path),calibration)
            cal_digest=source.sha(cal_path)
            model_pins[cal_path.relative_to(ROOT).as_posix()]=cal_digest
            audit.check("回収metadata",cal_manifests[phase_id,policy],{"id":identity,"policy":policy,"phase":phase_id,"path":cal_path.relative_to(ROOT).as_posix(),"SHA256":cal_digest})
            models[phase_id,policy],calibrations[phase_id,policy]=model,calibration
        print(phase_id+" 二種類の全node/教師/回収保存照合",flush=True)
    audit.check("新fit数",result["新回帰器fit"],fits)
    audit.check("最大12fit",fits<=12,True)
    audit.check("旧教師一致表示",result["旧教師一致"],teacher_matches)
    audit.check("教師集合一致表示",result["教師集合一致"],set_matches)
    accounts,summaries,cache_pins,viewer_pins,mixed_slots,closed_matches=[],[],{},{},0,0
    for entry in entries[20:]:
        session=entry["session"]
        phase=next(p for p in phases if session in {e["session"] for e in p["evaluation"]})
        phase_id=phase["id"]
        tape,cache_path,digest,input_quality=R55.load_tape(entry,source,audit)
        cache_pins[cache_path]=digest
        audit.check("原tapeの63bind",digest,previous_proof["キャッシュSHA256"][cache_path])
        for policy in CONTROLS:
            accounts.append(P.account(old_blocks[session,policy]["operation"],source,audit))
        audit.check("新四候補順",[block["policy"] for block in detail[session]],list(POLICIES))
        choices={}
        for block in detail[session]:
            policy,operation=block["policy"],block["operation"]
            parent=policy[0]+"0"
            model,calibration=models[phase_id,parent],calibrations[phase_id,parent]
            audit.check("新運用識別",(operation["candidate_id"],operation["session"],block["phase"]),(policy,session,phase_id))
            audit.check("入力品質",block["input_quality"],input_quality)
            source.check_decisions(block,tape,audit)
            source.check_orders(operation,tape,audit)
            source.check_trail(operation,tape,audit)
            for closed in operation["closed"]:
                counterpart=measurements[closed["slot_id"],closed["side"]]["operation"]["closed"]
                audit.check("同一新規単独一完結",len(counterpart),1)
                if counterpart:
                    audit.check("同一新規完結型値",R55.strict_close_equal(closed,counterpart[0]),True)
                closed_matches+=1
            path=ROOT/resource_map[session,policy]["pnl_path"]
            audit.check("Viewer正規保存先",path.resolve(),(STUDY/"viewer"/f"{policy}_{session}.trades.jsonl").resolve())
            viewer_pins[path.relative_to(ROOT).as_posix()]=source.sha(path)
            accounts.append(source.check_cash(operation,list(source.json_rows(path)),tape,audit))
            summaries.append({"場":session,"候補":policy,"期間":source.span(session),"入力品質":input_quality,"運用品質":operation["quality"],"運用集計":operation["metrics"]})
            choices[policy]={}
            for slot in block["slots"]:
                mixed_slots+=1
                identity=slot["slot_id"]
                feature,old=variants[parent][identity],old_slots[identity]
                predicted=expected_prediction(model,calibration,feature["vectors"],policy) if feature["ready"] else None
                side,reason=(predicted["side"],predicted["reason"]) if predicted else (0,feature["reason"])
                if side and feature["background_direction"]==0:
                    side,reason=0,"上位DI同値の役割未確定WAIT"
                role="待機" if not side else "順行" if side==feature["background_direction"] else "反転"
                expected={**{key:old[key] for key in BINDING},"policy":policy,"phase":phase_id,"model_id":model["model_id"],
                    "side":side,"role":role,"ready":feature["ready"],"reason":reason,"atr":feature["atr"],"D":feature["D"],"feature":feature,"prediction":predicted}
                audit.check("新slot全内容/採否",slot,expected)
                if side:
                    labels[policy].append({**baseline[identity,side],"policy":policy,"role":role})
                choices[policy][identity]=side
        for parent,child in (("B0","B1"),("Q0","Q1")):
            audit.check(child+"は同方向純subset",all(not side or choices[parent][key]==side for key,side in choices[child].items()),True)
        for row in labels_by_session[session]:
            _,force,_,_=source.calendar(session)
            expected={**{key:row[key] for key in (*BINDING,"policy","side","role")},**label_helper.first_force_expected(tape,row,force,source)}
            audit.check("先着原BBO全属性",row,expected)
        print(session+" 新四運用の保存照合",flush=True)
    audit.check("新6808定時枠",mixed_slots,6808)
    audit.check("主内全13保存照合数",result["検査"],expected_counts(previous["検査"],old_matches,closed_matches,quantity_counts))
    # preflightの完結数は0、正式の新規数と分離する。
    audit.check("fit前全13照合数",preflight["検査"],expected_counts(previous["検査"],old_matches,0,quantity_counts))
    audit.check("先着コピーと順序",sequence,[row for policy in POLICIES for row in labels[policy]])
    audit.check("全場別表示",result["場別"],summaries)
    check_periods(accounts,labels,result,source,summary,audit)
    for policy in CONTROLS:
        audit.check("旧保存対照全期間",result["候補"][policy],previous["候補"][policy])
        audit.check("旧役割対照",result["役割別入口"][policy],previous["役割別入口"][policy])
    audit.check("新詳細二系列",set(result["詳細"]),{"定時判断と運用.jsonl.gz","入口先着.jsonl.gz"})
    for name,digest in result["詳細"].items():
        audit.check("詳細SHA:"+name,source.sha(WORK/name),digest)
    api=check_api(viewer_url,resources,accounts,source,audit)
    for name,digest in {**before,**model_pins,**viewer_pins}.items():
        audit.check("実行中不変:"+name,source.sha(ROOT/name),digest)
    payload={"試行":64,"確認日時":datetime.now(source.JST).isoformat(),"全件一致":audit.bad==0,"照合項目数":audit.count,"不一致数":audit.bad,"不一致":audit.examples,
        "結果SHA256":source.sha(STUDY/"結果.json"),"本物fit再実行":False,"市場戦略再生":False,"新独立計測":False,"新主処理import":False,"55測定再監査":False,
        "再用方向行数":len(measurements),"新運用数":184,"新予定比較数":mixed_slots,"回帰木数":len(models),"回収集計数":len(calibrations),"回帰器保存fit数":fits,
        "数量出典照合":quantity_counts,"参照SHA256":before,"モデルSHA256":model_pins,"キャッシュSHA256":cache_pins,"新Viewer約定SHA256":viewer_pins,"ViewerAPI":api,
        "検証範囲":"63初回未完/接続補足成功と完了台帳の版連鎖。旧46縮約経路・完全50枠接続・旧54独立算術と保存射影、固定Q11全SOURCEと過去10場TOD/イベント価格ペア、新54/60二構造の全node/二群/教師/回収/予測、全新184運用の注文・現金・BBO・追尾・先着・費用・全予定活動、Viewer全276。",
        "限定":"旧55独立測定の再計測・新raw・本物fit・最良閾値探索・市場戦略再生なし。状態四群は木の二群とは別の保存診断。量と価格の一致・葉内平均は心理因果や未見利益を証明しない。"}
    destination.write_text(json.dumps(payload,ensure_ascii=False,indent=2,allow_nan=False)+"\n",encoding="utf-8")
    return payload


def self_test() -> dict:
    """別ファイルの人工を主処理から独立して起動する。

    引数: なし。
    返り値: dictは人工成功/差数。実教師・本物fit・市場は読まない。
    """
    artificial = load(Path(__file__).with_name("監査人工.py"), "再試験保存監査の独立人工")
    return artificial.self_test()


def main() -> None:
    """人工又はroot正式保存監査を上書きせず起動する。

    引数: CLIの--self-test/--run、任意--viewer-url。
    返り値: None。不一致は終了1、既存正式proofは拒否する。
    """
    parser = argparse.ArgumentParser(description="64のDI一根・54/60列量価格・二種類の木・184保存運用の独立監査")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--self-test", action="store_true")
    group.add_argument("--run", action="store_true")
    parser.add_argument("--viewer-url")
    args = parser.parse_args()
    proof = self_test() if args.self_test else run(args.viewer_url)
    print(json.dumps(proof, ensure_ascii=False, indent=2, allow_nan=False))
    if proof["不一致数"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
