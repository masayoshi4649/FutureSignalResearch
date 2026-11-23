"""00030の原価格・絶対BB幅・上昇下落回数と入口を独立に再構成する。"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from copy import deepcopy
from fractions import Fraction
import importlib.util
import json
import math
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT / "study/00030_価格突破とBB幅と方向頻度"
WORK = ROOT / "work/PSY突破/00030"
POLICIES = ("P0", "P1")
EXACT_FIELDS = ("BB幅比較厳密符号", "BB分散差厳密分子", "BB分散差厳密分母")


def helper(path: Path, name: str) -> Any:
    """固定済みの独立足・ATR・照合補助だけを読み込む。

    引数: path (Path) は独立補助、name (str) はモジュール識別。
    返り値: Any は補助。30主指標/入口/運用はimportしない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


B = helper(ROOT / "scripts/一目基準線/状態独立確認.py", "PSY突破の固定独立足と比較")
S, V, P, SOURCE_FIELDS = B.S, B.V, B.P, B.SOURCE_FIELDS
Audit = B.Audit


def observed(entry: dict, manifest: dict) -> dict:
    """固定8列cacheから原順の場内非後退観測を抽出する。

    引数: entry/manifest (dict) は固定入力行/実台帳。
    返り値: dict は原8列。採否へ使うのは価格と時点だけで、数量条件は計算しない。
    """
    source = Path(manifest["source_root"]) / entry["source_path"]
    stat = source.stat()
    if (stat.st_size, stat.st_mtime_ns) != (entry["source_size"], entry["source_mtime_ns"]):
        raise ValueError("固定原板statが変更")
    cache = (ROOT / "work/複合検証" / entry["cache_path"]).resolve()
    if not cache.is_relative_to((ROOT / "work").resolve()) or V.sha(cache) != entry["sha256_cache"] or cache.stat().st_size != entry["cache_size"]:
        raise ValueError("固定cacheの参照範囲/指紋が変更")
    with S.np.load(cache, allow_pickle=False) as archive:
        data = {key: archive[key] for key in ("now", "line", "last", "bid", "ask", "valid", "volume", "volume_time")}
    start, finish, _, _ = S.G.times(entry["session"])
    indices = S.np.flatnonzero(S.np.isfinite(data["now"]) & (start <= data["now"]) & (data["now"] <= finish))
    times = data["now"][indices]
    if len(times):
        indices = indices[S.np.r_[True, times[1:] >= S.np.maximum.accumulate(times[:-1])]]
    return {key: values[indices] for key, values in data.items()}


def psy12(frames: list[dict]) -> dict | None:
    """当時までの末尾13終値から12比較の上昇/下落/同値を直接数える。

    引数: frames (list[dict]) は当場の公開連続有効足。
    返り値: dict|None はU/D/F・整数差・上下率・出典番号。12比較不足はNone。
    """
    if len(frames) < 13:
        return None
    chosen = frames[-13:]
    differences = [current["close"] - previous["close"] for previous, current in zip(chosen[:-1], chosen[1:])]
    up = sum(value > 0 for value in differences)
    down = sum(value < 0 for value in differences)
    flat = sum(value == 0 for value in differences)
    return {"上昇数": up, "下落数": down, "同値数": flat, "方向差整数": up - down,
        "上昇率": 100 * up / 12, "下落率": 100 * down / 12, "足番号": [row["index"] for row in chosen]}


def bb20(frames: list[dict]) -> dict:
    """現在指定された20終値だけから母標準偏差と絶対幅を直接計算する。

    引数: frames (list[dict]) は価格窓。現在/前窓の選択は呼出側で行う。
    返り値: dict は平均/標準偏差/幅。幅は価格で割らない4σ。
    """
    if len(frames) != 20:
        return {"平均": None, "標準偏差": None, "幅": None}
    mean = sum(row["close"] for row in frames) / 20
    sd = math.sqrt(sum((row["close"] - mean) ** 2 for row in frames) / 20)
    return {"平均": mean, "標準偏差": sd, "幅": 4 * sd}


def variance20(frames: list[dict]) -> Fraction | None:
    """原終値の分数平均から偏差二乗和を作り、母分散を正確に求める。

    引数: frames (list[dict]) は指定した20本の原足。
    返り値: Fraction|None は分散。主の二乗平均差式を再利用しない。
    """
    if len(frames) != 20:
        return None
    closes = [Fraction(row["close"]) for row in frames]
    mean = sum(closes) / 20
    return sum((value - mean) ** 2 for value in closes) / 20


