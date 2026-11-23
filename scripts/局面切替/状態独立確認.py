"""00020の原価格・三尺度特徴・全Q候補・五戦略を独立に再構成する。"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT / "study/00020_テクニカル局面による順行反転の切替"
WORK = ROOT / "work/局面切替/00020"
INPUT = ROOT / "study/00008_外部研究を共通尺度へ移して探索/入力台帳.json"
OLD_STUDY = ROOT / "study/00019_VWAP復帰の入口と通常出口"
OLD_WORK = ROOT / "work/VWAP復帰/00019"
HELPER = ROOT / "scripts/VWAP復帰/状態独立確認.py"
POLICIES = ("B1", "B2", "S0", "S1", "S2")


def helper(path: Path, name: str) -> Any:
    """既検証の独立価格・Q計算補助だけを読む。

    引数: path (Path) は補助、name (str) はモジュール識別名。
    返り値: Any は独立補助。20入口/driver/局面.pyは読み込まない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


Q = helper(HELPER, "複合局面の独立Q")
S, V = Q.S, Q.V


class Indicators(S.Indicators):
    """独立EMA20・Wilder・RSIへ10終値で種を作るEMA10を加える。"""

    def __init__(self) -> None:
        """欠枠・尾部欠枠・限月変更に対応する未準備状態を作る。

        引数: なし。
        返り値: None。
        """
        super().__init__()
        self.seed10, self.ema10 = [], None

    def add(self, bar: dict) -> dict:
        """現在の一足だけでEMA10を更新する。

        引数: bar (dict) は独立OHLC。
        返り値: dict は独立価格指標とEMA10/その前値。
        """
        previous = self.ema10
        if self.ema10 is None:
            self.seed10.append(bar["close"])
            if len(self.seed10) == 10:
                self.ema10 = sum(self.seed10) / 10
        else:
            self.ema10 += (2 / 11) * (bar["close"] - self.ema10)
        return {**super().add(bar), "ema10": self.ema10, "ema10_previous": previous}


# ----------------------------------------
# 15分分類は現在の数値と直前の記憶から別に計算する。

def regimes(higher: list[dict], session: str) -> tuple[list[dict], dict]:
    """全15分足のS1/S2分類・記憶初期化・切替数を別処理で求める。

    引数: higher (list[dict]) は独立15分足、session (str) は場。
    返り値: tuple[list[dict],dict] は全局面と品質。局面.pyは呼び出さない。
    """
    prior = {"S1": ("待機", 0), "S2": ("待機", 0)}
    ready_before, previous_index = False, None
    rows, counts = [], Counter()
    categories = {"S1": Counter(), "S2": Counter()}
    for f in higher:
        ready = bool(f["publish"] and S.S.finite(*(f[k] for k in
            ("close", "ema20", "ema20_previous", "adx", "plus_di", "minus_di"))))
        ema = (1 if f["close"] > f["ema20"] > f["ema20_previous"] else
               -1 if f["close"] < f["ema20"] < f["ema20_previous"] else 0) if ready else 0
        di = (1 if f["plus_di"] > f["minus_di"] else -1 if f["plus_di"] < f["minus_di"] else 0) if ready else 0
        direction = ema if ema == di else 0
        reset = []
        if previous_index is not None and f["index"] != previous_index + 1:
            reset.append("15分足番号飛越")
        if f["missing"]:
            reset.append("15分欠枠")
        if not f["publish"]:
            reset.append("非公開15分足")
        if not ready:
            reset.append("上位指標未準備")
        memory = ("待機", 0) if reset else prior["S2"]
        if not ready:
            first = second = ("未準備", 0)
        elif f["adx"] <= 20:
            first = second = ("レンジ", 0)
        else:
            first = ("トレンド", direction) if f["adx"] >= 25 and direction != 0 else ("待機", 0)
            retained_range = memory[0] == "レンジ" and f["adx"] < 25
            retained_trend = memory[0] == "トレンド" and direction == memory[1]
            second = ("レンジ", 0) if retained_range else (
                ("トレンド", direction) if retained_trend else first)
        comparable = bool(ready_before and ready and not reset)
        row = {"場": session, "局面ID": f"NK225_{session}_15分_{f['index']:04d}", "時間足分": 15,
            **{k: f[k] for k in ("index", "start", "end", "confirm", "confirm_line", "publish", "missing")},
            "共通M準備": ready, "EMA方向": ema, "DI方向": di, "一致方向": direction,
            "ADX14": f["adx"], "+DI14": f["plus_di"], "-DI14": f["minus_di"],
            "15分終値": f["close"], "EMA20": f["ema20"], "EMA20前": f["ema20_previous"],
            "S1直前局面": prior["S1"][0], "S1直前方向": prior["S1"][1],
            "S2直前局面": prior["S2"][0], "S2直前方向": prior["S2"][1],
            "S2適用前局面": memory[0], "S2適用前方向": memory[1],
            "S1局面": first[0], "S1方向": first[1], "S2局面": second[0], "S2方向": second[1],
            "記憶初期化理由": sorted(set(reset)), "切替比較可能": comparable,
            "S1切替": bool(comparable and first != prior["S1"]),
            "S2切替": bool(comparable and second != prior["S2"])}
        rows.append(row)
        counts.update({"15分足数": 1, "公開15分足数": int(f["publish"]), "共通M準備15分足数": int(ready),
            "記憶初期化足数": int(bool(reset)), "初回準備分類数": int(ready and (not ready_before or bool(reset))),
            "S1切替回数": int(row["S1切替"]), "S2切替回数": int(row["S2切替"])})
        for name, state in (("S1", first), ("S2", second)):
            categories[name][state[0]] += 1
        prior, ready_before, previous_index = {"S1": first, "S2": second}, ready, f["index"]
    return rows, {**dict(counts), **{p + "局面足数": dict(categories[p]) for p in ("S1", "S2")}}


