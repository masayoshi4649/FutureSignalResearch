"""00041の原3分数値・中心偏差OLS・新突破と全先着を独立検算する。"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from fractions import Fraction
import importlib.util
import json
import math
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT / "study/00041_終値突破と回帰の方向と直線性"
WORK = ROOT / "work/回帰突破/00041"
INDICATOR_STUDY = ROOT / "study/00029_BB内復帰とOBV非追随"
INDICATOR_WORK = ROOT / "work/OBV反転/00029"
EXIT_STUDY = ROOT / "study/00033_CCI突破と足内終値位置"
POLICIES = ("L0", "L1", "L2")
OPERATIONS = tuple("3分_" + policy + "_XF" for policy in POLICIES)


def helper(path: Path, name: str) -> Any:
    """固定された独立足・数値・先着補助だけを読む。

    引数: path(Path)は固定独立コード、name(str)は読込名。
    返り値: Anyは補助。41主入口・主運用・主指標をimportしない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


Y = helper(ROOT / "scripts/発動値幅継続/状態独立確認.py", "回帰突破の固定独立原足と先着")
G, N, S, V = Y.G, Y.N, Y.S, Y.V
Audit = G.Audit
SIGNAL_FIELDS, LABEL_FIELDS, SOURCE_FIELDS = Y.SIGNAL_FIELDS, Y.LABEL_FIELDS, Y.SOURCE_FIELDS
FRAME_FIELDS = ("場", *SOURCE_FIELDS, "atr", "macd_hist")
canonical_sha, decision_signal = Y.canonical_sha, Y.decision_signal
normal_columns, label_direct = Y.normal_columns, Y.label_direct


def finite(value: object) -> bool:
    """真偽値を除いた有限実数だけを有効とする。

    引数: value(object)は保存値又は原観測値。
    返り値: boolは有限なint/floatであること。
    """
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def exact(value: Fraction | None) -> dict:
    """計算に使う分数と参考floatを分ける。

    引数: value(Fraction|None)は精密値又は未準備。
    返り値: dictは値/分子/分母/有効。未準備を0へ置換しない。
    """
    return {"値": float(value) if value is not None else None,
        "分子": value.numerator if value is not None else None,
        "分母": value.denominator if value is not None else None, "有効": value is not None}


def frame_projection(row: dict | None) -> dict | None:
    """当場3分の出典と使用数値だけを新辞書へ写す。

    引数: row(dict|None)は保存又は独立数値足。
    返り値: dict|Noneは15列。量・OBV・旧価格発動を含めない。
    """
    if row is not None and row["minutes"] != 3:
        raise ValueError("回帰突破は3分だけです")
    return None if row is None else {key: deepcopy(row[key]) for key in FRAME_FIELDS}


class NumericHistory:
    """原OHLCから別演算のWilder ATRと中心化MACDを更新する銀行。"""

    def __init__(self, minutes: int = 3) -> None:
        """3分数値銀行を未準備にする。

        引数: minutes(int)は3。
        返り値: None。同限月だけ数値をcarryする。
        """
        if minutes != 3:
            raise ValueError("回帰突破は3分だけです")
        self.contract = None
        self.clear()

    def clear(self) -> None:
        """前終値とATR/MACDの種・計算値を一緒に解除する。

        引数: なし。
        返り値: None。契約識別は保持し、数量品質では呼ばない。
        """
        self.previous, self.average, self.center = None, S.G.Wilder(), G.CenteredMACD()

    def build(self, frames: list[dict], session: str, contract: tuple,
              tail_missing: int = 0) -> tuple[list[dict], dict]:
        """原3分数値を更新し、全幅NPも数値銀行だけへ投入する。

        引数: frames(list[dict])は原OHLC、session(str)は場、contract(tuple)は限月、tail_missing(int)は末尾欠枠。
        返り値: tuple[list[dict],dict]は15列と独立銀行品質。欠枠解除後有効当足は数値の初足にする。
        """
        changed = self.contract is not None and self.contract != contract
        if changed:
            self.clear()
        self.contract = contract
        rows, previous_index, previous_key, clears = [], None, None, int(changed)
        for frame in frames:
            index, key = frame["index"], (frame["confirm"], frame["confirm_line"])
            if frame["minutes"] != 3 or previous_index is not None and index <= previous_index:
                raise ValueError("3分足番号順が不正")
            if frame["publish"] and (frame["confirm"] < frame["end"] or previous_key is not None and key < previous_key):
                raise ValueError("公開時計又は順序が不正")
            if index != (0 if previous_index is None else previous_index + 1) or frame["missing"] or not N.valid_ohlc(frame):
                self.clear()
                clears += 1
            atr = hist = None
            if N.valid_ohlc(frame):
                if self.previous is not None:
                    close = self.previous["close"]
                    atr = self.average.add(max(frame["high"] - frame["low"], abs(frame["high"] - close), abs(frame["low"] - close)))
                hist = self.center.add(frame["close"])["macd_hist"]
                self.previous = deepcopy(frame)
            rows.append({"場": session, **N.source(frame), "atr": atr, "macd_hist": hist})
            previous_index = index
            if frame["publish"]:
                previous_key = key
        if tail_missing:
            self.clear()
            clears += 1
        return rows, {"場": session, "時間足分": 3, "入力足数": len(rows),
            "ATR準備足数": sum(row["atr"] is not None for row in rows),
            "MACDヒスト準備足数": sum(row["macd_hist"] is not None for row in rows),
            "clear数": clears, "尾部完全欠枠": tail_missing}


