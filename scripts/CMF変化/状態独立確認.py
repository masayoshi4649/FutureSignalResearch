"""00043の原数量・42価格監視と、現前CMFの変化/寄与を独立検算する。"""

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
STUDY = ROOT / "study/00043_再テスト時のCMF変化方向"
WORK = ROOT / "work/CMF変化/00043"
ENTRY_STUDY = ROOT / "study/00042_突破再テストと数量加重終値位置"
ENTRY_WORK = ROOT / "work/再テスト量方向/00042"
INDICATOR_STUDY = ROOT / "study/00029_BB内復帰とOBV非追随"
INDICATOR_WORK = ROOT / "work/OBV反転/00029"
EXIT_STUDY = ROOT / "study/00033_CCI突破と足内終値位置"
POLICIES = ("D0", "D1", "D2")
OPERATIONS = tuple("3分_" + policy + "_XF" for policy in POLICIES)


def helper(path: Path, name: str) -> Any:
    """既固定の独立価格/数量/監視/先着補助をCLI起動せず読む。

    引数: path(Path)は独立コード、name(str)は読込名。
    返り値: Anyは固定補助。43主入口・主運用は期待値へimportしない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


Y = helper(ROOT / "scripts/再テスト量方向/状態独立確認.py", "CMF変化の固定42独立監視と数量")
G, N, S, V = Y.G, Y.N, Y.S, Y.V
Audit = G.Audit
SIGNAL_FIELDS, LABEL_FIELDS, SOURCE_FIELDS, FRAME_FIELDS = Y.SIGNAL_FIELDS, Y.LABEL_FIELDS, Y.SOURCE_FIELDS, Y.FRAME_FIELDS
canonical_sha, decision_signal, finite, exact = Y.canonical_sha, Y.decision_signal, Y.finite, Y.exact
normal_columns, label_direct, frame_projection, saved_rows = Y.normal_columns, Y.label_direct, Y.frame_projection, Y.saved_rows


def pure_signal(row: dict, policy: str = "D0") -> dict:
    """旧42A0の純13列から識別子だけを三D候補へ写す。

    引数: row(dict)は固定42A0純信号、policy(str)はD0/D1/D2。
    返り値: dictは当時jの実方向/実役割/価格/ATRを変えない純信号。
    """
    if policy not in POLICIES or row["入口ID"] != "3分_A0" or not row["イベントID"].endswith("_A0"):
        raise ValueError("固定42A0からの三候補だけです")
    if row["役割"] not in ("順行", "反転") or row["side"] not in (-1, 1):
        raise ValueError("実T/R方向が必要です")
    if row["方向"] != ("買い" if row["side"] == 1 else "売り"):
        raise ValueError("実方向と表示が不一致")
    value = {name: deepcopy(row[name]) for name in SIGNAL_FIELDS}
    value.update(イベントID=row["イベントID"][:-3] + "_" + policy, 入口ID="3分_" + policy)
    return value


def fraction_value(item: dict) -> Fraction | None:
    """有効な保存exact列を表示floatを経由せず復元する。

    引数: item(dict)は値/分子/分母/有効。
    返り値: Fraction|Noneは元の既約値。表示値を判定へ戻さない。
    """
    return Fraction(item["分子"], item["分母"]) if item["有効"] else None


def window_sums(rows: list[dict]) -> tuple[Fraction, Fraction]:
    """検査済み窓の加重和と総量を各元floatの分数から求める。

    引数: rows(list[dict])は公開完全価格/数量の連続足。
    返り値: tuple[Fraction,Fraction]はN/Q。Q0でも部分和そのものは有効。
    """
    total, weighted = Fraction(0), Fraction(0)
    for row in rows:
        high, low, close = (Fraction(row[name]) for name in ("high", "low", "close"))
        amount = Fraction(row["数量参照"]["観測差分量"])
        position = ((close - low) - (high - close)) / (high - low)
        total += amount
        weighted += position * amount
    return weighted, total


def pair_values(rows: list[dict]) -> dict | None:
    """22本から前/現21本を直接sliceし、差を交差積から別算する。

    引数: rows(list[dict])は数量/幅まで有効な連続22足。
    返り値: dict|Noneは内部精密値。共通20足総量0でも現/前総量が正なら有効。
    """
    if len(rows) != 22:
        return None
    before_n, before_q = window_sums(rows[:-1])
    current_n, current_q = window_sums(rows[1:])
    if before_q <= 0 or current_q <= 0:
        return None
    cross = current_n * before_q - before_n * current_q
    delta = cross / (before_q * current_q)
    current, old = rows[-1], rows[0]
    values = []
    for row in (current, old):
        high, low, close = (Fraction(row[name]) for name in ("high", "low", "close"))
        values.append((((close - low) - (high - close)) / (high - low), Fraction(row["数量参照"]["観測差分量"])))
    new_m, new_q = values[0]
    old_m, old_q = values[1]
    incoming = new_q * (new_m * before_q - before_n) / (before_q * current_q)
    outgoing = -old_q * (old_m * before_q - before_n) / (before_q * current_q)
    return {"前N": before_n, "前Q": before_q, "現N": current_n, "現Q": current_q,
        "前F": before_n / before_q, "現F": current_n / current_q, "差": delta, "交差積": cross,
        "I": incoming, "O": outgoing, "新m": new_m, "新q": new_q, "旧m": old_m, "旧q": old_q,
        "分解一致": incoming + outgoing == delta,
        "直接差一致": current_n / current_q - before_n / before_q == delta}


def rename(value: Any, old: str, new: str) -> Any:
    """全属性の識別子断片だけを再帰的に正規化する。

    引数: value(Any)はJSON値、old/new(str)は候補識別子。
    返り値: Anyは価格・時計・数量を変えない新しい値。
    """
    if isinstance(value, dict):
        return {name: rename(item, old, new) for name, item in value.items()}
    if isinstance(value, list):
        return [rename(item, old, new) for item in value]
    return value.replace(old, new) if isinstance(value, str) else value


def dependency_pins() -> dict:
    """42の独立価格/数量/監視と固定追尾の全依存を識別する。

    引数: なし。
    返り値: dict[str,str]はROOT相対pathと現在SHA。43主を数式依存にしない。
    """
    paths = {"scripts/再テスト量方向/状態独立確認.py", "scripts/終値位置/追尾独立確認.py"}
    return dict(sorted({**Y.dependency_pins(), **{name: V.sha(ROOT / name) for name in paths}}.items()))


def shared_bundle(audit: Audit) -> dict:
    """固定29の全使用数値と、42の純入口/全j/監視を限定目的で読む。

    引数: audit(Audit)は全保存物の圧縮/展開SHA・サイズの比較先。
    返り値: dictは数値と純旧A0/旧価格状態。live選別へ旧labelを渡さない。
    """
    bundle = Y.shared_bundle(audit)
    rows, case_sha = saved_rows(ENTRY_STUDY, ENTRY_WORK, "入口事例.jsonl.gz", audit)
    pure = defaultdict(list)
    for row in rows:
        if row["入口ID"] == "3分_A0":
            pure[row["場"]].append({name: deepcopy(row[name]) for name in SIGNAL_FIELDS})
    del rows
    old_j, old_monitor = defaultdict(list), defaultdict(list)
    rows, decision_sha = saved_rows(ENTRY_STUDY, ENTRY_WORK, "発動判定.jsonl.gz", audit)
    for row in rows:
        old_j[row["場"]].append(row)
    del rows
    rows, monitor_sha = saved_rows(ENTRY_STUDY, ENTRY_WORK, "登録監視.jsonl.gz", audit)
    for row in rows:
        old_monitor[row["場"]].append(row)
    return {**bundle, "pure": pure, "old_j": old_j, "old_monitor": old_monitor,
        "共有入口事例展開SHA256": case_sha, "共有旧発動判定展開SHA256": decision_sha,
        "共有旧登録監視展開SHA256": monitor_sha}


def references(study: Path, audit: Audit) -> None:
    """42の純入口/対照と29数値だけを固定正本・成功証明へ結ぶ。

    引数: study(Path)は43、audit(Audit)は比較先。
    返り値: None。旧価格状態も43で再算する責務は別に保持する。
    """
    Y.references(study, audit)
    anchor = "604104ee9546e89e49add20415673020ed816d01f8ae2ef0badefa3cd66bba12"
    audit.check("42固定正本", V.sha(ENTRY_STUDY / "固定.json"), anchor)
    for name, digest in V.read(ENTRY_STUDY / "固定.json")["ファイルSHA256"].items():
        audit.check("42固定現在:" + name, V.sha(ROOT / name), digest)
    for filename in ("入口参照.json", "対照参照.json"):
        ref = V.read(study / filename)
        audit.check(filename + ":試行", ref["参照試行"], "00042")
        audit.check(filename + ":固定", ref["旧固定SHA256"], anchor)
        audit.check(filename + ":複製なし", ref["大明細複製"], False)
        required = {"固定.json", "条件.json", "結果.json", "作業成果物.json", "独立監査.json",
            "状態独立確認.json", "追尾独立確認.json", "入力台帳.json"}
        audit.check(filename + ":証明必須集合", required <= set(ref["文書と証明"]), True)
        for name, item in ref["文書と証明"].items():
            audit.check(filename + ":正本:" + name, (ROOT / item["パス"]).resolve(), (ENTRY_STUDY / name).resolve())
            audit.check(filename + ":SHA:" + name, item["SHA256"], V.sha(ENTRY_STUDY / name))
        for name in ("独立監査.json", "状態独立確認.json", "追尾独立確認.json"):
            proof = V.read(ENTRY_STUDY / name)
            audit.check(filename + ":旧成功:" + name, (proof["全件一致"], proof["不一致数"]), (True, 0))
        expected = V.read(ENTRY_STUDY / "作業成果物.json")["ファイル"]
        if filename == "対照参照.json":
            expected = [row for row in expected if Path(row["パス"]).name in ("全運用詳細.jsonl.gz", "追尾.jsonl.gz")]
            audit.check(filename + ":旧候補", ref["候補ID"], "3分_A0_XF")
        audit.check(filename + ":共有集合", ref["共有明細"], expected)
        for item in expected:
            path = ROOT / item["パス"]
            audit.check(filename + ":圧縮SHA:" + path.name, V.sha(path), item["圧縮SHA256参考"])
            audit.check(filename + ":bytes:" + path.name, path.stat().st_size, item["圧縮バイト"])


def movement_window(rows: list[dict]) -> dict:
    """現/前窓を直接sliceし、精密交差積から差と寄与を作る。

    引数: rows(list[dict])は最大22本の検査済み連続足。
    返り値: dictは主保存schemaの全精密値。途中20本総量0でも補完しない。
    """
    current = Y.cmf_window(rows[-21:])
    previous = Y.cmf_window(rows[:-1] if rows else [])
    ready = len(rows) == 22 and current["CMF準備"] and previous["CMF準備"]
    reasons = []
    if len(rows) != 22:
        reasons.append("同場CMF現前22連続足未準備")
    if not current["CMF準備"]:
        reasons.append("現在CMF21数値未準備")
    if not previous["CMF準備"]:
        reasons.append("前CMF21数値未準備")
    values = pair_values(rows) if ready else None
    incoming = outgoing = None
    if values is not None:
        if not values["分解一致"] or not values["直接差一致"]:
            raise ArithmeticError("交差積の差・直接差・寄与和が不一致")
        incoming = {"足出典": Y.source(rows[-1]), "CLV": exact(values["新m"]), "観測q": exact(values["新q"])}
        outgoing = {"足出典": Y.source(rows[0]), "CLV": exact(values["旧m"]), "観測q": exact(values["旧q"])}
    delta = values["差"] if values is not None else None
    return {"現窓足番号": current["CMF窓足番号"], "前窓足番号": previous["CMF窓足番号"],
        "CMF現前準備": bool(ready), "現前準備除外理由": reasons,
        "CMF現": current["CMF21"], "CMF前": previous["CMF21"], "CMF差": exact(delta),
        "CMF差符号": int(delta > 0) - int(delta < 0) if ready else None,
        "現加重CLV合計": current["加重CLV合計"], "前加重CLV合計": previous["加重CLV合計"],
        "現観測量合計": current["観測量合計"], "前観測量合計": previous["観測量合計"],
        "CMF差交差積": exact(values["交差積"] if values is not None else None),
        "当足寄与I": exact(values["I"] if values is not None else None),
        "窓脱落寄与O": exact(values["O"] if values is not None else None),
        "分解一致": values["分解一致"] if values is not None else None,
        "入足参照": incoming, "落足参照": outgoing,
        "現単位量CLV平均": current["単位量CLV平均"], "前単位量CLV平均": previous["単位量CLV平均"],
        "現窓全量正同値": current["CMF全量正同値"], "前窓全量正同値": previous["CMF全量正同値"]}


def volume_panels(frames: list[dict], session: str) -> list[dict]:
    """数量有効prefixから現前22本を毎回取り直し、全足panelを作る。

    引数: frames(list[dict])は当場3分/Q、session(str)は場。
    返り値: list[dict]は全CMF差/分解。旧価格監視を量欠測で変えない。
    """
    segment, output, previous = [], [], None
    for raw in frames:
        frame = frame_projection(raw)
        if frame["場"] != session or previous is not None and frame["index"] <= previous["index"]:
            raise ValueError("当場の3分strict番号順だけです")
        bad = Y.price_reasons(frame)
        reasons = list(bad)
        if not Y.adjacent(previous, frame):
            reasons.append("価格番号区間公開順非連続")
        quantity = frame["数量参照"]
        amount = quantity.get("観測差分量") if isinstance(quantity, dict) else None
        q_ok = isinstance(quantity, dict) and quantity.get("数量基準完全") is True and finite(amount) and amount >= 0
        width_ok = N.valid_ohlc(frame) and frame["high"] > frame["low"]
        if not q_ok:
            reasons.append("数量基準完全非負未準備")
        if not width_ok:
            reasons.append("CLV幅正未準備")
        if reasons:
            segment = []
        if not bad and q_ok and width_ok:
            segment.append(frame)
        output.append({"場": session, "index": frame["index"], "足出典": Y.source(frame),
            "CMF窓解除理由": reasons, **movement_window(segment[-22:])})
        previous = frame
    return output


def select(block: dict, session: str | None = None) -> dict:
    """再構築又は固定42A0を三D候補へ写し、全旧jの準備・差方向を記録する。

    引数: block(dict)は場/旧純signals/frames/旧j判定、session(str|None)は明示場。
    返り値: dictは同じjの三純集合/全判定/全panel/親metadata。旧labelは参照しない。
    """
    original, contexts, frames = block["signals"]["3分_A0"], block["旧j判定"], block["frames"][3]
    actual_session = session or block.get("場") or (original[0]["場"] if original else None)
    if actual_session is None:
        raise ValueError("空の旧A0にも場を明示してください")
    panels = volume_panels(frames, actual_session)
    panel_by_index = {row["index"]: row for row in panels}
    frame_by_index = {row["index"]: row for row in frames}
    context_ids = [row["発動ID"] for row in contexts]
    if len(context_ids) != len(set(context_ids)):
        raise ValueError("旧j発動IDは一意だけです")
    actual = {row["イベントID"]: row for row in original}
    keys = [(row["要求時計秒"], row["要求原板行"]) for row in original]
    if len(actual) != len(original) or keys != sorted(keys) or len(keys) != len(set(keys)):
        raise ValueError("旧A0は競合後の一意な公開順が必要です")
    expected = {row["発動ID"] + "_A0": Y.pure_signal(row, "A0") for row in contexts if row["戦略判定"]["A0"]["採用"]}
    if actual != expected:
        raise ValueError("旧jと純A0が不一致")
    decisions, metadata = [], {}
    for row in contexts:
        frame, panel = frame_by_index[row["index"]], panel_by_index[row["index"]]
        if row["場"] != actual_session or any(row[name] != frame[name] for name in SOURCE_FIELDS):
            raise ValueError("旧jと保存原足の出典が不一致")
        if (row["要求時計秒"], row["要求原板行"]) != (frame["confirm"], frame["confirm_line"]):
            raise ValueError("旧jの要求keyが不一致")
        old, side, ready = bool(row["戦略判定"]["A0"]["採用"]), row["side"], panel["CMF現前準備"]
        improved = ready and side in (-1, 1) and side * panel["CMF差符号"] > 0
        verdicts = {}
        verdicts["D0"] = {"採用": old, "理由": list(row["戦略判定"]["A0"]["理由"]),
            "同時競合": row["戦略判定"]["A0"].get("同時競合", False)}
        for policy, accepted in (("D1", old and ready), ("D2", old and bool(improved))):
            if not old:
                reasons = ["旧A0不採用"]
            elif not ready:
                reasons = list(panel["現前準備除外理由"])
            elif policy == "D2" and not improved:
                reasons = ["CMF差実方向strict正不成立"]
            else:
                reasons = ["旧A0採用・現前CMF21準備" if policy == "D1" else "旧A0採用・CMF差実方向strict正"]
            verdicts[policy] = {"採用": accepted, "理由": reasons, "同時競合": False}
        identifier = row["発動ID"]
        parent = {"元登録ID": row["登録ID"], "元価格side": row["元価格side"],
            "元登録時計秒": row["登録参照"]["登録足"]["confirm"],
            "元登録原板行": row["登録参照"]["登録足"]["confirm_line"], "判別種別": row["構造区分"]}
        metadata[identifier] = parent
        decisions.append({"場": actual_session, "発動ID": identifier, "元42j発動ID": identifier,
            "元42A0イベントID": identifier + "_A0" if old else None, **deepcopy(parent),
            "index": row["index"], "足終了時計秒": row["end"], "要求時計秒": row["要求時計秒"],
            "要求原板行": row["要求原板行"], "side": side, "役割": row["役割"], "旧A0採用": old,
            "CMF現前参照": deepcopy(panel), "戦略判定": verdicts})
    accepted = {row["元42A0イベントID"]: row for row in decisions if row["旧A0採用"]}
    grouped = {"3分_" + policy: [] for policy in POLICIES}
    for row in original:
        if row["場"] != actual_session:
            raise ValueError("旧A0の場が不一致")
        for policy in POLICIES:
            if accepted[row["イベントID"]]["戦略判定"][policy]["採用"]:
                grouped["3分_" + policy].append(pure_signal(row, policy))
    quality = {"場": actual_session, "時間足分": 3, "旧j判定数": len(contexts), "旧A0純登録数": len(original),
        "旧A0純登録同値": True, "CMF足数": len(panels), "現前CMF準備足数": sum(row["CMF現前準備"] for row in panels),
        "戦略別発動数": {key: len(values) for key, values in grouped.items()},
        "戦略採否理由別": {p: dict(Counter(reason for row in decisions for reason in row["戦略判定"][p]["理由"])) for p in POLICIES}}
    block.update(signals=grouped, decisions=decisions, volume_panels=panels, quality=quality, metadata=metadata)
    return block


# ----------------------------------------
# 旧42の純入口/価格監視を原8列から再構築し、新現前CMFだけを別計算する。


def guarded_inputs(study: Path, work: Path, audit: Audit) -> tuple[dict, dict, dict, Path]:
    """非損益主準備と三案・費用・入力・使用数値版を市場入力前に照合する。

    引数: study/work(Path)は43保存先、audit(Audit)は比較先。
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
    expected = {"ラベル計算": False, "損益計算": False, "全66場既使用": True, "旧A0純登録同値": True, "旧A0登録数": 245,
        "条件SHA256": V.sha(study / "条件.json"), "入力台帳SHA256": V.sha(study / "入力台帳.json"),
        "参照台帳SHA256": V.sha(resolved), "純信号whitelist": list(SIGNAL_FIELDS),
        "指標参照SHA256": V.sha(study / "指標参照.json"),
        "入口参照SHA256": V.sha(study / "入口参照.json"), "対照参照SHA256": V.sha(study / "対照参照.json")}
    for name, value in expected.items():
        audit.check("主準備:" + name, master[name], value)
    paths = {"scripts/CMF変化/" + name for name in ("検証.py", "入口.py", "運用.py")}
    audit.check("主三コード集合", set(master["コードSHA256"]), paths)
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
        "入口参照SHA256": V.sha(study / "入口参照.json"), "対照参照SHA256": V.sha(study / "対照参照.json"),
        "厳密範囲": "原8列由来SOURCE/全数量Q属性/CMF現前/差/交差積/寄与の全分数/固定登録・監視・最初再テスト/時点/全採否/純13原値は厳密。全ATR/Hの別算値はabs1e-10/rel0、ATR正有効/D整数・H符号と全jのδH符号/M/採否はstrict。検算済み保存正本floatを定義とする全3分/判定SHAと、独立再算値の生SHAは区別する。",
        "数値許容": {"対象": ["atr", "macd_hist", "MACDヒスト変化"], "絶対許容": 1e-10, "相対許容": 0,
            "採否epsilon": False, "正本定義SHAと独立生数値SHAを区別": True}}