def available(frame: dict, candidates: list[dict], published_only: bool = False) -> dict | None:
    """原行込み公開キーと終了時計を満たす最後の出典を直接列挙する。

    引数: frame (dict) は判断足、candidates (list[dict]) は上位候補、published_only (bool) は公開限定。
    返り値: dict|None は最新の既知候補。値の準備不足を理由に過去へfallbackしない。
    """
    key = frame["confirm"], frame["confirm_line"]
    rows = [r for r in candidates if r["end"] <= frame["end"] and
            (r["confirm"], r["confirm_line"]) <= key and (not published_only or r["publish"])]
    return rows[-1] if rows else None


def scale(frame: dict | None) -> dict:
    """一尺度自身のATRで傾きとEMA間隔を独立正規化する。

    引数: frame (dict|None) は判断時に公開済みの価格足。
    返り値: dict は出典と準備/傾き/間隔/収束。
    """
    fields = ("index", "minutes", "end", "confirm", "confirm_line", "close", "ema10", "ema20", "ema20_previous", "atr")
    row = {k: frame.get(k) if frame is not None else None for k in fields}
    ready = bool(frame is not None and frame["publish"] and
        S.S.finite(*(row[k] for k in ("ema10", "ema20", "ema20_previous", "atr"))) and row["atr"] > 0)
    slope = (row["ema20"] - row["ema20_previous"]) / row["atr"] if ready else None
    separation = abs(row["ema10"] - row["ema20"]) / row["atr"] if ready else None
    return {**row, "準備済": ready, "正規化傾き": slope, "正規化間隔": separation,
        "収束": bool(ready and separation <= .25 and abs(slope) <= .10)}