# ----------------------------------------
# 主の二乗総和式を使わず、中心偏差と各予測残差の二乗和から回帰を作る。


def ols(values: list[float]) -> dict:
    """20終値の中心偏差からOLSと標本内R2を精密計算する。

    引数: values(list[float])は当足を含む古い順の20終値。
    返り値: dictは主保存schemaの全精密値。R2は残差二乗和から計算する。
    """
    ready = len(values) == 20 and all(finite(value) for value in values)
    dxy = dyy = slope = intercept = syy = sse = r2 = half = None
    if ready:
        ys = [Fraction(value) for value in values]
        mean_x, mean_y = Fraction(19, 2), sum(ys) / 20
        dx = [Fraction(index) - mean_x for index in range(20)]
        dy = [value - mean_y for value in ys]
        sxx = sum(value * value for value in dx)
        sxy = sum(x * y for x, y in zip(dx, dy, strict=True))
        syy = sum(value * value for value in dy)
        slope = sxy / sxx
        intercept = mean_y - slope * mean_x
        sse = sum((value - (intercept + slope * index)) ** 2 for index, value in enumerate(ys))
        dxy, dyy = 20 * sxy, 20 * syy
        if syy > 0:
            r2 = 1 - sse / syy
            half = r2 - Fraction(1, 2)
    return {"回帰準備": ready, "回帰点数": len(values), "Dxx": 13300,
        "Dxy": exact(dxy), "Dyy": exact(dyy), "傾き": exact(slope), "切片": exact(intercept),
        "全平方和": exact(syy), "残差平方和": exact(sse), "R2": exact(r2), "R2準備": r2 is not None,
        "傾き符号": int(slope > 0) - int(slope < 0) if slope is not None else None,
        "R2半分差": exact(half), "R2半分比較符号": int(half > 0) - int(half < 0) if half is not None else None}


def pure_signal(row: dict, policy: str = "L0") -> dict:
    """新原価格Pを当時の執行に必要な13列へ限定する。

    引数: row(dict)は発動IDを持つ原P、policy(str)はL0/L1/L2。
    返り値: dictは回帰詳細・未来ラベルを含まない順行純信号。
    """
    if policy not in POLICIES or row["役割"] != "順行" or row["side"] not in (-1, 1):
        raise ValueError("順行の回帰三候補だけです")
    if row["方向"] != ("買い" if row["side"] == 1 else "売り"):
        raise ValueError("実方向と表示が不一致")
    result = {key: deepcopy(row[key]) for key in SIGNAL_FIELDS if key not in ("イベントID", "入口ID", "bb_mean")}
    return {**result, "イベントID": row["発動ID"] + "_" + policy, "入口ID": "3分_" + policy, "bb_mean": None}


def verdicts(context: dict, side: int) -> dict:
    """方向・勢いの共通条件へR2の準備と半分境界を順に加える。

    引数: context(dict)は当時の窓数値、side(int)は買1/売-1。
    返り値: dictは理由を含む全三採否。許容差をgateに使わない。
    """
    base = list(context["M除外理由"])
    base.extend(reason for condition, reason in ((context["時間条件可"], "要求時間条件外"),
        (context["確認遅延条件可"], "確認遅延30秒超")) if not condition)
    regression, change = context["OLS20"], context["MACDヒスト変化"]
    if regression["傾き符号"] is None or side * regression["傾き符号"] <= 0:
        base.append("OLS20傾き実方向strict正不成立")
    if not finite(change) or side * change <= 0:
        base.append("MACDヒスト一足差実方向strict正不成立")
    result = {}
    for policy in POLICIES:
        reasons = list(base)
        if policy != "L0" and not regression["R2準備"]:
            reasons.append("R2数値未準備")
        if policy == "L2" and regression["R2半分比較符号"] not in (0, 1):
            reasons.append("R2半分以上不成立")
        result[policy] = {"採用": not reasons, "理由": reasons or ["終値突破と回帰複合採用"], "同時競合": False}
    return result