def check_prepared(study: Path, work: Path, resolved: Path, master: dict, audit: Audit) -> None:
    """成功した独立準備と全固定指紋を正式市場入力前に要求する。

    引数: study/work/resolved(Path)は保存/台帳、master(dict)は主準備、audit(Audit)は比較先。
    返り値: None。古版・未完・差ありは停止する。
    """
    prepared, expected = V.read(work / "独立準備点検.json"), proof_base(study, work, resolved, master, audit)
    for key in ("コードSHA256", "追尾コードSHA256", "依存コードSHA256", "主準備SHA256", "主コードSHA256",
            "条件SHA256", "入力台帳SHA256", "参照入力台帳SHA256", "指標参照SHA256", "入口参照SHA256", "対照参照SHA256"):
        audit.check("準備bind:" + key, prepared[key], expected[key])
    for key, value in {"全件一致": True, "不一致数": 0, "不一致": [], "ラベル計算": False, "損益計算": False}.items():
        audit.check("準備成功:" + key, prepared[key], value)
    for name, digest in V.read(study / "固定.json")["ファイルSHA256"].items():
        audit.check("正式固定現在:" + name, V.sha(ROOT / name), digest)
    if audit.mismatches:
        raise ValueError("準備/固定/現版に差があり正式市場入力前停止")


