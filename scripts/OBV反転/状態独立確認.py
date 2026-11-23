"""00029の原8列数量・中心化MACD・価格窓・OBV区間と採否を独立再構成する。"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from copy import deepcopy
import json
import importlib.util
import math
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT / "study/00029_BB内復帰とOBV非追随"
WORK = ROOT / "work/OBV反転/00029"
INPUT = STUDY / "入力台帳.json"


def helper(path: Path, name: str) -> Any:
    """固定済み独立補助だけをコマンド実行せず読み込む。

    引数: path (Path) は独立補助、name (str) は識別名。
    返り値: Any は補助。29主の指標/入口/運用はimportしない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


B = helper(ROOT / "scripts/一目基準線/状態独立確認.py", "OBV反転の固定独立足と比較")
Q = helper(ROOT / "scripts/数量反転/数量独立確認.py", "OBV反転の固定独立数量区間")
S, V, P, SOURCE_FIELDS = B.S, B.V, B.P, B.SOURCE_FIELDS
POLICIES = ("R0", "R1")


def observed(entry: dict, manifest: dict) -> dict:
    """原8列cacheから同場の非後退観測だけを別に取り出す。

    引数: entry/manifest (dict) は固定入力行/台帳。
    返り値: dict はnow/line/last/bid/ask/valid/volume/volume_time。数量時計で並べ替えない。
    """
    source = Path(manifest["source_root"]) / entry["source_path"]
    stat = source.stat()
    if (stat.st_size, stat.st_mtime_ns) != (entry["source_size"], entry["source_mtime_ns"]):
        raise ValueError("固定原板のstatが変更")
    cache = (ROOT / "work/複合検証" / entry["cache_path"]).resolve()
    if not cache.is_relative_to((ROOT / "work").resolve()) or V.sha(cache) != entry["sha256_cache"] or cache.stat().st_size != entry["cache_size"]:
        raise ValueError("固定cacheの範囲/指紋が変更")
    with S.np.load(cache, allow_pickle=False) as archive:
        data = {key: archive[key] for key in ("now", "line", "last", "bid", "ask", "valid", "volume", "volume_time")}
    start, finish, _, _ = S.G.times(entry["session"])
    indices = S.np.flatnonzero(S.np.isfinite(data["now"]) & (start <= data["now"]) & (data["now"] <= finish))
    times = data["now"][indices]
    if len(times):
        indices = indices[S.np.r_[True, times[1:] >= S.np.maximum.accumulate(times[:-1])]]
    return {key: values[indices] for key, values in data.items()}


class CenteredMACD:
    """最初の有効終値との差へ別実装EMAを当て、鏡像の奇関数性を保つ。"""

    def __init__(self) -> None:
        """原点と三EMAを未準備へ戻す。

        引数: なし。
        返り値: None。
        """
        self.origin = None
        self.fast, self.slow, self.signal = P.Exponential(12), P.Exponential(26), P.Exponential(9)

    def add(self, close: float) -> dict:
        """原点からの価格差を順次EMAへ投入する。

        引数: close (float) は現在の有効終値。
        返り値: dict は原点/MACD/Signal/H。数量不完全では初期化しない。
        """
        if self.origin is None:
            self.origin = close
        value = close - self.origin
        fast, slow = self.fast.add(value), self.slow.add(value)
        macd = fast - slow if fast is not None and slow is not None else None
        signal = self.signal.add(macd) if macd is not None else None
        hist = macd - signal if macd is not None and signal is not None else None
        return {"MACD原点": self.origin, "macd": macd, "macd_signal": signal, "macd_hist": hist}


def quantities(data: dict, frames: list[dict], start: float, finish: float) -> tuple[dict, dict]:
    """主の逐次aggregateを使わず、原累積列の区間隣接差から観測量を再構成する。

    引数: data (dict) は原8列、frames (list[dict]) は独立3分足、start/finish (float) は半開範囲。
    返り値: tuple[dict,dict] は固定14定義の数量属性/品質。全約定の完全性とは呼ばない。
    """
    return Q.independent_quantity(data, frames, start, finish, 3)


