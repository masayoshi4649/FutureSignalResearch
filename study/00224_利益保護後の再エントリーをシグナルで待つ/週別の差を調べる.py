"""I20とRC20の日次損益を同日で対応させ、暦週単位で改善の広がりを調べる。"""
from collections import defaultdict
from csv import DictReader
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUTPUTS = HERE.parents[1]/"outputs"
FIELDS = ("既知利益円", "既知損失円", "既知収支円")


def read_candidate(pattern: str) -> dict:
    """
    機能：候補の日次CSVから既知の利益・損失・収支を読み、日次合計を公式期間集計と照合する。
    引数：pattern（str）は公開CSVの候補ディレクトリに一致する相対パターン。
    返り値：dict。各日付文字列から利益・損失・収支の順のタプルへの辞書。
    """
    directory, = OUTPUTS.glob(pattern)
    days = {}
    with (directory/"デイ.csv").open(encoding="utf-8-sig", newline="") as stream:
        for row in DictReader(stream):
            day = row["セッション"][:10]
            assert day not in days and row["セッション"] == day+"_Day" and int(row["未知件数"]) == 0
            values = tuple(int(row[k]) for k in FIELDS)
            assert values[0]-values[1] == values[2] == int(row["確定収支円"])
            days[day] = values
    with (directory/"集計.csv").open(encoding="utf-8-sig", newline="") as stream:
        counts, = (r for r in DictReader(stream) if r["期間"] == "全45日")
    assert len(days) == int(counts["場数"]) == 45
    assert all(sum(v[i] for v in days.values()) == int(counts[k]) for i, k in enumerate(FIELDS))
    return days


def main() -> None:
    """
    機能：45日を9週に分け、週内の差と1週ずつ除外した残り40日の差を直接加算して照合する。
    引数：なし。試行222のI20と試行224のRC20の公開CSVを使用する。
    返り値：なし。週別表・改善週数・除外範囲を標準出力へ表示する。
    """
    base = read_candidate("00222_*/222_I20_*")
    rc = read_candidate("00224_*/224_RC20_*")
    assert base.keys() == rc.keys()
    weeks = defaultdict(list)
    delta = {}
    for day in sorted(base):
        stamp = date.fromisoformat(day)
        weeks[stamp.isocalendar()[:2]].append(day)
        delta[day] = (rc[day][2]-base[day][2], rc[day][1]-base[day][1])
    assert len(weeks) == 9
    whole = tuple(sum(v[i] for v in delta.values()) for i in (0, 1))
    weekly, excluded = [], []
    for span in weeks.values():
        assert [date.fromisoformat(d).weekday() for d in span] == list(range(5))
        week = tuple(sum(delta[d][i] for d in span) for i in (0, 1))
        rest = tuple(sum(v[i] for day, v in delta.items() if day not in span) for i in (0, 1))
        assert tuple(a+b for a, b in zip(week, rest, strict=True)) == whole
        weekly.append(week)
        excluded.append(rest)
        print(span[0], span[-1], *week, *rest)
    assert tuple(map(sum, zip(*weekly))) == whole
    print("全45日の収支差・損失差", *whole)
    for i, sign in ((0, 1), (1, -1)):
        print(("収支", "総損失")[i], "改善・悪化・同額の週", sum(sign*x[i] > 0 for x in weekly),
              sum(sign*x[i] < 0 for x in weekly), sum(x[i] == 0 for x in weekly),
              "1週除外後の差の範囲", min(x[i] for x in excluded), max(x[i] for x in excluded))


if __name__ == "__main__":
    main()
