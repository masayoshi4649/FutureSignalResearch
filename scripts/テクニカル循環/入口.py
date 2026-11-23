"""00011の共通準備と4種類のチャート入口を、確定足だけから生成する。"""

from __future__ import annotations

from collections import Counter, deque
import math


FAMILIES = {"T1": "押し目再開", "T2": "突破後再テスト", "R1": "端の失敗突破", "R2": "BB内復帰"}


def defined(*values: float | None) -> bool:
    """指標と価格の有限な準備状態を調べる。

    引数: values (float | None) は確認対象。
    返り値: bool は全て定義された有限値か。
    """
    return all(v is not None and math.isfinite(v) for v in values)


def upper_state(frame: dict | None) -> tuple[bool, int]:
    """公開済み15分足の準備と方向を分ける。

    引数: frame (dict | None) は同場で利用可能な最後の15分足。
    返り値: tuple[bool,int] は準備済みと買1・中立0・売−1。
    """
    if frame is None or not frame["publish"] or not defined(frame["close"], frame["ema20"], frame["ema20_previous"]):
        return False, 0
    direction = 1 if frame["close"] > frame["ema20"] > frame["ema20_previous"] else (
        -1 if frame["close"] < frame["ema20"] < frame["ema20_previous"] else 0)
    return True, direction


def trigger(row: dict, previous: dict, side: int, family: str) -> bool:
    """状態を持たない3系統の当足発動を判定する。

    引数: row/previous (dict) は現・直前の確定特徴、side (int) は買1/売−1、family (str) はT1/R1/R2。
    返り値: bool は発動。T2の登録状態はgenerateで管理する。
    """
    improved = side*(row["close"]-previous["close"]) > 0
    if family == "T1":
        return bool(previous["上位準備済"] and previous["上位方向"] == side == row["上位方向"]
                    and defined(previous["ema20"]) and side*(previous["close"]-previous["ema20"]) <= 0
                    and side*(row["close"]-row["ema20"]) > 0
                    and side*(row["ema20"]-previous["ema20"]) > 0 and improved)
    center_ahead = side*(row["bb_mean"]-row["close"]) > 0
    if family == "R1":
        low, high = row["直前6安値"], row["直前6高値"]
        recovery = row["low"] < low < row["close"] <= high if side == 1 else (
            row["high"] > high > row["close"] >= low)
        return bool(recovery and improved and row["adx"] < 20 and center_ahead)
    if family == "R2":
        return bool(defined(previous["bb_mean"], previous["bb_sd"])
                    and side*(previous["close"]-previous["bb_mean"]) < -2*previous["bb_sd"]
                    and side*(row["close"]-row["bb_mean"]) >= -2*row["bb_sd"]
                    and center_ahead and improved and row["adx"] < 20)
    raise ValueError("未知の状態なし入口")


# ----------------------------------------
# T2は前の確定足で登録した水準だけを使い、当足自身の突破を再テストとしない。

