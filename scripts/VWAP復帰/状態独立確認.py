"""00019の補助参照を固定18へ照合し、Q1/Q2を独立原価格・ATRから再構成する。"""

from __future__ import annotations

import argparse
from collections import Counter
import importlib.util
import json
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT / "study/00019_VWAP復帰の入口と通常出口"
WORK = ROOT / "work/VWAP復帰/00019"
INPUT = ROOT / "study/00008_外部研究を共通尺度へ移して探索/入力台帳.json"
PRICE_HELPER = ROOT / "scripts/RSI構造/状態独立確認.py"
AUDIT_HELPER = ROOT / "scripts/VWAP入力/独立確認.py"
OLD_STUDY = ROOT / "study/00018_VWAPの位置と傾きで順行反転を比較"
OLD_WORK = ROOT / "work/VWAP入口/00018"
OLD_STATE_CODE = ROOT / "scripts/VWAP入口/状態独立確認.py"
REFERENCE_FIELDS = ("配信VWAP", "当場差分VWAP", "配信3足前VWAP", "差分3足前VWAP",
    "補助epoch", "identity", "native有効", "差分有効", "N共通準備", "D共通準備",
    "補助参照", "N除外理由", "D除外理由")


def helper(path: Path, name: str) -> Any:
    """既存の独立価格/比較補助だけを読む。

    引数: path (Path) は独立補助、name (str) はモジュール名。
    返り値: Any は補助。新19入口や元指標classはimportしない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


S = helper(PRICE_HELPER, "VWAP復帰の独立価格")
V = helper(AUDIT_HELPER, "VWAP復帰の独立比較")


def generate(frames: list[dict], higher: list[dict], references: dict[int, dict],
             session: str, period: str) -> tuple[dict[str, dict], dict[str, dict], dict]:
    """独立OHLC/ATR・固定参照で、追加方向前Q候補と全12入口を求める。

    引数: frames/higher (list[dict]) は独立下位/15分足、references (dict[int,dict]) は固定18同値の参照、
    session/period (str) は場/期間。
    返り値: tuple[dict,dict,dict] はQ候補・12発動・共通準備品質。
    """
    _, _, cutoff, deadline = S.S.G.times(session)
    candidates, events, counts, rejected, previous = {}, {}, Counter(), Counter(), None
    for frame in frames:
        if not frame["publish"]:
            previous = None
            continue
        ref = references[frame["index"]]
        prior = references[previous["index"]] if previous is not None else None
        upper = S.upper_context(frame, higher)
        reasons = []
        if previous is None or frame["index"] != previous["index"] + 1 or frame["missing"]:
            reasons.append("前足が同場連続公開でない")
        if not ref["N共通準備"]:
            reasons.append("現在N四点未準備")
        if previous is None or not S.S.finite(frame["atr"], previous["atr"]) or min(frame["atr"], previous["atr"]) <= 0:
            reasons.append("現在または前ATR未準備")
        if prior is None or not prior["native有効"] or prior["補助epoch"] != ref["補助epoch"]:
            reasons.append("前native未確認またはepoch不一致")
        if not upper["上位準備済"]:
            reasons.append("上位未準備")
        if frame["confirm"] - frame["end"] > 30:
            reasons.append("確認遅延30秒超")
        time_ok = frame["confirm"] < cutoff and deadline - frame["confirm"] >= 3600
        counts["公開足数"] += 1
        counts["共通準備可足数"] += int(not reasons)
        counts["共通時間条件可足数"] += int(not reasons and time_ok)
        rejected.update(reasons)
        if not reasons and time_ok:
            row = {**frame, **ref, **{k: upper[k] for k in
                ("上位準備済", "上位方向", "上位確認秒", "上位確認行", "上位足終了秒")},
                "直前足": {**{k: previous[k] for k in ("index", "close", "atr", "confirm", "confirm_line")},
                    "配信VWAP": prior["配信VWAP"], "補助epoch": prior["補助epoch"]}}
            for side in (1, -1):
                before = side * (previous["close"] - prior["配信VWAP"])
                current = side * (frame["close"] - ref["配信VWAP"])
                improved = side * (frame["close"] - previous["close"]) > 0
                q1 = bool(before <= 0 and current > 0 and improved and side * (ref["配信VWAP"] - ref["配信3足前VWAP"]) > 0)
                q2 = bool(before < -previous["atr"] and -frame["atr"] <= current < 0 and improved)
                for family, found in (("Q1", q1), ("Q2", q2)):
                    if not found:
                        continue
                    base = f'NK225_{session}_{frame["minutes"]}分_{family}_{frame["index"]:04d}_{side}'
                    fired = []
                    for extra in ("なし", "15分方向一致"):
                        if extra != "なし" and upper["上位方向"] != side:
                            continue
                        source = f'{frame["minutes"]}分_{family}_{extra}'
                        identity = f'NK225_{session}_{source}_{frame["index"]:04d}_{side}'
                        events[identity] = {**row, "場": session, "期間": period, "時間足分": frame["minutes"],
                            "入口ID": source, "入口系統": family, "補助": extra, "役割": "順行" if family == "Q1" else "反転",
                            "side": side, "方向": "買い" if side == 1 else "売り", "QイベントID": base, "イベントID": identity,
                            "要求時計秒": frame["confirm"], "要求原板行": frame["confirm_line"],
                            "確認遅延秒": frame["confirm"] - frame["end"], "足終了時計秒": frame["end"],
                            "期限時計秒": deadline, "残り分_判断時": (deadline - frame["confirm"]) / 60,
                            "入口中心まで方向距離pt": None,
                            "判断終値からnative方向距離pt": side * (ref["配信VWAP"] - frame["close"]),
                            "250ptのATR倍": 250 / frame["atr"]}
                        fired.append(source)
                    candidates[base] = {"場": session, "期間": period, "時間足分": frame["minutes"], "QイベントID": base,
                        "系統": family, "side": side, "判断足番号": frame["index"], "要求時計秒": frame["confirm"],
                        "要求原板行": frame["confirm_line"], "発動入口ID": fired}
        previous = frame
    return candidates, events, {**dict(counts), "共通準備除外理由": dict(rejected)}


def run(study: Path, work: Path) -> dict:
    """正式再生後だけ固定18全参照と独立価格の新12入口を照合する。

    引数: study/work (Path) は19正式試行/作業先。
    返り値: dict は明示合否・件数・指紋。運用通常出口/会計は別コードへ分ける。
    """
    for name in ("結果.json", "固定.json", "入口品質.json"):
        if not (study / name).exists():
            raise ValueError("正式再生完了資料がないため実行しません")
    audit, manifest, config = V.Audit(), V.read(INPUT), V.read(study / "条件.json")
    old_proof = V.read(OLD_STUDY / "状態独立確認.json")
    audit.check("固定18独立確認が成功", old_proof["全件一致"], True)
    audit.check("固定18独立コード指紋", V.sha(OLD_STATE_CODE), old_proof["コードSHA256"])
    old_rows, old_sha = S.compressed_rows(OLD_WORK / "全足参照.jsonl.gz")
    audit.check("固定18全足展開内容指紋", old_sha, old_proof["全足参照展開SHA256"])
    rows, reference_sha = S.compressed_rows(work / "全足参照.jsonl.gz")
    old = {(r["場"], r["時間足分"], r["index"]): r for r in old_rows}
    current = {(r["場"], r["時間足分"], r["index"]): r for r in rows}
    audit.check("固定18の全56351参照", len(old_rows), 56351)
    audit.check("19参照キー一意", len(current), len(rows))
    S.compare_keys(audit, "固定18対19全参照集合", set(current), set(old))
    for key in current.keys() & old.keys():
        audit.check(f"18固定全参照{key}", current[key], old[key])
    candidate_rows, candidate_sha = S.compressed_rows(work / "発動候補.jsonl.gz")
    cases, cases_sha = S.compressed_rows(work / "入口事例.jsonl.gz")
    saved_candidates = {r["QイベントID"]: r for r in candidate_rows}
    saved_cases = {r["イベントID"]: r for r in cases}
    audit.check("保存Q候補ID一意", len(saved_candidates), len(candidate_rows))
    audit.check("保存入口ID一意", len(saved_cases), len(cases))
    actual_quality = {(r["場"], r["時間足分"]): r for r in V.read(study / "入口品質.json")}
    expected_candidates, expected_cases, frame_count, phases = {}, {}, Counter(), Counter()
    banks, contract = {n: S.Indicators() for n in (1, 3, 5, 15)}, None
    for entry in manifest["entries"]:
        session, codes = entry["session"], tuple(entry["in_session_contract_codes"])
        if len(codes) != 1:
            raise ValueError("価格限月が一意でない")
        if contract is not None and codes != contract:
            banks = {n: S.Indicators() for n in banks}
        contract = codes
        period = "後続検査" if session[:10] >= config["分割"]["後続開始日"] else (
            "条件選択" if session[:10] >= config["分割"]["選択開始日"] else "学習")
        phases[period] += 1
        data = S.S.observed(entry)
        formed = {n: S.S.bars(data, session, n, bank) for n, bank in banks.items()}
        for minutes in (1, 3, 5):
            refs = {}
            for frame in formed[minutes]:
                source = current[session, minutes, frame["index"]]
                for field in ("index", "start", "end", "confirm", "confirm_line", "publish", "missing"):
                    audit.check(f"{session}:{minutes}:{frame['index']}:独立価格足:{field}", source[field], frame[field])
                refs[frame["index"]] = {k: source[k] for k in REFERENCE_FIELDS}
            candidates, events, quality = generate(formed[minutes], formed[15], refs, session, period)
            expected_candidates.update(candidates)
            expected_cases.update(events)
            actual = actual_quality.get((session, minutes), {})
            for key, value in quality.items():
                audit.check(f"{session}:{minutes}分:共通準備:{key}", actual.get(key, 0), value)
            for family in ("Q1", "Q2"):
                for extra in ("なし", "15分方向一致"):
                    source_id = f"{minutes}分_{family}_{extra}"
                    audit.check(f"{session}:{source_id}:発動数", actual["系統別発動数"][source_id],
                                sum(r["入口ID"] == source_id for r in events.values()))
            frame_count[str(minutes)] += len(formed[minutes])
        frame_count["15"] += len(formed[15])
        print(json.dumps({"場": session, "独立確認": "固定18参照・原価格ATR・Q1/Q2", "現時点不一致数": audit.mismatches}, ensure_ascii=False), flush=True)
    audit.check("固定65場", len(manifest["entries"]), 65)
    audit.check("固定40/24/1", dict(phases), {"学習": 40, "条件選択": 24, "後続検査": 1})
    S.compare_keys(audit, "方向追加前の全Q候補集合", set(saved_candidates), set(expected_candidates))
    for key in saved_candidates.keys() & expected_candidates.keys():
        audit.check(key + ":全Q候補", saved_candidates[key], expected_candidates[key])
    S.compare_keys(audit, "全12入口集合", set(saved_cases), set(expected_cases))
    fields = ("index", "start", "end", "minutes", "open", "high", "low", "close", "missing", "publish", "confirm",
        "confirm_line", "atr", "ema20", "ema20_previous", "rsi", "adx", "bb_mean", "bb_sd", "plus_di", "minus_di",
        "上位準備済", "上位方向", "上位確認秒", "上位確認行", "上位足終了秒", "直前足",
        "場", "期間", "時間足分", "入口ID", "入口系統", "補助", "役割", "side", "方向", "QイベントID",
        "要求時計秒", "要求原板行", "確認遅延秒", "足終了時計秒", "期限時計秒", "残り分_判断時",
        "入口中心まで方向距離pt", "判断終値からnative方向距離pt", "250ptのATR倍")
    for key in saved_cases.keys() & expected_cases.keys():
        for field in fields + REFERENCE_FIELDS:
            audit.check(key + ":" + field, saved_cases[key][field], expected_cases[key][field])
    result = {"全件一致": audit.mismatches == 0, "照合項目数": audit.count, "不一致数": audit.mismatches, "不一致": audit.errors,
        "入力場数": len(manifest["entries"]), "期間場数": dict(phases), "独立足数": dict(frame_count),
        "保存参照足数": len(rows), "固定18参照足数": len(old_rows), "保存発動候補数": len(candidate_rows),
        "独立発動候補数": len(expected_candidates), "保存入口数": len(cases), "独立入口数": len(expected_cases),
        "入口別件数": dict(Counter(r["入口ID"] for r in expected_cases.values())),
        "コードSHA256": V.sha(Path(__file__)), "入力台帳SHA256": V.sha(INPUT),
        "補助入力台帳SHA256": V.sha(ROOT / "study/00017_配信元VWAPと売買代金の入力監査/結果.json"),
        "全足参照展開SHA256": reference_sha, "固定18全足参照展開SHA256": old_sha,
        "発動候補展開SHA256": candidate_sha, "入口事例展開SHA256": cases_sha,
        "固定18独立確認SHA256": V.sha(OLD_STUDY / "状態独立確認.json"),
        "独立価格補助SHA256": V.sha(PRICE_HELPER), "独立比較補助SHA256": V.sha(AUDIT_HELPER),
        "検証範囲": "19全56351参照を固定18の全属性と照合し、固定18の展開SHA/原価格・原順補助独立proofコード指紋を確認。その既検証参照と原価格cacheから独立1/3/5/15足・WilderATR・上位EMAを再計算し、現在N4/前native・現在前ATR/同epoch・時点/時間・Q1/Q2境界・方向追加前全候補と12発動全集合を照合。前N4や下位EMA/ADX/BB/RSIをgateへ追加しない。",
        "限界": "新19入口/元指標classをimportして再生しない。補助値自体は固定18の独立済み全参照を再利用し、19で再度小列から全補助を別抽出した証明とはしない。受信/VWAP固有時計欠如を引き継ぐ。先着/通常出口/運用会計は別監査。"}
    (work / "状態独立確認.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("全件一致", "照合項目数", "不一致数", "保存参照足数", "保存発動候補数", "保存入口数")}, ensure_ascii=False))
    if audit.errors:
        print(json.dumps(audit.errors[:5], ensure_ascii=False))
    return result


def main() -> None:
    """正式再生完了通知後だけ全量の状態監査を実行する。

    引数: なし。--study/--work/--実行許可を読む。
    返り値: None。不許可時は実データを開かない。
    """
    parser = argparse.ArgumentParser(description="00019固定参照・Q1/Q2独立確認")
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