def exact_width_change(previous: list[dict], current: list[dict]) -> tuple[int | None, int | None, int | None]:
    """同じ本数の母分散差から絶対4σ幅の増減符号と既約差を求める。

    引数: previous/current (list[dict]) は旧20/現20窓。
    返り値: tuple[int|None,int|None,int|None] は符号/分散差分子/分母。幅差の分数ではない。
    """
    before, after = variance20(previous), variance20(current)
    if before is None or after is None:
        return None, None, None
    change = after - before
    return int(change > 0) - int(change < 0), change.numerator, change.denominator


class NumericHistory:
    """ATRの価格銀行と、毎場の公開13/14終値履歴を分けて保持する。"""

    def __init__(self) -> None:
        """限月を未確定とし数値銀行を空にする。

        引数: なし。
        返り値: None。
        """
        self.contract = None
        self.clear()

    def clear(self) -> None:
        """ATRの独立数値系列だけを初期化する。

        引数: なし。
        返り値: None。PSYの履歴は場内buildの区間配列で管理する。
        """
        self.absolute = P.Indicators()

    def build(self, frames: list[dict], session: str, contract: tuple, tail_missing: int = 0) -> tuple[list[dict], dict]:
        """原足の切断と当場公開制約を別判定してATR/PSYを生成する。

        引数: frames (list[dict]) は完全幅3分OHLC、session (str) は当場、contract (tuple) は限月、
        tail_missing (int) は完全尾部欠枠。
        返り値: tuple[list[dict],dict] は全数値足と品質。NP/missing当足はPSYに投入しない。
        """
        changed = self.contract is not None and self.contract != contract
        if changed:
            self.clear()
        self.contract = contract
        output, local, previous_index, previous_key = [], [], None, None
        numeric_clears, psy_clears = int(changed), 0
        for frame in frames:
            index, key = frame["index"], (frame["confirm"], frame["confirm_line"])
            if frame["minutes"] != 3 or previous_index is not None and index <= previous_index:
                raise ValueError("独立原足の尺度/番号順が不正")
            if frame["publish"] and (frame["confirm"] < frame["end"] or previous_key is not None and key < previous_key):
                raise ValueError("独立原足の公開時刻/順が不正")
            reasons = ["限月変更"] if changed and previous_index is None else []
            if index != (0 if previous_index is None else previous_index + 1):
                reasons.append("足番号欠枠")
            if frame["missing"]:
                reasons.append("欠枠")
            numeric = B.valid_ohlc(frame)
            if not numeric:
                reasons.append("OHLC不正")
            if any(reason != "限月変更" for reason in reasons):
                self.clear()
                numeric_clears += 1
            atr = self.absolute.add(frame)["atr"] if numeric else None
            psy_reasons = list(reasons)
            if not frame["publish"]:
                psy_reasons.append("非公開足")
            if psy_reasons:
                local = []
                psy_clears += 1
            if numeric and frame["publish"] and not frame["missing"]:
                local.append(frame)
            current = psy12(local)
            previous = psy12(local[:-1])
            output.append({"場": session, **B.source(frame), "atr": atr, "価格数値入力可": numeric,
                "PSY現": current, "PSY前": previous, "PSY準備済": current is not None and previous is not None,
                "銀行解除理由": reasons, "PSY解除理由": psy_reasons})
            previous_index = index
            if frame["publish"]:
                previous_key = key
        if tail_missing:
            self.clear()
            numeric_clears += 1
        return output, {"場": session, "時間足分": 3, "入力足数": len(output),
            "価格数値入力足数": sum(row["価格数値入力可"] for row in output),
            "ATR正準備足数": sum(B.finite(row["atr"]) and row["atr"] > 0 for row in output),
            "PSY現在準備足数": sum(row["PSY現"] is not None for row in output),
            "PSY現前準備足数": sum(row["PSY準備済"] for row in output),
            "数値clear数": numeric_clears, "PSYclear数": psy_clears, "尾部完全欠枠": tail_missing,
            "非公開価格数値更新数": sum(not row["publish"] and row["価格数値入力可"] for row in output)}


def reference(row: dict | None) -> dict | None:
    """前足の公開出典/ATR/PSY二状態を不変な参照へ写す。

    引数: row (dict|None) は当場の直前有効公開足。
    返り値: dict|None は使用属性だけのsnapshot。
    """
    fields = ("場", *SOURCE_FIELDS, "atr", "価格数値入力可", "PSY現", "PSY前", "PSY準備済")
    return deepcopy({key: row[key] for key in fields}) if row is not None else None