def obv_segments(frames: list[dict], quantity: dict) -> list[dict]:
    """公開価格/数量の切断後の区間を直接取り直し、符号付き量のprefix和を計算する。

    引数: frames (list[dict]) は当場3分原足、quantity (dict) は独立数量属性。
    返り値: list[dict] は各足の有効性/区間番号/0種/OBV。ゼロ量は有効量である。
    """
    segments, output = [], []
    for position, frame in enumerate(frames):
        item = quantity[frame["index"]]
        available = bool(frame["publish"] and not frame["missing"] and B.valid_ohlc(frame) and item["数量基準完全"] and
            B.finite(item["観測差分量"]) and item["観測差分量"] >= 0)
        gap = position == 0 or frame["missing"] or frame["index"] != frames[position - 1]["index"] + 1
        if not available:
            segments.append([])
            output.append({"有効": False, "区間番号": None, "種足": None, "種": False, "増分": None, "OBV": None})
            continue
        if gap or not segments or not segments[-1]:
            segments.append([])
        segment = segments[-1]
        segment.append((frame, item["観測差分量"]))
        changes = []
        for index in range(1, len(segment)):
            previous, current = segment[index - 1][0], segment[index][0]
            sign = int(current["close"] > previous["close"]) - int(current["close"] < previous["close"])
            changes.append(sign * segment[index][1])
        output.append({"有効": True, "区間番号": len(segments), "種足": segment[0][0]["index"],
            "種": len(segment) == 1, "増分": changes[-1] if changes else 0.0, "OBV": float(math.fsum(changes))})
    return output


class NumericHistory:
    """独立ATR/中心化MACDと、場内符号付き量のprefix和を保存形式へ投影する。"""

    def __init__(self) -> None:
        """限月を未確定にし数値系列を空にする。

        引数: なし。
        返り値: None。
        """
        self.contract = None
        self.clear()

    def clear(self) -> None:
        """数量区間とは独立に価格の数値銀行を解除する。

        引数: なし。
        返り値: None。限月識別は保持する。
        """
        self.absolute, self.center = P.Indicators(), CenteredMACD()
        self.origin_source = None

    def build(self, frames: list[dict], session: str, contract: tuple, tail_missing: int = 0,
              quantities: dict | None = None) -> tuple[list[dict], dict]:
        """価格切断と数量切断を別判定し、当場の全原足数値を作る。

        引数: frames (list[dict]) は3分原足、session (str) は当場、contract (tuple) は限月、
        tail_missing (int) は完全尾部欠枠、quantities (dict|None) は独立Q14属性。
        返り値: tuple[list[dict],dict] は数値/数量/OBV全足と品質。先着/運用は含まない。
        """
        changed = self.contract is not None and self.contract != contract
        if changed:
            self.clear()
        self.contract = contract
        output, previous_index, previous_key = [], None, None
        segment, segment_number, obv_clears, numeric_clears = [], 0, 0, int(changed)
        for frame in frames:
            index, key = frame["index"], (frame["confirm"], frame["confirm_line"])
            if frame["minutes"] != 3 or previous_index is not None and index <= previous_index:
                raise ValueError("独立原足の尺度/番号順が不正")
            if frame["publish"] and (frame["confirm"] < frame["end"] or previous_key is not None and key < previous_key):
                raise ValueError("独立原足の公開時点/順が不正")
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
            values = {"atr": None, "macd": None, "macd_signal": None, "macd_hist": None}
            if numeric:
                values["atr"] = self.absolute.add(frame)["atr"]
                if self.center.origin is None:
                    self.origin_source = {"場": session, **B.source(frame)}
                values.update({key: value for key, value in self.center.add(frame["close"]).items() if key != "MACD原点"})
            quantity = deepcopy((quantities or {}).get(index))
            q = quantity.get("観測差分量") if quantity is not None else None
            q_ok = bool(quantity is not None and quantity.get("数量基準完全") and B.finite(q) and q >= 0)
            obv_reasons = list(reasons)
            if not frame["publish"]:
                obv_reasons.append("非公開足")
            if not q_ok:
                obv_reasons.append("数量基準不完全又は不正")
            if obv_reasons:
                segment = []
                obv_clears += 1
            seed, delta, value, segment_id = False, None, None, None
            if numeric and frame["publish"] and not frame["missing"] and q_ok:
                if not segment:
                    segment_number += 1
                    seed = True
                segment.append((frame, q))
                changes = [((int(current[0]["close"] > previous[0]["close"]) -
                    int(current[0]["close"] < previous[0]["close"])) * current[1])
                    for previous, current in zip(segment[:-1], segment[1:])]
                value = float(math.fsum(changes))
                delta = changes[-1] if changes else 0.0
                segment_id = f"{session}_量区間{segment_number:04d}"
            output.append({"場": session, **B.source(frame), **values, "価格数値入力可": numeric,
                "MACD原点": self.center.origin, "MACD原点出典": deepcopy(self.origin_source),
                "数量参照": quantity, "数量入力可": q_ok, "OBV": value, "OBV増分": delta, "OBV種": seed,
                "OBV区間ID": segment_id, "OBV区間足数": len(segment), "OBV公開可": segment_id is not None,
                "銀行解除理由": reasons, "OBV解除理由": obv_reasons})
            previous_index = index
            if frame["publish"]:
                previous_key = key
        if tail_missing:
            self.clear()
            numeric_clears += 1
        return output, {"場": session, "時間足分": 3, "入力足数": len(output),
            "価格数値入力足数": sum(row["価格数値入力可"] for row in output),
            "MACD準備足数": sum(B.finite(row["macd_hist"]) for row in output),
            "数量入力可足数": sum(row["数量入力可"] for row in output),
            "完全0量足数": sum(row["数量入力可"] and row["数量参照"]["観測差分量"] == 0 for row in output),
            "OBV公開足数": sum(row["OBV公開可"] for row in output), "OBV区間数": segment_number,
            "数値clear数": numeric_clears, "OBVclear数": obv_clears, "尾部完全欠枠": tail_missing,
            "非公開価格数値更新数": sum(not row["publish"] and row["価格数値入力可"] for row in output),
            "場末MACD原点": self.center.origin}


