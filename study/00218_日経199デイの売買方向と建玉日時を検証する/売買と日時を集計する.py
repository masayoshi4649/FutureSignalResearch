"""日経199_02の判断・新規・決済を同じ建玉に結び、方向別の時系列を作る。"""
import csv
import json
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
WORK = ROOT / "work/218集計"
sys.path.insert(0, str(next((ROOT / "study").glob("00216_*"))))
from 全場を集計する import JST, calculate, sources, windows

SIDES = {"買い": 0, "売り": 1}
NAMES = {"元の両側": "218:日経199_02", "買い限定": "218:買い限定", "売り限定": "218:売り限定"}
SLOTS = ("08:45～09:00", "09:00～11:30", "11:30～12:30", "12:30～15:30")
OUTCOME = {1: "利確先着", 2: "損切先着", 3: "期限決済", 4: "セッション締切"}
METRICS = {
    "場数": "対象日数", "参加場": "取得日数", "取得": "建玉回数", "勝": "黒字件数", "敗": "赤字件数",
    "未知": "損益不明件数", "勝率": "確定建玉勝率", "利益": "利益円（既知）", "損失": "損失円（既知）",
    "収支": "収支円（既知）", "順": "順先着件数", "逆": "逆先着件数", "未到達": "未到達件数",
    "不足": "観測不足件数", "先着率": "到達済み順先着率", "黒字場": "確定黒字日数",
    "赤字場": "確定赤字日数", "建玉中央値下限": "建玉中央値下限円", "建玉中央値上限": "建玉中央値上限円",
    "場中央値下限": "日次中央値下限円", "場中央値上限": "日次中央値上限円",
}
TRADE_COLS = ["候補", "建玉番号", "売買方向", "判断日時JST", "新規日時JST", "決済日時JST",
              "建値pt", "決済値pt", "売買方向の値幅pt", "費用前損益円", "往復費用円（決済済）",
              "費用後損益円", "決済区分", "建玉時間帯JST", "IFD片側幅pt", "保有期限",
              "保有秒数", "判断原行", "新規原行", "決済原行"]


def stamp(seconds: float | None) -> str | None:
    """
    機能：原板の価格時計を日本標準時の年月日時分秒に変換する。
    引数：seconds（float または None）はUnix秒。
    返り値：str または None。日時不明の場合は空欄にする。
    """
    if seconds is None:
        return None
    assert seconds == int(seconds)
    return datetime.fromtimestamp(seconds, JST).strftime("%Y-%m-%d %H:%M:%S")


def slot(trade: dict) -> str:
    """
    機能：実際に新規取得した時刻を固定の時計帯へ割り当てる。
    引数：trade（dict）は方向と取得時刻を持つ建玉。
    返り値：str。開始を含み終了を含まない時計帯。
    """
    opened = datetime.fromtimestamp(trade["entry_time"], JST)
    minute = opened.hour*60 + opened.minute
    assert 525 <= minute < 930
    return SLOTS[sum(minute >= edge for edge in (540, 690, 750))]


def session_prices(dates: list) -> dict:
    """
    機能：各日の08:45確定足の始値と15:29確定足の終値を後付け診断用に取得する。
    引数：dates（list）は全対象シーン。
    返り値：dict。場別の始値・終値・騰落方向。
    """
    result = {}
    for day in dates:
        path = ROOT.parent / "JP_OSE_Data/future/NK225" / day / "candle_1min.csv"
        with path.open(encoding="utf-8-sig", newline="") as stream:
            selected = {}
            for r in csv.DictReader(stream):
                moment = datetime.fromisoformat(r["time"]).astimezone(JST)
                t = moment.strftime("%H:%M")
                if moment.date().isoformat() == day[:10] and t in ("08:45", "15:29"):
                    assert r["closed"].lower() == "true" and t not in selected
                    selected[t] = r
        start, end = int(selected["08:45"]["open"]), int(selected["15:29"]["close"])
        result[day] = (start, end, "上昇" if end > start else "下落" if end < start else "同値")
    return result


