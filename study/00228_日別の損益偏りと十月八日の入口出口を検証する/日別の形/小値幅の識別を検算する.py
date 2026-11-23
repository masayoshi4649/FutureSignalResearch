"""日全体の値幅順位と実際の取得時に知り得た20分の値幅を、同じ45日・133建玉で突合する。"""
import csv
import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
BASE = ROOT / "work/224反対追試/口座元帳.json"
TEST = ROOT / "work/228小値幅/口座元帳.json"
DAILY = next((ROOT / "outputs").glob("00228_*/228_RC20_日別の形/日別の形と損益.csv"))


def accounts(path: Path, key: str) -> dict:
    """
    機能：口座の建玉を場・要求行・取得行・方向・元の幅で引けるようにする。
    引数：path（Path）は元帳、key（str）は候補名。返り値：dict。固有キーに対応する建玉。
    """
    trades = json.loads(path.read_bytes())["口座再生"][key]
    lookup = {(t["scene"], t["request_line"], t["entry_line"], t["side"], t["width"]): t for t in trades}
    assert len(lookup) == len(trades)
    return lookup


def main() -> None:
    """
    機能：常時既知でない当日値幅と、各取得時点で判別可能だった小値幅・追加決済を分けて集計する。
    引数：なし。返り値：None。区分別の件数・変化日・期間別現金収支を表示する。
    """
    with DAILY.open(encoding="utf-8-sig", newline="") as stream:
        days = list(csv.DictReader(stream))
    base, variant = accounts(BASE, "RC20"), accounts(TEST, "V02C20")
    assert base.keys() == variant.keys() and len(base) == 133 and len(days) == 45
    states = defaultdict(list)
    for key, t in variant.items():
        ref = base[key]
        width = t["prior_range"]
        flag = "欠測" if width is None else "該当" if width <= t["width"] / 2 else "非該当"
        triggered = t["extra_signal"] >= 0
        filled = t["extra_fill"]
        changed = (t["exit_line"], t["net"]) != (ref["exit_line"], ref["net"])
        assert not triggered or flag == "該当"
        assert changed == filled
        states[t["scene"]].append((flag, triggered, filled, int(t["net"] - ref["net"])))
        if t["scene"] == "2026-10-08_Day":
            print("10/8取得", t["entry_line"], width, t["width"], width / t["width"], flag)

    # ----------------------------------------
    for rank in ("小", "中", "大"):
        members = [row for row in days if row["値幅区分"] == rank]
        by_day = {r["セッション"]: states[r["セッション"]] for r in members}
        records = [item for values in by_day.values() for item in values]
        for unit, values in (("建玉", [[t] for t in records]), ("日", by_day.values())):
            positive = sum(any(v[0] == "該当" for v in group) for group in values)
            negative = sum(all(v[0] == "非該当" for v in group) for group in values)
            triggered = sum(any(v[1] for v in group) for group in values)
            filled = sum(any(v[2] for v in group) for group in values)
            print(rank, unit, "該当・非該当・不明・発火・決済", positive, negative, len(values)-positive-negative, triggered, filled)
        print("変化した取引の場・収支差", [(d[5:10], t[3]) for d, vs in by_day.items() for t in vs if t[2]])
        for group in (days[:24], days[24:]):
            subset = [d for d in group if d["値幅区分"] == rank]
            print(rank, subset[0]["セッション"], "日数・赤字・利益ゼロ・買い・売り",
                  len(subset), sum(float(d["収支円"]) < 0 for d in subset), sum(float(d["利益円"]) == 0 for d in subset),
                  sum(int(d["買い収支円"]) for d in subset), sum(int(d["売り収支円"]) for d in subset))


if __name__ == "__main__":
    main()
