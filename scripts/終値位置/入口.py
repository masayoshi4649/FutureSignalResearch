"""固定31C0の同時点選別に、足内の終値位置だけを追加する。"""

from copy import deepcopy
from fractions import Fraction
import math

SIGNAL_FIELDS = ("場", "イベントID", "入口ID", "役割", "side", "方向", "要求時計秒", "要求原板行",
    "確認遅延秒", "low", "high", "atr", "bb_mean")
POLICIES = ("T0", "T1")


def ratio(value: Fraction | None) -> dict:
    """精密値と表示値を分け、未定義をゼロにしない。

    引数: value(Fraction|None)は精密比。
    返り値: dictは値・分子・分母・有効。
    """
    return {"値": float(value) if value is not None else None,
        "分子": value.numerator if value is not None else None,
        "分母": value.denominator if value is not None else None, "有効": value is not None}


def shape(row: dict, previous: dict | None = None) -> dict:
    """公開済み突破足の終値位置を元OHLCから精密計算する。

    引数: row(dict)は固定31の原P、previous(dict|None)は同場直前足の診断参照。
    返り値: dictはCLV・二採否・診断。前ATRの有無は採否へ影響しない。
    """
    high, low, close = (Fraction(row[k]) for k in ("high", "low", "close"))
    width = high-low
    if width < 0 or not low <= close <= high:
        raise ValueError("有効OHLCの原Pだけを受け付けます")
    clv = (2*close-high-low)/width if width > 0 else None
    side = row["side"]
    if side not in (1, -1):
        raise ValueError("売買符号が不正")
    t0 = deepcopy(row["戦略判定"]["C0"])
    reasons = [] if t0["採用"] else list(t0["理由"])
    if clv is None:
        reasons.append("現在足高安幅0")
    elif side*clv <= 0:
        reasons.append("実方向CLVstrict正不成立")
    t1 = {"採用": not reasons, "理由": reasons or ["CCI突破と実方向CLVstrict正"],
        "同時競合": t0["同時競合"]}
    reference = row["直前最高H"] if side == 1 else row["直前最安L"]
    distance = side*(close-Fraction(reference))
    previous = row.get("前3分参照") if previous is None else previous
    previous_atr = previous.get("atr") if previous else None
    valid_atr = isinstance(previous_atr, (float, int)) and math.isfinite(previous_atr) and previous_atr > 0
    atr_distance = distance/Fraction(previous_atr) if valid_atr else None
    prior_range = Fraction(row["直前最高H"])-Fraction(row["直前最安L"])
    range_distance = distance/prior_range if prior_range > 0 else None
    keys = ("場", "index", "open", "high", "low", "close", "side", "方向", "要求時計秒", "要求原板行",
        "足終了時計秒", "確認遅延秒", "共通M準備", "M除外理由", "時間条件可", "確認遅延条件可", "先着評価対象")
    return {**{k: deepcopy(row[k]) for k in keys}, "原発動ID": row["発動ID"],
        "旧イベントID": row["発動ID"]+"_C0", "CLV": ratio(clv),
        "実方向CLV符号": None if clv is None else (side*clv > 0)-(side*clv < 0),
        "高安幅pt": float(width), "T0採用": t0["採用"], "T1採用": t1["採用"],
        "戦略判定": {"T0": t0, "T1": t1},
        "診断": {"突破距離pt": float(distance), "突破基準価格": float(Fraction(reference)),
            "前ATR": previous_atr if valid_atr else None,
            "前ATR規格化突破距離": ratio(atr_distance), "直前20高安幅pt": float(prior_range),
            "直前範囲規格化突破距離": ratio(range_distance), "採否への使用": False}}


def pure_signal(row: dict, policy: str) -> dict:
    """当時情報の明示列だけを写し、候補IDを置き換える。

    引数: row(dict)は固定31C0純信号、policy(str)はT0/T1。
    返り値: dictは未来ラベル等を含まない新信号。
    """
    if policy not in POLICIES or row["入口ID"] != "3分_C0" or not row["イベントID"].endswith("_C0"):
        raise ValueError("固定31C0からの二案だけ")
    signal = {key: deepcopy(row.get(key)) if key == "bb_mean" else deepcopy(row[key]) for key in SIGNAL_FIELDS}
    signal.update(入口ID="3分_"+policy, イベントID=row["イベントID"][:-3]+"_"+policy)
    return signal


def select(block: dict) -> dict:
    """全原Pの形状を記録し、同じ瞬間のC0信号だけを二案へ分ける。

    引数: block(dict)は固定31の非PnL場材料。
    返り値: dictはshape_rowsと二案純信号を持つ場材料。原Pを待ち直さない。
    """
    rows = [shape(row) for row in block["quality"]["全Q発動記録"]]
    lookup = {row["旧イベントID"]: row for row in rows}
    if len(lookup) != len(rows):
        raise ValueError("原Pが重複")
    old = block["signals"]["3分_C0"]
    if {r["イベントID"] for r in old} != {r["旧イベントID"] for r in rows if r["T0採用"]}:
        raise ValueError("旧C0とT0の全採否が不一致")
    block["signals"] = {"3分_"+p: [pure_signal(row, p) for row in old if lookup[row["イベントID"]][p+"採用"]]
        for p in POLICIES}
    block["shape_rows"] = rows
    return block
