"""00046の原8列、二実体の包み、精密SMA進行と全新先着を独立検算する。"""

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
STUDY = ROOT / "study/00046_二足の実体包みと平均進行"
WORK = ROOT / "work/実体包み/00046"
INDICATOR_STUDY = ROOT / "study/00029_BB内復帰とOBV非追随"
INDICATOR_WORK = ROOT / "work/OBV反転/00029"
EXIT_STUDY = ROOT / "study/00033_CCI突破と足内終値位置"
POLICIES = ("B0", "B1", "B2")
OPERATIONS = tuple("3分_" + value + "_XF" for value in POLICIES)


def helper(path: Path, name: str) -> Any:
    """固定された独立足・数値・先着補助だけを読む。

    引数: path(Path)は固定独立コード、name(str)は読込名。
    返り値: Anyは補助。46主入口・主運用・主指標をimportしない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value

OLD = helper(ROOT / "scripts/回帰突破/状態独立確認.py", "実体包みの固定独立原足と先着")
G, N, S, V, Y = OLD.G, OLD.N, OLD.S, OLD.V, OLD.Y
NumericHistory = OLD.NumericHistory
SIGNAL_FIELDS, LABEL_FIELDS, SOURCE_FIELDS = OLD.SIGNAL_FIELDS, OLD.LABEL_FIELDS, OLD.SOURCE_FIELDS
FRAME_FIELDS = ("場", *SOURCE_FIELDS, "atr", "macd_hist")
SMA_FIELDS = ("SMA前", "SMA前々", "SMA進行", "終値対前SMA", "SMA準備", "SMA進行符号", "SMA位置符号",
              "SMA前20足番号", "SMA前々20足番号", "SMA過去足数", "SMA最遅公開key", "SMA解除理由")
NUMERIC_FIELDS = (*FRAME_FIELDS, *SMA_FIELDS)
METADATA_FIELDS = ("元価格side", "前足番号", "B2判別種別", "B2役割")
ROLES = {"B0": "反転", "B1": "反転", "B2": "切替"}
ACTIVE_ROLES = {"B0": ("反転",), "B1": ("反転",), "B2": ("順行", "反転")}
ROLE_PAIRS = tuple((policy, role) for policy in POLICIES for role in ACTIVE_ROLES[policy])
finite, exact = OLD.finite, OLD.exact
canonical_sha, decision_signal = OLD.canonical_sha, OLD.decision_signal
normal_columns, label_direct = OLD.normal_columns, OLD.label_direct
saved_rows = Y.saved_rows


class Audit(OLD.Audit):
    """現前Hの表示aliasも同じ限定許容と厳密符号で検査する。"""

    def check(self, name: str, actual: Any, expected: Any) -> None:
        """表示aliasを既定H比較器へ接続し、他の許容対象を増やさない。

        引数: name(str)は経路、actual/expected(Any)は定義/独立値。
        返り値: None。現前H値だけabs1e-10/rel0、有限・符号はstrict。
        """
        if name.rsplit(":", 1)[-1] in ("MACDヒスト現", "MACDヒスト前"):
            return super().check(name + ":macd_hist", actual, expected)
        return super().check(name, actual, expected)


# ----------------------------------------
# 数値は固定独立41の銀行だけを読む。46主の数式や採否関数はimportしない。


def frame_projection(row: dict | None) -> dict | None:
    """当場3分の出典と使用数値だけを新辞書へ写す。

    引数: row(dict|None)は保存又は独立数値足。
    返り値: dict|Noneは15列。量・OBV・旧価格発動を含めない。
    """
    if row is not None and row["minutes"] != 3:
        raise ValueError("実体包みは3分だけです")
    return None if row is None else {key: deepcopy(row[key]) for key in FRAME_FIELDS}


def body_envelop(previous: dict, current: dict, side: int) -> bool:
    """二つの実体区間の包含と終値側の厳密超過から価格発動を別検査する。

    引数: previous/current(dict)は隣接する有効OHLC、side(int)は買い1/売り−1。
    返り値: boolは前実体反対色・現実体実方向・始値側等号可・終値側strictの包み。
    """
    if side not in (1, -1):
        raise ValueError("実方向は1又は−1")
    old_o, old_c, new_o, new_c = (Fraction(previous["open"]), Fraction(previous["close"]),
                                 Fraction(current["open"]), Fraction(current["close"]))
    old_lower, old_upper = min(old_o, old_c), max(old_o, old_c)
    new_lower, new_upper = min(new_o, new_c), max(new_o, new_c)
    reverse = old_c < old_o if side == 1 else old_c > old_o
    actual = new_c > new_o if side == 1 else new_c < new_o
    beyond = new_c > old_upper if side == 1 else new_c < old_lower
    return bool(reverse and actual and new_lower <= old_lower and new_upper >= old_upper and beyond)


def mean_pair(past: list[dict]) -> tuple[Fraction | None, Fraction | None]:
    """現足を含まない過去21足から別々の20足窓和を作る。

    引数: past(list[dict])は同場の連続公開有効足を古い順に並べた配列。
    返り値: tuple[Fraction|None,Fraction|None]は前SMA20/前々SMA20。20本時は前だけ既知。
    """
    if len(past) < 20:
        return None, None
    prices = [Fraction(row["close"]) for row in past[-21:]]
    first = sum(prices[-20:], Fraction()) / 20
    return first, sum(prices[:-1], Fraction()) / 20 if len(prices) == 21 else None


def price_valid(row: dict) -> bool:
    """原OHLCから完全3分の価格有効性だけを判定する。

    引数: row(dict)は原足又は共有15列。
    返り値: boolは3分・180秒・有限かつ整合するOHLC。
    """
    return bool(row["minutes"] == 3 and row["end"] - row["start"] == 180 and N.valid_ohlc(row))


def sma_state(past: list[dict], close: float) -> dict:
    """二つの過去窓の別スライス和から精密SMAと当時位置を計算する。

    引数: past(list[dict])は最大21公開過去足、close(float)は現終値。
    返り値: dictは精密4値・準備・符号と全窓出典。現足を平均へ入れない。
    """
    first, second = mean_pair(past)
    change = first - second if first is not None and second is not None else None
    position = Fraction(close) - first if first is not None and finite(close) else None
    return {"SMA前": exact(first), "SMA前々": exact(second), "SMA進行": exact(change),
        "終値対前SMA": exact(position), "SMA準備": change is not None and position is not None,
        "SMA進行符号": (change > 0) - (change < 0) if change is not None else None,
        "SMA位置符号": (position > 0) - (position < 0) if position is not None else None,
        "SMA前20足番号": [row["index"] for row in past[-20:]],
        "SMA前々20足番号": [row["index"] for row in past[-21:-1]], "SMA過去足数": len(past),
        "SMA最遅公開key": [past[-1]["confirm"], past[-1]["confirm_line"]] if past else None}


def build_local(frames: list[dict], session: str) -> tuple[list[dict], dict]:
    """固定数値を更新せず、連続区間のprefix履歴から現足除外SMAを別構築する。

    引数: frames(list[dict])は共有又は独立の15列足、session(str)は当場。
    返り値: tuple[list[dict],dict]は新27列/局所品質。数量・価格先着を呼ばない。
    """
    history, rows, previous, public_key, clears = [], [], None, None, 0
    for source in frames:
        row = frame_projection(source)
        if row["場"] != session or row["minutes"] != 3:
            raise ValueError("当場3分足のみ")
        key = row["confirm"], row["confirm_line"]
        if previous is not None and row["index"] <= previous["index"]:
            raise ValueError("足番号重複又は後退")
        if row["publish"] and (row["confirm"] < row["end"] or public_key is not None and key <= public_key):
            raise ValueError("公開key同値/後退又は終了前公開")
        reasons = []
        if previous is None and row["index"] != 0 or previous is not None and (
                row["index"] != previous["index"] + 1 or row["start"] != previous["end"]):
            reasons.append("番号又は終了非連続")
        if row["missing"]:
            reasons.append("欠枠")
        if not row["publish"]:
            reasons.append("非公開")
        if not price_valid(row):
            reasons.append("完全3分価格不正")
        if reasons:
            history, clears = [], clears + 1
        eligible = bool(row["publish"] and not row["missing"] and price_valid(row))
        state = sma_state(history[-21:], row["close"]) if eligible else sma_state([], 0.)
        rows.append({**row, **state, "SMA解除理由": reasons})
        if eligible:
            history.append(row)
        previous = row
        if row["publish"]:
            public_key = key
    return rows, {"場": session, "時間足分": 3, "入力足数": len(rows), "局所解除足数": clears,
        "SMA共通準備足数": sum(row["SMA準備"] for row in rows),
        "SMA前単独準備足数": sum(row["SMA前"]["有効"] for row in rows)}


def judgment_projection(value: Any) -> Any:
    """限定許容するATR/Hだけを判断情報へ写し、他の全精密値を保持する。

    引数: value(Any)は全数値/全P/純信号。
    返り値: AnyはATR正/D整数とH/差符号を持つ厳密JSON。
    """
    if isinstance(value, dict):
        output = {}
        for key, item in value.items():
            if key == "atr":
                positive = finite(item) and item > 0
                output["ATR判断"] = {"正有効": positive, "D整数": max(5, math.ceil(item / 5) * 5) if positive else None}
            elif key in ("macd_hist", "MACDヒスト現", "MACDヒスト前", "MACDヒスト変化"):
                output[key] = {"有限": True, "符号": (item > 0) - (item < 0)} if finite(item) else deepcopy(item)
            else:
                output[key] = judgment_projection(item)
        return output
    if isinstance(value, list):
        return [judgment_projection(item) for item in value]
    return deepcopy(value)


def compare_numeric_scope(name: str, defined: Any, independent: Any, audit: Audit) -> bool:
    """浮動値の限定許容と全価格/分数/準備/採否の厳密一致を個別に要求する。

    引数: name(str)は範囲、defined/independent(Any)は正本定義/生計算、audit(Audit)は比較先。
    返り値: boolは厳密判断投影の同値。許容超過も別に不一致へ記録する。
    """
    audit.check(name + ":全数値", defined, independent)
    same = canonical_sha(judgment_projection(defined)) == canonical_sha(judgment_projection(independent))
    audit.check(name + ":全準備符号採否と非許容値strict", same, True)
    return same


def define_frames(independent: list[dict], shared: list[dict]) -> list[dict]:
    """独立SOURCEを残して、検算対象の正本ATR/H定義列を別配列に作る。

    引数: independent/shared(list[dict])は原8列別算/29共有15列。
    返り値: list[dict]は数値2列だけのoverlay。生配列と銀行は変更しない。
    """
    source = {row["index"]: row for row in shared}
    indices = [row["index"] for row in independent]
    if len(source) != len(shared) or len(indices) != len(set(indices)) or set(indices) != set(source):
        raise ValueError("独立足と共有数値定義の全足一対一対応に差")
    return [{**deepcopy(row), **{name: deepcopy(source[row["index"]][name]) for name in ("atr", "macd_hist")}}
            for row in independent]


def classification(row: dict, side: int) -> tuple[str, str | None]:
    """当時の二つの精密符号から順行・反転・待機を分類する。

    引数: row(dict)はSMA状態、side(int)は実方向。
    返り値: tuple[str,str|None]は区分と実役割。SMA不足はWAIT値と区別する。
    """
    if not row["SMA準備"]:
        return "未準備", None
    signs = row["SMA進行符号"], row["SMA位置符号"]
    if signs == (side, side):
        return "T", "順行"
    if signs == (-side, -side):
        return "R", "反転"
    return "WAIT", None


def role_for(row: dict, policy: str) -> str | None:
    """基準二案と切替案の操作上の実役割を固定する。

    引数: row(dict)はP又はenriched、policy(str)はB0/B1/B2。
    返り値: str|Noneは反転/順行又は不採用の役割なし。
    """
    if policy not in POLICIES:
        raise ValueError("固定三案のみ")
    return row["B2役割"] if policy == "B2" else "反転"


def pure_signal(row: dict, policy: str = "B0") -> dict:
    """当時の実方向と候補役割を執行用13列へ写す。

    引数: row(dict)は新P又はenriched、policy(str)はB0/B1/B2。
    返り値: dictは純信号。平均/分類出典/未来先着を含めない。
    """
    role = role_for(row, policy)
    if (policy, role) not in ROLE_PAIRS or row["side"] not in (-1, 1):
        raise ValueError("採用する四役割と実方向だけ")
    if row["方向"] != ("買い" if row["side"] == 1 else "売り"):
        raise ValueError("実方向表示に差")
    return {**{name: deepcopy(row[name]) for name in SIGNAL_FIELDS},
            "イベントID": row["発動ID"] + "_" + policy, "入口ID": "3分_" + policy,
            "役割": role, "bb_mean": None}


def verdicts(row: dict) -> dict:
    """共通価格/勢い基準へ平均準備と値の採否を段階付加する。

    引数: row(dict)は新Pの当時判断。
    返り値: dictは三案の全採否/理由。条件不成立を後続へ持ち越さない。
    """
    base = list(row["M除外理由"])
    if not row["時間条件可"]:
        base.append("要求時間条件外")
    if not row["確認遅延条件可"]:
        base.append("確認遅延30秒超")
    if row["MACDヒスト変化符号"] is None or row["side"] * row["MACDヒスト変化符号"] <= 0:
        base.append("MACDヒスト実方向strict正不成立")
    output = {}
    for policy in POLICIES:
        reasons = list(base)
        if policy != "B0" and not row["SMA準備"]:
            reasons.append("当場21過去終値SMA二平均未準備")
        if policy == "B2" and row["SMA準備"] and row["B2判別種別"] == "WAIT":
            reasons.append("平均位置進行の混在又は等号WAIT")
        output[policy] = {"採用": not reasons, "理由": reasons or ["二足実体包みと勢い複合採用"], "同時競合": False}
    return output


def event_row(row: dict, previous: dict, side: int, cutoff: float, deadline: float, config: dict) -> dict:
    """包含Pの全価格・精密値・時点と三採否を独立行へまとめる。

    引数: row/previous(dict)は現前27列、side(int)は実方向、cutoff/deadline(float)は場時刻、
    config(dict)は事前条件。
    返り値: dictは未選別の新P。元の二実体とB2役割を別に保存する。
    """
    event = f"NK225_{row['場']}_3分_実体包み_{row['index']:04d}_{side}"
    change = row["macd_hist"] - previous["macd_hist"] if finite(row["macd_hist"]) and finite(previous["macd_hist"]) else None
    branch, role = classification(row, side)
    missing = []
    if not finite(row["atr"]) or row["atr"] <= 0:
        missing.append("現在ATR14有限正未準備")
    if change is None:
        missing.append("同場隣接公開MACDヒスト未準備")
    time_ok = row["confirm"] < cutoff and deadline - row["confirm"] >= config["残り時間下限分"] * 60
    delay_ok = row["confirm"] - row["end"] <= config["確認遅延上限秒"]
    record = {**deepcopy(row), "時間足分": 3, "発動ID": event, "イベントID": event,
        "入口ID": "3分_実体包み", "入口系統": "二足実体包み", "役割": "反転", "side": side,
        "元価格side": side, "方向": "買い" if side == 1 else "売り", "前足番号": previous["index"],
        "前3分参照": frame_projection(previous),
        "前実体": exact(Fraction(previous["close"]) - Fraction(previous["open"])),
        "現実体": exact(Fraction(row["close"]) - Fraction(row["open"])),
        "始値対前終値": exact(Fraction(row["open"]) - Fraction(previous["close"])),
        "終値対前始値": exact(Fraction(row["close"]) - Fraction(previous["open"])),
        "MACDヒスト現": row["macd_hist"], "MACDヒスト前": previous["macd_hist"],
        "MACDヒスト変化": change, "MACDヒスト変化符号": (change > 0) - (change < 0) if change is not None else None,
        "B2判別種別": branch, "B2役割": role, "共通M準備": not missing, "M除外理由": missing,
        "時間条件可": time_ok, "確認遅延条件可": delay_ok, "要求時計秒": row["confirm"], "要求原板行": row["confirm_line"],
        "足終了時計秒": row["end"], "確認遅延秒": row["confirm"] - row["end"], "期限時計秒": deadline,
        "残り分_判断時": (deadline - row["confirm"]) / 60, "先着評価対象": time_ok and delay_ok, "bb_mean": None}
    record["戦略判定"] = verdicts(record)
    return record


def generate(frames: list[dict], session: str, cutoff: float, deadline: float, config: dict) -> dict:
    """隣接二行の区間包含を直接列挙し、新P全集合と三純入口を別構築する。

    引数: frames(list[dict])は新27列、session(str)は場、cutoff/deadline(float)は停止/強制、
    config(dict)は時間/遅延条件。
    返り値: dictは全足/全P/全採否/metadata。指標や価格先着を新たに計算しない。
    """
    projected = [{name: deepcopy(row[name]) for name in NUMERIC_FIELDS} for row in frames]
    eligible, records, metadata, key_before = [], [], {}, None
    clears = pair_count = 0
    for index, row in enumerate(projected):
        if row["場"] != session or row["minutes"] != 3:
            raise ValueError("当場新3分足のみ")
        previous = projected[index - 1] if index else None
        key = row["confirm"], row["confirm_line"]
        if previous is not None and row["index"] <= previous["index"]:
            raise ValueError("足番号重複又は後退")
        if row["publish"] and (row["confirm"] < row["end"] or key_before is not None and key <= key_before):
            raise ValueError("公開key同値/後退又は終了前公開")
        consecutive = previous is None or (row["index"] == previous["index"] + 1 and row["start"] == previous["end"])
        valid = bool(row["publish"] and not row["missing"] and price_valid(row))
        eligible.append(valid)
        clears += int(not valid or not consecutive)
        if previous is not None and eligible[index - 1] and valid and consecutive:
            pair_count += 1
            for side in (1, -1):
                if body_envelop(previous, row, side):
                    record = event_row(row, previous, side, cutoff, deadline, config)
                    records.append(record)
                    metadata[record["発動ID"]] = {name: deepcopy(record[name]) for name in METADATA_FIELDS}
        if row["publish"]:
            key_before = key
    groups = defaultdict(list)
    for row in records:
        for policy in POLICIES:
            if row["戦略判定"][policy]["採用"]:
                groups[(policy, row["要求時計秒"], row["要求原板行"])].append(row)
    for (policy, _, _), rows in groups.items():
        if len(rows) > 1:
            for row in rows:
                row["戦略判定"][policy] = {"採用": False, "理由": ["同判断複数信号見送り"], "同時競合": True}
    signals = {"3分_" + p: [] for p in POLICIES}
    for row in records:
        for policy in POLICIES:
            if row["戦略判定"][policy]["採用"]:
                signals["3分_" + policy].append({**deepcopy(row), "イベントID": row["発動ID"] + "_" + policy,
                    "入口ID": "3分_" + policy, "戦略": policy, "役割": role_for(row, policy),
                    "複合判定": deepcopy(row["戦略判定"][policy])})
    quality = {"場": session, "時間足分": 3, "入力足数": len(projected), "局所解除足数": clears, "二足価格準備数": pair_count,
        "原価格発動数": len(records), "先着評価対象外数": sum(not row["先着評価対象"] for row in records),
        "B2分類数": dict(Counter(row["B2判別種別"] for row in records)),
        "戦略別発動数": {sid: len(rows) for sid, rows in signals.items()},
        "戦略採否理由別": {p: dict(Counter(reason for row in records for reason in row["戦略判定"][p]["理由"])) for p in POLICIES}}
    return {"場": session, "frames": {3: projected}, "signals": signals, "raw": records, "decisions": records,
            "metadata": metadata, "quality": quality}


# ----------------------------------------
# 共通の台帳と出典結合。root以外は市場CLIを起動しない。

def dependency_pins() -> dict:
    """固定独立足・中心化MACD・直接先着・追尾の全依存を識別する。

    引数: なし。
    返り値: dict[str,str]はROOT相対pathと現在SHA。46主コードを数式依存にしない。
    """
    paths = {"scripts/回帰突破/状態独立確認.py", "scripts/発動値幅継続/状態独立確認.py", "scripts/OBV反転/状態独立確認.py",
        "scripts/終値位置/追尾独立確認.py"}
    return dict(sorted({**Y.dependency_pins(), **{name: V.sha(ROOT / name) for name in paths}}.items()))


def shared_bundle(audit: Audit) -> dict:
    """29の保存全数値を出典照合し、3分15列だけを研究入力へ渡す。

    引数: audit(Audit)は圧縮・展開SHAとサイズの比較先。
    返り値: dictはlowerと元数値展開SHA。旧P/旧case/旧取引を読み込まない。
    """
    rows, digest = saved_rows(INDICATOR_STUDY, INDICATOR_WORK, "全指標.jsonl.gz", audit)
    lower = defaultdict(list)
    for row in rows:
        if row["minutes"] == 3:
            lower[row["場"]].append(frame_projection(row))
    return {"lower": lower, "共有3分全指標展開SHA256": digest}


def references(study: Path, audit: Audit) -> None:
    """指標参照だけを固定29正本へ結び、旧入口を新発動の正本にしない。

    引数: study(Path)は46、audit(Audit)は比較先。
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

    引数: study/work(Path)は46保存先、audit(Audit)は比較先。
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
    paths = {"scripts/実体包み/" + name for name in ("検証.py", "入口.py", "指標.py", "運用.py")}
    audit.check("主四コード集合", set(master["コードSHA256"]), paths)
    for name, digest in master["コードSHA256"].items():
        audit.check("主準備現在:" + name, V.sha(ROOT / name), digest)
    audit.check("主66場順", [row["場"] for row in master["準備"]], [entry["session"] for entry in manifest["entries"]])
    if audit.mismatches:
        raise ValueError("入力/主準備/数値参照に差があり市場入力前停止")
    return config, manifest, master, resolved


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
        "厳密範囲": "原8列由来SOURCE/SMA20全分数/新P/時点/全採否/純13原値は厳密。全ATR/Hの別算値はabs1e-10/rel0、ATR正有効/D整数・H符号と全原PのδH符号/M/採否はstrict。検算済み保存正本floatを定義とする全3分/判定SHAと、独立再算値の生SHAは区別する。",
        "数値許容": {"対象": ["atr", "macd_hist", "MACDヒスト現", "MACDヒスト前", "MACDヒスト変化"], "絶対許容": 1e-10, "相対許容": 0,
            "採否epsilon": False, "正本定義SHAと独立生数値SHAを区別": True}}


