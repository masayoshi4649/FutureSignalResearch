"""00011のBB内復帰を即時・次の連続一足確認へ分ける。"""

from __future__ import annotations

from collections import Counter, deque
import importlib.util
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[2]


def shared() -> Any:
    """固定00011の入口処理を変更せず読み込む。

    引数: なし。
    返り値: Any は共通準備とR2即時発動の固定実装。
    """
    spec = importlib.util.spec_from_file_location("反転確認の固定R2", ROOT/"scripts/テクニカル循環/入口.py")
    value = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = value
    spec.loader.exec_module(value)
    return value


CORE = shared()
MODES = ("即時", "次足確認")


def setting(signal: dict) -> dict:
    """設定足の当時の中心と高安を保存する。

    引数: signal (dict) は固定R2が成立した確定足。
    返り値: dict は将来値へ差し替えない設定足情報。
    """
    return {key: signal[key] for key in ("index", "end", "confirm", "confirm_line", "high", "low", "close", "bb_mean", "atr")}


def contexts(frames: list[dict], higher: list[dict]) -> dict[int, dict]:
    """確認足時点の共通準備と利用可能上位足を作る。

    引数: frames/higher (list[dict]) は同場の発動足/15分特徴。
    返り値: dict[int,dict] は足番号別の共通準備特徴。未公開は含めない。
    """
    history = deque(maxlen=6)
    pointer, upper, result = 0, None, {}
    for frame in frames:
        if not frame["publish"]:
            continue
        if frame["missing"]:
            history.clear()
        while pointer < len(higher) and (higher[pointer]["confirm"], higher[pointer]["confirm_line"]) <= (frame["confirm"], frame["confirm_line"]) and higher[pointer]["end"] <= frame["end"]:
            upper = higher[pointer]
            pointer += 1
        ready, direction = CORE.upper_state(upper)
        indicators = CORE.defined(frame["ema20"], frame["atr"], frame["adx"], frame["bb_mean"], frame["bb_sd"]) and frame["atr"] > 0
        result[frame["index"]] = {**frame, "共通準備済": bool(len(history) == 6 and indicators and ready),
            "上位準備済": ready, "上位方向": direction, "上位確認秒": upper["confirm"] if upper is not None else None,
            "上位確認行": upper["confirm_line"] if upper is not None else None,
            "上位足終了秒": upper["end"] if upper is not None else None}
        history.append(frame)
    return result


def make_signal(frame: dict, setup: dict, mode: str, side: int, session: str,
                deadline: float, config: dict) -> dict:
    """現在のATRと設定時中心・構造を持つ新規要求を作る。

    引数: frame/setup (dict) は判断/設定足、mode/session (str) は方式/場、side (int) は方向、
    deadline (float) は期限、config (dict) は固定条件。
    返り値: dict は未来ラベルを含まないsignal。
    """
    size = frame["minutes"]
    source_id = f"{size}分_{mode}"
    center = setup["bb_mean"]
    return {**frame, "bb_mean": center, "確認足bb_mean": frame["bb_mean"], "場": session,
        "時間足分": size, "入口ID": source_id, "確認方式": mode, "side": side, "方向": "買い" if side == 1 else "売り",
        "イベントID": f"NK225_{session}_{source_id}_{frame['index']:04d}_{side}",
        "要求時計秒": frame["confirm"], "要求原板行": frame["confirm_line"], "足終了時計秒": frame["end"],
        "確認遅延秒": frame["confirm"]-frame["end"], "期限時計秒": deadline,
        "元R2設定イベントID": setup["イベントID"],
        "設定足": setting(setup), "構造価格": setup["low"]-config["運用"]["呼値pt"] if side == 1 else setup["high"]+config["運用"]["呼値pt"],
        "設定中心まで方向距離pt": side*(center-frame["close"]), "残り分_判断時": (deadline-frame["confirm"])/60,
        "250ptのATR倍": 250/frame["atr"]}


# ----------------------------------------
# 旧設定の次足だけを判定し、現足の新しいR2登録はその後に行う。

def generate(frames: list[dict], higher: list[dict], session: str, cutoff: float,
             deadline: float, config: dict) -> tuple[dict[str, list[dict]], dict]:
    """同じR2設定から即時と一足確認の4入口を生成する。

    引数: frames/higher (list[dict]) は同場発動足/15分特徴、session (str) は場、
    cutoff/deadline (float) は新規停止/期限、config (dict) は固定条件。
    返り値: tuple[dict[str,list[dict]],dict] は当尺度2方式のsignalと品質。
    """
    if not frames:
        raise ValueError("入口尺度を特定できる足がありません")
    size = frames[0]["minutes"]
    original, quality = CORE.generate(frames, higher, session, cutoff, deadline, config)
    setups = {(r["index"], r["side"]): r for r in original[f"{size}分_R2"]}
    prepared = contexts(frames, higher)
    output = {f"{size}分_{mode}": [] for mode in MODES}
    active: dict[int, dict | None] = {1: None, -1: None}
    counts = Counter()
    for frame in frames:
        if not frame["publish"]:
            counts["設定非公開足失効"] += sum(s is not None for s in active.values())
            active = {1: None, -1: None}
            continue
        row = prepared[frame["index"]]
        if frame["missing"]:
            counts["設定欠枠失効"] += sum(s is not None for s in active.values())
            active = {1: None, -1: None}
        eligible = row["共通準備済"] and row["adx"] < 20 and row["confirm"] < cutoff and deadline-row["confirm"] >= config["残り時間下限分"]*60
        for side in (1, -1):
            setup = active[side]
            if setup is not None:
                if frame["index"] == setup["index"]+1 and not frame["missing"]:
                    counts["次足判定設定"] += 1
                    edge = setup["high"] if side == 1 else setup["low"]
                    if eligible and side*(row["close"]-edge) > 0 and side*(setup["bb_mean"]-row["close"]) > 0:
                        output[f"{size}分_次足確認"].append(make_signal(row, setup, "次足確認", side, session, deadline, config))
                        counts["次足確認発動"] += 1
                    else:
                        counts["次足未確認失効"] += 1
                else:
                    counts["一足満了"] += 1
                active[side] = None
            current = setups.get((frame["index"], side))
            if current is not None:
                immediate = make_signal(current, current, "即時", side, session, deadline, config)
                output[f"{size}分_即時"].append(immediate)
                active[side] = current
                counts["R2設定数"] += 1
    counts["場末設定失効"] += sum(s is not None for s in active.values())
    result = {"場": session, "時間足分": size, "共通準備可足": quality.get("共通準備可足", 0),
              "共通時間条件可足": quality.get("共通時間条件可足", 0), **dict(counts),
              "系統別発動数": {source: len(rows) for source, rows in output.items()}}
    return output, result