def reconstruct(manifest: dict, bundle: dict, config: dict) -> Any:
    """原8列から42母監視を再構築した後、同じjへ現前CMFを別計算する。

    引数: manifest/bundle/config(dict)は予約台帳/共有正本/43条件。
    返り値: Anyは非先着/非運用の場別iterator。旧labelを採否へ渡さない。
    """
    old_config = V.read(ENTRY_STUDY / "条件.json")
    for old in Y.reconstruct(manifest, bundle, old_config):
        session, period = old["場"], old["期間"]
        defined, independent = old["_正本数値定義全3分"], old["_再算全3分"]
        old_pure = [deepcopy(row) for row in old["純信号"] if row["入口ID"] == "3分_A0"]
        material = {"場": session, "signals": {"3分_A0": old_pure}, "frames": {3: defined},
            "旧j判定": deepcopy(old["判定"])}
        selected = select(material, session)
        alternate_old = old["_再算判断"]
        alternate_pure = [Y.pure_signal(row, "A0") for row in alternate_old["signals"]["3分_A0"]]
        alternate = select({"場": session, "signals": {"3分_A0": alternate_pure}, "frames": {3: independent},
            "旧j判定": deepcopy(alternate_old["decisions"])}, session)
        pure = [row for policy in POLICIES for row in selected["signals"]["3分_" + policy]]
        yield {"場": session, "期間": period, "純信号": pure, "純信号内容SHA256": canonical_sha(pure),
            "純信号判断SHA256": canonical_sha([decision_signal(row) for row in pure]),
            "判定": selected["decisions"], "判定SHA256": canonical_sha(selected["decisions"]),
            "判定判断SHA256": canonical_sha(selected["decisions"]),
            "全3分投影SHA256": canonical_sha(defined), "3分投影足数": len(defined), "入力品質": selected["quality"],
            "全CMF投影SHA256": canonical_sha(selected["volume_panels"]), "CMF足数": len(selected["volume_panels"]),
            "_old42": old, "_旧A0純": old_pure, "_再算全3分": independent, "_正本数値定義全3分": defined,
            "_正本判断": selected, "_再算判断": alternate, "_metadata": selected["metadata"]}


