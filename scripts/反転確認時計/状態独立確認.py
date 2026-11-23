"""00026の固定価格/SARと、反転の新しい確認時計を原OHLCから独立検算する。"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from copy import deepcopy
import importlib.util
import hashlib
import json
import math
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT / "study/00026_反転のSAR確認時刻と順行持続"
WORK = ROOT / "work/反転確認時計/00026"
INPUT = ROOT / "study/00008_外部研究を共通尺度へ移して探索/入力台帳.json"
PRICE_HELPER = ROOT / "scripts/SAR持続/状態独立確認.py"
OLD_WORK = ROOT / "work/SAR持続/00025"
POLICIES = ("N0", "N1", "N2")
PREPARE_FIELDS = ("発動ID", "入口系統", "役割", "side", "要求時計秒", "要求原板行", "足終了時計秒", "期限時計秒",
    "close", "atr", "共通M26準備", "M除外理由", "時間条件可", "確認遅延条件可", "先着評価対象",
    "f起点参照", "f起点発動ID", "反転確認種別", "h価格条件可", "固定設定", "戦略判定")


def helper(path: Path, name: str) -> Any:
    """固定25の独立OHLC/SAR/価格監視だけを読取再用する。

    引数: path (Path) は独立補助、name (str) はモジュール名。
    返り値: Any は補助。26主入口/指標/運用をimportしない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


B = helper(PRICE_HELPER, "反転確認時計の固定25独立価格SAR")
V, S = B.V, B.S


# ----------------------------------------
# 親価格状態の確定済み区間からfを先列挙し、後続hを別の区間走査で一度だけ求める。

def reaction_paths(block: dict) -> list[dict]:
    """最初のfごとに親価格終了を切断位置として、最初の公開SAR一致を探す。

    引数: block (dict) は独立25の全足/context/価格raw/監視。
    返り値: list[dict] はf起点の即時/登録/後続訪問/消費/失効。先着ラベル/損益を使わない。
    """
    frames = block["価格足"][3]
    positions = {frame["index"]: position for position, frame in enumerate(frames)}
    trace = {record["index"]: record for record in block["監視"]}
    paths = []
    for first in (row for row in block["全raw"].values() if row["入口系統"] == "R内復帰"):
        position, side, episode = positions[first["index"]], first["side"], first["エピソードID"]
        immediate = first["SAR現在有効"] and first["SAR現方向"] == side
        path = {"f": first, "開始位置": position, "即時": immediate, "訪問": [], "h位置": None,
            "終了位置": position if immediate else len(frames) - 1,
            "終了理由": "f即時SAR確認消費" if immediate else "場末尾反転監視終了"}
        if not immediate:
            for current_position in range(position + 1, len(frames)):
                frame, ctx = frames[current_position], block["全context"][frames[current_position]["index"]]
                parent = trace[frame["index"]]
                before = parent["監視前"]
                after = parent["監視後"]
                age = frame["index"] - first["index"]
                visit = {"位置": current_position, "経過本数": age, "動作": "継続", "親終了理由": None}
                reason = None
                if before is None or before["エピソードID"] != episode:
                    reason = "親価格監視なし"
                elif after is None or after["エピソードID"] != episode:
                    parent_end = next((action["理由"] for action in parent["動作"] if action["動作"] in ("監視終了", "監視満了")), "親価格監視終了")
                    reason = "価格外回復先着" if parent_end == "外回復価格消費" else parent_end
                    visit["親終了理由"] = parent_end
                elif frame["confirm"] >= block["期限"]:
                    reason = "返済期限"
                elif age > 3:
                    reason = "後続三足満了"
                elif frame["end"] <= first["confirm"] or (frame["confirm"], frame["confirm_line"]) <= (first["confirm"], first["confirm_line"]):
                    visit["動作"] = "時点対象外"
                elif ctx["SAR現在有効"] and ctx["SAR現方向"] == side:
                    path["h位置"] = current_position
                    reason = "後続SAR確認消費"
                    visit["h価格条件可"] = first["固定設定"]["L"] < frame["close"] < first["固定設定"]["R"]
                if reason is not None:
                    visit["動作"] = reason
                path["訪問"].append(visit)
                if reason is not None:
                    path["終了位置"], path["終了理由"] = current_position, reason
                    break
        paths.append(path)
    return paths

def foot_reference(row: dict) -> dict:
    """現在又はfの時点/価格/ATRだけを固定出典へ抽出する。

    引数: row (dict) は当時足/価格イベント。
    返り値: dict は七つの時点/価格項目。ラベルや将来状態を入れない。
    """
    return {key: row[key] for key in ("index", "start", "end", "confirm", "confirm_line", "close", "atr")}


