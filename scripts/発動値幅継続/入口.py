"""固定39J0を保ち、発動足TRの準備と前ATR以下の非拡大を分離する。"""

from collections import Counter
from copy import deepcopy
from fractions import Fraction
import importlib.util
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("発動値幅継続の固定39純射影", ROOT/"scripts/上位中心継続/入口.py")
BASE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = BASE
SPEC.loader.exec_module(BASE)
SPEC_NUMERIC = importlib.util.spec_from_file_location("発動値幅継続の固定29有効OHLC", ROOT/"scripts/OBV反転/指標.py")
NUMERIC = importlib.util.module_from_spec(SPEC_NUMERIC)
sys.modules[SPEC_NUMERIC.name] = NUMERIC
SPEC_NUMERIC.loader.exec_module(NUMERIC)
SIGNAL_FIELDS, SOURCE_FIELDS = BASE.SIGNAL_FIELDS, BASE.SOURCE_FIELDS
finite, canonical_sha = BASE.finite, BASE.canonical_sha
FRAME_FIELDS = ("場", *SOURCE_FIELDS, "atr")
POLICIES = ("W0", "W1", "W2")
ROLES = {p: "順行" for p in POLICIES}


def frame_projection(row: dict | None) -> dict | None:
    """固定29の3分足からOHLC出典とATRだけを取り出す。

    引数: row(dict|None)は旧29数値足又は前公開足なし。
    返り値: dict|Noneは限定14列。MACD/数量/上位/未来labelを含めない。
    """
    if row is None:
        return None
    if row["minutes"] != 3:
        raise ValueError("発動値幅は固定29の3分だけです")
    return {k: deepcopy(row[k]) for k in FRAME_FIELDS}


def exact(value: Fraction | None) -> dict:
    """分数の表示値と厳密な分子分母を分ける。

    引数: value(Fraction|None)は厳密値又は未準備。
    返り値: dictは値/分子/分母/有効。無効を0へ補完しない。
    """
    return {"値": float(value) if value is not None else None, "分子": value.numerator if value is not None else None,
        "分母": value.denominator if value is not None else None, "有効": value is not None}


def pure_signal(row: dict, policy: str = "W0") -> dict:
    """固定39J0純13列を識別子だけ変更して値幅三案へ写す。

    引数: row(dict)は旧J0純信号、policy(str)はW0/W1/W2。
    返り値: dictは現ATRと要求時計を含めてコピーする純13列。
    """
    if policy not in POLICIES:
        raise ValueError("事前の発動値幅三案だけです")
    if row["入口ID"] != "3分_J0" or not row["イベントID"].endswith("_J0"):
        raise ValueError("固定39J0の純入口だけです")
    if (row["役割"] != "順行" or row["side"] not in (-1, 1)
            or row["方向"] != ("買い" if row["side"] == 1 else "売り")):
        raise ValueError("実方向が一致した順行だけです")
    result = {k: deepcopy(row.get(k)) if k == "bb_mean" else deepcopy(row[k]) for k in SIGNAL_FIELDS}
    result.update(入口ID="3分_"+policy, イベントID=row["イベントID"][:-3]+"_"+policy)
    return result


def range_state(current: dict, previous: dict | None) -> dict:
    """当場公開ペアの精密TRと保存正本前ATRを比較する。

    引数: current(dict)は要求時の現足、previous(dict|None)は当場の前公開足。
    返り値: dictは準備/理由/TR三距離/精密TR・差・比/非拡大分類。現ATRを変更しない。
    """
    price_reasons = []
    if previous is None:
        price_reasons.append("前3分公開参照なし")
    for name, row in (("現", current), ("前", previous)):
        if row is None:
            continue
        if not row["publish"]:
            price_reasons.append(name+"3分非公開")
        if not NUMERIC.VALID(row):
            price_reasons.append(name+"3分OHLC不正")
        if row["missing"] != 0:
            price_reasons.append(name+"3分欠枠あり")
        if row["end"]-row["start"] != 180:
            price_reasons.append(name+"3分完全幅180秒不成立")
        if row["confirm"] < row["end"]:
            price_reasons.append(name+"3分終了前公開")
    if previous is not None:
        if previous["index"]+1 != current["index"]:
            price_reasons.append("現前3分足番号非隣接")
        if previous["end"] != current["start"]:
            price_reasons.append("現前3分終了開始非隣接")
        if (previous["confirm"], previous["confirm_line"]) > (current["confirm"], current["confirm_line"]):
            price_reasons.append("現前3分公開順不整合")
    distances = {name: None for name in ("高安幅", "高値と前終値の距離", "安値と前終値の距離")}
    tr = None
    if not price_reasons:
        high, low, before_close = Fraction(current["high"]), Fraction(current["low"]), Fraction(previous["close"])
        distances = {"高安幅": high-low, "高値と前終値の距離": abs(high-before_close), "安値と前終値の距離": abs(low-before_close)}
        tr = max(distances.values())
    prior_atr = previous["atr"] if previous is not None and finite(previous["atr"]) else None
    reasons = list(price_reasons)
    if prior_atr is None or prior_atr <= 0:
        reasons.append("前3分ATR14有限正未準備")
    ready = not reasons
    reference = Fraction(prior_atr) if ready else None
    difference, ratio = (tr-reference, tr/reference) if ready else (None, None)
    sign = int(difference > 0)-int(difference < 0) if difference is not None else None
    return {"値幅準備": ready, "準備除外理由": reasons, "TR準備": not price_reasons,
        "TR三距離": {k: exact(v) for k, v in distances.items()}, "TR": exact(tr), "前ATR14": prior_atr,
        "TR前ATR差": exact(difference), "TR前ATR比": exact(ratio), "TR前ATR差符号": sign,
        "値幅区分": "未準備" if not ready else "非拡大" if sign <= 0 else "拡大"}


