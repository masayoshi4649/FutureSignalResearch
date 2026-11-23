"""00031の原OHLC・CCI厳密境界・上位BB幅と全採否を独立再構成する。"""

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
STUDY = ROOT / "study/00031_CCI持続と上位BB幅"
WORK = ROOT / "work/CCI突破/00031"
POLICIES = ("C0", "C1")
MANIFEST_SHA = "680b831ee6bef1ec1cf49dc6283931f5b0ca9611f15f5c19d81af6e4738aaf9b"


def helper(path: Path, name: str) -> Any:
    """固定済みの独立足・ATR・照合補助だけを読み込む。

    引数: path (Path) は独立補助、name (str) はモジュール識別。
    返り値: Any は補助。31主の指標/入口/運用をimportしない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


B = helper(ROOT / "scripts/一目基準線/状態独立確認.py", "CCI突破の固定独立足と比較")
T = helper(ROOT / "scripts/異種発動/追尾独立確認.py", "CCI突破の固定独立追尾の依存版")
S, V, P, SOURCE_FIELDS = B.S, B.V, B.P, B.SOURCE_FIELDS
Audit = B.Audit


# ----------------------------------------
# CCIは原H/L/Cの各値から分数へ写し、同じ20本の平均と平均偏差で計算する。

def typical_price(frame: dict) -> Fraction:
    """原H/L/Cを個別に正確分数へ変換して典型価格を作る。

    引数: frame (dict) は有限有効OHLC。
    返り値: Fraction は(H+L+C)/3。floatのTPを再びFractionへ写す計算ではない。
    """
    return (Fraction(frame["high"]) + Fraction(frame["low"]) + Fraction(frame["close"])) / 3


def cci20(frames: list[dict]) -> dict:
    """直近20本のTPと同一窓平均偏差からCCIを別走査で厳密計算する。

    引数: frames (list[dict]) は切断済み履歴。末尾20本だけを使う。
    返り値: dict はTP/平均/MD/CCIのFraction又はNone。MD0はCCI欠測。
    """
    if len(frames) < 20:
        return {"TP": None, "平均": None, "MD": None, "CCI": None}
    values = [typical_price(frame) for frame in frames[-20:]]
    mean = sum(values) / 20
    deviation = sum(abs(value - mean) for value in values) / 20
    result = (values[-1] - mean) * Fraction(200, 3) / deviation if deviation > 0 else None
    return {"TP": values[-1], "平均": mean, "MD": deviation, "CCI": result}


def bb20(frames: list[dict]) -> dict:
    """指定20終値の直接偏差和から平均・母標準偏差・絶対幅を求める。

    引数: frames (list[dict]) は20本窓。
    返り値: dict は表示平均/標準偏差/幅。未準備はNone。
    """
    if len(frames) != 20:
        return {"平均": None, "標準偏差": None, "幅": None}
    mean = sum(frame["close"] for frame in frames) / 20
    sd = math.sqrt(sum((frame["close"] - mean) ** 2 for frame in frames) / 20)
    return {"平均": mean, "標準偏差": sd, "幅": 4 * sd}


def variance20(frames: list[dict]) -> Fraction | None:
    """元20終値の正確平均から偏差二乗和を作る。

    引数: frames (list[dict]) は指定20本。
    返り値: Fraction|None は母分散。主の二乗平均差式を再利用しない。
    """
    if len(frames) != 20:
        return None
    values = [Fraction(frame["close"]) for frame in frames]
    mean = sum(values) / 20
    return sum((value - mean) ** 2 for value in values) / 20


def exact_width_change(previous: list[dict], current: list[dict]) -> tuple[int | None, int | None, int | None]:
    """同じ20本母分散の差からBB絶対幅の増減と既約分散差を求める。

    引数: previous/current (list[dict]) は前/現在の20本。
    返り値: tuple[int|None,int|None,int|None] は符号/分散差分子/分母。幅差ではない。
    """
    before, after = variance20(previous), variance20(current)
    if before is None or after is None:
        return None, None, None
    delta = after - before
    return int(delta > 0) - int(delta < 0), delta.numerator, delta.denominator


def cci_snapshot(frames: list[dict]) -> dict | None:
    """独立Fraction核をCCI20の保存属性へ投影する。

    引数: frames (list[dict]) は同場連続公開の原足履歴。
    返り値: dict|None は20本分の値/厳密数/同窓μ/MD/現在TP/出典。MD0も無効dictとして残す。
    """
    if len(frames) < 20:
        return None
    values = cci20(frames)
    value, mean, deviation, current = values["CCI"], values["平均"], values["MD"], values["TP"]
    return {"値": float(value) if value is not None else None,
        "分子": value.numerator if value is not None else None, "分母": value.denominator if value is not None else None,
        "平均分子": mean.numerator, "平均分母": mean.denominator, "MD分子": deviation.numerator, "MD分母": deviation.denominator,
        "現TP分子": current.numerator, "現TP分母": current.denominator,
        "足番号": [row["index"] for row in frames[-20:]], "有効": value is not None}


class NumericHistory:
    """3分ATR/当場CCIと、15分BB数値carryを独立の区間履歴で作る。"""

    def __init__(self, minutes: int) -> None:
        """尺度と未確定限月を保持し数値銀行を空にする。

        引数: minutes (int) は3又は15。
        返り値: None。
        """
        if minutes not in (3, 15):
            raise ValueError("3分又は15分だけ")
        self.minutes, self.contract = minutes, None
        self.clear()

    def clear(self) -> None:
        """同限月の価格数値銀行を解除する。

        引数: なし。
        返り値: None。CCIの局所履歴は毎場build内で初期化する。
        """
        self.absolute, self.bb_history = P.Indicators(), []

    def build(self, frames: list[dict], session: str, contract: tuple, tail_missing: int = 0) -> tuple[list[dict], dict]:
        """原足の欠枠と公開を別判定し、ATR/CCI又はBB全足を再構成する。

        引数: frames (list[dict]) は完全幅原OHLC、session (str) は当場、contract (tuple) は限月、
        tail_missing (int) は完全尾部欠枠。
        返り値: tuple[list[dict],dict] は保存形式の全数値足と品質。先着/運用を呼ばない。
        """
        changed = self.contract is not None and self.contract != contract
        if changed:
            self.clear()
        self.contract = contract
        output, local, prior_index, prior_key = [], [], None, None
        clears, local_clears = int(changed), 0
        for frame in frames:
            index, key = frame["index"], (frame["confirm"], frame["confirm_line"])
            if frame["minutes"] != self.minutes or prior_index is not None and index <= prior_index:
                raise ValueError("独立入力の尺度/番号順が不正")
            if frame["publish"] and (frame["confirm"] < frame["end"] or prior_key is not None and key < prior_key):
                raise ValueError("公開時点又は公開keyが不正")
            reasons = ["限月変更"] if changed and prior_index is None else []
            if index != (0 if prior_index is None else prior_index + 1):
                reasons.append("足番号欠枠")
            if frame["missing"]:
                reasons.append("欠枠")
            valid = B.valid_ohlc(frame)
            if not valid:
                reasons.append("OHLC不正")
            if any(reason != "限月変更" for reason in reasons):
                self.clear()
                clears += 1
            row = {"場": session, **B.source(frame), "atr": None, "価格数値入力可": valid, "銀行解除理由": reasons}
            if self.minutes == 3:
                row["atr"] = self.absolute.add(frame)["atr"] if valid else None
                local_reasons = list(reasons)
                if not frame["publish"]:
                    local_reasons.append("非公開足")
                if local_reasons:
                    local = []
                    local_clears += 1
                current, previous = None, None
                if valid and frame["publish"] and not frame["missing"]:
                    local.append(frame)
                    current, previous = cci_snapshot(local), cci_snapshot(local[:-1])
                row.update(CCI現=current, CCI前=previous,
                    CCI準備済=bool(current is not None and current["有効"] and previous is not None and previous["有効"]),
                    CCI解除理由=local_reasons)
            else:
                if valid:
                    self.bb_history.append({"場": session, **B.source(frame)})
                window = self.bb_history[-20:] if valid else []
                values, variance = bb20(window), variance20(window)
                row.update({"BB" + name: value for name, value in values.items()})
                row.update(BB分散分子=variance.numerator if variance is not None else None,
                    BB分散分母=variance.denominator if variance is not None else None,
                    BB窓出典=deepcopy(window), BB準備済=variance is not None)
            output.append(row)
            prior_index = index
            if frame["publish"]:
                prior_key = key
        if tail_missing:
            self.clear()
            clears += 1
        quality = {"場": session, "時間足分": self.minutes, "入力足数": len(output),
            "価格数値入力足数": sum(row["価格数値入力可"] for row in output), "数値clear数": clears,
            "ATR正準備足数": sum(B.finite(row["atr"]) and row["atr"] > 0 for row in output),
            "CCI現前準備足数": sum(row.get("CCI準備済", False) for row in output), "CCI局所clear数": local_clears,
            "BB数値準備足数": sum(row.get("BB準備済", False) for row in output), "尾部完全欠枠": tail_missing,
            "非公開数値更新数": sum(not row["publish"] and row["価格数値入力可"] for row in output)}
        return output, quality


# ----------------------------------------
# 前20価格は同場の区間配列から、上位asofは全候補の直接絞込みで求める。

EXACT_FIELDS = ("BB幅比較厳密符号", "BB分散差厳密分子", "BB分散差厳密分母")


def reference(row: dict | None) -> dict | None:
    """下位CCI又は上位BBの使用属性と公開元を保存する。

    引数: row (dict|None) は当場の参照足。
    返り値: dict|None は元足・数値・窓出典のsnapshot。未来ラベルを含まない。
    """
    if row is None:
        return None
    local = ("CCI現", "CCI前", "CCI準備済") if row["minutes"] == 3 else (
        "BB平均", "BB標準偏差", "BB幅", "BB分散分子", "BB分散分母", "BB窓出典", "BB準備済")
    return deepcopy({key: row[key] for key in ("場", *SOURCE_FIELDS, "atr", "価格数値入力可", *local)})


def upper_states(higher: list[dict], session: str) -> list[dict]:
    """各15分足の配列隣接を直接調べ、当場公開pairを構成する。

    引数: higher (list[dict]) は当場15分全数値足、session (str) は場。
    返り値: list[dict] は最新足候補ごとの出典/準備/理由/厳密幅差。良い古値へ戻さない。
    """
    if any(row["minutes"] != 15 or row["場"] != session for row in higher):
        raise ValueError("当場15分だけ")
    output = []
    for position, current in enumerate(higher):
        reasons = []
        previous = higher[position - 1] if position else None
        if previous is not None and previous["index"] + 1 != current["index"]:
            reasons.append("15分番号飛越")
        if current["missing"]:
            reasons.append("15分欠枠")
        if not current["publish"]:
            reasons.append("非公開15分")
        if not current["価格数値入力可"]:
            reasons.append("15分OHLC不正")
        prior = previous if not reasons and previous is not None and previous["publish"] and previous["価格数値入力可"] and not previous["missing"] else None
        ready = bool(prior is not None and prior["BB準備済"] and current["BB準備済"])
        if not ready:
            reasons.append("当場隣接公開15分BB未準備")
        exact = (None, None, None)
        if ready:
            exact = exact_width_change(prior["BB窓出典"], current["BB窓出典"])
        output.append({"場": session, **{key: current[key] for key in ("index", "end", "confirm", "confirm_line", "publish")},
            "上位参照": reference(current), "前上位参照": reference(prior), "上位ペア準備": ready,
            "上位ペア除外理由": reasons, **dict(zip(EXACT_FIELDS, exact))})
    return output


def decisions(context: dict, side: int) -> dict:
    """同一準備へ現前CCI厳密100超を課し、C1だけ上位幅増加を加える。

    引数: context (dict) は当時の全参照/準備、side (int) は実方向。
    返り値: dict はC0/C1採否。float表示や将来足を判定へ使わない。
    """
    base = list(context["M除外理由"])
    if not context["時間条件可"]:
        base.append("要求時間条件外")
    if not context["確認遅延条件可"]:
        base.append("確認遅延30秒超")
    for name in ("CCI現", "CCI前"):
        value = context[name]
        if value is None or not value["有効"] or side * Fraction(value["分子"], value["分母"]) <= 100:
            base.append(name + "実方向100超不成立")
    output = {}
    for policy in POLICIES:
        reasons = list(base)
        if policy == "C1" and context["BB幅比較厳密符号"] != 1:
            reasons.append("上位BB絶対幅strict拡大不成立")
        output[policy] = {"採用": not reasons, "理由": reasons or ["価格突破と複合条件採用"], "同時競合": False}
    return output


def generate(frames: list[dict], higher: list[dict], session: str, cutoff: float, deadline: float, config: dict) -> tuple[dict, dict]:
    """同場過去区間と公開候補の全走査から原突破と全C採否を列挙する。

    引数: frames/higher (list[dict]) は3/15分独立数値足、session (str) は場、
    cutoff/deadline (float) は停止/返済期限、config (dict) は固定31条件。
    返り値: tuple[dict,dict] は全純採用と全context/raw品質。先着/損益を呼ばない。
    """
    if any(row["minutes"] != 3 or row["場"] != session for row in frames):
        raise ValueError("当場3分だけ")
    higher_states = upper_states(higher, session)
    segment, contexts, raw, grouped = [], [], [], defaultdict(list)
    price_count = common_count = 0
    for position, current in enumerate(frames):
        key = current["confirm"], current["confirm_line"]
        eligible = [row for row in higher_states if row["publish"] and row["end"] <= current["end"] and
            (row["confirm"], row["confirm_line"]) <= key]
        upper = eligible[-1] if eligible else None
        upper_context = {name: deepcopy(upper[name]) if upper is not None else [] if name == "上位ペア除外理由" else
            False if name == "上位ペア準備" else None for name in
            ("上位参照", "前上位参照", "上位ペア準備", "上位ペア除外理由", *EXACT_FIELDS)}
        previous_index = frames[position - 1]["index"] if position else None
        continuous = current["publish"] and current["価格数値入力可"] and not current["missing"] and (
            current["index"] == (0 if previous_index is None else previous_index + 1))
        if not continuous:
            segment = []
        window = segment[-20:]
        ready = bool(len(window) == 20 and current["publish"] and current["価格数値入力可"])
        high = max(row["high"] for row in window) if ready else None
        low = min(row["low"] for row in window) if ready else None
        reasons = []
        if not ready:
            reasons.append("同場直前20公開価格足未準備")
        if not B.finite(current["atr"]) or current["atr"] <= 0:
            reasons.append("現在ATR正未準備")
        if not current["CCI準備済"]:
            reasons.append("同場CCI現前未準備")
        if not upper_context["上位ペア準備"]:
            reasons.append("当場最新公開15分BB現前未準備")
        context = {**deepcopy(current), **upper_context, "時間足分": 3, "価格準備": ready,
            "前20足番号": [row["index"] for row in window], "直前最高H": high, "直前最安L": low,
            "前3分参照": reference(window[-1]) if window else None, "共通M準備": not reasons, "M除外理由": reasons,
            "時間条件可": current["confirm"] < cutoff and deadline - current["confirm"] >= config["残り時間下限分"] * 60,
            "確認遅延条件可": current["confirm"] - current["end"] <= config["確認遅延上限秒"]}
        contexts.append(context)
        price_count += int(ready)
        common_count += int(not reasons)
        if ready:
            sides = ([1] if current["close"] > high else []) + ([-1] if current["close"] < low else [])
            for side in sides:
                event = f"NK225_{session}_3分_価格突破_{current['index']:04d}_{side}"
                record = {**deepcopy(context), "入口系統": "T価格突破", "役割": "順行", "side": side,
                    "方向": "買い" if side > 0 else "売り", "発動ID": event, "QイベントID": event, "イベントID": event,
                    "入口ID": "3分_T価格突破", "要求時計秒": current["confirm"], "要求原板行": current["confirm_line"],
                    "足終了時計秒": current["end"], "確認遅延秒": current["confirm"] - current["end"], "期限時計秒": deadline,
                    "残り分_判断時": (deadline - current["confirm"]) / 60,
                    "先着評価対象": bool(context["時間条件可"] and context["確認遅延条件可"]), "戦略判定": decisions(context, side)}
                raw.append(record)
                for policy in POLICIES:
                    if record["戦略判定"][policy]["採用"]:
                        grouped[policy, *key].append(record)
        if current["publish"] and current["価格数値入力可"] and not current["missing"]:
            segment.append(current)
    for (policy, _, _), same_key in grouped.items():
        if len(same_key) > 1:
            for record in same_key:
                record["戦略判定"][policy] = {"採用": False, "同時競合": True, "理由": ["同判断複数信号見送り"]}
    selected = {"3分_" + policy: [] for policy in POLICIES}
    for record in raw:
        for policy in POLICIES:
            if record["戦略判定"][policy]["採用"]:
                selected["3分_" + policy].append({**deepcopy(record), "入口ID": "3分_" + policy, "戦略": policy,
                    "複合判定": deepcopy(record["戦略判定"][policy]), "イベントID": record["発動ID"] + "_" + policy})
    return selected, {"場": session, "時間足分": 3, "足数": len(frames), "価格20窓準備足数": price_count,
        "共通M準備足数": common_count, "原価格発動数": len(raw), "全Q発動記録": raw, "複合context記録": contexts,
        "先着評価対象外数": sum(not row["先着評価対象"] for row in raw),
        "戦略別発動数": {name: len(rows) for name, rows in selected.items()},
        "戦略採否理由別": {policy: dict(Counter(reason for row in raw for reason in row["戦略判定"][policy]["理由"])) for policy in POLICIES}}


def reconstruct(manifest: dict, config: dict) -> Any:
    """原cacheから両尺度の独立足/数値と全C採否を期間順に再構成する。

    引数: manifest/config (dict) は既使用66台帳/固定31条件。
    返り値: Any は場別iterator。ラベル/約定/損益を計算しない。
    """
    banks = {size: NumericHistory(size) for size in (3, 15)}
    for entry in manifest["entries"]:
        session = entry["session"]
        start, finish, cutoff, deadline = S.G.times(session)
        data = observed(entry, manifest)
        frames, tails, qualities = {}, {}, []
        for size, bank in banks.items():
            formed = S.bars(data, session, size, B.BareBars())
            tail = max(0, int((finish - start) // (size * 60)) - 1 - (formed[-1]["index"] if formed else -1))
            frames[size], quality = bank.build(formed, session, tuple(entry["in_session_contract_codes"]), tail)
            tails[str(size)] = tail
            qualities.append(quality)
        signals, quality = generate(frames[3], frames[15], session, cutoff, deadline, config)
        phase = "学習" if session[:10] < config["分割"]["選択開始日"] else (
            "条件選択" if session[:10] < config["分割"]["後続開始日"] else "後続検査")
        yield {"場": session, "期間": phase, "価格足": frames, "指標品質": qualities, "入口品質": quality,
            "純入口": signals, "新規停止": cutoff, "期限": deadline,
            "入力品質": {"場": session, "正常板数": int(data["valid"].sum()),
                "確定足数": {str(size): sum(row["publish"] for row in rows) for size, rows in frames.items()}, "尾部欠枠": tails}}


# ----------------------------------------
# 主の入口・数値をimportせず、既使用66場の同じ原観測を独立足へ渡す。

def observed(entry: dict, manifest: dict) -> dict:
    """固定cacheの原順と場内非後退時計だけを取り出す。

    引数: entry/manifest (dict) は固定入力行/実台帳。
    返り値: dict は原8列。数量はCCI/BB/採否へ使わない。
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


