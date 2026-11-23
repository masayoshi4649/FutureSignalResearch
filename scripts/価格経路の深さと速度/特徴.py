"""旧58の保持水準と全30列へ、bからの既知終値の深さ・平均進行・位置を加える。"""

from copy import deepcopy
from fractions import Fraction
import importlib.util
import math
from pathlib import Path


SPEC = importlib.util.spec_from_file_location("深さ速度が固定参照する58特徴",
    Path(__file__).resolve().parents[1] / "水準を保持する再試験/特徴.py")
F58 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(F58)
SOURCE_FIELDS = F58.SOURCE_FIELDS
BASE_FEATURES = deepcopy(F58.FEATURES)
FEATURES = deepcopy(BASE_FEATURES)
for role, start in (("T", 31), ("R", 35)):
    for offset, (name, method) in enumerate((("登録b終値からの最大逆行対ATR", "P10"),
            ("b以後の既知最大終値進行からの戻り対ATR", "P10"),
            ("bから一足当たり平均純進行対ATR", "P05"),
            ("保持端からの実方向終値距離対D", "P10"))):
        FEATURES.append({"id": f"F{start + offset:02d}", "name": role + name,
            "method": method, "family": "price", "scale": "m03"})
RULES = {"旧特徴": 30, "追加特徴": 8, "全特徴": 38,
    "旧保持機械": deepcopy(F58.RULES),
    "対象": "現episodeのbを含む、判断時まで可視な完全隣接3分終値",
    "座標": "u_i=実side*(C_i-C_b)", "深さ": "-min(0,min(u_i))/現在ATR",
    "戻り": "(max(0,max(u_i))-u_j)/現在ATR",
    "平均純進行": "n=j.index-b.index。n>0ならu_j/(現在ATR*n)、n0は既知0",
    "終値位置": "実side*(C_j-固定K)/現在D。気配又は実取得価格ではない",
    "取消後": "旧58と同じTTL/置換/resetまで既知終値統計を保持。有効旗は復活させない",
    "未ID": "四値0。旧stage/flagsとgeometryで適用外と真の零を区別",
    "極値": "現在までの終値だけ。同値極値の出典は最初。未来の底/峰/足中順は使わない",
    "旧列": "固定58の全30列・baseF53・control_vectors18・paths・historyを不変保持",
    "返り値追加": "control_vectors30=旧58vectorsの深い複写、geometry=小型終値診断",
    "重複": "F07一足変化/k後統計と異なる起点だが従属又は同値化し得る。独立票にしない",
    "非対象": ["当時BBO結合", "未来実entry", "実約定MAE/MFE", "教師", "損益", "新ready除外"]}
CONTROL_FIELDS = ("ready", "reason", "base", "control_vectors", "vectors", "atr", "D",
    "background_direction", "paths", "history")


def control_projection(feature: dict) -> dict:
    """新項目を除き、固定58の返り値だけへ純粋に射影する。

    引数: feature(dict)は新59のextract返り値。
    返り値: dictは旧keysだけの深い複写。vectorsをcontrol_vectors30へ置き換える。
    """
    result = {name: deepcopy(feature[name]) for name in CONTROL_FIELDS}
    result["vectors"] = deepcopy(feature["control_vectors30"])
    return result


def geometry(path: dict, current: dict, rows: dict[int, dict], atr: float, distance: float) -> dict:
    """現episodeのbから現在までの終値だけで、追加四値と小型診断を作る。

    引数: path(dict)は旧58経路、current(dict)は旧最新足、rows(dict[int,dict])は可視SOURCE、
        atr(float)は現在ATR、distance(float)は現在D。
    返り値: dictは追加四値と出典参照。未IDは四値0、原SOURCEを全文転記しない。
    """
    if not F58.I49.finite(atr) or atr <= 0 or not F58.I49.finite(distance) or distance <= 0:
        raise ValueError("現在ATR/Dは有限正値が必要")
    result = {"episode_id": path["episode_id"], "b": deepcopy(path["b"]),
        "current": F58.source_ref(current), "n": None, "observations": 0,
        "b_close": None, "current_close": current["close"], "level": path["level"],
        "u_current": None, "u_min": None, "u_max": None,
        "u_min_source": None, "u_max_source": None, "values": [0, 0, 0, 0]}
    if path["episode_id"] is None:
        if path["b"] is not None or path["level"] is not None or path["stage"] != 0:
            raise ValueError("未IDの旧保持状態が不整合")
        return result
    b = path["b"]
    if b is None or path["level"] is None or path["side"] not in (-1, 1):
        raise ValueError("登録済み経路のb/K/実方向が不正")
    indices = list(range(b["index"], current["index"] + 1))
    if not indices or any(index not in rows for index in indices):
        raise ValueError("bから現在までの正本終値出典が不足")
    selected = [rows[index] for index in indices]
    if (F58.source_ref(selected[0]) != b or selected[-1] != current
            or any(not F58.I49.eligible_price(row) for row in selected)
            or any(not F58.I49.adjacent(p, c) for p, c in zip(selected, selected[1:]))):
        raise ValueError("保持b/現足/完全隣接の出典が不一致")
    # ----------------------------------------
    # k/r/fの有無で対象を切らない。bを含むのでu=0は必ず観測されている。
    side, origin = path["side"], Fraction(selected[0]["close"])
    values = [side * (Fraction(row["close"]) - origin) for row in selected]
    minimum, maximum, latest = min(values), max(values), values[-1]
    n, scale, D = current["index"] - b["index"], Fraction(atr), Fraction(distance)
    additional = [float(-min(Fraction(0), minimum) / scale),
        float((max(Fraction(0), maximum) - latest) / scale),
        float(latest / (scale * n)) if n > 0 else 0.0,
        float(side * (Fraction(current["close"]) - Fraction(path["level"])) / D)]
    diagnostic = [float(latest), float(minimum), float(maximum), *additional]
    if not all(math.isfinite(value) for value in diagnostic):
        raise ValueError("追加価格経路値が表示範囲外又は非有限")
    result.update(n=n, observations=len(selected), b_close=selected[0]["close"],
        u_current=float(latest), u_min=float(minimum), u_max=float(maximum),
        u_min_source=F58.source_ref(selected[values.index(minimum)]),
        u_max_source=F58.source_ref(selected[values.index(maximum)]), values=additional)
    return result


def extract(slot: dict, frames3: list[dict]) -> dict:
    """旧58辞書を深い複写で保持し、T/R各四列だけを末尾へ追加する。

    引数: slot(dict)は既存定時判断、frames3(list[dict])は旧正本SOURCE銀行。
    返り値: dictは旧58全項目とcontrol_vectors30/geometry。vectorsは38列、旧準備不足は両空。
        旧global/入力/出力を変更せず、原板・教師・損益・未来価格を読まない。
    """
    old = F58.extract(slot, frames3)
    result = deepcopy(old)
    result.update(control_vectors30=deepcopy(old["vectors"]),
        geometry={"1": {"T": None, "R": None}, "-1": {"T": None, "R": None}})
    if not old["ready"]:
        return result
    rows = {row["index"]: row for row in F58.visible_sources(slot, frames3)}
    current = old["base"]["history"]["reaction_sources"][-1]
    for side in ("1", "-1"):
        additional = []
        for role in ("T", "R"):
            value = geometry(old["paths"][side][role], current, rows, old["atr"], old["D"])
            result["geometry"][side][role] = value
            additional.extend(value["values"])
        result["vectors"][side] = deepcopy(old["vectors"][side]) + additional
    return result