# ----------------------------------------
# 価格窓の切断点から直前20足を毎回取り直し、side別の最新同値kを列挙する。

def reference(row: dict | None) -> dict | None:
    """原点・数量・OBV区間を含む当時足の参照を固定する。

    引数: row (dict|None) は過去又は現在の独立数値足。
    返り値: dict|None は使用属性だけのsnapshot。
    """
    fields = ("場", *SOURCE_FIELDS, "atr", "macd", "macd_signal", "macd_hist", "MACD原点", "MACD原点出典",
        "価格数値入力可", "数量参照", "数量入力可", "OBV", "OBV区間ID", "OBV区間足数", "OBV公開可")
    return deepcopy({key: row[key] for key in fields}) if row is not None else None


def decisions(context: dict, side: int) -> dict:
    """両案の同じ準備へMACD反転方向とR1だけのOBV非追随を適用する。

    引数: context (dict) はside別準備を展開済みの当時足、side (int) は実方向。
    返り値: dict はR0/R1全採否。保有や未来ラベルを使わない。
    """
    reasons = list(context["M除外理由"])
    if not context["時間条件可"]:
        reasons.append("要求時間条件外")
    if not context["確認遅延条件可"]:
        reasons.append("確認遅延30秒超")
    change = context["MACDヒスト変化"]
    if not B.finite(change) or side * change <= 0:
        reasons.append("MACDヒスト一足差実方向不成立")
    output = {}
    for policy in POLICIES:
        local = list(reasons)
        if policy == "R1" and (not B.finite(context["OBV比較差"]) or side * context["OBV比較差"] <= 0):
            local.append("価格極値に対するOBV非追随不成立")
        output[policy] = {"採用": not local, "理由": local or ["旧帯内終値と複合反転採用"], "同時競合": False}
    return output


