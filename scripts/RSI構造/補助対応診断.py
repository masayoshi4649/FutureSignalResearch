"""00015のネック位置の追加確認による入口の部分集合と、一建玉の参加集合差を診断する。"""

from collections import defaultdict
import gzip
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT/"study/00015_RSIの山谷と価格構造"
WORK = ROOT/"work/RSI構造/00015"
PERIODS = ("学習", "条件選択", "後続検査")


def load_detail(name: str, artifacts: dict) -> list[dict]:
    """展開内容SHAを照合してGit外の固定詳細を読む。

    引数: name (str) はgzip名、artifacts (dict) は正式な作業成果物指紋。
    返り値: list[dict] は元詳細。指紋不一致は例外。
    """
    path = WORK/name
    expected = next(r["展開内容SHA256"] for r in artifacts["ファイル"] if r["パス"].endswith(name))
    with gzip.open(path, "rb") as stream:
        content = stream.read()
    if hashlib.sha256(content).hexdigest() != expected:
        raise ValueError("固定詳細の展開SHAと異なります")
    return [json.loads(line) for line in content.splitlines()]


def trade_key(trade: dict) -> tuple:
    """補助名だけを正規化し、同じ実新規を識別する。

    引数: trade (dict) は完結取引。
    返り値: tuple は入口イベント・新規時計・原行・価格。返済はキーに含めない。
    """
    return (trade["入口イベントID"].replace("_ネック位置確認_", "_なし_"),
            trade["新規時計秒"], trade["新規原板行"], trade["新規価格"])


def compare(base: list[dict], extra: list[dict]) -> dict:
    """同じ実新規の出口差と、抑止・追加参加を分ける。

    引数: base/extra (list[dict]) は補助なし/ネック条件の完結取引。
    返り値: dict は基準費用での会計差。部分集合の入口でも実新規は単純部分集合にならない。
    """
    a, b = {trade_key(t): t for t in base}, {trade_key(t): t for t in extra}
    if len(a) != len(base) or len(b) != len(extra):
        raise ValueError("実新規キーの重複")
    common, only_a, only_b = a.keys() & b.keys(), a.keys()-b.keys(), b.keys()-a.keys()
    delta = sum(b[k]["基準純損益円"]-a[k]["基準純損益円"] for k in common)
    removed = sum(a[k]["基準純損益円"] for k in only_a)
    added = sum(b[k]["基準純損益円"] for k in only_b)
    full = sum(t["基準純損益円"] for t in extra)-sum(t["基準純損益円"] for t in base)
    if full != delta-removed+added:
        raise ValueError("参加集合差の分解が不一致")
    return {"共通実新規数": len(common), "なし側のみ実新規数": len(only_a), "ネック条件のみ実新規数": len(only_b),
            "共通実新規純額差円": delta, "なし側のみ純額円": removed, "ネック条件のみ純額円": added,
            "全運用純額差円": full}


def main() -> None:
    """全12入口の補助対応と18運用群の差を保存する。

    引数: なし。
    返り値: None。条件・結果・固定コードを変更しない。
    """
    artifacts = json.loads((STUDY/"作業成果物.json").read_text(encoding="utf-8"))
    report = json.loads((STUDY/"結果.json").read_text(encoding="utf-8"))
    cases = load_detail("入口事例.jsonl.gz", artifacts)
    details = load_detail("全運用詳細.jsonl.gz", artifacts)
    groups, trades, comparisons = defaultdict(dict), defaultdict(list), []
    for row in cases:
        group = row["時間足分"], row["入口系統"], row["期間"], row["補助"]
        key = row["場"], row["index"], row["side"]
        if key in groups[group]:
            raise ValueError("保存入口キー重複")
        groups[group][key] = row
    for row in details:
        trades[row["候補ID"], row["品質"]["期間"]].extend(row["取引"])
    checks = 0
    compare_fields = ("要求時計秒", "要求原板行", "ラベル", "新規時計秒", "新規原板行", "新規価格", "判定時計秒", "判定原板行", "現極値", "前極値", "極値間隔本数", "極値間高値", "極値間安値", "ネック価格", "ネック条件成立", "rsi", "atr")
    values = {r["候補ID"]: r for r in report["結果"]}
    for size in (1, 3, 5):
        for family in ("反転乖離", "押し戻り継続"):
            for period in PERIODS:
                a, b = groups[size, family, period, "なし"], groups[size, family, period, "ネック位置確認"]
                expected = {k for k, r in a.items() if r["ネック条件成立"]}
                if expected != b.keys():
                    raise ValueError("ネック条件の入口集合が補助なしの当時ネック条件部分と異なります")
                for key in b:
                    for field in compare_fields:
                        checks += 1
                        if a[key][field] != b[key][field]:
                            raise ValueError("同じ仮約定・極値・ネック参照の内容が不一致")
                base_id, extra_id = f"{size}分_{family}_なし_X0", f"{size}分_{family}_ネック位置確認_X0"
                paired = compare(trades[base_id, period], trades[extra_id, period])
                if paired["全運用純額差円"] != values[extra_id][period]["運用"]["追加0pt純損益円"]-values[base_id][period]["運用"]["追加0pt純損益円"]:
                    raise ValueError("正式結果の全純額差と不一致")
                comparisons.append({"足分": size, "系統": family, "期間": period,
                    "補助なし入口数": len(a), "ネック条件入口数": len(b), "ネック位置不成立で除く入口数": len(a)-len(b),
                    "同じ仮約定の全項目一致": True, "運用比較": paired})
    quality = json.loads((STUDY/"入口品質.json").read_text(encoding="utf-8"))
    counts = defaultdict(lambda: defaultdict(int))
    for row in quality:
        for name, value in row.items():
            if name not in ("場", "時間足分", "系統別発動数") and isinstance(value, int):
                counts[str(row["時間足分"])][name] += value
    output = {"確認日": "2026-11-04", "全65場既使用": True, "対応集合全件一致": True,
              "同じ仮約定の照合項目数": checks, "結果": comparisons, "全65場状態件数": dict(counts),
              "結果SHA256": hashlib.sha256((STUDY/"結果.json").read_bytes()).hexdigest(),
              "コードSHA256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "限界": "保存入口の対応診断。全原板からの入口漏れ監査や新しい未見検証ではない。共通仮約定を重複した独立標本としない。品質空白を解消せず、全運用差を各取引の出口差としない。"}
    (STUDY/"補助対応診断.json").write_text(json.dumps(output, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(json.dumps({"対応集合全件一致": True, "同じ仮約定の照合項目数": checks, "期間群数": len(comparisons)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
