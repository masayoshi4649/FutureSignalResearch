"""価格極値の確認時点でだけRSIとの隣接二極値を比較する。"""

from __future__ import annotations

from collections import Counter, deque
import importlib.util
import math
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
FAMILIES = {"反転乖離": "反転乖離", "押し戻り継続": "押し戻り継続"}
ROLES = {"反転乖離": "反転", "押し戻り継続": "順行"}
EXTRAS = ("なし", "ネック位置確認")
PIVOT_SETTINGS = {"左足本数": 2, "右足本数": 2, "中心間隔下限本数": 3, "中心間隔上限本数": 20, "RSI期間": 14}


def shared() -> Any:
    """旧00011の有限値判定と上位準備だけを読み込む。

    引数: なし。
    返り値: Any は旧入口モジュール。旧generateや売買条件は呼ばない。
    """
    spec = importlib.util.spec_from_file_location("RSI構造の上位準備", ROOT/"scripts/テクニカル循環/入口.py")
    value = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = value
    spec.loader.exec_module(value)
    return value


CORE = shared()


def validate_config(config: dict) -> None:
    """固定された足幅・二系統・左右本数を検査する。

    引数: config (dict) は00015の条件。
    返り値: None。不一致ではValueErrorを送出する。
    """
    if config["時間足分"] != [1, 3, 5] or config["入口系統"] != list(FAMILIES) or config["補助"] != list(EXTRAS):
        raise ValueError("固定した1/3/5分・二系統・二補助だけを扱う")
    if config["極値条件"] != PIVOT_SETTINGS:
        raise ValueError("左右2本・間隔3〜20本・中心RSI14を変更しない")


def pivot(center: dict, judgment: dict, side: int) -> dict:
    """中心足の公開と二本後の極値確認を別名で保存する。

    引数: center/judgment (dict) は中心足/確認足、side (int) は安値1・高値−1。
    返り値: dict は不変の極値記録。非有限な中心RSIはNoneに正規化する。
    """
    return {"中心番号": center["index"], "中心足開始秒": center["start"], "中心足終了秒": center["end"],
            "中心足公開時計秒": center["confirm"], "中心足公開原行": center["confirm_line"],
            "中心高値": center["high"], "中心安値": center["low"], "中心終値": center["close"],
            "中心RSI14": center["rsi"] if CORE.defined(center.get("rsi")) else None,
            "極値価格": center["low"] if side == 1 else center["high"],
            "極値確認足index": judgment["index"], "極値確認足終了秒": judgment["end"],
            "極値確認時計秒": judgment["confirm"], "極値確認原行": judgment["confirm_line"]}


def relation(previous: dict | None, current: dict, side: int) -> str | None:
    """中心価格と中心RSIの厳密な符号関係だけを分類する。

    引数: previous (dict|None) は同側直前極値、current (dict) は今回極値、side (int) は安値1・高値−1。
    返り値: str|None は反転乖離/押し戻り継続。準備・距離・上位・時間は別判定。
    """
    if previous is None or not CORE.defined(previous["中心RSI14"], current["中心RSI14"]):
        return None
    price = side*(current["極値価格"]-previous["極値価格"])
    strength = side*(current["中心RSI14"]-previous["中心RSI14"])
    if price < 0 and strength > 0:
        return "反転乖離"
    if price > 0 and strength < 0:
        return "押し戻り継続"
    return None


# ----------------------------------------
# 全pivotを先に記録し、送信できない場合でも同側の隣接極値を更新する。

