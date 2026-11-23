"""価格時計で利用可能な累積差分量と、同場の直前20足RVOLを集約する。"""

from __future__ import annotations

from collections import Counter, deque
import math
from typing import Any


def finite(value: float | None) -> bool:
    """数量と時計が有限値かを判定する。

    引数: value (float | None) は観測値。
    返り値: bool は欠測でなく有限か。
    """
    return value is not None and math.isfinite(value)


def bucket(index: int, start: float, minutes: int) -> dict:
    """一つの価格時計枠の数量記録を初期化する。

    引数: index (int) は同場番号、start (float) は場開始秒、minutes (int) は足幅。
    返り値: dict は価格有無・採用量・当足時計・不完全理由の作業状態。
    """
    return {"index": index, "start": start+index*minutes*60,
            "quantity": 0.0, "has_price": False, "current_clock_seen": False,
            "reasons": set(), "last_quantity_clock": None, "last_price_clock": None, "last_line": None}


# ----------------------------------------
# 原順の累積差分を処理する。足の確認行の新しい増分は次の枠へだけ入れる。

def aggregate(events: list[Any], frames: list[dict], start: float, finish: float,
              minutes: int) -> tuple[dict[int, dict], dict]:
    """原順観測から数量足を作り、公開価格足の番号へ数量属性を対応させる。

    引数: events (list[Any]) はnow/line/last/volume/volume_timeを持つ原順観測、
    frames (list[dict]) は同場同尺度の価格足または価格特徴、start/finish (float) は半開場内時計、
    minutes (int) は1/3/5分。
    返り値: tuple[dict[int,dict],dict] は価格足番号別の数量属性と数量品質。
    """
    if minutes not in (1, 3, 5) or not finite(start) or not finite(finish) or start >= finish:
        raise ValueError("1/3/5分と有限な場内の半開範囲が必要")
    width, counters = minutes*60, Counter()
    buckets = {}
    current, previous_key = None, None
    previous_quantity, previous_quantity_clock = None, None
    maximum_lead = maximum_lag = 0.0
    for event in events:
        counters["入力観測数"] += 1
        if not finite(event.now):
            counters["価格時計欠測除外"] += 1
            continue
        now, line = float(event.now), int(event.line)
        if not start <= now < finish:
            counters["場外時計除外"] += 1
            continue
        key = now, line
        if previous_key is not None and key < previous_key:
            counters["価格時計原行後退除外"] += 1
            continue
        previous_key = key
        counters["場内採用価格時計観測数"] += 1
        index = int((now-start)//width)
        if current is None or index != current["index"]:
            if current is not None:
                if index > current["index"]+1:
                    counters["価格時計枠空白区間数"] += 1
                    counters["価格時計欠枠数"] += index-current["index"]-1
                    previous_quantity = previous_quantity_clock = None
                if not current["has_price"]:
                    counters["無価格枠後基準切替数"] += 1
                    previous_quantity = previous_quantity_clock = None
            current = bucket(index, start, minutes)
            buckets[index] = current
        if finite(event.last) and event.last > 0:
            current["has_price"] = True
        invalid = False
        if not finite(event.volume) or event.volume < 0:
            current["reasons"].add("数量欠測または不正")
            counters["数量欠測不正観測数"] += 1
            invalid = True
        if not finite(event.volume_time):
            current["reasons"].add("数量時計欠測または不正")
            counters["数量時計欠測不正観測数"] += 1
            invalid = True
        if invalid:
            continue
        quantity, quantity_clock = float(event.volume), float(event.volume_time)
        offset = quantity_clock-now
        maximum_lead, maximum_lag = max(maximum_lead, offset), max(maximum_lag, -offset)
        counters["数量時計先行観測数"] += int(offset > 0)
        counters["数量時計遅延観測数"] += int(offset < 0)
        counters["数量時計同時計観測数"] += int(offset == 0)
        if offset > 0:
            continue
        counters["数量採用観測数"] += 1
        if previous_quantity is None:
            current["reasons"].add("初回または欠枠後の累積基準")
            counters["累積基準設定数"] += 1
        elif quantity < previous_quantity or quantity_clock < previous_quantity_clock:
            if quantity < previous_quantity:
                current["reasons"].add("採用累積数量減少")
                counters["採用累積数量減少数"] += 1
            if quantity_clock < previous_quantity_clock:
                current["reasons"].add("採用数量時計後退")
                counters["採用数量時計後退数"] += 1
        else:
            delta = quantity-previous_quantity
            current["quantity"] += delta
            counters["正の差分採用数"] += int(delta > 0)
        previous_quantity, previous_quantity_clock = quantity, quantity_clock
        current["current_clock_seen"] |= quantity_clock >= current["start"]
        current["last_quantity_clock"], current["last_price_clock"], current["last_line"] = quantity_clock, now, line

    # ----------------------------------------
    # 現在足は分母から外し、数量の完全性と価格公開の役割を区別する。
    history, result = deque(maxlen=20), {}
    previous_frame_index = None
    for frame in frames:
        index = frame["index"]
        if index in result or (previous_frame_index is not None and index <= previous_frame_index):
            raise ValueError("価格足の番号重複または後退")
        if frame["minutes"] != minutes or not math.isclose(frame["start"], start+index*width, rel_tol=0, abs_tol=1e-6):
            raise ValueError("価格足の尺度または開始時計が数量枠と異なります")
        info = buckets.get(index)
        if info is None or not info["has_price"]:
            raise ValueError("数量枠の価格観測と価格足が矛盾")
        if (previous_frame_index is not None and index != previous_frame_index+1) or frame.get("missing", 0):
            history.clear()
        previous_frame_index = index
        reasons = set(info["reasons"])
        if index == 0:
            reasons.add("セッション最初の数量足")
        if not info["current_clock_seen"]:
            reasons.add("当足に属する採用数量時計なし")
        complete = not reasons
        count = len(history)
        total = float(math.fsum(history)) if history else 0.0
        mean = total/count if count else None
        available = bool(complete and count == 20 and mean is not None and mean > 0)
        result[index] = {"観測差分量": info["quantity"], "数量基準完全": complete,
                         "直前数量足数": count, "直前数量合計": total, "直前数量平均": mean,
                         "RVOL": info["quantity"]/mean if available else None, "数量準備済": available,
                         "最終採用数量時計": info["last_quantity_clock"],
                         "最終採用価格時計": info["last_price_clock"], "最終採用原行": info["last_line"],
                         "数量不完全理由": sorted(reasons)}
        counters["数量価格足数"] += 1
        counters["数量基準完全足数"] += int(complete)
        counters["数量基準不完全足数"] += int(not complete)
        counters["直前20数量足利用可能足数"] += int(complete and count == 20)
        counters["数量準備済足数"] += int(available)
        counters["公開数量準備済足数"] += int(available and frame["publish"])
        if complete and frame["publish"]:
            history.append(info["quantity"])
        else:
            history.clear()
    quality = {"時間足分": minutes, **dict(counters), "最大数量時計先行秒": maximum_lead,
               "最大数量時計遅延秒": maximum_lag, "無価格数量枠数": sum(not b["has_price"] for b in buckets.values()),
               "価格足対象外の有価格数量枠数": sum(b["has_price"] and i not in result for i, b in buckets.items()),
               "数量基準完全は全約定の完全性ではない": True}
    return result, quality