def compare_preparation(main: dict, block: dict, bundle: dict, audit: Audit) -> dict:
    """全数量/価格/42状態と、新差/分解/採否/正本SHAを厳密範囲別に比較する。

    引数: main/block(dict)は主/独立場、bundle(dict)は共有正本、audit(Audit)は比較先。
    返り値: dictは旧監視・全新数値・三集合・数値表現差の要約。
    """
    session, period, old = block["場"], block["期間"], block["_old42"]
    independent, original = block["_再算全3分"], bundle["lower"][session]
    audit.check(session + ":原8列SOURCE/全Q/ATR/H", independent, original)
    audit.check(session + ":原8列再構築42全j", [{"期間": period, **row} for row in old["判定"]], bundle["old_j"].get(session, []))
    audit.check(session + ":原8列再構築42全j厳密", [{"期間": period, **row} for row in old["判定"]] == bundle["old_j"].get(session, []), True)
    audit.check(session + ":原8列再構築42全監視", [{"期間": period, **row} for row in old["監視"]], bundle["old_monitor"].get(session, []))
    audit.check(session + ":原8列再構築42全監視厳密", [{"期間": period, **row} for row in old["監視"]] == bundle["old_monitor"].get(session, []), True)
    audit.check(session + ":原8列再構築42A0純13", block["_旧A0純"], bundle["pure"].get(session, []))
    audit.check(session + ":旧A0純13現ATR含む厳密", block["_旧A0純"] == bundle["pure"].get(session, []), True)
    expected_record = {name: value for name, value in block.items() if not name.startswith("_")}
    audit.check(session + ":全現前CMF/差/分解/採否/出典", main, expected_record)
    audit.check(session + ":全正本定義厳密JSON", main == expected_record, True)
    audit.check(session + ":独立数値で42全監視/全採否strict",
        Y.numerical_judgment(old["_再算判断"]), Y.numerical_judgment(old["_正本判断"]))
    same = Y.numerical_judgment(block["_再算判断"]) == Y.numerical_judgment(block["_正本判断"])
    audit.check(session + ":再算数値の新D全採否strict", same, True)
    for actual, other in zip(old["判定"], old["_再算判断"]["decisions"]):
        audit.check(actual["発動ID"] + ":独立現前差:MACDヒスト変化", other["MACDヒスト変化"], actual["MACDヒスト変化"])
    old_ids = {row["イベントID"]: row for row in block["_旧A0純"]}
    ids = {p: {row["イベントID"][:-3] + "_A0" for row in main["純信号"] if row["入口ID"] == "3分_" + p} for p in POLICIES}
    audit.check(session + ":D0全旧A0集合", ids["D0"], set(old_ids))
    audit.check(session + ":D1準備subsetD0", ids["D1"] <= ids["D0"], True)
    audit.check(session + ":D2変化subsetD1", ids["D2"] <= ids["D1"], True)
    for signal in main["純信号"]:
        policy, origin = signal["入口ID"].removeprefix("3分_"), signal["イベントID"][:-3] + "_A0"
        audit.check(signal["イベントID"] + ":純13列集合", set(signal), set(SIGNAL_FIELDS))
        audit.check(signal["イベントID"] + ":旧j全13値厳密", signal == pure_signal(old_ids[origin], policy), True)
    panels = block["_正本判断"]["volume_panels"]
    for panel in panels:
        if panel["CMF現前準備"]:
            actual = fraction_value(panel["CMF差"])
            left, right = fraction_value(panel["当足寄与I"]), fraction_value(panel["窓脱落寄与O"])
            denominator = fraction_value(panel["現観測量合計"]) * fraction_value(panel["前観測量合計"])
            audit.check(session + f":{panel['index']}:I+O精密一致", actual == left + right, True)
            audit.check(session + f":{panel['index']}:交差積精密一致", actual == fraction_value(panel["CMF差交差積"]) / denominator, True)
    differences = {name: [abs(a[name] - b[name]) for a, b in zip(independent, original, strict=True)
        if finite(a[name]) and finite(b[name]) and a[name] != b[name]] for name in ("atr", "macd_hist")}
    return {"場": session, "期間": period, **{p + "登録数": len(ids[p]) for p in POLICIES},
        "旧突破登録数": len(old["登録"]), "旧全j数": len(old["判定"]), "旧監視足数": len(old["監視"]),
        "3分投影足数": len(original), "CMF足数": len(panels), "現前CMF準備足数": sum(row["CMF現前準備"] for row in panels),
        "全3分投影SHA256": block["全3分投影SHA256"], "独立再算全3分内容SHA256": canonical_sha(independent),
        "全CMF投影SHA256": block["全CMF投影SHA256"], "全判定SHA256": block["判定SHA256"],
        **{name + "表現差足数": len(values) for name, values in differences.items()},
        **{name + "最大絶対差": max(values, default=0.0) for name, values in differences.items()},
        "再算数値判断不一致場": int(not same)}