def generate(frames: list[dict], higher: list[dict], session: str, cutoff: float,
             deadline: float, config: dict) -> tuple[dict[str, list[dict]], dict]:
    """公開連続五足で極値を確認し、二極値と同足ネック位置を評価する。

    引数: frames/higher (list[dict]) は同場1/3/5分/15分特徴、session (str) は場、
    cutoff/deadline (float) は新規停止/期限秒、config (dict) は固定条件。
    返り値: tuple[dict[str,list[dict]],dict] は当尺度四入口と全pivot/品質。
    """
    validate_config(config)
    if not frames:
        raise ValueError("入口尺度を特定できる足がない")
    size = frames[0]["minutes"]
    if size not in (1, 3, 5) or any(row["minutes"] != size for row in frames):
        raise ValueError("当場の同尺度1/3/5分だけを扱う")
    output = {f"{size}分_{family}_{extra}": [] for family in FAMILIES for extra in EXTRAS}
    window, segment = deque(maxlen=5), {}
    previous_pivot = {1: None, -1: None}
    counter, rejected, records = Counter(), Counter(), []
    pointer, upper, previous_key, previous_index = 0, None, None, None
    for frame in frames:
        key = frame["confirm"], frame["confirm_line"]
        if previous_key is not None and key < previous_key:
            raise ValueError("足の公開キーが後退")
        if previous_index is not None and frame["index"] <= previous_index:
            raise ValueError("価格足番号が重複または後退")
        gap = previous_index is not None and frame["index"] != previous_index+1
        previous_key, previous_index = key, frame["index"]
        if not frame["publish"] or frame["missing"] or gap:
            window.clear()
            segment.clear()
            previous_pivot = {1: None, -1: None}
            counter["非公開リセット" if not frame["publish"] else "連続窓リセット"] += 1
        if not frame["publish"]:
            continue
        if frame["confirm"] < frame["end"]:
            raise ValueError("足終了前の公開")
        if not CORE.defined(frame["low"], frame["high"], frame["close"]):
            raise ValueError("公開価格足のOHLCが非有限")
        while pointer < len(higher) and (higher[pointer]["confirm"], higher[pointer]["confirm_line"]) <= key and higher[pointer]["end"] <= frame["end"]:
            upper = higher[pointer]
            pointer += 1
        ready, direction = CORE.upper_state(upper)
        row = {**frame, "上位準備済": ready, "上位方向": direction,
               "上位確認秒": upper["confirm"] if upper is not None else None,
               "上位確認行": upper["confirm_line"] if upper is not None else None,
               "上位足終了秒": upper["end"] if upper is not None else None,
               "上位足番号": upper["index"] if upper is not None else None}
        counter["公開足"] += 1
        window.append(row)
        segment[row["index"]] = row
        if len(window) < 5:
            counter["極値五足窓不足"] += 1
            continue
        five = list(window)
        left, center, right = five[:2], five[2], five[3:]
        indicators = CORE.defined(row.get("rsi"), row.get("atr")) and row["atr"] > 0
        common = bool(indicators and ready)
        time_ok = frame["confirm"] < cutoff and deadline-frame["confirm"] >= config["残り時間下限分"]*60
        for side in (1, -1):
            field = "low" if side == 1 else "high"
            found = all(side*(center[field]-part[field]) < 0 for part in left) and all(side*(center[field]-part[field]) <= 0 for part in right)
            if not found:
                continue
            current, previous = pivot(center, row, side), previous_pivot[side]
            distance = current["中心番号"]-previous["中心番号"] if previous else None
            interval = [part for index, part in segment.items() if previous is not None and previous["中心番号"] < index < current["中心番号"]]
            between_high = max((part["high"] for part in interval), default=None)
            between_low = min((part["low"] for part in interval), default=None)
            neck = between_high if side == 1 else between_low
            neck_ok = neck is not None and side*(row["close"]-neck) > 0
            family = relation(previous, current, side)
            distance_ok = distance is not None and 3 <= distance <= 20
            center_ready = previous is not None and CORE.defined(previous["中心RSI14"], current["中心RSI14"])
            improved = side*(row["close"]-five[-2]["close"]) > 0
            reasons = []
            if previous is None:
                reasons.append("前極値なし")
            elif not distance_ok:
                reasons.append("中心間隔範囲外")
            if not center_ready:
                reasons.append("中心RSI未準備")
            if family is None:
                reasons.append("価格RSI型不成立")
            if not indicators:
                reasons.append("判断RSI_ATR未準備")
            if not ready:
                reasons.append("上位未準備")
            if not time_ok:
                reasons.append("時間条件不成立")
            if not improved:
                reasons.append("終値改善不成立")
            if family == "押し戻り継続" and direction != side:
                reasons.append("継続上位方向不一致")
            by_extra = {extra: reasons + (["ネック位置不成立"] if extra != "なし" and not neck_ok else []) for extra in EXTRAS}
            record = {"場": session, "時間足分": size, "side": side, "極値種別": "安値" if side == 1 else "高値",
                      "現極値": current, "前極値": previous, "極値間隔本数": distance,
                      "極値間高値": between_high, "極値間安値": between_low,
                      "ネック価格": neck, "ネック条件成立": bool(neck_ok), "価格RSI型": family,
                      "判断足番号": row["index"], "要求時計秒": row["confirm"], "要求原板行": row["confirm_line"],
                      "判断終値": row["close"], "直前終値": five[-2]["close"], "判断RSI14": row["rsi"], "判断ATR14": row["atr"],
                      "上位準備済": ready, "上位方向": direction, "上位確認秒": row["上位確認秒"],
                      "上位確認行": row["上位確認行"], "上位足終了秒": row["上位足終了秒"], "上位足番号": row["上位足番号"],
                      "中心間隔適合": bool(distance_ok), "中心RSI準備済": bool(center_ready),
                      "共通準備済": common, "時間条件成立": bool(time_ok), "終値改善": bool(improved),
                      "除外理由": reasons, "追加確認別除外理由": by_extra, "発動入口ID": []}
            counter["確定安値数" if side == 1 else "確定高値数"] += 1
            counter["隣接対数"] += int(previous is not None)
            counter["距離適合対数"] += int(distance_ok)
            counter["中心RSI準備対数"] += int(center_ready)
            counter["価格RSI型適合対数"] += int(family is not None)
            counter["共通準備可極値数"] += int(common)
            counter["共通時間条件可極値数"] += int(common and time_ok)
            rejected.update(reasons)
            for extra in EXTRAS:
                if by_extra[extra]:
                    continue
                source_id = f"{size}分_{family}_{extra}"
                signal = {**row, **{k: record[k] for k in ("現極値", "前極値", "極値間隔本数", "極値間高値", "極値間安値", "ネック価格", "ネック条件成立")},
                          "場": session, "時間足分": size, "入口ID": source_id, "入口系統": family, "補助": extra,
                          "追加確認": extra, "役割": ROLES[family], "side": side, "方向": "買い" if side == 1 else "売り",
                          "イベントID": f"NK225_{session}_{source_id}_{row['index']:04d}_{side}",
                          "要求時計秒": row["confirm"], "要求原板行": row["confirm_line"],
                          "確認遅延秒": row["confirm"]-row["end"], "期限時計秒": deadline,
                          "足終了時計秒": row["end"], "残り分_判断時": (deadline-row["confirm"])/60,
                          "入口中心まで方向距離pt": side*(row["bb_mean"]-row["close"]) if CORE.defined(row.get("bb_mean")) else None,
                          "250ptのATR倍": 250/row["atr"]}
                output[source_id].append(signal)
                record["発動入口ID"].append(source_id)
                counter["確認遅延超過発動"] += int(signal["確認遅延秒"] > config["確認遅延上限秒"])
            records.append(record)
            # 未準備・時間外・距離外・補助不成立でも、同側の次の比較対象は今回へ更新する。
            previous_pivot[side] = current
    return output, {"場": session, "時間足分": size, **dict(counter), "極値除外理由": dict(rejected),
                    "系統別発動数": {key: len(rows) for key, rows in output.items()}, "全pivot記録": records}