def generate(frames: list[dict], session: str, cutoff: float, deadline: float, config: dict) -> dict:
    """有効連続区間の末尾を直接sliceし、旧高安と新20終値から全Pを作る。

    引数: frames(list[dict])は3分数値、session(str)は場、cutoff/deadline(float)は停止/強制、config(dict)は固定条件。
    返り値: dictはsignals/raw/decisions/quality。主のdeque更新は再用しない。
    """
    if any(row["場"] != session or row["minutes"] != 3 for row in frames):
        raise ValueError("当場の3分数値だけです")
    projected, segment, records = [frame_projection(row) for row in frames], [], []
    counts = {"足数": 0, "価格20窓準備足数": 0, "共通M準備足数": 0, "局所窓解除足数": 0}
    for position, frame in enumerate(projected):
        prior_input = projected[position - 1] if position else None
        if prior_input is not None and prior_input["index"] >= frame["index"]:
            raise ValueError("3分足番号はstrict昇順だけです")
        valid = bool(frame["publish"] and N.valid_ohlc(frame) and frame["missing"] == 0
            and frame["end"] - frame["start"] == 180 and frame["confirm"] >= frame["end"])
        linked = prior_input is None or (frame["index"] - prior_input["index"] == 1
            and prior_input["end"] == frame["start"]
            and (prior_input["confirm"], prior_input["confirm_line"]) <= (frame["confirm"], frame["confirm_line"]))
        if not valid or not linked:
            segment = []
            counts["局所窓解除足数"] += 1
        before = segment[-20:]
        ready = valid and len(before) == 20
        previous = before[-1] if before else None
        regression = ols([row["close"] for row in before[1:]] + [frame["close"]] if ready else [])
        change = frame["macd_hist"] - previous["macd_hist"] if previous is not None and finite(frame["macd_hist"]) and finite(previous["macd_hist"]) else None
        reasons = [reason for condition, reason in ((ready, "同場21連続公開価格足未準備"),
            (regression["回帰準備"], "OLS20数値未準備"),
            (finite(frame["atr"]) and frame["atr"] > 0, "現在ATR14有限正未準備"),
            (finite(change), "同場隣接公開MACDヒスト未準備")) if not condition]
        counts["足数"] += 1
        counts["価格20窓準備足数"] += int(ready)
        counts["共通M準備足数"] += int(not reasons)
        if ready:
            high, low = max(row["high"] for row in before), min(row["low"] for row in before)
            context = {**deepcopy(frame), "時間足分": 3, "価格準備": True,
                "前20足番号": [row["index"] for row in before],
                "回帰20足番号": [row["index"] for row in before[1:]] + [frame["index"]],
                "直前最高H": high, "直前最安L": low, "前3分参照": frame_projection(previous),
                "OLS20": regression, "MACDヒスト変化": change, "bb_mean": None,
                "共通M準備": not reasons, "M除外理由": reasons,
                "時間条件可": frame["confirm"] < cutoff and deadline - frame["confirm"] >= config["残り時間下限分"] * 60,
                "確認遅延条件可": frame["confirm"] - frame["end"] <= config["確認遅延上限秒"]}
            for side in (1, -1):
                if not (frame["close"] > high if side == 1 else frame["close"] < low):
                    continue
                identifier = f"NK225_{session}_3分_回帰突破_{frame['index']:04d}_{side}"
                records.append({**deepcopy(context), "入口系統": "T価格突破", "役割": "順行", "side": side,
                    "方向": "買い" if side == 1 else "売り", "発動ID": identifier, "QイベントID": identifier,
                    "イベントID": identifier, "入口ID": "3分_T価格突破", "要求時計秒": frame["confirm"],
                    "要求原板行": frame["confirm_line"], "足終了時計秒": frame["end"],
                    "確認遅延秒": frame["confirm"] - frame["end"], "期限時計秒": deadline,
                    "残り分_判断時": (deadline - frame["confirm"]) / 60,
                    "先着評価対象": bool(context["時間条件可"] and context["確認遅延条件可"]),
                    "戦略判定": verdicts(context, side)})
        if valid:
            segment.append(frame)
    for policy in POLICIES:
        conflicts = defaultdict(list)
        for row in records:
            if row["戦略判定"][policy]["採用"]:
                conflicts[row["要求時計秒"], row["要求原板行"]].append(row)
        for values in conflicts.values():
            if len(values) > 1:
                for row in values:
                    row["戦略判定"][policy] = {"採用": False, "理由": ["同判断複数信号見送り"], "同時競合": True}
    signals = {"3分_" + policy: [] for policy in POLICIES}
    for row in records:
        for policy in POLICIES:
            if row["戦略判定"][policy]["採用"]:
                signals["3分_" + policy].append({**deepcopy(row), "入口ID": "3分_" + policy, "戦略": policy,
                    "複合判定": deepcopy(row["戦略判定"][policy]), "イベントID": row["発動ID"] + "_" + policy})
    quality = {"場": session, "時間足分": 3, **counts, "原価格発動数": len(records),
        "先着評価対象外数": sum(not row["先着評価対象"] for row in records),
        "戦略別発動数": {key: len(values) for key, values in signals.items()},
        "戦略採否理由別": {policy: dict(Counter(reason for row in records for reason in row["戦略判定"][policy]["理由"])) for policy in POLICIES}}
    return {"場": session, "signals": signals, "raw": records, "decisions": records, "quality": quality}


