"""既存45デイの単一口座から、週初に決めた出口だけを順番に接続する。"""
import argparse
from collections import defaultdict
from datetime import date
import hashlib
import json
from pathlib import Path
import runpy

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
WORK = ROOT / "work/225週次選抜"
SOURCE = {
    "I": "222境界照合", "T": "222境界照合", "P01": "223値幅",
    "S00": "223構造", "S03": "223構造", "V03": "223残存",
    "R01": "223反対", "R02": "223反対", "Q02": "223量",
}
WAITS = (20, 30)
RULES = ("単純IFD", "全履歴", "直近3週")
MEASURE = runpy.run_path(str(next(HERE.parent.glob("00222_*/建玉制限を再生する.py"))))["measures"]
CSV = runpy.run_path(str(next(HERE.parent.glob("00222_*/候補別CSVを用意する.py"))))


def load() -> tuple:
    """
    機能：同じ入口を使用した出口別口座を読み、完結した日別に分ける。
    引数：なし。SOURCEに指定した試行222・223の口座元帳を用いる。
    返り値：tuple。対象日、候補・待機・日別の建玉、入力ファイルの指紋。
    """
    records, hashes, books = {}, {}, {}
    for folder in dict.fromkeys(SOURCE.values()):
        filename = "口座元帳.json" if folder.startswith("222") else "比較元帳.json"
        path = ROOT / "work" / folder / filename
        data = path.read_bytes()
        records[folder] = json.loads(data)
        hashes[str(path.relative_to(ROOT).as_posix())] = hashlib.sha256(data).hexdigest()
    dates = records[SOURCE["I"]]["対象場"]
    assert len(dates) == 45 and sorted(set(dates)) == dates
    for choice, folder in SOURCE.items():
        for wait in WAITS:
            key = f"{choice}{wait}" if folder.startswith("222") else f"{choice}_{wait}"
            rows = records[folder]["口座再生"][key]
            by_day = {d: [] for d in dates}
            for row in rows:
                by_day[row["scene"]].append(row)
            for day, trades in by_day.items():
                previous = 0
                for row in trades:
                    assert previous < row["request_time"] <= row["entry_time"] <= row["confirmed_until"]
                    previous = row["confirmed_until"]
                MEASURE([day], trades, wait)
            books[choice, wait] = by_day
    return dates, books, hashes


def weekly(dates: list) -> list:
    """
    機能：ISO暦週にまとめ、すべて月曜から金曜の5デイであることを確認する。
    引数：dates（list）は昇順の場名。
    返り値：list。週ごとの日付一覧。
    """
    groups = defaultdict(list)
    for day in dates:
        groups[date.fromisoformat(day[:10]).isocalendar()[:2]].append(day)
    weeks = list(groups.values())
    assert len(weeks) == 9
    for days in weeks:
        assert [date.fromisoformat(d[:10]).weekday() for d in days] == list(range(5))
    return weeks


def effects(rows: dict) -> dict:
    """
    機能：渡された期間だけを用いて、単純IFD比の損失減と収支増を計算する。
    引数：rows（dict）は候補・待機別の対象期間内の建玉。
    返り値：dict。候補別・待機別の損失減、収支増、候補もしくは基準の未知件数。
    """
    sums = {}
    for key, trades in rows.items():
        net = [t["net"] for t in trades if t["net"] is not None]
        sums[key] = (-sum(x for x in net if x < 0), sum(net), len(trades)-len(net))
    result = {}
    for choice in SOURCE:
        result[choice] = {}
        for wait in WAITS:
            loss, balance, missing = sums[choice, wait]
            base_loss, base_net, base_missing = sums["I", wait]
            result[choice][wait] = (base_loss-loss, balance-base_net, missing+base_missing)
    return result


def rank(scores: dict) -> list:
    """
    機能：両待機の損失減と収支増がすべて正の候補から、事前指定順に優先順位を決定する。
    引数：scores（dict）は完結済みの窓に限った候補別の金額差。
    返り値：list。過去だけで適格となった候補の優先順。
    """
    eligible = []
    for order, choice in enumerate(SOURCE):
        values = list(scores[choice].values())
        if all(loss > 0 and net > 0 and missing == 0 for loss, net, missing in values):
            eligible.append((-min(v[0] for v in values), -min(v[1] for v in values), order, choice))
    return [row[-1] for row in sorted(eligible)]


def project(days: list, books: dict) -> dict:
    """
    機能：期間外の建玉を除き、後続計算が参照できる情報を渡された日だけに絞る。
    引数：days（list）は対象日、books（dict）は出口・待機・日別の元帳。
    返り値：dict。候補・待機別の取引一覧。
    """
    return {key: [t for d in days for t in by_day[d]] for key, by_day in books.items()}


