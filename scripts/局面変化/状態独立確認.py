"""00022の隣接15分ペア・共通準備・局面切替を原価格から別計算する。"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from copy import deepcopy
import importlib.util
import json
import math
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT / "study/00022_ADXと上位BB幅の変化による局面切替"
WORK = ROOT / "work/局面変化/00022"
INPUT = ROOT / "study/00008_外部研究を共通尺度へ移して探索/入力台帳.json"
PRICE_HELPER = ROOT / "scripts/異種発動/状態独立確認.py"
OLD_WORK = ROOT / "work/異種発動/00021"
POLICIES = ("A0", "S1", "S2")


def helper(path: Path, name: str) -> Any:
    """既検証の独立価格/発動/比較補助だけを読む。

    引数: path (Path) は補助、name (str) はモジュール名。
    返り値: Any は補助。22主入口/driver/指標classはimportしない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


P = helper(PRICE_HELPER, "局面変化の独立価格と基底発動")
S, V = P.S, P.V
Indicators = P.Indicators


def slope_state(adx: float, change: float, width_change: float, direction: int) -> tuple[str, int]:
    """確定済みの変化値だけで新しいS2を符号対称に分類する。

    引数: adx/change/width_change (float) は現ADX/ADX一差/15分帯幅一差、direction (int) はDI方向。
    返り値: tuple[str,int] は局面と許可方向。DXを追加の独立条件にしない。
    """
    if direction != 0 and change > 0 and (adx >= 25 or width_change > 0):
        return "トレンド", direction
    if adx <= 20 and change <= 0 and width_change <= 0:
        return "レンジ", 0
    return "待機", 0


def diagnostic_dx(plus: float | None, minus: float | None) -> tuple[float | None, bool]:
    """有限DIから診断DXとゼロ和flagを別計算する。

    引数: plus/minus (float|None) は現DI。
    返り値: tuple[float|None,bool] はDXとゼロ和。0/0へ数学的な意味を付与しない。
    """
    if not S.S.finite(plus, minus):
        return None, False
    total = plus + minus
    return (100 * abs(plus - minus) / total, False) if total > 0 else (0.0, total == 0)


# ----------------------------------------
# 同場隣接公開の前値だけを保持し、欠枠/非公開/不正単点をまたがない。

PAIR_FIELDS = ("index", "minutes", "start", "end", "confirm", "confirm_line", "publish", "missing",
    "adx", "plus_di", "minus_di", "bb_mean", "bb_sd", "bandwidth")
ASSIGN_FIELDS = ("旧上位準備済", "ペア準備済", "ペア不可理由", "上位現足", "上位前足", "局面", "DI方向",
    "ADX14", "+DI14", "-DI14", "S1局面", "S1方向", "S2局面", "S2方向", "S2理由", "ADX変化", "上位帯幅変化",
    "現DX", "前DX", "DI和ゼロ", "前DI和ゼロ", "DX差", "DX_ADX差", "平滑恒等残差")


def point_ready(frame: dict) -> bool:
    """隣接ペアの一要素にできる公開単点を判定する。

    引数: frame (dict) は独立15分足。
    返り値: bool はADX/DI有限と正のBB中心/σ/帯幅の可否。
    """
    return bool(frame["publish"] and S.S.finite(*(frame[k] for k in
        ("adx", "plus_di", "minus_di", "bb_mean", "bb_sd", "bandwidth"))) and
        min(frame["bb_mean"], frame["bb_sd"], frame["bandwidth"]) > 0)


