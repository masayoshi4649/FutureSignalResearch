"""94の固定保存口座を損益と利益返しへ分解する。売買・原板再生は行わない。"""

import argparse
from collections import defaultdict
from decimal import Decimal
import hashlib
import json
from pathlib import Path


def sha(path: Path) -> str:
    """
    機能: 保存ファイルの内容指紋を取得する。
    引数: path(Path)は明示された保存入力。
    返り値: strはSHA256。
    """
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def load(path: Path) -> dict:
    """
    機能: 保存JSONを十進数の精度を維持して読み込む。
    引数: path(Path)は保存入力。
    返り値: dictはJSON本文。非有限定数は拒否する。
    """
    def bad(value: str) -> None:
        """
        機能: 非有限の定数をエラーにする。
        引数: value(str)は不正な定数。
        返り値: None。常にValueError。
        """
        raise ValueError(value)
    return json.loads(path.read_text(encoding="utf-8-sig"), parse_float=Decimal, parse_constant=bad)


def serial(value: object) -> int | float:
    """
    機能: 十進数の半円を丸めずJSONへ保存する。
    引数: value(object)はDecimal。
    返り値: int|floatは有限の数値。
    """
    if not isinstance(value, Decimal) or not value.is_finite():
        raise TypeError(type(value).__name__)
    return int(value) if value == value.to_integral_value() else float(value)


def add_position(row: dict, p: dict) -> None:
    """
    機能: 完結玉を正負と初回利益観測の分母へ一度加算する。
    引数: row(dict)は集計先、p(dict)は完結Actual玉。
    返り値: None。残玉があれば拒否する。
    """
    assert p["quantity"] == p["reserved"] == 0
    net = p["realized_net"]
    row["玉数"] += 1
    row["新規枚数"] += p["initial_quantity"]
    row["粗額円"] += p["gross_yen"]
    row["純額円"] += net
    row["黒字玉"] += net > 0
    row["赤字玉"] += net < 0
    row["同額玉"] += net == 0
    row["正額円"] += max(0, net)
    row["負額円"] += min(0, net)
    for flag, label in (("first_unit_positive", "u"), ("first_whole_positive", "W")):
        positive = p["marks"][flag]
        row[label + "正益玉"] += positive is not None
        if positive is not None and net < 0:
            row[label + "正益後最終赤字玉"] += 1
            row[label + "正益後最終赤字額円"] += net
            row[label + "初正益時全予約済赤字玉"] += positive["reserved"] == positive["quantity"]
        if positive is None and net < 0:
            row[label + "正益未観測赤字玉"] += 1
            row[label + "正益未観測赤字額円"] += net
    row["保護起動玉"] += p["protection_active"]


def main() -> None:
    """
    機能: 正式54場の保存会計を分解し、再参加の閾値を選ばず診断だけを保存する。
    引数: --run/--summary/--out(Path)はNative54・独立集計・新規保存先。
    返り値: None。不整合は例外で終了する。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    assert not args.out.exists()
    completion_path = args.run / "完了.json"
    completion = load(completion_path)
    result = load(args.summary)
    assert completion["場数"] == result["場数"] == 54 and result["scope"] == "正式"
    assert result["成功"] is True and result["固定54場金額照合実施"] is True
    before = {str(completion_path): sha(completion_path), str(args.summary): sha(args.summary), str(Path(__file__)): sha(Path(__file__))}
    assert result["完了記録SHA256"] == before[str(completion_path)]
    rows, groups, day_sums = {}, {}, {}
    for name, expected in sorted(completion["結果SHA256"].items()):
        path = args.run / name
        assert path.resolve().is_relative_to(args.run.resolve()) and sha(path) == expected
        assert result["入力SHA256"][name] == expected
        before[str(path)] = expected
        native = load(path)
        for key, book in native["books"].items():
            row = rows.setdefault(key, defaultdict(Decimal))
            day_sums.setdefault(key, defaultdict(Decimal))[native["session"][:10]] += book["totals"]["net_yen"]
            for p in book["positions"]:
                add_position(row, p)
                group = key + "/" + p["source"]["method"] + "/" + p["source"]["kind"]
                add_position(groups.setdefault(group, defaultdict(Decimal)), p)
    for key, row in rows.items():
        expected = result["集計"][key]
        assert row["玉数"] == expected["positions"] and row["新規枚数"] == expected["entry_quantity"]
        assert row["粗額円"] == expected["gross_yen"] and row["純額円"] == expected["net_yen"]
        assert row["u正益玉"] == expected["unit_positive_positions"] and row["W正益玉"] == expected["whole_positive_positions"]
        row["PF"] = row["正額円"] / -row["負額円"] if row["負額円"] else None
        row["黒字開始日数"] = sum(v > 0 for v in day_sums[key].values())
        row["赤字開始日数"] = sum(v < 0 for v in day_sums[key].values())
        row["開始日数"] = len(day_sums[key])
    for name, expected in before.items():
        assert sha(Path(name)) == expected
    proof = {"試行": 94, "成功": True, "状態": "保存54場の事後診断・新売買と閾値選定なし",
             "集計": rows, "元手法と元段階別": groups, "開始日別純額": day_sums,
             "評価方針": "各手法で成立した取引の実現収支と保有中の保護を評価する。未参加/決済後の仮想利益・機会損失は採点/最適化しない。",
             "入力SHA256": before, "入力前後不変": True,
             "限界": "PFは実玉純額の正額/負額。開始日はDay/Night合算。u未観測は欠測を含み得る。正益後最終赤字額は該当玉の最終純額合計。初正益時の予約は当保存phaseの自己保護要求前であり、放置や赤字化の原因と単独断定しない。全原板MTM監査は別証拠。"}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(proof, ensure_ascii=False, indent=2, allow_nan=False, default=serial) + "\n", encoding="utf-8")
    print(json.dumps({"成功": True, "口座": len(rows), "out": str(args.out)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