def verdicts(context: dict, family: str, side: int, inside: bool = True) -> dict:
    """共通準備から反転即時/後続と共通順行を三案別に判定する。

    引数: context (dict) は当時M26、family (str) はf/g/h、side (int) は実方向、inside (bool) はh帯内。
    返り値: dict は全N採否/理由。後続対象外を時間/準備不足と別に保存する。
    """
    common = list(context["M除外理由"])
    if not context["時間条件可"]:
        common.append("要求時間条件外")
    current = bool(context["SAR現在有効"] and context["SAR現方向"] == side)
    change = context["MACDヒスト変化"]
    momentum = B.B.S.S.finite(change) and side * change > 0
    persistence = context["SAR現前準備"] and context["SAR現方向"] == context["SAR前方向"] == side
    output = {}
    for policy in POLICIES:
        reasons = list(common)
        if family == "T外回復":
            reasons += [] if persistence else ["実方向SAR二本持続不成立"]
            success = "価格外回復と実方向SAR二本持続採用"
        elif family == "R内復帰":
            if policy == "N0":
                reasons += [] if momentum else ["実方向MACD勢い不成立"]
                success = "価格内復帰と実方向MACD採用"
            else:
                reasons += [] if current else ["現在公開SAR実方向不成立"]
                success = "価格内復帰と現在公開SAR採用"
        elif family == "R方向確認":
            if policy != "N2":
                reasons.append("後続hは当案対象外")
            if not inside:
                reasons.append("SAR確認時の終値が固定範囲内でない")
            if not current:
                reasons.append("現在公開SAR実方向不成立")
            success = "内復帰後の公開SAR方向確認採用"
        else:
            raise ValueError("独立Nの未知系統")
        output[policy] = {"採用": not reasons, "理由": reasons or [success], "同時競合": False}
    return output


def watch_seed(path: dict, number: int) -> dict:
    """fに確定した情報だけから反転待機snapshotを作る。

    引数: path (dict) は独立f区間、number (int) は診断番号。
    返り値: dict は当時の固定f/価格設定。後続h位置や終了理由を含めない。
    """
    first = path["f"]
    return {"エピソードID": first["エピソードID"], "f発動ID": first["発動ID"], "r": first["side"],
        "R": first["固定設定"]["R"], "L": first["固定設定"]["L"], "f": foot_reference(first),
        "価格設定": deepcopy(first["固定設定"]), "診断番号": number}


def later_signal(context: dict, watch: dict, session: str, deadline: float) -> dict:
    """初SAR一致hを新しい公開価格/ATRとf出典を持つ原イベントへ変換する。

    引数: context/watch (dict) は現在情報/固定f、session (str) は場、deadline (float) は期限。
    返り値: dict はh技術イベント。strict範囲外でも保存し採否だけを不可にする。
    """
    event, side = watch["f発動ID"] + "_後続SAR確認", watch["r"]
    inside = watch["L"] < context["close"] < watch["R"]
    fixed = {**deepcopy(watch["価格設定"]), "段階": "外回復待ち", "内復帰": deepcopy(watch["f"])}
    return {**deepcopy(context), "場": session, "時間足分": 3, "入口系統": "R方向確認", "役割": "反転",
        "side": side, "方向": "買い" if side == 1 else "売り", "発動ID": event, "QイベントID": event,
        "イベントID": event, "入口ID": "3分_R方向確認", "要求時計秒": context["confirm"],
        "要求原板行": context["confirm_line"], "確認遅延秒": context["confirm"] - context["end"],
        "足終了時計秒": context["end"], "期限時計秒": deadline,
        "残り分_判断時": (deadline - context["confirm"]) / 60,
        "先着評価対象": bool(context["時間条件可"] and context["確認遅延条件可"]),
        "元突破side": -side, "エピソードID": watch["エピソードID"], "固定設定": fixed,
        "f起点参照": deepcopy(watch["f"]), "f起点発動ID": watch["f発動ID"], "反転確認種別": "後続h",
        "h価格条件可": inside, "旧25戦略判定": None,
        "戦略判定": verdicts(context, "R方向確認", side, inside)}


