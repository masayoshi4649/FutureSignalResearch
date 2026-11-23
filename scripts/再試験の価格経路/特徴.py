"""旧53の同じ凍結帯と反応5本へ、再試験の順序と既知終値進行を加える。"""

from copy import deepcopy
from fractions import Fraction
import importlib.util
import math
from pathlib import Path


SPEC = importlib.util.spec_from_file_location("再試験経路が固定参照する53特徴", Path(__file__).resolve().parents[1] / "局所帯分岐/特徴.py")
F53 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(F53)
BASE_FEATURES = deepcopy(F53.FEATURES)
SOURCE_FIELDS = F53.SOURCE_FIELDS
FEATURES = deepcopy(BASE_FEATURES)
for role, start in (("T", 19), ("R", 25)):
    for offset, (name, method) in enumerate((("最大到達段階", "P10"), ("episode有効", "P10"),
            ("確認k有効", "P10"), ("確認k公開後経過対900秒", "P10"),
            ("確認k終値からの実方向進行対ATR", "P05"), ("既知最大終値進行からの戻り対ATR", "P10"))):
        FEATURES.append({"id": f"F{start + offset:02d}", "name": role + name, "method": method, "family": "price", "scale": "m03"})
RULES = {"旧特徴": 18, "追加特徴": 12, "全特徴": 30, "参照本数": 10, "反応本数": 5,
    "帯端buffer": 5, "b": "q前<5かつq現>=5。最初だけ", "T_r": "後の別足q_min<=0かつq_close>=5。最初だけ",
    "T_k": "r後の別足q_close>q_max(r)", "R_f": "b後の別足q_close<=-5。最初だけ",
    "R_r": "f後の別足q_max>=0かつq_close<=-5。最初だけ", "R_k": "r後の別足q_close<q_min(r)",
    "元突破方向": "Tは実side、Rは-実side", "足内高安順": "使用しない", "同足段階再使用": False,
    "T帯取消": "b後q_close<=-5", "R帯取消": "f後q_close>=5。f前の外残留は取消しない",
    "k否定": "突破したr端へ実side*(C-line)<=0で戻る。等号も取消",
    "取消優先": ["帯失敗又は元外側再取得", "確認kの突破線否定"], "取消後再開始": False,
    "各定時": "旧53の新窓で状態初期化。前の窓を新しい帯へ接ぎ替えない",
    "stage": "最大到達を保持。Tは0..3、Rは0..4", "k形成後統計": "取消後も現在まで既知の終値を記述。再点火しない",
    "age": "(判断time-k.confirm)/900。k未形成だけ-1", "進行尺度": "現在判断の旧ATRを全既知終値に共通使用",
    "k未形成数値": {"age": -1, "進行": 0, "戻り": 0}, "未知": "旧53未準備だけ両vectors空。episode不成立は未知でない"}


def source_ref(row: dict | None) -> dict | None:
    """一回保存される旧出典をindexと公開keyだけで参照する。

    引数: row(dict|None)は反応足又は未形成。
    返り値: dict|Noneは足番号/key。OHLC全列を重複転記しない。
    """
    return None if row is None else {"index": row["index"], "key": [row["confirm"], row["confirm_line"]]}


def coordinates(row: dict, level: Fraction, direction: int) -> tuple[Fraction, Fraction, Fraction]:
    """元突破方向を正とする、固定帯端からの価格座標を作る。

    引数: row(dict)は旧検査済みOHLC、level(Fraction)は固定K、direction(int)は元突破±1。
    返り値: tuple[Fraction,Fraction,Fraction]はq_min/q_max/q_close。高安の発生順は使わない。
    """
    extremes = [direction * (Fraction(row[key]) - level) for key in ("high", "low")]
    return min(extremes), max(extremes), direction * (Fraction(row["close"]) - level)