def decisions(context: dict, side: int) -> dict:
    """厳密幅増加を共通に、P1だけのPSY整数二状態を適用する。

    引数: context (dict) は当時数値/準備、side (int) は実方向。
    返り値: dict は全P採否。表示幅のfloat差や率閾値を採否に使わない。
    """
    reasons = list(context["M除外理由"])
    if not context["時間条件可"]:
        reasons.append("要求時間条件外")
    if not context["確認遅延条件可"]:
        reasons.append("確認遅延30秒超")
    if context["BB幅比較厳密符号"] != 1:
        reasons.append("BB絶対幅strict拡大不成立")
    current, previous = context["PSY現"], context["PSY前"]
    aligned = bool(current is not None and previous is not None and
        side * current["方向差整数"] > 0 and side * previous["方向差整数"] > 0)
    output = {}
    for policy in POLICIES:
        local = list(reasons)
        if policy == "P1" and not aligned:
            local.append("PSY整数U_D二状態実方向不成立")
        output[policy] = {"採用": not local, "理由": local or ["価格突破と複合条件採用"], "同時競合": False}
    return output


def generate(frames: list[dict], session: str, cutoff: float, deadline: float, config: dict) -> tuple[dict, dict]:
    """同場区間から直前20価格を直接取り直し、原突破と全P採否を列挙する。

    引数: frames (list[dict]) は独立3分数値足、session (str) は場、cutoff/deadline (float) は停止/期限、
    config (dict) は固定30条件。
    返り値: tuple[dict,dict] は二純入口と全context/rawP品質。ラベル/PnLを呼ばない。
    """
    if any(row["場"] != session or row["minutes"] != 3 for row in frames):
        raise ValueError("当場3分以外の公開足を混ぜません")
    segment, contexts, raw, groups = [], [], [], defaultdict(list)
    price_count = common_count = 0
    for position, current in enumerate(frames):
        prior_index = frames[position - 1]["index"] if position else None
        continuous = current["publish"] and current["価格数値入力可"] and not current["missing"] and (
            current["index"] == (0 if prior_index is None else prior_index + 1))
        if not continuous:
            segment = []
        before = segment[-20:]
        ready = bool(len(before) == 20 and current["publish"] and current["価格数値入力可"])
        previous = before[-1] if before else None
        after = before[1:] + [current] if ready else []
        old_bb, new_bb = bb20(before), bb20(after)
        bb = {prefix + "BB" + key: item for prefix, values in (("旧", old_bb), ("現", new_bb)) for key, item in values.items()}
        precision = dict(zip(EXACT_FIELDS, exact_width_change(before, after)))
        high = max(row["high"] for row in before) if ready else None
        low = min(row["low"] for row in before) if ready else None
        reasons = []
        if not ready:
            reasons.append("同場直前20公開価格足未準備")
        if not B.finite(current["atr"]) or current["atr"] <= 0:
            reasons.append("現在ATR正未準備")
        if not current["PSY準備済"]:
            reasons.append("同場PSY現前未準備")
        if not B.finite(bb["旧BB幅"]) or not B.finite(bb["現BB幅"]) or precision["BB幅比較厳密符号"] is None:
            reasons.append("現前BB幅精密比較未準備")
        context = {**deepcopy(current), **bb, **precision, "時間足分": 3, "価格準備": ready,
            "前20足番号": [row["index"] for row in before], "現BB足番号": [row["index"] for row in after],
            "直前最高H": high, "直前最安L": low, "前3分参照": reference(previous), "共通M準備": not reasons,
            "M除外理由": reasons, "時間条件可": current["confirm"] < cutoff and deadline - current["confirm"] >= config["残り時間下限分"] * 60,
            "確認遅延条件可": current["confirm"] - current["end"] <= config["確認遅延上限秒"]}
        contexts.append(context)
        price_count += int(ready)
        common_count += int(not reasons)
        if ready:
            sides = ([1] if current["close"] > high else []) + ([-1] if current["close"] < low else [])
            for side in sides:
                event = f"NK225_{session}_3分_価格突破_{current['index']:04d}_{side}"
                row = {**deepcopy(context), "入口系統": "T価格突破", "役割": "順行", "side": side,
                    "方向": "買い" if side > 0 else "売り", "発動ID": event, "QイベントID": event, "イベントID": event,
                    "入口ID": "3分_T価格突破", "要求時計秒": current["confirm"], "要求原板行": current["confirm_line"],
                    "足終了時計秒": current["end"], "確認遅延秒": current["confirm"] - current["end"],
                    "期限時計秒": deadline, "残り分_判断時": (deadline - current["confirm"]) / 60,
                    "先着評価対象": context["時間条件可"] and context["確認遅延条件可"], "戦略判定": decisions(context, side)}
                raw.append(row)
                for policy in POLICIES:
                    if row["戦略判定"][policy]["採用"]:
                        groups[policy, current["confirm"], current["confirm_line"]].append(row)
        if current["publish"] and current["価格数値入力可"] and not current["missing"]:
            segment.append(current)
    for (policy, _, _), same_key in groups.items():
        if len(same_key) > 1:
            for row in same_key:
                row["戦略判定"][policy] = {"採用": False, "同時競合": True, "理由": ["同判断複数信号見送り"]}
    selected = {"3分_" + policy: [] for policy in POLICIES}
    for row in raw:
        for policy in POLICIES:
            if row["戦略判定"][policy]["採用"]:
                selected["3分_" + policy].append({**deepcopy(row), "入口ID": "3分_" + policy, "戦略": policy,
                    "複合判定": deepcopy(row["戦略判定"][policy]), "イベントID": row["発動ID"] + "_" + policy})
    return selected, {"場": session, "時間足分": 3, "足数": len(frames), "価格20窓準備足数": price_count,
        "共通M準備足数": common_count, "原価格発動数": len(raw), "全Q発動記録": raw, "複合context記録": contexts,
        "先着評価対象外数": sum(not row["先着評価対象"] for row in raw),
        "戦略別発動数": {key: len(rows) for key, rows in selected.items()},
        "戦略採否理由別": {policy: dict(Counter(reason for row in raw for reason in row["戦略判定"][policy]["理由"])) for policy in POLICIES}}