def contexts(lower: list[dict], higher15: list[dict], higher60: list[dict], states: list[dict]) -> dict[int, dict]:
    """公開連続区間の末尾五本RSIと三尺度出典から共通Mを再構成する。

    引数: lower/higher15/higher60/states (list[dict]) は独立足と分類済み局面。
    返り値: dict[int,dict] は全下位判断context。上位pointer方式は使わない。
    """
    result, segment = {}, []
    for f in lower:
        if not f["publish"] or f["missing"] or segment and f["index"] != segment[-1]["index"] + 1:
            segment = []
        if f["publish"] and S.S.finite(f["rsi"]):
            segment.append(f)
        else:
            segment = []
        history = [{k: r[k] for k in ("index", "confirm", "confirm_line", "rsi")} for r in segment[-5:]]
        current = available(f, states)
        ready = bool(current is not None and current["共通M準備"] and f["publish"])
        reasons = [] if ready else ["局面参照なし" if current is None else "非公開下位足" if not f["publish"] else "上位指標未準備"]
        base = {"共通M準備": ready, "局面参照ID": current["局面ID"] if current else None,
            "局面公開秒": current["confirm"] if current else None,
            "局面公開原行": current["confirm_line"] if current else None,
            "局面足終了秒": current["end"] if current else None, "局面準備不可理由": list(reasons)}
        for name in ("EMA方向", "DI方向", "一致方向", "ADX14", "+DI14", "-DI14", "15分終値", "EMA20", "EMA20前",
                     "S1局面", "S1方向", "S2局面", "S2方向"):
            base[name] = current[name] if current else ("未準備" if name in ("S1局面", "S2局面") else
                0 if name.endswith("方向") else None)
        features = {"入口": scale(f), "15分": scale(available(f, higher15, True)), "60分": scale(available(f, higher60, True))}
        reasons.extend(name + "EMA/ATR未準備" for name, feature in features.items() if not feature["準備済"])
        if len(history) < 5:
            reasons.append("同場連続公開RSI五本未準備")
        result[f["index"]] = {**base, "旧M準備": ready, "共通M準備": bool(ready and not reasons),
            "M除外理由": reasons, "三尺度特徴": features, "RSI五本": history,
            "収束尺度数": sum(int(p["収束"]) for p in features.values())}
    return result


# ----------------------------------------
# 五戦略の採否は将来ラベルを受け取らず、方向変換した同じ式で決める。

def decision(policy: str, family: str, side: int, context: dict) -> dict:
    """局面段階と複合EMA/RSI段階の全真偽を独立評価する。

    引数: policy/family (str) は戦略/系統、side (int) は買1売−1、context (dict) は当時既知特徴。
    返り値: dict は採否・見送り理由・全段階真偽。
    """
    ready = context["共通M準備"]
    rsi = [p["rsi"] if side == 1 else 100 - p["rsi"] for p in context["RSI五本"]]
    if not ready:
        accepted, why = False, "共通局面準備なし"
    elif policy in ("B1", "B2", "S0"):
        accepted = policy == "S0" or family == {"B1": "Q1", "B2": "Q2"}.get(policy)
        why = "固定手法選択" if accepted else "固定手法の対象外"
    elif context[policy + "局面"] == "トレンド":
        if family != "Q1":
            accepted, why = False, "トレンドで反転を見送り"
        else:
            accepted = side == context[policy + "方向"]
            why = "トレンド方向の順行" if accepted else "トレンド逆向きを見送り"
    elif context[policy + "局面"] == "レンジ":
        accepted = family == "Q2"
        why = "レンジの反転" if accepted else "レンジで順行を見送り"
    else:
        accepted, why = False, "転換待機"
    has_five = bool(ready and len(rsi) == 5)
    spike = bool(has_five and rsi[-1] >= 70 and rsi[-1] - rsi[-2] >= 12 and sum(x >= 65 for x in rsi[:-1]) <= 1)
    trend = bool(has_five and all(side * f["正規化傾き"] >= .02 for f in context["三尺度特徴"].values()) and
        side * (context["三尺度特徴"]["入口"]["close"] - context["三尺度特徴"]["入口"]["ema20"]) > 0)
    sustained = bool(has_five and min(rsi[-3:]) >= 50)
    converged = bool(has_five and context["収束尺度数"] >= 2)
    rebound = bool(has_five and rsi[-2] <= 40 and 30 <= rsi[-1] <= 60 and rsi[-1] > rsi[-2])
    reasons = [] if accepted else [why]
    if policy in ("S1", "S2") and ready:
        if spike:
            reasons.append("RSI急変警戒")
        if family == "Q1":
            if not trend:
                reasons.append("三尺度EMA順行不一致")
            if not sustained:
                reasons.append("RSI三本持続不成立")
        else:
            if not converged:
                reasons.append("二尺度収束不成立")
            if not rebound:
                reasons.append("RSI戻り不成立")
    return {"採用": bool(accepted and not reasons), "理由": reasons or [why], "局面段階採用": bool(accepted),
        "方向側RSI五本": rsi, "RSI急変警戒": spike, "三尺度EMA順行": trend, "RSI三本持続": sustained,
        "二尺度収束": converged, "RSI戻り": rebound, "同時競合": False}


