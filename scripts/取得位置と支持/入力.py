"""既知の上位端と当時の新規気配を結び、同じ60特徴へ取得位置を加える。"""

from collections import Counter
from copy import deepcopy
from fractions import Fraction
import importlib.util
import json
import math
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent


def load(path: Path, name: str):
    """固定コードを固有名で読み、旧大域値を変更しない。

    引数: path(Path)は対象、name(str)は読込名。
    返り値: ModuleTypeは読込結果。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


PREVIOUS = load(HERE.parent / "支持を保つ技法群/検証.py", "取得71の固定70")
I69, C, P, O = PREVIOUS.I, PREVIOUS.C, PREVIOUS.P, PREVIOUS.O
F = I69.F
STUDY = ROOT / "study/00071_技法の組み合わせへ取得位置を加える"
PARENT = ROOT / "work/取得位置と支持"
WORK = PARENT / "00071"
PREFLIGHT = PARENT / "入力接続確認.json"
OLD, OLDWORK = PREVIOUS.STUDY, PREVIOUS.WORK
SOURCE, SOURCEWORK = PREVIOUS.OLD, PREVIOUS.OLDWORK
LEDGER = PREVIOUS.PARENT / "70完了記録.json"
LEDGER_SHA = "7dcd85171c51a8ba6a526b7a0e5f3e5ae25375e8b6e3f5676ab45b07140d3c33"
POSITION_META = {"id": "F61", "name": "取得位置と上位端", "method": "P01", "family": "price", "scale": "m15"}
FEATURES = deepcopy(F.FEATURES) + [POSITION_META]
IDENTITY = ("session", "slot_id", "scheduled", "time", "line")
RULES = {"式": "g=s*(M-E*)/D。買M=上位high/E*=ask、売M=上位low/E*=bid",
    "上位": "同場・最新完全公開15分足。end<=予定、confirm原行<=実判断、予定からの古さ900秒以内",
    "気配": "旧55判断行の正常BBOを5項目identityで結合、両方向同値。後続行へ待ち直さない",
    "数値": "Fraction(str(保存数値))で差と除算、有限float64へ。学習と走査は同じfloat32",
    "未知": "旧readyの欠落又は不一致は接続失敗。0補完・片側除外・新maskなし",
    "独立性": "既存幅と終値位置に代数重複。P01の位置情報であり新しい技法票でない",
    "同時点": "予定気配であり、条件発動後の実約定や未来端を入力へ入れない",
    "上限": "gのclip・正負gate・閾値選択を加えない。D・旧入口・追尾を変更しない"}


def finite(value: object) -> bool:
    """boolを除く有限の保存数値を判定する。

    引数: value(object)は入力。
    返り値: boolは有限int/floatの場合に真。
    """
    return type(value) in (int, float) and math.isfinite(value)


def verify_previous() -> dict:
    """70の成功・完了台帳全対象を確認する。

    引数: なし。
    返り値: dictは70結果。市場や学習は実行しない。
    """
    if C.sha(LEDGER) != LEDGER_SHA:
        raise ValueError("70完了台帳の指紋が不一致")
    for relative, expected in C.read_json(LEDGER)["成果物SHA256"].items():
        if C.sha(ROOT / relative) != expected:
            raise ValueError("70完了物が変化:" + relative)
    proof, done = C.read_json(OLD / "保存物確認.json"), C.read_json(OLDWORK / "実行完了.json")
    if not proof["全件一致"] or proof["不一致数"] or C.sha(OLD / "結果.json") != proof["結果SHA256"] or proof["結果SHA256"] != done["結果SHA256"]:
        raise ValueError("70の成功証拠が不一致")
    return C.read_json(OLD / "結果.json")


def quote_for(slot: dict, immediate: dict) -> dict:
    """保存済みの両方向判断から、将来ラベルを除いた当時気配だけを取り出す。

    引数: slot(dict)は5項目identity、immediate(dict)は旧即時独立測定。
    返り値: dictは判断BBO。時計・原行・両方向の一致が必要。
    """
    quotes = []
    for side in (1, -1):
        row = immediate[slot["slot_id"], side]
        if row["side"] != side or any(row[key] != slot[key] for key in IDENTITY):
            raise ValueError("旧判断BBOの5項目結合に差")
        quotes.append(row["decision_bbo"])
    if quotes[0] != quotes[1]:
        raise ValueError("同じ判断の両方向BBOが異なる")
    return deepcopy(quotes[0])


def extend_position(slot: dict, feature60: dict, quote: dict | None) -> dict:
    """当時の価格出典と正常気配だけから取得位置を付加する。

    引数: slot(dict)は判断identity、feature60(dict)は旧特徴、quote(dict|None)は当時BBO。
    返り値: dictは旧60投影を保持する61特徴。未準備は旧辞書と同値で、未知の0補完はしない。
    """
    if not feature60["ready"]:
        return deepcopy(feature60)
    if not isinstance(quote, dict):
        raise ValueError("準備済みの当時BBOが欠落")
    if (not all(finite(slot[key]) for key in ("scheduled", "time")) or slot["time"] < slot["scheduled"]
            or type(slot["line"]) is not int or slot["line"] <= 0):
        raise ValueError("判断時計又は原行が不正")
    if (quote.get("valid") is not True or not finite(quote.get("now")) or type(quote.get("line")) is not int
            or quote.get("now") != slot["time"] or quote.get("line") != slot["line"]
            or not all(finite(quote.get(key)) for key in ("bid", "ask")) or not 0 < quote["bid"] < quote["ask"]):
        raise ValueError("当時の正常BBO又は時計が不正")
    sources = feature60["base"]["base"]["sources"]
    upper, current = sources["upper"], sources["current"]
    if (upper["session"] != slot["session"] or upper["minutes"] != 15 or upper["publish"] is not True
            or upper["missing"] != 0 or type(upper["confirm_line"]) is not int or upper["confirm_line"] <= 0
            or not all(finite(upper[key]) for key in ("start", "end", "confirm", "open", "high", "low", "close"))
            or upper["end"] - upper["start"] != 900 or upper["confirm"] < upper["end"]
            or not 0 <= slot["scheduled"] - upper["end"] <= 900
            or (upper["confirm"], upper["confirm_line"]) > (slot["time"], slot["line"])
            or not 0 < upper["low"] <= min(upper["open"], upper["close"]) <= max(upper["open"], upper["close"]) <= upper["high"]):
        raise ValueError("上位足の完全性・公開時計・価格が不正")
    if (not finite(feature60["D"]) or feature60["D"] <= 0 or not finite(feature60["atr"]) or feature60["atr"] <= 0
            or set(feature60["vectors"]) != {"1", "-1"}
            or any(len(values) != 60 for values in feature60["vectors"].values())):
        raise ValueError("旧60特徴又は幅が不正")
    result, distances = deepcopy(feature60), {}
    for side in (1, -1):
        reference, entry = (upper["high"], quote["ask"]) if side == 1 else (upper["low"], quote["bid"])
        distance = Fraction(side) * (Fraction(str(reference)) - Fraction(str(entry))) / Fraction(str(feature60["D"]))
        value = float(distance)
        if not math.isfinite(value):
            raise ValueError("取得位置が非有限")
        result["vectors"][str(side)].append(value)
        distances[str(side)] = {"value": value, "exact": str(distance), "M": reference, "E_star": entry}
    result["position"] = {"feature_id": "F61", "formula": "s*(M-E*)/D", "upper_source": deepcopy(upper),
        "quote": {key: quote[key] for key in ("now", "line", "bid", "ask", "valid")},
        "D": feature60["D"], "upper_age_seconds": slot["scheduled"] - upper["end"],
        "same_end": current["end"] == upper["end"], "same_close": current["close"] == upper["close"],
        "values": distances}
    return result


def base_projection(feature: dict) -> dict:
    """追加列とその出典だけを除き、旧60特徴を取り出す。

    引数: feature(dict)は新特徴。
    返り値: dictは旧60投影。元入力を変更しない。
    """
    result = deepcopy(feature)
    if result["ready"]:
        result.pop("position")
        result["vectors"] = {side: values[:60] for side, values in result["vectors"].items()}
    return result


def verified_inputs() -> tuple:
    """既成功入力を再構成し、全ready枠の取得位置と対照を同じ集合へ結合する。

    引数: なし。
    返り値: tupleは台帳/判断/60特徴/61特徴/即時教師/条件/条件教師/旧P運用/検査。
    """
    verify_previous()
    entries, blocks, base, immediate, conditions, _, inherited = I69.verified_inputs()
    prior = C.read_json(I69.PREFLIGHT)
    if inherited != prior["検査"] or I69.fingerprint(base) != prior["全特徴SHA256"] or I69.fingerprint(conditions) != prior["全条件SHA256"]:
        raise ValueError("旧69の全特徴・条件への結合差")
    rows = P.read_rows(SOURCEWORK / "条件独立測定.jsonl.gz")
    measured = {(row["slot_id"], row["side"]): row for row in rows}
    expected = {(identity, side) for identity, feature in base.items() if feature["ready"] for side in (1, -1)}
    if len(rows) != len(measured) or set(measured) != expected or len(measured) != 4092:
        raise ValueError("条件教師の全ready方向が不一致")
    old_blocks = P.read_rows(OLDWORK / "定時判断と運用.jsonl.gz")
    if len(old_blocks) != 92 or {row["policy"] for row in old_blocks} != {"P0", "P1"}:
        raise ValueError("70保存対照の不一致")
    for block in old_blocks:
        for slot in block["slots"]:
            if slot["feature"] != base[slot["slot_id"]]:
                raise ValueError("旧70の評価入力が異なる")
    extended, signs, ages = {}, {"1": Counter(), "-1": Counter()}, Counter()
    same_end = same_close = both = ready = 0
    for block in blocks.values():
        for slot in block["slots"]:
            feature = base[slot["slot_id"]]
            new = extend_position(slot, feature, quote_for(slot, immediate) if feature["ready"] else None)
            if base_projection(new) != feature:
                raise ValueError("追加前後の旧60投影が不一致")
            extended[slot["slot_id"]] = new
            if not feature["ready"]:
                continue
            ready += 1
            position = new["position"]
            same_end += int(position["same_end"])
            same_close += int(position["same_close"])
            both += int(position["same_end"] and position["same_close"])
            ages[str(position["upper_age_seconds"])] += 1
            for side in ("1", "-1"):
                value = position["values"][side]["value"]
                signs[side]["正" if value > 0 else "負" if value < 0 else "零"] += 1
    if set(extended) != set(base) or ready != 2046:
        raise ValueError("追加特徴の枠集合が変化")
    checks = {"旧69検査": inherited, "旧70全特徴一致": sum(len(row["slots"]) for row in old_blocks),
        "全予定枠": len(base), "準備済み枠": ready, "旧60投影一致": len(base), "BBO両方向5項目結合": ready,
        "新取得位置方向": ready * 2, "旧条件方向": len(measured), "旧保存運用": len(old_blocks),
        "上位と現3分の同end": same_end, "上位と現3分の同close": same_close, "両方同じ": both,
        "上位古さ秒": dict(ages), "g符号": {side: dict(count) for side, count in signs.items()},
        "全60特徴SHA256": I69.fingerprint(base), "全61特徴SHA256": I69.fingerprint(extended),
        "全条件SHA256": I69.fingerprint(conditions), "旧70台帳SHA256": C.sha(LEDGER)}
    return entries, blocks, base, extended, immediate, conditions, measured, old_blocks, checks


def preflight() -> None:
    """本物学習・予測前に取得位置の入力範囲と指紋を保存する。

    引数: なし。
    返り値: None。市場・独立教師・fitを実行せず、既存保存を上書きしない。
    """
    if PREFLIGHT.exists():
        raise FileExistsError("71入力接続確認は既存")
    entries, _, _, _, _, _, _, _, checks = verified_inputs()
    payload = {"試行": 71, "接続成功": True, "全66場既使用": True, "場数": len(entries), "検査": checks,
        "新fit": False, "市場再生": False, "新独立測定": False, "11月5日Day追加読取": False,
        "前巡分類": "進捗。70の92運用・監査・共通知見・外部追加・完了台帳を保存",
        "入力コードSHA256": C.sha(Path(__file__)), "特徴metadata": {"B0": deepcopy(F.FEATURES), "G0": FEATURES}}
    C.write_json(PREFLIGHT, payload)
    print(json.dumps({key: payload[key] for key in ("接続成功", "場数", "検査")}, ensure_ascii=False))


if __name__ == "__main__":
    preflight()
