"""UTF-8 BOM付き損益CSVを再読し、固定済み正本の全行と独立照合する。"""

import csv
import hashlib
import json
import math
from pathlib import Path
import sys


def sha(path: Path) -> str:
    """
    機能: ファイルの指紋を計算する。
    引数: path (Path)は入力または出力。
    返り値: strはSHA256。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def equal(actual: str | float, expected: float, label: str) -> None:
    """
    機能: 円・数量・百分率を相対許容なしで照合する。
    引数: actual (str|float)、expected (float)、label (str)はCSV値・正本値・対象名。
    返り値: None。不一致時は例外。
    """
    assert math.isclose(float(actual), expected, rel_tol=0, abs_tol=1e-6), label


def read(path: Path) -> list[dict]:
    """
    機能: CSVの文字コードを確認して全行を再読する。
    引数: path (Path)は生成済みCSV。
    返り値: list[dict]は列名付き行。
    """
    assert path.read_bytes().startswith(b"\xef\xbb\xbf")
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def main() -> None:
    """
    機能: 全明細・集計を正本へ結び、再読検査を確認JSONへ追加する。
    引数: CLI (str[])は正本JSON・期待SHA256・CSVフォルダの順。
    返り値: None。金融再計算と正本変更は行わない。
    """
    source, expected_sha, destination = sys.argv[1:]
    source, destination = Path(source), Path(destination)
    assert sha(source) == expected_sha
    data = json.loads(source.read_text(encoding="utf-8-sig"))
    detail = read(destination / "全セッション.csv")
    totals = read(destination / "候補別集計.csv")
    assert len(detail) == data["会計数"]
    assert len(totals) == len(data["主key"])
    by = {(r["条件ID"], r["開始日"] + "_" + {"デイ": "Day", "ナイト": "Night"}[r["セッション"]]): r for r in detail}
    assert len(by) == len(detail)
    total_by = {r["条件ID"]: r for r in totals}
    assert len(total_by) == len(totals)
    fields = {"新規件数": "positions", "新規枚数": "entry_quantity", "粗損益円": "gross_yen", "手数料円": "fee_yen", "追加滑り円": "slip_yen", "純損益円": "net_yen"}
    running, cases = {}, 0
    for row in sorted(data["場別"], key=lambda r: (data["主key"].index(r["key"]), r["session"])):
        got = by[row["key"], row["session"]]
        assert int(got["試行"]) == data["試行"]
        for column, name in fields.items():
            equal(got[column], row[name], column)
            cases += 1
        running[row["key"]] = running.get(row["key"], 0) + row["net_yen"]
        equal(got["累計収支円"], running[row["key"]], "累計")
        for column, name in (("参加枠", "active"), ("判断枠", "denom")):
            equal(got[column], row["活動主表"][name], column)
        equal(got["参加率パーセント"], row["活動主表"]["active"] / row["活動主表"]["denom"] * 100, "百分率")
    for key in data["主key"]:
        got, row = total_by[key], data["集計"][key]
        assert int(got["セッション数"]) == data["場数"]
        for column, name in fields.items():
            equal(got[column], row[name], column)
        equal(got["保存点連結時価DD円"], row["保存点連結時価DD"], "DD")
        equal(got["参加枠"], row["活動主表"]["active"], "参加合計")
        equal(got["判断枠"], row["活動主表"]["denom"], "分母合計")
        equal(got["参加率パーセント"], row["活動主表"]["active"] / row["活動主表"]["denom"] * 100, "合計百分率")
    check_path = destination / "CSVの確認.json"
    check = json.loads(check_path.read_text(encoding="utf-8"))
    assert check["入力SHA256"] == sha(source) == expected_sha
    for name, value in check["出力"].items():
        assert sha(destination / name) == value["sha256"]
    check["CSV独立再読"] = {"成功": True, "全行": len(detail), "集計行": len(totals), "数値対照件数": cases, "累計対照": len(detail), "参加率対照": len(detail), "ゼロ取引行保持": sum(r["positions"] == 0 for r in data["場別"]), "再読コードSHA256": sha(Path(__file__))}
    check_path.write_text(json.dumps(check, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(check["CSV独立再読"], ensure_ascii=False))


if __name__ == "__main__":
    main()