def trade_record(name: str, seq: int, trade: dict) -> list:
    """
    機能：1建玉の時刻、方向、返済理由と費用後損益を照合して並べる。
    引数：name（str）は口座名、seq（int）は通番、trade（dict）は元帳の建玉。
    返り値：list。建玉明細CSVの1行。
    """
    t = trade
    known = t["net"] is not None
    begin, end = windows(t["scene"], "全体")
    assert t["side"] in SIDES.values() and begin <= t["request_time"] <= t["entry_time"] < end
    change = fee = held = None
    reason = "決済不明"
    if known:
        assert t["entry_time"] <= t["exit_time"] <= end and t["confirmed_until"] == t["exit_time"]
        change = (t["exit_price"]-t["entry_price"]) * (1 if t["side"] == 0 else -1)
        fee = 1077
        assert change*100 == t["gross"] and change*100-fee == t["net"]
        held = int(t["exit_time"]-t["entry_time"])
        reason = OUTCOME[t["status"]]
        assert t["label"] == {1: 1, 2: -1, 3: 0, 4: 0}[t["status"]]
    else:
        assert t["exit_time"] is None and t["exit_price"] is None
    return [name, seq, "買い" if t["side"] == 0 else "売り", stamp(t["request_time"]),
            stamp(t["entry_time"]), stamp(t["exit_time"]), t["entry_price"], t["exit_price"], change,
            t["gross"], fee, t["net"], reason, slot(t), t["width"], "場末" if t["horizon"] == "SESSION" else t["horizon"][1:]+"分",
            held, t["request_line"], t["entry_line"], t["exit_line"] if known else None]


def summary(dates: list, trades: list) -> tuple:
    """
    機能：元帳の対象群を日順に集計し、費用後勝率と同幅到達時の先着率を求める。
    引数：dates（list）は分母に残す全日、trades（list）は対象の建玉。
    返り値：tuple。日別の内訳と集計CSVの指標列。
    """
    daily, m = calculate(dates, trades, "全体")
    known = m["取得"] - m["未知"]
    reached = m["順"] + m["逆"]
    m.update(勝率=m["勝"]/known if known else None, 先着率=m["順"]/reached if reached else None)
    return daily, [m[k] for k in METRICS]