def pair_states(higher: list[dict], session: str) -> tuple[list[dict], dict]:
    """独立15分足列から現前ペア・変化・診断DX・新旧局面を構成する。

    引数: higher (list[dict]) は独立15分足、session (str) は場。
    返り値: tuple[list[dict],dict] は全局面行と品質。旧21独立分類だけを再用する。
    """
    old, _ = P.classify(higher, session)
    records, counts, previous, last_index = [], Counter(), None, None
    for f, old_row in zip(higher, old):
        reasons = []
        if last_index is not None and f["index"] != last_index + 1:
            reasons.append("15分番号飛越")
        if f["missing"]:
            reasons.append("15分欠枠")
        if not f["publish"]:
            reasons.append("非公開15分")
        if not point_ready(f):
            reasons.append("15分単点未準備")
        prior = deepcopy(previous) if not reasons else None
        ready = bool(point_ready(f) and prior is not None and prior["index"] + 1 == f["index"])
        if not ready and not reasons:
            reasons.append("同場隣接公開15分前値なし")
        current = {k: f[k] for k in PAIR_FIELDS}
        now_dx, zero = diagnostic_dx(f["plus_di"], f["minus_di"])
        prior_dx, prior_zero = diagnostic_dx(prior["plus_di"], prior["minus_di"]) if prior else (None, False)
        change = f["adx"] - prior["adx"] if ready else None
        width_change = f["bandwidth"] - prior["bandwidth"] if ready else None
        if ready:
            state, direction = slope_state(f["adx"], change, width_change, old_row["DI方向"])
            reason = ("強ADX上昇継続" if f["adx"] >= 25 else "低ADX上昇・幅拡大") if state == "トレンド" else (
                "低ADX非上昇・幅非拡大" if state == "レンジ" else
                "高ADX失速待機" if f["adx"] >= 25 and change <= 0 else "条件不一致待機")
        else:
            state, direction, reason = "未準備", 0, "未準備"
        records.append({**old_row, "旧上位準備済": old_row["上位準備済"], "上位準備済": ready,
            "ペア準備済": ready, "ペア不可理由": reasons, "上位現足": current, "上位前足": prior,
            "S1局面": old_row["局面"], "S1方向": old_row["DI方向"] if old_row["局面"] == "トレンド" else 0,
            "S2局面": state, "S2方向": direction, "S2理由": reason, "ADX変化": change, "上位帯幅変化": width_change,
            "現DX": now_dx, "前DX": prior_dx, "DI和ゼロ": zero, "前DI和ゼロ": prior_zero,
            "DX差": now_dx - prior_dx if ready else None, "DX_ADX差": now_dx - f["adx"] if ready else None,
            "平滑恒等残差": now_dx - f["adx"] - 13 * change if ready else None})
        counts["15分足数"] += 1
        counts["ペア準備足数"] += int(ready)
        counts["S2_" + state] += 1
        previous = current if point_ready(f) else None
        last_index = f["index"]
    return records, dict(counts)


def assign(frame: dict, states: list[dict]) -> dict:
    """判断時点以下の最新公開curを列挙し、ペア不可でも古い正常へ戻さない。

    引数: frame (dict) は下位判断足、states (list[dict]) は独立上位局面。
    返り値: dict は新上位参照/診断。最大キーと足終了を双方制限する。
    """
    rows = [r for r in states if r["publish"] and r["end"] <= frame["end"] and
            (r["confirm"], r["confirm_line"]) <= (frame["confirm"], frame["confirm_line"])]
    current = rows[-1] if rows else None
    result = {"上位準備済": bool(current and current["ペア準備済"]),
        "局面参照ID": current["局面ID"] if current else None, "局面公開秒": current["confirm"] if current else None,
        "局面公開原行": current["confirm_line"] if current else None, "局面足終了秒": current["end"] if current else None}
    for k in ASSIGN_FIELDS:
        if current is not None:
            value = deepcopy(current[k])
        elif k == "ペア不可理由":
            value = ["15分参照なし"]
        elif k in ("局面", "S1局面", "S2局面", "S2理由"):
            value = "未準備"
        elif k in ("旧上位準備済", "ペア準備済", "DI和ゼロ", "前DI和ゼロ"):
            value = False
        else:
            value = 0 if k.endswith("方向") else None
        result[k] = value
    return result


def contexts(frames: list[dict], higher: list[dict], states: list[dict],
             cutoff: float, deadline: float) -> tuple[dict, dict]:
    """旧下位M21を保持し、追加ペア準備だけで新共通M22を作る。

    引数: frames/higher/states (list[dict]) は独立価格足/15分足/新分類、cutoff/deadline (float) は停止/期限。
    返り値: tuple[dict,dict] は旧M21と新M22の全足context。旧発動をここで削除しない。
    """
    old_states = [{**r, "上位準備済": r["旧上位準備済"]} for r in states]
    old = P.contexts(frames, old_states, cutoff, deadline)
    new = {}
    for f in frames:
        current = assign(f, states)
        previous = old[f["index"]]
        reasons = list(previous["M除外理由"])
        if not current["ペア準備済"]:
            reasons.append("同場隣接公開15分ペア未準備")
        ready = bool(previous["共通M準備"] and current["ペア準備済"])
        new[f["index"]] = {**previous, **current, "旧M21準備": previous["共通M準備"],
            "旧M21除外理由": deepcopy(previous["M除外理由"]), "共通M準備": ready,
            "共通M22準備": ready, "M除外理由": reasons}
    return old, new