# ----------------------------------------
# 原8列再算、正本floatの厳密再現、再算数値の判断影響を分けて証明する。


def dependency_pins() -> dict:
    """固定独立足・中心化MACD・直接先着・追尾の全依存を識別する。

    引数: なし。
    返り値: dict[str,str]はROOT相対pathと現在SHA。41主コードを数式依存にしない。
    """
    paths = {"scripts/発動値幅継続/状態独立確認.py", "scripts/OBV反転/状態独立確認.py",
        "scripts/終値位置/追尾独立確認.py"}
    return dict(sorted({**Y.dependency_pins(), **{name: V.sha(ROOT / name) for name in paths}}.items()))


def shared_bundle(audit: Audit) -> dict:
    """29の保存全数値を出典照合し、3分15列だけを研究入力へ渡す。

    引数: audit(Audit)は圧縮・展開SHAとサイズの比較先。
    返り値: dictはlowerと元数値展開SHA。旧P/旧case/旧取引を読み込まない。
    """
    rows, digest = Y.saved_rows(INDICATOR_STUDY, INDICATOR_WORK, "全指標.jsonl.gz", audit)
    lower = defaultdict(list)
    for row in rows:
        if row["minutes"] == 3:
            lower[row["場"]].append(frame_projection(row))
    return {"lower": lower, "共有3分全指標展開SHA256": digest}


def references(study: Path, audit: Audit) -> None:
    """指標参照だけを固定29正本へ結び、旧入口を新発動の正本にしない。

    引数: study(Path)は41、audit(Audit)は比較先。
    返り値: None。各証明と全数値明細の現在指紋を検査する。
    """
    anchor = "353143ea3f7a626736bf44551d17ba6e22b8bfd76ee40e2f4f9b0c190736f48a"
    audit.check("29固定正本", V.sha(INDICATOR_STUDY / "固定.json"), anchor)
    for name, digest in V.read(INDICATOR_STUDY / "固定.json")["ファイルSHA256"].items():
        audit.check("29固定現在:" + name, V.sha(ROOT / name), digest)
    ref = V.read(study / "指標参照.json")
    audit.check("数値参照試行", ref["参照試行"], "00029")
    audit.check("数値参照固定", ref["旧固定SHA256"], anchor)
    audit.check("数値複製なし", ref["大明細複製"], False)
    expected_names = {"固定.json", "条件.json", "結果.json", "作業成果物.json", "独立監査.json",
        "状態独立確認.json", "追尾独立確認.json", "入力台帳.json"}
    audit.check("数値参照証明集合", set(ref["文書と証明"]), expected_names)
    for name, item in ref["文書と証明"].items():
        audit.check("数値参照正本:" + name, (ROOT / item["パス"]).resolve(), (INDICATOR_STUDY / name).resolve())
        audit.check("数値参照SHA:" + name, item["SHA256"], V.sha(INDICATOR_STUDY / name))
    for name in ("独立監査.json", "状態独立確認.json", "追尾独立確認.json"):
        proof = V.read(INDICATOR_STUDY / name)
        audit.check("数値旧証明成功:" + name, (proof["全件一致"], proof["不一致数"]), (True, 0))
    expected = [row for row in V.read(INDICATOR_STUDY / "作業成果物.json")["ファイル"]
        if Path(row["パス"]).name == "全指標.jsonl.gz"]
    audit.check("数値共有集合", ref["共有明細"], expected)
    for item in expected:
        path = ROOT / item["パス"]
        audit.check("数値圧縮SHA", V.sha(path), item["圧縮SHA256参考"])
        audit.check("数値圧縮bytes", path.stat().st_size, item["圧縮バイト"])