def transform(block: dict) -> dict:
    """区間探索で確定したhだけを足監視/診断/原集合へ投影して全Nを確定する。

    引数: block (dict) は固定25独立価格/SAR/旧採否。
    返り値: dict は新context/原集合/全N純集合/親と反転監視/品質を持つ場別情報。
    """
    session, phase, frames = block["場"], block["期間"], block["価格足"][3]
    paths = reaction_paths(block)
    contexts = {index: {**deepcopy(row), "共通M26準備": row["共通M25準備"]} for index, row in block["全context"].items()}
    raw, cases = {}, {}
    for key, old in block["全raw"].items():
        row = {**deepcopy(old), **deepcopy(contexts[old["index"]]), "旧25戦略判定": deepcopy(old["戦略判定"])}
        row["戦略判定"] = verdicts(row, row["入口系統"], row["side"])
        row["反転確認種別"] = "f即時" if row["入口系統"] == "R内復帰" and row["SAR現在有効"] and row["SAR現方向"] == row["side"] else None
        row["h価格条件可"] = True if row["入口系統"] == "R内復帰" else None
        raw[key] = row
    before, after, actions, diagnostics = {}, {}, defaultdict(list), []
    for number, path in enumerate(paths):
        first, begin = path["f"], path["開始位置"]
        watch = watch_seed(path, number)
        diagnostic = {"エピソードID": watch["エピソードID"], "f発動ID": watch["f発動ID"] , "r": watch["r"],
            "f": deepcopy(watch["f"]), "確認種別": None, "確認発動ID": None, "確認足": None,
            "h価格条件可": None, "終了理由": None, "終了時計秒": None, "終了原板行": None}
        actions[begin].append({"動作": "反転候補登録", "f発動ID": first["発動ID"]})
        if path["即時"]:
            actions[begin].append({"動作": "f即時SAR確認消費", "発動ID": first["発動ID"],
                "戦略採否": deepcopy(raw[first["発動ID"]]["戦略判定"])})
            diagnostic.update(確認種別="f即時", 確認発動ID=first["発動ID"], 確認足=foot_reference(first),
                h価格条件可=True, 終了理由="f即時SAR確認消費", 終了時計秒=first["confirm"], 終了原板行=first["confirm_line"])
            after[begin] = None
        else:
            actions[begin].append({"動作": "後続SAR確認待ち"})
            after[begin] = deepcopy(watch)
            for visit in path["訪問"]:
                position, action = visit["位置"], visit["動作"]
                context = contexts[frames[position]["index"]]
                before[position] = deepcopy(watch)
                if action == "時点対象外":
                    actions[position].append({"動作": "後続確認時点対象外", "理由": "end又はkeyがf公開より後でない", "経過本数": visit["経過本数"]})
                    after[position] = deepcopy(watch)
                elif action == "継続":
                    after[position] = deepcopy(watch)
                elif action == "後続SAR確認消費":
                    row = later_signal(context, watch, session, block["期限"])
                    raw[row["発動ID"]] = row
                    actions[position].append({"動作": "後続SAR確認消費", "発動ID": row["発動ID"],
                        "h価格条件可": row["h価格条件可"], "戦略採否": deepcopy(row["戦略判定"])})
                    diagnostic.update(確認種別="後続h", 確認発動ID=row["発動ID"], 確認足=foot_reference(context),
                        h価格条件可=row["h価格条件可"], 終了理由=action, 終了時計秒=context["confirm"], 終了原板行=context["confirm_line"])
                    after[position] = None
                else:
                    actions[position].append({"動作": "反転監視取消", "理由": action})
                    diagnostic.update(終了理由=action, 終了時計秒=context["confirm"], 終了原板行=context["confirm_line"])
                    after[position] = None
            if diagnostic["終了理由"] is None:
                diagnostic["終了理由"] = "場末尾反転監視終了"
        diagnostics.append(diagnostic)
    # ----------------------------------------
    # 原集合は足時計順で並べ、全戦略競合を確定してから各caseを深複写する。
    raw = dict(sorted(raw.items(), key=lambda item: (item[1]["要求時計秒"], item[1]["要求原板行"])))
    selected = defaultdict(list)
    for row in raw.values():
        for policy in POLICIES:
            if row["戦略判定"][policy]["採用"]:
                selected[policy, row["要求時計秒"], row["要求原板行"]].append(row)
    for (policy, _, _), local in selected.items():
        if len(local) > 1:
            for row in local:
                row["戦略判定"][policy] = {"採用": False, "理由": ["同判断複数信号見送り"], "同時競合": True}
    for row in raw.values():
        for policy in POLICIES:
            if row["戦略判定"][policy]["採用"]:
                event = row["発動ID"] + "_" + policy
                cases[event] = {**deepcopy(row), "入口ID": "3分_" + policy, "戦略": policy,
                    "複合判定": deepcopy(row["戦略判定"][policy]), "イベントID": event}
    trace = [{"場": session, "index": frame["index"], "時計秒": frame["confirm"], "原板行": frame["confirm_line"],
        "反転監視前": deepcopy(before.get(position)), "動作": actions[position], "反転監視後": deepcopy(after.get(position))}
        for position, frame in enumerate(frames)]
    price_trace = deepcopy(block["監視"])
    for record in price_trace + trace:
        for action in record["動作"]:
            if "戦略採否" in action:
                action["戦略採否"] = deepcopy(raw[action["発動ID"]]["戦略判定"])
    counts = stage_counts(block, contexts, raw, cases, trace, diagnostics)
    return {**block, "全context": contexts, "全raw": raw, "全採用": cases, "監視": price_trace,
        "反転監視": trace, "反転監視診断": diagnostics, "段階件数": counts}

# ----------------------------------------
# 共通準備/親価格の件数を固定し、追加hと三案の選別だけを新しく集計する。

def stage_counts(block: dict, contexts: dict, raw: dict, cases: dict,
                 trace: list[dict], diagnostics: list[dict]) -> dict:
    """全価格段階と反転確認時計/三案集合をラベルなしで集計する。

    引数: block/contexts/raw/cases (dict) は元基礎と新集合、trace/diagnostics (list[dict]) は新反転監視。
    返り値: dict は主prepareと比較する段階品質。先着数値/売買結果を参照しない。
    """
    quality = deepcopy(block["段階件数"])
    actions = Counter(action["動作"] for record in trace for action in record["動作"])
    quality.update(固定25価格イベント数=len(block["全raw"]),
        後続h原イベント数=sum(row["入口系統"] == "R方向確認" for row in raw.values()),
        反転候補登録数=len(diagnostics), f即時SAR確認数=actions["f即時SAR確認消費"],
        後続SAR待機開始数=actions["後続SAR確認待ち"], 後続SAR確認消費数=actions["後続SAR確認消費"],
        後続確認時点対象外足数=actions["後続確認時点対象外"],
        h元端等号不採用数=sum(row["入口系統"] == "R方向確認" and not row["h価格条件可"] for row in raw.values()),
        反転監視動作別=dict(actions), 反転監視終了理由別=dict(Counter(row["終了理由"] for row in diagnostics)),
        イベントM除外理由別=dict(Counter(reason for row in raw.values() for reason in row["M除外理由"])),
        戦略採否理由別={policy: dict(Counter(reason for row in raw.values() for reason in row["戦略判定"][policy]["理由"])) for policy in POLICIES},
        戦略別役割発動数={"3分_" + policy: dict(Counter(row["役割"] for row in cases.values() if row["戦略"] == policy)) for policy in POLICIES},
        戦略別発動数={"3分_" + policy: sum(row["戦略"] == policy for row in cases.values()) for policy in POLICIES})
    quality["イベント段階"] = []
    for family in ("R内復帰", "T外回復", "R方向確認"):
        local = [row for row in raw.values() if row["入口系統"] == family]
        quality["イベント段階"].append({"系統": family, "役割": "順行" if family == "T外回復" else "反転",
            "原イベント数": len(local), "時間可数": sum(row["時間条件可"] for row in local),
            "確認遅延可数": sum(row["確認遅延条件可"] for row in local),
            "先着評価対象数": sum(row["先着評価対象"] for row in local),
            "M26時間通過数": sum(row["共通M26準備"] and row["時間条件可"] for row in local),
            **{policy + "採用数": sum(row["戦略判定"][policy]["採用"] for row in local) for policy in POLICIES}})
    quality["先着評価対象外数"] = sum(not row["先着評価対象"] for row in raw.values())
    projection = [{key: row.get(key) for key in PREPARE_FIELDS} for row in raw.values()]
    quality.update(全原発動投影内容SHA256=canonical_sha(projection),
        反転監視内容SHA256=canonical_sha(trace), 反転診断内容SHA256=canonical_sha(diagnostics),
        ATR検算列=atr_leaves(projection, "原発動") + atr_leaves(trace, "反転監視") + atr_leaves(diagnostics, "反転診断"),
        ATR全足検算列=[{"index": frame["index"], "値": frame["atr"], **atr_integers(frame["atr"])} for frame in block["価格足"][3]])
    return quality