def generate(frames: list[dict], session: str, cutoff: float, deadline: float, config: dict) -> tuple[dict, dict]:
    """同場価格区間から原Pを列挙し、数量不完全でも価格発動を保持する。

    引数: frames (list[dict]) は独立3分数値足、session (str) は当場、cutoff/deadline (float) は停止/期限、
    config (dict) は29固定条件。
    返り値: tuple[dict,dict] は全R純入口/全context原P品質。数値先着を計算しない。
    """
    if any(row["場"] != session or row["minutes"] != 3 for row in frames):
        raise ValueError("当場3分以外を混ぜません")
    segment, contexts, raw, selected = [], [], [], defaultdict(list)
    price_ready_count = 0
    for position, current in enumerate(frames):
        prior_index = frames[position - 1]["index"] if position else None
        continuous = current["publish"] and current["価格数値入力可"] and not current["missing"] and (
            current["index"] == (0 if prior_index is None else prior_index + 1))
        if not continuous:
            segment = []
        previous20 = segment[-20:]
        ready = len(previous20) == 20 and current["publish"] and current["価格数値入力可"]
        previous = previous20[-1] if previous20 else None
        mean = sum(row["close"] for row in previous20) / 20 if len(previous20) == 20 else None
        sd = math.sqrt(sum((row["close"] - mean) ** 2 for row in previous20) / 20) if mean is not None else None
        lower, upper = (mean - 2 * sd, mean + 2 * sd) if mean is not None else (None, None)
        change = current["macd_hist"] - previous["macd_hist"] if previous and B.finite(
            current["macd_hist"]) and B.finite(previous["macd_hist"]) else None
        anchors, directional = {}, {}
        for side in (1, -1):
            k = None
            if ready:
                extreme = min(row["low"] for row in previous20) if side > 0 else max(row["high"] for row in previous20)
                candidates = [row for row in previous20 if row["low" if side > 0 else "high"] == extreme]
                k = candidates[-1]
            reasons = []
            if not ready:
                reasons.append("同場直前20公開価格足未準備")
            if not B.finite(current["atr"]) or current["atr"] <= 0:
                reasons.append("現在ATR正未準備")
            if not B.finite(change):
                reasons.append("同場隣接公開MACDヒスト未準備")
            if not current["数量入力可"]:
                reasons.append("当足数量基準完全未準備")
            same = bool(k and k["OBV公開可"] and current["OBV公開可"] and k["OBV区間ID"] == current["OBV区間ID"] and
                B.finite(current["OBV"]) and B.finite(k["OBV"]))
            if not same:
                reasons.append("当足と価格極値kの同一OBV区間未準備")
            anchors[side] = k
            directional[str(side)] = {"共通M準備": not reasons, "M除外理由": reasons, "OBV_k参照": reference(k),
                "OBV比較差": current["OBV"] - k["OBV"] if same else None}
        context = {**deepcopy(current), "時間足分": 3, "価格準備": ready, "前20足番号": [row["index"] for row in previous20],
            "旧BB平均": mean, "旧BB標準偏差": sd, "旧BB下端": lower, "旧BB上端": upper,
            "前3分参照": reference(previous), "MACDヒスト変化": change, "方向別準備": directional,
            "時間条件可": current["confirm"] < cutoff and deadline - current["confirm"] >= config["残り時間下限分"] * 60,
            "確認遅延条件可": current["confirm"] - current["end"] <= config["確認遅延上限秒"]}
        contexts.append(context)
        price_ready_count += int(ready)
        if ready and lower < current["close"] < upper:
            for side in (1, -1):
                k = anchors[side]
                if not (current["low"] < k["low"] if side > 0 else current["high"] > k["high"]):
                    continue
                event = f"NK225_{session}_3分_極値更新帯内_{current['index']:04d}_{side}"
                scoped = {**deepcopy(context), **deepcopy(directional[str(side)])}
                row = {**scoped, "入口系統": "R極値更新帯内", "役割": "反転", "side": side,
                    "方向": "買い" if side > 0 else "売り", "発動ID": event, "QイベントID": event, "イベントID": event,
                    "入口ID": "3分_R極値更新帯内", "要求時計秒": current["confirm"], "要求原板行": current["confirm_line"],
                    "足終了時計秒": current["end"], "確認遅延秒": current["confirm"] - current["end"], "期限時計秒": deadline,
                    "残り分_判断時": (deadline - current["confirm"]) / 60,
                    "先着評価対象": context["時間条件可"] and context["確認遅延条件可"], "戦略判定": decisions(scoped, side)}
                raw.append(row)
                for policy in POLICIES:
                    if row["戦略判定"][policy]["採用"]:
                        selected[policy, current["confirm"], current["confirm_line"]].append(row)
        if current["publish"] and not current["missing"] and current["価格数値入力可"]:
            segment.append(current)
    for (policy, _, _), same_key in selected.items():
        if len(same_key) > 1:
            for row in same_key:
                row["戦略判定"][policy] = {"採用": False, "同時競合": True, "理由": ["同判断複数信号見送り"]}
    grouped = {"3分_" + policy: [] for policy in POLICIES}
    for row in raw:
        for policy in POLICIES:
            if row["戦略判定"][policy]["採用"]:
                grouped["3分_" + policy].append({**deepcopy(row), "入口ID": "3分_" + policy, "戦略": policy,
                    "複合判定": deepcopy(row["戦略判定"][policy]), "イベントID": row["発動ID"] + "_" + policy})
    return grouped, {"場": session, "時間足分": 3, "足数": len(frames), "価格20窓準備足数": price_ready_count,
        "原価格発動数": len(raw), "全Q発動記録": raw, "複合context記録": contexts,
        "先着評価対象外数": sum(not row["先着評価対象"] for row in raw),
        "戦略別発動数": {key: len(rows) for key, rows in grouped.items()},
        "戦略採否理由別": {policy: dict(Counter(reason for row in raw for reason in row["戦略判定"][policy]["理由"])) for policy in POLICIES}}


