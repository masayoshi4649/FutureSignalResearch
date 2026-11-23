"""VWAP条件の付け外しを同じ価格発動へ対応させ、運用参加集合の差を分ける。"""

from collections import defaultdict
import gzip
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT / "study/00018_VWAPの位置と傾きで順行反転を比較"
WORK = ROOT / "work/VWAP入口/00018"
PERIODS = ("学習", "条件選択", "後続検査")
PAIRS = (("N_A", "N_B", "native位置"), ("N_B", "N_C", "native傾き"),
         ("D_A", "D_B", "native位置"), ("D_A", "D_D", "差分位置"),
         ("N_A", "D_A", "D共通準備"), ("N_B", "D_B", "D共通準備"),
         ("D_B", "D_D", "起算置換"))


def load(name: str, artifacts: dict) -> list[dict]:
    """正式指紋を検査し、保存明細だけを復元する。

    引数: name(str)は作業gzip、artifacts(dict)は作業成果物台帳。
    返り値: list[dict] は全行。市場入力や主エンジンを再生しない。
    """
    path = WORK / name
    expected = next(r["展開内容SHA256"] for r in artifacts["ファイル"] if r["パス"].endswith(name))
    digest, rows = hashlib.sha256(), []
    with gzip.open(path, "rb") as stream:
        for raw in stream:
            digest.update(raw)
            if raw.strip():
                rows.append(json.loads(raw))
    if digest.hexdigest() != expected:
        raise ValueError("作業明細の固定指紋が不一致")
    return rows


def selected(row: dict, family: str, rule: str) -> bool:
    """基準入口に追加する条件を保存値から別計算する。

    引数: row(dict)は価格発動を共有する入口、family(str)はT1/R2、rule(str)は比較条件。
    返り値: bool は追加条件の成立。起算置換はこの関数で包含を要求しない。
    """
    side = row["side"]
    if rule == "D共通準備":
        return bool(row["D共通準備"])
    if rule == "native傾き":
        return side * (row["配信VWAP"] - row["配信3足前VWAP"]) > 0
    line = row["配信VWAP"] if rule == "native位置" else row["当場差分VWAP"]
    return side * (row["close"] - line) > 0 if family == "T1" else side * (line - row["close"]) > 0


# ----------------------------------------
# 同じ実新規の出口と、除外/追加された参加集合を分離する。

def compare(left: list[dict], right: list[dict], events: dict[str, str]) -> dict:
    """実新規キーを元価格イベントへ揃えて純額差を分解する。

    引数: left/right(list[dict])は比較する完結取引、events(dict[str,str])は元価格ID対応。
    返り値: dict は共通新規の出口差と、左右だけの参加純額。
    """
    def key(trade: dict) -> tuple:
        """要求条件名を元価格イベントへ戻して実新規を識別する。

        引数: trade(dict)は完結取引。
        返り値: tuple は元価格ID・新規時計/原行/価格。返済は含めない。
        """
        return (events[trade["入口イベントID"]], trade["新規時計秒"], trade["新規原板行"], trade["新規価格"])

    a, b = {key(t): t for t in left}, {key(t): t for t in right}
    if len(a) != len(left) or len(b) != len(right):
        raise ValueError("同じ実新規キーが重複")
    common, only_a, only_b = a.keys() & b.keys(), a.keys() - b.keys(), b.keys() - a.keys()
    for item in common:
        for field in ("返済時計秒", "返済原板行", "返済価格", "返済理由", "基準純損益円"):
            if a[item][field] != b[item][field]:
                raise ValueError("固定X0の同じ実新規で出口が不一致: " + field)
    delta = sum(b[k]["基準純損益円"] - a[k]["基準純損益円"] for k in common)
    removed = sum(a[k]["基準純損益円"] for k in only_a)
    added = sum(b[k]["基準純損益円"] for k in only_b)
    full = sum(t["基準純損益円"] for t in right) - sum(t["基準純損益円"] for t in left)
    if full != delta - removed + added:
        raise ValueError("全運用差と集合差分解が不一致")
    return {"共通実新規数": len(common), "左側のみ実新規数": len(only_a), "右側のみ実新規数": len(only_b),
            "共通実新規純額差円": delta, "左側のみ純額円": removed, "右側のみ純額円": added,
            "全運用純額差円": full}