def numeric_summary(stages: list[dict]) -> dict:
    """42母監視と新CMF差/寄与の検算範囲を別に集計する。

    引数: stages(list[dict])は場別比較要約。
    返り値: dictは全足/旧登録/旧j/全新CMFと限定許容の表現差。
    """
    return {"新3分全数値照合足数": sum(row["3分投影足数"] for row in stages),
        "全数量属性照合足数": sum(row["3分投影足数"] for row in stages),
        "再構築42突破登録数": sum(row["旧突破登録数"] for row in stages),
        "再構築42全j数": sum(row["旧全j数"] for row in stages),
        "再構築42監視足数": sum(row["旧監視足数"] for row in stages),
        "全CMF現前照合足数": sum(row["CMF足数"] for row in stages),
        "精密差分解照合足数": sum(row["現前CMF準備足数"] for row in stages),
        "独立数値判断不一致場数": sum(row["再算数値判断不一致場"] for row in stages),
        **{"独立" + name + "表現差足数": sum(row[name + "表現差足数"] for row in stages) for name in ("atr", "macd_hist")},
        **{"独立" + name + "最大絶対差": max((row[name + "最大絶対差"] for row in stages), default=0.0) for name in ("atr", "macd_hist")}}


def prepare(study: Path, work: Path) -> dict:
    """root起動で42母集合と新現前CMF三案を非損益検算する。

    引数: study/work(Path)は43保存先。
    返り値: dictは旧label/新先着/運用/PnLを計算しない独立準備証明。
    """
    audit, initial = Audit(), V.sha(Path(__file__))
    config, manifest, master, resolved = guarded_inputs(study, work, audit)
    bundle, stages = shared_bundle(audit), []
    for main_record, block in zip(master["準備"], reconstruct(manifest, bundle, config), strict=True):
        stages.append(compare_preparation(main_record, block, bundle, audit))
        print(json.dumps({"場": block["場"], "独立準備": "原Q/OHLC/ATR/H・42母監視・現前CMF/交差積/I/O/全D", "不一致数": audit.mismatches}, ensure_ascii=False), flush=True)
    count = sum(row["D0登録数"] for row in stages)
    audit.check("旧42A0全245", count, 245)
    audit.check("主旧42A0数", master["旧A0登録数"], count)
    audit.check("独立実行中コード不変", V.sha(Path(__file__)), initial)
    proof = {**proof_base(study, work, resolved, master, audit), "ラベル計算": False, "損益計算": False,
        "全66場既使用": True, "旧A0純登録同値": audit.mismatches == 0, "旧A0登録数": count,
        "場別準備": stages, **numeric_summary(stages), "方針別登録数": {p: sum(row[p + "登録数"] for row in stages) for p in POLICIES},
        **{name: value for name, value in bundle.items() if name.endswith("展開SHA256")},
        "検証範囲": "原8列から3分OHLC/Q全属性/ATR/Hと固定42全b/監視/最初jを再構築して旧A0純13へ照合。22足を別sliceし、CMF現前/交差積由来差/入足と落足寄与/全三採否を精密検算。正本float定義SHAと独立再算数値の判断影響は別確認。",
        "限界": "非先着/非運用/非PnL。旧42caseは直ちに純13へ射影し、旧labelをliveへ渡さない。I/Oは診断だけで採否に使わない。全66場既使用。"}
    (work / "独立準備点検.json").write_text(json.dumps(proof, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({key: proof[key] for key in ("全件一致", "照合項目数", "不一致数", "旧A0登録数", "方針別登録数")}, ensure_ascii=False))
    return proof


def run(study: Path, work: Path) -> dict:
    """正式後に全判定/全新先着と旧42A0全属性対照を別に検算する。

    引数: study/work(Path)は43保存先。
    返り値: dictは新四明細/共有旧先着/全属性対照へbindする状態証明。
    """
    if not (study / "固定.json").exists() or not (study / "結果.json").exists():
        raise ValueError("root固定・正式完了後だけです")
    audit, initial = Audit(), V.sha(Path(__file__))
    config, manifest, master, resolved = guarded_inputs(study, work, audit)
    check_prepared(study, work, resolved, master, audit)
    bundle = shared_bundle(audit)
    old_rows, _ = saved_rows(ENTRY_STUDY, ENTRY_WORK, "入口事例.jsonl.gz", audit)
    old_cases = {row["イベントID"]: row for row in old_rows if row["入口ID"] == "3分_A0"}
    old_rows, _ = saved_rows(ENTRY_STUDY, ENTRY_WORK, "全運用詳細.jsonl.gz", audit)
    old_details = {row["場"]: row for row in old_rows if row["候補ID"] == "3分_A0_XF"}
    old_rows, _ = saved_rows(ENTRY_STUDY, ENTRY_WORK, "追尾.jsonl.gz", audit)
    old_logs = defaultdict(list)
    for row in old_rows:
        if row["候補ID"] == "3分_A0_XF":
            old_logs[row["場"]].append(row)
    names = ("発動判定", "入口事例", "全運用詳細", "追尾")
    saved, hashes, grouped = {}, {}, {name: defaultdict(list) for name in names}
    for name in names:
        saved[name], hashes[name] = saved_rows(study, work, name + ".jsonl.gz", audit)
        for row in saved[name]:
            grouped[name][row["場"]].append(row)
    audit.check("新四成果物集合", {Path(row["パス"]).name for row in V.read(study / "作業成果物.json")["ファイル"]}, {name + ".jsonl.gz" for name in names})
    pairs = [(row["場"], row["候補ID"]) for row in saved["全運用詳細"]]
    audit.check("場候補一意", len(pairs), len(set(pairs)))
    audit.check("全3x66", set(pairs), {(entry["session"], cid) for entry in manifest["entries"] for cid in OPERATIONS})
    audit.check("全case一意", len(saved["入口事例"]), len({row["イベントID"] for row in saved["入口事例"]}))
    stages, controls, counts = [], [], {p: 0 for p in POLICIES}
    role_counts = {p: {role: 0 for role in ("順行", "反転")} for p in POLICIES}
    entries = {row["session"]: row for row in manifest["entries"]}
    for main_record, block in zip(master["準備"], reconstruct(manifest, bundle, config), strict=True):
        stages.append(compare_preparation(main_record, block, bundle, audit))
        session, period = block["場"], block["期間"]
        expected_rows = [{"期間": period, **row} for row in block["判定"]]
        audit.check(session + ":正式全jの現前判定", grouped["発動判定"][session], expected_rows)
        audit.check(session + ":正式全j厳密", grouped["発動判定"][session] == expected_rows, True)
        cases = {row["イベントID"]: row for row in grouped["入口事例"][session]}
        audit.check(session + ":全case純集合", set(cases), {row["イベントID"] for row in block["純信号"]})
        quotes = normal_columns(entries[session], manifest)
        _, _, cutoff, deadline = S.G.times(session)
        for signal in block["純信号"]:
            event, original = signal["イベントID"][:-3], signal["イベントID"][:-3] + "_A0"
            direct = label_direct(quotes, signal, cutoff, deadline)
            expected = {**deepcopy(signal), "期間": period,
                "要求時計JST": datetime.fromtimestamp(signal["要求時計秒"], timezone(timedelta(hours=9))).isoformat(),
                "元価格発動ID": event, **deepcopy(block["_metadata"][event]), "旧A0イベントID": original, **direct}
            audit.check(signal["イベントID"] + ":全新case原BBO直接先着", cases.get(signal["イベントID"]), expected)
            audit.check(signal["イベントID"] + ":全case厳密", cases.get(signal["イベントID"]) == expected, True)
            audit.check(signal["イベントID"] + ":旧同時計A0の11label形式対応", direct, {name: old_cases[original][name] for name in LABEL_FIELDS})
            policy = signal["入口ID"].removeprefix("3分_")
            counts[policy] += 1
            role_counts[policy][signal["役割"]] += 1
        for detail in grouped["全運用詳細"][session]:
            audit.check(detail["候補ID"] + session + ":期間", detail["品質"]["期間"], period)
            if detail["候補ID"] == "3分_D0_XF":
                logs = [row for row in grouped["追尾"][session] if row["候補ID"] == detail["候補ID"]]
                adapted, adapted_logs = rename(detail, "_D0", "_A0"), rename(logs, "_D0", "_A0")
                audit.leaf(session + ":旧42A0全ledger同値", adapted, old_details[session], adapted == old_details[session])
                audit.leaf(session + ":旧42A0全trace同値", adapted_logs, old_logs[session], adapted_logs == old_logs[session])
                controls.append({"場": session, "候補ID": detail["候補ID"], "全運用同値": adapted == old_details[session],
                    "全追尾同値": adapted_logs == old_logs[session], "旧識別子全運用内容SHA256": canonical_sha(adapted),
                    "旧識別子追尾内容SHA256": canonical_sha(adapted_logs)})
        print(json.dumps({"場": session, "独立状態": "原8列42母監視・現前CMF/差/I/O・全case直接先着・旧A0対照", "不一致数": audit.mismatches}, ensure_ascii=False), flush=True)
    result = V.read(study / "結果.json")
    for key, expected in {"全66場既使用": True, "入口評価数": 3, "運用候補数": 3, "現方針運用候補数": 3,
            "入口125250評価の変更": False, "表示固定ID": list(OPERATIONS)}.items():
        audit.check("正式結果:" + key, result[key], expected)
    for row in result["入口評価"]:
        audit.check(row["入口ID"] + ":集合役割", row["役割"], "切替")
    role_groups = [(row["入口ID"], row["役割"]) for row in result["役割別入口評価"]]
    audit.check("全三案実二役割6群", set(role_groups), {("3分_" + p, role) for p in POLICIES for role in ("順行", "反転")})
    audit.check("役割群一意", len(role_groups), len(set(role_groups)))
    audit.check("全case数", len(saved["入口事例"]), sum(counts.values()))
    audit.check("D0旧A0全245", counts["D0"], len(old_cases))
    audit.check("D0保存全属性対照", V.read(study / "D0対照同値.json"), {"全件一致": True, "旧先着全件同値": True,
        "場候補数": len(controls), "照合": controls, "入口参照SHA256": V.sha(study / "入口参照.json"),
        "対照参照SHA256": V.sha(study / "対照参照.json")})
    audit.check("独立実行中コード不変", V.sha(Path(__file__)), initial)
    proof = {**proof_base(study, work, resolved, master, audit), "場別準備": stages, **numeric_summary(stages),
        "旧A0登録数": counts["D0"], "方針別case数": counts, "方針実役割別case数": role_counts,
        "全先着直接照合件数": sum(counts.values()), "方針別先着直接照合件数": counts,
        "旧同時計実方向先着照合数": sum(counts.values()), "旧42全属性同値場数": len(controls),
        "保存発動判定数": len(saved["発動判定"]), "保存入口事例数": len(saved["入口事例"]),
        "保存運用詳細数": len(saved["全運用詳細"]), "保存追尾数": len(saved["追尾"]),
        "成果物照合": {name + ".jsonl.gz": {"展開内容SHA256": hashes[name], "行数": len(saved[name])} for name in names},
        **{name + "展開SHA256": digest for name, digest in hashes.items()},
        **{name: value for name, value in bundle.items() if name.endswith("展開SHA256")},
        "結果SHA256": V.sha(study / "結果.json"), "固定SHA256": V.sha(study / "固定.json"),
        "独立準備SHA256": V.sha(work / "独立準備点検.json"),
        "検証範囲": "原8列で全OHLC/Q/ATR/H/42登録監視/全j/A0純245を再構築。新22足CMF現前/交差積差/I+O/三採否を別算。全新caseを実方向の原BBOから直接125/250検算し、旧A0の11label形式対応とD0全66ledger/trace同値を別確認する。",
        "限界": "旧labelを新判断へ渡さず、I/Oを採否に使わない。新規受付/最初約定/Decimalは別会計、全実保有/最初返済要求は別追尾。全66場既使用、未予約11/5Day未読。"}
    (work / "状態独立確認.json").write_text(json.dumps(proof, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({key: proof[key] for key in ("全件一致", "照合項目数", "不一致数", "旧A0登録数", "方針別case数")}, ensure_ascii=False))
    return proof


def main() -> None:
    """rootの非損益準備許可又は正式完了後だけ明示CLIを起動する。

    引数: なし。--study/--work/--prepare/--実行許可を読む。
    返り値: None。無指定又は不一致は非0終了する。
    """
    parser = argparse.ArgumentParser(description="00043旧再テストと現前CMF変化の独立検算")
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

