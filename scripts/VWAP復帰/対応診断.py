"""固定19の出口差・入口選別・通常線までの距離を、対応する取引で診断する。"""

from collections import defaultdict
import gzip
import hashlib
import json
from pathlib import Path
import statistics


ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT / "study/00019_VWAP復帰の入口と通常出口"
WORK = ROOT / "work/VWAP復帰/00019"
PERIODS = ("学習", "条件選択", "後続検査")


def sha(path: Path) -> str:
    """ファイルの指紋を計算する。

    引数: path(Path)は対象。
    返り値: strはSHA256。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(name: str, artifacts: dict) -> list[dict]:
    """作業明細の正式な展開指紋を確認して読む。

    引数: name(str)はgzip名、artifacts(dict)は正式台帳。
    返り値: list[dict]は全保存行。
    """
    expected = next(r["展開内容SHA256"] for r in artifacts["ファイル"] if r["パス"].endswith(name))
    with gzip.open(WORK / name, "rb") as stream:
        raw = stream.read()
    if hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError("固定作業明細の指紋が不一致")
    return [json.loads(line) for line in raw.splitlines() if line.strip()]


def compare(left: list[dict], right: list[dict], events: dict, identical: bool) -> dict:
    """同じ実新規の出口差と、参加集合の差を分解する。

    引数: left/right(list[dict])は取引、events(dict)は元Q対応、identical(bool)は同一出口照合の要否。
    返り値: dictは純額差と左の保有区間を基準にした利益消失診断。
    """
    def key(trade: dict) -> tuple:
        """補助名を除いたQと実新規で対応キーを作る。

        引数: trade(dict)は完結取引。
        返り値: tupleはQ・新規時計・原行・価格。
        """
        return (events[trade["入口イベントID"]]["QイベントID"], trade["新規時計秒"], trade["新規原板行"], trade["新規価格"])

    a, b = {key(t): t for t in left}, {key(t): t for t in right}
    if len(a) != len(left) or len(b) != len(right):
        raise ValueError("実新規キーの重複")
    common, only_a, only_b = sorted(a.keys() & b.keys()), a.keys() - b.keys(), b.keys() - a.keys()
    if identical:
        for k in common:
            for field in ("返済要求時計秒", "返済要求原板行", "返済時計秒", "返済原板行", "返済価格", "返済理由", "基準純損益円"):
                if a[k][field] != b[k][field]:
                    raise ValueError("同じ実新規・同じ出口で挙動が不一致: " + field)
    delta = sum(b[k]["基準純損益円"] - a[k]["基準純損益円"] for k in common)
    removed = sum(a[k]["基準純損益円"] for k in only_a)
    added = sum(b[k]["基準純損益円"] for k in only_b)
    full = sum(t["基準純損益円"] for t in right) - sum(t["基準純損益円"] for t in left)
    if full != delta - removed + added:
        raise ValueError("純額差の参加集合分解が不一致")
    recovery = []
    for threshold in (20, 50, 100):
        keys = [k for k in common if a[k]["観測最大順行pt"] >= threshold]
        recovery.append({"左MFE下限pt": threshold, "共通実新規数": len(keys),
            "左純赤字数": sum(a[k]["基準純損益円"] < 0 for k in keys),
            "右純赤字数": sum(b[k]["基準純損益円"] < 0 for k in keys),
            "左赤字から右黒字数": sum(a[k]["基準純損益円"] < 0 < b[k]["基準純損益円"] for k in keys),
            "共通純額差円": sum(b[k]["基準純損益円"] - a[k]["基準純損益円"] for k in keys)})
    return {"共通実新規数": len(common), "左側のみ実新規数": len(only_a), "右側のみ実新規数": len(only_b),
        "共通実新規純額差円": delta, "左側のみ純額円": removed, "右側のみ純額円": added, "全運用純額差円": full,
        "左赤字から右黒字数": sum(a[k]["基準純損益円"] < 0 < b[k]["基準純損益円"] for k in common),
        "左黒字から右赤字数": sum(b[k]["基準純損益円"] < 0 < a[k]["基準純損益円"] for k in common),
        "左保有区間を基準とした利益消失": recovery}


# ----------------------------------------
# 距離は選別に使わず、同じイベントと実新規に付随する診断へ限定する。

def main() -> None:
    """全36運用の対応と距離を小型JSONへ保存する。

    引数: なし。
    返り値: None。固定条件・結果・明細は変更しない。
    """
    report = json.loads((STUDY / "結果.json").read_text(encoding="utf-8"))
    artifacts = json.loads((STUDY / "作業成果物.json").read_text(encoding="utf-8"))
    cases, details = load("入口事例.jsonl.gz", artifacts), load("全運用詳細.jsonl.gz", artifacts)
    events, groups, trades = {}, defaultdict(dict), defaultdict(list)
    for row in cases:
        if row["イベントID"] in events:
            raise ValueError("入口イベント重複")
        events[row["イベントID"]] = row
        index, key = (row["時間足分"], row["入口系統"], row["補助"], row["期間"]), row["QイベントID"]
        if key in groups[index]:
            raise ValueError("補助別Q重複")
        groups[index][key] = row
    for row in details:
        trades[row["候補ID"], row["品質"]["期間"]].extend(row["取引"])
    official = {r["候補ID"]: r for r in report["結果"]}
    output, distances, checks = [], [], 0
    fields = ("QイベントID", "要求時計秒", "要求原板行", "ラベル", "新規価格", "新規時計秒", "新規原板行", "判定時計秒", "判定原板行", "配信VWAP", "atr", "close", "side", "上位方向")
    for size in (1, 3, 5):
        for family in ("Q1", "Q2"):
            for period in PERIODS:
                a, b = groups[size, family, "なし", period], groups[size, family, "15分方向一致", period]
                if {k for k, r in a.items() if r["上位方向"] == r["side"]} != b.keys():
                    raise ValueError("上位方向の部分集合が不一致")
                for k in b:
                    for field in fields:
                        checks += 1
                        if a[k][field] != b[k][field]:
                            raise ValueError("同じQの仮約定/指標が不一致: " + field)
                pairs = [(f"{size}分_{family}_{extra}_{l}", f"{size}分_{family}_{extra}_{r}", "出口", False)
                         for extra in ("なし", "15分方向一致") for l, r in (("X0", "X1"), ("X0", "X2"), ("X1", "X2"))]
                pairs += [(f"{size}分_{family}_なし_{p}", f"{size}分_{family}_15分方向一致_{p}", "15分方向選別", True) for p in ("X0", "X1", "X2")]
                for left, right, kind, identical in pairs:
                    comparison = compare(trades[left, period], trades[right, period], events, identical)
                    expected = official[right][period]["運用"]["追加0pt純損益円"] - official[left][period]["運用"]["追加0pt純損益円"]
                    checks += 1
                    if comparison["全運用純額差円"] != expected:
                        raise ValueError("正式純額と対応差の不一致")
                    output.append({"足分": size, "系統": family, "期間": period, "比較": kind, "左": left, "右": right, "運用比較": comparison})
                for extra in ("なし", "15分方向一致"):
                    for policy in ("X0", "X1", "X2"):
                        cid = f"{size}分_{family}_{extra}_{policy}"
                        values = [(1 if t["方向"] == "買い" else -1) * (events[t["入口イベントID"]]["配信VWAP"] - t["新規価格"]) for t in trades[cid, period]]
                        distances.append({"候補ID": cid, "期間": period, "件数": len(values),
                            "実新規から初期通常線方向距離pt_最小": min(values, default=None),
                            "実新規から初期通常線方向距離pt_中央値": statistics.median(values) if values else None,
                            "実新規から初期通常線方向距離pt_最大": max(values, default=None),
                            "非正距離数": sum(v <= 0 for v in values),
                            "12.2pt以下距離数": sum(v <= 12.2 for v in values)})
    result = {"確認日": "2026-11-04", "対応集合全件一致": True, "照合項目数": checks, "対照期間群数": len(output),
        "結果": output, "通常線距離": distances, "コードSHA256": sha(Path(__file__)), "結果SHA256": sha(STUDY / "結果.json"),
        "限界": "全65場既使用。保存済み同Q・同実新規の事後診断であり新しい選別ではない。MFE閾値は比較左の保有区間で固定し、短い右保有区間のMFEで母集団を作り直さない。Q1の通常線は損切り側になり得るため符号付き距離を利幅と呼ばない。12.2ptは倍率10/往復22円と片道追加5ptの算術目安で、実約定や収益を保証しない。"}
    (STUDY / "対応診断.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("対応集合全件一致", "照合項目数", "対照期間群数")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