def main() -> None:
    """七対照×三尺度×二役割×三期間の対応と運用差を保存する。

    引数: なし。
    返り値: None。全量再生せず、保存入力と会計の対応を検査する。
    """
    artifacts = json.loads((STUDY / "作業成果物.json").read_text(encoding="utf-8"))
    report = json.loads((STUDY / "結果.json").read_text(encoding="utf-8"))
    cases = load("入口事例.jsonl.gz", artifacts)
    detailed = load("全運用詳細.jsonl.gz", artifacts)
    groups, trades, events = defaultdict(dict), defaultdict(list), {}
    for row in cases:
        index = row["時間足分"], row["入口系統"], row["期間"], row["補助"]
        key = row["場"], row["index"], row["side"]
        if key in groups[index]:
            raise ValueError("保存入口の重複")
        groups[index][key] = row
        if row["イベントID"] in events and events[row["イベントID"]] != row["価格イベントID"]:
            raise ValueError("元価格イベント対応が不一致")
        events[row["イベントID"]] = row["価格イベントID"]
    for row in detailed:
        trades[row["候補ID"], row["品質"]["期間"]].extend(row["取引"])
    official = {r["候補ID"]: r for r in report["結果"]}
    fields = ("要求時計秒", "要求原板行", "ラベル", "新規時計秒", "新規原板行", "新規価格", "判定時計秒", "判定原板行",
              "価格イベントID", "配信VWAP", "当場差分VWAP", "配信3足前VWAP", "差分3足前VWAP", "補助epoch", "identity",
              "N共通準備", "D共通準備", "補助参照", "close", "atr", "rsi", "上位方向")
    output, checks = [], 0
    for size in (1, 3, 5):
        for family in ("T1", "R2"):
            for period in PERIODS:
                for left, right, rule in PAIRS:
                    a, b = groups[size, family, period, left], groups[size, family, period, right]
                    if rule != "起算置換":
                        expected = {key for key, row in a.items() if selected(row, family, rule)}
                        if expected != b.keys():
                            raise ValueError("条件追加の部分集合が不一致: " + str((size, family, period, left, right)))
                    for key in a.keys() & b.keys():
                        for field in fields:
                            checks += 1
                            if a[key][field] != b[key][field]:
                                raise ValueError("同じ価格発動/仮約定/補助値が不一致: " + field)
                    left_id, right_id = f"{size}分_{family}_{left}_X0", f"{size}分_{family}_{right}_X0"
                    amounts = compare(trades[left_id, period], trades[right_id, period], events)
                    if amounts["全運用純額差円"] != official[right_id][period]["運用"]["追加0pt純損益円"] - official[left_id][period]["運用"]["追加0pt純損益円"]:
                        raise ValueError("正式純損益と集合診断が不一致")
                    output.append({"足分": size, "系統": family, "期間": period, "左": left, "右": right, "比較条件": rule,
                        "左入口数": len(a), "右入口数": len(b), "共通入口数": len(a.keys() & b.keys()),
                        "左のみ入口数": len(a.keys() - b.keys()), "右のみ入口数": len(b.keys() - a.keys()),
                        "部分集合検査": rule != "起算置換", "運用比較": amounts})
    result = {"確認日": "2026-11-04", "全65場既使用": True, "対応集合全件一致": True,
              "同じ仮約定の照合項目数": checks, "結果": output,
              "コードSHA256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "結果SHA256": hashlib.sha256((STUDY / "結果.json").read_bytes()).hexdigest(),
              "限界": "保存入口と運用集合の診断。入力全体からの発動漏れ検査は別の状態独立確認。全65場は既使用で、共通仮約定を独立標本へ重複加算しない。固定X0の共通実新規の出口差と参加集合差を分ける。N/Dの全運用差は起算単独の因果効果ではない。"}
    (STUDY / "補助対応診断.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"対応集合全件一致": True, "照合項目数": checks, "対照期間群数": len(output)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
