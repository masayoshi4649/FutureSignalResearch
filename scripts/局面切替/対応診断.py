"""全Qの採否を局面/手法別に分け、切替の機会差と運用差を診断する。"""

from collections import Counter, defaultdict
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT / "study/00020_テクニカル局面による順行反転の切替"
WORK = ROOT / "work/局面切替/00020"
PERIODS = ("学習", "条件選択", "後続検査")
LABELS = ("順行先着", "逆行先着", "期限未達", "観測不足", "未約定")


def module(path: Path, name: str) -> Any:
    """固定済み対応会計補助だけを読む。

    引数: path(Path)は補助、name(str)は識別名。
    返り値: Anyはモジュール。入口/運用エンジンを実行しない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


P = module(ROOT / "scripts/VWAP復帰/対応診断.py", "局面診断の同新規会計補助")


def read(name: str, artifacts: dict) -> list[dict]:
    """正式な展開指紋を検査して作業明細を復元する。

    引数: name(str)はgzip名、artifacts(dict)は正式台帳。
    返り値: list[dict]は保存された全行。
    """
    expected = next(r["展開内容SHA256"] for r in artifacts["ファイル"] if r["パス"].endswith(name))
    with gzip.open(WORK / name, "rb") as stream:
        data = stream.read()
    if hashlib.sha256(data).hexdigest() != expected:
        raise ValueError("作業明細の指紋が不一致")
    return [json.loads(line) for line in data.splitlines() if line.strip()]


def labels(rows: list[dict]) -> dict:
    """全五分類をゼロ件も残して集計する。

    引数: rows(list[dict])は同じ診断群の影候補。
    返り値: dictは候補数/約定/先着数と率。期限/不足を分母から消さない。
    """
    counts = Counter(r["ラベル"] for r in rows)
    if counts.keys() - set(LABELS):
        raise ValueError("未知の先着分類")
    filled = len(rows) - counts["未約定"]
    return {"候補数": len(rows), "約定候補数": filled, **{name: counts[name] for name in LABELS},
            "確認率": counts["順行先着"] / filled if filled else None}


# ----------------------------------------
# 先着は独立した仮参加、運用は一建玉の実参加として対応させる。

def main() -> None:
    """全局面の選別とS0対切替/出口の運用差を保存する。

    引数: なし。
    返り値: None。結果と固定した条件は変更しない。
    """
    artifacts = json.loads((STUDY / "作業成果物.json").read_text(encoding="utf-8"))
    result = json.loads((STUDY / "結果.json").read_text(encoding="utf-8"))
    shadow, cases = read("全複合shadow.jsonl.gz", artifacts), read("入口事例.jsonl.gz", artifacts)
    details = read("全運用詳細.jsonl.gz", artifacts)
    regimes, context = read("全局面.jsonl.gz", artifacts), read("全複合context.jsonl.gz", artifacts)
    events = {r["イベントID"]: r for r in cases}
    if len(events) != len(cases) or len({r["QイベントID"] for r in shadow}) != len(shadow):
        raise ValueError("純入口か全Qが重複")
    selected = defaultdict(set)
    for row in cases:
        selected[row["入口ID"], row["期間"]].add(row["QイベントID"])
    groups, funnel, opportunities = defaultdict(list), [], []
    for row in shadow:
        for strategy in ("S1", "S2"):
            decision = row["戦略判定"][strategy]
            state = row[strategy + "局面"]
            groups[row["時間足分"], strategy, state, row["入口系統"], row["side"], row["期間"]].append(row)
            if not row["共通M準備"] and decision["採用"]:
                raise ValueError("共通M前に採用")
    for (size, strategy, state, family, side, period), rows in sorted(groups.items()):
        accepted = [r for r in rows if r["戦略判定"][strategy]["採用"]]
        rejected = [r for r in rows if not r["戦略判定"][strategy]["採用"]]
        opportunities.append({"足分": size, "戦略": strategy, "局面": state, "系統": family,
            "side": side, "期間": period, "全Q": labels(rows), "採用": labels(accepted), "見送り": labels(rejected),
            "避けた逆行先着": sum(r["ラベル"] == "逆行先着" for r in rejected),
            "逃した順行先着": sum(r["ラベル"] == "順行先着" for r in rejected)})
    checks = 0
    for size in (1, 3, 5):
        for strategy in ("S1", "S2"):
            for family in ("Q1", "Q2"):
                for period in PERIODS:
                    original = [r for r in shadow if (r["時間足分"], r["入口系統"], r["期間"]) == (size, family, period)]
                    current = original
                    stages = [("全Q", lambda r: True), ("共通M", lambda r: r["共通M準備"]),
                        ("局面と方向", lambda r: r["戦略判定"][strategy]["局面段階採用"]),
                        ("EMA一致または収束", lambda r: r["戦略判定"][strategy]["三尺度EMA順行" if family == "Q1" else "二尺度収束"]),
                        ("RSI持続または戻り", lambda r: r["戦略判定"][strategy]["RSI三本持続" if family == "Q1" else "RSI戻り"]),
                        ("急変警戒なし", lambda r: not r["戦略判定"][strategy]["RSI急変警戒"]),
                        ("競合除外後", lambda r: r["戦略判定"][strategy]["採用"])]
                    records = []
                    for name, predicate in stages:
                        current = [r for r in current if predicate(r)]
                        records.append({"段階": name, **labels(current)})
                    expected = selected[f"{size}分_{strategy}", period]
                    actual = {r["QイベントID"] for r in current}
                    family_expected = {qid for qid in expected if next(r for r in shadow if r["QイベントID"] == qid)["入口系統"] == family}
                    if actual != family_expected:
                        raise ValueError("段階最終集合と純入口が不一致")
                    checks += 1
                    funnel.append({"足分": size, "戦略": strategy, "系統": family, "期間": period, "段階": records})
    trades = defaultdict(list)
    for row in details:
        trades[row["候補ID"], row["品質"]["期間"]].extend(row["取引"])
    official = {r["候補ID"]: r for r in result["結果"]}
    comparisons, protection = [], []
    for size in (1, 3, 5):
        for period in PERIODS:
            pairs = [(f"{size}分_S0_{policy}", f"{size}分_{strategy}_{policy}", "複合切替", True)
                     for strategy in ("S1", "S2") for policy in ("X0", "X1", "X2")]
            pairs += [(f"{size}分_{strategy}_{left}", f"{size}分_{strategy}_{right}", "通常出口", False)
                      for strategy in ("B1", "B2", "S0", "S1", "S2") for left, right in (("X0", "X1"), ("X0", "X2"), ("X1", "X2"))]
            for left, right, kind, identical in pairs:
                comparison = P.compare(trades[left, period], trades[right, period], events, identical)
                expected = official[right][period]["運用"]["追加0pt純損益円"] - official[left][period]["運用"]["追加0pt純損益円"]
                if comparison["全運用純額差円"] != expected:
                    raise ValueError("対応分解と正式純額が不一致")
                checks += 1
                comparisons.append({"足分": size, "期間": period, "左": left, "右": right, "比較": kind, "運用比較": comparison})
    for cid in official:
        for period in PERIODS:
            values = trades[cid, period]
            armed = [t for t in values if t["追尾起動"]]
            protection.append({"候補ID": cid, "期間": period, "完結数": len(values), "追尾起動数": len(armed),
                "起動後純赤字数": sum(t["基準純損益円"] < 0 for t in armed),
                "起動後同値未満約定数": sum((1 if t["方向"] == "買い" else -1)*(t["返済価格"]-t["新規価格"]) < 0 for t in armed),
                "最終設定未満約定数": sum(t["最終追尾から実返済方向差pt"] < 0 for t in armed),
                "最終設定からの不足pt計": sum(max(0, -t["最終追尾から実返済方向差pt"]) for t in armed)})
    output = {"確認日": "2026-11-04", "全65場既使用": True, "対応集合全件一致": True,
        "照合項目数": checks, "全Q候補数": len(shadow), "純入口数": len(cases),
        "局面機会表": opportunities, "段階別": funnel, "運用対応": comparisons, "利益保護": protection,
        "全15分局面数": len(regimes), "全複合context数": len(context),
        "局面切替回数": {p: sum(r[p + "切替"] for r in regimes) for p in ("S1", "S2")},
        "本命入口70目標数": sum(r["70目標"] and r["複合本命"] for r in result["入口評価"]),
        "コードSHA256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "結果SHA256": hashlib.sha256((STUDY / "結果.json").read_bytes()).hexdigest(),
        "限界": "全Q先着は各発動へ仮参加した結果で、一建玉運用の損益ではない。段階順は事前に固定した説明順で各条件の独立因果効果ではない。rangeのRSI30〜60はspike>=70と両立しないためrangeの急変除外は冗長。保護起動は返済要求前の実有効化で、要求待機中や約定後のMFEから起動を補わない。最終保護設定と実返済価格差は滑りだけでなく先行する通常出口等も含む。見送りを将来ラベルで実運用へ戻さない。"}
    (STUDY / "対応診断.json").write_text(json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({k: output[k] for k in ("対応集合全件一致", "照合項目数", "全Q候補数", "純入口数")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