def tables(account: str, dates: list, trades: list, prices: dict) -> dict:
    """
    機能：口座ごとに建玉明細・日別・期間別を生成し、元口座は方向と時間帯も分解する。
    引数：account（str）は口座ID、dates（list）は45日、trades（list）は口座元帳、prices（dict）は両端の価格。
    返り値：dict。既存CSV出力器に渡す表。
    """
    name = NAMES[account]
    split = account == "元の両側"
    groups = {"合計": trades}
    if split:
        groups.update({side: [r for r in trades if r["side"] == code] for side, code in SIDES.items()})
    # ----------------------------------------
    result = {"候補比較": {"headers": ["候補", "方向", "対象"]+list(METRICS.values()), "rows": []},
              "建玉明細": {"headers": list(TRADE_COLS), "rows": [trade_record(name, i, t) for i,t in enumerate(trades, 1)]}}
    if split:
        observed = json.loads((ROOT/"work/218時刻/当時位置.json").read_bytes())["明細"]
        index = {(r["場"], r["取得原行"]): r for r in observed}
        assert len(index) == len(trades)
        result["建玉明細"]["headers"] += ["当日最初の正常板中値pt", "判断時中値pt", "判断時の朝比pt"]
        for trade, record in zip(trades, result["建玉明細"]["rows"], strict=True):
            seen = index[trade["scene"], trade["entry_line"]]
            assert seen["判断原行"] == trade["request_line"] and seen["収支"] == trade["net"]
            record.extend([seen["基準中値"], seen["判断中値"], seen["中値差"]])
    sessions = {}
    for side, group in groups.items():
        daily, _ = summary(dates, group)
        sessions[side] = daily
        top = sorted((d for d in daily if d["確定収支"] is not None and d["収支"] > 0),
                     key=lambda d: (-d["収支"], d["場"]))[:3]
        skipped = {r["場"] for r in top}
        spans = {"全45日": dates, "前24日": dates[:24], "後21日": dates[24:], "直近3日": dates[-3:],
                 "10月20日除外": [d for d in dates if d[:10] != "2026-10-20"],
                 "当該方向の利益上位3日除外": [d for d in dates if d not in skipped]}
        for month in ("09", "10", "11"):
            spans[month+"月"] = [d for d in dates if d[5:7] == month]
        for direction in ("上昇", "下落", "同値"):
            days = [d for d in dates if prices[d][2] == direction]
            if days:
                spans["当日"+direction+"（場末判明）"] = days
        for period, days in spans.items():
            _, values = summary(days, group)
            result["候補比較"]["rows"].append([name, side, period, *values])
    # ----------------------------------------
    day_keys = {"取得": "件数", "勝": "黒字件数", "敗": "赤字件数", "未知": "不明件数", "利益": "利益円",
                "損失": "損失円", "収支": "既知収支円", "確定収支": "確定収支円", "既知累計": "既知累計円"}
    headers = ["候補", "セッション日JST", "曜日", "08:45始値pt", "15:29足終値pt", "騰落pt（場末判明）"]
    headers += [side+k for side in groups for k in day_keys.values()]
    day_rows = []
    for i, day in enumerate(dates):
        start, end, _ = prices[day]
        weekday = datetime.fromisoformat(day[:10]).weekday()
        row = [name, day[:10], "月火水木金土日"[weekday], start, end, end-start]
        for side in groups:
            row += [sessions[side][i][k] for k in day_keys]
        if split:
            for k in ("取得", "利益", "損失", "収支"):
                assert sessions["合計"][i][k] == sessions["買い"][i][k] + sessions["売り"][i][k]
        day_rows.append(row)
    result["日別"] = {"headers": headers, "rows": day_rows}
    if split:
        by_slot = []
        for period, days in (("全45日", dates), ("前24日", dates[:24]), ("後21日", dates[24:])):
            for band in SLOTS:
                for side in SIDES:
                    subset = [t for t in groups[side] if slot(t) == band]
                    _, values = summary(days, subset)
                    by_slot.append([name, period, band, side, *values])
        result["時間帯別"] = {"headers": ["候補", "対象", "新規時間帯JST", "売買方向"]+list(METRICS.values()), "rows": by_slot}
    return result


def main() -> None:
    """
    機能：両側の基準を既存金融正本と照合し、各口座を別CSV用の入力にする。
    引数：なし。片側対照を先に再生する。
    返り値：None。UTF-8の型付き表を作業領域へ保存する。
    """
    dates, originals, _ = sources("デイ")
    books = json.loads((ROOT/"work/218片側/比較元帳.json").read_bytes())
    assert set(books) == set(NAMES) and len(dates) == 45
    fields = "scene side entry_time exit_time entry_price exit_price entry_line exit_line net label width".split()
    ref = originals["216:日経199_02"]
    assert len(ref) == 181
    assert all(all(a[k] == b[k] for k in fields) for a,b in zip(ref, books["元の両側"], strict=True))
    prices = session_prices(dates)
    WORK.mkdir(exist_ok=True, parents=True)
    for account, trades in books.items():
        ordered = sorted(trades, key=lambda t: (t["entry_time"], t["entry_line"]))
        bundle = tables(account, dates, ordered, prices)
        names = {k: "集計" if k == "候補比較" else k for k in bundle}
        (WORK/(account+".json")).write_text(json.dumps({"tableNames": names, "tables": bundle},
                                                       ensure_ascii=False, allow_nan=False), encoding="utf8")


if __name__ == "__main__":
    main()