def select(signals: list[dict], context_by_index: dict, size: int) -> tuple[dict, dict]:
    """全Qのshadowを残したまま、戦略内同判断競合を別集合で除く。

    引数: signals (list[dict]) は独立Qなし信号、context_by_index (dict) は独立context、size (int) は尺度。
    返り値: tuple[dict,dict] はQイベント別shadow/戦略イベント別採用集合。
    """
    shadow, groups, selected = {}, defaultdict(list), {}
    for signal in signals:
        context = context_by_index[signal["index"]]
        verdicts = {p: decision(p, signal["入口系統"], signal["side"], context) for p in POLICIES}
        row = {**signal, **context, "戦略判定": verdicts}
        shadow[signal["QイベントID"]] = row
        for p in POLICIES:
            if verdicts[p]["採用"]:
                groups[p, signal["要求時計秒"], signal["要求原板行"]].append(row)
    for (p, _, _), rows in groups.items():
        if len(rows) > 1:
            for row in rows:
                row["戦略判定"][p].update(採用=False, 同時競合=True, 理由=["同判断複数信号見送り"])
            continue
        row = rows[0]
        source = f"{size}分_{p}"
        selected[f"{row['QイベントID']}_{p}"] = {**deepcopy(row), "元Q入口ID": row["入口ID"], "入口ID": source,
            "戦略": p, "複合判定": deepcopy(row["戦略判定"][p]), "イベントID": f"{row['QイベントID']}_{p}"}
    return shadow, selected