def decision(policy: str, family: str, side: int, context: dict) -> dict:
    """同じM22の混合・旧S1・改訂S2を将来情報なしで選別する。

    引数: policy/family (str) は規則/発動、side (int) は売買、context (dict) は当時の新準備と分類。
    返り値: dict は採否/理由/競合初期値。
    """
    if not context["共通M準備"]:
        ok, reason = False, "共通M22未準備"
    elif policy == "A0":
        ok, reason = True, "常時混合"
    elif context[policy + "局面"] == "トレンド":
        ok = family == "T1" and side == context[policy + "方向"]
        reason = "トレンド同DI方向の継続" if ok else "トレンドで対象外発動"
    elif context[policy + "局面"] == "レンジ":
        ok = family == "R1"
        reason = "レンジの反転" if ok else "レンジで継続見送り"
    else:
        ok, reason = False, "転換待機"
    return {"採用": bool(ok), "理由": [reason], "同時競合": False}


def select(raw: dict[str, dict], context_by_index: dict) -> tuple[dict, dict]:
    """全旧発動を残し、競合を全確定した後だけ採用caseを複写する。

    引数: raw (dict[str,dict]) は独立旧21canonical発動、context_by_index (dict) は新M22。
    返り値: tuple[dict,dict] は全shadow/全九採用集合。旧caseの他戦略表示は使わない。
    """
    shadow, groups, selected = {}, defaultdict(list), {}
    for key, original in raw.items():
        context = context_by_index[original["index"]]
        verdicts = {p: decision(p, original["入口系統"], original["side"], context) for p in POLICIES}
        row = {**deepcopy(original), **deepcopy(context), "旧21戦略判定": deepcopy(original["戦略判定"]),
            "戦略判定": verdicts}
        shadow[key] = row
        for policy in POLICIES:
            if verdicts[policy]["採用"]:
                groups[policy, row["要求時計秒"], row["要求原板行"]].append(row)
    for (policy, _, _), rows in groups.items():
        if len(rows) > 1:
            for row in rows:
                row["戦略判定"][policy].update(採用=False, 同時競合=True, 理由=["同判断複数信号見送り"])
    for key, row in shadow.items():
        for policy, verdict in row["戦略判定"].items():
            if not verdict["採用"]:
                continue
            source = f"{row['minutes']}分_{policy}"
            selected[key + "_" + policy] = {**deepcopy(row), "入口ID": source, "戦略": policy,
                "複合判定": deepcopy(verdict), "イベントID": key + "_" + policy}
    return shadow, selected


# ----------------------------------------
# 正式完了後にだけ全保存行を開き、旧raw保存・新ペア・全採否を接続する。

