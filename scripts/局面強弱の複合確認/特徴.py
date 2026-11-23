"""旧46特徴へ、当時の15分ADXと価格単位のBB幅を欠測旗付きで追加する。"""

from collections import deque
from copy import deepcopy
from fractions import Fraction
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys


def load(path: Path, name: str):
    """固定済みの価格補助を独立した名前で読み込む。

    引数: path(Path)はコード、name(str)はモジュール名。
    返り値: ModuleTypeは読込結果。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


HERE = Path(__file__).resolve().parent
OLD = load(HERE.parent / "方向と再開確認/特徴.py", "局面強弱の固定62特徴")
I49 = load(HERE.parent / "定時帯反応/入口.py", "局面強弱の固定49数値銀行")
FEATURES = deepcopy(OLD.FEATURES) + [
    {"id": "F47", "name": "15分ADX水準", "method": "I08", "family": "trend", "scale": "m15"},
    {"id": "F48", "name": "15分ADX現前変化", "method": "I08", "family": "trend", "scale": "m15"},
    {"id": "F49", "name": "15分BB価格幅対現3分ATR", "method": "I05", "family": "vol", "scale": "m15"},
    {"id": "F50", "name": "15分BB価格幅変化対現3分ATR", "method": "I05", "family": "vol", "scale": "m15"},
    {"id": "F51", "name": "15分ADX現値有効", "method": "I08", "family": "trend", "scale": "m15"},
    {"id": "F52", "name": "15分ADX現前変化有効", "method": "I08", "family": "trend", "scale": "m15"},
    {"id": "F53", "name": "15分BB価格幅現値有効", "method": "I05", "family": "vol", "scale": "m15"},
    {"id": "F54", "name": "15分BB価格幅変化有効", "method": "I05", "family": "vol", "scale": "m15"},
]
RULES = deepcopy(OLD.RULES)
RULES["局面強弱"] = {
    "旧46準備": "そのまま保持。追加列の欠測で除外しない",
    "ADX": "固定49の同限月carry・無効足reset・Wilder14を再用",
    "BB": "同じ数値銀行のreset/carryで有効終値20本、母分散、価格幅4sqrt(分散)",
    "幅の相違": "公式BandWidthの4sigma/SMAではない。水準割りをせず価格鏡映を維持",
    "差の出典": "旧upper.sourceと同じ現15分足と当場index-1の完全隣接・当時公開足",
    "追加列": "ADX/100,deltaADX/100,幅/現ATR3,delta幅/現ATR3,現ADX/差ADX/現幅/差幅の有効旗",
    "未知": "対応数値0かつ有効旗0。既知0と区別し、未知を弱い/収縮と命名しない",
    "鏡像": "追加8列は両方向同値。方向票や独立した8技法として数えない",
}


def width(prices: list[float]) -> float | None:
    """20終値の母分散から価格単位のバンド全幅を作る。

    引数: prices(list[float])は直近の有効終値、20本以外なら未準備。
    返り値: float|Noneは4σ又は未準備。分散まではFractionで計算する。
    """
    if len(prices) != 20:
        return None
    values = [Fraction(p) for p in prices]
    mean = sum(values) / 20
    variance = sum((p - mean) ** 2 for p in values) / 20
    result = 4 * math.sqrt(float(variance))
    if not math.isfinite(result):
        raise ValueError("BB価格幅が有限でない")
    return result


def build_context(sessions: list[dict]) -> dict:
    """SOURCEだけから49数値と同じ助走・resetを持つ15分文脈を作る。

    引数: sessions(list[dict])は固定49inputs形式の全場SOURCE。
    返り値: dictは場名から拡張15分足配列への写像。教師・損益は読まない。
    """
    banks = I49.build_bank(sessions)
    closes, identities, output = deque(maxlen=20), deque(maxlen=20), {}
    for item in sessions:
        rows = []
        for row in banks[item["session"]]["frames15"]:
            if not row["valid"] or row["numeric_count"] <= 1:
                closes.clear()
                identities.clear()
            if row["valid"]:
                closes.append(row["close"])
                identities.append([row["session"], row["index"], row["confirm"], row["confirm_line"]])
            signature = hashlib.sha256(json.dumps(list(identities), ensure_ascii=False,
                separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()
            rows.append({**deepcopy(row), "bb_width": width(list(closes)),
                "bb_count": len(closes), "bb_window_sha256": signature})
        output[item["session"]] = rows
    return output


# ----------------------------------------
# 数値の有効性と、現前差を作れる公開隣接性を分ける。

def present(value: object, maximum: float | None = None) -> bool:
    """非負有限値で、必要なら上限内かを検査する。

    引数: value(object)は指標、maximum(float|None)は上限。
    返り値: boolは有効数値か。
    """
    return I49.finite(value) and value >= 0 and (maximum is None or value <= maximum)


def extend(slot: dict, old_feature: dict, rows: list[dict]) -> dict:
    """旧46特徴の準備を保ったまま、同じ15分出典から8列を追加する。

    引数: slot(dict)は固定50の定時枠、old_feature(dict)は固定62特徴、
        rows(list[dict])は当場のbuild_context出力。
    返り値: dictは全54特徴、旧46射影、局面値・有効旗・出典。
    """
    result = deepcopy(old_feature)
    result["control_vectors46"] = deepcopy(old_feature["vectors"])
    regime = {"current_source": None, "previous_source": None,
        "adx": None, "previous_adx": None, "bb_width": None, "previous_bb_width": None,
        "adx_valid": False, "adx_change_valid": False, "bb_valid": False, "bb_change_valid": False,
        "bb_count": 0, "bb_window_sha256": None, "previous_bb_window_sha256": None,
        "pair_valid": False, "values": [0.0] * 8, "reason": "旧特徴未準備"}
    result["regime"] = regime
    if not old_feature["ready"]:
        return result
    expected = slot["upper"]["source"]
    selected = [row for row in rows if row["index"] == expected["index"]]
    if len(selected) != 1 or I49.source(selected[0]) != expected:
        raise ValueError("局面の現15分出典と旧upperが不一致")
    current = selected[0]
    if (not current["valid"] or current["end"] > slot["scheduled"]
            or I49.key(current) > (slot["time"], slot["line"])):
        raise ValueError("局面現足が当時公開有効足でない")
    if any(current[key] != slot["upper"][key] for key in ("plus_di", "minus_di")):
        raise ValueError("固定49再計算DIと保存DIが不一致")
    previous_rows = [row for row in rows if row["index"] == current["index"] - 1]
    if len(previous_rows) > 1:
        raise ValueError("前15分出典が重複")
    previous = previous_rows[0] if previous_rows else None
    if previous is not None and (not previous["publish"]
            or previous["end"] > slot["scheduled"]
            or I49.key(previous) > (slot["time"], slot["line"])):
        previous = None
    pair = bool(previous is not None and previous["valid"] and I49.adjacent(previous, current)
        and previous["end"] <= slot["scheduled"]
        and I49.key(previous) <= (slot["time"], slot["line"])
        and current["numeric_count"] == previous["numeric_count"] + 1)
    adx_ok, bb_ok = present(current["adx"], 100), present(current["bb_width"])
    adx_pair = pair and adx_ok and present(previous["adx"], 100)
    bb_pair = pair and bb_ok and present(previous["bb_width"])
    atr = Fraction(old_feature["atr"])
    values = [float(Fraction(current["adx"]) / 100) if adx_ok else 0.0,
        float((Fraction(current["adx"]) - Fraction(previous["adx"])) / 100) if adx_pair else 0.0,
        float(Fraction(current["bb_width"]) / atr) if bb_ok else 0.0,
        float((Fraction(current["bb_width"]) - Fraction(previous["bb_width"])) / atr) if bb_pair else 0.0,
        int(adx_ok), int(adx_pair), int(bb_ok), int(bb_pair)]
    if not all(I49.finite(v) for v in values):
        raise ValueError("局面特徴が有限でない")
    regime.update(current_source=I49.source(current),
        previous_source=I49.source(previous) if previous is not None else None,
        adx=current["adx"], previous_adx=previous["adx"] if previous is not None else None,
        bb_width=current["bb_width"], previous_bb_width=previous["bb_width"] if previous is not None else None,
        adx_valid=adx_ok, adx_change_valid=bool(adx_pair), bb_valid=bb_ok, bb_change_valid=bool(bb_pair),
        bb_count=current["bb_count"], bb_window_sha256=current["bb_window_sha256"],
        previous_bb_window_sha256=previous["bb_window_sha256"] if previous is not None else None,
        pair_valid=pair, values=values, reason="有効旗で追加欠測を区別")
    result["vectors"] = {side: old_feature["vectors"][side] + values for side in ("1", "-1")}
    return result


def control_projection(feature: dict) -> dict:
    """局面追加前の全46特徴と付随状態を復元する。

    引数: feature(dict)はextend出力。
    返り値: dictは旧62と完全比較する深い写し。
    """
    result = deepcopy(feature)
    result["vectors"] = result.pop("control_vectors46")
    result.pop("regime")
    return result