def reconstruct(manifest: dict, config: dict, audit: Any) -> Any:
    """固定65場の原OHLC/SAR/親監視から新しい確認時計とN三案を再構成する。

    引数: manifest/config (dict) は固定入力/26条件、audit (Any) は照合先。
    返り値: Any は場別iterator。固定manifest外の新しい場は列挙/参照しない。
    """
    for block in B.reconstruct(manifest, config, audit):
        yield transform(block)

# ----------------------------------------
# 固定前は純技術列と全反転監視をcanonical指紋でも照合し、先着/P&Lは開かない。

def atr_integers(value: Any) -> dict:
    """ATRの正有効性と5pt格子の登録幅/追尾幅を整数へ写す。

    引数: value (Any) は原ATR又は欠測。
    返り値: dict は正有効boolとε/Dのpt整数。不正値を価格へ補完しない。
    """
    valid = isinstance(value, (int, float)) and math.isfinite(value) and value > 0
    return {"ATR正有効": bool(valid), "登録εpt整数": max(5, math.ceil(.25 * value / 5) * 5) if valid else None,
        "追尾Dpt整数": max(5, math.ceil(value / 5) * 5) if valid else None}


def canonical_value(value: Any) -> Any:
    """ATR浮動leafだけを判断に使う整数格子へ変換し、その他の内容を保存する。

    引数: value (Any) は未加工の技術配列/監視/出典。
    返り値: Any はhash専用投影。実データや売買数式の値を書き換えない。
    """
    if isinstance(value, dict):
        return {key: atr_integers(item) if key == "atr" else canonical_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [canonical_value(item) for item in value]
    return value


def atr_leaves(value: Any, prefix: str) -> list[dict]:
    """生のATR全leafを鍵sort/配列index順で別の数値照合列へ抽出する。

    引数: value (Any) は元の技術配列、prefix (str) は原発動/反転監視/反転診断。
    返り値: list[dict] は経路/原値/ε/D整数。元値はabs1e-10で別照合する。
    """
    result = []
    if isinstance(value, dict):
        for key in sorted(value):
            path, item = prefix + "/" + str(key), value[key]
            if key == "atr":
                result.append({"経路": path, "値": item, **atr_integers(item)})
            else:
                result.extend(atr_leaves(item, path))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            result.extend(atr_leaves(item, prefix + "/" + str(index)))
    return result


def canonical_sha(rows: list[dict]) -> str:
    """ATR以外の厳密内容とATR由来整数をcanonical指紋へ結合する。

    引数: rows (list[dict]) はラベル/P&Lなしの技術配列。
    返り値: str はUTF-8鍵順固定SHA256。ATR浮動全内容同値という意味ではない。
    """
    encoded = json.dumps(canonical_value(rows), ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def prepare(study: Path, work: Path) -> dict:
    """原OHLC/SAR/価格/反転確認状態を再構成し、主prepareの全場件数と数値品質を比較する。

    引数: study/work (Path) は26正式先/作業先。
    返り値: dict はラベルなし準備の合否と指紋。正式状態監査や収益確認の代替にしない。
    """
    audit, config, manifest = V.Audit(), V.read(study / "条件.json"), V.read(INPUT)
    source = V.read(work / "準備点検.json")
    audit.check("主準備ラベル未計算", source["ラベル計算"], False)
    audit.check("主準備損益未計算", source["損益計算"], False)
    audit.check("主準備入力", source["入力台帳SHA256"], V.sha(INPUT))
    audit.check("主準備条件", source["条件SHA256"], V.sha(study / "条件.json"))
    for name, digest in source["コードSHA256"].items():
        audit.check("主準備code:" + name, digest, V.sha(ROOT / name))
    stages = {row["場"]: row for row in source["準備"]}
    channels = {row["場"]: row for row in source["30窓品質"]}
    quantities = {row["場"]: row for row in source["数量診断品質"]}
    sar_qualities = {row["場"]: row for row in source["SAR品質"]}
    old_stages = {row["場"]: row for row in V.read(OLD_WORK / "準備点検.json")["準備"]}
    phases, summary, rows = Counter(), Counter(), []
    atr_summary = {name: {"件数": 0, "厳密値差数": 0, "最大絶対差": 0.0, "整数判定差数": 0} for name in ("ATR検算列", "ATR全足検算列")}
    atr_pairs = {name: set() for name in atr_summary}
    invariant = ("設定数", "内復帰価格消費数", "外回復価格消費数", "対象外足数",
        "登録遅延超数", "監視動作別", "終了理由別", "新設定除外理由別", "登録候補数", "登録見送り理由別")
    for block in reconstruct(manifest, config, audit):
        session, period, counts = block["場"], block["期間"], block["段階件数"]
        audit.check(session + ":全準備段階", stages[session], counts)
        for field, summary_item in atr_summary.items():
            actual_values, expected_values = stages[session][field], counts[field]
            summary_item["件数"] += len(expected_values)
            for actual_value, expected_value in zip(actual_values, expected_values):
                left, right = actual_value["値"], expected_value["値"]
                if left != right:
                    summary_item["厳密値差数"] += 1
                    atr_pairs[field].add((left, right))
                    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
                        summary_item["最大絶対差"] = max(summary_item["最大絶対差"], abs(left - right))
                if any(actual_value[key] != expected_value[key] for key in ("ATR正有効", "登録εpt整数", "追尾Dpt整数")):
                    summary_item["整数判定差数"] += 1
        for name in invariant:
            audit.check(session + ":旧25価格状態件数不変:" + name, counts[name], old_stages[session][name])
        audit.check(session + ":旧25M25数不変", counts["共通M準備足数"], old_stages[session]["共通M準備足数"])
        for name, actual, expected in (("30窓品質", channels[session], block["30窓品質"]),
                ("SAR品質", sar_qualities[session], block["SAR品質"])):
            B.compare_row(audit, session + ":" + name,
                {key: value for key, value in actual.items() if key not in ("場", "期間")},
                {key: value for key, value in expected.items() if key != "場"})
        actual_quantity = {key: value for key, value in quantities[session].items() if key not in ("場", "期間")}
        expected_quantity = block["数量診断品質"]
        for key in actual_quantity.keys() | expected_quantity.keys():
            audit.check(session + ":数量品質:" + key, actual_quantity.get(key, 0), expected_quantity.get(key, 0))
        for policy in POLICIES:
            selected = [row for row in block["全採用"].values() if row["戦略"] == policy]
            row = {"場": session, "期間": period, "入口ID": "3分_" + policy, "発動数": len(selected),
                "買い発動数": sum(item["side"] == 1 for item in selected), "売り発動数": sum(item["side"] == -1 for item in selected)}
            actual = next(item for item in source["場別発動"] if item["場"] == session and item["入口ID"] == row["入口ID"])
            audit.check(session + ":二集合件数:" + policy, actual, row)
        rows.append(counts)
        phases[period] += 1
        for key in ("設定数", "内復帰価格消費数", "外回復価格消費数", "先着評価対象外数", "登録遅延超数",
                "f即時SAR確認数", "後続SAR待機開始数", "後続SAR確認消費数", "h元端等号不採用数"):
            summary[period + ":" + key] += counts[key]
        for policy, role_counts in counts["戦略別役割発動数"].items():
            for role, count in role_counts.items():
                summary[period + ":" + policy + ":" + role] += count
        print(json.dumps({"場": session, "独立準備点検": "原OHLC固定SAR/全価格f・g/独立区間h/三集合件数と技術全指紋のみ",
            "不一致数": audit.mismatches}, ensure_ascii=False), flush=True)
    audit.check("既使用65場", dict(phases), {"学習": 40, "条件選択": 24, "後続検査": 1})
    for field in atr_summary:
        atr_summary[field]["厳密値差組数"] = len(atr_pairs[field])
    proof = {"全件一致": audit.mismatches == 0, "照合項目数": audit.count, "不一致数": audit.mismatches,
        "不一致": audit.errors, "ラベル計算": False, "損益計算": False, "期間場数": dict(phases),
        "ATR照合": {"数値絶対許容": 1e-10, "数値相対許容": 0, "全経路と件数": "厳密同値", "整数判定": "厳密同値",
            "canonical範囲": "atr浮動leafを正有効/εpt整数/Dpt整数へ投影し、他全内容は厳密SHA。浮動ATR全内容同値を意味しない",
            "集計": atr_summary},
        "段階集計": dict(summary), "場別段階": rows, "コードSHA256": V.sha(Path(__file__)),
        "入力台帳SHA256": V.sha(INPUT), "条件SHA256": V.sha(study / "条件.json"),
        "主準備SHA256": V.sha(work / "準備点検.json"), "独立価格窓補助SHA256": V.sha(PRICE_HELPER),
        "検証範囲": "固定25の独立原OHLC/SAR/価格区間再構成を読取再用し、全f起点を先列挙して後続区間を別走査。親価格g/失効を先切断、三足寿命/end-key/初公開SARr消費と元端等号h原保存・strict採否を区別する。M26=M25、N0即時MACD/N1即時SAR/N2即時又は新h・全案共通T持続、全理由/段階/三集合件数と全原発動の明示技術投影・全反転監視・全反転診断のcanonical SHAを比較。ただしatr浮動leafだけは正有効/εpt整数/Dpt整数へ投影、元ATR全leafと全3分足ATRはabs1e-10/rel0、全path/件数とε/D整数は厳密別照合。全SAR品質/内容SHAと旧25価格件数も照合。固定manifestの65場だけを開き、新Night/先着ラベル/P&Lは読取も計算もしない。",
        "限界": "26主指標/入口/driver/運用classをimportして自己再生しない。旧Wの未使用パターン列は独立数式計算外なので原発動SHAは明示投影だけ。全保存context/price源値/既存SAR/原先着/全採否属性/全監視の照合は正式完了後。原板全本文再抽出や将来収益の証明ではない。"}
    (work / "独立準備点検.json").write_text(json.dumps(proof, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({key: proof[key] for key in ("全件一致", "照合項目数", "不一致数", "ラベル計算", "損益計算")}, ensure_ascii=False))
    return proof


compare_row = B.compare_row


def run(study: Path, work: Path) -> dict:
    """正式完了後だけ原価格から凍結30窓・全f/g・全監視と全三集合とSARを検算する。

    引数: study/work (Path) は26正式先/作業先。
    返り値: dict は全独立計算列・全保存監視・全集合の明示合否と指紋。先着数値と会計は別監査。
    """
    if not (study / "結果.json").exists() or not (study / "固定.json").exists():
        raise ValueError("正式結果完了通知後だけ実行します")
    audit, config, manifest = V.Audit(), V.read(study / "条件.json"), V.read(INPUT)
    preparation = V.read(work / "独立準備点検.json")
    audit.check("独立準備全一致", preparation["全件一致"], True)
    audit.check("独立準備code現在", preparation["コードSHA256"], V.sha(Path(__file__)))
    audit.check("独立準備主証拠現在", preparation["主準備SHA256"], V.sha(work / "準備点検.json"))
    audit.check("独立準備条件現在", preparation["条件SHA256"], V.sha(study / "条件.json"))
    pins = V.read(study / "固定.json")["ファイルSHA256"]
    for name in ("検証.py", "入口.py", "指標.py", "運用.py", "合成検証.py"):
        path = Path(__file__).with_name(name)
        audit.check("正式固定コード:" + name, V.sha(path), pins[path.relative_to(ROOT).as_posix()])
    audit.check("正式固定条件", V.sha(study / "条件.json"), pins[(study / "条件.json").relative_to(ROOT).as_posix()])
    rows_by_name, hashes = {}, {}
    for name in ("全複合context", "全局面", "上位足", "全複合shadow", "入口事例", "30分窓", "監視",
                 "全運用詳細", "追尾", "SAR", "反転監視"):
        rows_by_name[name], hashes[name] = S.compressed_rows(work / (name + ".jsonl.gz"))
    key_functions = {
        "全複合context": lambda r: (r["場"], r["時間足分"], r["index"]),
        "全局面": lambda r: (r["場"], r["index"]),
        "上位足": lambda r: (r["場"], r["minutes"], r["index"]),
        "全複合shadow": lambda r: r["発動ID"], "入口事例": lambda r: r["イベントID"],
        "30分窓": lambda r: (r["場"], r["種別"]),
        "SAR": lambda r: (r["場"], r["index"]),
        "反転監視": lambda r: (r["種別"], r["場"], r["index"] if r["種別"] == "反転足監視" else r["f発動ID"]),
        "監視": lambda r: (r["種別"], r["場"], r["index"] if r["種別"] == "足監視" else r["エピソードID"])}
    saved, expected_ids = {}, {name: set() for name in key_functions}
    for name, key_of in key_functions.items():
        saved[name] = {key_of(r): r for r in rows_by_name[name]}
        audit.check(name + ":キー一意", len(saved[name]), len(rows_by_name[name]))
    regime_quality = {r["場"]: r for r in V.read(study / "局面品質.json")}
    entry_quality = {r["場"]: r for r in V.read(study / "入口品質.json")}
    channel_quality = {r["場"]: r for r in V.read(study / "30窓品質.json")}
    quantity_quality = {r["場"]: r for r in V.read(study / "数量診断品質.json")}
    sar_quality = {r["場"]: r for r in V.read(study / "SAR品質.json")}
    old_proof = V.read(OLD_WORK / "状態独立確認.json")
    for name in ("30分窓", "全局面", "上位足", "SAR"):
        audit.check("固定25と保存同値:" + name, hashes[name], old_proof[name + "展開SHA256"])
    price_invariants(audit, rows_by_name)
    label_numbers = ("新規価格", "新規時計秒", "新規原板行", "判定時計秒", "判定原板行", "判定気配",
                     "最大順行pt", "最大逆行pt", "所要分")
    phases, totals, stages, entries, raw_families = Counter(), Counter(), [], Counter(), Counter()
    for block in reconstruct(manifest, config, audit):
        session, period = block["場"], block["期間"]
        phases[period] += 1
        stage = {key: value for key, value in block["段階件数"].items() if key not in ("ATR検算列", "ATR全足検算列")}
        stages.append(stage)
        audit.check(session + ":全段階件数", entry_quality[session], stage)
        for name, actual, expected in (("局面品質", regime_quality[session], block["局面品質"]),
                                       ("30窓品質", channel_quality[session], block["30窓品質"]),
                                       ("SAR品質", sar_quality[session], block["SAR品質"])):
            compare_row(audit, session + ":" + name, {k: v for k, v in actual.items() if k not in ("場", "期間")},
                {k: v for k, v in expected.items() if k != "場"})
        quantity_actual = {k: v for k, v in quantity_quality[session].items() if k not in ("場", "期間")}
        quantity_expected = block["数量診断品質"]
        for key in quantity_actual.keys() | quantity_expected.keys():
            audit.check(session + ":数量品質:" + key, quantity_actual.get(key, 0), quantity_expected.get(key, 0))
        expected = {
            "全複合context": [{"期間": period, **r} for r in block["全context"].values()],
            "全局面": [{"期間": period, **r} for r in block["局面"]],
            "上位足": [{"場": session, "期間": period, **r} for size in (15, 30) for r in block["価格足"][size]],
            "全複合shadow": [{"期間": period, **r} for r in block["全raw"].values()],
            "入口事例": [{"期間": period, **r} for r in block["全採用"].values()],
            "30分窓": [{"期間": period, **r} for r in block["30窓"]],
            "SAR": [{"期間": period, **r} for r in block["SAR"]],
            "反転監視": ([{"種別": "反転足監視", "期間": period, **r} for r in block["反転監視"]] +
                [{"種別": "反転終了診断", "場": session, "期間": period, **r} for r in block["反転監視診断"]]),
            "監視": ([{"種別": "足監視", "期間": period, **r} for r in block["監視"]] +
                [{"種別": "監視終了診断", "場": session, "期間": period, **r} for r in block["監視終了診断"]])}
        for name, local in expected.items():
            local_keys = {key_functions[name](r) for r in local}
            actual_keys = {key for key, r in saved[name].items() if r["場"] == session}
            S.compare_keys(audit, session + ":" + name + ":全集合", actual_keys, local_keys)
            expected_ids[name].update(local_keys)
            for row in local:
                key = key_functions[name](row)
                if key not in saved[name]:
                    continue
                actual = saved[name][key]
                compare_row(audit, name + ":" + str(key), actual, row)
                if name in ("全複合shadow", "入口事例"):
                    requested = row["要求時計秒"]
                    time_ok = requested < block["新規停止"] and block["期限"] - requested >= 3600
                    delay_ok = row["確認遅延秒"] <= 30
                    eligible = time_ok and delay_ok
                    audit.check(str(key) + ":先着対象は時間と遅延条件", actual["先着評価対象"], eligible)
                    if name == "入口事例":
                        audit.check(str(key) + ":全case先着対象", actual["先着評価対象"], True)
                    if not eligible:
                        audit.check(str(key) + ":対象外label", actual["ラベル"], "対象外")
                        audit.check(str(key) + ":対象外理由", actual["理由"], "要求時間条件外" if not time_ok else "足確定確認遅延30秒超")
                        for field in label_numbers:
                            audit.check(str(key) + ":対象外数値None:" + field, actual[field], None)
        for r in block["全採用"].values():
            entries[r["入口ID"]] += 1
        for r in block["全raw"].values():
            raw_families[r["入口系統"]] += 1
        for size, rows in block["価格足"].items():
            totals[str(size)] += len(rows)
        print(json.dumps({"場": session, "独立確認": "固定原OHLC/SAR・親f/g・独立区間h・全三採否",
            "現時点不一致数": audit.mismatches}, ensure_ascii=False), flush=True)
    audit.check("全65場", len(manifest["entries"]), 65)
    audit.check("既使用40/24/1", dict(phases), {"学習": 40, "条件選択": 24, "後続検査": 1})
    for name in key_functions:
        S.compare_keys(audit, name + ":全65合集", set(saved[name]), expected_ids[name])
    canonical = saved["全複合shadow"]
    verdict_errors = []
    for case in rows_by_name["入口事例"]:
        shadow = canonical.get(case["発動ID"])
        if shadow is None:
            verdict_errors.append(case["イベントID"])
            audit.check(case["イベントID"] + ":元canonical存在", False, True)
            continue
        audit.check(case["イベントID"] + ":全三採否canonical一致", case["戦略判定"], shadow["戦略判定"])
        audit.check(case["イベントID"] + ":自己複合判定", case["複合判定"], shadow["戦略判定"][case["戦略"]])
        if case["戦略判定"] != shadow["戦略判定"]:
            verdict_errors.append(case["イベントID"])
    proof = {"全件一致": audit.mismatches == 0, "照合項目数": audit.count, "不一致数": audit.mismatches,
        "不一致": audit.errors, "表示属性注意": bool(verdict_errors), "case内canonical判定不一致数": len(verdict_errors),
        "入力場数": len(manifest["entries"]), "期間場数": dict(phases), "独立足数": dict(totals),
        "保存context数": len(rows_by_name["全複合context"]), "保存局面数": len(rows_by_name["全局面"]),
        "保存上位足数": len(rows_by_name["上位足"]), "保存発動候補数": len(rows_by_name["全複合shadow"]),
        "保存shadow数": len(rows_by_name["全複合shadow"]), "保存入口数": len(rows_by_name["入口事例"]),
        "保存反転監視数": len(rows_by_name["反転監視"]), "保存SAR数": len(rows_by_name["SAR"]), "保存30分窓数": len(rows_by_name["30分窓"]), "保存監視数": len(rows_by_name["監視"]),
        "保存運用詳細数": len(rows_by_name["全運用詳細"]), "保存追尾数": len(rows_by_name["追尾"]),
        "入口系統別raw数": dict(raw_families), "戦略別入口数": dict(entries),
        "ATR照合": preparation["ATR照合"], "独立準備SHA256": V.sha(work / "独立準備点検.json"),
        "監視段階": stages, "コードSHA256": V.sha(Path(__file__)), "入力台帳SHA256": V.sha(INPUT),
        "条件SHA256": V.sha(study / "条件.json"), "結果SHA256": V.sha(study / "結果.json"),
        "独立価格発動補助SHA256": V.sha(PRICE_HELPER), "独立数量補助SHA256": V.sha(B.B.B.QUANTITY_HELPER),
        "固定25状態proofSHA256": V.sha(OLD_WORK / "状態独立確認.json"),
        "全複合context展開SHA256": hashes["全複合context"], "全局面展開SHA256": hashes["全局面"],
        "上位足展開SHA256": hashes["上位足"], "発動候補展開SHA256": hashes["全複合shadow"],
        "全複合shadow展開SHA256": hashes["全複合shadow"], "入口事例展開SHA256": hashes["入口事例"],
        "反転監視展開SHA256": hashes["反転監視"], "SAR展開SHA256": hashes["SAR"], "30分窓展開SHA256": hashes["30分窓"], "監視展開SHA256": hashes["監視"],
        "全運用詳細展開SHA256": hashes["全運用詳細"], "追尾展開SHA256": hashes["追尾"],
        "検証範囲": "固定25独立原cache/OHLC/SAR/価格監視補助を読取再用し、26主classをimportしない。全fを先列挙し後続区間を別走査、親g/取消/期限優先・age>3/end-keystrict・初公開SARr一回消費・元端等号h保存とstrict採否・f即時/h時計分離を全反転監視/診断の全文で比較。共通M26=M25とN0即時MACD/N1即時SAR/N2即時又はh・全案共有T方向持続・全理由/純集合を確認。全原技術投影/反転trace/診断canonical SHAはatr浮動leafだけを正有効/εpt整数/Dpt整数へ投影し他の全内容は厳密比較、ATR元値は既定abs1e-10/rel0で各保存属性を別照合。旧25全f/g原価格集合/源値/原先着とcontext旧列・全親監視非採否は不変、30窓/局面/上位/SAR全文展開SHAも同値比較。全case全N採否、先着time/delayと対象外理由/9Noneを検査する。",
        "限界": "新26指標/入口/driver/運用classをimportして自己再生しない。固定25の検証済み独立原OHLC/SAR/helperは読取再用。旧W未使用パターン列は独立数式計算外なので原発動hashは明示投影。通常先着数値/新規受入/一建玉/会計/追尾は別監査、原板全本文は再抽出しない。固定manifest65場以外の新Nightは未閲覧、65場は既使用で将来収益性の証明ではない。"}
    (work / "状態独立確認.json").write_text(json.dumps(proof, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({k: proof[k] for k in ("全件一致", "照合項目数", "不一致数", "保存shadow数", "保存入口数",
        "保存30分窓数", "保存監視数", "保存SAR数", "保存反転監視数", "case内canonical判定不一致数")}, ensure_ascii=False))
    return proof




def price_invariants(audit: Any, rows_by_name: dict) -> None:
    """固定25の原イベント/context/監視の不変列を25保存物へ直接比較する。

    引数: audit (Any) は照合先、rows_by_name (dict) は25正式保存行。
    返り値: None。新Q採否とM25による上書きだけを明示して分離する。
    """
    old_proof = V.read(OLD_WORK / "状態独立確認.json")
    audit.check("旧25状態全一致", old_proof["全件一致"], True)
    for name in ("全複合shadow", "全複合context", "監視"):
        old_rows, digest = S.compressed_rows(OLD_WORK / (name + ".jsonl.gz"))
        audit.check("固定25不変元SHA:" + name, digest, old_proof[name + "展開SHA256"])
        if name == "全複合shadow":
            key_of = lambda row: row["発動ID"]
        elif name == "全複合context":
            key_of = lambda row: (row["場"], row["時間足分"], row["index"])
        else:
            key_of = lambda row: (row["種別"], row["場"], row["index"] if row["種別"] == "足監視" else row["エピソードID"])
        old = {key_of(row): row for row in old_rows}
        new = {key_of(row): row for row in rows_by_name[name]
            if name != "全複合shadow" or row["入口系統"] in ("R内復帰", "T外回復")}
        S.compare_keys(audit, "旧25全集合不変:" + name, set(new), set(old))
        for key in old.keys() & new.keys():
            left, right = old[key], new[key]
            if name == "監視":
                left, right = deepcopy(left), deepcopy(right)
                for record in (left, right):
                    for action in record.get("動作", []):
                        action.pop("戦略採否", None)
                audit.check("旧25監視非採否全文不変:" + str(key), right, left)
            else:
                for field, value in left.items():
                    target = "旧25戦略判定" if field == "戦略判定" else field
                    audit.check("旧25価格/context不変列:" + str(key) + ":" + field, right.get(target), value)


def main() -> None:
    """固定前のラベルなし準備又は正式完了通知後の全反転確認状態監査を開始する。

    引数: なし。--study/--work/--prepare/--実行許可を読む。
    返り値: None。不一致なら非0終了。無指定では実入力を開かない。
    """
    parser = argparse.ArgumentParser(description="00026 反転確認時計の原OHLC独立状態確認")
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
        parser.error("固定前は --prepare、正式完了通知後は --実行許可 が必要です")
    if not proof["全件一致"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
