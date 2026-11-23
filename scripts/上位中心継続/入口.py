"""固定38H0へ、上位基準26の現前準備と時間進行を順に追加する。"""

from collections import Counter
from copy import deepcopy
from fractions import Fraction
import importlib.util
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("上位中心継続の固定38純射影", ROOT/"scripts/上位雲継続/入口.py")
BASE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = BASE
SPEC.loader.exec_module(BASE)
SIGNAL_FIELDS, SOURCE_FIELDS, ICHI_FIELDS = BASE.SIGNAL_FIELDS, BASE.SOURCE_FIELDS, BASE.ICHI_FIELDS
UPPER_FIELDS, upper_projection, finite, canonical_sha = BASE.UPPER_FIELDS, BASE.upper_projection, BASE.finite, BASE.canonical_sha
POLICIES = ("J0", "J1", "J2")
ROLES = {p: "順行" for p in POLICIES}


def pure_signal(row: dict, policy: str = "J0") -> dict:
    """固定38H0の13列を識別子だけ変更して三案へ写す。

    引数: row(dict)は旧38H0純入口、policy(str)はJ0/J1/J2。
    返り値: dictは元時計/価格/ATR/役割を全保持する純13列。
    """
    if policy not in POLICIES:
        raise ValueError("事前の上位中心三案だけです")
    if row["入口ID"] != "3分_H0" or not row["イベントID"].endswith("_H0"):
        raise ValueError("固定38H0の純入口だけを受け取ります")
    if (row["役割"] != "順行" or row["side"] not in (-1, 1)
            or row["方向"] != ("買い" if row["side"] == 1 else "売り")):
        raise ValueError("実方向が一致する順行だけです")
    result = {k: deepcopy(row.get(k)) if k == "bb_mean" else deepcopy(row[k]) for k in SIGNAL_FIELDS}
    result.update(入口ID="3分_"+policy, イベントID=row["イベントID"][:-3]+"_"+policy)
    return result


def pair_state(current: dict | None, previous: dict | None, lower: dict, side: int) -> dict:
    """雲準備を使わず、当場隣接公開J26ペアと厳密差を判定する。

    引数: current/previous(dict|None)は最新/番号で隣接する前15分、lower(dict)は下位出典、side(int)は実方向。
    返り値: dictは現前準備/理由/基準現前/厳密差/進行。差の分子分母は価格差を表す。
    """
    reasons = []
    if current is None:
        reasons.append("当場公開15分なし")
    elif previous is None:
        reasons.append("前上位公開参照なし")
    request_key = lower["confirm"], lower["confirm_line"]
    for name, row in (("現", current), ("前", previous)):
        if row is None:
            continue
        if not row["publish"]:
            reasons.append(name+"15分非公開")
        if not row["一目数値入力可"]:
            reasons.append(name+"15分数値入力不可")
        if not finite(row["ichimoku_kijun"]):
            reasons.append(name+"15分基準26未準備")
        if row["missing"] != 0:
            reasons.append(name+"15分欠枠あり")
        if row["end"]-row["start"] != 900:
            reasons.append(name+"15分完全幅900秒不成立")
        if row["end"] > lower["end"]:
            reasons.append(name+"15分終了が下位未来")
        if (row["confirm"], row["confirm_line"]) > request_key:
            reasons.append(name+"15分公開keyが要求未来")
    if current is not None and previous is not None:
        if previous["index"]+1 != current["index"]:
            reasons.append("上位現前足番号非隣接")
        if previous["end"] != current["start"]:
            reasons.append("上位現前終了開始非隣接")
        if (previous["confirm"], previous["confirm_line"]) > (current["confirm"], current["confirm_line"]):
            reasons.append("前後公開順不整合")
    ready = not reasons
    now = current["ichimoku_kijun"] if current is not None and finite(current["ichimoku_kijun"]) else None
    before = previous["ichimoku_kijun"] if previous is not None and finite(previous["ichimoku_kijun"]) else None
    delta = Fraction(now)-Fraction(before) if ready else None
    sign = int(delta > 0)-int(delta < 0) if delta is not None else None
    return {"上位現前準備": ready, "準備除外理由": reasons, "基準線現値": now, "基準線前値": before,
        "基準線差": float(delta) if delta is not None else None,
        "基準線差厳密分子": delta.numerator if delta is not None else None,
        "基準線差厳密分母": delta.denominator if delta is not None else None, "基準線差厳密符号": sign,
        "進行方向": "未準備" if sign is None else "同方向" if side*sign > 0 else "逆方向" if side*sign < 0 else "等号"}