def walk(weeks: list, books: dict) -> tuple:
    """
    機能：適用週より前の情報だけで選び、凍結後に適用週を別途評価する。
    引数：weeks（list）は暦週、books（dict）は9条件の口座。
    返り値：tuple。各日の出口割当と、週ごとの訓練と適用週の評価。
    """
    picks = {name: {} for name in RULES}
    history = []
    for index, current in enumerate(weeks):
        for name in RULES:
            prior = weeks[:index] if name == "全履歴" else weeks[max(0, index-3):index]
            training = [d for week in prior for d in week]
            chosen, order, train = "I", [], {}
            if index >= 3 and name != "単純IFD":
                assert training[-1] < current[0]
                train = effects(project(training, books))
                order = rank(train)
                chosen = order[0] if order else "I"
            picks[name].update(dict.fromkeys(current, chosen))
            if name != "単純IFD" and index >= 3:
                observed = effects(project(current, books))[chosen]
                history.append({"週": index+1, "方策": name, "初日": current[0], "最終日": current[-1],
                                "選抜窓": [training[0], training[-1]], "出口": chosen, "適格": order,
                                "過去": train, "当週": observed, "過去両立の当週再現": chosen != "I" and
                                all(l > 0 and n > 0 and u == 0 for l, n, u in observed.values())})
    return picks, history


def publish(dates: list, books: dict, picks: dict) -> tuple:
    """
    機能：日末の無保有を境に実際に選ばれた元帳を繋ぎ、期間・日・明細の候補別表を生成する。
    引数：dates（list）は全対象日、books（dict）は元帳、picks（dict）は週初に決めた日別出口。
    返り値：tuple。候補別CSV入力と、報告用の期間集計。
    """
    old = CSV["OLD"]
    tables = {
        "候補比較": {"headers": ["候補", "期間", *old["COLS"].values(), "含み益後赤字件数", "含み益後赤字の損失円"], "rows": []},
        "デイ": {"headers": ["候補", *old["DAY"].values(), "対象秒数", "既知保有秒数", "適用出口", "暦週"], "rows": []},
        "建玉明細": {"headers": ["候補","セッション","方向","判断日時JST","新規日時JST","建値pt","IFD片幅pt","利確指値pt",
                         "初期損切価格pt","決済日時JST","決済値pt","費用後収支円","決済理由","新規原行","決済原行",
                         "最大評価損益円","最大評価日時JST","最小評価損益円","最小評価日時JST","追尾起動時刻JST",
                         "追尾発動時刻JST","適用出口","暦週"], "rows": []},
    }
    totals = {}
    for rule in RULES:
        for wait in WAITS:
            label = f"225:{rule}_{wait}分"
            book = [t for d in dates for t in books[picks[rule][d], wait][d]]
            periods = {"全45日": dates, "初期15日": dates[:15], "週次適用30日": dates[15:]}
            for period, span in periods.items():
                daily, summary = MEASURE(span, book, wait)
                tables["候補比較"]["rows"].append([label, period, *[summary[k] for k in old["COLS"]],
                                                   summary["利益後赤字件数"], summary["利益後赤字損失"]])
                totals.setdefault(rule, {}).setdefault(wait, {})[period] = summary
                if period == "全45日":
                    for item in daily:
                        day = item["場"]
                        tables["デイ"]["rows"].append([label, *[item[k] for k in old["DAY"]],
                            item["対象秒"], item["保有秒"], picks[rule][day], date.fromisoformat(day[:10]).isocalendar().week])
            for trade in book:
                day = trade["scene"]
                tables["建玉明細"]["rows"].append([*CSV["trade_row"](label, trade), picks[rule][day],
                                                date.fromisoformat(day[:10]).isocalendar().week])
    return {"tableNames": CSV["TABLE_NAMES"], "tables": tables}, totals


def main() -> None:
    """
    機能：選抜根拠、期間集計、CSVの型付き原稿を作成し、任意で公開CSVを原稿と全セル照合する。
    引数：CLIの --照合（Path、任意）は候補別CSVの親フォルダ。
    返り値：なし。JSONを作業領域に保存する。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--照合", type=Path)
    args = parser.parse_args()
    dates, books, hashes = load()
    weeks = weekly(dates)
    picks, history = walk(weeks, books)
    for count in range(4, len(weeks)):
        short_days = dates[:count*5]
        prefix = {key: {day: value[day] for day in short_days} for key, value in books.items()}
        partial, trace = walk(weeks[:count], prefix)
        assert all(partial[rule] == {day: picks[rule][day] for day in short_days} for rule in RULES)
        assert trace == [entry for entry in history if entry["週"] <= count]
    payload, totals = publish(dates, books, picks)
    WORK.mkdir(parents=True, exist_ok=True)
    for file, data in (("閲覧入力", payload), ("選抜", {"対象場": dates, "割当": picks, "週別": history, "期間": totals, "元帳SHA256": hashes})):
        (WORK / f"{file}.json").write_text(json.dumps(data, ensure_ascii=False, allow_nan=False), encoding="utf8")
    if args.照合:
        CSV["NAMES"].clear()
        CSV["NAMES"].update({(r, w): f"225:{r}_{w}分" for r in RULES for w in WAITS})
        CSV["verify"](payload, args.照合)


if __name__ == "__main__":
    main()