def run(study: Path, work: Path) -> dict:
    """原価格の全指標・全上位ペア・旧発動・新九集合を独立に検算する。

    引数: study/work (Path) は22正式先/作業先。
    返り値: dict は明示合否・件数・指紋。ラベル/PnLは条件選別に使わない。
    """
    if not (study / "結果.json").exists() or not (study / "固定.json").exists():
        raise ValueError("正式完了通知前は実行しません")
    audit, config, manifest = V.Audit(), V.read(study / "条件.json"), V.read(INPUT)
    old_proof = V.read(OLD_WORK / "状態独立確認.json")
    audit.check("旧21機能照合完了", old_proof["全件一致"], True)
    audit.check("旧21独立コード指紋", old_proof["コードSHA256"], V.sha(PRICE_HELPER))
    old_rows, old_sha = S.compressed_rows(OLD_WORK / "全複合shadow.jsonl.gz")
    audit.check("旧21canonical展開SHA", old_sha, old_proof["全複合shadow展開SHA256"])
    old_canonical = {r["発動ID"]: r for r in old_rows}
    contexts_saved, context_sha = S.compressed_rows(work / "全複合context.jsonl.gz")
    states_saved, state_sha = S.compressed_rows(work / "全局面.jsonl.gz")
    uppers_saved, upper_sha = S.compressed_rows(work / "上位足.jsonl.gz")
    shadows_saved, shadow_sha = S.compressed_rows(work / "全複合shadow.jsonl.gz")
    cases_saved, case_sha = S.compressed_rows(work / "入口事例.jsonl.gz")
    maps = {
        "全context": ({(r["場"], r["時間足分"], r["index"]): r for r in contexts_saved}, contexts_saved),
        "全局面": ({(r["場"], r["index"]): r for r in states_saved}, states_saved),
        "上位足": ({(r["場"], r["minutes"], r["index"]): r for r in uppers_saved}, uppers_saved),
        "全rawshadow": ({r["発動ID"]: r for r in shadows_saved}, shadows_saved),
        "全九入口": ({r["イベントID"]: r for r in cases_saved}, cases_saved)}
    for name, (mapping, rows) in maps.items():
        audit.check(name + ":キー一意", len(mapping), len(rows))
    regime_quality = {r["場"]: r for r in V.read(study / "局面品質.json")}
    entry_quality = {(r["場"], r["時間足分"]): r for r in V.read(study / "入口品質.json")}
    banks, contract, phases, totals = {n: Indicators() for n in (1, 3, 5, 15)}, None, Counter(), Counter()
    expected = {k: {} for k in maps}
    original_raw = {}
    for entry in manifest["entries"]:
        session, codes = entry["session"], tuple(entry["in_session_contract_codes"])
        if len(codes) != 1:
            raise ValueError("限月が一意でない")
        if contract is not None and codes != contract:
            banks = {n: Indicators() for n in banks}
        contract = codes
        period = "後続検査" if session[:10] >= config["分割"]["後続開始日"] else (
            "条件選択" if session[:10] >= config["分割"]["選択開始日"] else "学習")
        phases[period] += 1
        data = S.S.observed(entry)
        formed = {n: S.S.bars(data, session, n, bank) for n, bank in banks.items()}
        states, quality = pair_states(formed[15], session)
        audit.check(session + ":局面品質",
            {k: v for k, v in regime_quality[session].items() if k not in ("場", "期間")}, quality)
        expected["全局面"].update({(session, r["index"]): {"期間": period, **r} for r in states})
        expected["上位足"].update({(session, 15, f["index"]): {"場": session, "期間": period, **f} for f in formed[15]})
        _, _, cutoff, deadline = S.S.G.times(session)
        for size in (1, 3, 5):
            old_context, new_context = contexts(formed[size], formed[15], states, cutoff, deadline)
            raw, _ = P.generate(formed[size], old_context, session, period, deadline)
            original_raw.update(raw)
            shadow, cases = select(raw, new_context)
            expected["全rawshadow"].update(shadow)
            expected["全九入口"].update(cases)
            expected["全context"].update({(session, size, f["index"]): {"場": session, "期間": period, "時間足分": size,
                **f, **new_context[f["index"]]} for f in formed[size]})
            q = entry_quality[session, size]
            checks = {"足数": len(formed[size]), "旧M21準備足数": sum(r["共通M準備"] for r in old_context.values()),
                "共通M準備足数": sum(r["共通M22準備"] for r in new_context.values()),
                "旧M21発動数": len(raw), "新M22発動数": sum(r["共通M22準備"] for r in shadow.values())}
            for field, value in checks.items():
                audit.check(f"{session}:{size}:{field}", q[field], value)
            for policy in POLICIES:
                audit.check(f"{session}:{size}:{policy}:発動数", q["戦略別発動数"][f"{size}分_{policy}"],
                    sum(r["戦略"] == policy for r in cases.values()))
            totals[str(size)] += len(formed[size])
        totals["15"] += len(formed[15])
        print(json.dumps({"場": session, "独立確認": "原価格・同場15分ペア・全raw/全九採否",
            "現時点不一致数": audit.mismatches}, ensure_ascii=False), flush=True)
    audit.check("全65場", len(manifest["entries"]), 65)
    audit.check("既使用40/24/1", dict(phases), {"学習": 40, "条件選択": 24, "後続検査": 1})
    audit.check("旧canonical全4475", len(old_rows), 4475)
    S.compare_keys(audit, "旧21全raw独立再生成", set(original_raw), set(old_canonical))
    for key in original_raw.keys() & old_canonical.keys():
        P.compare_fields(audit, key + ":旧canonical", old_canonical[key], original_raw[key])
    for name, (saved, _) in maps.items():
        S.compare_keys(audit, name + ":全集合", set(saved), set(expected[name]))
        for key in saved.keys() & expected[name].keys():
            P.compare_fields(audit, f"{name}:{key}", saved[key], expected[name][key])
    canonical = maps["全rawshadow"][0]
    verdict_errors = []
    for case in cases_saved:
        actual = case["戦略判定"]
        final = canonical[case["発動ID"]]["戦略判定"]
        audit.check(case["イベントID"] + ":全三戦略verdictはcanonical", actual, final)
        audit.check(case["イベントID"] + ":自己複合判定", case["複合判定"], final[case["戦略"]])
        if actual != final:
            verdict_errors.append(case["イベントID"])
    shadow_map, cases_map = expected["全rawshadow"], expected["全九入口"]
    proof = {"全件一致": audit.mismatches == 0, "照合項目数": audit.count, "不一致数": audit.mismatches, "不一致": audit.errors,
        "判定対象": "全独立計算列・全raw/採用集合・全戦略verdict。主W未使用パターン診断列は対象外",
        "表示属性注意": bool(verdict_errors), "case内canonical判定不一致数": len(verdict_errors),
        "入力場数": len(manifest["entries"]), "期間場数": dict(phases), "独立足数": dict(totals),
        "保存context数": len(contexts_saved), "保存局面数": len(states_saved), "保存上位足数": len(uppers_saved),
        "保存発動候補数": len(shadows_saved), "保存shadow数": len(shadows_saved), "保存入口数": len(cases_saved),
        "旧21canonical発動数": len(old_canonical), "独立旧raw数": len(original_raw),
        "新M22準備raw数": sum(r["共通M22準備"] for r in shadow_map.values()),
        "新M22除外raw数": sum(not r["共通M22準備"] for r in shadow_map.values()),
        "独立入口数": len(cases_map), "戦略別入口数": dict(Counter(r["入口ID"] for r in cases_map.values())),
        "コードSHA256": V.sha(Path(__file__)), "入力台帳SHA256": V.sha(INPUT),
        "独立価格発動補助SHA256": V.sha(PRICE_HELPER), "旧21機能照合SHA256": V.sha(OLD_WORK / "状態独立確認.json"),
        "旧21canonical展開SHA256": old_sha, "全複合context展開SHA256": context_sha,
        "全局面展開SHA256": state_sha, "上位足展開SHA256": upper_sha,
        "発動候補展開SHA256": shadow_sha, "全複合shadow展開SHA256": shadow_sha, "入口事例展開SHA256": case_sha,
        "検証範囲": "原価格から全1/3/5/15分足と固定21独立MACD/BB/Stoch/Wilderを再計算。旧21全raw4475をcanonical shadowと比較し、旧case他戦略表示は使わない。同場隣接公開15分ペア/欠枠・非公開・不正単点reset、現前キー/ADX幅変化/DX/ゼロ和・平滑恒等残差、公開as-of、新旧Mと全旧raw保持/S1S2採否/全九集合を別計算。全競合確定後のcase全三戦略verdictと自己判定のcanonical一致まで照合。",
        "限界": "22主coreをimportしない。固定21の独立価格/発動補助を読み取り再用するが主21class自己再生ではない。最新公開curだけをas-ofへ使い、非公開marker自体で参照を進めない一方、分類ペア履歴は非公開で切る。先着/一建玉受入/会計/追尾は別監査。主W未使用パターン列や原板全本文の再抽出は対象外。全65場は既使用で将来の収益性を証明しない。"}
    (work / "状態独立確認.json").write_text(json.dumps(proof, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({k: proof[k] for k in ("全件一致", "照合項目数", "不一致数", "保存shadow数", "保存入口数",
        "新M22除外raw数", "case内canonical判定不一致数")}, ensure_ascii=False))
    return proof


def main() -> None:
    """正式再生完了通知後だけ全量独立再構成を開始する。

    引数: なし。--study/--work/--実行許可を読む。
    返り値: None。不一致時は非0終了。
    """
    parser = argparse.ArgumentParser(description="00022上位変化と全採否の独立確認")
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
