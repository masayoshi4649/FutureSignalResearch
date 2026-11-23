"""同場の収縮設定から、最初の拡大突破と突破失敗を確定足で生成する。"""

from __future__ import annotations

from collections import Counter, deque
import importlib.util
import math
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
FAMILIES = ("突破追随", "突破失敗反転")
EXTRAS = ("なし", "15分方向一致")


def shared() -> Any:
    """固定00011の有限値・上位準備関数だけを読み込む。

    引数: なし。
    返り値: Any は固定された指標準備と上位方向の判定。
    """
    spec = importlib.util.spec_from_file_location("収縮反転の上位判定", ROOT/"scripts/テクニカル循環/入口.py")
    value = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = value
    spec.loader.exec_module(value)
    return value


CORE = shared()


def bandwidth(frame: dict) -> float | None:
    """BB20×2の帯幅を中心で割って求める。

    引数: frame (dict) は確定足のbb_meanと母標準偏差bb_sd。
    返り値: float | None は4σ/SMA20。非正・欠測・非有限は無効。
    """
    mean, deviation = frame.get("bb_mean"), frame.get("bb_sd")
    if not CORE.defined(mean, deviation) or mean <= 0 or deviation <= 0:
        return None
    value = 4*deviation/mean
    return value if math.isfinite(value) and value > 0 else None


def make_signal(row: dict, setup: dict, broken: dict, family: str, extra: str,
                side: int, session: str, deadline: float) -> dict:
    """現在までに確定した設定・突破を添えて入口を作る。

    引数: row/setup/broken (dict) は現足・収縮・突破、family/extra/session (str) は系統・補助・場、
    side (int) は買1/売−1、deadline (float) は期限秒。
    返り値: dict は将来ラベルを含まない新規要求。
    """
    size = row["minutes"]
    source_id = f"{size}分_{family}_{extra}"
    return {**row, "場": session, "時間足分": size, "入口ID": source_id, "入口系統": family, "補助": extra,
        "side": side, "方向": "買い" if side == 1 else "売り", "イベントID": f"NK225_{session}_{source_id}_{row['index']:04d}_{side}",
        "要求時計秒": row["confirm"], "要求原板行": row["confirm_line"], "確認遅延秒": row["confirm"]-row["end"],
        "足終了時計秒": row["end"], "期限時計秒": deadline, "残り分_判断時": (deadline-row["confirm"])/60,
        "収縮設定": dict(setup), "突破登録": dict(broken), "収縮からの経過足": row["index"]-setup["index"],
        "突破からの経過足": row["index"]-broken["index"], "250ptのATR倍": 250/row["atr"]}


# ----------------------------------------
# 状態は補助・準備・保有の有無と独立に一度だけ進め、その後に発動を絞る。