def episode(reference: list[dict], reaction: list[dict], level: float, direction: int,
            role: str, atr: float, decision_time: float) -> dict:
    """同じ帯の一方向に、最初のb/rを固定したT又はRの順序を作る。

    引数: reference/reaction(list[dict])は旧検査済み10/5足、level(float)はK、direction(int)は元突破±1、
        role(str)はT/R、atr(float)は現在判断の正ATR、decision_time(float)は判断時計。
    返り値: dictは最大stage/有効旗/段階出典/取消/既知終値統計。教師・損益を使わない。
    """
    if len(reference) != 10 or len(reaction) != 5 or direction not in (-1, 1) or role not in ("T", "R"):
        raise ValueError("価格経路の窓又は方向/役割が不正")
    side, origin, denominator = direction if role == "T" else -direction, Fraction(level), Fraction(atr)
    if denominator <= 0:
        raise ValueError("判断ATRは正が必要")
    b = f = r = k = None
    stage, valid, k_valid, line, cancel = 0, False, False, None, None
    trace, closes = [], []
    previous = direction * (Fraction(reference[-1]["close"]) - origin)
    for row in reaction:
        near, far, close = coordinates(row, origin, direction)
        action = "未登録" if b is None else "取消後履歴" if not valid else "次段待ち"
        # ----------------------------------------
        # 既存episodeの取消を先に処理し、その足を新登録や次段へ使い直さない。
        if valid:
            band_failure = role == "T" and close <= -5
            reacquired = role == "R" and f is not None and close >= 5
            denied = k is not None and side * (Fraction(row["close"]) - Fraction(line)) <= 0
            reasons = (["T帯内失敗"] if band_failure else ["R元外側再取得"] if reacquired else [])
            if denied:
                reasons.append("確認kの突破線否定")
            if reasons:
                valid, k_valid = False, False
                cancel = {**source_ref(row), "reasons": reasons}
                action = "取消"
        # ----------------------------------------
        # 一つの足では一つの段階だけ進め、最初のbとrを後で選び直さない。
        if b is None:
            if previous < 5 and close >= 5:
                b, stage, valid, action = row, 1, True, "b登録"
        elif valid and k is None:
            if role == "T":
                if r is None and near <= 0 and close >= 5:
                    r, stage, action = row, 2, "T再試験r"
                elif r is not None and close > coordinates(r, origin, direction)[1]:
                    k, stage, k_valid, action = row, 3, True, "T再開k"
                    line = r["high"] if side == 1 else r["low"]
            else:
                if f is None and close <= -5:
                    f, stage, action = row, 2, "R内復帰f"
                elif f is not None and r is None and far >= 0 and close <= -5:
                    r, stage, action = row, 3, "R再試験r"
                elif r is not None and close < coordinates(r, origin, direction)[0]:
                    k, stage, k_valid, action = row, 4, True, "R再開k"
                    line = r["high"] if side == 1 else r["low"]
        # ----------------------------------------
        # kが一度形成された後は取消後も既知の終値を記述し、採用可能性を復活させない。
        if k is not None:
            closes.append({"index": row["index"], "key": [row["confirm"], row["confirm_line"]], "close": row["close"]})
        trace.append({**source_ref(row), "action": action, "stage": stage, "episode_valid": valid, "k_valid": k_valid})
        previous = close
    if k is None:
        age, progress, maximum, pullback = -1.0, 0.0, 0.0, 0.0
    else:
        age = (decision_time - k["confirm"]) / 900
        if age < 0:
            raise ValueError("確認kが判断より未来")
        values = [side * (Fraction(row["close"]) - Fraction(k["close"])) / denominator for row in closes]
        current, peak = values[-1], max(Fraction(0), *values)
        progress, maximum, pullback = float(current), float(peak), float(peak - current)
    if not all(math.isfinite(value) for value in (age, progress, maximum, pullback)):
        raise ValueError("新価格経路の表示数値が非有限")
    return {"role": role, "side": side, "break_direction": direction, "level": level,
        "stage": stage, "episode_valid": valid, "k_valid": k_valid, "b": source_ref(b), "f": source_ref(f),
        "r": source_ref(r), "k": source_ref(k), "line": line, "cancel": cancel, "trace": trace,
        "age": age, "progress": progress, "max_close_progress": maximum, "pullback": pullback}


def extract(slot: dict, frames3: list[dict]) -> dict:
    """旧18特徴と同じ準備のまま、T/R各六列の既知価格経路を加える。

    引数: slot(dict)は既存定時判断、frames3(list[dict])は旧53が読む正本SOURCE13。
    返り値: dictはready/reason/base/control_vectors18/vectors30/atr/D/background_direction/paths。
        episode不成立や取消は特徴欠測にしない。元slot/frames/旧globalは変更しない。
    """
    base = F53.extract(slot, frames3)
    result = {"ready": base["ready"], "reason": base["reason"], "base": base,
        "control_vectors": deepcopy(base["vectors"]), "vectors": {"1": [], "-1": []},
        "atr": base["atr"], "D": base["D"], "background_direction": base["background_direction"],
        "paths": {"1": {"T": None, "R": None}, "-1": {"T": None, "R": None}}}
    if not base["ready"]:
        return result
    history = base["history"]
    by_origin = {}
    for direction in (1, -1):
        level = history["band"]["high" if direction == 1 else "low"]
        by_origin[direction] = {role: episode(history["reference_sources"], history["reaction_sources"], level,
            direction, role, base["atr"], slot["time"]) for role in ("T", "R")}
    for side in (1, -1):
        paths = {"T": by_origin[side]["T"], "R": by_origin[-side]["R"]}
        additional = []
        for role in ("T", "R"):
            current = paths[role]
            additional += [current["stage"], int(current["episode_valid"]), int(current["k_valid"]),
                current["age"], current["progress"], current["pullback"]]
        result["paths"][str(side)] = paths
        result["vectors"][str(side)] = deepcopy(base["vectors"][str(side)]) + additional
    return result
