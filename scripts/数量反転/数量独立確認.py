"""00014の観測数量・RVOLと全価格入口を、固定cacheから独立に再構成する。"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict, deque
import gzip
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys
from typing import Any

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT / "study/00014_反転入口と観測差分量"
WORK = ROOT / "work/数量反転/00014"
MANIFEST = ROOT / "study/00008_外部研究を共通尺度へ移して探索/入力台帳.json"
LEGACY_MANIFEST = ROOT / "work/複合検証/入力キャッシュ台帳.json"
INDEPENDENT = ROOT / "scripts/収縮反転/状態独立確認.py"
QFIELDS = ("観測差分量", "数量基準完全", "直前数量足数", "直前数量合計", "直前数量平均",
           "RVOL", "数量準備済", "最終採用数量時計", "最終採用価格時計", "最終採用原行", "数量不完全理由")
PRICE_FIELDS = ("index", "start", "end", "minutes", "open", "high", "low", "close", "missing", "publish",
                "confirm", "confirm_line", "ema20", "ema20_previous", "atr", "adx", "bb_mean", "bb_sd",
                "上位準備済", "上位方向", "上位確認秒", "上位確認行", "上位足終了秒",
                "直前6高値", "直前6安値", "直前足", "side", "要求時計秒", "要求原板行", "確認遅延秒",
                "入口系統", "入口ID", "基準価格入口ID", "基準価格イベントID", "補助", "期間")


def module(path: Path, name: str) -> Any:
    """過去に別実装した足・指標補助だけを読み込む。

    引数: path (Path) は独立補助、name (str) は識別名。
    返り値: Any はモジュール。00014数量・入口・driverは読み込まない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


S = module(INDEPENDENT, "数量監査の独立価格補助")


def read(path: Path) -> Any:
    """UTF-8のJSONを読み取る。

    引数: path (Path) は資料。
    返り値: Any は復元したJSON値。
    """
    return json.loads(path.read_text(encoding="utf-8-sig"))


def sha(path: Path) -> str:
    """原板以外の入力・監査コードを指紋化する。

    引数: path (Path) は対象。
    返り値: str はSHA256。巨大原板本文は再走査しない。
    """
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def compressed_rows(path: Path) -> tuple[list[dict], str]:
    """保存された全行と展開内容SHAを取得する。

    引数: path (Path) はUTF-8のgzip JSONL。
    返り値: tuple[list[dict],str] は行と展開内容SHA256。
    """
    rows, digest = [], hashlib.sha256()
    with gzip.open(path, "rb") as stream:
        for line in stream:
            digest.update(line)
            if line.strip():
                rows.append(json.loads(line))
    return rows, digest.hexdigest()


def observed(entry: dict, source_root: Path) -> dict[str, np.ndarray]:
    """固定cacheを一度読み、driverと同じ場内非後退価格時計列を取得する。

    引数: entry (dict) は固定台帳行、source_root (Path) は共通原板ルート。
    返り値: dict[str,np.ndarray] は数量に必要な5列。原板はstatだけを確認する。
    """
    source, path = source_root / entry["source_path"], ROOT / "work/複合検証" / entry["cache_path"]
    status = source.stat()
    if (status.st_size, status.st_mtime_ns) != (entry["source_size"], entry["source_mtime_ns"]):
        raise ValueError("固定原板statが変更")
    if sha(path) != entry["sha256_cache"] or path.stat().st_size != entry["cache_size"]:
        raise ValueError("固定cache指紋が不一致")
    with np.load(path, allow_pickle=False) as archive:
        data = {key: archive[key] for key in ("now", "line", "last", "volume", "volume_time")}
    start, finish, _, _ = S.G.times(entry["session"])
    positions = np.flatnonzero(np.isfinite(data["now"]) & (data["now"] >= start) & (data["now"] <= finish))
    times = data["now"][positions]
    if len(times):
        positions = positions[np.r_[True, times[1:] >= np.maximum.accumulate(times[:-1])]]
    return {key: values[positions] for key, values in data.items()}


# ----------------------------------------
# 原順を価格時計の区間に先分割し、採用累積配列の隣接差分から量を求める。