def generate(frames: list[dict], higher: list[dict], session: str, cutoff: float,
             deadline: float, config: dict) -> tuple[dict[str, list[dict]], dict]:
    """20/6/6/3の固定状態遷移から当尺度4入口を生成する。

    引数: frames/higher (list[dict]) は同場の発動足/15分特徴、session (str) は場、
    cutoff/deadline (float) は新規停止/期限、config (dict) は固定条件。
    返り値: tuple[dict[str,list[dict]],dict] は当尺度の発動列と状態品質。
    """
    if not frames:
        raise ValueError("入口尺度を特定できる足がありません")
    size = frames[0]["minutes"]
    if size not in config["時間足分"] or any(f["minutes"] != size for f in frames):
        raise ValueError("同じ3分または5分尺度だけを扱います")
    output = {f"{size}分_{family}_{extra}": [] for family in FAMILIES for extra in EXTRAS}
    history = deque(maxlen=20)
    setup, broken = None, None
    pointer, upper, previous_key = 0, None, None
    counter = Counter()
    for frame in frames:
        key = frame["confirm"], frame["confirm_line"]
        if previous_key is not None and key < previous_key:
            raise ValueError("確定足の確認キーが後退")
        previous_key = key
        if frame["publish"] and frame["confirm"] < frame["end"]:
            raise ValueError("足終了前の公開")
        if not frame["publish"] or frame["missing"]:
            history.clear()
            setup, broken = None, None
            counter["非公開リセット" if not frame["publish"] else "欠枠リセット"] += 1
            if not frame["publish"]:
                continue
        width = bandwidth(frame)
        if width is None:
            history.clear()
            setup, broken = None, None
            counter["帯幅無効リセット"] += 1
            continue
        while pointer < len(higher) and (higher[pointer]["confirm"], higher[pointer]["confirm_line"]) <= key and higher[pointer]["end"] <= frame["end"]:
            upper = higher[pointer]
            pointer += 1
        ready, direction = CORE.upper_state(upper)
        row = {**frame, "帯幅": width, "上位準備済": ready, "上位方向": direction,
            "上位確認秒": upper["confirm"] if upper is not None else None,
            "上位確認行": upper["confirm_line"] if upper is not None else None,
            "上位足終了秒": upper["end"] if upper is not None else None}
        common = CORE.defined(row["ema20"], row["atr"], row["adx"], row["bb_mean"], row["bb_sd"]) and row["atr"] > 0 and ready
        eligible = common and row["confirm"] < cutoff and deadline-row["confirm"] >= config["残り時間下限分"]*60
        counter["有効公開足"] += 1
        counter["共通準備可足"] += int(common)
        counter["共通時間条件可足"] += int(eligible)
        event = None
        # 既存の突破後状態か、未突破の設定か、どちらか一つだけを先に判定する。
        if broken is not None:
            age = row["index"]-broken["index"]
            low, high = setup["固定安値"], setup["固定高値"]
            if age > 3:
                counter["突破後満了"] += 1
                setup, broken = None, None
            elif age >= 1:
                crossed = row["close"] <= low if broken["side"] == 1 else row["close"] >= high
                if crossed:
                    counter["反対端飛越失効"] += 1
                    setup, broken = None, None
                elif low < row["close"] < high:
                    event = ("突破失敗反転", -broken["side"], dict(setup), dict(broken))
                    counter["突破失敗消費"] += 1
                    setup, broken = None, None
        elif setup is not None:
            age = row["index"]-setup["index"]
            if age > 6:
                counter["未突破満了"] += 1
                setup = None
            elif age >= 1:
                side = 1 if row["close"] > setup["固定高値"] else (-1 if row["close"] < setup["固定安値"] else 0)
                if side:
                    if width > setup["帯幅"]:
                        broken = {key: row[key] for key in ("index", "end", "confirm", "confirm_line", "帯幅")}
                        broken["side"] = side
                        event = ("突破追随", side, dict(setup), dict(broken))
                        counter["拡大突破消費"] += 1
                    else:
                        counter["非拡大範囲外失効"] += 1
                        setup = None
        if event is not None:
            family, side, saved_setup, saved_break = event
            if eligible:
                for extra in EXTRAS:
                    if extra == "15分方向一致" and direction != side:
                        counter["上位方向不一致抑止"] += 1
                        continue
                    signal = make_signal(row, saved_setup, saved_break, family, extra, side, session, deadline)
                    output[signal["入口ID"]].append(signal)
                    counter["確認遅延超過発動"] += int(signal["確認遅延秒"] > config["確認遅延上限秒"])
            else:
                counter["準備時間条件で発動抑止"] += 1
        history.append(row)
        # 当足を含む20有効足の最小を確認し、突破後状態がない時だけ次の設定を置く。
        if broken is None and len(history) == 20 and width <= min(h["帯幅"] for h in history):
            counter["未突破設定置換"] += int(setup is not None)
            recent = list(history)[-6:]
            setup = {key: row[key] for key in ("index", "end", "confirm", "confirm_line", "bb_mean", "帯幅")}
            setup.update(固定高値=max(h["high"] for h in recent), 固定安値=min(h["low"] for h in recent))
            counter["収縮設定登録"] += 1
    return output, {"場": session, "時間足分": size, **dict(counter),
                    "系統別発動数": {source: len(rows) for source, rows in output.items()}}