# ----------------------------------------
# 同じ元J0の要求keyで値幅を一回判定し、前足不可は古正常へ戻さない。

def select(block: dict, session: str | None = None) -> dict:
    """元J0純集合から、値幅準備と非拡大の三部分集合を作る。

    引数: block(dict)はsignals['3分_J0']/frames[3]/下位出典、session(str|None)は場。
    返り値: dictは三signalsと小型decisions。価格とATRの新しい銀行は計算しない。
    """
    original = block["signals"]["3分_J0"]
    actual_session = session or block.get("場") or (original[0]["場"] if original else None)
    if actual_session is None:
        raise ValueError("空のJ0場でも場を明示してください")
    frames = block["frames"][3]
    if any(r["場"] != actual_session or r["minutes"] != 3 for r in frames):
        raise ValueError("当場の固定29の3分足だけです")
    projected = {r["index"]: frame_projection(r) for r in frames}
    if len(projected) != len(frames):
        raise ValueError("3分足番号は一意だけです")
    keys = [(r["要求時計秒"], r["要求原板行"]) for r in original]
    if keys != sorted(keys) or any(n > 1 for n in Counter(keys).values()):
        raise ValueError("競合後・公開順の旧J0だけです")
    if len({r["イベントID"] for r in original}) != len(original):
        raise ValueError("元J0イベントIDは一意だけです")
    grouped, decisions = {"3分_"+p: [] for p in POLICIES}, []
    for row in original:
        pure_signal(row)
        if row["場"] != actual_session:
            raise ValueError("旧J0純入口の場が不一致")
        source = block["下位出典"][row["イベントID"]]
        current = projected[source["index"]]
        if any(current[k] != source[k] for k in SOURCE_FIELDS):
            raise ValueError("元J0下位出典と保存3分が不一致")
        key = row["要求時計秒"], row["要求原板行"]
        if key != (current["confirm"], current["confirm_line"]) or not current["publish"]:
            raise ValueError("旧J0要求keyと現足公開出典が不一致")
        if (row["low"], row["high"], row["atr"]) != (current["low"], current["high"], current["atr"]):
            raise ValueError("純入口の現高安/ATRと正本現足が不一致")
        previous = projected.get(current["index"]-1)
        if previous is not None and (not previous["publish"] or previous["end"] > current["end"]
                or (previous["confirm"], previous["confirm_line"]) > key):
            previous = None
        state = range_state(current, previous)
        ready, narrow = state["値幅準備"], state["値幅区分"] == "非拡大"
        verdicts = {
            "W0": {"採用": True, "理由": ["固定39J0完全入口"], "同時競合": False},
            "W1": {"採用": ready, "理由": ["発動値幅準備採用"] if ready else list(state["準備除外理由"]), "同時競合": False},
            "W2": {"採用": ready and narrow, "理由": list(state["準備除外理由"]) if not ready else
                ["発動TR前ATR以下採用"] if narrow else ["発動TRが前ATR超"], "同時競合": False}}
        decisions.append({"場": actual_session, "元39J0イベントID": row["イベントID"], "元index": current["index"],
            "足終了時計秒": current["end"], "要求時計秒": key[0], "要求原板行": key[1], "実side": row["side"], "役割": "順行",
            "当足参照": deepcopy(current), "前足参照": deepcopy(previous), **state, "戦略判定": verdicts})
        for policy in POLICIES:
            if verdicts[policy]["採用"]:
                grouped["3分_"+policy].append(pure_signal(row, policy))
    block.update(signals=grouped, decisions=decisions)
    return block