def run(study: Path, work: Path) -> dict:
    """正式完了後だけ全65場の価格・局面・context・shadow・採用全集合を監査する。

    引数: study/work (Path) は20正式先/作業先。
    返り値: dict は全件一致/件数/指紋/限界。成績を選別へ戻さない。
    """
    if not (study / "結果.json").exists() or not (study / "固定.json").exists():
        raise ValueError("正式再生完了前は実行できません")
    audit, manifest, config = V.Audit(), V.read(INPUT), V.read(study / "条件.json")
    old_proof = V.read(OLD_WORK / "状態独立確認.json")
    audit.check("旧19状態独立確認", old_proof["全件一致"], True)
    audit.check("旧19独立コード", V.sha(HELPER), old_proof["コードSHA256"])
    old_refs, old_sha = S.compressed_rows(OLD_WORK / "全足参照.jsonl.gz")
    refs, reference_sha = S.compressed_rows(work / "全足参照.jsonl.gz")
    audit.check("固定19参照proof", old_sha, old_proof["全足参照展開SHA256"])
    audit.check("全参照の展開本文同値", reference_sha, old_sha)
    audit.check("全参照全文", refs, old_refs)
    context_rows, context_sha = S.compressed_rows(work / "全複合context.jsonl.gz")
    state_rows, state_sha = S.compressed_rows(work / "全局面.jsonl.gz")
    upper_rows, upper_sha = S.compressed_rows(work / "上位足.jsonl.gz")
    shadows, shadow_sha = S.compressed_rows(work / "全複合shadow.jsonl.gz")
    cases, case_sha = S.compressed_rows(work / "入口事例.jsonl.gz")
    saved_context = {(r["場"], r["時間足分"], r["index"]): r for r in context_rows}
    saved_states = {(r["場"], r["index"]): r for r in state_rows}
    saved_upper = {(r["場"], r["minutes"], r["index"]): r for r in upper_rows}
    saved_shadow = {r["QイベントID"]: r for r in shadows}
    saved_cases = {r["イベントID"]: r for r in cases}
    references = {(r["場"], r["時間足分"], r["index"]): r for r in refs}
    old_cases, _ = S.compressed_rows(OLD_WORK / "入口事例.jsonl.gz")
    old_plain = {r["QイベントID"]: r for r in old_cases if r["補助"] == "なし"}
    for name, mapping, values in (("context", saved_context, context_rows), ("局面", saved_states, state_rows),
                                 ("上位足", saved_upper, upper_rows), ("shadow", saved_shadow, shadows),
                                 ("入口", saved_cases, cases)):
        audit.check(name + "キー一意", len(mapping), len(values))
    saved_quality = {r["場"]: r for r in V.read(study / "局面品質.json")}
    entry_quality = {(r["場"], r["時間足分"]): r for r in V.read(study / "入口品質.json")}
    banks, contract = {n: Indicators() for n in (1, 3, 5, 15, 60)}, None
    expected_context, expected_states, expected_upper, expected_shadow, expected_cases = {}, {}, {}, {}, {}
    original_q, totals = {}, Counter()
    for entry in manifest["entries"]:
        session, codes = entry["session"], tuple(entry["in_session_contract_codes"])
        if len(codes) != 1:
            raise ValueError("限月非一意")
        if contract is not None and codes != contract:
            banks = {n: Indicators() for n in banks}
        contract = codes
        period = "後続検査" if session[:10] >= config["分割"]["後続開始日"] else (
            "条件選択" if session[:10] >= config["分割"]["選択開始日"] else "学習")
        data = S.S.observed(entry)
        formed = {n: S.S.bars(data, session, n, bank) for n, bank in banks.items()}
        current_states, quality = regimes(formed[15], session)
        for k, value in quality.items():
            audit.check(f"{session}:15分類品質:{k}", saved_quality[session].get(k, 0), value)
        expected_states.update({(session, r["index"]): {"期間": period, **r} for r in current_states})
        for size in (15, 60):
            for f in formed[size]:
                expected_upper[session, size, f["index"]] = {"場": session, "期間": period, **f}
        for size in (1, 3, 5):
            local_ref = {}
            for f in formed[size]:
                saved = references[session, size, f["index"]]
                for k in ("index", "start", "end", "confirm", "confirm_line", "publish", "missing"):
                    audit.check(f"{session}:{size}:{f['index']}:原価格足:{k}", saved[k], f[k])
                local_ref[f["index"]] = {k: saved[k] for k in Q.REFERENCE_FIELDS}
            _, generated, _ = Q.generate(formed[size], formed[15], local_ref, session, period)
            plain = [r for r in generated.values() if r["補助"] == "なし"]
            original_q.update({r["QイベントID"]: r for r in plain})
            c = contexts(formed[size], formed[15], formed[60], current_states)
            expected_context.update({(session, size, i): {"期間": period, "場": session, "時間足分": size, "index": i, **row}
                                     for i, row in c.items()})
            sh, selected = select(plain, c, size)
            expected_shadow.update(sh)
            expected_cases.update(selected)
            eq = entry_quality[session, size]
            audit.check(f"{session}:{size}:全足数", eq["足数"], len(formed[size]))
            audit.check(f"{session}:{size}:M足数", eq["共通M準備足数"], sum(r["共通M準備"] for r in c.values()))
            for p in POLICIES:
                audit.check(f"{session}:{size}:{p}:採用数", eq["戦略別発動数"][f"{size}分_{p}"],
                    sum(r["戦略"] == p for r in selected.values()))
            totals[str(size)] += len(formed[size])
        totals["15"] += len(formed[15])
        totals["60"] += len(formed[60])
        print(json.dumps({"場": session, "独立確認": "三尺度指標・全局面・全Q選別", "現時点不一致数": audit.mismatches}, ensure_ascii=False), flush=True)
    S.compare_keys(audit, "固定19なしQ全文集合", set(original_q), set(old_plain))
    for key in original_q.keys() & old_plain.keys():
        for field, value in original_q[key].items():
            audit.check(key + ":固定19元Q:" + field, old_plain[key].get(field), value)
    for name, saved, expected in (("全局面", saved_states, expected_states), ("全複合context", saved_context, expected_context)):
        S.compare_keys(audit, name + "全集合", set(saved), set(expected))
        for key in saved.keys() & expected.keys():
            audit.check(f"{name}:{key}", saved[key], expected[key])
    S.compare_keys(audit, "15/60上位足全集合", set(saved_upper), set(expected_upper))
    for key in saved_upper.keys() & expected_upper.keys():
        for field, value in expected_upper[key].items():
            audit.check(f"上位足:{key}:{field}", saved_upper[key][field], value)
    for name, saved, expected in (("全Qshadow", saved_shadow, expected_shadow), ("全15入口", saved_cases, expected_cases)):
        S.compare_keys(audit, name + "全集合", set(saved), set(expected))
        for key in saved.keys() & expected.keys():
            for field, value in expected[key].items():
                audit.check(f"{name}:{key}:{field}", saved[key].get(field), value)
    proof = {"全件一致": audit.mismatches == 0, "照合項目数": audit.count, "不一致数": audit.mismatches, "不一致": audit.errors,
        "入力場数": len(manifest["entries"]), "独立足数": dict(totals), "保存参照足数": len(refs),
        "保存局面数": len(state_rows), "保存context数": len(context_rows), "保存上位足数": len(upper_rows),
        "保存発動候補数": len(shadows), "保存shadow数": len(shadows), "保存入口数": len(cases),
        "独立Q候補数": len(original_q), "独立入口数": len(expected_cases),
        "戦略別入口数": dict(Counter(r["入口ID"] for r in expected_cases.values())),
        "コードSHA256": V.sha(Path(__file__)), "入力台帳SHA256": V.sha(INPUT),
        "補助入力台帳SHA256": V.sha(ROOT / "study/00017_配信元VWAPと売買代金の入力監査/結果.json"),
        "全足参照展開SHA256": reference_sha, "全局面展開SHA256": state_sha, "全複合context展開SHA256": context_sha,
        "上位足展開SHA256": upper_sha, "発動候補展開SHA256": shadow_sha, "全複合shadow展開SHA256": shadow_sha,
        "入口事例展開SHA256": case_sha, "旧19独立確認SHA256": V.sha(OLD_WORK / "状態独立確認.json"),
        "独立Q補助SHA256": V.sha(HELPER),
        "検証範囲": "原価格cacheから1/3/5/15/60分半開足・確認原行・欠枠/尾部/限月reset、EMA10/20/前値・WilderATR/ADX/DI・RSIを独立計算。固定19全参照本文/なしQと同値を確認。15分S1/S2全分類/記憶/切替、lower判断key/end制限as-of、全足三尺度特徴/RSI5と共通M、全Qshadow五戦略の複合条件/理由/競合、全15入口採用集合を照合。",
        "限界": "20主core/局面.py/元指標classはimportしない。補助VWAPは独立済み固定19/18全参照を同値再利用し、小列原板を再抽出する監査ではない。価格時計は正確な受信時計ではない。先着ラベル/運用受入/会計/追尾初着は別監査。range側RSI30..60とspike>=70は同時成立せず独立選別効果と数えない。"}
    (work / "状態独立確認.json").write_text(json.dumps(proof, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({k: proof[k] for k in ("全件一致", "照合項目数", "不一致数", "保存参照足数", "保存shadow数", "保存入口数")}, ensure_ascii=False))
    return proof


def main() -> None:
    """正式再生完了通知後だけ全量独立再構成を行う。

    引数: なし。--study/--work/--実行許可を読む。
    返り値: None。合否不一致は非0終了。
    """
    parser = argparse.ArgumentParser(description="00020複合局面の独立再構成")
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