def generate(frames: list[dict], higher: list[dict], session: str, cutoff: float,
             deadline: float, config: dict) -> tuple[dict[str, list[dict]], dict]:
    """共通準備後の4入口と、再テストの消費・失効を生成する。

    引数: frames/higher (list[dict]) は同場の3/5分・15分特徴、session (str) は場、
    cutoff/deadline (float) は新規停止・期限秒、config (dict) は固定条件。
    返り値: tuple[dict[str,list[dict]],dict] は8入口のうち当尺度4入口と品質集計。
    """
    if not frames:
        raise ValueError("入口尺度を特定できる足がありません")
    size = frames[0]["minutes"]
    if size not in config["時間足分"] or any(f["minutes"] != size for f in frames):
        raise ValueError("入口は固定した3分または5分の同尺度だけ")
    output = {f"{size}分_{family}": [] for family in FAMILIES}
    history = deque(maxlen=6)
    active: dict[int, dict | None] = {1: None, -1: None}
    counter = Counter()
    pointer, upper = 0, None
    previous_key = None
    for frame in frames:
        key = frame["confirm"], frame["confirm_line"]
        if previous_key is not None and key < previous_key:
            raise ValueError("確定足の確認順が後退")
        previous_key = key
        if not frame["publish"]:
            counter["非公開足"] += 1
            continue
        if frame["confirm"] < frame["end"]:
            raise ValueError("足終了前の公開")
        if frame["missing"]:
            counter["欠枠後リセット"] += 1
            history.clear()
            active = {1: None, -1: None}
        while pointer < len(higher) and (higher[pointer]["confirm"], higher[pointer]["confirm_line"]) <= key and higher[pointer]["end"] <= frame["end"]:
            upper = higher[pointer]
            pointer += 1
        ready, direction = upper_state(upper)
        row = {**frame, "上位準備済": ready, "上位方向": direction,
               "上位確認秒": upper["confirm"] if upper is not None else None,
               "上位確認行": upper["confirm_line"] if upper is not None else None,
               "上位足終了秒": upper["end"] if upper is not None else None,
               "直前6高値": max((h["high"] for h in history), default=None) if len(history) == 6 else None,
               "直前6安値": min((h["low"] for h in history), default=None) if len(history) == 6 else None}
        previous = history[-1] if history else None
        row["直前足"] = {k: previous.get(k) for k in ("index", "close", "ema20", "bb_mean", "bb_sd", "上位準備済", "上位方向", "上位確認秒", "上位確認行")} if previous else None
        indicators = defined(row["ema20"], row["atr"], row["adx"], row["bb_mean"], row["bb_sd"]) and row["atr"] > 0
        common = bool(previous and len(history) == 6 and indicators and ready)
        eligible = common and frame["confirm"] < cutoff and deadline-frame["confirm"] >= config["残り時間下限分"]*60
        counter["公開足"] += 1
        counter["共通準備可足"] += int(common)
        counter["共通時間条件可足"] += int(eligible)
        counter["六本窓不足足"] += int(len(history) != 6)
        counter["指標未準備足"] += int(not indicators)
        counter["上位未準備足"] += int(not ready)
        for side in (1, -1):
            registration = active[side]
            retest = False
            if registration is not None:
                age = frame["index"]-registration["index"]
                if age > 3:
                    counter["再テスト満了"] += 1
                    active[side] = None
                elif side*(row["close"]-registration["水準"]) <= 0:
                    counter["再テスト終値失効"] += 1
                    active[side] = None
                elif 1 <= age <= 3 and eligible and direction == side:
                    edge = row["low"] if side == 1 else row["high"]
                    tick = config["運用"]["呼値pt"]
                    retest = abs(edge-registration["水準"]) <= tick and side*(row["close"]-registration["水準"]) > tick
            if eligible:
                members = [f for f in ("T1", "R1", "R2") if trigger(row, previous, side, f)]
                if retest:
                    members.append("T2")
                for family in FAMILIES:
                    if family not in members:
                        continue
                    source = f"{size}分_{family}"
                    signal = {**row, "場": session, "時間足分": size, "入口ID": source, "入口系統": family,
                              "side": side, "方向": "買い" if side == 1 else "売り",
                              "イベントID": f"NK225_{session}_{source}_{frame['index']:04d}_{side}",
                              "要求時計秒": frame["confirm"], "要求原板行": frame["confirm_line"],
                              "確認遅延秒": frame["confirm"]-frame["end"], "期限時計秒": deadline,
                              "足終了時計秒": frame["end"], "残り分_判断時": (deadline-frame["confirm"])/60,
                              "入口中心まで方向距離pt": side*(row["bb_mean"]-row["close"]),
                              "250ptのATR倍": 250/row["atr"],
                              "再テスト登録": dict(registration) if family == "T2" else None}
                    output[source].append(signal)
                    counter["確認遅延超過発動"] += int(signal["確認遅延秒"] > config["確認遅延上限秒"])
                if retest:
                    active[side] = None
                    counter["再テスト消費"] += 1
            # 当足の突破を最後に登録し、この足での再テストには利用しない。
            if len(history) == 6:
                level = row["直前6高値"] if side == 1 else row["直前6安値"]
                if side*(row["close"]-level) > 0:
                    active[side] = {"index": frame["index"], "確認行": frame["confirm_line"],
                                    "確認秒": frame["confirm"], "水準": level}
                    counter["再テスト登録"] += 1
        history.append(row)
    return output, {"場": session, "時間足分": size, **dict(counter),
                    "系統別発動数": {source: len(rows) for source, rows in output.items()}}
