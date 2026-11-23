"""固定61特徴の直近六終値から集中・効率・最大一足方向を共通準備で追加する。"""

from collections import Counter
from copy import deepcopy
from fractions import Fraction
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
PREVIOUS_PATH = HERE.parent / "支持を満たす技法分割/検証.py"
PREVIOUS_SHA = "852798780db71ee175c32a76907f4ce887256c864af646007e530484ebb498a0"


def load(path: Path, name: str):
    """固定コードを固有名で読み、旧大域値を変更しない。

    引数: path(Path)は対象、name(str)は固有module名。
    返り値: ModuleTypeは読込結果。市場・学習の関数は起動しない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


if hashlib.sha256(PREVIOUS_PATH.read_bytes()).hexdigest() != PREVIOUS_SHA:
    raise ValueError("固定72主コードの指紋差")
PREVIOUS = load(PREVIOUS_PATH, "直近73の固定72主")
I72 = PREVIOUS.I
I71 = I72.I71
I69, C, P, O, F = I72.I69, I72.C, I72.P, I72.O, I72.F
STUDY = ROOT / "study/00073_直近の集中と方向効率を組み合わせる"
PARENT = ROOT / "work/直近進行の集中と効率"
WORK = PARENT / "00073"
PREFLIGHT = PARENT / "入力接続確認.json"
OLD, OLDWORK = PREVIOUS.STUDY, PREVIOUS.WORK
SOURCE, SOURCEWORK = I72.SOURCE, I72.SOURCEWORK
LEDGER = I72.PARENT / "72完了記録.json"
LEDGER_SHA = "2ded91aa2154f6a6202bfcc224126f88433f013498d49ab9a7dfb7850945fe1a"
IDENTITY = I72.IDENTITY
BASE_FEATURES = deepcopy(I72.FEATURES)
ADDITIONAL_FEATURES = [{"id": f"F{index}", "name": name, "method": "P05", "family": "price", "scale": "m03"}
    for index, name in ((62, "直近一足集中率"), (63, "直近方向効率"), (64, "最大一足の方向"))]
FEATURES = [*deepcopy(BASE_FEATURES), *deepcopy(ADDITIONAL_FEATURES)]
FEATURE_COUNTS = {"B0": 61, "Q0": 64}
SOURCE_FIELDS = ("session", "index", "minutes", "start", "end", "confirm", "confirm_line", "publish", "missing", "open", "high", "low", "close")
FIELDS = SOURCE_FIELDS
N = 5
RULES = {"入力": "固定72の同61特徴・当時公開SOURCEを再用。新市場取得・新指標銀行・新ラベル計測なし",
    "窓": "旧53履歴のreference_sources末1本(j-5)とreaction_sources5本(j-4..j)。6終値から5差分、窓延長・欠足補間・他場carryなし",
    "時計": "全6SOURCEは当場完全3分・missing0・公開済み、end<=予定、confirm原行<=実判断。最後は旧currentと全文一致",
    "隣接": "index+1・前end=次start・公開key strict増加。非公開/欠足/不完全は共通準備落ち、不正schema/出典不一致は停止",
    "差分": "古い順のcloseをFraction(str(value))へ写して5終値差分。TV=絶対差分和でATRとは別",
    "F62": "C=max(abs(d))/TV。TV>0なら買売同値、範囲1/5..1",
    "F63": "E=s*sum(d)/TV。範囲-1..1、純進行0でもTV>0なら既知0",
    "F64": "J=s*sign(max(d)+min(d))。正負の最大絶対値が同値なら既知0、値は-1/0/+1",
    "準備": "旧readyFalseを保持。欠足/未公開/TV0ではB61/Q64ともreadyFalse・両vector空。未知を0や新maskで補完しない",
    "投影": "old_projectionは元61全文、baseline_projectionは共通準備61。旧準備と共通準備の構成差を分ける",
    "鏡像": "価格をa-priceへ反射しsideも反転すると対応C/E/J同値。両側同枠ではC同値・E/J反対符号",
    "順序の限定": "C/E/Jは差分の並替不変。最新急進や失速・再開の順序を識別したとはしない。元差分/全出典を診断に保持",
    "技法票": "3列は全P05/price/m03。既存価格の加工で独立family票を増やさない",
    "同条件": "61対照と64追加は同じ共通ready・同じ現在情報を使う。旧72S0/S1は保存参考で再生しない"}


# ----------------------------------------
def finite(value: object) -> bool:
    """boolを除いた有限な保存数値を判定する。

    引数: value(object)は保存値。
    返り値: boolは有限int/floatの場合に真。
    """
    return type(value) in (int, float) and math.isfinite(value)


def same(a: object, b: object) -> bool:
    """保存JSONの型も含めて同値を判定する。

    引数: a/b(object)は保存辞書等。
    返り値: boolはkey順以外が同じ場合に真。旧辞書を変更しない。
    """
    return json.dumps(a, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=True) == json.dumps(
        b, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=True)


def exact(value: Fraction) -> dict:
    """有理数を有限表示値と既約分子分母へ分ける。

    引数: value(Fraction)は計算値。
    返り値: dictはvalue/numerator/denominator。表示範囲外は停止する。
    """
    try:
        shown = float(value)
    except OverflowError as exc:
        raise ValueError("直近算術のfloat64表示範囲外") from exc
    if not math.isfinite(shown):
        raise ValueError("直近算術の有限表示不成立")
    return {"value": shown, "numerator": value.numerator, "denominator": value.denominator}


def source_schema(row: object, session: str) -> None:
    """SOURCE13の形・型・同場性を価格計算より先に検査する。

    引数: row(object)は一足、session(str)は当場。
    返り値: None。不正schemaや他場混入は補完せず停止する。
    """
    if not isinstance(row, dict) or not set(SOURCE_FIELDS) <= set(row):
        raise ValueError("直近SOURCE13の項目不足")
    if (row["session"] != session or type(row["index"]) is not int or row["index"] < 0
            or type(row["minutes"]) is not int or row["minutes"] != 3
            or type(row["confirm_line"]) is not int or row["confirm_line"] < 0
            or type(row["publish"]) is not bool or type(row["missing"]) is not int or row["missing"] < 0
            or not all(finite(row[key]) for key in ("start", "end", "confirm"))):
        raise ValueError("直近SOURCEの場・型・時計schema不正")


def recent_values(slot: dict, old_feature61: dict) -> dict:
    """既存履歴の六公開終値だけから共通準備とC/E/Jを求める。

    引数: slot(dict)は判断identity、old_feature61(dict)は元61特徴。
    返り値: dictは旧準備・理由・6SOURCE・5差分・TV・精密3値・最大差分出典。
        教師・未来価格・実約定・保有は参照しない。
    """
    old = old_feature61
    if (not isinstance(old, dict) or type(old.get("ready")) is not bool or not isinstance(old.get("reason"), str)
            or not isinstance(old.get("vectors"), dict) or set(old["vectors"]) != {"1", "-1"}):
        raise ValueError("元61特徴のschema不正")
    expected = 61 if old["ready"] else 0
    if any(not isinstance(vector, list) or len(vector) != expected for vector in old["vectors"].values()):
        raise ValueError("元61特徴のvector長不正")
    result = {"n": N, "old_ready": old["ready"], "old_reason": old["reason"], "valid": False,
        "reason": old["reason"] if not old["ready"] else "", "sources": [], "deltas": [], "deltas_exact": [],
        "TV": None, "values": {"1": [], "-1": []}, "exact": {"1": [], "-1": []}, "largest": None}
    if not old["ready"]:
        return result
    if (not isinstance(slot, dict) or not isinstance(slot.get("session"), str) or not slot["session"]
            or not isinstance(slot.get("slot_id"), str) or not slot["slot_id"]
            or not all(finite(slot.get(key)) for key in ("scheduled", "time")) or slot["time"] < slot["scheduled"]
            or type(slot.get("line")) is not int or slot["line"] <= 0):
        raise ValueError("判断identity/時計schema不正")
    try:
        history = old["base"]["history"]
        current = old["base"]["base"]["sources"]["current"]
        reference, reaction = history["reference_sources"], history["reaction_sources"]
    except (KeyError, TypeError) as exc:
        raise ValueError("元61の局所履歴schemaなし") from exc
    if not isinstance(reference, list) or not isinstance(reaction, list):
        raise ValueError("元61の参照/反応SOURCE配列不正")
    if not reference or len(reaction) != N:
        result["reason"] = "直近六終値のSOURCE不足"
        return result
    rows = [reference[-1], *reaction]
    for row in [*rows, current]:
        source_schema(row, slot["session"])
    if len({row["index"] for row in rows}) != N + 1:
        raise ValueError("直近SOURCEの番号重複")
    projected = [{key: deepcopy(row[key]) for key in SOURCE_FIELDS} for row in rows]
    if not same(projected[-1], {key: current[key] for key in SOURCE_FIELDS}):
        raise ValueError("直近最後SOURCEと旧currentの全文差")
    result["sources"] = projected
    limit = slot["time"], slot["line"]
    for row in rows:
        if row["end"] > slot["scheduled"] or (row["confirm"], row["confirm_line"]) > limit:
            result["reason"] = "直近六終値に当時未公開の足"
            return result
        if (not row["publish"] or row["missing"] != 0 or row["end"] - row["start"] != 180
                or row["confirm"] < row["end"]):
            result["reason"] = "直近六終値に非公開・欠枠・不完全足"
            return result
        if (not all(finite(row[key]) and row[key] > 0 for key in ("open", "high", "low", "close"))
                or not row["low"] <= min(row["open"], row["close"]) <= max(row["open"], row["close"]) <= row["high"]):
            raise ValueError("当時可視な直近足のOHLC不正")
    if any(b["index"] != a["index"] + 1 or a["end"] != b["start"]
            or (a["confirm"], a["confirm_line"]) >= (b["confirm"], b["confirm_line"])
            for a, b in zip(rows, rows[1:])):
        result["reason"] = "直近六終値の番号・終了・公開順不連続"
        return result
    closes = [Fraction(str(row["close"])) for row in rows]
    differences = [b - a for a, b in zip(closes, closes[1:])]
    total = sum(map(abs, differences), Fraction(0))
    result.update(deltas=[exact(value)["value"] for value in differences], deltas_exact=[exact(value) for value in differences], TV=exact(total))
    if total == 0:
        result["reason"] = "直近五差分の総変動TVが0"
        return result
    maximum = max(map(abs, differences))
    signed_extremes = max(differences) + min(differences)
    sign = int(signed_extremes > 0) - int(signed_extremes < 0)
    extrema = [{"from_index": rows[i]["index"], "to_index": rows[i + 1]["index"],
        "from_key": [rows[i]["confirm"], rows[i]["confirm_line"]],
        "to_key": [rows[i + 1]["confirm"], rows[i + 1]["confirm_line"]],
        "sign": int(value > 0) - int(value < 0)} for i, value in enumerate(differences) if abs(value) == maximum]
    result["largest"] = {"absolute": exact(maximum), "max_delta": exact(max(differences)), "min_delta": exact(min(differences)),
        "direction": sign, "mixed_tie": len({row["sign"] for row in extrema}) > 1, "sources": extrema}
    for side in (1, -1):
        values = [maximum / total, side * sum(differences, Fraction(0)) / total, Fraction(side * sign)]
        result["exact"][str(side)] = [exact(value) for value in values]
        result["values"][str(side)] = [exact(value)["value"] for value in values]
    result.update(valid=True, reason="")
    return result


# ----------------------------------------
def extend(slot: dict, old_feature61: dict) -> tuple:
    """同じ共通準備の61対照と64追加を作り、元61を復元可能に保つ。

    引数: slot(dict)は判断、old_feature61(dict)は固定特徴。
    返り値: tuple[dict,dict]はpreparedB/preparedQ。旧辞書とvectorを変更しない。
    """
    recent = recent_values(slot, old_feature61)
    baseline = deepcopy(old_feature61)
    baseline.update(control_vectors61=deepcopy(old_feature61["vectors"]), recent_progress=recent)
    baseline["ready"] = bool(old_feature61["ready"] and recent["valid"])
    if not baseline["ready"]:
        baseline.update(reason=recent["reason"], vectors={"1": [], "-1": []})
    additional = deepcopy(baseline)
    if baseline["ready"]:
        additional["vectors"] = {side: [*baseline["vectors"][side], *recent["values"][side]] for side in ("1", "-1")}
    return baseline, additional


def old_projection(feature: dict) -> dict:
    """共通準備の変化と追加列を除き、固定旧61全文を復元する。

    引数: feature(dict)はB又はQ特徴。
    返り値: dictは元61のready/reason/vectorsを戻した深いコピー。
    """
    result = deepcopy(feature)
    progress = result.pop("recent_progress")
    vectors = result.pop("control_vectors61")
    result.update(ready=progress["old_ready"], reason=progress["old_reason"], vectors=vectors)
    return result


def baseline_projection(feature: dict) -> dict:
    """64追加特徴を同じ共通準備の61対照へ射影する。

    引数: feature(dict)はQ特徴。
    返り値: dictはready/reasonと診断を保持し、ready時のvectorsだけ61列へ戻すコピー。
    """
    result = deepcopy(feature)
    if result["ready"]:
        result["vectors"] = {side: vector[:61] for side, vector in result["vectors"].items()}
    return result


def verify_previous() -> dict:
    """72完了台帳・成功監査・単一完了の指紋を確認する。

    引数: なし。
    返り値: dictは旧72結果。旧市場とモデルを再実行しない。
    """
    if C.sha(LEDGER) != LEDGER_SHA:
        raise ValueError("72完了台帳の固定SHA差")
    for relative, expected in C.read_json(LEDGER)["成果物SHA256"].items():
        if C.sha(ROOT / relative) != expected:
            raise ValueError("72完了成果物変更:" + relative)
    proof, done = C.read_json(OLD / "保存物確認.json"), C.read_json(OLDWORK / "実行完了.json")
    if (not proof["全件一致"] or proof["不一致数"] or proof["結果SHA256"] != C.sha(OLD / "結果.json")
            or done["結果SHA256"] != proof["結果SHA256"]):
        raise ValueError("72成功証拠の不一致")
    return C.read_json(OLD / "結果.json")


def verified_inputs() -> tuple:
    """同じ旧入力を再用し、共通準備B/Qを全予定枠へ付加する。

    引数: なし。
    返り値: tupleは旧9要素のS保存参考への変更とpreparedB/preparedQを末尾に加えた計11要素。
        rootの事前接続・固定後入力照合時に実行し、新ラベル・学習・市場再生をしない。
    """
    verify_previous()
    entries, blocks, base60, extended61, immediate, conditions, measured, _, inherited = I72.verified_inputs()
    if inherited != C.read_json(I72.PREFLIGHT)["検査"]:
        raise ValueError("72入力接続確認の差")
    old = [row for row in P.read_rows(OLDWORK / "定時判断と運用.jsonl.gz") if row["policy"] in ("S0", "S1")]
    if len(old) != 92 or len({(row["session"], row["policy"]) for row in old}) != 92:
        raise ValueError("旧72S保存92運用の集合差")
    saved_count = 0
    for block in old:
        for slot in block["slots"]:
            if not same(slot["feature"], extended61[slot["slot_id"]]):
                raise ValueError("旧72S保存61特徴との全文差")
            saved_count += 1
    preparedB, preparedQ, reasons, phase_counts = {}, {}, Counter(), {}
    for block in blocks.values():
        for slot in block["slots"]:
            identity = slot["slot_id"]
            if identity in preparedB:
                raise ValueError("全予定枠IDの重複")
            old_feature = extended61[identity]
            b, q = extend(slot, old_feature)
            if not same(old_projection(b), old_feature) or not same(old_projection(q), old_feature) or not same(baseline_projection(q), b):
                raise ValueError("旧61投影又は共通B/Q射影差")
            preparedB[identity], preparedQ[identity] = b, q
            if old_feature["ready"] and not b["ready"]:
                reasons[b["reason"]] += 1
    for name, group in (("全66", entries), ("学習専用20", entries[:20]), ("時系列検査20", entries[20:40]),
            ("条件選択24", entries[40:64]), ("既使用後続2", entries[64:])):
        ids = [slot["slot_id"] for entry in group for slot in blocks[entry["session"]]["slots"]]
        phase_counts[name] = {"全予定枠": len(ids), "旧準備済み枠": sum(extended61[key]["ready"] for key in ids),
            "共通準備済み枠": sum(preparedB[key]["ready"] for key in ids),
            "旧準備からの落ち": sum(extended61[key]["ready"] and not preparedB[key]["ready"] for key in ids)}
    checks = {"72の入力検査": inherited, "旧S保存運用": len(old), "旧S保存特徴照合": saved_count,
        "全予定枠": len(extended61), "旧準備済み枠": sum(feature["ready"] for feature in extended61.values()),
        "共通準備済み枠": sum(feature["ready"] for feature in preparedB.values()), "共通準備落ち理由": dict(reasons),
        "準備分布": phase_counts, "旧61全文投影一致": len(preparedB), "共通B/Q射影一致": len(preparedQ),
        "旧61特徴SHA256": I69.fingerprint(extended61), "B61特徴SHA256": I69.fingerprint(preparedB),
        "Q64特徴SHA256": I69.fingerprint(preparedQ), "条件SHA256": I69.fingerprint(conditions), "参照独立方向": len(measured)}
    if len(preparedB) != 2442 or len(preparedQ) != 2442 or saved_count != 3404:
        raise ValueError("73予定枠又は保存特徴比較数の差")
    return entries, blocks, base60, extended61, immediate, conditions, measured, old, checks, preparedB, preparedQ


def preflight() -> dict:
    """本物学習前に旧投影と新共通準備の内容を一度保存する。

    引数: なし。
    返り値: dictは入力接続だけの成功証拠。root以外は実行しない。
    """
    if PREFLIGHT.exists():
        raise FileExistsError("73入力接続確認は保存済み")
    values = verified_inputs()
    result = {"試行": 73, "接続成功": True, "入力コードSHA256": C.sha(Path(__file__)),
        "旧72台帳SHA256": LEDGER_SHA, "検査": values[8], "新fit": 0, "新市場再生": 0}
    C.write_json(PREFLIGHT, result)
    return result


if __name__ == "__main__":
    print(json.dumps(preflight(), ensure_ascii=False, allow_nan=False), flush=True)
