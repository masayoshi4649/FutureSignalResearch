"""00025のSARを原OHLC区間から別手順で再構成し、準備/正式状態を検算する。"""

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
STUDY = ROOT / "study/00025_価格イベントとSAR方向持続"
WORK = ROOT / "work/SAR持続/00025"
INPUT = ROOT / "study/00008_外部研究を共通尺度へ移して探索/入力台帳.json"
PRICE_HELPER = ROOT / "scripts/終値切替/状態独立確認.py"
OLD_WORK = ROOT / "work/終値切替/00024"
POLICIES = ("Q0", "Q1")


def helper(path: Path, name: str) -> Any:
    """固定24の独立価格/窓/指標計算を読取で借りる。

    引数: path (Path) は独立補助、name (str) はモジュール名。
    返り値: Any は補助。25主のSAR/入口/指標/運用はimportしない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


B = helper(PRICE_HELPER, "SAR持続の固定24独立価格")
V, S = B.V, B.S


# ----------------------------------------
# 主の逐次bankとは別に、最後の切断以降のOHLC区間を先頭から配列で計算する。

def segment_values(frames: list[dict]) -> list[dict]:
    """欠損のない原OHLC区間を先頭から再走査してSARの全時点を計算する。

    引数: frames (list[dict]) は数値入力順の有効OHLC。公開/未公開は数値計算を分けない。
    返り値: list[dict] は当時の方向/事前線/表示/EP/AF/次線。初期同値は方向0で保留する。
    """
    output = []
    direction, display, extreme, factor, following = 0, None, None, None, None
    for position, frame in enumerate(frames):
        before, flipped, seeded = None, False, False
        if direction == 0:
            if position and frame["close"] != frames[position - 1]["close"]:
                prior = frames[position - 1]
                direction = 1 if frame["close"] > prior["close"] else -1
                display = min(prior["low"], frame["low"]) if direction == 1 else max(prior["high"], frame["high"])
                extreme = frame["high"] if direction == 1 else frame["low"]
                factor, seeded = .02, True
        else:
            before = following
            crossed = frame["low"] < before if direction == 1 else frame["high"] > before
            if crossed:
                direction = -direction
                display = min(extreme, frame["low"]) if direction == 1 else max(extreme, frame["high"])
                extreme, factor, flipped = (frame["high"] if direction == 1 else frame["low"]), .02, True
            else:
                recent = frames[max(0, position - 2):position]
                display = min([before] + [row["low"] for row in recent]) if direction == 1 else max(
                    [before] + [row["high"] for row in recent])
                current_extreme = frame["high"] if direction == 1 else frame["low"]
                if direction * (current_extreme - extreme) > 0:
                    extreme = current_extreme
                    factor = min(.2, factor + .02)
        following = display + factor * (extreme - display) if direction else None
        output.append({"方向": direction, "事前線": before, "表示SAR": display, "EP": extreme,
            "AF": factor, "次線": following, "反転": flipped, "初期化": seeded, "数値有効": bool(direction)})
    return output

# ----------------------------------------
# 価格監視は独立24の区間計算を使い、SARの数値可用性と二案の値条件だけを別に付ける。

def contexts_with_sar(old_contexts: dict, sar_rows: list[dict]) -> dict:
    """旧価格contextに独立SARの同場公開現前参照とM25を付ける。

    引数: old_contexts (dict) は24当時情報、sar_rows (list[dict]) は独立SAR足。
    返り値: dict は足番号別の新context。方向一致を準備条件へ混ぜない。
    """
    values, output, prior = {row["index"]: row for row in sar_rows}, {}, None
    for index, old in old_contexts.items():
        current = values.get(index)
        previous = prior if prior is not None and prior["publish"] and prior["index"] + 1 == index else None
        ready = bool(current and current["SAR公開可"] and current["SAR方向"] in (-1, 1))
        previous_ready = bool(previous and previous["SAR公開可"] and previous["SAR方向"] in (-1, 1)
            and current and previous["index"] + 1 == current["index"])
        reasons = list(old["M除外理由"])
        if not ready:
            reasons.append("現在公開SAR未準備")
        if not previous_ready:
            reasons.append("同場隣接公開前SAR未準備")
        output[index] = {**deepcopy(old), "旧24共通M準備": old["共通M準備"],
            "旧24M除外理由": deepcopy(old["M除外理由"]), "SAR参照": deepcopy(current),
            "前SAR参照": deepcopy(previous), "SAR現在有効": ready, "SAR前値有効": previous_ready,
            "SAR現前準備": ready and previous_ready,
            "SAR現方向": current["SAR方向"] if ready else 0,
            "SAR前方向": previous["SAR方向"] if previous_ready else 0,
            "共通M準備": not reasons, "共通M25準備": not reasons, "M除外理由": reasons}
        prior = current if current and current["publish"] else None
    return output


def decisions(context: dict, side: int) -> dict:
    """共通M25で準備を揃え、MACDと二足SAR方向の異なる二条件を計算する。

    引数: context (dict) は当時情報、side (int) は実新規方向。
    返り値: dict はQ0/Q1の採否と理由。上位値・事後ラベルを使わない。
    """
    common = list(context["M除外理由"])
    if not context["時間条件可"]:
        common.append("要求時間条件外")
    histogram = context["MACDヒスト変化"]
    momentum = B.S.S.finite(histogram) and side * histogram > 0
    persistent = context["SAR現在有効"] and context["SAR前値有効"] and (
        context["SAR現方向"] == context["SAR前方向"] == side)
    reasons = {"Q0": common + ([] if momentum else ["実方向MACD勢い不成立"]),
        "Q1": common + ([] if persistent else ["実方向SAR二本持続不成立"])}
    return {policy: {"採用": not reason,
        "理由": reason or ["価格と実方向MACD採用" if policy == "Q0" else "価格と実方向SAR二本持続採用"],
        "同時競合": False} for policy, reason in reasons.items()}


def price_plan(block: dict, sar_rows: list[dict]) -> tuple[dict, dict, dict, list, list, dict]:
    """独立24価格経路を不変に保ち、Q採否と全監視の採否表示を純変換する。

    引数: block (dict) は原価格/窓/局面/量、sar_rows (list[dict]) は独立SAR。
    返り値: tuple[dict,dict,dict,list,list,dict] はcontext/raw/cases/trace/episode/品質。
    """
    frames, session, period = block["価格足"][3], block["場"], block["期間"]
    old_contexts, old_raw, old_cases, trace, episodes = B.price_plan(frames, block["局面"], block["30窓"],
        block["数量"], session, block["新規停止"], block["期限"])
    quality = B.stage_counts(frames, old_contexts, old_raw, old_cases, trace, episodes, session, period)
    contexts, raw, cases = contexts_with_sar(old_contexts, sar_rows), {}, {}
    for key, old in old_raw.items():
        row = {**deepcopy(old), **deepcopy(contexts[old["index"]]),
            "旧24戦略判定": deepcopy(old["戦略判定"])}
        row["戦略判定"] = decisions(row, row["side"])
        raw[key] = row
    groups = defaultdict(list)
    for row in raw.values():
        for policy in POLICIES:
            if row["戦略判定"][policy]["採用"]:
                groups[policy, row["要求時計秒"], row["要求原板行"]].append(row)
    for (policy, _, _), rows in groups.items():
        if len(rows) > 1:
            for row in rows:
                row["戦略判定"][policy] = {"採用": False, "理由": ["同判断複数信号見送り"], "同時競合": True}
    for row in raw.values():
        for policy in POLICIES:
            if row["戦略判定"][policy]["採用"]:
                event = row["発動ID"] + "_" + policy
                cases[event] = {**deepcopy(row), "入口ID": "3分_" + policy, "戦略": policy,
                    "複合判定": deepcopy(row["戦略判定"][policy]), "イベントID": event}
    for record in trace:
        for action in record["動作"]:
            if "戦略採否" in action:
                action["戦略採否"] = deepcopy(raw[action["発動ID"]]["戦略判定"])
    quality.update(旧24共通M準備足数=sum(r["旧24共通M準備"] for r in contexts.values()),
        共通M準備足数=sum(r["共通M準備"] for r in contexts.values()),
        SAR現在準備足数=sum(r["SAR現在有効"] for r in contexts.values()),
        SAR現前準備足数=sum(r["SAR現在有効"] and r["SAR前値有効"] for r in contexts.values()),
        戦略採否理由別={policy: dict(Counter(z for r in raw.values() for z in r["戦略判定"][policy]["理由"])) for policy in POLICIES},
        イベントM除外理由別=dict(Counter(z for r in raw.values() for z in r["M除外理由"])),
        戦略別役割発動数={"3分_" + policy: dict(Counter(r["役割"] for r in cases.values() if r["戦略"] == policy)) for policy in POLICIES},
        戦略別発動数={"3分_" + policy: sum(r["戦略"] == policy for r in cases.values()) for policy in POLICIES})
    quality["イベント段階"] = []
    for role in ("反転", "順行"):
        own = [row for row in raw.values() if row["役割"] == role]
        quality["イベント段階"].append({"役割": role, "原価格イベント数": len(own),
            "時間可数": sum(row["時間条件可"] for row in own),
            "確認遅延可数": sum(row["確認遅延条件可"] for row in own),
            "先着評価対象数": sum(row["先着評価対象"] for row in own),
            "M24時間通過数": sum(row["旧24共通M準備"] and row["時間条件可"] for row in own),
            "M25時間通過数": sum(row["共通M準備"] and row["時間条件可"] for row in own),
            "旧24E0数": sum(row["旧24戦略判定"]["E0"]["採用"] for row in own),
            "SAR準備でQ0除外数": sum(row["旧24戦略判定"]["E0"]["採用"] and not row["共通M準備"] for row in own),
            "Q0採用数": sum(row["戦略判定"]["Q0"]["採用"] for row in own),
            "Q1採用数": sum(row["戦略判定"]["Q1"]["採用"] for row in own)})
    return contexts, raw, cases, trace, episodes, quality

# ----------------------------------------
# 数値carryを主から借りず、切断ごとの過去OHLC列を再計算する。

def valid_ohlc(frame: dict) -> bool:
    """原始終高安の有限正値と包絡を独立検査する。

    引数: frame (dict) は3分足。
    返り値: bool は数値入力の可否。公開可否を混ぜない。
    """
    values = [frame.get(key) for key in ("open", "high", "low", "close")]
    if any(not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0 for value in values):
        return False
    opening, high, low, close = values
    return low <= min(opening, close) <= max(opening, close) <= high


class SARHistory:
    """過去OHLC区間を保持して場ごとに配列を取り直す独立SAR。"""

    def __init__(self) -> None:
        """空の原OHLC区間と未指定限月を用意する。

        引数: なし。
        返り値: None。主SARの方向/線/EP/AFを流用しない。
        """
        self.sources, self.contract = [], None

    def build(self, frames: list[dict], session: str, contract: tuple,
              tail_missing: int = 0) -> tuple[list[dict], dict]:
        """欠枠等の切断を先に列挙し、各区間を頭から一回ずつ再計算する。

        引数: frames (list[dict]) は3分OHLC、session (str) は場、contract (tuple) は限月、
        tail_missing (int) は完全幅末尾欠枠数。
        返り値: tuple[list[dict],dict] は全足SARと品質。末尾NPも数値投入し、公開用途は分離する。
        """
        changed = self.contract is not None and contract != self.contract
        if changed:
            self.sources = []
        self.contract = contract
        working, references, rows = deepcopy(self.sources), [], []
        previous_index, previous_key, reset_count = None, None, int(changed)

        def flush() -> list[dict]:
            """現在区間を配列計算して当場の出力対象だけを変換する。

            引数: なし。外側のworking/referencesを読む。
            返り値: list[dict] は当場の完成SAR行。過去carry行を再保存しない。
            """
            values, local = segment_values(working), []
            for position, source, reasons in references:
                value = values[position]
                prior = values[position - 1] if position else None
                local.append({**deepcopy(source), "SAR準備済": value["数値有効"],
                    "SAR公開可": bool(value["数値有効"] and source["publish"]),
                    "SAR方向": value["方向"], "SAR事前方向": prior["方向"] if prior else 0,
                    "SAR事前線": value["事前線"], "SAR表示線": value["表示SAR"],
                    "SAR次足線": value["次線"], "SAR_EP": value["EP"], "SAR_AF": value["AF"],
                    "SAR事前EP": prior["EP"] if prior else None, "SAR事前AF": prior["AF"] if prior else None,
                    "SAR反転": value["反転"], "SAR初期化": value["初期化"], "SAR数値入力可": True,
                    "SAR前二足": deepcopy(working[max(0, position - 2):position]), "SAR解除理由": list(reasons)})
            return local

        for frame in frames:
            index, key = frame["index"], (frame["confirm"], frame["confirm_line"])
            if frame["minutes"] != 3 or previous_index is not None and index <= previous_index:
                raise ValueError("独立SARの足幅/番号が不正")
            if frame["publish"] and (frame["confirm"] < frame["end"] or previous_key is not None and key < previous_key):
                raise ValueError("独立SARの公開キーが不正")
            reasons = ["限月変更"] if changed and previous_index is None else []
            if (previous_index is None and index != 0) or (previous_index is not None and index != previous_index + 1):
                reasons.append("3分番号欠枠")
            if frame["missing"]:
                reasons.append("3分欠枠")
            numeric = valid_ohlc(frame)
            if not numeric:
                reasons.append("3分OHLC不正")
            if any(reason != "限月変更" for reason in reasons):
                rows.extend(flush())
                working, references = [], []
                reset_count += 1
            source = {"場": session, **{key: (None if key in ("open", "high", "low", "close")
                and isinstance(frame[key], float) and not math.isfinite(frame[key]) else frame[key]) for key in B.SOURCE_FIELDS}}
            if numeric:
                references.append((len(working), source, reasons))
                working.append(source)
            else:
                rows.append({**deepcopy(source), "SAR準備済": False, "SAR公開可": False,
                    "SAR方向": 0, "SAR事前方向": 0, "SAR事前線": None, "SAR表示線": None,
                    "SAR次足線": None, "SAR_EP": None, "SAR_AF": None, "SAR事前EP": None,
                    "SAR事前AF": None, "SAR反転": False, "SAR初期化": False, "SAR数値入力可": False,
                    "SAR前二足": [], "SAR解除理由": reasons})
            previous_index = index
            if frame["publish"]:
                previous_key = key
        rows.extend(flush())
        values = segment_values(working)
        last = values[-1] if values else {"方向": 0, "次線": None, "EP": None, "AF": None}
        if tail_missing:
            working = []
            last = {"方向": 0, "次線": None, "EP": None, "AF": None}
            reset_count += 1
        self.sources = working
        return rows, {"場": session, "SAR全足内容SHA256": hashlib.sha256(json.dumps(rows, ensure_ascii=False,
            sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest(),
            "SAR入力足数": len(rows),
            "SAR数値準備足数": sum(row["SAR準備済"] for row in rows),
            "SAR公開準備足数": sum(row["SAR公開可"] for row in rows),
            "SAR初期化数": sum(row["SAR初期化"] for row in rows),
            "SAR反転数": sum(row["SAR反転"] for row in rows),
            "SAR未公開数値更新数": sum(not row["publish"] and row["SAR数値入力可"] for row in rows),
            "SARclear数": reset_count, "SAR尾部完全欠枠": tail_missing,
            "SAR場末方向": last["方向"], "SAR場末次線": last["次線"],
            "SAR場末EP": last["EP"], "SAR場末AF": last["AF"]}


def reconstruct(manifest: dict, config: dict, audit: Any) -> Any:
    """全65場の原価格と独立SARから価格状態/M25/全二採否を再構成する。

    引数: manifest/config (dict) は固定入力/25条件、audit (Any) は検査記録。
    返り値: Any は場別独立集合のiterator。先着ラベル/損益は読まず計算しない。
    """
    history = SARHistory()
    inputs = {entry["session"]: entry for entry in manifest["entries"]}
    for block in B.price_blocks(manifest, config, audit):
        session, frames = block["場"], block["価格足"][3]
        start, finish, _, _ = B.S.S.G.times(session)
        tail = max(0, int((finish - start) // 180) - 1 - (frames[-1]["index"] if frames else -1))
        sar_rows, sar_quality = history.build(frames, session, tuple(inputs[session]["in_session_contract_codes"]), tail)
        contexts, raw, cases, trace, episodes, counts = price_plan(block, sar_rows)
        block.update(全context=contexts, 全raw=raw, 全採用=cases, 監視=trace,
            監視終了診断=episodes, 段階件数=counts, SAR=sar_rows, SAR品質=sar_quality)
        yield block

# ----------------------------------------
# 固定前の準備では先着ラベル/損益/全運用保存物を開かない。

def prepare(study: Path, work: Path) -> dict:
    """原OHLC/SAR/価格状態を再構成し、主prepareの全場件数と数値品質を比較する。

    引数: study/work (Path) は25正式先/作業先。
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
    invariant = ("設定数", "内復帰価格消費数", "外回復価格消費数", "対象外足数", "先着評価対象外数",
        "登録遅延超数", "監視動作別", "終了理由別", "新設定除外理由別", "登録候補数", "登録見送り理由別")
    for block in reconstruct(manifest, config, audit):
        session, period, counts = block["場"], block["期間"], block["段階件数"]
        audit.check(session + ":全準備段階", stages[session], counts)
        for name in invariant:
            audit.check(session + ":旧24価格状態件数不変:" + name, counts[name], old_stages[session][name])
        audit.check(session + ":旧M24数不変", counts["旧24共通M準備足数"], old_stages[session]["共通M準備足数"])
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
        for key in ("設定数", "内復帰価格消費数", "外回復価格消費数", "先着評価対象外数", "登録遅延超数"):
            summary[period + ":" + key] += counts[key]
        for policy, role_counts in counts["戦略別役割発動数"].items():
            for role, count in role_counts.items():
                summary[period + ":" + policy + ":" + role] += count
        print(json.dumps({"場": session, "独立準備点検": "原OHLC区間SAR/全価格f・g/理由/二集合件数のみ",
            "不一致数": audit.mismatches}, ensure_ascii=False), flush=True)
    audit.check("既使用65場", dict(phases), {"学習": 40, "条件選択": 24, "後続検査": 1})
    proof = {"全件一致": audit.mismatches == 0, "照合項目数": audit.count, "不一致数": audit.mismatches,
        "不一致": audit.errors, "ラベル計算": False, "損益計算": False, "期間場数": dict(phases),
        "段階集計": dict(summary), "場別段階": rows, "コードSHA256": V.sha(Path(__file__)),
        "入力台帳SHA256": V.sha(INPUT), "条件SHA256": V.sha(study / "条件.json"),
        "主準備SHA256": V.sha(work / "準備点検.json"), "独立価格窓補助SHA256": V.sha(PRICE_HELPER),
        "検証範囲": "固定24独立価格/窓から原3/15/30分OHLC・MACD等・価格全登録/最初f/gを再構成。SARは最後reset以降の原OHLC区間を先頭から配列再計算し、同限月carry/NP数値投入/欠枠と末尾reset、三線と方向/EP/AFを独立形成。M25数値準備とQ0MACD/Q1現前方向を分離し、全理由/段階/65場二集合件数とSAR品質を比較。旧24保存ラベル/損益と25先着/運用結果は読取も計算もしない。",
        "限界": "25主SAR/指標/入口/driver/運用の自己再生ではない。全保存context/trace/SAR/event全属性の照合は正式完了後。数量0カウンタ省略は0正規化。主Wの未使用パターンは数式対象外。原板全本文再抽出や将来収益の証明ではない。"}
    (work / "独立準備点検.json").write_text(json.dumps(proof, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({key: proof[key] for key in ("全件一致", "照合項目数", "不一致数", "ラベル計算", "損益計算")}, ensure_ascii=False))
    return proof


compare_row = B.compare_row


def run(study: Path, work: Path) -> dict:
    """正式完了後だけ原価格から凍結30窓・全f/g・全監視と全二集合とSARを検算する。

    引数: study/work (Path) は25正式先/作業先。
    返り値: dict は全独立計算列・全保存監視・全集合の明示合否と指紋。先着数値と会計は別監査。
    """
    if not (study / "結果.json").exists() or not (study / "固定.json").exists():
        raise ValueError("正式結果完了通知後だけ実行します")
    audit, config, manifest = V.Audit(), V.read(study / "条件.json"), V.read(INPUT)
    pins = V.read(study / "固定.json")["ファイルSHA256"]
    for name in ("検証.py", "入口.py", "指標.py", "運用.py", "合成検証.py"):
        path = Path(__file__).with_name(name)
        audit.check("正式固定コード:" + name, V.sha(path), pins[path.relative_to(ROOT).as_posix()])
    audit.check("正式固定条件", V.sha(study / "条件.json"), pins[(study / "条件.json").relative_to(ROOT).as_posix()])
    rows_by_name, hashes = {}, {}
    for name in ("全複合context", "全局面", "上位足", "全複合shadow", "入口事例", "30分窓", "監視",
                 "全運用詳細", "追尾", "SAR"):
        rows_by_name[name], hashes[name] = S.compressed_rows(work / (name + ".jsonl.gz"))
    key_functions = {
        "全複合context": lambda r: (r["場"], r["時間足分"], r["index"]),
        "全局面": lambda r: (r["場"], r["index"]),
        "上位足": lambda r: (r["場"], r["minutes"], r["index"]),
        "全複合shadow": lambda r: r["発動ID"], "入口事例": lambda r: r["イベントID"],
        "30分窓": lambda r: (r["場"], r["種別"]),
        "SAR": lambda r: (r["場"], r["index"]),
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
    for name in ("30分窓", "全局面", "上位足"):
        audit.check("固定24と保存同値:" + name, hashes[name], old_proof[name + "展開SHA256"])
    price_invariants(audit, rows_by_name)
    label_numbers = ("新規価格", "新規時計秒", "新規原板行", "判定時計秒", "判定原板行", "判定気配",
                     "最大順行pt", "最大逆行pt", "所要分")
    phases, totals, stages, entries, raw_families = Counter(), Counter(), [], Counter(), Counter()
    for block in reconstruct(manifest, config, audit):
        session, period = block["場"], block["期間"]
        phases[period] += 1
        stage = block["段階件数"]
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
        print(json.dumps({"場": session, "独立確認": "原OHLC区間SAR・凍結窓・全f/g監視・全二採否",
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
        audit.check(case["イベントID"] + ":全二採否canonical一致", case["戦略判定"], shadow["戦略判定"])
        audit.check(case["イベントID"] + ":自己複合判定", case["複合判定"], shadow["戦略判定"][case["戦略"]])
        if case["戦略判定"] != shadow["戦略判定"]:
            verdict_errors.append(case["イベントID"])
    proof = {"全件一致": audit.mismatches == 0, "照合項目数": audit.count, "不一致数": audit.mismatches,
        "不一致": audit.errors, "表示属性注意": bool(verdict_errors), "case内canonical判定不一致数": len(verdict_errors),
        "入力場数": len(manifest["entries"]), "期間場数": dict(phases), "独立足数": dict(totals),
        "保存context数": len(rows_by_name["全複合context"]), "保存局面数": len(rows_by_name["全局面"]),
        "保存上位足数": len(rows_by_name["上位足"]), "保存発動候補数": len(rows_by_name["全複合shadow"]),
        "保存shadow数": len(rows_by_name["全複合shadow"]), "保存入口数": len(rows_by_name["入口事例"]),
        "保存SAR数": len(rows_by_name["SAR"]), "保存30分窓数": len(rows_by_name["30分窓"]), "保存監視数": len(rows_by_name["監視"]),
        "保存運用詳細数": len(rows_by_name["全運用詳細"]), "保存追尾数": len(rows_by_name["追尾"]),
        "入口系統別raw数": dict(raw_families), "戦略別入口数": dict(entries),
        "監視段階": stages, "コードSHA256": V.sha(Path(__file__)), "入力台帳SHA256": V.sha(INPUT),
        "条件SHA256": V.sha(study / "条件.json"), "結果SHA256": V.sha(study / "結果.json"),
        "独立価格発動補助SHA256": V.sha(PRICE_HELPER), "独立数量補助SHA256": V.sha(B.B.QUANTITY_HELPER),
        "固定24状態proofSHA256": V.sha(OLD_WORK / "状態独立確認.json"),
        "全複合context展開SHA256": hashes["全複合context"], "全局面展開SHA256": hashes["全局面"],
        "上位足展開SHA256": hashes["上位足"], "発動候補展開SHA256": hashes["全複合shadow"],
        "全複合shadow展開SHA256": hashes["全複合shadow"], "入口事例展開SHA256": hashes["入口事例"],
        "SAR展開SHA256": hashes["SAR"], "30分窓展開SHA256": hashes["30分窓"], "監視展開SHA256": hashes["監視"],
        "全運用詳細展開SHA256": hashes["全運用詳細"], "追尾展開SHA256": hashes["追尾"],
        "検証範囲": "原cacheから独立24価格/窓補助で全3/15/30分半開OHLC・公開原行・MACD/Wilder・価格全登録/最初f/gを再構成。25SARは最後reset以降の原OHLC区間を頭から配列再計算し、strict seed/前next線貫通先/非反転前2高安制約/EPとAF/反転表示/次線・同限月carry/NP内部更新/欠枠resetの全保存行と品質canonical SHAを照合。旧24全raw価格集合と属性・全contextの旧列・全監視の採否以外とepisodesを不変比較し、旧30窓/15局面/上位足は全文展開SHAも一致比較。M24/M25数値準備とQ0MACD/Q1二足SARを分離、全二採用集合・全case全Qverdict・先着対象time/delay・対象外優先理由/9数値Noneを照合する。",
        "限界": "25主SAR/指標/入口/driver/運用をimportして自己再生しない。固定24独立価格/窓/数量補助は読取再用。SARは本研究の具体的規約で他標準との完全同値を主張しない。主W未使用パターンは数式再計算外。通常先着数値/新規受入/会計/一建玉/追尾は別監査、原板全本文は再抽出しない。全65場は既使用で将来収益性の証明ではない。"}
    (work / "状態独立確認.json").write_text(json.dumps(proof, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({k: proof[k] for k in ("全件一致", "照合項目数", "不一致数", "保存shadow数", "保存入口数",
        "保存30分窓数", "保存監視数", "保存SAR数", "case内canonical判定不一致数")}, ensure_ascii=False))
    return proof



# ----------------------------------------
# 正式状態監査でのみ旧保存rawを開き、価格属性/時点/ラベルの不変部分を照合する。

def price_invariants(audit: Any, rows_by_name: dict) -> None:
    """固定24の原イベント/context/監視の不変列を25保存物へ直接比較する。

    引数: audit (Any) は照合先、rows_by_name (dict) は25正式保存行。
    返り値: None。新Q採否とM25による上書きだけを明示して分離する。
    """
    old_proof = V.read(OLD_WORK / "状態独立確認.json")
    audit.check("旧24状態全一致", old_proof["全件一致"], True)
    for name in ("全複合shadow", "全複合context", "監視"):
        old_rows, digest = S.compressed_rows(OLD_WORK / (name + ".jsonl.gz"))
        audit.check("固定24不変元SHA:" + name, digest, old_proof[name + "展開SHA256"])
        if name == "全複合shadow":
            key_of = lambda row: row["発動ID"]
        elif name == "全複合context":
            key_of = lambda row: (row["場"], row["時間足分"], row["index"])
        else:
            key_of = lambda row: (row["種別"], row["場"], row["index"] if row["種別"] == "足監視" else row["エピソードID"])
        old = {key_of(row): row for row in old_rows}
        new = {key_of(row): row for row in rows_by_name[name]}
        S.compare_keys(audit, "旧24全集合不変:" + name, set(new), set(old))
        for key in old.keys() & new.keys():
            left, right = old[key], new[key]
            if name == "監視":
                left, right = deepcopy(left), deepcopy(right)
                for record in (left, right):
                    for action in record.get("動作", []):
                        action.pop("戦略採否", None)
                audit.check("旧24監視非採否全文不変:" + str(key), right, left)
            else:
                for field, value in left.items():
                    target = {"共通M準備": "旧24共通M準備", "M除外理由": "旧24M除外理由",
                        "戦略判定": "旧24戦略判定"}.get(field, field)
                    audit.check("旧24価格/context不変列:" + str(key) + ":" + field, right.get(target), value)


def main() -> None:
    """固定前のラベルなし準備又は正式完了通知後の全状態監査を開始する。

    引数: なし。--study/--work/--prepare/--実行許可を読む。
    返り値: None。不一致なら非0終了。無指定では実入力を開かない。
    """
    parser = argparse.ArgumentParser(description="00025 SAR方向持続の原OHLC独立状態確認")
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
