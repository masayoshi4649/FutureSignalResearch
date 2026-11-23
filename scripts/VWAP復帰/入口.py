"""同場N四点を共有し、VWAP再獲得順行とATR乖離内復帰を比較する。"""

from __future__ import annotations

from collections import Counter
import importlib.util
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("VWAP復帰の固定上位準備", ROOT/"scripts/テクニカル循環/入口.py")
CORE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = CORE
SPEC.loader.exec_module(CORE)
FAMILIES = {"Q1": "VWAP再獲得順行", "Q2": "VWAP乖離内復帰反転"}
ROLES = {"Q1": "順行", "Q2": "反転"}
EXTRAS = ("なし", "15分方向一致")


def validate_config(config: dict) -> None:
    """三尺度・二VWAP発動・二上位条件と固定閾値を検査する。

    引数: config (dict) は19条件。
    返り値: None。相違はValueError。
    """
    if config["時間足分"] != [1, 3, 5] or config["入口系統"] != list(FAMILIES) or config["補助"] != list(EXTRAS):
        raise ValueError("固定三尺度・Q1/Q2・二補助だけを扱う")
    if config["参照条件"] != {"連続点数": 4, "傾き差本数": 3, "判断時点": True} or config["Q条件"] != {"Q2乖離ATR倍率": 1, "Q1傾き差本数": 3}:
        raise ValueError("固定18参照・1ATR乖離・三足差を変更しない")


def trigger(row: dict, previous: dict, reference: dict, prior_reference: dict,
            side: int, family: str) -> bool:
    """前足から現足へのstrict位置変化を判定する。

    引数: row/previous (dict) は現/前価格足、reference/prior_reference (dict) は補助、side (int) は買1売−1、family (str) はQ1/Q2。
    返り値: bool は新VWAP発動。準備と時間は呼出側で検査する。
    """
    before = side*(previous["close"]-prior_reference["配信VWAP"])
    current = side*(row["close"]-reference["配信VWAP"])
    improved = side*(row["close"]-previous["close"]) > 0
    if family == "Q1":
        return bool(before <= 0 and current > 0 and improved
                    and side*(reference["配信VWAP"]-reference["配信3足前VWAP"]) > 0)
    if family == "Q2":
        return bool(before < -previous["atr"] and -row["atr"] <= current < 0 and improved)
    raise ValueError("未知のVWAP発動")


# ----------------------------------------
# 前足N四点は再要求せず、現在四点の中で前足nativeの有効性を確認する。

