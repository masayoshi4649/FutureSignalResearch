"""新一場の入口ラベルと実返済、三案の共通取引を対応させる。"""

from collections import Counter
from datetime import datetime
import gzip
import hashlib
import json
from pathlib import Path
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT / "study/00027_試行00026の新Night固定後確認"
WORK = ROOT / "work/固定後確認/00027"


def read(path: Path) -> dict | list:
    """保存正本を読み、圧縮明細は行ごとの配列にする。

    引数: path(Path)はJSON又はJSONL.gz。
    返り値: dict | listは復号した正本。売買や先着を再実行しない。
    """
    if path.suffix == ".gz":
        with gzip.open(path, "rt", encoding="utf-8") as stream:
            return [json.loads(line) for line in stream]
    return json.loads(path.read_text(encoding="utf-8-sig"))


def sha(path: Path) -> str:
    """診断が参照した保存版の内容指紋を返す。

    引数: path(Path)は実在ファイル。
    返り値: strはSHA256の十六進文字列。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def stamp(seconds: float) -> str:
    """価格時計を日本時間の表示へ変換する。

    引数: seconds(float)はUNIX秒。
    返り値: strはJSTのISO日時。
    """
    return datetime.fromtimestamp(seconds, ZoneInfo("Asia/Tokyo")).isoformat()


def identity(trade: dict) -> tuple:
    """候補名に依存しない同じ実新規の識別値を作る。

    引数: trade(dict)は完結した一取引。
    返り値: tupleは役割・方向・新規時計・原行・価格。
    """
    return tuple(trade[key] for key in (
        "入口役割", "方向", "新規時計秒", "新規原板行", "新規価格"))


def run() -> dict:
    """全五実取引を入口の先着ラベルへ対応し、確認待ちを診断する。

    引数: なし。
    返り値: dictは照合結果・対応表・指紋。条件と正本は変更しない。
    """
    cases = read(WORK / "入口事例.jsonl.gz")
    details = read(WORK / "全運用詳細.jsonl.gz")
    watch = read(WORK / "反転監視.jsonl.gz")
    shadow = read(WORK / "全複合shadow.jsonl.gz")
    result = read(STUDY / "結果.json")
    comparisons, failures = 0, []

    def check(name: str, actual: object, expected: object) -> None:
        """値の一致を数え、相違があれば診断の失敗に残す。

        引数: name(str)は名称、actual(object)は実値、expected(object)は期待値。
        返り値: None。失敗を消さず、最後に成功扱いを拒否する。
        """
        nonlocal comparisons
        comparisons += 1
        if actual != expected:
            failures.append({"項目": name, "実値": actual, "期待値": expected})

    check("新規場数", result["新規確認場数"], 1)
    check("旧損益非合算", result["旧場損益合算"], False)
    check("固定全三案", [r["候補ID"] for r in details], result["確認候補"])
    case_map = {c["イベントID"]: c for c in cases}
    check("入口ID一意", len(case_map), len(cases))
    corresponding, summary = [], []
    for detail in details:
        cid = detail["候補ID"]
        own = []
        for trade in detail["取引"]:
            case = case_map[trade["入口イベントID"]]
            for ckey, tkey in (("新規時計秒", "新規時計秒"),
                              ("新規原板行", "新規原板行"), ("新規価格", "新規価格")):
                check(cid + tkey, case[ckey], trade[tkey])
            exit_key = (trade["返済時計秒"], trade["返済原板行"])
            label_key = (case["判定時計秒"], case["判定原板行"])
            row = {"候補ID": cid, "入口イベントID": trade["入口イベントID"],
                   "役割": trade["入口役割"], "方向": trade["方向"],
                   "入口JST": trade["新規時計JST"], "返済JST": trade["返済時計JST"],
                   "返済理由": trade["返済理由"], "入口ラベル": case["ラベル"],
                   "先着判定JST": stamp(case["判定時計秒"]),
                   "先着判定前に返済": exit_key < label_key,
                   "基準純損益円": trade["基準純損益円"],
                   "追加5pt純損益円": trade["追加滑り5pt純損益円"],
                   "実保有最大順行pt": trade["観測最大順行pt"],
                   "追尾起動": trade["追尾起動"], "最終追尾価格": trade["最終追尾価格"]}
            own.append(row)
            corresponding.append(row)
        operation = next(x for x in result["結果"] if x["候補ID"] == cid)["新規確認"]["運用"]
        check(cid + "取引数", len(own), operation["完結取引数"])
        check(cid + "基準合計", sum(r["基準純損益円"] for r in own), operation["追加0pt純損益円"])
        check(cid + "追加5合計", sum(r["追加5pt純損益円"] for r in own), operation["追加5pt純損益円"])
        summary.append({"候補ID": cid, "実取引数": len(own),
                        "順行先着取引数": sum(r["入口ラベル"] == "順行先着" for r in own),
                        "逆行先着なのに実黒字数": sum(r["入口ラベル"] == "逆行先着" and r["基準純損益円"] > 0 for r in own),
                        "実保有250到達取引数": sum(r["実保有最大順行pt"] >= 250 for r in own),
                        "追尾起動数": sum(r["追尾起動"] for r in own),
                        "追尾起動後基準赤字数": sum(r["追尾起動"] and r["基準純損益円"] < 0 for r in own)})

    # ----------------------------------------
    common = []
    for left, right in (("N0", "N1"), ("N0", "N2"), ("N1", "N2")):
        left_rows = next(x["取引"] for x in details if x["候補ID"] == f"3分_{left}_X0")
        right_rows = next(x["取引"] for x in details if x["候補ID"] == f"3分_{right}_X0")
        lmap, rmap = {identity(x): x for x in left_rows}, {identity(x): x for x in right_rows}
        keys = lmap.keys() & rmap.keys()
        for key in keys:
            for field in ("返済時計秒", "返済原板行", "返済価格", "返済理由", "基準純損益円"):
                check(left + right + field, lmap[key][field], rmap[key][field])
        common.append({"左": left, "右": right, "共通実新規数": len(keys),
                       "左のみ実新規数": len(lmap.keys() - rmap.keys()),
                       "右のみ実新規数": len(rmap.keys() - lmap.keys()),
                       "共通返済純損益差円": sum(rmap[k]["基準純損益円"] - lmap[k]["基準純損益円"] for k in keys)})
    endings = [x for x in watch if x["種別"] == "反転終了診断"]
    later = [x for x in shadow if x["入口系統"] == "R方向確認"]
    check("後続h生成数", len(later), sum(x["確認種別"] == "後続SAR" for x in endings))
    proof = {"全件一致": not failures, "照合項目数": comparisons, "不一致数": len(failures),
             "不一致": failures, "新規場数": 1, "旧場損益合算": False,
             "候補別": summary, "入口実返済対応": corresponding, "案間対応": common,
             "反転監視終了理由": dict(Counter(x["終了理由"] for x in endings)),
             "後続h生成数": len(later),
             "限界": "新一場の対応診断。入口ラベルは返済後を含む反実仮想であり実収益ではない。少数の黒字や不採用を一般的な有効性・原因としない。",
             "ファイルSHA256": {p.relative_to(ROOT).as_posix(): sha(p) for p in (
                 Path(__file__), STUDY / "結果.json", STUDY / "固定.json",
                 STUDY / "独立監査.json", WORK / "入口事例.jsonl.gz",
                 WORK / "全運用詳細.jsonl.gz", WORK / "反転監視.jsonl.gz", WORK / "全複合shadow.jsonl.gz")}}
    (WORK / "対応診断.json").write_text(json.dumps(proof, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if failures:
        raise RuntimeError("新一場の対応診断に相違があります")
    return proof


if __name__ == "__main__":
    outcome = run()
    print(json.dumps({key: outcome[key] for key in ("全件一致", "照合項目数", "不一致数")}, ensure_ascii=False))