def guarded_inputs(study: Path, work: Path, audit: Audit) -> tuple[dict, dict, dict, Path]:
    """非損益主準備と三案・費用・入力・使用数値版を市場入力前に照合する。

    引数: study/work(Path)は41保存先、audit(Audit)は比較先。
    返り値: tupleは条件/解決台帳/主準備/台帳path。差があればcache前に停止する。
    """
    config, (manifest, resolved) = V.read(study / "条件.json"), G.resolved_manifest(study)
    references(study, audit)
    old, fee = V.read(INDICATOR_STUDY / "条件.json"), V.read(EXIT_STUDY / "条件.json")
    for key in ("対象", "時間足分", "逆行pt", "順行pt", "残り時間下限分", "確認遅延上限秒",
            "入口支持", "費用支持", "目標確認率", "間引き必要件数", "分割"):
        audit.check("固定評価尺度:" + key, config[key], old[key])
    for key in ("運用", "必須追尾"):
        audit.check("固定33費用出口:" + key, config[key], fee[key])
    audit.check("三入口", config["戦略"], list(POLICIES))
    audit.check("三XF", config["運用組合せ"], [{"戦略": p, "出口ID": "XF"} for p in POLICIES])
    master = V.read(work / "準備点検.json")
    expected = {"ラベル計算": False, "損益計算": False, "全66場既使用": True,
        "条件SHA256": V.sha(study / "条件.json"), "入力台帳SHA256": V.sha(study / "入力台帳.json"),
        "参照台帳SHA256": V.sha(resolved), "純信号whitelist": list(SIGNAL_FIELDS),
        "指標参照SHA256": V.sha(study / "指標参照.json")}
    for name, value in expected.items():
        audit.check("主準備:" + name, master[name], value)
    paths = {"scripts/回帰突破/" + name for name in ("検証.py", "入口.py", "運用.py")}
    audit.check("主三コード集合", set(master["コードSHA256"]), paths)
    for name, digest in master["コードSHA256"].items():
        audit.check("主準備現在:" + name, V.sha(ROOT / name), digest)
    audit.check("主66場順", [row["場"] for row in master["準備"]], [entry["session"] for entry in manifest["entries"]])
    if audit.mismatches:
        raise ValueError("入力/主準備/数値参照に差があり市場入力前停止")
    return config, manifest, master, resolved