def generate(frames: list[dict], higher: list[dict], session: str, cutoff: float,
             deadline: float, config: dict, references: dict) -> tuple[dict, dict]:
    """公開判断時点のVWAP復帰から当尺度四入口を生成する。

    引数: frames/higher (list[dict]) は下位足/15分足、session (str) は場、cutoff/deadline (float) は停止/期限、
    config/references (dict) は固定条件/固定18の補助参照。
    返り値: tuple[dict,dict] は入口と共通準備/Q発動の記録。将来ラベルは読まない。
    """
    validate_config(config)
    if not frames:
        raise ValueError("入口尺度を特定する価格足がない")
    size = frames[0]["minutes"]
    if size not in (1, 3, 5) or any(f["minutes"] != size for f in frames):
        raise ValueError("同尺度の1/3/5分だけを扱う")
    output = {f"{size}分_{family}_{extra}": [] for family in FAMILIES for extra in EXTRAS}
    counts, rejected, records = Counter(), Counter(), []
    previous, previous_key, previous_index, upper, pointer = None, None, None, None, 0
    for frame in frames:
        key = frame["confirm"], frame["confirm_line"]
        if previous_key is not None and key < previous_key and frame["publish"]:
            raise ValueError("公開キーの後退")
        if frame["publish"]:
            previous_key = key
        if previous_index is not None and frame["index"] <= previous_index:
            raise ValueError("足番号の重複/後退")
        previous_index = frame["index"]
        if not frame["publish"]:
            previous = None
            continue
        if frame["confirm"] < frame["end"]:
            raise ValueError("足終了前の公開")
        while pointer < len(higher) and (higher[pointer]["confirm"], higher[pointer]["confirm_line"]) <= key and higher[pointer]["end"] <= frame["end"]:
            upper = higher[pointer]
            pointer += 1
        ready, direction = CORE.upper_state(upper)
        reference = references[frame["index"]]
        prior = references[previous["index"]] if previous is not None else None
        reasons = []
        if previous is None or frame["index"] != previous["index"]+1 or frame["missing"]:
            reasons.append("前足が同場連続公開でない")
        if not reference["N共通準備"]:
            reasons.append("現在N四点未準備")
        if previous is None or not CORE.defined(frame.get("atr"), previous.get("atr")) or min(frame["atr"], previous["atr"]) <= 0:
            reasons.append("現在または前ATR未準備")
        if prior is None or not prior["native有効"] or prior["補助epoch"] != reference["補助epoch"]:
            reasons.append("前native未確認またはepoch不一致")
        if not ready:
            reasons.append("上位未準備")
        if frame["confirm"]-frame["end"] > 30:
            reasons.append("確認遅延30秒超")
        time_ok = frame["confirm"] < cutoff and deadline-frame["confirm"] >= config["残り時間下限分"]*60
        counts["公開足数"] += 1
        counts["共通準備可足数"] += int(not reasons)
        counts["共通時間条件可足数"] += int(not reasons and time_ok)
        rejected.update(reasons)
        if not reasons and time_ok:
            if not CORE.defined(reference["配信VWAP"], reference["配信3足前VWAP"], prior["配信VWAP"]) or min(reference["配信VWAP"], reference["配信3足前VWAP"], prior["配信VWAP"]) <= 0:
                raise ValueError("N四点準備と参照値が矛盾")
            row = {**frame, **reference, "上位準備済": ready, "上位方向": direction,
                   "上位確認秒": upper["confirm"], "上位確認行": upper["confirm_line"],
                   "上位足終了秒": upper["end"],
                   "直前足": {**{k: previous[k] for k in ("index", "close", "atr", "confirm", "confirm_line")},
                              "配信VWAP": prior["配信VWAP"], "補助epoch": prior["補助epoch"]}}
            for family in FAMILIES:
                for side in (1, -1):
                    if not trigger(row, previous, reference, prior, side, family):
                        continue
                    ids = []
                    base_id = f"NK225_{session}_{size}分_{family}_{frame['index']:04d}_{side}"
                    for extra in EXTRAS:
                        if extra != "なし" and direction != side:
                            continue
                        source_id = f"{size}分_{family}_{extra}"
                        signal = {**row, "場": session, "時間足分": size, "入口ID": source_id,
                                  "入口系統": family, "補助": extra, "役割": ROLES[family], "side": side,
                                  "方向": "買い" if side == 1 else "売り", "QイベントID": base_id,
                                  "イベントID": f"NK225_{session}_{source_id}_{frame['index']:04d}_{side}",
                                  "要求時計秒": frame["confirm"], "要求原板行": frame["confirm_line"],
                                  "確認遅延秒": frame["confirm"]-frame["end"], "足終了時計秒": frame["end"],
                                  "期限時計秒": deadline, "残り分_判断時": (deadline-frame["confirm"])/60,
                                  "入口中心まで方向距離pt": None,
                                  "判断終値からnative方向距離pt": side*(reference["配信VWAP"]-frame["close"]),
                                  "250ptのATR倍": 250/frame["atr"]}
                        output[source_id].append(signal)
                        ids.append(source_id)
                    records.append({"場": session, "時間足分": size, "QイベントID": base_id,
                                    "系統": family, "side": side, "判断足番号": frame["index"],
                                    "要求時計秒": frame["confirm"], "要求原板行": frame["confirm_line"],
                                    "発動入口ID": ids})
        previous = frame
    return output, {"場": session, "時間足分": size, **dict(counts), "共通準備除外理由": dict(rejected),
                    "系統別発動数": {k: len(v) for k, v in output.items()}, "全Q発動記録": records}