def prepare(study: Path, work: Path) -> dict:
    """root起動の非損益準備で全原足/数値/二足包みと新三入口を検算する。

    引数: study/work(Path)は46保存先。
    返り値: dictはラベル・運用・PnL計算を呼ばない独立準備証明。
    """
    audit, initial = Audit(), V.sha(Path(__file__))
    config, manifest, master, resolved = guarded_inputs(study, work, audit)
    bundle, stages = shared_bundle(audit), []
    for main_record, block in zip(master["準備"], reconstruct(manifest, bundle, config), strict=True):
        stages.append(compare_preparation(main_record, block, bundle, audit))
        print(json.dumps({"場": block["場"], "独立準備": "原3分ATR/H・二実体包含・SMA窓和・全B", "不一致数": audit.mismatches}, ensure_ascii=False), flush=True)
    audit.check("独立実行中コード不変", V.sha(Path(__file__)), initial)
    proof = {**proof_base(study, work, resolved, master, audit), "ラベル計算": False, "損益計算": False,
        "全66場既使用": True, "場別準備": stages, **numeric_summary(stages),
        "方針別登録数": {p: sum(r[p + "登録数"] for r in stages) for p in POLICIES},
        "共有3分全指標展開SHA256": bundle["共有3分全指標展開SHA256"],
        "検証範囲": "全8列入力から3分OHLC/ATR14/中心化MACDヒストを再算。二実体の区間包含、現足除外SMA20の二窓和、三採否と純13を独立構築。正本floatのSHA整合と再算数値の全符号/採否影響を分けて検査する。",
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


def reconstruct(manifest: dict, bundle: dict, config: dict) -> Any:
    """原8列数値と正本数値を別経路で包み足/SMAへ通す。

    引数: manifest/bundle/config(dict)は固定66台帳/29共有15列/事前条件。
    返り値: Anyは場別非損益iterator。新価格発動を旧入口集合から作らない。
    """
    bank = NumericHistory(3)
    for entry in manifest["entries"]:
        session = entry["session"]
        start, finish, cutoff, deadline = S.G.times(session)
        data = G.observed(entry, manifest)
        formed = S.bars(data, session, 3, N.BareBars())
        tail = max(0, int((finish - start) // 180) - 1 - (formed[-1]["index"] if formed else -1))
        independent, bank_quality = bank.build(formed, session, tuple(entry["in_session_contract_codes"]), tail)
        defined = define_frames(independent, bundle["lower"][session])
        local_defined, quality = build_local(defined, session)
        local_independent, raw_quality = build_local(independent, session)
        selected = generate(local_defined, session, cutoff, deadline, config)
        alternate = generate(local_independent, session, cutoff, deadline, config)
        pure = [pure_signal(row, policy) for policy in POLICIES for row in selected["signals"]["3分_" + policy]]
        period = "学習" if session[:10] < config["分割"]["選択開始日"] else ("条件選択" if session[:10] < config["分割"]["後続開始日"] else "後続検査")
        yield {"場": session, "期間": period, "純信号": pure, "純信号内容SHA256": canonical_sha(pure),
            "純信号判断SHA256": canonical_sha([decision_signal(row) for row in pure]),
            "判定": selected["decisions"], "判定SHA256": canonical_sha(selected["decisions"]),
            "判定判断SHA256": canonical_sha(selected["decisions"]),
            "全3分投影SHA256": canonical_sha(defined), "3分投影足数": len(defined), "入力品質": selected["quality"],
            "全指標内容SHA256": canonical_sha(local_defined), "全指標足数": len(local_defined), "数値品質": quality,
            "_再算全3分": independent, "_正本数値定義全3分": defined, "_正本全指標": local_defined,
            "_再算全指標": local_independent, "_正本判断": selected, "_再算判断": alternate,
            "_局所生品質": raw_quality, "_原足銀行品質": bank_quality}


def compare_preparation(master: dict, block: dict, bundle: dict, audit: Audit) -> dict:
    """数値限定許容・生値判断・正本定義厳密内容を三段で照合する。

    引数: master/block/bundle(dict)は主場別準備/独立場別/29共有、audit(Audit)は比較先。
    返り値: dictは全Pと三集合、数値表現差、strict判断影響の要約。
    """
    session, independent, defined = block["場"], block["_再算全3分"], block["_正本数値定義全3分"]
    audit.check(session + ":原8列SOURCE/ATR/H", independent, bundle["lower"][session])
    expected = {name: value for name, value in block.items() if not name.startswith("_")}
    audit.check(session + ":主準備と全正本定義", master, expected)
    audit.check(session + ":主全値厳密JSON", master == expected, True)
    full_same = compare_numeric_scope(session + ":全27列生数値", block["_正本全指標"], block["_再算全指標"], audit)
    selected, alternate = block["_正本判断"], block["_再算判断"]
    p_same = compare_numeric_scope(session + ":生値による全P", selected["decisions"], alternate["decisions"], audit)
    raw_pure = [pure_signal(row, p) for p in POLICIES for row in alternate["signals"]["3分_" + p]]
    pure_same = compare_numeric_scope(session + ":生値による三純13", block["純信号"], raw_pure, audit)
    audit.check(session + ":生値と全局所品質", block["_局所生品質"], block["数値品質"])
    for name in ("metadata", "quality"):
        audit.check(session + ":生値の価格状態/件数:" + name, selected[name], alternate[name])
        audit.check(session + ":生値厳密残余:" + name, selected[name] == alternate[name], True)
    ids = {p: {row["イベントID"][:-3] for row in block["純信号"] if row["入口ID"] == "3分_" + p} for p in POLICIES}
    audit.check(session + ":B1subsetB0", ids["B1"] <= ids["B0"], True)
    audit.check(session + ":B2subsetB1", ids["B2"] <= ids["B1"], True)
    decisions = {row["発動ID"]: row for row in block["判定"]}
    roles = Counter()
    for signal in block["純信号"]:
        policy = signal["入口ID"].removeprefix("3分_")
        audit.check(signal["イベントID"] + ":純13列", set(signal), set(SIGNAL_FIELDS))
        audit.check(signal["イベントID"] + ":当時全13値", signal == pure_signal(decisions[signal["イベントID"][:-3]], policy), True)
        audit.check(signal["イベントID"] + ":四役割の実定義", (policy, signal["役割"]) in ROLE_PAIRS, True)
        roles[(policy, signal["役割"])] += 1
    differences = {name: [abs(a[name] - b[name]) for a, b in zip(independent, defined, strict=True)
        if finite(a[name]) and finite(b[name]) and a[name] != b[name]] for name in ("atr", "macd_hist")}
    return {"場": session, "期間": block["期間"], **{p + "登録数": len(ids[p]) for p in POLICIES},
        "原価格発動数": len(block["判定"]), "3分投影足数": len(independent),
        "実役割別登録": [{"戦略": p, "役割": role, "件数": roles[(p, role)]} for p, role in ROLE_PAIRS],
        **{name + "表現差足数": len(values) for name, values in differences.items()},
        **{name + "最大絶対差": max(values, default=0.0) for name, values in differences.items()},
        "再算数値判断不一致場": int(not (full_same and p_same and pure_same)),
        "全3分投影SHA256": block["全3分投影SHA256"], "正本定義全指標内容SHA256": block["全指標内容SHA256"],
        "独立生全指標内容SHA256": canonical_sha(block["_再算全指標"]),
        "全判定SHA256": block["判定SHA256"], "独立生全判定SHA256": canonical_sha(alternate["decisions"])}


def numeric_summary(stages: list[dict]) -> dict:
    """全足表現差と全Pのstrict判断影響を分離してまとめる。

    引数: stages(list[dict])は全場準備要約。
    返り値: dictは全足/P件数・限定浮動差・判断差。B1同値を論理必然にしない。
    """
    return {"新3分全数値照合足数": sum(row["3分投影足数"] for row in stages),
        "原価格発動数": sum(row["原価格発動数"] for row in stages),
        "独立数値判断不一致場数": sum(row["再算数値判断不一致場"] for row in stages),
        **{"独立" + name + "表現差足数": sum(row[name + "表現差足数"] for row in stages) for name in ("atr", "macd_hist")},
        **{"独立" + name + "最大絶対差": max((row[name + "最大絶対差"] for row in stages), default=0.0) for name in ("atr", "macd_hist")}}


def run(study: Path, work: Path) -> dict:
    """正式後だけ二実体包含と精密SMA・全採否と全case直接先着を照合する。

    引数: study/work(Path)は46正式/作業先。
    返り値: dictは五系列の状態証明。受付/約定/Decimalと全実保有は別証明へ結ぶ。
    """
    if not (study / "固定.json").exists() or not (study / "結果.json").exists():
        raise ValueError("root固定・正式完了後だけです")
    audit, initial = Audit(), V.sha(Path(__file__))
    config, manifest, master, resolved = guarded_inputs(study, work, audit)
    check_prepared(study, work, resolved, master, audit)
    bundle = shared_bundle(audit)
    names = ("全指標", "発動判定", "入口事例", "全運用詳細", "追尾")
    saved, hashes, grouped = {}, {}, {name: defaultdict(list) for name in names}
    for name in names:
        saved[name], hashes[name] = saved_rows(study, work, name + ".jsonl.gz", audit)
        for row in saved[name]:
            grouped[name][row["場"]].append(row)
    artifact_names = {Path(row["パス"]).name for row in V.read(study / "作業成果物.json")["ファイル"]}
    audit.check("新五成果物集合", artifact_names, {name + ".jsonl.gz" for name in names})
    pairs = [(row["場"], row["候補ID"]) for row in saved["全運用詳細"]]
    audit.check("全場候補一意", len(pairs), len(set(pairs)))
    audit.check("全3x66", set(pairs), {(entry["session"], cid) for entry in manifest["entries"] for cid in OPERATIONS})
    audit.check("全case一意", len(saved["入口事例"]), len({row["イベントID"] for row in saved["入口事例"]}))
    if audit.mismatches:
        raise ValueError("正式保存物の集合/指紋に差があり原足入力前停止")
    stages, counts, role_counts = [], Counter({p: 0 for p in POLICIES}), Counter()
    entries = {entry["session"]: entry for entry in manifest["entries"]}
    for main_record, block in zip(master["準備"], reconstruct(manifest, bundle, config), strict=True):
        stages.append(compare_preparation(main_record, block, bundle, audit))
        session, period, selected = block["場"], block["期間"], block["_正本判断"]
        expected_numeric = [{"期間": period, **row} for row in block["_正本全指標"]]
        expected_decisions = [{"期間": period, **row} for row in block["判定"]]
        for name, expected in (("全指標", expected_numeric), ("発動判定", expected_decisions)):
            audit.check(session + ":正式全値:" + name, grouped[name][session], expected)
            audit.check(session + ":正式厳密JSON:" + name, grouped[name][session] == expected, True)
        cases = {row["イベントID"]: row for row in grouped["入口事例"][session]}
        audit.check(session + ":全case純集合", set(cases), {row["イベントID"] for row in block["純信号"]})
        quotes = normal_columns(entries[session], manifest)
        _, _, cutoff, deadline = S.G.times(session)
        for signal in block["純信号"]:
            origin = signal["イベントID"][:-3]
            direct = label_direct(quotes, signal, cutoff, deadline)
            expected = {**deepcopy(signal), "期間": period,
                "要求時計JST": datetime.fromtimestamp(signal["要求時計秒"], timezone(timedelta(hours=9))).isoformat(),
                "元価格発動ID": origin, **deepcopy(selected["metadata"][origin]), **direct}
            audit.check(signal["イベントID"] + ":全新case直接BBO先着", cases.get(signal["イベントID"]), expected)
            audit.check(signal["イベントID"] + ":全新case厳密値", cases.get(signal["イベントID"]) == expected, True)
            policy = signal["入口ID"].removeprefix("3分_")
            counts[policy] += 1
            role_counts[(policy, signal["役割"])] += 1
        for detail in grouped["全運用詳細"][session]:
            audit.check(detail["候補ID"] + session + ":期間", detail["品質"]["期間"], period)
        print(json.dumps({"場": session, "独立状態": "原8列ATR/H/SMA・二実体/SMA・全新case直接先着",
                          "不一致数": audit.mismatches}, ensure_ascii=False), flush=True)
    result = V.read(study / "結果.json")
    for key, expected in {"全66場既使用": True, "入口評価数": 3, "運用候補数": 3, "現方針運用候補数": 3,
            "入口125250評価の変更": False, "表示固定ID": list(OPERATIONS)}.items():
        audit.check("正式結果:" + key, result[key], expected)
    audit.check("正式三候補順", [row["候補ID"] for row in result["結果"]], list(OPERATIONS))
    audit.check("全case数", len(saved["入口事例"]), sum(counts.values()))
    audit.check("独立実行中コード不変", V.sha(Path(__file__)), initial)
    proof = {**proof_base(study, work, resolved, master, audit), "場別準備": stages, **numeric_summary(stages),
        "方針別case数": dict(counts), "全先着直接照合件数": sum(counts.values()), "方針別先着直接照合件数": dict(counts),
        "役割別先着直接照合件数": [{"戦略": p, "役割": role, "件数": role_counts[(p, role)]}
            for p, role in ROLE_PAIRS],
        "保存全指標数": len(saved["全指標"]),
        "保存発動判定数": len(saved["発動判定"]), "保存入口事例数": len(saved["入口事例"]),
        "保存運用詳細数": len(saved["全運用詳細"]), "保存追尾数": len(saved["追尾"]),
        "成果物照合": {name + ".jsonl.gz": {"展開内容SHA256": hashes[name], "行数": len(saved[name])} for name in names},
        **{name + "展開SHA256": digest for name, digest in hashes.items()},
        "共有3分全指標展開SHA256": bundle["共有3分全指標展開SHA256"],
        "結果SHA256": V.sha(study / "結果.json"), "固定SHA256": V.sha(study / "固定.json"),
        "独立準備SHA256": V.sha(work / "独立準備点検.json"),
        "MACD数値照合統計": audit.macd_differences, "MACD厳密符号不一致数": audit.macd_sign_diffs,
        "検証範囲": "原8列OHLC/独立ATR/中心化H、二実体区間包含/現足除外精密SMA/三採否/当時実役割/純13を別構築。全新caseの最初+1秒正常BBOから125/250/空白/期限を実sideで直接走査。定義数値の全SHA整合と独立生数値の全準備/符号/採否strictを分離。",
        "限界": "旧29は足/ATR/H出典のみ。旧入口/旧先着/旧全属性対照は流用しない。実新規受付/最初BBO/Decimalは別会計、全保有と最初返済要求は別追尾。全66場既使用。"}
    (work / "状態独立確認.json").write_text(json.dumps(proof, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({key: proof[key] for key in ("全件一致", "照合項目数", "不一致数", "方針別case数")}, ensure_ascii=False))
    return proof


def main() -> None:
    """root許可による非損益準備又は固定後正式検算を明示起動する。

    引数: なし。--study/--work/--prepare/--実行許可を読む。
    返り値: None。無指定・不一致は非0終了する。
    """
    parser = argparse.ArgumentParser(description="00046二足実体包みとSMA窓和の独立検算")
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