def resolved_manifest(study: Path) -> tuple[dict, Path]:
    """入力pointerを正本28の同一既使用66場へ限定して解決する。

    引数: study (Path) は31正式先。
    返り値: tuple[dict,Path] は実台帳/正本パス。新11/5等へ展開しない。
    """
    pointer = V.read(study / "入力台帳.json")
    actual = (study / pointer["参照"]).resolve()
    canonical = ROOT / "study/00028_基準線復帰と上位一目の方向/入力台帳.json"
    if actual != canonical or pointer["SHA256"] != MANIFEST_SHA or V.sha(actual) != MANIFEST_SHA:
        raise ValueError("入力参照は固定28正本の66場に限定")
    manifest = V.read(actual)
    if len(manifest["entries"]) != 66 or len({row["session"] for row in manifest["entries"]}) != 66:
        raise ValueError("一意な既使用66場が必要")
    return manifest, actual


def guarded_inputs(study: Path, work: Path, audit: Audit) -> tuple[dict, dict, dict, Path]:
    """固定運用/pointerと主準備の版をcacheより前に確認する。

    引数: study/work (Path) は正式/作業先、audit (Audit) は記録。
    返り値: tuple[dict,dict,dict,Path] は条件/実台帳/主準備/解決台帳。
    """
    config = V.read(study / "条件.json")
    manifest, resolved = resolved_manifest(study)
    audit.check("事前二候補", config["戦略"], list(POLICIES))
    for name, expected in {"下位分": 3, "上位分": 15, "価格窓本数": 20, "CCI期間": 20,
            "CCI係数分子": 3, "CCI係数分母": 200, "CCI境界": 100, "BB期間": 20, "BB偏差倍率": 2}.items():
        audit.check("独立機械規約:" + name, config["CCI突破"][name], expected)
    old = V.read(ROOT / "study/00030_価格突破とBB幅と方向頻度/条件.json")
    for key in ("対象", "時間足分", "出口", "逆行pt", "順行pt", "残り時間下限分", "確認遅延上限秒", "運用",
            "必須追尾", "入口支持", "費用支持", "目標確認率", "間引き必要件数", "分割"):
        audit.check("継承運用尺度/費用/支持:" + key, config[key], old[key])
    master = V.read(work / "準備点検.json")
    audit.check("準備ラベルなし", master["ラベル計算"], False)
    audit.check("準備損益なし", master["損益計算"], False)
    audit.check("主準備条件", master["条件SHA256"], V.sha(study / "条件.json"))
    audit.check("主準備入力pointer", master["入力台帳SHA256"], V.sha(study / "入力台帳.json"))
    audit.check("主準備解決入力", master["参照台帳SHA256"], V.sha(resolved))
    allowed = {"scripts/CCI突破/" + name for name in ("検証.py", "入口.py", "指標.py")}
    audit.check("事前三主コード", set(master["コードSHA256"]), allowed)
    if set(master["コードSHA256"]) == allowed:
        for path, digest in master["コードSHA256"].items():
            audit.check("主準備コード現在:" + path, V.sha(ROOT / path), digest)
    audit.check("主66場順", [row["場"] for row in master["準備"]], [row["session"] for row in manifest["entries"]])
    if audit.mismatches:
        raise ValueError("固定条件/入力/主準備の不一致によりcache前停止")
    return config, manifest, master, resolved


