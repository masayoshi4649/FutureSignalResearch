"""00018の原価格P・補助原順参照・共通助走・36発動を独立再構成する。"""

from __future__ import annotations

import argparse
from collections import Counter, deque
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
STUDY = ROOT / "study/00018_VWAPの位置と傾きで順行反転を比較"
WORK = ROOT / "work/VWAP入口/00018"
INPUT = ROOT / "study/00008_外部研究を共通尺度へ移して探索/入力台帳.json"
PRICE_HELPER = ROOT / "scripts/RSI構造/状態独立確認.py"
VALUE_HELPER = ROOT / "scripts/VWAP入力/独立確認.py"
VALUE_MANIFEST = ROOT / "work/VWAP入力/00017/抽出台帳.json"
OLD_CASES = ROOT / "work/テクニカル循環/00011/入口事例.jsonl.gz"


def helper(path: Path, name: str) -> Any:
    """以前の独立価格/数式補助だけを読み込む。

    引数: path (Path) は独立補助、name (str) は識別名。
    返り値: Any は補助。新18参照/入口/driverや元価格指標classは読み込まない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


S = helper(PRICE_HELPER, "VWAP入口の独立価格構造")
V = helper(VALUE_HELPER, "VWAP入口の独立累積区間")


def price_signals(frames: list[dict], higher: list[dict], session: str, period: str) -> dict[str, dict]:
    """旧11の共通準備とT1/R2を、独立価格足から直式で求める。

    引数: frames/higher (list[dict]) は独立の下位/15分足、session/period (str) は場/期間。
    返り値: dict[str,dict] は価格Pイベント。遅延30秒超も旧Pどおり残し、補助マスクで後に判定する。
    """
    _, _, cutoff, deadline = S.S.G.times(session)
    history, output = deque(maxlen=6), {}
    for frame in frames:
        if not frame["publish"]:
            continue
        if frame["missing"]:
            history.clear()
        upper = S.upper_context(frame, higher)
        previous = history[-1] if history else None
        row = {**frame, **{k: upper[k] for k in ("上位準備済", "上位方向", "上位確認秒", "上位確認行", "上位足終了秒")},
            "直前6高値": max(h["high"] for h in history) if len(history) == 6 else None,
            "直前6安値": min(h["low"] for h in history) if len(history) == 6 else None,
            "直前足": {k: previous[k] for k in ("index", "close", "ema20", "bb_mean", "bb_sd",
                "上位準備済", "上位方向", "上位確認秒", "上位確認行")} if previous is not None else None}
        ready = S.S.finite(row["ema20"], row["atr"], row["adx"], row["bb_mean"], row["bb_sd"]) and row["atr"] > 0
        eligible = previous is not None and len(history) == 6 and ready and upper["上位準備済"]
        eligible = eligible and frame["confirm"] < cutoff and deadline - frame["confirm"] >= 3600
        if eligible:
            for side in (1, -1):
                improved = side * (row["close"] - previous["close"]) > 0
                t1 = bool(improved and previous["上位準備済"] and previous["上位方向"] == side == row["上位方向"]
                    and S.S.finite(previous["ema20"]) and side * (previous["close"] - previous["ema20"]) <= 0
                    and side * (row["close"] - row["ema20"]) > 0 and side * (row["ema20"] - previous["ema20"]) > 0)
                r2 = bool(improved and row["adx"] < 20 and side * (row["bb_mean"] - row["close"]) > 0
                    and S.S.finite(previous["bb_mean"], previous["bb_sd"])
                    and side * (previous["close"] - previous["bb_mean"]) < -2 * previous["bb_sd"]
                    and side * (row["close"] - row["bb_mean"]) >= -2 * row["bb_sd"])
                for family, active in (("T1", t1), ("R2", r2)):
                    if not active:
                        continue
                    size, index = frame["minutes"], frame["index"]
                    source = f"{size}分_{family}"
                    identity = f"NK225_{session}_{source}_{index:04d}_{side}"
                    output[identity] = {**row, "場": session, "期間": period, "時間足分": size, "入口ID": source,
                        "入口系統": family, "side": side, "方向": "買い" if side == 1 else "売り", "イベントID": identity,
                        "要求時計秒": frame["confirm"], "要求原板行": frame["confirm_line"],
                        "確認遅延秒": frame["confirm"] - frame["end"], "期限時計秒": deadline,
                        "足終了時計秒": frame["end"], "残り分_判断時": (deadline - frame["confirm"]) / 60,
                        "入口中心まで方向距離pt": side * (row["bb_mean"] - row["close"]),
                        "250ptのATR倍": 250 / row["atr"], "再テスト登録": None}
        history.append(row)
    return output


# ----------------------------------------
# 補助全列を先に採用累積epochへ区分し、各原行までの不変基準番号を配列で求める。

def auxiliary_states(columns: dict, session: str, metadata: dict) -> dict:
    """補助NPZから原順最大時計・累積epoch・その時点までの既知baseを独立に作る。

    引数: columns (dict) は00017小列、session (str) は場、metadata (dict) は対応表。
    返り値: dict は原行位置別の時計採否・比率・epoch・基準。主Online classは呼ばない。
    """
    start, finish, floor = V.bounds(session)
    V.basic(columns, metadata["contract_codes"], start, finish)
    now, volume, quantity_clock, value, native = (columns[k] for k in ("now", "volume", "volume_time", "trading_value", "native_vwap"))
    positions = np.flatnonzero(np.isfinite(now))
    accepted_clock = np.zeros(len(now), dtype=bool)
    if len(positions):
        values = now[positions]
        accepted_clock[positions[np.r_[True, values[1:] >= np.maximum.accumulate(values[:-1])]]] = True
    maximum_at = np.maximum.accumulate(np.where(accepted_clock, np.arange(len(now)), -1))
    cumulative = (accepted_clock & np.isfinite(quantity_clock) & (quantity_clock <= now)
                  & np.isfinite(volume) & (volume >= 0) & np.isfinite(value) & (value >= 0))
    accepted = np.flatnonzero(cumulative)
    changed = np.zeros(len(now), dtype=bool)
    if len(accepted):
        for field in ("volume", "trading_value", "volume_time"):
            decrease = columns[field][accepted[1:]] < columns[field][accepted[:-1]]
            changed[accepted[1:][decrease]] = True
        for field in ("contract", "exchange", "opening_time", "opening_price"):
            values = columns[field][accepted]
            present = values >= 0 if field in ("contract", "exchange") else np.isfinite(values) & (values > 0)
            known = np.flatnonzero(present)
            differing = known[1:][values[known[1:]] != values[known[:-1]]]
            changed[accepted[differing]] = True
    epoch = np.cumsum(changed, dtype=np.int64)
    identity_known = (columns["contract"] >= 0) & (columns["exchange"] >= 0)
    for field in ("opening_time", "opening_price"):
        identity_known &= np.isfinite(columns[field]) & (columns[field] > 0)
    known_now = identity_known & (columns["opening_time"] <= now)
    paired = np.isfinite(volume) & (volume > 0) & np.isfinite(value) & (value >= 0) & np.isfinite(native) & (native > 0)
    error = np.full(len(now), np.nan)
    with np.errstate(over="ignore", divide="ignore", invalid="ignore"):
        error[paired] = np.abs(native[paired] - value[paired] / volume[paired] / 1000)
    consistent = paired & np.isfinite(error) & (error <= .00010001)
    prefix_candidate = (cumulative & known_now & (floor <= now) & (now < start)
        & (floor <= quantity_clock) & (quantity_clock < start)
        & (consistent | ((volume == 0) & (value == 0))))
    zero_candidate = cumulative & known_now & (now == start) & (quantity_clock <= start) & (volume == 0) & (value == 0)
    candidates = np.flatnonzero(prefix_candidate | zero_candidate)
    base = np.full(len(now), -1, dtype=np.int64)
    if len(candidates):
        for identifier in np.unique(epoch):
            group = np.flatnonzero(epoch == identifier)
            available = candidates[epoch[candidates] == identifier]
            if not len(available):
                continue
            prior = np.searchsorted(available, group, side="right") - 1
            keep = prior >= 0
            base[group[keep]] = available[prior[keep]]
    apply_reason = []
    for i in range(len(now)):
        reasons = []
        if not math.isfinite(now[i]):
            reasons.append("価格時計欠測")
        elif not accepted_clock[i]:
            reasons.append("価格時計原行後退")
        elif not math.isfinite(quantity_clock[i]) or quantity_clock[i] > now[i]:
            reasons.append("数量時計欠測または先行")
        elif not math.isfinite(volume[i]) or not math.isfinite(value[i]) or min(volume[i], value[i]) < 0:
            reasons.append("累積数量代金不正")
        apply_reason.append(reasons)
    return {"epoch": epoch, "base": base, "changed": changed, "accepted_clock": accepted_clock,
            "consistent": consistent, "error": error, "identity_known": identity_known,
            "apply_reason": apply_reason, "maximum_at": maximum_at}


def identity(columns: dict, at: int, metadata: dict) -> dict:
    """補助番号を限月/市場の原値へ解決する。

    引数: columns (dict) は小列、at (int) は位置、metadata (dict) は対応表。
    返り値: dict は既知識別属性と欠測None。
    """
    contract, market = int(columns["contract"][at]), int(columns["exchange"][at])
    return {"限月": metadata["contract_codes"][contract] if contract >= 0 else None,
            "市場": metadata["exchange_values"][market] if market >= 0 else None,
            "始値時計": float(columns["opening_time"][at]) if np.isfinite(columns["opening_time"][at]) and columns["opening_time"][at] > 0 else None,
            "始値価格": float(columns["opening_price"][at]) if np.isfinite(columns["opening_price"][at]) and columns["opening_price"][at] > 0 else None}


def point_reference(columns: dict, states: dict, at: int, key: tuple, session: str,
                    metadata: dict) -> dict:
    """最新物理行だけを公開上限で検査し、過去の正常値へfallbackせず参照を作る。

    引数: columns/states (dict) は小列/独立状態、at (int) は最新原行位置、key (tuple) は公開キー、
    session (str) は場、metadata (dict) は対応表。
    返り値: dict は現在native/差分・基準・不可理由。
    """
    if at < 0:
        return {"配信VWAP": None, "当場差分VWAP": None, "補助epoch": 0, "identity": None,
                "native有効": False, "差分有効": False, "補助参照": None, "現在不可理由": ["参照原行なし"]}
    start, finish, _ = V.bounds(session)
    e, current_identity = V.snapshot(columns, at), identity(columns, at, metadata)
    now, quantity_clock = columns["now"][at], columns["volume_time"][at]
    reasons = list(states["apply_reason"][at])
    if not math.isfinite(now) or not start <= now < finish:
        reasons.append("価格時計場外または不明")
    if not math.isfinite(now) or (now, int(columns["line"][at])) > key or columns["line"][at] > key[1]:
        reasons.append("公開上限外")
    if not math.isfinite(quantity_clock) or not start <= quantity_clock <= now:
        reasons.append("数量時計場外先行または不明")
    if not math.isfinite(columns["last"][at]) or columns["last"][at] <= 0:
        reasons.append("Last非正または不明")
    if not states["consistent"][at]:
        reasons.append("配信内部比率不整合または未定義")
    if any(v is None for v in current_identity.values()) or not math.isfinite(columns["opening_time"][at]) or columns["opening_time"][at] > now:
        reasons.append("identity未確認")
    native_ok, base_at = not reasons, int(states["base"][at])
    delta_q, delta_t, differential = None, None, None
    if base_at >= 0 and native_ok and current_identity == identity(columns, base_at, metadata):
        delta_q = float(columns["volume"][at] - columns["volume"][base_at])
        delta_t = float(columns["trading_value"][at] - columns["trading_value"][base_at])
        if delta_q > 0 and delta_t > 0:
            differential = delta_t / delta_q / 1000
    d_ok = native_ok and differential is not None and math.isfinite(differential) and differential > 0
    reference = {**e, "内部比率整合": bool(states["consistent"][at]),
        "内部絶対差pt": float(states["error"][at]) if np.isfinite(states["error"][at]) else None,
        "最大既知キー": [float(columns["now"][states["maximum_at"][at]]), int(columns["line"][states["maximum_at"][at]])] if states["maximum_at"][at] >= 0 else None,
        "基準": V.snapshot(columns, base_at) if base_at >= 0 else None, "差分数量": delta_q, "差分代金": delta_t,
        "現在不可理由": sorted(set(reasons))}
    return {"配信VWAP": e["native_vwap"] if native_ok else None, "当場差分VWAP": differential if d_ok else None,
            "補助epoch": int(states["epoch"][at]), "identity": current_identity,
            "native有効": native_ok, "差分有効": bool(d_ok), "補助参照": reference, "現在不可理由": sorted(set(reasons))}


# ----------------------------------------
# 公開足ごとの最新物理行を先に求め、同場の有効連続区間から四点だけを選ぶ。

def foot_references(columns: dict, states: dict, frames: list[dict], session: str,
                    metadata: dict) -> tuple[dict[int, dict], dict]:
    """全価格足のas-of参照と同epoch四点マスクを独立に作る。

    引数: columns/states (dict) は小列/独立状態、frames (list[dict]) は独立価格足、
    session (str) は場、metadata (dict) は対応表。
    返り値: tuple[dict[int,dict],dict] は全足属性と参照品質。不可足は助走へ数えない。
    """
    points, processed = [], -1
    for frame in frames:
        if not frame["publish"]:
            row = {"配信VWAP": None, "当場差分VWAP": None,
                "補助epoch": int(states["epoch"][processed]) if processed >= 0 else 0,
                "identity": None, "native有効": False, "差分有効": False, "補助参照": None,
                "現在不可理由": ["非公開価格足"]}
        else:
            processed = max(processed, int(np.searchsorted(columns["line"], frame["confirm_line"], side="right")) - 1)
            row = point_reference(columns, states, processed, (frame["confirm"], frame["confirm_line"]), session, metadata)
            if frame["confirm"] - frame["end"] > 30:
                row["native有効"] = row["差分有効"] = False
                row["現在不可理由"] = row["現在不可理由"] + ["価格足確認遅延30秒超"]
        points.append(row)
    result, runs, counter = {}, [], Counter()
    for at, (frame, row) in enumerate(zip(frames, points)):
        separate = not row["native有効"] or frame["missing"] or not frame["publish"] or frame["confirm"] - frame["end"] > 30
        if at:
            separate = separate or frame["index"] != frames[at - 1]["index"] + 1 or row["補助epoch"] != points[at - 1]["補助epoch"]
        if separate:
            runs = []
        if row["native有効"]:
            runs.append(at)
        window = [points[i] for i in runs[-4:]]
        n_ready = len(window) == 4
        bases = {p["補助参照"]["基準"]["line"] for p in window if p["補助参照"] is not None and p["補助参照"]["基準"] is not None}
        d_all = all(p["差分有効"] for p in window)
        d_ready = n_ready and d_all and len(bases) == 1
        n_reasons = [] if n_ready else row["現在不可理由"] + (["同場四点未準備"] if len(window) < 4 else ["四点nativeまたはepoch不成立"])
        d_reasons = [] if d_ready else n_reasons + ([] if d_all else ["四点差分基準または正増分未準備"]) + ([] if len(bases) == 1 else ["四点差分基準不一致"])
        attrs = {k: row[k] for k in ("配信VWAP", "当場差分VWAP", "補助epoch", "identity", "native有効", "差分有効", "補助参照")}
        attrs.update({"配信3足前VWAP": window[0]["配信VWAP"] if n_ready else None,
            "差分3足前VWAP": window[0]["当場差分VWAP"] if d_ready else None,
            "N共通準備": bool(n_ready), "D共通準備": bool(d_ready),
            "N除外理由": sorted(set(n_reasons)), "D除外理由": sorted(set(d_reasons))})
        result[frame["index"]] = attrs
        for name, active in (("価格足数", True), ("公開足数", frame["publish"]),
            ("native有効足数", row["native有効"]), ("差分有効足数", row["差分有効"]),
            ("N共通準備足数", n_ready), ("D共通準備足数", d_ready)):
            counter[name] += int(active)
    if processed >= 0:
        counter["参照まで処理した状態数"] = processed + 1
        counter["後退除外状態数"] = int(np.count_nonzero(np.isfinite(columns["now"][:processed + 1]) & ~states["accepted_clock"][:processed + 1]))
        counter["累積区間変更数"] = int(np.count_nonzero(states["changed"][:processed + 1]))
    return result, dict(counter)


def apply_conditions(prices: dict[str, dict], references: dict[int, dict], session: str,
                     period: str) -> tuple[dict[str, dict], dict[str, dict], dict]:
    """独立価格Pへ六固定設定を適用し、包含関係と全発動を作る。

    引数: prices (dict[str,dict]) は独立P、references (dict[int,dict]) は全足参照、session/period (str) は場/期間。
    返り値: tuple[dict,dict,dict] は価格発動記録/36発動/発動品質。損益を条件選択へ使わない。
    """
    records, events, counts = {}, {}, Counter()
    for identity_key, price in prices.items():
        ref, side, close = references[price["index"]], price["side"], price["close"]
        role = "順行" if price["入口系統"] == "T1" else "反転"
        native, differential = ref["配信VWAP"], ref["当場差分VWAP"]
        native_position = bool(native is not None and side * ((close - native) if role == "順行" else (native - close)) > 0)
        delta_position = bool(differential is not None and side * ((close - differential) if role == "順行" else (differential - close)) > 0)
        slope = bool(native is not None and ref["配信3足前VWAP"] is not None and side * (native - ref["配信3足前VWAP"]) > 0)
        passed = {"N_A": ref["N共通準備"], "N_B": ref["N共通準備"] and native_position,
            "N_C": ref["N共通準備"] and native_position and slope,
            "D_A": ref["D共通準備"], "D_B": ref["D共通準備"] and native_position,
            "D_D": ref["D共通準備"] and delta_position}
        fired = []
        for setting, allowed in passed.items():
            if not allowed:
                continue
            source = f'{price["時間足分"]}分_{price["入口系統"]}_{setting}'
            event_id = f'NK225_{session}_{source}_{price["index"]:04d}_{side}'
            events[event_id] = {**price, **ref, "価格入口ID": price["入口ID"], "価格イベントID": identity_key,
                "入口ID": source, "補助": setting, "役割": role, "イベントID": event_id}
            fired.append(source)
        records[identity_key] = {"場": session, "期間": period, "時間足分": price["時間足分"], "価格入口ID": price["入口ID"],
            "価格イベントID": identity_key, "元価格信号": price, **ref,
            "native位置成立": native_position, "差分位置成立": delta_position, "native傾き成立": slope,
            "通過設定": passed, "発動入口ID": fired}
        counts["価格発動数"] += 1
        counts["N共通準備通過価格発動数"] += int(ref["N共通準備"])
        counts["D共通準備通過価格発動数"] += int(ref["D共通準備"])
    return records, events, dict(counts)


# ----------------------------------------
# 保存全足/価格P/全36発動を照合し、旧3/5分Pは固定11元信号全文とも比較する。

def run(study: Path, work: Path) -> dict:
    """正式再生後の全65場を独立再構成し、全段階の集合と属性を検査する。

    引数: study/work (Path) は00018の正式/作業先。
    返り値: dict は明示合否・件数・固定指紋。運用・先着・会計は親の別監査。
    """
    for name in ("結果.json", "固定.json", "入口品質.json", "参照品質.json"):
        if not (study / name).exists():
            raise ValueError("正式再生完了資料がないため実行しません")
    audit = V.Audit()
    manifest, config = V.read(INPUT), V.read(study / "条件.json")
    auxiliary_manifest = V.read(VALUE_MANIFEST)
    auxiliaries = {r["session"]: r for r in auxiliary_manifest["entries"]}
    reference_rows, reference_sha = S.compressed_rows(work / "全足参照.jsonl.gz")
    price_rows, prices_sha = S.compressed_rows(work / "価格発動.jsonl.gz")
    case_rows, cases_sha = S.compressed_rows(work / "入口事例.jsonl.gz")
    saved_ref = {(r["場"], r["時間足分"], r["index"]): r for r in reference_rows}
    saved_price = {r["価格イベントID"]: r for r in price_rows}
    saved_cases = {r["イベントID"]: r for r in case_rows}
    for name, mapping, rows in (("全足参照", saved_ref, reference_rows), ("全価格P", saved_price, price_rows), ("全36入口", saved_cases, case_rows)):
        audit.check(name + "のキー一意", len(mapping), len(rows))
    quality = {(r["場"], r["時間足分"]): r for r in V.read(study / "参照品質.json")}
    price_quality = {(r["場"], r["時間足分"]): r for r in V.read(study / "入口品質.json")}
    expected_ref, expected_price, expected_cases = {}, {}, {}
    banks, contract, foot_count, phases = {n: S.Indicators() for n in (1, 3, 5, 15)}, None, Counter(), Counter()
    for entry in manifest["entries"]:
        session, codes = entry["session"], tuple(entry["in_session_contract_codes"])
        if len(codes) != 1:
            raise ValueError("価格限月が一意でない")
        if contract is not None and contract != codes:
            banks = {n: S.Indicators() for n in banks}
        contract = codes
        period = "後続検査" if session[:10] >= config["分割"]["後続開始日"] else (
            "条件選択" if session[:10] >= config["分割"]["選択開始日"] else "学習")
        phases[period] += 1
        data = S.S.observed(entry)
        formed = {n: S.S.bars(data, session, n, bank) for n, bank in banks.items()}
        aux = auxiliaries[session]
        for field in ("source_path", "sha256_uncompressed", "source_size", "source_mtime_ns"):
            audit.check(session + ":価格/補助同一出典:" + field, aux[field], entry[field])
        path = ROOT / aux["cache_path"]
        audit.check(session + ":補助cacheSHA", V.sha(path), aux["sha256_cache"])
        with np.load(path, allow_pickle=False) as archive:
            columns = {k: archive[k] for k in archive.files}
        states = auxiliary_states(columns, session, aux)
        for minutes in (1, 3, 5):
            refs, ref_quality = foot_references(columns, states, formed[minutes], session, aux)
            for frame in formed[minutes]:
                expected_ref[session, minutes, frame["index"]] = {"場": session, "期間": period, "時間足分": minutes,
                    **{k: frame[k] for k in ("index", "start", "end", "confirm", "confirm_line", "publish", "missing")},
                    **refs[frame["index"]]}
            prices = price_signals(formed[minutes], formed[15], session, period)
            records, events, counts = apply_conditions(prices, refs, session, period)
            expected_price.update(records)
            expected_cases.update(events)
            actual = quality.get((session, minutes), {})
            for field, value in ref_quality.items():
                audit.check(f"{session}:{minutes}分:参照品質:{field}", actual.get(field, 0), value)
            actual_price_quality = price_quality.get((session, minutes), {})
            for field, value in counts.items():
                audit.check(f"{session}:{minutes}分:価格通過品質:{field}", actual_price_quality.get(field, 0), value)
            for family in ("T1", "R2"):
                for setting in ("N_A", "N_B", "N_C", "D_A", "D_B", "D_D"):
                    source = f"{minutes}分_{family}_{setting}"
                    audit.check(f"{session}:{source}:発動数", actual_price_quality["系統別発動数"][source],
                                sum(r["入口ID"] == source for r in events.values()))
            foot_count[str(minutes)] += len(formed[minutes])
        foot_count["15"] += len(formed[15])
        print(json.dumps({"場": session, "独立確認": "原価格P・小列原順epoch・全足/36入口", "現時点不一致数": audit.mismatches}, ensure_ascii=False), flush=True)
    audit.check("全65場", len(manifest["entries"]), 65)
    audit.check("固定40/24/1", dict(phases), {"学習": 40, "条件選択": 24, "後続検査": 1})
    for name, actual, expected in (("全足参照", saved_ref, expected_ref), ("全価格P", saved_price, expected_price), ("全36入口", saved_cases, expected_cases)):
        S.compare_keys(audit, name, set(actual), set(expected))
    for key in saved_ref.keys() & expected_ref.keys():
        audit.check(f"全足{key}", saved_ref[key], expected_ref[key])
    price_fields = ("index", "start", "end", "minutes", "open", "high", "low", "close", "missing", "publish",
        "confirm", "confirm_line", "ema20", "ema20_previous", "atr", "rsi", "adx", "bb_mean", "bb_sd", "plus_di", "minus_di",
        "上位準備済", "上位方向", "上位確認秒", "上位確認行", "上位足終了秒", "直前6高値", "直前6安値", "直前足",
        "場", "時間足分", "入口ID", "入口系統", "side", "方向", "要求時計秒", "要求原板行", "確認遅延秒",
        "期限時計秒", "足終了時計秒", "残り分_判断時", "入口中心まで方向距離pt", "250ptのATR倍", "再テスト登録")
    for key in saved_price.keys() & expected_price.keys():
        actual, expected = saved_price[key], expected_price[key]
        audit.check(key + ":価格発動/六条件", {k: v for k, v in actual.items() if k != "元価格信号"},
                    {k: v for k, v in expected.items() if k != "元価格信号"})
        for field in price_fields:
            audit.check(key + ":独立価格P:" + field, actual["元価格信号"][field], expected["元価格信号"][field])
    original_rows, old_sha = S.compressed_rows(OLD_CASES)
    old = {r["イベントID"]: r for r in original_rows if r["時間足分"] in (3, 5) and r["入口系統"] in ("T1", "R2")}
    current = {k: v for k, v in saved_price.items() if v["時間足分"] in (3, 5)}
    S.compare_keys(audit, "固定11の3/5分P集合", set(current), set(old))
    added_after_generation = {"期間", "要求時計JST", "ラベル", "理由", "新規価格", "新規時計秒", "新規原板行",
        "判定時計秒", "判定原板行", "判定気配", "最大順行pt", "最大逆行pt", "所要分"}
    for key in current.keys() & old.keys():
        audit.check(key + ":旧11固定P全文", current[key]["元価格信号"],
                    {k: v for k, v in old[key].items() if k not in added_after_generation})
    reference_fields = ("配信VWAP", "当場差分VWAP", "配信3足前VWAP", "差分3足前VWAP", "補助epoch", "identity",
        "native有効", "差分有効", "N共通準備", "D共通準備", "補助参照", "N除外理由", "D除外理由")
    for key in saved_cases.keys() & expected_cases.keys():
        for field in price_fields + reference_fields + ("価格入口ID", "価格イベントID", "補助", "役割", "期間"):
            audit.check(key + ":" + field, saved_cases[key][field], expected_cases[key][field])
    aux_input = ROOT / "study/00017_配信元VWAPと売買代金の入力監査/結果.json"
    output = {"全件一致": audit.mismatches == 0, "照合項目数": audit.count, "不一致数": audit.mismatches, "不一致": audit.errors,
        "入力場数": len(manifest["entries"]), "期間場数": dict(phases), "独立足数": dict(foot_count),
        "保存参照足数": len(reference_rows), "独立参照足数": len(expected_ref),
        "保存価格発動数": len(price_rows), "独立価格発動数": len(expected_price),
        "旧11同値比較価格数": len(old), "保存入口数": len(case_rows), "独立入口数": len(expected_cases),
        "入口別件数": dict(Counter(r["入口ID"] for r in expected_cases.values())),
        "コードSHA256": V.sha(Path(__file__)), "入力台帳SHA256": V.sha(INPUT),
        "補助入力台帳SHA256": V.sha(aux_input), "補助作業台帳SHA256": V.sha(VALUE_MANIFEST),
        "全足参照展開SHA256": reference_sha, "価格発動展開SHA256": prices_sha, "入口事例展開SHA256": cases_sha,
        "旧11入口事例展開SHA256": old_sha, "独立価格補助SHA256": V.sha(PRICE_HELPER), "独立数量補助SHA256": V.sha(VALUE_HELPER),
        "検証範囲": "旧価格cacheの全65場から独立1/3/5/15足・指標でT1/R2全Pを再構成し、3/5分Pは固定11元信号全文とも比較。00017小列を原順最大時計と採用累積epochへ先分割し、当時までの整合prefix/直接零のbase番号を対応。全価格足の公開原行as-of最新rawと上限/不可理由・参照/base/epoch、同場4連続有効点のN/D/同base、6設定のstrict位置/傾き・36全集合を別計算して照合。価格時計欠測/後退latestに古正常fallbackをせず、遅延/不可/非公開/欠枠/epoch変更では助走を取り直す。",
        "限界": "18主参照/入口/driverや元指標classをimportして自身を再実行しない。過去の独立価格/RSI/Wilderと小列数式補助だけを再利用。原板全行の別再抽出ではなく、17固定補助NPZを入力とする。VWAP/代金固有時計・実受信時計の欠如と未観測resetの限界を引き継ぐ。先着/実建玉抑止/約定/運用会計/Viewerは別監査。"}
    (work / "状態独立確認.json").write_text(json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({k: output[k] for k in ("全件一致", "照合項目数", "不一致数", "保存参照足数", "保存価格発動数", "保存入口数")}, ensure_ascii=False))
    if audit.errors:
        print(json.dumps(audit.errors[:5], ensure_ascii=False))
    return output


def main() -> None:
    """正式再生完了通知後だけ実データ監査を開始する。

    引数: なし。--study/--work/--実行許可を読む。
    返り値: None。許可前は実データを開かない。
    """
    parser = argparse.ArgumentParser(description="00018原価格P・VWAP参照・36発動の独立再構成")
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

