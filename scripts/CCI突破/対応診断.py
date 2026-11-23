"""保存済みCCI複合入口の選別・実参加・回収を別々に対応する。"""

from collections import Counter
import importlib.util
import json
from pathlib import Path
from statistics import median
import sys


ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT / "study/00031_CCI持続と上位BB幅"
WORK = ROOT / "work/CCI突破/00031"
HELPER = ROOT / "scripts/PSY突破/対応診断.py"
PERIODS = ("学習", "条件選択", "後続検査")
POLICIES = ("C0", "C1")
spec = importlib.util.spec_from_file_location("CCI対応の保存物共通集計", HELPER)
H = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = H
spec.loader.exec_module(H)


def middle(values: list[float | None]) -> float | None:
    """欠測を補わず、観測済み値だけの中央値を求める。

    引数: values(list[float | None])は同一群の保存値。
    返り値: float | Noneは記述統計。空群は欠測。
    """
    available = [v for v in values if v is not None]
    return median(available) if available else None


def run() -> dict:
    """先着と実会計を再計算せず、固定二案の差を分解する。

    引数: なし。保存JSONと圧縮明細だけを読む。
    返り値: dictは照合・入口選別・実参加・価格位置・回収の集計。
    """
    cases = H.read(WORK / "入口事例.jsonl.gz")
    raw = H.read(WORK / "全複合shadow.jsonl.gz")
    details = H.read(WORK / "全運用詳細.jsonl.gz")
    result = H.read(STUDY / "結果.json")
    checks, errors = 0, []

    def check(name: str, actual: object, expected: object) -> None:
        """不一致を保存し、最終合否に反映する。

        引数: name(str)は項目、actual/expected(object)は実値/期待値。
        返り値: None。相違を丸めて一致へ変えない。
        """
        nonlocal checks
        checks += 1
        if actual != expected:
            errors.append({"項目": name, "実値": actual, "期待値": expected})

    case_map = {r["イベントID"]: r for r in cases}
    check("case一意", len(case_map), len(cases))
    check("原P一意", len({r["発動ID"] for r in raw}), len(raw))
    check("二案", [r["候補ID"] for r in result["結果"]], [f"3分_{p}_X0" for p in POLICIES])
    trades = [{**t, "候補ID": d["候補ID"]} for d in details for t in d["取引"]]
    for trade in trades:
        own = case_map[trade["入口イベントID"]]
        for field in ("新規価格", "新規時計秒", "新規原板行"):
            check(trade["候補ID"] + trade["建玉ID"] + field, trade[field], own[field])

    # ----------------------------------------
    # 値による純入口選別と、一建玉が変える参加集合を分ける。

    stages, entrances, participation, positions, recovery = [], [], [], [], []
    for period in PERIODS:
        origin = [r for r in raw if r["期間"] == period]
        stages.append({"期間": period, "原価格発動数": len(origin),
            "共通M準備数": sum(r["共通M準備"] for r in origin),
            "先着評価対象数": sum(r["先着評価対象"] for r in origin),
            "M除外理由別": dict(Counter(reason for r in origin for reason in r["M除外理由"])),
            "DayNight原発動数": {s: sum(r["場"].endswith(s) for r in origin) for s in ("Day", "Night")},
            "全案採用数": {p: sum(r["戦略判定"][p]["採用"] for r in origin) for p in POLICIES}})
        left = {r["発動ID"]: r for r in cases if r["戦略"] == "C0" and r["期間"] == period}
        right = {r["発動ID"]: r for r in cases if r["戦略"] == "C1" and r["期間"] == period}
        check(period + "純入口部分集合", set(right) <= set(left), True)
        for key in right:
            for field in ("要求時計秒", "要求原板行", "side", "新規価格", "新規時計秒", "新規原板行", "ラベル", "判定時計秒", "判定原板行"):
                check(period + key + field, right[key][field], left[key][field])
        entrances.append({"期間": period, "保持入口": H.entry_summary(list(right.values())),
            "除外入口": H.entry_summary([r for k, r in left.items() if k not in right]),
            "新規追加入口数": len(set(right)-set(left))})
        for retained in (True, False):
            own = [r for k, r in left.items() if (k in right) == retained]
            boundary = {r["イベントID"]: r["直前最高H"] if r["side"] == 1 else r["直前最安L"] for r in own}
            positions.append({"期間": period, "C1保持": retained, **H.entry_summary(own),
                "要求終値の突破距離pt中央値": middle([r["side"]*(r["close"]-boundary[r["イベントID"]]) for r in own]),
                "仮新規の突破距離pt中央値": middle([r["side"]*(r["新規価格"]-boundary[r["イベントID"]]) if r["新規価格"] is not None else None for r in own])})
        lt = [r for r in trades if r["候補ID"] == "3分_C0_X0" and r["期間"] == period]
        rt = [r for r in trades if r["候補ID"] == "3分_C1_X0" and r["期間"] == period]
        lm, rm = {H.identity(t): t for t in lt}, {H.identity(t): t for t in rt}
        check(period + "C0実新規一意", len(lm), len(lt))
        check(period + "C1実新規一意", len(rm), len(rt))
        common, removed, added = lm.keys() & rm.keys(), lm.keys()-rm.keys(), rm.keys()-lm.keys()
        for key in common:
            for field in ("返済時計秒", "返済原板行", "返済価格", "返済理由", "基準純損益円", *[f"追加滑り{n}pt純損益円" for n in (0, 5, 10)]):
                check(period + str(key) + field, lm[key][field], rm[key][field])
        decomposed = {}
        for fee in (0, 5, 10):
            field = f"追加滑り{fee}pt純損益円"
            delta = sum(t[field] for t in rt)-sum(t[field] for t in lt)
            same = sum(rm[k][field]-lm[k][field] for k in common)
            check(period + str(fee) + "総額分解", delta, same-sum(lm[k][field] for k in removed)+sum(rm[k][field] for k in added))
            decomposed[f"追加{fee}pt総額差円"] = delta
            decomposed[f"追加{fee}pt共通出口差円"] = same
        participation.append({"期間": period, "共通実新規数": len(common),
            "C0のみ": H.operation_summary([lm[k] for k in removed]),
            "C1のみ": H.operation_summary([rm[k] for k in added]), **decomposed})

    # ----------------------------------------
    # 仮想の250到達と、実保有の到達・費用後赤字を分離する。

    for policy in POLICIES:
        for period in PERIODS:
            cid = f"3分_{policy}_X0"
            own = [t for t in trades if t["候補ID"] == cid and t["期間"] == period]
            favorable = [t for t in own if case_map[t["入口イベントID"]]["ラベル"] == "順行先着"]
            armed = [t for t in own if t["追尾起動"]]
            reds = [t for t in armed if t["起動後純赤字"]]
            before = 0
            for t in favorable:
                c = case_map[t["入口イベントID"]]
                before += (t["返済時計秒"], t["返済原板行"]) < (c["判定時計秒"], c["判定原板行"])
            same = sum(t["返済価格"] == t["新規価格"] for t in reds)
            adverse = sum((1 if t["方向"] == "買い" else -1)*(t["返済価格"]-t["新規価格"]) < 0 for t in reds)
            check(cid + period + "起動後赤字内訳", len(reds), same+adverse)
            recovery.append({"候補ID": cid, "期間": period, "完結取引数": len(own),
                "仮250先着取引数": len(favorable), "仮250判定前返済数": before,
                "実保有MFE250取引数": sum(t["観測最大順行pt"] >= 250 for t in own),
                "追尾起動数": len(armed), "起動後純赤字数": len(reds),
                "同値返済費用赤字数": same, "不利返済赤字数": adverse})
    warnings = [{"候補ID": d["候補ID"], "場": d["場"], "期間": d["品質"]["期間"],
        **{key: d["品質"][key] for key in ("観測現金増減円", "完結取引数", "観測経路注意取引数", "経路注意取引純損益円", "保有中空白区間数", "新規待機中空白区間数", "最長正常板間隔秒")}}
        for d in details if d["品質"]["観測経路注意"]]
    files = (Path(__file__), HELPER, STUDY / "結果.json", STUDY / "固定.json", STUDY / "独立監査.json",
        WORK / "診断予定.json", WORK / "入口事例.jsonl.gz", WORK / "全複合shadow.jsonl.gz", WORK / "全運用詳細.jsonl.gz")
    output = {"全件一致": not errors, "照合項目数": checks, "不一致数": len(errors), "不一致": errors,
        "全66場既使用": True, "期間別原発動": stages, "入口追加比較": entrances,
        "実参加比較": participation, "保持除外の価格位置": positions, "候補別回収": recovery,
        "品質注意の実参加": warnings,
        "限界": "既使用資料の記述的対応。指標条件追加の成績を単独指標の性能にせず、不採用を自動反転へ変換しない。価格位置差は同時点の選別で、待機の価格進行ではない。学習注意期の全体確定額nullを置き換えない。",
        "ファイルSHA256": {p.relative_to(ROOT).as_posix(): H.sha(p) for p in files}}
    (WORK / "対応診断.json").write_text(json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False)+"\n", encoding="utf-8")
    if errors:
        raise RuntimeError("保存物対応の不一致を確認してください")
    return output


if __name__ == "__main__":
    proof = run()
    print(json.dumps({k: proof[k] for k in ("全件一致", "照合項目数", "不一致数")}, ensure_ascii=False))
