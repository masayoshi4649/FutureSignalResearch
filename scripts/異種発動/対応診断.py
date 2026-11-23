"""canonical発動台帳から局面選択・参加集合・入口先着と利益回収を診断する。"""

from collections import Counter, defaultdict
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT / "study/00021_BBとMACDとストキャスの発動切替"
WORK = ROOT / "work/異種発動/00021"
PERIODS = ("学習", "条件選択", "後続検査")
POLICIES = ("T0", "R0", "A0", "S1")
LABELS = ("順行先着", "逆行先着", "期限未達", "観測不足", "未約定")


def module(path: Path, name: str) -> Any:
    """保存済み同新規の会計対応補助だけを読む。

    引数: path(Path)は補助、name(str)は識別名。
    返り値: Anyは補助モジュール。21主coreは再実行しない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


P = module(ROOT / "scripts/VWAP復帰/対応診断.py", "異種発動の対応会計補助")


def read(name: str, artifacts: dict) -> list[dict]:
    """固定展開指紋を確認して作業明細を読む。

    引数: name(str)はgzip名、artifacts(dict)は正式成果物台帳。
    返り値: list[dict]は保存された全行。
    """
    expected = next(r["展開内容SHA256"] for r in artifacts["ファイル"] if r["パス"].endswith(name))
    with gzip.open(WORK / name, "rb") as stream:
        data = stream.read()
    if hashlib.sha256(data).hexdigest() != expected:
        raise ValueError("固定作業指紋が不一致")
    return [json.loads(line) for line in data.splitlines() if line.strip()]


def labels(rows: list[dict]) -> dict:
    """全五分類を同じ分母で集計する。

    引数: rows(list[dict])は発動台帳の群。
    返り値: dictは件数・率。未約定を分け期限/不足を分母へ残す。
    """
    values = Counter(r["ラベル"] for r in rows)
    if values.keys() - set(LABELS):
        raise ValueError("未知のラベル")
    filled = len(rows) - values["未約定"]
    return {"候補数": len(rows), "約定候補数": filled, **{k: values[k] for k in LABELS},
            "確認率": values["順行先着"] / filled if filled else None}


def before_conflict(row: dict, strategy: str) -> bool:
    """保存済み当時局面から競合処理前の選択を別計算する。

    引数: row(dict)は一つの有効発動、strategy(str)は四戦略。
    返り値: boolは選択候補。将来ラベル/他caseの表示欄を参照しない。
    """
    if strategy == "T0":
        return row["入口系統"] == "T1"
    if strategy == "R0":
        return row["入口系統"] == "R1"
    if strategy == "A0":
        return True
    return bool(row["局面"] == "トレンド" and row["入口系統"] == "T1" and row["side"] == row["DI方向"]
                or row["局面"] == "レンジ" and row["入口系統"] == "R1")


# ----------------------------------------
# case内の他戦略表示は既知の古いsnapshotがあるため、一貫してshadowを正本にする。

def main() -> None:
    """全発動の機会と全12運用の対応を小型JSONへ保存する。

    引数: なし。
    返り値: None。固定core/生明細/正式数値を上書きしない。
    """
    artifacts = json.loads((STUDY / "作業成果物.json").read_text(encoding="utf-8"))
    result = json.loads((STUDY / "結果.json").read_text(encoding="utf-8"))
    shadow, cases = read("全複合shadow.jsonl.gz", artifacts), read("入口事例.jsonl.gz", artifacts)
    details, context = read("全運用詳細.jsonl.gz", artifacts), read("全複合context.jsonl.gz", artifacts)
    events = {r["イベントID"]: r for r in cases}
    canonical = {r["発動ID"]: r for r in shadow}
    if len(events) != len(cases) or len(canonical) != len(shadow):
        raise ValueError("発動/採用入口の重複")
    selected, counts, checks = defaultdict(set), defaultdict(list), 0
    for r in cases:
        own = canonical[r["発動ID"]]["戦略判定"][r["戦略"]]
        if r["複合判定"] != own or r["戦略判定"][r["戦略"]] != own:
            raise ValueError("実選択の判定がcanonicalと不一致")
        selected[r["入口ID"], r["期間"]].add(r["発動ID"])
        checks += 2
    for r in shadow:
        alignment = "同値" if not r["DI方向"] else "一致" if r["DI方向"] == r["side"] else "逆向き"
        counts[r["時間足分"], r["期間"], r["局面"], r["入口系統"], r["side"], alignment].append(r)
    price_groups, price_confirmation = defaultdict(list), []
    for r in shadow:
        change = r["side"] * (r["close"] - r["直前足"]["close"])
        direction = "順行変化" if change > 0 else "逆行変化" if change < 0 else "同値"
        price_groups[r["時間足分"], r["期間"], r["入口系統"], direction].append(r)
    for (size, period, family, direction), rows in sorted(price_groups.items()):
        price_confirmation.append({"足分": size, "期間": period, "系統": family, "現足価格方向": direction,
            "全発動": labels(rows), "S1採用": labels([r for r in rows if r["戦略判定"]["S1"]["採用"]])})
    opportunities = []
    for (size, period, state, family, side, alignment), rows in sorted(counts.items()):
        accepted = [r for r in rows if r["戦略判定"]["S1"]["採用"]]
        rejected = [r for r in rows if not r["戦略判定"]["S1"]["採用"]]
        opportunities.append({"足分": size, "期間": period, "局面": state, "系統": family, "side": side,
            "DI方向整合": alignment, "全発動": labels(rows), "採用": labels(accepted), "見送り": labels(rejected),
            "避けた逆行先着": sum(r["ラベル"] == "逆行先着" for r in rejected),
            "逃した順行先着": sum(r["ラベル"] == "順行先着" for r in rejected)})
    stages, participation = [], []
    for size in (1, 3, 5):
        for period in PERIODS:
            own = [r for r in shadow if (r["時間足分"], r["期間"]) == (size, period)]
            for strategy in POLICIES:
                expected = {r["発動ID"] for r in own if r["戦略判定"][strategy]["採用"]}
                if expected != selected[f"{size}分_{strategy}", period]:
                    raise ValueError("canonicalの採否集合と全採用入口が不一致")
                checks += 1
                chosen = [r for r in own if before_conflict(r, strategy)]
                final = [r for r in own if r["戦略判定"][strategy]["採用"]]
                stages.append({"足分": size, "期間": period, "戦略": strategy,
                    "段階": [{"段階": "全有効発動", **labels(own)}, {"段階": "手法と当時局面選択", **labels(chosen)},
                               {"段階": "同時競合除外後", **labels(final)}]})
            a = {r["発動ID"] for r in own if r["戦略判定"]["A0"]["採用"]}
            b = {r["発動ID"] for r in own if r["戦略判定"]["S1"]["採用"]}
            participation.append({"足分": size, "期間": period, "共通発動": labels([canonical[k] for k in a & b]),
                "A0のみ": labels([canonical[k] for k in a - b]), "S1のみ": labels([canonical[k] for k in b - a])})
    trades = defaultdict(list)
    for r in details:
        trades[r["候補ID"], r["品質"]["期間"]].extend(r["取引"])
    official = {r["候補ID"]: r for r in result["結果"]}
    comparisons, protection, realization = [], [], []
    for size in (1, 3, 5):
        for period in PERIODS:
            for left, right in (("A0", "S1"), ("T0", "S1"), ("R0", "S1"), ("T0", "A0"), ("R0", "A0")):
                a, b = f"{size}分_{left}_X0", f"{size}分_{right}_X0"
                comparison = P.compare(trades[a, period], trades[b, period], events, True)
                if comparison["全運用純額差円"] != official[b][period]["運用"]["追加0pt純損益円"] - official[a][period]["運用"]["追加0pt純損益円"]:
                    raise ValueError("運用差の参加集合分解が不一致")
                comparisons.append({"足分": size, "期間": period, "左": a, "右": b, "運用比較": comparison})
                checks += 1
    for cid in official:
        for period in PERIODS:
            values = trades[cid, period]
            armed = [t for t in values if t["追尾起動"]]
            trailing = [t for t in armed if t["返済理由"] == "必須利益追尾"]
            protection.append({"候補ID": cid, "期間": period, "完結数": len(values), "追尾起動数": len(armed),
                "起動後純赤字数": sum(t["基準純損益円"] < 0 for t in armed),
                "起動後同値未満約定数": sum((1 if t["方向"] == "買い" else -1)*(t["返済価格"]-t["新規価格"]) < 0 for t in armed),
                "最終設定未満約定数": sum(t["最終追尾から実返済方向差pt"] < 0 for t in armed),
                "追尾理由の設定未満約定数": sum(t["最終追尾から実返済方向差pt"] < 0 for t in trailing),
                "最終設定からの不足pt計": sum(max(0, -t["最終追尾から実返済方向差pt"]) for t in armed)})
            for family in ("T1", "R1"):
                own = [t for t in values if events[t["入口イベントID"]]["入口系統"] == family]
                for t in own:
                    case = events[t["入口イベントID"]]
                    for field in ("新規時計秒", "新規原板行", "新規価格"):
                        if t[field] != case[field]:
                            raise ValueError("実新規と先着仮新規が異なるため対応不可")
                        checks += 1
                wins = [t for t in own if events[t["入口イベントID"]]["ラベル"] == "順行先着"]
                losses = [t for t in own if events[t["入口イベントID"]]["ラベル"] == "逆行先着"]
                realization.append({"候補ID": cid, "期間": period, "系統": family, "実新規対応数": len(own),
                    "対応先着250数": len(wins), "先着250だが基準純赤字数": sum(t["基準純損益円"] < 0 for t in wins),
                    "先着250だが250利確理由以外数": sum(t["返済理由"] != "利確" for t in wins),
                    "対応先着125数": len(losses), "先着125でも基準黒字数": sum(t["基準純損益円"] > 0 for t in losses),
                    "基準純額円": sum(t["基準純損益円"] for t in own), "追加5pt純額円": sum(t["追加滑り5pt純損益円"] for t in own)})
    preparation = []
    for size in (1, 3, 5):
        for period in PERIODS:
            rows = [r for r in context if (r["時間足分"], r["期間"]) == (size, period)]
            preparation.append({"足分": size, "期間": period, "全足数": len(rows), "公開足数": sum(r["publish"] for r in rows),
                "共通M足数": sum(r["共通M準備"] for r in rows), "時間条件付きM足数": sum(r["共通M準備"] and r["時間条件可"] for r in rows),
                "除外理由延べ数": dict(Counter(reason for r in rows for reason in r["M除外理由"]))})
    output = {"確認日": "2026-11-04", "全65場既使用": True, "対応集合全件一致": True, "照合項目数": checks,
        "全発動候補数": len(shadow), "純入口数": len(cases), "全複合context数": len(context),
        "準備総括": preparation, "局面機会表": opportunities, "段階別": stages, "A0対S1発動集合": participation,
        "指標発動と実価格変化": price_confirmation,
        "運用対応": comparisons, "利益保護": protection, "入口先着と利益回収": realization,
        "コードSHA256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), "結果SHA256": hashlib.sha256((STUDY / "結果.json").read_bytes()).hexdigest(),
        "採否正本": "全複合shadow.jsonl.gz。case内他戦略欄の既知43表示差は分析入力にしない。各caseの実選択戦略だけは正本と一致を検査。",
        "限界": "全有効発動は共通Mと時間条件を満たすT/Rであり、指標未準備の価格足へ仮ラベルを作らない。A0の競合除外とS1の片方採用でS1はA0の単純部分集合とは限らない。全戦略と足幅の重複を独立標本に加算しない。先着250は各実新規から期限まで仮保有した反実仮想で、返済後の値も含む。利益回収との対応は事後診断であり未来ラベルを新規へ使わない。"}
    (STUDY / "対応診断.json").write_text(json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({k: output[k] for k in ("対応集合全件一致", "照合項目数", "全発動候補数", "純入口数")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
