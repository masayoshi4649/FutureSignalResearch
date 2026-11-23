"""固定11の価格発動を保ち、共通N/D準備の中でVWAP位置・傾きだけを比較する。"""

from __future__ import annotations

from collections import Counter
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("VWAPの固定11価格入口", ROOT/"scripts/テクニカル循環/入口.py")
BASE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = BASE
SPEC.loader.exec_module(BASE)
BASE_CONDITION = ROOT/"study/00011_順行と反転のチャート構造と利益回収/条件.json"
BASE_CONFIG = json.loads(BASE_CONDITION.read_text(encoding="utf-8"))
BASE_CONFIG["時間足分"] = [1, 3, 5]
FAMILIES = {"T1": "押し目再開", "R2": "BB内復帰"}
ROLES = {"T1": "順行", "R2": "反転"}
SETTINGS = ("N_A", "N_B", "N_C", "D_A", "D_B", "D_D")


def validate_config(config: dict) -> None:
    """固定三尺度・二価格系統・六VWAP条件を検査する。

    引数: config (dict) は固定条件。
    返り値: None。不一致ではValueError。
    """
    if config["時間足分"] != [1, 3, 5] or config["入口系統"] != list(FAMILIES) or config["補助"] != list(SETTINGS) or config["参照条件"] != {"連続点数": 4, "傾き差本数": 3, "判断時点": True}:
        raise ValueError("固定三尺度・T1/R2・六設定・判断時点四点を変更しない")


def generate(frames: list[dict], higher: list[dict], session: str, cutoff: float,
             deadline: float, config: dict, references: dict[int, dict]) -> tuple[dict, dict]:
    """同じ旧11価格発動へN/D共通準備と位置/傾きの部分集合を付ける。

    引数: frames/higher (list[dict]) は価格足/上位足、session (str) は場、
    cutoff/deadline (float) は停止/期限、config (dict) は固定条件、references (dict) は全足補助参照。
    返り値: tuple[dict,dict] は当尺度12入口と価格P/六条件の通過記録。
    """
    validate_config(config)
    original, old_quality = BASE.generate(frames, higher, session, cutoff, deadline, deepcopy(BASE_CONFIG))
    size = frames[0]["minutes"]
    output = {f"{size}分_{family}_{setting}": [] for family in FAMILIES for setting in SETTINGS}
    records, counts = [], Counter()
    for family in FAMILIES:
        for price in original[f"{size}分_{family}"]:
            ref = references[price["index"]]
            native, differential = ref["配信VWAP"], ref["当場差分VWAP"]
            if ref["N共通準備"] and (not BASE.defined(native, ref["配信3足前VWAP"]) or min(native, ref["配信3足前VWAP"]) <= 0):
                raise ValueError("N共通準備と参照値が矛盾")
            if ref["D共通準備"] and (not ref["N共通準備"] or not BASE.defined(differential, ref["差分3足前VWAP"]) or min(differential, ref["差分3足前VWAP"]) <= 0):
                raise ValueError("D共通準備と参照値が矛盾")
            side, close = price["side"], price["close"]
            role = ROLES[family]
            n_position = native is not None and (side*(close-native) > 0 if role == "順行" else side*(native-close) > 0)
            d_position = differential is not None and (side*(close-differential) > 0 if role == "順行" else side*(differential-close) > 0)
            slope = native is not None and ref["配信3足前VWAP"] is not None and side*(native-ref["配信3足前VWAP"]) > 0
            passed = {"N_A": ref["N共通準備"], "N_B": ref["N共通準備"] and n_position,
                      "N_C": ref["N共通準備"] and n_position and slope,
                      "D_A": ref["D共通準備"], "D_B": ref["D共通準備"] and n_position,
                      "D_D": ref["D共通準備"] and d_position}
            ids = []
            for setting in SETTINGS:
                if not passed[setting]:
                    continue
                source_id = f"{size}分_{family}_{setting}"
                row = {**price, **ref, "価格入口ID": f"{size}分_{family}",
                       "価格イベントID": price["イベントID"], "入口ID": source_id,
                       "入口系統": family, "補助": setting, "役割": role,
                       "イベントID": f"NK225_{session}_{source_id}_{price['index']:04d}_{side}"}
                output[source_id].append(row)
                ids.append(source_id)
            counts["価格発動数"] += 1
            counts["N共通準備通過価格発動数"] += int(ref["N共通準備"])
            counts["D共通準備通過価格発動数"] += int(ref["D共通準備"])
            records.append({"場": session, "時間足分": size, "価格入口ID": f"{size}分_{family}",
                            "価格イベントID": price["イベントID"], "元価格信号": deepcopy(price),
                            **ref, "native位置成立": bool(n_position), "差分位置成立": bool(d_position),
                            "native傾き成立": bool(slope), "通過設定": {k: bool(v) for k, v in passed.items()},
                            "発動入口ID": ids})
    return output, {"場": session, "時間足分": size, **dict(counts),
                    "旧11価格品質": old_quality, "系統別発動数": {k: len(v) for k, v in output.items()},
                    "全価格発動記録": records}