# ----------------------------------------
# 先に最新公開uを選び、前足不良なら古い良好ペアへ戻らない。

def select(block: dict, higher15: list[dict], session: str | None = None) -> dict:
    """固定H0の要求keyで一回判断し、準備/進行の三純集合を作る。

    引数: block(dict)はsignals['3分_H0']/frames[3]/下位出典、higher15(list[dict])は当場の限定27列、
    session(str|None)は場。省略時はblock又は旧純入口の場を使う。
    返り値: dictはsignals三集合と小型decisionsを追加した材料。将来labelを使用しない。
    """
    original = block["signals"]["3分_H0"]
    actual_session = session or block.get("場") or (original[0]["場"] if original else None)
    if actual_session is None:
        raise ValueError("空のH0場でも場を明示してください")
    if any(r["場"] != actual_session or r["minutes"] != 15 for r in higher15):
        raise ValueError("当場の15分限定列だけを参照します")
    frames = block["frames"][3]
    if any(r["minutes"] != 3 for r in frames):
        raise ValueError("下位出典は固定29の3分だけです")
    frame_by_index = {r["index"]: r for r in frames}
    if len(frame_by_index) != len(frames):
        raise ValueError("下位足番号は一意だけです")
    keys = [(r["要求時計秒"], r["要求原板行"]) for r in original]
    if keys != sorted(keys) or any(n > 1 for n in Counter(keys).values()):
        raise ValueError("固定38H0の競合後・公開順の集合だけです")
    if len({r["イベントID"] for r in original}) != len(original):
        raise ValueError("旧H0イベントIDは一意だけです")
    projected = [upper_projection(r) for r in higher15]
    by_index = {r["index"]: r for r in projected}
    if len(by_index) != len(projected):
        raise ValueError("上位足番号は一意だけです")
    published = sorted((r for r in projected if r["publish"]), key=lambda r: (r["confirm"], r["confirm_line"], r["index"]))
    pointer, visible, decisions = 0, [], []
    grouped = {"3分_"+p: [] for p in POLICIES}
    for row in original:
        if row["場"] != actual_session:
            raise ValueError("旧H0純入口の場が不一致")
        pure_signal(row)
        lower = block["下位出典"][row["イベントID"]]
        if any(lower[k] != frame_by_index[lower["index"]][k] for k in SOURCE_FIELDS):
            raise ValueError("旧H0下位出典と保存3分が不一致")
        key = row["要求時計秒"], row["要求原板行"]
        if key != (lower["confirm"], lower["confirm_line"]) or not lower["publish"]:
            raise ValueError("旧H0要求keyと下位公開出典が不一致")
        while pointer < len(published) and (published[pointer]["confirm"], published[pointer]["confirm_line"]) <= key:
            visible.append(published[pointer])
            pointer += 1
        upper = next((r for r in reversed(visible) if r["end"] <= lower["end"]), None)
        previous = by_index.get(upper["index"]-1) if upper is not None else None
        if previous is not None and (not previous["publish"] or previous["end"] > lower["end"]
                or (previous["confirm"], previous["confirm_line"]) > key):
            previous = None
        pair = pair_state(upper, previous, lower, row["side"])
        _, _, cloud, tj = BASE.classification(upper, row["side"])
        ready = pair["上位現前準備"]
        progress = ready and pair["進行方向"] == "同方向"
        verdicts = {
            "J0": {"採用": True, "理由": ["固定38H0完全入口"], "同時競合": False},
            "J1": {"採用": ready, "理由": ["上位基準線現前準備採用"] if ready else list(pair["準備除外理由"]), "同時競合": False},
            "J2": {"採用": progress, "理由": list(pair["準備除外理由"]) if not ready else
                ["上位基準線実方向進行採用"] if progress else ["上位基準線実方向進行不成立"], "同時競合": False}}
        decisions.append({"場": actual_session, "元38H0イベントID": row["イベントID"], "元index": lower["index"],
            "足終了時計秒": lower["end"], "要求時計秒": key[0], "要求原板行": key[1], "実side": row["side"], "役割": "順行",
            "上位参照": deepcopy(upper), "前上位参照": deepcopy(previous), **pair, "雲方向": cloud, "TJ方向": tj, "戦略判定": verdicts})
        for policy in POLICIES:
            if verdicts[policy]["採用"]:
                grouped["3分_"+policy].append(pure_signal(row, policy))
    block.update(signals=grouped, decisions=decisions)
    return block