def resolved_manifest(study: Path) -> tuple[dict, Path]:
    """入力pointerを正本28の同一66場へ限定して解決する。

    引数: study (Path) は29の正式先。
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


def reconstruct(manifest: dict, config: dict) -> Any:
    """原8列から数量/価格を別計算し、数値だけ同限月carryして原反転を列挙する。

    引数: manifest/config (dict) は実66台帳/29条件。
    返り値: Any は場別iterator。先着/運用を呼ばない。
    """
    bank = NumericHistory()
    for entry in manifest["entries"]:
        session = entry["session"]
        start, finish, cutoff, deadline = S.G.times(session)
        data = observed(entry, manifest)
        formed = S.bars(data, session, 3, B.BareBars())
        quantity, quantity_quality = quantities(data, formed, start, finish)
        tail = max(0, int((finish - start) // 180) - 1 - (formed[-1]["index"] if formed else -1))
        frames, numeric_quality = bank.build(formed, session, tuple(entry["in_session_contract_codes"]), tail, quantity)
        signals, quality = generate(frames, session, cutoff, deadline, config)
        phase = "学習" if session[:10] < config["分割"]["選択開始日"] else (
            "条件選択" if session[:10] < config["分割"]["後続開始日"] else "後続検査")
        yield {"場": session, "期間": phase, "価格足": {3: frames}, "指標品質": [numeric_quality],
            "数量品質": [{"場": session, **quantity_quality}], "入口品質": quality, "純入口": signals,
            "新規停止": cutoff, "期限": deadline, "入力品質": {"場": session,
                "正常板数": int(data["valid"].sum()), "確定足数": {"3": sum(row["publish"] for row in frames)},
                "尾部欠枠": {"3": tail}}}


class Audit(B.Audit):
    """事前合意のATR/MACD許容と、全符号/採否/数量/価格の厳密比較を分ける。"""

    def __init__(self) -> None:
        """基底比較器とMACD各列の差分集計を用意する。

        引数: なし。
        返り値: None。
        """
        super().__init__()
        self.macd_differences, self.macd_examples, self.macd_sign_diffs = {}, [], 0

    def check(self, name: str, actual: Any, expected: Any) -> None:
        """MACD末端だけ既定許容で比較し、符号は許容なしで照合する。

        引数: name (str) は経路、actual/expected (Any) は主/独立値。
        返り値: None。採否へepsilonを足さず、符号差があれば不一致にする。
        """
        field = name.rsplit(":", 1)[-1]
        if field in ("macd", "macd_signal", "macd_hist", "MACDヒスト変化") and B.finite(actual) and B.finite(expected):
            stats = self.macd_differences.setdefault(field, {"全数値leaf": 0, "leaf差数": 0, "最大絶対差": 0.0})
            stats["全数値leaf"] += 1
            stats["leaf差数"] += int(actual != expected)
            stats["最大絶対差"] = max(stats["最大絶対差"], abs(actual - expected))
            if actual != expected and len(self.macd_examples) < 20:
                self.macd_examples.append({"経路": name, "主": actual, "独立": expected, "絶対差": abs(actual - expected)})
            self.leaf(name, actual, expected, math.isclose(actual, expected, abs_tol=1e-10, rel_tol=0))
            left_sign = int(actual > 0) - int(actual < 0)
            right_sign = int(expected > 0) - int(expected < 0)
            self.macd_sign_diffs += int(left_sign != right_sign)
            self.leaf(name + ":厳密符号", left_sign, right_sign, left_sign == right_sign)
            return
        super().check(name, actual, expected)


def compare_quantity_quality(audit: Audit, name: str, actual: list, expected: list) -> None:
    """数量品質のcounterだけ、未出現0キーを0として照合する。

    引数: audit (Audit) は記録、name (str) は場/期間、actual/expected (list) は品質列。
    返り値: None。足ごとの数量参照は別に全属性を厳密比較する。
    """
    audit.check(name + ":品質数", len(actual), len(expected))
    for index, (left, right) in enumerate(zip(actual, expected)):
        for key in sorted(left.keys() | right.keys()):
            audit.check(name + ":" + str(index) + ":" + key, left.get(key, 0), right.get(key, 0))


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
    allowed = {"scripts/OBV反転/" + name for name in ("検証.py", "入口.py", "指標.py")}
    audit.check("事前三主コード", set(master["コードSHA256"]), allowed)
    if set(master["コードSHA256"]) == allowed:
        for path, digest in master["コードSHA256"].items():
            audit.check("主準備コード現在:" + path, V.sha(ROOT / path), digest)
    audit.check("主66場順", [row["場"] for row in master["準備"]], [row["session"] for row in manifest["entries"]])
    if audit.mismatches:
        raise ValueError("固定数量/入力/主準備の不一致によりcache前停止")
    return config, manifest, master, resolved


def stage(block: dict) -> dict:
    """ラベルなし入口品質の大列を除き、小さな段階集計を返す。

    引数: block (dict) は独立再構成した場。
    返り値: dict は期間付き品質。全context/rawは元workだけに保持する。
    """
    return {"期間": block["期間"], **{key: value for key, value in block["入口品質"].items()
        if key not in ("全Q発動記録", "複合context記録")}}


def proof_base(study: Path, work: Path, resolved: Path, audit: Audit) -> dict:
    """準備と正式に共通する比較範囲・コード/入力指紋を作る。

    引数: study/work/resolved (Path) は正式/作業/実台帳、audit (Audit) は記録。
    返り値: dict は共通proof。通常先着・会計を計算したとは記さない。
    """
    return {"全件一致": audit.mismatches == 0, "照合項目数": audit.count, "不一致数": audit.mismatches,
        "不一致": audit.errors, "入力場数": 66, "全66場既使用": True,
        "コードSHA256": V.sha(Path(__file__)), "条件SHA256": V.sha(study / "条件.json"),
        "入力台帳SHA256": V.sha(study / "入力台帳.json"), "解決入力台帳SHA256": V.sha(resolved),
        "参照入力台帳SHA256": V.sha(resolved),
        "主準備SHA256": V.sha(work / "準備点検.json"),
        "独立足補助SHA256": V.sha(ROOT / "scripts/一目基準線/状態独立確認.py"),
        "独立数量補助SHA256": V.sha(ROOT / "scripts/数量反転/数量独立確認.py"),
        "ATR照合": {"leaf数": audit.atr_count, "表現差数": audit.atr_repr_diff, "最大絶対差": audit.atr_max_abs,
            "追尾D整数差数": audit.atr_tick_diff, "許容": "abs1e-10/rel0と正有効/追尾D整数厳密"},
        "MACD表現差": audit.macd_differences, "MACD差例": audit.macd_examples,
        "MACD照合": {"許容": "abs1e-10/rel0は中心化macd/signal/hist/現前差だけ。符号と全採否は厳密", "符号不一致数": audit.macd_sign_diffs}}


def count_signals(block: dict) -> list[dict]:
    """各案の場別純採用・方向数を数える。

    引数: block (dict) は独立場。
    返り値: list[dict] は当場R0/R1の件数。仮約定や実参加ではない。
    """
    return [{"場": block["場"], "期間": block["期間"], "入口ID": key, "発動数": len(rows),
        "買い発動数": sum(row["side"] == 1 for row in rows), "売り発動数": sum(row["side"] == -1 for row in rows)}
        for key, rows in block["純入口"].items()]


def period_counts(counts: list[dict]) -> list[dict]:
    """期間別の純採用と活動場・開始日数を集計する。

    引数: counts (list[dict]) は場別件数。
    返り値: list[dict] は固定R順/期間順の件数。
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


