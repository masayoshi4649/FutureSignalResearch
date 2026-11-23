"""既存00008台帳の数量監査を、現在のNK225全65場へ再集計する。"""

from collections import Counter
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
INPUT = ROOT/"study/00008_外部研究を共通尺度へ移して探索/入力台帳.json"
EXPECTED = "800fc5b6b0749a1df8ccf9d28500649a5a8b5225dbfd33473c7c6d25de746fc8"
FIELDS = ("price_bars", "baseline_complete_bars", "baseline_incomplete_bars", "rvol_previous_twenty_available_bars")


def summarize(entries: list[dict]) -> dict:
    """保存済みの数量監査件数を合計する。

    引数: entries (list[dict]) は固定台帳の対象場。
    返り値: dict は場数・五分足件数・時計等の件数。原板の独立再監査ではない。
    """
    counts, bars = Counter(), Counter()
    for entry in entries:
        audit = entry["volume_audit"]
        counts.update(audit["counts"])
        bars.update({key: audit[key] for key in FIELDS})
    return {"場数": len(entries), "足件数": dict(bars), "時計等件数": dict(counts)}


def main() -> None:
    """台帳の固定版を検査し、追加集計と読み方を保存する。

    引数: なし。
    返り値: None。売買条件・原板・元台帳を変更しない。
    """
    digest = hashlib.sha256(INPUT.read_bytes()).hexdigest()
    if digest != EXPECTED:
        raise ValueError("集計対象の固定00008台帳と異なります")
    entries = json.loads(INPUT.read_text(encoding="utf-8"))["entries"]
    if len(entries) != 65 or any(e["symbol"] != "NK225" for e in entries):
        raise ValueError("固定NK225全65場と異なります")
    groups = {"学習": [], "条件選択": [], "既使用11/4デイ": [], "全65場": entries}
    for entry in entries:
        phase = "既使用11/4デイ" if entry["session"][:10] >= "2026-11-04" else (
            "条件選択" if entry["session"][:10] >= "2026-10-19" else "学習")
        groups[phase].append(entry)
    values = {phase: summarize(rows) for phase, rows in groups.items()}
    result = {"確認日": "2026-11-04", "入力台帳SHA256": digest,
              "集計コードSHA256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "元の監査コード": "scripts/複合検証/データ準備.py",
              "方法": "00008のvolume_auditを再集計。原板の新しい独立再監査ではない",
              "数量足分": 5, "全65場既使用": True, "結果": values,
              "限界": "価格時計の利用可能観測差分量。全約定数量・方向別フロー・全約定VWAPの完全性を証明しない。1/3分の数量足はこの件数表で監査していない。"}
    output = ROOT/"docs/議論/数量台帳の追加集計.json"
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    text = "# 現在のNK225全65場の数量台帳集計\n\n確認日2026-11-04。[既存の入力と数量の監査](入力と数量の監査.md)を補足する。00008に保存された数量監査を再集計したもので、原板の新しい独立再監査ではない。全65場は既使用。\n\n"
    text += "| 期間 | 場 | 価格5分足 | 基準完全足 | 不完全足 | 直前20数量足が利用可能 |\n| --- | ---: | ---: | ---: | ---: | ---: |\n"
    for phase, item in values.items():
        text += "| "+" | ".join(str(v) for v in (phase, item["場数"], *(item["足件数"][key] for key in FIELDS)))+" |\n"
    text += "\n場内の単調な価格時計で数量監査へ採った2,379,517状態は、数量時計と価格時計が一致していた。保存監査の数量欠測/不正、数量時計欠測、先行/遅延、採用累積減少・採用数量時計後退はいずれも0。原行全体や場外・時計欠測まで完全だったという意味ではない。\n\n"
    text += "基準不完全85足は初回または欠足後の再基準化を含み、欠けた5分枠21個と区別する。この入力では観測差分量による補助を検討できるが、数量条件を付ける候補だけ開始を遅くせず、対照も同じ数量助走を要求する。現在足をRVOLの直前20足平均へ入れない。1/3分で比較する場合は、その足幅の集約と準備の検査を追加する。\n\n"
    text += "価格は最終観測価格、数量は累積値の変化であり、差分量すべてがその最終価格で約定したとは分からない。全約定VWAPや参加者の建値として使わず、約定側別の買い/売り圧力とも呼ばない。出来高補助の費用後優位性は別の試行で検証する。\n\n"
    text += "[数値の正本](数量台帳の追加集計.json) / [固定00008入力台帳](../../study/00008_外部研究を共通尺度へ移して探索/入力台帳.json) / [集計コード](../../scripts/入力監査/数量台帳集計.py)\n\n再表示：`python -X utf8 scripts/入力監査/数量台帳集計.py`。標準ライブラリだけを使う。入力台帳SHA256は数値正本へ保存した。\n"
    output.with_suffix(".md").write_text(text, encoding="utf-8")
    print(json.dumps({phase: item["足件数"] for phase, item in values.items()}, ensure_ascii=False))


if __name__ == "__main__":
    main()