def reconstruct(manifest: dict, config: dict) -> Any:
    """固定8列の原OHLCからATR/PSY/BB/原価格突破を独立再構成する。

    引数: manifest/config (dict) は実66台帳/固定30条件。
    返り値: Any は場別iterator。数量/MACD/先着/運用を計算しない。
    """
    bank = NumericHistory()
    for entry in manifest["entries"]:
        session = entry["session"]
        start, finish, cutoff, deadline = S.G.times(session)
        data = observed(entry, manifest)
        formed = S.bars(data, session, 3, B.BareBars())
        tail = max(0, int((finish - start) // 180) - 1 - (formed[-1]["index"] if formed else -1))
        frames, numeric_quality = bank.build(formed, session, tuple(entry["in_session_contract_codes"]), tail)
        signals, quality = generate(frames, session, cutoff, deadline, config)
        phase = "学習" if session[:10] < config["分割"]["選択開始日"] else (
            "条件選択" if session[:10] < config["分割"]["後続開始日"] else "後続検査")
        yield {"場": session, "期間": phase, "価格足": {3: frames}, "指標品質": [numeric_quality],
            "入口品質": quality, "純入口": signals, "新規停止": cutoff, "期限": deadline,
            "入力品質": {"場": session, "正常板数": int(data["valid"].sum()),
                "確定足数": {"3": sum(row["publish"] for row in frames)}, "尾部欠枠": {"3": tail}}}


# ----------------------------------------
# 固定入力と準備の版を、価格計算へ進む前に確認する。

def resolved_manifest(study: Path) -> tuple[dict, Path]:
    """入力pointerを正本28の同一66場へ限定して解決する。

    引数: study (Path) は30の正式先。
    返り値: tuple[dict,Path] は実台帳/正本パス。任意の別入力へ差し替えない。
    """
    pointer = V.read(study / "入力台帳.json")
    actual = (study / pointer["参照"]).resolve()
    canonical = ROOT / "study/00028_基準線復帰と上位一目の方向/入力台帳.json"
    if actual != canonical or V.sha(actual) != pointer["SHA256"]:
        raise ValueError("入力参照は固定28正本の66場に限定")
    manifest = V.read(actual)
    if len(manifest["entries"]) != 66 or len({row["session"] for row in manifest["entries"]}) != 66:
        raise ValueError("一意な既使用66場が必要")
    return manifest, actual



def guarded_inputs(study: Path, work: Path, audit: Audit) -> tuple[dict, dict, dict, Path]:
    """固定数値/pointerと主準備の版をcacheへ進む前に確認する。

    引数: study/work (Path) は正式/作業先、audit (Audit) は記録。
    返り値: tuple[dict,dict,dict,Path] は条件/実台帳/主準備/解決台帳。
    """
    config = V.read(study / "条件.json")
    manifest, resolved = resolved_manifest(study)
    audit.check("事前二候補", config["戦略"], list(POLICIES))
    old = V.read(ROOT / "study/00028_基準線復帰と上位一目の方向/条件.json")
    for key in ("対象", "時間足分", "出口", "逆行pt", "順行pt", "残り時間下限分", "確認遅延上限秒", "運用",
            "必須追尾", "入口支持", "費用支持", "目標確認率", "間引き必要件数", "分割"):
        audit.check("継承運用尺度/費用/支持:" + key, config[key], old[key])
    master = V.read(work / "準備点検.json")
    audit.check("準備ラベルなし", master["ラベル計算"], False)
    audit.check("準備損益なし", master["損益計算"], False)
    audit.check("主準備条件", master["条件SHA256"], V.sha(study / "条件.json"))
    audit.check("主準備入力pointer", master["入力台帳SHA256"], V.sha(study / "入力台帳.json"))
    audit.check("主準備解決入力", master["参照台帳SHA256"], V.sha(resolved))
    allowed = {"scripts/PSY突破/" + name for name in ("検証.py", "入口.py", "指標.py")}
    audit.check("事前三主コード", set(master["コードSHA256"]), allowed)
    if set(master["コードSHA256"]) == allowed:
        for path, digest in master["コードSHA256"].items():
            audit.check("主準備コード現在:" + path, V.sha(ROOT / path), digest)
    audit.check("主66場順", [row["場"] for row in master["準備"]], [row["session"] for row in manifest["entries"]])
    if audit.mismatches:
        raise ValueError("固定条件/入力/主準備の不一致によりcache前停止")
    return config, manifest, master, resolved



def stage(block: dict) -> dict:
    """ラベルなし入口品質の大列を除き、小さな段階集計を返す。

    引数: block (dict) は独立再構成した場。
    返り値: dict は期間付き品質。全context/rawは元workだけに保持する。
    """
    return {"期間": block["期間"], **{key: value for key, value in block["入口品質"].items()
        if key not in ("全Q発動記録", "複合context記録")}}



def count_signals(block: dict) -> list[dict]:
    """各案の場別純採用・方向数を数える。

    引数: block (dict) は独立場。
    返り値: list[dict] は当場P0/P1の件数。仮約定や実参加ではない。
    """
    return [{"場": block["場"], "期間": block["期間"], "入口ID": key, "発動数": len(rows),
        "買い発動数": sum(row["side"] == 1 for row in rows), "売り発動数": sum(row["side"] == -1 for row in rows)}
        for key, rows in block["純入口"].items()]



def period_counts(counts: list[dict]) -> list[dict]:
    """期間別の純採用と活動場・開始日数を集計する。

    引数: counts (list[dict]) は場別件数。
    返り値: list[dict] は固定P順/期間順の件数。
    """
    output = []
    for policy in POLICIES:
        for phase in ("学習", "条件選択", "後続検査"):
            local = [row for row in counts if row["入口ID"] == "3分_" + policy and row["期間"] == phase]
            active = [row for row in local if row["発動数"]]
            output.append({"入口ID": "3分_" + policy, "期間": phase, "発動数": sum(row["発動数"] for row in local),
                "発動場数": len(active), "発動開始日数": len({row["場"][:10] for row in active}),
                "買い発動数": sum(row["買い発動数"] for row in local), "売り発動数": sum(row["売り発動数"] for row in local)})
    return output


# ----------------------------------------
# 原突破から必然となるPSYの単調関係を、採否条件を変えず補助確認する。

def raw_psy_check(rows: list[dict], audit: Audit) -> dict:
    """全rawの実方向終値差とPSY現前の入替恒等式を検査する。

    引数: rows (list[dict]) は原価格突破、audit (Audit) は照合記録。
    返り値: dict は共通準備前も含めた件数。二状態を独立二票とは扱わない。
    """
    totals = Counter({"原価格発動数": len(rows), "PSY現前準備数": 0, "前状態実方向正数": 0,
        "前状態正かつ現状態非正数": 0, "方向差増分負数": 0})
    for row in rows:
        key, side, previous = row["発動ID"], row["side"], row["前3分参照"]
        audit.check(key + ":価格突破は当足終値差実方向正", previous is not None and
            side * (row["close"] - previous["close"]) > 0, True)
        current, before = row["PSY現"], row["PSY前"]
        if current is None or before is None:
            continue
        totals["PSY現前準備数"] += 1
        oriented_current, oriented_previous = side * current["方向差整数"], side * before["方向差整数"]
        increment = oriented_current - oriented_previous
        totals["前状態実方向正数"] += int(oriented_previous > 0)
        totals["前状態正かつ現状態非正数"] += int(oriented_previous > 0 and oriented_current <= 0)
        totals["方向差増分負数"] += int(increment < 0)
        audit.check(key + ":PSY入替実方向差は0か1か2", increment in (0, 1, 2), True)
        audit.check(key + ":前PSY実方向正なら現PSYも正", oriented_previous <= 0 or oriented_current > 0, True)
        for name, item in (("現", current), ("前", before)):
            audit.check(key + ":PSY" + name + ":U_D_F合計12", item["上昇数"] + item["下落数"] + item["同値数"], 12)
            audit.check(key + ":PSY" + name + ":方向差整数", item["方向差整数"], item["上昇数"] - item["下落数"])
    return dict(totals)


def proof_base(study: Path, work: Path, resolved: Path, audit: Audit) -> dict:
    """準備と正式に共通する照合範囲とコード/入力指紋を作る。

    引数: study/work/resolved (Path) は正式/作業/実台帳、audit (Audit) は記録。
    返り値: dict は共通proof。先着数値・会計を計算したとは記さない。
    """
    return {"全件一致": audit.mismatches == 0, "照合項目数": audit.count, "不一致数": audit.mismatches,
        "不一致": audit.errors, "入力場数": 66, "全66場既使用": True,
        "コードSHA256": V.sha(Path(__file__)), "条件SHA256": V.sha(study / "条件.json"),
        "入力台帳SHA256": V.sha(study / "入力台帳.json"), "解決入力台帳SHA256": V.sha(resolved),
        "参照入力台帳SHA256": V.sha(resolved), "主準備SHA256": V.sha(work / "準備点検.json"),
        "独立足補助SHA256": V.sha(ROOT / "scripts/一目基準線/状態独立確認.py"),
        "ATR照合": {"leaf数": audit.atr_count, "表現差数": audit.atr_repr_diff, "最大絶対差": audit.atr_max_abs,
            "追尾D整数差数": audit.atr_tick_diff, "許容": "abs1e-10/rel0と正有効/追尾D整数厳密"},
        "厳密照合": "ATR以外は価格/時点/出典、PSY整数と表示率、BB表示値、Fraction母分散現前差/符号/既約分子分母、全M/採否を厳密比較。採否epsilonなし"}


def prepare(study: Path, work: Path) -> dict:
    """原OHLCのATR/PSY/BB/全突破と全P採否をラベルなし主準備へ照合する。

    引数: study/work (Path) は正式/作業先。
    返り値: dict は準備proof。先着/運用/損益を計算しない。
    """
    audit, original_code = Audit(), V.sha(Path(__file__))
    config, manifest, master, resolved = guarded_inputs(study, work, audit)
    totals, counts, stages, psy_diagnostics = Counter(), [], [], Counter()
    for saved, block in zip(master["準備"], reconstruct(manifest, config), strict=True):
        session = block["場"]
        expected = {"場": session, "期間": block["期間"], "指標": {"3": block["価格足"][3]},
            "入口品質": block["入口品質"], "指標品質": block["指標品質"], "入力品質": block["入力品質"]}
        audit.check(session + ":全数値/価格/採否", saved, expected)
        counts.extend(count_signals(block))
        stages.append(stage(block))
        raw = block["入口品質"]["全Q発動記録"]
        totals["3分足"] += len(block["価格足"][3])
        totals["原価格発動"] += len(raw)
        for policy in POLICIES:
            totals[policy] += len(block["純入口"]["3分_" + policy])
        for row in raw:
            audit.check(row["発動ID"] + ":P1はP0部分集合", not row["戦略判定"]["P1"]["採用"] or row["戦略判定"]["P0"]["採用"], True)
        psy_diagnostics.update(raw_psy_check(raw, audit))
        print(json.dumps({"場": session, "独立準備": "原OHLC/ATR/価格20窓/精密分散差/PSY二状態/全P", "不一致数": audit.mismatches}, ensure_ascii=False), flush=True)
    audit.check("全場二案件数", master["場別発動"], counts)
    grouped = period_counts(counts)
    audit.check("全期間二案件数", master["期間別発動"], grouped)
    audit.check("独立実行中code不変", V.sha(Path(__file__)), original_code)
    proof = {**proof_base(study, work, resolved, audit), "ラベル計算": False, "損益計算": False,
        "全数": dict(totals), "場別発動": counts, "期間別発動": grouped, "監視段階": stages,
        "原突破PSY恒等関係": dict(psy_diagnostics), "主コードSHA256": master["コードSHA256"],
        "検証範囲": "固定66cacheの当場非後退列から半開OHLCを独立構築。ATR/毎場の公開PSY12現前/直前20高安/旧現BB20絶対幅/分数偏差二乗和による母分散差/全context/M/rawP/全P採否/競合/件数を比較。原突破の終値実方向差とPSY現前の単調関係を別確認。",
        "限界": "準備だけで先着/新規受入/運用/PnLを呼ばない。量/MACD等を採否に使用しない。原板本文を再抽出せず固定cacheを共通入力とする。PSY現前は独立二票ではない。"}
    (work / "独立準備点検.json").write_text(json.dumps(proof, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({key: proof[key] for key in ("全件一致", "照合項目数", "不一致数", "入力場数", "ラベル計算", "損益計算")}, ensure_ascii=False))
    return proof


# ----------------------------------------
# 正式監査は固定と準備を先に照合し、全保存状態と6gzipを指紋で結び付ける。

def run(study: Path, work: Path) -> dict:
    """root正式完了後だけ6gzipの全保存状態を原OHLCから検算する。

    引数: study/work (Path) は正式/作業先。
    返り値: dict は全状態proof。通常先着数値・会計・追尾は別監査へ分ける。
    """
    if not (study / "結果.json").exists() or not (study / "固定.json").exists():
        raise ValueError("正式固定とroot再生完了通知後に実行します")
    audit, original_code = Audit(), V.sha(Path(__file__))
    config, manifest, master, resolved = guarded_inputs(study, work, audit)
    prepared = V.read(work / "独立準備点検.json")
    for key, expected in (("全件一致", True), ("コードSHA256", original_code),
            ("主準備SHA256", V.sha(work / "準備点検.json")), ("条件SHA256", V.sha(study / "条件.json")),
            ("入力台帳SHA256", V.sha(study / "入力台帳.json")), ("解決入力台帳SHA256", V.sha(resolved))):
        audit.check("独立準備bind:" + key, prepared[key], expected)
    fixed, formal = V.read(study / "固定.json"), V.read(study / "結果.json")
    for path, digest in fixed["ファイルSHA256"].items():
        audit.check("正式固定現在:" + path, V.sha(ROOT / path), digest)
    audit.check("正式二候補", [row["候補ID"] for row in formal["結果"]], ["3分_" + policy + "_X0" for policy in POLICIES])
    if audit.mismatches:
        raise ValueError("固定/独立準備の版差によりcache前停止")
    names = ("全指標", "全複合context", "全複合shadow", "入口事例", "全運用詳細", "追尾")
    rows, hashes, grouped = {}, {}, {}
    artifacts = {Path(row["パス"]).name: row for row in V.read(study / "作業成果物.json")["ファイル"]}
    sessions = {entry["session"] for entry in manifest["entries"]}
    for name in names:
        rows[name], hashes[name] = B.compressed_rows(work / (name + ".jsonl.gz"))
        audit.check("正式成果物全文SHA:" + name, hashes[name], artifacts[name + ".jsonl.gz"]["展開内容SHA256"])
        by_session = defaultdict(list)
        for row in rows[name]:
            audit.check("保存場は既使用66内:" + name, row["場"] in sessions, True)
            by_session[row["場"]].append(row)
        grouped[name] = by_session
    input_quality, entrance_quality, numeric_quality = (V.read(study / name) for name in
        ("入力品質.json", "入口品質.json", "指標品質.json"))
    for name, local in (("入力", input_quality), ("入口", entrance_quality), ("指標", numeric_quality)):
        audit.check(name + "品質66件", len(local), 66)
    input_quality = {row["場"]: row for row in input_quality}
    entrance_quality = {row["場"]: row for row in entrance_quality}
    numeric_quality = {row["場"]: row for row in numeric_quality}
    stages, raw_expected, case_expected, psy_diagnostics = [], {}, {}, Counter()
    for block in reconstruct(manifest, config):
        session, phase = block["場"], block["期間"]
        audit.check(session + ":全ATR/PSY", grouped["全指標"][session], [{"期間": phase, **row} for row in block["価格足"][3]])
        audit.check(session + ":全context/BB/M", grouped["全複合context"][session],
            [{"期間": phase, **row} for row in block["入口品質"]["複合context記録"]])
        expected_raw = [{"期間": phase, **row} for row in block["入口品質"]["全Q発動記録"]]
        audit.check(session + ":原P全件数", len(grouped["全複合shadow"][session]), len(expected_raw))
        for actual, expected in zip(grouped["全複合shadow"][session], expected_raw):
            B.compare_signal(audit, actual, expected, False)
            raw_expected[expected["発動ID"]] = expected
        psy_diagnostics.update(raw_psy_check(expected_raw, audit))
        expected_cases = [{"期間": phase, **row} for local in block["純入口"].values() for row in local]
        audit.check(session + ":全P純採用数", len(grouped["入口事例"][session]), len(expected_cases))
        for actual, expected in zip(grouped["入口事例"][session], expected_cases):
            B.compare_signal(audit, actual, expected, True)
            case_expected[expected["イベントID"]] = expected
        small = stage(block)
        stages.append(small)
        audit.check(session + ":入口品質", entrance_quality[session], small)
        audit.check(session + ":入力品質", input_quality[session], {"期間": phase, **block["入力品質"]})
        audit.check(session + ":指標品質", numeric_quality[session], {"期間": phase, **block["指標品質"][0]})
        details = grouped["全運用詳細"][session]
        audit.check(session + ":全二案運用", {row["候補ID"] for row in details}, {"3分_" + policy + "_X0" for policy in POLICIES})
        audit.check(session + ":運用一意2件", len(details), 2)
        for detail in details:
            audit.check(session + ":運用品質期間", detail["品質"]["期間"], phase)
        print(json.dumps({"場": session, "独立確認": "原OHLC/ATR/PSY/精密BB/原P/全P", "不一致数": audit.mismatches}, ensure_ascii=False), flush=True)
    audit.check("原P全一意集合", {row["発動ID"] for row in rows["全複合shadow"]}, set(raw_expected))
    audit.check("全P採用一意集合", {row["イベントID"] for row in rows["入口事例"]}, set(case_expected))
    canonical_diffs = 0
    for row in rows["入口事例"]:
        expected = raw_expected.get(row["発動ID"])
        same = expected is not None and row["戦略判定"] == expected["戦略判定"]
        canonical_diffs += int(not same)
        audit.check(row["イベントID"] + ":全P採否canonical", same, True)
    audit.check("独立実行中code不変", V.sha(Path(__file__)), original_code)
    proof = {**proof_base(study, work, resolved, audit),
        "期間場数": {phase: sum(row["期間"] == phase for row in stages) for phase in ("学習", "条件選択", "後続検査")},
        "表示属性注意": canonical_diffs != 0, "case内canonical判定不一致数": canonical_diffs,
        "保存指標数": len(rows["全指標"]), "保存context数": len(rows["全複合context"]), "保存shadow数": len(rows["全複合shadow"]),
        "保存発動候補数": len(rows["全複合shadow"]), "保存入口数": len(rows["入口事例"]),
        "保存運用詳細数": len(rows["全運用詳細"]), "保存追尾数": len(rows["追尾"]), "監視段階": stages,
        "原突破PSY恒等関係": dict(psy_diagnostics),
        "成果物照合": {name + ".jsonl.gz": {"展開内容SHA256": hashes[name], "行数": len(rows[name])} for name in names},
        **{name + "展開SHA256": digest for name, digest in hashes.items()}, "発動候補展開SHA256": hashes["全複合shadow"],
        "結果SHA256": V.sha(study / "結果.json"), "固定SHA256": V.sha(study / "固定.json"),
        "独立準備SHA256": V.sha(work / "独立準備点検.json"),
        "検証範囲": "固定cacheからATR/PSY/価格20窓/絶対BB幅/分数分散差と全P採否を独立再構成。正式全足/全context/rawP/case/品質と時間遅延対象外9Noneを全件比較し、6gzip全行の展開SHAをbind。PSY単調関係を全rawで検算。",
        "限界": "通常先着数値・実新規受入・会計・追尾は別監査。原板本文を再抽出せず固定cacheを共通入力とする。既使用66場を未見と呼ばない。原突破PSY現前は独立二票ではない。"}
    (work / "状態独立確認.json").write_text(json.dumps(proof, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({key: proof[key] for key in ("全件一致", "照合項目数", "不一致数", "入力場数", "保存shadow数", "保存入口数")}, ensure_ascii=False))
    return proof


def main() -> None:
    """固定前準備とroot正式完了後の状態監査を明示指定で分ける。

    引数: なし。--study/--work/--prepare/--実行許可を読む。
    返り値: None。不一致は非0終了。無指定で先着/運用を読まない。
    """
    parser = argparse.ArgumentParser(description="PSY突破の原OHLC独立状態確認")
    parser.add_argument("--study", type=Path, default=STUDY)
    parser.add_argument("--work", type=Path, default=WORK)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--prepare", action="store_true")
    mode.add_argument("--実行許可", action="store_true")
    args = parser.parse_args()
    proof = prepare(args.study.resolve(), args.work.resolve()) if args.prepare else run(args.study.resolve(), args.work.resolve())
    if not proof["全件一致"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