def prepare(study: Path, work: Path) -> dict:
    """原8列の全数量・全価格・中心化MACD・OBV・採否をラベルなし主準備へ照合する。

    引数: study/work (Path) は正式/作業先。
    返り値: dict は全準備proof。先着/運用/損益を計算しない。
    """
    audit = Audit()
    original_code = V.sha(Path(__file__))
    config, manifest, master, resolved = guarded_inputs(study, work, audit)
    totals, counts, stages = Counter(), [], []
    for saved, block in zip(master["準備"], reconstruct(manifest, config), strict=True):
        session = block["場"]
        expected = {"場": session, "期間": block["期間"], "指標": {"3": block["価格足"][3]},
            "入口品質": block["入口品質"], "指標品質": block["指標品質"], "入力品質": block["入力品質"]}
        audit.check(session + ":全数値/価格/採否", {key: value for key, value in saved.items() if key != "数量品質"}, expected)
        compare_quantity_quality(audit, session + ":原8列数量品質", saved["数量品質"], block["数量品質"])
        counts.extend(count_signals(block))
        stages.append(stage(block))
        totals["3分足"] += len(block["価格足"][3])
        totals["原価格発動"] += len(block["入口品質"]["全Q発動記録"])
        for policy in POLICIES:
            totals[policy] += len(block["純入口"]["3分_" + policy])
        for row in block["入口品質"]["全Q発動記録"]:
            audit.check(row["発動ID"] + ":R1はR0部分集合", not row["戦略判定"]["R1"]["採用"] or row["戦略判定"]["R0"]["採用"], True)
        print(json.dumps({"場": session, "独立準備": "原8列数量/中心化MACD/価格20窓/k/OBV/全R", "不一致数": audit.mismatches}, ensure_ascii=False), flush=True)
    audit.check("全場二案件数", master["場別発動"], counts)
    grouped = period_counts(counts)
    audit.check("全期間二案件数", master["期間別発動"], grouped)
    audit.check("独立実行中code不変", V.sha(Path(__file__)), original_code)
    proof = {**proof_base(study, work, resolved, audit), "ラベル計算": False, "損益計算": False,
        "全数": dict(totals), "場別発動": counts, "期間別発動": grouped, "監視段階": stages,
        "主コードSHA256": master["コードSHA256"],
        "検証範囲": "固定66cache原8列の同場非後退列から半開OHLCと原累積数量を別計算。独立の区間隣接差で全Q属性、原点中心化MACD/ATR、直前20窓と最新同値k、数量同区間OBVのprefix和、全context/方向別M/原P/全R採否/競合と件数を比較。",
        "限界": "準備だけで先着/新規受入/運用/PnLを呼ばない。真の全約定量/攻撃側flowとは呼ばない。数量品質の未出現0counterだけ0と同一視し、全足属性は別に比較。"}
    (work / "独立準備点検.json").write_text(json.dumps(proof, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({key: proof[key] for key in ("全件一致", "照合項目数", "不一致数", "入力場数", "ラベル計算", "損益計算")}, ensure_ascii=False))
    return proof


def run(study: Path, work: Path) -> dict:
    """root正式完了後だけ6gzip全保存状態を原8列から検算する。

    引数: study/work (Path) は正式/作業先。
    返り値: dict は全状態proof。通常先着数値と会計・追尾本体は別監査へ分ける。
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
    input_quality, entrance_quality, numeric_quality, quantity_quality = (V.read(study / name) for name in
        ("入力品質.json", "入口品質.json", "指標品質.json", "数量品質.json"))
    for name, local in (("入力", input_quality), ("入口", entrance_quality), ("指標", numeric_quality), ("数量", quantity_quality)):
        audit.check(name + "品質66件", len(local), 66)
    input_quality = {row["場"]: row for row in input_quality}
    entrance_quality = {row["場"]: row for row in entrance_quality}
    numeric_quality = {row["場"]: row for row in numeric_quality}
    quantity_quality = {row["場"]: row for row in quantity_quality}
    stages, raw_expected, case_expected = [], {}, {}
    for block in reconstruct(manifest, config):
        session, phase = block["場"], block["期間"]
        audit.check(session + ":全指標/Q/OBV", grouped["全指標"][session], [{"期間": phase, **row} for row in block["価格足"][3]])
        audit.check(session + ":全context/k/M", grouped["全複合context"][session],
            [{"期間": phase, **row} for row in block["入口品質"]["複合context記録"]])
        expected_raw = [{"期間": phase, **row} for row in block["入口品質"]["全Q発動記録"]]
        audit.check(session + ":原P全件数", len(grouped["全複合shadow"][session]), len(expected_raw))
        for actual, expected in zip(grouped["全複合shadow"][session], expected_raw):
            B.compare_signal(audit, actual, expected, False)
            raw_expected[expected["発動ID"]] = expected
        expected_cases = [{"期間": phase, **row} for local in block["純入口"].values() for row in local]
        audit.check(session + ":全R純採用数", len(grouped["入口事例"][session]), len(expected_cases))
        for actual, expected in zip(grouped["入口事例"][session], expected_cases):
            B.compare_signal(audit, actual, expected, True)
            case_expected[expected["イベントID"]] = expected
        small = stage(block)
        stages.append(small)
        audit.check(session + ":入口品質", entrance_quality[session], small)
        audit.check(session + ":入力品質", input_quality[session], {"期間": phase, **block["入力品質"]})
        audit.check(session + ":指標品質", numeric_quality[session], {"期間": phase, **block["指標品質"][0]})
        compare_quantity_quality(audit, session + ":数量品質", [quantity_quality[session]], [{"期間": phase, **block["数量品質"][0]}])
        details = grouped["全運用詳細"][session]
        audit.check(session + ":全二案運用", {row["候補ID"] for row in details}, {"3分_" + policy + "_X0" for policy in POLICIES})
        audit.check(session + ":運用一意2件", len(details), 2)
        for detail in details:
            audit.check(session + ":運用品質期間", detail["品質"]["期間"], phase)
        print(json.dumps({"場": session, "独立確認": "原8列/Q/中心化MACD/全OBV/k/原P/全R", "不一致数": audit.mismatches}, ensure_ascii=False), flush=True)
    audit.check("原P全一意集合", {row["発動ID"] for row in rows["全複合shadow"]}, set(raw_expected))
    audit.check("全R採用一意集合", {row["イベントID"] for row in rows["入口事例"]}, set(case_expected))
    canonical_diffs = 0
    for row in rows["入口事例"]:
        expected = raw_expected.get(row["発動ID"])
        same = expected is not None and row["戦略判定"] == expected["戦略判定"]
        canonical_diffs += int(not same)
        audit.check(row["イベントID"] + ":全R採否canonical", same, True)
    audit.check("独立実行中code不変", V.sha(Path(__file__)), original_code)
    proof = {**proof_base(study, work, resolved, audit),
        "期間場数": {phase: sum(row["期間"] == phase for row in stages) for phase in ("学習", "条件選択", "後続検査")},
        "表示属性注意": canonical_diffs != 0, "case内canonical判定不一致数": canonical_diffs,
        "保存指標数": len(rows["全指標"]), "保存context数": len(rows["全複合context"]), "保存shadow数": len(rows["全複合shadow"]),
        "保存発動候補数": len(rows["全複合shadow"]), "保存入口数": len(rows["入口事例"]),
        "保存運用詳細数": len(rows["全運用詳細"]), "保存追尾数": len(rows["追尾"]), "監視段階": stages,
        "成果物照合": {name + ".jsonl.gz": {"展開内容SHA256": hashes[name], "行数": len(rows[name])} for name in names},
        **{name + "展開SHA256": digest for name, digest in hashes.items()}, "発動候補展開SHA256": hashes["全複合shadow"],
        "結果SHA256": V.sha(study / "結果.json"), "固定SHA256": V.sha(study / "固定.json"),
        "独立準備SHA256": V.sha(work / "独立準備点検.json"),
        "検証範囲": "原8列から全数量/中心化MACD/ATR/価格20窓/最新同値k/OBV区間prefix和と全R採否を再構成。正式全足/全context/rawP/case/品質と時間遅延対象外9Noneを全件比較し、6gzip全行の展開SHAをbind。",
        "限界": "通常先着数値・実新規受入・会計・追尾は別監査。原板本文を再抽出せず固定8列cacheを共通入力とする。観測差分量は真の全約定量/攻撃側flowではない。既使用66場を未見と呼ばない。"}
    (work / "状態独立確認.json").write_text(json.dumps(proof, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({key: proof[key] for key in ("全件一致", "照合項目数", "不一致数", "入力場数", "保存shadow数", "保存入口数")}, ensure_ascii=False))
    return proof


def main() -> None:
    """固定前準備とroot正式完了後の状態監査を明示指定で分ける。

    引数: なし。--study/--work/--prepare/--実行許可を読む。
    返り値: None。不一致は非0終了。無指定で先着/運用を読まない。
    """
    parser = argparse.ArgumentParser(description="OBV反転の原8列独立状態確認")
    parser.add_argument("--study", type=Path, default=STUDY)
    parser.add_argument("--work", type=Path, default=WORK)
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--実行許可", action="store_true")
    args = parser.parse_args()
    if args.prepare:
        proof = prepare(args.study.resolve(), args.work.resolve())
    elif args.実行許可:
        proof = run(args.study.resolve(), args.work.resolve())
    else:
        parser.error("--prepare 又はroot正式完了後の --実行許可 が必要です")
    if not proof["全件一致"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