def stage(block: dict) -> dict:
    """全context/rawを除いた当場の段階集計を返す。

    引数: block (dict) は独立再構成場。
    返り値: dict は期間付き小型品質。大列は主準備workへ残る。
    """
    return {"期間": block["期間"], **{key: value for key, value in block["入口品質"].items()
        if key not in ("全Q発動記録", "複合context記録")}}


def count_signals(block: dict) -> list[dict]:
    """各案の場別純採用と売買件数を集計する。

    引数: block (dict) は独立再構成場。
    返り値: list[dict] はC0/C1の純件数。仮約定/実参加とは別。
    """
    return [{"場": block["場"], "期間": block["期間"], "入口ID": key, "発動数": len(rows),
        "買い発動数": sum(row["side"] == 1 for row in rows), "売り発動数": sum(row["side"] == -1 for row in rows)}
        for key, rows in block["純入口"].items()]


def period_counts(counts: list[dict]) -> list[dict]:
    """固定C順と期間順で純採用の活動場/日/方向を集計する。

    引数: counts (list[dict]) は場別件数。
    返り値: list[dict] は期間集計。支持や結果を再選択しない。
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


def proof_base(study: Path, work: Path, resolved: Path, audit: Audit) -> dict:
    """主独立の準備・コード・条件・入力を一つの版へ結び付ける。

    引数: study/work/resolved (Path) は正式/作業/実台帳、audit (Audit) は照合記録。
    返り値: dict は共通proof。通常先着数値と会計は別監査。
    """
    master = V.read(work / "準備点検.json")
    return {"全件一致": audit.mismatches == 0, "照合項目数": audit.count, "不一致数": audit.mismatches,
        "不一致": audit.errors, "入力場数": 66, "全66場既使用": True,
        "コードSHA256": V.sha(Path(__file__)), "追尾コードSHA256": V.sha(Path(__file__).with_name("追尾独立確認.py")),
        "主コードSHA256": master["コードSHA256"], "主準備SHA256": V.sha(work / "準備点検.json"),
        "条件SHA256": V.sha(study / "条件.json"), "入力台帳SHA256": V.sha(study / "入力台帳.json"),
        "解決入力台帳SHA256": V.sha(resolved), "参照入力台帳SHA256": V.sha(resolved),
        "依存コードSHA256": dependency_pins(),
        "独立足補助SHA256": V.sha(ROOT / "scripts/一目基準線/状態独立確認.py"),
        "ATR照合": {"leaf数": audit.atr_count, "表現差数": audit.atr_repr_diff, "最大絶対差": audit.atr_max_abs,
            "追尾D整数差数": audit.atr_tick_diff, "許容": "abs1e-10/rel0と正有効/追尾D整数厳密"},
        "厳密照合": "ATR以外はCCIの元HLC/TP/同窓平均/MD/厳密分子分母と±100境界、上位BB表示/分散差、原価格/時点/出典/準備/採否を厳密比較。採否epsilonなし"}


def dependency_pins() -> dict:
    """独立補助の推移的importから旧コードのpath付き指紋を列挙する。

    引数: なし。
    返り値: dict[str,str] はROOT相対pathとSHA。自己/追尾は別キーでbindし、31主importを拒否する。
    """
    own = Path(__file__).resolve()
    paths, visited, queue = set(), set(), [B, T]
    while queue:
        module = queue.pop()
        if id(module) in visited:
            continue
        visited.add(id(module))
        filename = getattr(module, "__file__", None)
        if not filename:
            continue
        path = Path(filename).resolve()
        if path.suffix != ".py" or not path.is_relative_to((ROOT / "scripts").resolve()):
            continue
        if path.parent == own.parent:
            raise ValueError("独立状態へ31主や他の同階層コードをimportしません")
        paths.add(path)
        queue.extend(value for value in vars(module).values() if isinstance(value, type(sys)))
    return {path.relative_to(ROOT).as_posix(): V.sha(path) for path in sorted(paths)}


# ----------------------------------------
# rootの明示起動だけで準備/正式監査を分け、無指定では実観測へ進まない。

def prepare(study: Path, work: Path) -> dict:
    """原OHLCのATR/CCI/上位BB/全突破と全C採否をラベルなし主準備へ照合する。

    引数: study/work (Path) は正式/作業先。
    返り値: dict は準備proof。先着/運用/損益を計算しない。
    """
    audit, original_code = Audit(), V.sha(Path(__file__))
    config, manifest, master, resolved = guarded_inputs(study, work, audit)
    totals, counts, stages = Counter(), [], []
    for saved, block in zip(master["準備"], reconstruct(manifest, config), strict=True):
        session = block["場"]
        expected = {"場": session, "期間": block["期間"], "指標": {str(size): block["価格足"][size] for size in (3, 15)},
            "入口品質": block["入口品質"], "指標品質": block["指標品質"], "入力品質": block["入力品質"]}
        audit.check(session + ":全数値/価格/採否", saved, expected)
        counts.extend(count_signals(block))
        stages.append(stage(block))
        raw = block["入口品質"]["全Q発動記録"]
        for size in (3, 15):
            totals[str(size) + "分足"] += len(block["価格足"][size])
        totals["原価格発動"] += len(raw)
        for policy in POLICIES:
            totals[policy] += len(block["純入口"]["3分_" + policy])
        for row in raw:
            audit.check(row["発動ID"] + ":C1はC0部分集合", not row["戦略判定"]["C1"]["採用"] or row["戦略判定"]["C0"]["採用"], True)
        print(json.dumps({"場": session, "独立準備": "原OHLC/ATR/CCI精密/上位BB/全C", "不一致数": audit.mismatches}, ensure_ascii=False), flush=True)
    audit.check("全場二案件数", master["場別発動"], counts)
    grouped = period_counts(counts)
    audit.check("全期間二案件数", master["期間別発動"], grouped)
    audit.check("独立実行中code不変", V.sha(Path(__file__)), original_code)
    proof = {**proof_base(study, work, resolved, audit), "ラベル計算": False, "損益計算": False,
        "全数": dict(totals), "場別発動": counts, "期間別発動": grouped, "監視段階": stages,
        "主コードSHA256": master["コードSHA256"],
        "検証範囲": "固定66cacheの当場非後退列から3/15分半開原OHLCを独立構築。ATR/当場CCI20現前の元HLC正確分数・同窓平均/MD/±100・15分BB数値carry/当場最新公開と隣接前値のend-key asof/厳密母分散差/全context/M/rawP/全C採否/競合/件数を比較。",
        "限界": "準備だけで先着/新規受入/運用/PnLを呼ばない。量/MACD等を採否に使用しない。原板本文を再抽出せず既使用66cacheを共通入力とする。"}
    (work / "独立準備点検.json").write_text(json.dumps(proof, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({key: proof[key] for key in ("全件一致", "照合項目数", "不一致数", "入力場数", "ラベル計算", "損益計算")}, ensure_ascii=False))
    return proof


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
            ("追尾コードSHA256", V.sha(Path(__file__).with_name("追尾独立確認.py"))),
            ("主準備SHA256", V.sha(work / "準備点検.json")), ("条件SHA256", V.sha(study / "条件.json")),
            ("入力台帳SHA256", V.sha(study / "入力台帳.json")), ("解決入力台帳SHA256", V.sha(resolved))):
        audit.check("独立準備bind:" + key, prepared[key], expected)
    for path, digest in prepared["依存コードSHA256"].items():
        audit.check("準備依存コード現在:" + path, V.sha(ROOT / path), digest)
    audit.check("準備依存集合", prepared["依存コードSHA256"], dependency_pins())
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
        audit.check(name + "品質全件", len(local), 132 if name == "指標" else 66)
    input_quality = {row["場"]: row for row in input_quality}
    entrance_quality = {row["場"]: row for row in entrance_quality}
    numeric_by_session = defaultdict(list)
    for row in numeric_quality:
        numeric_by_session[row["場"]].append(row)
    stages, raw_expected, case_expected = [], {}, {}
    for block in reconstruct(manifest, config):
        session, phase = block["場"], block["期間"]
        audit.check(session + ":全3/15数値", grouped["全指標"][session],
            [{"期間": phase, **row} for size in (3, 15) for row in block["価格足"][size]])
        audit.check(session + ":全context/BB/M", grouped["全複合context"][session],
            [{"期間": phase, **row} for row in block["入口品質"]["複合context記録"]])
        expected_raw = [{"期間": phase, **row} for row in block["入口品質"]["全Q発動記録"]]
        audit.check(session + ":原P全件数", len(grouped["全複合shadow"][session]), len(expected_raw))
        for actual, expected in zip(grouped["全複合shadow"][session], expected_raw):
            B.compare_signal(audit, actual, expected, False)
            raw_expected[expected["発動ID"]] = expected
        expected_cases = [{"期間": phase, **row} for local in block["純入口"].values() for row in local]
        audit.check(session + ":全C純採用数", len(grouped["入口事例"][session]), len(expected_cases))
        for actual, expected in zip(grouped["入口事例"][session], expected_cases):
            B.compare_signal(audit, actual, expected, True)
            case_expected[expected["イベントID"]] = expected
        small = stage(block)
        stages.append(small)
        audit.check(session + ":入口品質", entrance_quality[session], small)
        audit.check(session + ":入力品質", input_quality[session], {"期間": phase, **block["入力品質"]})
        audit.check(session + ":指標品質", numeric_by_session[session], [{"期間": phase, **row} for row in block["指標品質"]])
        details = grouped["全運用詳細"][session]
        audit.check(session + ":全二案運用", {row["候補ID"] for row in details}, {"3分_" + policy + "_X0" for policy in POLICIES})
        audit.check(session + ":運用一意2件", len(details), 2)
        for detail in details:
            audit.check(session + ":運用品質期間", detail["品質"]["期間"], phase)
        print(json.dumps({"場": session, "独立確認": "原OHLC/ATR/CCI精密/上位BB/原P/全C", "不一致数": audit.mismatches}, ensure_ascii=False), flush=True)
    audit.check("原P全一意集合", {row["発動ID"] for row in rows["全複合shadow"]}, set(raw_expected))
    audit.check("全C採用一意集合", {row["イベントID"] for row in rows["入口事例"]}, set(case_expected))
    canonical_diffs = 0
    for row in rows["入口事例"]:
        expected = raw_expected.get(row["発動ID"])
        same = expected is not None and row["戦略判定"] == expected["戦略判定"]
        canonical_diffs += int(not same)
        audit.check(row["イベントID"] + ":全C採否canonical", same, True)
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
        "検証範囲": "固定cacheから全3/15分原OHLC/ATR/精密CCI20/上位BB値と厳密差/当場最新隣接公開/end-key asof/価格20窓/M/全C採否を独立再構成。正式全足/全context/rawP/case/品質と時間遅延対象外9Noneを全件比較し、6gzip全行の展開SHAをbind。",
        "限界": "通常先着数値・実新規受入・会計・追尾は別監査。原板本文を再抽出せず固定cacheを共通入力とする。既使用66場を未見と呼ばない。"}
    (work / "状態独立確認.json").write_text(json.dumps(proof, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({key: proof[key] for key in ("全件一致", "照合項目数", "不一致数", "入力場数", "保存shadow数", "保存入口数")}, ensure_ascii=False))
    return proof


def main() -> None:
    """固定前準備とroot正式完了後の状態監査を明示指定で分ける。

    引数: なし。--study/--work/--prepare/--実行許可を読む。
    返り値: None。不一致は非0終了。無指定で先着/運用を読まない。
    """
    parser = argparse.ArgumentParser(description="CCI突破の原OHLC独立状態確認")
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