def quantity_blocks(data: dict, start: float, finish: float, minutes: int,
                    legacy: bool = False) -> tuple[dict[int, dict], dict]:
    """価格時計区間ごとに数量の受入れ・差分と基準切替を独立に計算する。

    引数: data (dict) は同長の5列、start/finish (float) は半開範囲、minutes (int) は足幅、
    legacy (bool) は旧5分台帳の定義を別検算する場合だけ真。
    返り値: tuple[dict[int,dict],dict] は枠別量/理由/最終採用と品質。数量時計順には並べ替えない。
    """
    if minutes not in (1, 3, 5) or not math.isfinite(start) or not math.isfinite(finish) or start >= finish:
        raise ValueError("有限な場内範囲と1/3/5分が必要")
    counts = Counter({"入力観測数": len(data["now"])})
    keep, previous_key = [], None
    for position, (now, line) in enumerate(zip(data["now"], data["line"])):
        if not math.isfinite(now):
            counts["価格時計欠測除外"] += 1
            continue
        if not start <= now < finish:
            counts["場外時計除外"] += 1
            continue
        key = (float(now), 0 if legacy else int(line))
        if previous_key is not None and key < previous_key:
            counts["価格時計原行後退除外"] += 1
            continue
        previous_key = key
        keep.append(position)
    selected = {key: values[keep] for key, values in data.items()}
    counts["場内採用価格時計観測数"] = len(keep)
    width, result = 60 * minutes, {}
    indices = ((selected["now"] - start) // width).astype(int)
    heads = np.flatnonzero(np.r_[True, indices[1:] != indices[:-1]]) if len(indices) else []
    tails = np.r_[heads[1:], len(indices)] if len(indices) else []
    previous_index, prior_volume, prior_clock, prior_has_price = None, None, None, True
    maximum_lead = maximum_lag = 0.0
    for first, after in zip(heads, tails):
        index = int(indices[first])
        piece = {key: values[first:after] for key, values in selected.items()}
        has_price = bool(np.any(np.isfinite(piece["last"]) & (piece["last"] > 0)))
        gap = previous_index is not None and index > previous_index + 1
        no_price = previous_index is not None and not prior_has_price
        if gap:
            counts["価格時計枠空白区間数"] += 1
            counts["価格時計欠枠数"] += index - previous_index - 1
        if no_price:
            counts["無価格枠後基準切替数"] += 1
        if gap or (no_price and not legacy):
            prior_volume = prior_clock = None
        previous_index, prior_has_price = index, has_price
        bad_quantity = ~np.isfinite(piece["volume"]) | (piece["volume"] < 0)
        bad_clock = ~np.isfinite(piece["volume_time"])
        counts["数量欠測不正観測数"] += int(np.count_nonzero(bad_quantity))
        counts["数量時計欠測不正観測数"] += int(np.count_nonzero(bad_clock))
        reasons = set()
        if not legacy:
            if np.any(bad_quantity):
                reasons.add("数量欠測または不正")
            if np.any(bad_clock):
                reasons.add("数量時計欠測または不正")
        eligible = ~bad_quantity & ~bad_clock
        offsets = piece["volume_time"][eligible] - piece["now"][eligible]
        if len(offsets):
            maximum_lead = max(maximum_lead, float(np.max(offsets)))
            maximum_lag = max(maximum_lag, float(np.max(-offsets)))
        counts["数量時計先行観測数"] += int(np.count_nonzero(offsets > 0))
        counts["数量時計遅延観測数"] += int(np.count_nonzero(offsets < 0))
        counts["数量時計同時計観測数"] += int(np.count_nonzero(offsets == 0))
        accepted = np.flatnonzero(eligible & (piece["volume_time"] <= piece["now"]))
        counts["数量採用観測数"] += len(accepted)
        quantity, current_clock_seen, last_clock, last_now, last_line = 0.0, False, None, None, None
        if len(accepted):
            volumes, clocks = piece["volume"][accepted], piece["volume_time"][accepted]
            previous_values = np.r_[volumes[0] if prior_volume is None else prior_volume, volumes[:-1]]
            previous_clocks = np.r_[clocks[0] if prior_clock is None else prior_clock, clocks[:-1]]
            falls, backwards = volumes < previous_values, clocks < previous_clocks
            transitions = ~(falls | backwards)
            if prior_volume is None:
                reasons.add("初回または欠枠後の累積基準")
                counts["累積基準設定数"] += 1
                transitions[0] = False
            if np.any(falls):
                reasons.add("採用累積数量減少")
            if np.any(backwards):
                reasons.add("採用数量時計後退")
            counts["採用累積数量減少数"] += int(np.count_nonzero(falls))
            counts["採用数量時計後退数"] += int(np.count_nonzero(backwards))
            increments = (volumes - previous_values)[transitions]
            quantity = float(math.fsum(float(value) for value in increments))
            counts["正の差分採用数"] += int(np.count_nonzero(increments > 0))
            prior_volume, prior_clock = float(volumes[-1]), float(clocks[-1])
            current_clock_seen = bool(np.any(clocks >= start + index * width))
            last_clock, last_now = float(clocks[-1]), float(piece["now"][accepted[-1]])
            last_line = int(piece["line"][accepted[-1]])
        result[index] = {"quantity": quantity, "has_price": has_price, "reasons": reasons,
                         "current_clock_seen": current_clock_seen, "accepted": len(accepted),
                         "last_clock": last_clock, "last_now": last_now, "last_line": last_line}
    counts["最大数量時計先行秒"], counts["最大数量時計遅延秒"] = maximum_lead, maximum_lag
    counts["無価格数量枠数"] = sum(not b["has_price"] for b in result.values())
    return result, dict(counts)


def independent_quantity(data: dict, frames: list[dict], start: float, finish: float,
                         minutes: int) -> tuple[dict[int, dict], dict]:
    """独立区間量へ、当足を含めない公開済み直前20足のRVOLを付加する。

    引数: data (dict) は原順5列、frames (list[dict]) は独立価格足、start/finish (float) は範囲、
    minutes (int) は1/3/5分。
    返り値: tuple[dict[int,dict],dict] はQ11と独立品質。数量と公開の準備を分離する。
    """
    blocks, counts = quantity_blocks(data, start, finish, minutes)
    result, usable, previous = {}, deque(maxlen=20), None
    for frame in frames:
        index = frame["index"]
        if index in result or previous is not None and index <= previous:
            raise ValueError("独立価格足indexが一意昇順でない")
        if frame["minutes"] != minutes or frame["start"] != start + index * minutes * 60:
            raise ValueError("独立価格足の尺度・起点が不正")
        row = blocks.get(index)
        if row is None or not row["has_price"]:
            raise ValueError("独立価格足と数量枠が矛盾")
        if frame["missing"] or previous is not None and index != previous + 1:
            usable.clear()
        previous = index
        reasons = set(row["reasons"])
        if index == 0:
            reasons.add("セッション最初の数量足")
        if not row["current_clock_seen"]:
            reasons.add("当足に属する採用数量時計なし")
        complete, count = not reasons, len(usable)
        total = math.fsum(usable)
        mean = total / count if count else None
        ready = bool(complete and count == 20 and mean is not None and mean > 0)
        result[index] = {"観測差分量": row["quantity"], "数量基準完全": complete,
                         "直前数量足数": count, "直前数量合計": total, "直前数量平均": mean,
                         "RVOL": row["quantity"] / mean if ready else None, "数量準備済": ready,
                         "最終採用数量時計": row["last_clock"], "最終採用価格時計": row["last_now"],
                         "最終採用原行": row["last_line"], "数量不完全理由": sorted(reasons)}
        for name, add in (("数量価格足数", 1), ("数量基準完全足数", complete),
                          ("数量基準不完全足数", not complete), ("直前20数量足利用可能足数", complete and count == 20),
                          ("数量準備済足数", ready), ("公開数量準備済足数", ready and frame["publish"])):
            counts[name] = counts.get(name, 0) + int(add)
        if complete and frame["publish"]:
            usable.append(row["quantity"])
        else:
            usable.clear()
    counts["価格足対象外の有価格数量枠数"] = sum(b["has_price"] and i not in result for i, b in blocks.items())
    counts["時間足分"], counts["数量基準完全は全約定の完全性ではない"] = minutes, True
    return result, counts


# ----------------------------------------
# 価格の全発動を原価格から求め、数量準備とRVOL条件を最後に適用する。

def exclusion(quantity: dict) -> str | None:
    """数量の未準備を基準・履歴・分母の順に説明する。

    引数: quantity (dict) は独立Q11。
    返り値: str|None は除外理由。数量の準備済みならNone。
    """
    if quantity["数量準備済"]:
        return None
    if not quantity["数量基準完全"]:
        return "当足の数量基準不完全"
    if quantity["直前数量足数"] < 20:
        return "直前20数量足の未準備"
    mean = quantity["直前数量平均"]
    return "直前数量平均が非正または未定義" if mean is None or not math.isfinite(mean) or mean <= 0 else "数量状態が未準備"


def independent_entries(frames: list[dict], higher: list[dict], quantity: dict[int, dict],
                        session: str, period: str) -> tuple[dict, dict, dict]:
    """R1/R2の直式と公開時点から、数量除外前の価格候補と全12入口を再構成する。

    引数: frames/higher (list[dict]) は独立下位/15分足、quantity (dict[int,dict]) は独立量、
    session/period (str) は場と固定期間。
    返り値: tuple[dict,dict,dict] は基準価格候補・数量通過入口・共通準備品質。
    """
    _, _, cutoff, deadline = S.G.times(session)
    history, base, selected, counts = deque(maxlen=6), {}, {}, Counter()
    for frame in frames:
        if not frame["publish"]:
            continue
        if frame["missing"]:
            history.clear()
        available = [u for u in higher if u["end"] <= frame["end"] and
                     (u["confirm"], u["confirm_line"]) <= (frame["confirm"], frame["confirm_line"])]
        upper = available[-1] if available else None
        upper_ready = bool(upper and upper["publish"] and S.finite(upper["close"], upper["ema20"], upper["ema20_previous"]))
        direction = 0
        if upper_ready:
            direction = 1 if upper["close"] > upper["ema20"] > upper["ema20_previous"] else (
                -1 if upper["close"] < upper["ema20"] < upper["ema20_previous"] else 0)
        low = min(h["low"] for h in history) if len(history) == 6 else None
        high = max(h["high"] for h in history) if len(history) == 6 else None
        previous = history[-1] if history else None
        row = {**frame, "上位準備済": upper_ready, "上位方向": direction,
               "上位確認秒": upper["confirm"] if upper else None, "上位確認行": upper["confirm_line"] if upper else None,
               "上位足終了秒": upper["end"] if upper else None, "直前6高値": high, "直前6安値": low,
               "直前足": {k: previous[k] for k in ("index", "close", "ema20", "bb_mean", "bb_sd", "上位準備済",
                         "上位方向", "上位確認秒", "上位確認行")} if previous else None}
        indicators = S.finite(row["ema20"], row["atr"], row["adx"], row["bb_mean"], row["bb_sd"]) and row["atr"] > 0
        common = bool(previous and len(history) == 6 and indicators and upper_ready)
        eligible = common and frame["confirm"] < cutoff and deadline - frame["confirm"] >= 3600
        for name, add in (("公開足", True), ("共通準備可足", common), ("共通時間条件可足", eligible),
                          ("六本窓不足足", len(history) != 6), ("指標未準備足", not indicators), ("上位未準備足", not upper_ready)):
            counts[name] += int(add)
        if eligible and row["adx"] < 20:
            for side in (1, -1):
                if side * (row["close"] - previous["close"]) <= 0 or side * (row["bb_mean"] - row["close"]) <= 0:
                    continue
                r1 = row["low"] < low < row["close"] <= high if side == 1 else row["high"] > high > row["close"] >= low
                r2 = bool(S.finite(previous["bb_mean"], previous["bb_sd"])
                          and side * (previous["close"] - previous["bb_mean"]) < -2 * previous["bb_sd"]
                          and side * (row["close"] - row["bb_mean"]) >= -2 * row["bb_sd"])
                for family, triggered in (("R1", r1), ("R2", r2)):
                    if not triggered:
                        continue
                    size, index = frame["minutes"], frame["index"]
                    base_id = f"{size}分_{family}"
                    identity = f"NK225_{session}_{base_id}_{index:04d}_{side}"
                    q = quantity[index]
                    reason = exclusion(q)
                    record = {"基準価格入口ID": base_id, "基準価格イベントID": identity, "場": session,
                              "期間": period, "時間足分": size, "index": index, "side": side,
                              "要求時計秒": frame["confirm"], "要求原板行": frame["confirm_line"],
                              "数量準備除外理由": reason, **q}
                    if identity in base:
                        raise ValueError("独立基準価格イベントIDが重複")
                    base[identity] = record
                    if reason is not None:
                        continue
                    for extra in ("なし", "RVOL1.2以上"):
                        if extra != "なし" and q["RVOL"] < 1.2:
                            continue
                        source = f"{base_id}_{extra}"
                        event_id = f"NK225_{session}_{source}_{index:04d}_{side}"
                        selected[event_id] = {**row, **q, "場": session, "期間": period,
                            "入口ID": source, "入口系統": family, "補助": extra, "side": side,
                            "イベントID": event_id, "基準価格入口ID": base_id, "基準価格イベントID": identity,
                            "要求時計秒": frame["confirm"], "要求原板行": frame["confirm_line"],
                            "確認遅延秒": frame["confirm"] - frame["end"]}
        history.append(row)
    return base, selected, dict(counts)


# ----------------------------------------
# 旧5分台帳は旧定義で別計算し、新仕様との差を一致扱いへ混ぜずに残す。

def legacy_five(data: dict, start: float, finish: float) -> tuple[dict, dict]:
    """旧5分台帳の共通定義を、累積配列の区間差分から再計算する。

    引数: data (dict) は固定cacheの価格時計選別後の5列、start/finish (float) は場範囲。
    返り値: tuple[dict,dict] はindex別量/完全性/20履歴と、旧台帳形式の集計。
    """
    blocks, _ = quantity_blocks(data, start, finish, 5, legacy=True)
    result, run, longest, ready, previous = {}, 0, 0, 0, None
    for index, info in blocks.items():
        if not info["has_price"]:
            continue
        if previous is not None and index != previous + 1:
            run = 0
        complete = not info["reasons"] and index != 0 and info["accepted"] > 0
        available = complete and run >= 20
        run = run + 1 if complete else 0
        ready += int(available)
        longest = max(longest, run)
        result[index] = {"observed_volume": info["quantity"], "baseline_complete": complete,
                         "preceding_twenty_quantity_bars_available": bool(available)}
        previous = index
    complete_count = sum(r["baseline_complete"] for r in result.values())
    return result, {"price_bars": len(result), "baseline_complete_bars": complete_count,
                    "baseline_incomplete_bars": len(result) - complete_count, "longest_complete_run": longest,
                    "rvol_previous_twenty_available_bars": ready}


def old_comparison(audit: Any, session: str, entry: dict, legacy_detail: dict | None,
                   data: dict, quantities: dict) -> dict:
    """旧保存値を旧定義で照合したうえで、新定義との意味の差を別掲する。

    引数: audit (Any) は比較記録、session (str) は場、entry (dict) は固定台帳、
    legacy_detail (dict|None) は旧詳細台帳、data (dict) は5列、quantities (dict) は新5分Q11。
    返り値: dict は共通部分の比較件数と、新旧の定義差の集約。
    """
    start, finish, _, _ = S.G.times(session)
    legacy, summary = legacy_five(data, start, finish)
    saved = entry.get("volume_audit", {})
    for key, expected in summary.items():
        if key in saved:
            audit.check(f"{session}:旧5分台帳:{key}", saved[key], expected)
    detailed = legacy_detail.get("volume_audit", {}).get("five_minute_bars") if legacy_detail else None
    if detailed is not None:
        actual = {r["index"]: r for r in detailed}
        audit.check(session + ":旧5分全足index", set(actual), set(legacy))
        for index in actual.keys() & legacy.keys():
            for key, expected in legacy[index].items():
                audit.check(f"{session}:旧5分足{index}:{key}", actual[index][key], expected)
    differences, amounts, complete, twenty = [], 0, 0, 0
    for index in quantities.keys() & legacy.keys():
        old, new = legacy[index], quantities[index]
        changed_amount = not math.isclose(old["observed_volume"], new["観測差分量"], rel_tol=0, abs_tol=1e-7)
        changed_complete = old["baseline_complete"] != new["数量基準完全"]
        changed_twenty = old["preceding_twenty_quantity_bars_available"] != (
            new["数量基準完全"] and new["直前数量足数"] == 20)
        amounts += int(changed_amount)
        complete += int(changed_complete)
        twenty += int(changed_twenty)
        if changed_amount or changed_complete or changed_twenty:
            differences.append({"index": index, "旧観測量": old["observed_volume"], "新観測量": new["観測差分量"],
                                "旧基準完全": old["baseline_complete"], "新基準完全": new["数量基準完全"],
                                "新不完全理由": new["数量不完全理由"]})
    return {"場": session, "旧保存集計照合": bool(saved), "旧保存足照合数": len(detailed) if detailed is not None else 0,
            "共通index数": len(quantities.keys() & legacy.keys()), "観測量差足数": amounts,
            "基準完全性差足数": complete, "直前20足利用可差足数": twenty, "差の先頭例": differences[:3],
            "定義差": "新定義は無価格枠の次に累積基準を切り、不正数量/数量時計を当足不完全とし、当足以後の採用数量時計を必須とする。公開不能足を次の履歴に含めない。旧台帳とのこれらの差を監査不一致とはしない。"}


def keyed(rows: list[dict], fields: tuple[str, ...]) -> dict:
    """一意キー別の保存行を作る。

    引数: rows (list[dict]) は行、fields (tuple[str,...]) はキー列。
    返り値: dict はキー別の行。重複は監査継続せず例外にする。
    """
    output = {tuple(row[f] for f in fields): row for row in rows}
    if len(output) != len(rows):
        raise ValueError("保存行の監査キーが重複")
    return output


def run(study: Path, work: Path) -> dict:
    """再生完了後の全65場の数量足・R1/R2価格候補・12入口を独立照合する。

    引数: study/work (Path) は00014の正式/作業先。
    返り値: dict は明示合否・範囲・指紋。旧戦略を再実行せず、原板本文を再読しない。
    """
    required = ("結果.json", "数量品質.json", "入口品質.json", "固定.json")
    if any(not (study / name).exists() for name in required):
        raise ValueError("正式再生の完了資料がそろっていないため監査しません")
    audit = S.Audit()
    config, manifest = read(study / "条件.json"), read(MANIFEST)
    entries = manifest["entries"]
    audit.check("固定入力65場", len(entries), 65)
    audit.check("固定入力NK225のみ", {e["symbol"] for e in entries}, {"NK225"})
    quantity_rows, quantity_sha = compressed_rows(work / "数量足.jsonl.gz")
    price_rows, price_sha = compressed_rows(work / "基準価格入口.jsonl.gz")
    case_rows, cases_sha = compressed_rows(work / "入口事例.jsonl.gz")
    saved_q = keyed(quantity_rows, ("場", "時間足分", "index"))
    saved_base = keyed(price_rows, ("基準価格イベントID",))
    saved_cases = keyed(case_rows, ("イベントID",))
    saved_quality = keyed(read(study / "数量品質.json"), ("場", "時間足分"))
    saved_entry_quality = keyed(read(study / "入口品質.json"), ("場", "時間足分"))
    legacy_entries = {}
    if LEGACY_MANIFEST.exists():
        legacy_entries = {e["session"]: e for e in read(LEGACY_MANIFEST)["entries"] if e["symbol"] == "NK225"}
    expected_q, expected_base, expected_cases, old_results = {}, {}, {}, []
    banks, contract, frame_count, period_count = {n: S.Indicators() for n in (1, 3, 5, 15)}, None, Counter(), Counter()
    for entry in entries:
        session, codes = entry["session"], tuple(entry["in_session_contract_codes"])
        if len(codes) != 1:
            raise ValueError("固定限月が一意でない")
        if contract is not None and contract != codes:
            banks = {n: S.Indicators() for n in banks}
        contract = codes
        period = "後続検査" if session[:10] >= config["分割"]["後続開始日"] else (
            "条件選択" if session[:10] >= config["分割"]["選択開始日"] else "学習")
        period_count[period] += 1
        data = observed(entry, Path(manifest["source_root"]))
        formed = {n: S.bars(data, session, n, bank) for n, bank in banks.items()}
        start, finish, _, _ = S.G.times(session)
        for minutes in (1, 3, 5):
            quantities, quality = independent_quantity(data, formed[minutes], start, finish, minutes)
            frame_count[str(minutes)] += len(formed[minutes])
            for frame in formed[minutes]:
                index = frame["index"]
                expected_q[session, minutes, index] = {"場": session, "期間": period, "時間足分": minutes,
                    **{key: frame[key] for key in ("index", "start", "end", "confirm", "confirm_line", "publish")},
                    **quantities[index]}
            saved = saved_quality.get((session, minutes))
            audit.check(f"{session}:{minutes}分:数量品質の存在", saved is not None, True)
            if saved is not None:
                for key, expected in quality.items():
                    audit.check(f"{session}:{minutes}分:数量品質:{key}", saved.get(key, 0), expected)
            base, selected, common_counts = independent_entries(formed[minutes], formed[15], quantities, session, period)
            expected_base.update({(key,): row for key, row in base.items()})
            expected_cases.update({(key,): row for key, row in selected.items()})
            price_quality = saved_entry_quality.get((session, minutes), {}).get("価格共通準備", {})
            for key, expected in common_counts.items():
                audit.check(f"{session}:{minutes}分:価格共通準備:{key}", price_quality.get(key, 0), expected)
            if minutes == 5:
                old_results.append(old_comparison(audit, session, entry, legacy_entries.get(session), data, quantities))
        frame_count["15"] += len(formed[15])
        print(json.dumps({"場": session, "独立確認": "数量1/3/5・価格1/3/5/15", "現時点不一致数": audit.mismatches}, ensure_ascii=False), flush=True)
    audit.check("固定期間40/24/1", dict(period_count), {"学習": 40, "条件選択": 24, "後続検査": 1})
    audit.check("全数量足集合", set(saved_q), set(expected_q))
    for key in saved_q.keys() & expected_q.keys():
        audit.check(f"数量足{key}", saved_q[key], expected_q[key])
    audit.check("全6基準価格入口イベント集合", set(saved_base), set(expected_base))
    for key in saved_base.keys() & expected_base.keys():
        audit.check(f"基準価格入口{key}", saved_base[key], expected_base[key])
    audit.check("全12数量入口イベント集合", set(saved_cases), set(expected_cases))
    for key in saved_cases.keys() & expected_cases.keys():
        for field in PRICE_FIELDS + QFIELDS:
            audit.check(f"数量入口{key}:{field}", saved_cases[key][field], expected_cases[key][field])
    output = {"全件一致": audit.mismatches == 0, "照合項目数": audit.count, "不一致数": audit.mismatches,
        "不一致": audit.errors, "入力場数": len(entries), "期間場数": dict(period_count), "独立価格足数": dict(frame_count),
        "保存数量足数": len(quantity_rows), "独立数量足数": len(expected_q), "基準価格入口数": len(expected_base),
        "保存12入口数": len(saved_cases), "独立12入口数": len(expected_cases),
        "入口別件数": dict(Counter(row["入口ID"] for row in expected_cases.values())),
        "旧5分台帳比較": old_results,
        "コードSHA256": sha(Path(__file__)), "独立価格補助SHA256": sha(INDEPENDENT),
        "独立Wilder補助SHA256": sha(S.HELPER), "入力台帳SHA256": sha(MANIFEST),
        "旧詳細台帳SHA256": sha(LEGACY_MANIFEST) if LEGACY_MANIFEST.exists() else None,
        "数量足展開SHA256": quantity_sha, "基準価格入口展開SHA256": price_sha, "入口事例展開SHA256": cases_sha,
        "検証範囲": "固定cacheの原順を価格時計区間へ分割し、受入累積の隣接差分を別計算。全1/3/5分数量足Q11・公開時計原行・直前20足RVOL・価格共通助走を照合。原価格から1/3/5/15分OHLC・EMA20/BB20母標準偏差/ATR14/ADX14を独立再構成し、数量除外前の全R1/R2価格候補と数量適用後12入口の全発動集合を照合。旧5分保存値は旧定義で別照合し、新定義の差は別掲。",
        "限界": "00014数量.py/入口.py/検証.py、元の数量監査class・元指標classをimportして再計算しない。以前の独立価格/指標補助だけを再利用する。先着ラベル・会計・運用の確認は親の別監査。原板本文の再取得や真の全約定出来高の証明ではない。固定cacheの価格時計を正確な受信時計としない。"}
    (work / "数量独立確認.json").write_text(json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({k: output[k] for k in ("全件一致", "照合項目数", "不一致数", "保存数量足数", "保存12入口数")}, ensure_ascii=False))
    if audit.errors:
        print(json.dumps(audit.errors[:5], ensure_ascii=False))
    return output


def main() -> None:
    """正式再生完了後の明示指定だけで実データ監査を開始する。

    引数: なし。--study/--work/--実行許可を読む。
    返り値: None。不許可時は実データを開かず終了する。
    """
    parser = argparse.ArgumentParser(description="00014数量と価格入口の独立確認")
    parser.add_argument("--study", type=Path, default=STUDY)
    parser.add_argument("--work", type=Path, default=WORK)
    parser.add_argument("--実行許可", action="store_true")
    args = parser.parse_args()
    if not args.実行許可:
        parser.error("正式再生完了通知後に --実行許可 を指定してください")
    if not run(args.study.resolve(), args.work.resolve())["全件一致"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
