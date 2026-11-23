"""旧発動同値・準備差・局面選択差・実参加差を分離する。"""

from collections import Counter, defaultdict
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT / "study/00022_ADXと上位BB幅の変化による局面切替"
WORK = ROOT / "work/局面変化/00022"
OLD_STUDY = ROOT / "study/00021_BBとMACDとストキャスの発動切替"
PERIODS = ("学習", "条件選択", "後続検査")
POLICIES = ("A0", "S1", "S2")


def module(path: Path, name: str) -> Any:
    """既存の保存明細/対応会計補助だけを読む。

    引数: path(Path)は補助、name(str)は識別名。
    返り値: Anyはモジュール。主発動/運用は再実行しない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


B = module(ROOT / "scripts/異種発動/対応診断.py", "局面変化の旧21対応補助")
P, labels = B.P, B.labels


def read(name: str, artifacts: dict) -> list[dict]:
    """展開指紋を検査して22作業明細を読む。

    引数: name(str)はgzip名、artifacts(dict)は正式台帳。
    返り値: list[dict]は保存された全行。
    """
    expected = next(r["展開内容SHA256"] for r in artifacts["ファイル"] if r["パス"].endswith(name))
    with gzip.open(WORK / name, "rb") as stream:
        data = stream.read()
    if hashlib.sha256(data).hexdigest() != expected:
        raise ValueError("22明細の固定指紋が不一致")
    return [json.loads(line) for line in data.splitlines() if line.strip()]


def transition(row: dict) -> str:
    """当時の特徴と実採否から選択差の原因を分類する。

    引数: row(dict)は全旧発動を保持した新shadow。
    返り値: strは準備/共通/始動追加/失速抑止等。将来ラベルを分類に使わない。
    """
    if not row["共通M22準備"]:
        return "M22準備除外"
    old, new = row["戦略判定"]["S1"]["採用"], row["戦略判定"]["S2"]["採用"]
    if old and new:
        return "S1_S2共通採用"
    if new:
        return "低ADX始動の追加" if row["S2理由"] == "低ADX上昇・幅拡大" else "その他追加"
    if old:
        if row["S2理由"] == "高ADX失速待機":
            return "高ADX失速の抑止"
        if row["S1局面"] == "レンジ":
            return "R発動を始動局面で抑止" if row["S2局面"] == "トレンド" else "R発動を非レンジ待機で抑止"
        return "その他抑止"
    return "両規則見送り"


# ----------------------------------------
# 元発動を保った比較と、実際の一建玉参加による差を混同しない。

def main() -> None:
    """全旧発動の同値を確認し、三つの差と利益回収を保存する。

    引数: なし。
    返り値: None。固定core/結果/生caseは変更しない。
    """
    artifacts = json.loads((STUDY / "作業成果物.json").read_text(encoding="utf-8"))
    official = json.loads((STUDY / "結果.json").read_text(encoding="utf-8"))
    old_artifacts = json.loads((OLD_STUDY / "作業成果物.json").read_text(encoding="utf-8"))
    old_official = json.loads((OLD_STUDY / "結果.json").read_text(encoding="utf-8"))
    raw, cases, detailed = read("全複合shadow.jsonl.gz", artifacts), read("入口事例.jsonl.gz", artifacts), read("全運用詳細.jsonl.gz", artifacts)
    old_raw, old_cases = B.read("全複合shadow.jsonl.gz", old_artifacts), B.read("入口事例.jsonl.gz", old_artifacts)
    old_detailed = B.read("全運用詳細.jsonl.gz", old_artifacts)
    canonical, original = {r["発動ID"]: r for r in raw}, {r["発動ID"]: r for r in old_raw}
    if len(canonical) != len(raw) or len(original) != len(old_raw) or canonical.keys() != original.keys():
        raise ValueError("元発動の一意性/全集合が不一致")
    checks = 1
    fields = ("場", "期間", "時間足分", "index", "side", "入口系統", "要求時計秒", "要求原板行", "足終了時計秒", "確認遅延秒",
        "close", "high", "low", "atr", "bb_mean", "bb_sd", "bandwidth", "macd", "macd_signal", "macd_hist", "stoch_raw", "stoch_k", "stoch_d",
        "直前足", "二足前", "ラベル", "理由", "新規時計秒", "新規原板行", "新規価格", "判定時計秒", "判定原板行", "判定気配", "最大順行pt", "最大逆行pt", "所要分")
    for key, row in canonical.items():
        for field in fields:
            checks += 1
            if row[field] != original[key][field]:
                raise ValueError("元発動/指標/先着ラベルが不一致: " + field)
        checks += 1
        if row["旧21戦略判定"] != original[key]["戦略判定"]:
            raise ValueError("旧21canonical採否の不一致")
    event_map, selected = {}, defaultdict(set)
    for row in [*old_cases, *cases]:
        event, base = row["イベントID"], row["QイベントID"]
        if event in event_map and event_map[event]["QイベントID"] != base:
            raise ValueError("旧新caseの元イベントが不一致")
        event_map[event] = {"QイベントID": base}
    for row in cases:
        correct = canonical[row["発動ID"]]["戦略判定"]
        if row["戦略判定"] != correct or row["複合判定"] != correct[row["戦略"]]:
            raise ValueError("全caseの全戦略属性がcanonicalと不一致")
        selected[row["入口ID"], row["期間"]].add(row["発動ID"])
        checks += 2
    groups, changes, preparation, opportunities, participation = defaultdict(list), [], [], [], []
    for row in raw:
        groups[row["時間足分"], row["期間"], transition(row), row["入口系統"], row["side"]].append(row)
    for (size, period, kind, family, side), rows in sorted(groups.items()):
        changes.append({"足分": size, "期間": period, "変化区分": kind, "系統": family, "side": side, **labels(rows)})
    for size in (1, 3, 5):
        for period in PERIODS:
            rows = [r for r in raw if (r["時間足分"], r["期間"]) == (size, period)]
            ready = [r for r in rows if r["共通M22準備"]]
            removed = [r for r in rows if not r["共通M22準備"]]
            preparation.append({"足分": size, "期間": period, "旧M21全発動": labels(rows), "新M22通過": labels(ready), "準備除外": labels(removed)})
            for strategy in POLICIES:
                expected = {r["発動ID"] for r in rows if r["戦略判定"][strategy]["採用"]}
                if expected != selected[f"{size}分_{strategy}", period]:
                    raise ValueError("canonical採否と全入口集合が不一致")
                checks += 1
            for left, right in (("A0", "S1"), ("A0", "S2"), ("S1", "S2")):
                a = {r["発動ID"] for r in ready if r["戦略判定"][left]["採用"]}
                b = {r["発動ID"] for r in ready if r["戦略判定"][right]["採用"]}
                participation.append({"足分": size, "期間": period, "左": left, "右": right,
                    "共通採用": labels([canonical[k] for k in a & b]), "左のみ": labels([canonical[k] for k in a - b]), "右のみ": labels([canonical[k] for k in b - a])})
            for reason in sorted({r["S2理由"] for r in ready}):
                for family in ("T1", "R1"):
                    local = [r for r in ready if r["S2理由"] == reason and r["入口系統"] == family]
                    accepted = [r for r in local if r["戦略判定"]["S2"]["採用"]]
                    rejected = [r for r in local if not r["戦略判定"]["S2"]["採用"]]
                    opportunities.append({"足分": size, "期間": period, "S2理由": reason, "系統": family,
                        "全発動": labels(local), "採用": labels(accepted), "見送り": labels(rejected),
                        "避けた逆行先着": sum(r["ラベル"] == "逆行先着" for r in rejected), "逃した順行先着": sum(r["ラベル"] == "順行先着" for r in rejected)})
    trades, old_trades = defaultdict(list), defaultdict(list)
    for rows, destination in ((detailed, trades), (old_detailed, old_trades)):
        for row in rows:
            destination[row["候補ID"], row["品質"]["期間"]].extend(row["取引"])
    current_values, old_values = {r["候補ID"]: r for r in official["結果"]}, {r["候補ID"]: r for r in old_official["結果"]}
    comparisons, preparation_comparisons, protection, realization = [], [], [], []
    for size in (1, 3, 5):
        for period in PERIODS:
            for left, right in (("A0", "S1"), ("A0", "S2"), ("S1", "S2")):
                a, b = f"{size}分_{left}_X0", f"{size}分_{right}_X0"
                paired = P.compare(trades[a, period], trades[b, period], event_map, True)
                if paired["全運用純額差円"] != current_values[b][period]["運用"]["追加0pt純損益円"] - current_values[a][period]["運用"]["追加0pt純損益円"]:
                    raise ValueError("新三規則の運用差分解が不一致")
                comparisons.append({"足分": size, "期間": period, "左": a, "右": b, "運用比較": paired})
                checks += 1
            for strategy in ("A0", "S1"):
                cid = f"{size}分_{strategy}_X0"
                paired = P.compare(old_trades[cid, period], trades[cid, period], event_map, True)
                if paired["全運用純額差円"] != current_values[cid][period]["運用"]["追加0pt純損益円"] - old_values[cid][period]["運用"]["追加0pt純損益円"]:
                    raise ValueError("準備差による旧新運用差が不一致")
                preparation_comparisons.append({"足分": size, "期間": period, "候補ID": cid, "左試行": 21, "右試行": 22, "運用比較": paired})
                checks += 1
    cases_by_id = {r["イベントID"]: r for r in cases}
    for cid in current_values:
        for period in PERIODS:
            values = trades[cid, period]
            armed = [t for t in values if t["追尾起動"]]
            protection.append({"候補ID": cid, "期間": period, "完結数": len(values), "追尾起動数": len(armed),
                "起動後純赤字数": sum(t["基準純損益円"] < 0 for t in armed),
                "起動後同値未満約定数": sum((1 if t["方向"] == "買い" else -1)*(t["返済価格"]-t["新規価格"]) < 0 for t in armed),
                "最終設定未満約定数": sum(t["最終追尾から実返済方向差pt"] < 0 for t in armed),
                "最終設定からの不足pt計": sum(max(0, -t["最終追尾から実返済方向差pt"]) for t in armed)})
            for family in ("T1", "R1"):
                own = [t for t in values if cases_by_id[t["入口イベントID"]]["入口系統"] == family]
                for t in own:
                    for field in ("新規時計秒", "新規原板行", "新規価格"):
                        if t[field] != cases_by_id[t["入口イベントID"]][field]:
                            raise ValueError("実新規と仮先着の新規が不一致")
                        checks += 1
                wins = [t for t in own if cases_by_id[t["入口イベントID"]]["ラベル"] == "順行先着"]
                realization.append({"候補ID": cid, "期間": period, "系統": family, "実新規対応数": len(own), "対応先着250数": len(wins),
                    "先着250だが基準純赤字数": sum(t["基準純損益円"] < 0 for t in wins),
                    "先着250だが250利確以外数": sum(t["返済理由"] != "利確" for t in wins),
                    "基準純額円": sum(t["基準純損益円"] for t in own), "追加5pt純額円": sum(t["追加滑り5pt純損益円"] for t in own)})
    output = {"確認日": "2026-11-05", "全65場既使用": True, "対応集合全件一致": True, "照合項目数": checks,
        "全旧発動数": len(raw), "新M22発動数": sum(r["共通M22準備"] for r in raw), "準備除外数": sum(not r["共通M22準備"] for r in raw),
        "純入口数": len(cases), "全case全戦略属性一致": True, "旧発動照合フィールド数": len(fields),
        "準備差": preparation, "局面選択差": changes, "局面機会表": opportunities, "発動参加集合": participation,
        "運用対応": comparisons, "M21対M22運用対応": preparation_comparisons, "利益保護": protection, "入口先着と利益回収": realization,
        "コードSHA256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), "結果SHA256": hashlib.sha256((STUDY / "結果.json").read_bytes()).hexdigest(),
        "旧結果SHA256": hashlib.sha256((OLD_STUDY / "結果.json").read_bytes()).hexdigest(),
        "限界": "全旧発動とラベルは同値だが、新Mで参加できない発動もある。旧新試行の全額差をS2分類の効果にしない。局面別先着は各発動へ仮参加した反実仮想で、実運用は一建玉の別集合。全規則/足幅の重複を独立標本に加算しない。額差は観測額で品質注意を含む場合がある。同値設定は実現同値や費用後非赤字の保証ではない。"}
    (STUDY / "対応診断.json").write_text(json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({k: output[k] for k in ("対応集合全件一致", "照合項目数", "全旧発動数", "新M22発動数", "準備除外数", "純入口数")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
