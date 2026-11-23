"""固定00011のR1/R2価格入口へ、共通の数量準備とRVOL補助を付加する。"""

from __future__ import annotations

from collections import Counter
import importlib.util
import math
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
FAMILIES = {"R1": "端の失敗突破", "R2": "BB内復帰"}
EXTRAS = ("なし", "RVOL1.2以上")
QUANTITY_FIELDS = ("観測差分量", "数量基準完全", "直前数量足数", "直前数量合計", "直前数量平均",
                   "RVOL", "数量準備済", "最終採用数量時計", "最終採用価格時計", "最終採用原行", "数量不完全理由")


def shared() -> Any:
    """旧00011の価格入口を変更せず読み込む。

    引数: なし。
    返り値: Any は価格の共通準備とR1/R2発動。足幅の許可は新条件から渡す。
    """
    spec = importlib.util.spec_from_file_location("数量反転の固定価格入口", ROOT / "scripts/テクニカル循環/入口.py")
    value = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = value
    spec.loader.exec_module(value)
    return value


CORE = shared()


def unavailable_reason(quantity: dict) -> str | None:
    """数量準備除外を当足・履歴・分母の段階へ分ける。

    引数: quantity (dict) は当足の数量属性。
    返り値: str|None は除外理由または準備済み。
    """
    if quantity["数量準備済"]:
        return None
    if not quantity["数量基準完全"]:
        return "当足の数量基準不完全"
    if quantity["直前数量足数"] < 20:
        return "直前20数量足の未準備"
    average = quantity["直前数量平均"]
    if average is None or not math.isfinite(average) or average <= 0:
        return "直前数量平均が非正または未定義"
    return "数量状態が未準備"


def generate(frames: list[dict], higher: list[dict], session: str, cutoff: float,
             deadline: float, config: dict, quantity_by_index: dict[int, dict]) -> tuple[dict, dict]:
    """既存価格発動を数量準備で共通選別し、同じRVOL下限を比較する。

    引数: frames/higher (list[dict]) は同場1/3/5分と15分特徴、session (str) は場、
    cutoff/deadline (float) は停止/期限秒、config (dict) は固定条件、
    quantity_by_index (dict[int,dict]) は数量集約APIの価格足index別属性。
    返り値: tuple[dict,dict] は当尺度4入口と価格入口/数量除外の記録。
    """
    if not frames:
        raise ValueError("入口尺度を特定できる足がない")
    size = frames[0]["minutes"]
    if config["時間足分"] != [1, 3, 5] or size not in (1, 3, 5):
        raise ValueError("固定した1/3/5分だけを扱う")
    if config["数量条件"]["参照足数"] != 20 or config["数量条件"]["RVOL下限"] != 1.2 or config["数量条件"]["数量準備両側共通"] is not True:
        raise ValueError("数量20足・RVOL1.2・共通準備を変更しない")
    # 旧関数の尺度検査はconfigに従う。価格式・共通準備を変えず1分も同じ式で処理する。
    original, price_quality = CORE.generate(frames, higher, session, cutoff, deadline, config)
    output = {f"{size}分_{family}_{extra}": [] for family in FAMILIES for extra in EXTRAS}
    counts, excluded, family_price, family_excluded, records = Counter(), Counter(), Counter(), Counter(), []
    for family in FAMILIES:
        base_id = f"{size}分_{family}"
        for source in original[base_id]:
            index = source["index"]
            if index not in quantity_by_index or any(key not in quantity_by_index[index] for key in QUANTITY_FIELDS):
                raise ValueError("価格発動足の数量属性が欠けている")
            quantity = {key: quantity_by_index[index][key] for key in QUANTITY_FIELDS}
            reason = unavailable_reason(quantity)
            ready, rvol = bool(quantity["数量準備済"]), quantity["RVOL"]
            if ready and (rvol is None or not math.isfinite(rvol) or rvol < 0):
                raise ValueError("数量準備済みなのにRVOLが未定義または不正")
            counts["基準価格入口数"] += 1
            family_price[base_id] += 1
            if not ready:
                counts["数量準備除外数"] += 1
                excluded[reason] += 1
                family_excluded[base_id] += 1
            else:
                counts["数量準備通過数"] += 1
                counts["RVOL補助除外数"] += int(rvol < 1.2)
            records.append({"基準価格入口ID": base_id, "基準価格イベントID": source["イベントID"],
                            "場": session, "時間足分": size, "index": index, "side": source["side"],
                            "要求時計秒": source["要求時計秒"], "要求原板行": source["要求原板行"],
                            "数量準備除外理由": reason, **quantity})
            if not ready:
                continue
            for extra in EXTRAS:
                if extra != "なし" and rvol < 1.2:
                    continue
                source_id = f"{size}分_{family}_{extra}"
                signal = {**source, **quantity, "基準価格入口ID": base_id,
                          "基準価格イベントID": source["イベントID"], "入口ID": source_id,
                          "補助": extra, "イベントID": f"NK225_{session}_{source_id}_{index:04d}_{source['side']}"}
                output[source_id].append(signal)
    selected_quality = {key: price_quality.get(key, 0) for key in
                        ("公開足", "共通準備可足", "共通時間条件可足", "六本窓不足足", "指標未準備足", "上位未準備足")}
    return output, {"場": session, "時間足分": size, **{key: counts[key] for key in
                    ("基準価格入口数", "数量準備除外数", "数量準備通過数", "RVOL補助除外数")},
                    "系統別基準価格入口数": {f"{size}分_{f}": family_price[f"{size}分_{f}"] for f in FAMILIES},
                    "系統別数量準備除外数": {f"{size}分_{f}": family_excluded[f"{size}分_{f}"] for f in FAMILIES},
                    "数量準備除外理由": dict(excluded), "価格共通準備": selected_quality,
                    "系統別発動数": {key: len(rows) for key, rows in output.items()},
                    "基準価格入口記録": records}