def reconstruct(manifest: dict, bundle: dict, config: dict) -> Any:
    """原8列の独立OHLC/ATR/Hから新突破と全回帰判定を別実装する。

    引数: manifest/bundle/config(dict)は予約台帳/29保存数値/条件。
    返り値: Anyは非先着・非運用の場別iterator。正本float定義と独立数値影響を区別する。
    """
    bank = NumericHistory(3)
    for entry in manifest["entries"]:
        session = entry["session"]
        start, finish, cutoff, deadline = S.G.times(session)
        data = G.observed(entry, manifest)
        formed = S.bars(data, session, 3, N.BareBars())
        tail = max(0, int((finish - start) // 180) - 1 - (formed[-1]["index"] if formed else -1))
        independent, quality = bank.build(formed, session, tuple(entry["in_session_contract_codes"]), tail)
        original = {row["index"]: row for row in bundle["lower"][session]}
        defined = [{**deepcopy(row), **{name: original[row["index"]][name] for name in ("atr", "macd_hist")}} for row in independent]
        selected = generate(defined, session, cutoff, deadline, config)
        alternate = generate(independent, session, cutoff, deadline, config)
        pure = [pure_signal(row, policy) for policy in POLICIES for row in selected["signals"]["3分_" + policy]]
        period = "学習" if session[:10] < config["分割"]["選択開始日"] else ("条件選択" if session[:10] < config["分割"]["後続開始日"] else "後続検査")
        yield {"場": session, "期間": period, "純信号": pure, "純信号内容SHA256": canonical_sha(pure),
            "純信号判断SHA256": canonical_sha([decision_signal(row) for row in pure]),
            "判定": selected["decisions"], "判定SHA256": canonical_sha(selected["decisions"]),
            "判定判断SHA256": canonical_sha(selected["decisions"]),
            "全3分投影SHA256": canonical_sha(defined), "3分投影足数": len(defined), "入力品質": selected["quality"],
            "_再算全3分": independent, "_正本数値定義全3分": defined, "_再算判断": alternate, "_銀行品質": quality}


def comparison_state(row: dict) -> dict:
    """数値許容とは別に固定する価格・符号・準備・採否の投影を作る。

    引数: row(dict)は一つの原価格P判定。
    返り値: dictはδH符号/M/全採否と回帰精密値。浮動差を採否へ流用しない。
    """
    change = row["MACDヒスト変化"]
    return {key: deepcopy(row[key]) for key in ("発動ID", "side", "要求時計秒", "要求原板行", "OLS20",
        "前20足番号", "回帰20足番号", "直前最高H", "直前最安L", "共通M準備", "M除外理由",
        "時間条件可", "確認遅延条件可", "戦略判定")} | {"MACD差符号": int(change > 0) - int(change < 0) if finite(change) else None}


def compare_preparation(main: dict, block: dict, bundle: dict, audit: Audit) -> dict:
    """全足数値の限定許容と、新発動・判断・正本整合SHAを別々に確認する。

    引数: main/block(dict)は主/独立場、bundle(dict)は29保存数値、audit(Audit)は比較先。
    返り値: dictは全数値・表現差・全P・三集合の要約。旧入口の同値を要求しない。
    """
    session, independent = block["場"], block["_再算全3分"]
    source = bundle["lower"][session]
    audit.check(session + ":原8列SOURCEと全ATR/H", independent, source)
    expected_record = {key: value for key, value in block.items() if not key.startswith("_")}
    audit.check(session + ":正本定義の全P回帰と全採否", main, expected_record)
    audit.check(session + ":全正本定義厳密JSON値", main == expected_record, True)
    original_states = [comparison_state(row) for row in block["判定"]]
    alternate_states = [comparison_state(row) for row in block["_再算判断"]["decisions"]]
    for actual, alternate in zip(block["判定"], block["_再算判断"]["decisions"], strict=True):
        audit.check(actual["発動ID"] + ":再算数値差:MACDヒスト変化", alternate["MACDヒスト変化"], actual["MACDヒスト変化"])
    audit.check(session + ":独立数値による全P符号準備採否strict", alternate_states, original_states)
    same = alternate_states == original_states
    audit.check(session + ":独立数値の判断影響なし", same, True)
    audit.check(session + ":独立数値の全足品質", block["_再算判断"]["quality"], block["入力品質"])
    ids = {policy: {row["イベントID"][:-3] for row in main["純信号"] if row["入口ID"] == "3分_" + policy} for policy in POLICIES}
    audit.check(session + ":L1冗長準備はL0同集合", ids["L1"], ids["L0"])
    audit.check(session + ":L2subsetL1", ids["L2"] <= ids["L1"], True)
    raw = {row["発動ID"]: row for row in main["判定"]}
    for signal in main["純信号"]:
        policy = signal["入口ID"].removeprefix("3分_")
        audit.check(signal["イベントID"] + ":純13列集合", set(signal), set(SIGNAL_FIELDS))
        audit.check(signal["イベントID"] + ":元発動現ATR含む厳密13値", signal == pure_signal(raw[signal["イベントID"][:-3]], policy), True)
    differences = {name: [abs(a[name] - b[name]) for a, b in zip(independent, source, strict=True)
        if finite(a[name]) and finite(b[name]) and a[name] != b[name]] for name in ("atr", "macd_hist")}
    return {"場": session, "期間": block["期間"], **{p + "登録数": len(ids[p]) for p in POLICIES},
        "原価格発動数": len(main["判定"]), "3分投影足数": len(source),
        **{name + "表現差足数": len(values) for name, values in differences.items()},
        **{name + "最大絶対差": max(values, default=0.0) for name, values in differences.items()},
        "再算数値判断不一致場": int(not same), "全3分投影SHA256": block["全3分投影SHA256"],
        "独立再算全3分内容SHA256": canonical_sha(independent), "全判定SHA256": block["判定SHA256"]}


def numeric_summary(stages: list[dict]) -> dict:
    """全足数値の表現差と全原Pにおける判断影響を別集計する。

    引数: stages(list[dict])は場別準備要約。
    返り値: dictは全足・原P件数・限定許容値と厳密判断差の件数。
    """
    return {"新3分全数値照合足数": sum(r["3分投影足数"] for r in stages),
        "原価格発動数": sum(r["原価格発動数"] for r in stages),
        "独立数値判断不一致場数": sum(r["再算数値判断不一致場"] for r in stages),
        **{"独立" + name + "表現差足数": sum(r[name + "表現差足数"] for r in stages) for name in ("atr", "macd_hist")},
        **{"独立" + name + "最大絶対差": max((r[name + "最大絶対差"] for r in stages), default=0.0) for name in ("atr", "macd_hist")}}


def proof_base(study: Path, work: Path, resolved: Path, master: dict, audit: Audit) -> dict:
    """主版・入力・独立依存と数値責任の三段階を結ぶ。

    引数: study/work/resolved(Path)は保存/台帳、master(dict)は主準備、audit(Audit)は比較先。
    返り値: dictは準備/正式共通proof。旧入口証明に新Pの責務を委ねない。
    """
    return {"全件一致": audit.mismatches == 0, "照合項目数": audit.count, "不一致数": audit.mismatches,
        "不一致": audit.errors, "コードSHA256": V.sha(Path(__file__)),
        "追尾コードSHA256": V.sha(Path(__file__).with_name("追尾独立確認.py")), "依存コードSHA256": dependency_pins(),
        "主準備SHA256": V.sha(work / "準備点検.json"), "主コードSHA256": master["コードSHA256"],
        "条件SHA256": V.sha(study / "条件.json"), "入力台帳SHA256": V.sha(study / "入力台帳.json"),
        "参照入力台帳SHA256": V.sha(resolved), "解決入力台帳SHA256": V.sha(resolved),
        "指標参照SHA256": V.sha(study / "指標参照.json"),
        "厳密範囲": "原8列由来SOURCE/中心偏差OLS全分数/新P/時点/全採否/純13原値は厳密。全ATR/Hの別算値はabs1e-10/rel0、ATR正有効/D整数・H符号と全原PのδH符号/M/採否はstrict。検算済み保存正本floatを定義とする全3分/判定SHAと、独立再算値の生SHAは区別する。",
        "数値許容": {"対象": ["atr", "macd_hist", "MACDヒスト変化"], "絶対許容": 1e-10, "相対許容": 0,
            "採否epsilon": False, "正本定義SHAと独立生数値SHAを区別": True}}


def prepare(study: Path, work: Path) -> dict:
    """root起動の非損益準備で全原足/数値/回帰と新三入口を検算する。

    引数: study/work(Path)は41保存先。
    返り値: dictはラベル・運用・PnL計算を呼ばない独立準備証明。
    """
    audit, initial = Audit(), V.sha(Path(__file__))
    config, manifest, master, resolved = guarded_inputs(study, work, audit)
    bundle, stages = shared_bundle(audit), []
    for main_record, block in zip(master["準備"], reconstruct(manifest, bundle, config), strict=True):
        stages.append(compare_preparation(main_record, block, bundle, audit))
        print(json.dumps({"場": block["場"], "独立準備": "原3分ATR/H・中心偏差OLS・新P・全L", "不一致数": audit.mismatches}, ensure_ascii=False), flush=True)
    audit.check("独立実行中コード不変", V.sha(Path(__file__)), initial)
    proof = {**proof_base(study, work, resolved, master, audit), "ラベル計算": False, "損益計算": False,
        "全66場既使用": True, "場別準備": stages, **numeric_summary(stages),
        "方針別登録数": {p: sum(r[p + "登録数"] for r in stages) for p in POLICIES},
        "共有3分全指標展開SHA256": bundle["共有3分全指標展開SHA256"],
        "検証範囲": "全8列入力から3分OHLC/ATR14/中心化MACDヒストを再算。中心偏差と残差二乗OLS、新21足突破、三採否と純13を独立構築。正本floatのSHA整合と再算数値の全符号/採否影響を分けて検査する。",
        "限界": "非先着/非運用/非PnL。旧29は数値出典だけ、旧188入口/旧case/旧全属性対照を流用しない。全66場既使用。"}
    (work / "独立準備点検.json").write_text(json.dumps(proof, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({key: proof[key] for key in ("全件一致", "照合項目数", "不一致数", "原価格発動数", "方針別登録数")}, ensure_ascii=False))
    return proof


def check_prepared(study: Path, work: Path, resolved: Path, master: dict, audit: Audit) -> None:
    """成功した独立準備と全固定指紋を正式市場入力前に要求する。

    引数: study/work/resolved(Path)は保存/台帳、master(dict)は主準備、audit(Audit)は比較先。
    返り値: None。古版・未完・差ありは停止する。
    """
    prepared, expected = V.read(work / "独立準備点検.json"), proof_base(study, work, resolved, master, audit)
    for key in ("コードSHA256", "追尾コードSHA256", "依存コードSHA256", "主準備SHA256", "主コードSHA256",
            "条件SHA256", "入力台帳SHA256", "参照入力台帳SHA256", "指標参照SHA256"):
        audit.check("準備bind:" + key, prepared[key], expected[key])
    for key, value in {"全件一致": True, "不一致数": 0, "不一致": [], "ラベル計算": False, "損益計算": False}.items():
        audit.check("準備成功:" + key, prepared[key], value)
    for name, digest in V.read(study / "固定.json")["ファイルSHA256"].items():
        audit.check("正式固定現在:" + name, V.sha(ROOT / name), digest)
    if audit.mismatches:
        raise ValueError("準備/固定/現版に差があり正式市場入力前停止")


def run(study: Path, work: Path) -> dict:
    """正式後に全新P/三採否と全caseの約定後125250を直接検算する。

    引数: study/work(Path)は41保存先。
    返り値: dictは状態証明。新規受付/会計と追尾の別証明へSHA接続する。
    """
    if not (study / "固定.json").exists() or not (study / "結果.json").exists():
        raise ValueError("root固定・正式完了後だけです")
    audit, initial = Audit(), V.sha(Path(__file__))
    config, manifest, master, resolved = guarded_inputs(study, work, audit)
    check_prepared(study, work, resolved, master, audit)
    bundle = shared_bundle(audit)
    names = ("回帰判定", "入口事例", "全運用詳細", "追尾")
    saved, hashes, grouped = {}, {}, {name: defaultdict(list) for name in names}
    for name in names:
        saved[name], hashes[name] = Y.saved_rows(study, work, name + ".jsonl.gz", audit)
        for row in saved[name]:
            grouped[name][row["場"]].append(row)
    artifact_names = {Path(row["パス"]).name for row in V.read(study / "作業成果物.json")["ファイル"]}
    audit.check("新四成果物集合", artifact_names, {name + ".jsonl.gz" for name in names})
    pairs = [(row["場"], row["候補ID"]) for row in saved["全運用詳細"]]
    audit.check("全場候補一意", len(pairs), len(set(pairs)))
    audit.check("全3x66", set(pairs), {(entry["session"], cid) for entry in manifest["entries"] for cid in OPERATIONS})
    audit.check("全case一意", len(saved["入口事例"]), len({row["イベントID"] for row in saved["入口事例"]}))
    stages, counts = [], {policy: 0 for policy in POLICIES}
    entries = {row["session"]: row for row in manifest["entries"]}
    for main_record, block in zip(master["準備"], reconstruct(manifest, bundle, config), strict=True):
        stages.append(compare_preparation(main_record, block, bundle, audit))
        session, period = block["場"], block["期間"]
        audit.check(session + ":正式全回帰判定", grouped["回帰判定"][session], [{"期間": period, **row} for row in block["判定"]])
        audit.check(session + ":正式回帰全値厳密", grouped["回帰判定"][session] == [{"期間": period, **row} for row in block["判定"]], True)
        cases = {row["イベントID"]: row for row in grouped["入口事例"][session]}
        audit.check(session + ":全case純集合", set(cases), {row["イベントID"] for row in block["純信号"]})
        quotes = normal_columns(entries[session], manifest)
        _, _, cutoff, deadline = S.G.times(session)
        for signal in block["純信号"]:
            direct = label_direct(quotes, signal, cutoff, deadline)
            expected = {**deepcopy(signal), "期間": period,
                "要求時計JST": datetime.fromtimestamp(signal["要求時計秒"], timezone(timedelta(hours=9))).isoformat(),
                "元価格発動ID": signal["イベントID"][:-3], "元価格side": signal["side"], **direct}
            audit.check(signal["イベントID"] + ":全新case直接BBO先着", cases.get(signal["イベントID"]), expected)
            audit.check(signal["イベントID"] + ":全case厳密値", cases.get(signal["イベントID"]) == expected, True)
            counts[signal["入口ID"].removeprefix("3分_")] += 1
        for detail in grouped["全運用詳細"][session]:
            audit.check(detail["候補ID"] + session + ":期間", detail["品質"]["期間"], period)
        print(json.dumps({"場": session, "独立状態": "原3分ATR/H・中心偏差OLS・全L・全新case直接先着", "不一致数": audit.mismatches}, ensure_ascii=False), flush=True)
    result = V.read(study / "結果.json")
    for key, expected in {"全66場既使用": True, "入口評価数": 3, "運用候補数": 3, "現方針運用候補数": 3,
            "入口125250評価の変更": False, "表示固定ID": list(OPERATIONS)}.items():
        audit.check("正式結果:" + key, result[key], expected)
    audit.check("全case数", len(saved["入口事例"]), sum(counts.values()))
    audit.check("L1冗長準備全件", counts["L1"], counts["L0"])
    audit.check("独立実行中コード不変", V.sha(Path(__file__)), initial)
    proof = {**proof_base(study, work, resolved, master, audit), "場別準備": stages, **numeric_summary(stages),
        "方針別case数": counts, "全先着直接照合件数": sum(counts.values()), "方針別先着直接照合件数": counts,
        "保存回帰判定数": len(saved["回帰判定"]), "保存入口事例数": len(saved["入口事例"]),
        "保存運用詳細数": len(saved["全運用詳細"]), "保存追尾数": len(saved["追尾"]),
        "成果物照合": {name + ".jsonl.gz": {"展開内容SHA256": hashes[name], "行数": len(saved[name])} for name in names},
        **{name + "展開SHA256": digest for name, digest in hashes.items()},
        "共有3分全指標展開SHA256": bundle["共有3分全指標展開SHA256"],
        "結果SHA256": V.sha(study / "結果.json"), "固定SHA256": V.sha(study / "固定.json"),
        "独立準備SHA256": V.sha(work / "独立準備点検.json"),
        "検証範囲": "原8列3分OHLC/ATR14/中心化H、中心偏差OLS/全新P/三採否/純13を検算。全新caseを原正常BBOの最初+1秒新規から125/250/空白/期限へ直接走査。正本数値SHA整合と独立数値のstrict符号/採否影響を分離。",
        "限界": "旧入口/旧先着/旧全属性対照は流用しない。運用の受付/最初約定/Decimalは別会計、全実保有と最初返済要求は別追尾。全66場既使用。"}
    (work / "状態独立確認.json").write_text(json.dumps(proof, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({key: proof[key] for key in ("全件一致", "照合項目数", "不一致数", "方針別case数")}, ensure_ascii=False))
    return proof


def main() -> None:
    """root許可による非損益準備又は固定後正式検算を明示起動する。

    引数: なし。--study/--work/--prepare/--実行許可を読む。
    返り値: None。無指定・不一致は非0終了する。
    """
    parser = argparse.ArgumentParser(description="00041新終値突破と中心偏差OLSの独立検算")
    parser.add_argument("--study", type=Path, default=STUDY)
    parser.add_argument("--work", type=Path, default=WORK)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--prepare", action="store_true")
    modes.add_argument("--実行許可", action="store_true")
    args = parser.parse_args()
    proof = prepare(args.study.resolve(), args.work.resolve()) if args.prepare else run(args.study.resolve(), args.work.resolve())
    if not proof["全件一致"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
