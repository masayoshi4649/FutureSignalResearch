"""日経199_02の単純IFDで建ててから返済するまでの実側気配と損益の山谷を調べる。"""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT/"work/163任意幅の数値化"))
from arrays163 import load_records

JST = timezone(timedelta(hours=9))
FEE = 1077
WORK = ROOT/"work/219経路"


def stamp(seconds: float) -> str:
    """
    機能：気配の価格時計を日本時間の時分秒付き日付へ変換する。
    引数：seconds（float）はUnix秒。
    返り値：str。日本標準時での日時。
    """
    return datetime.fromtimestamp(seconds, JST).isoformat(timespec="seconds")


def archives() -> dict:
    """
    機能：元口座が参照したデイごとの価格索引と指紋を集める。
    引数：なし。既使用の索引と最後の3デイに使った再生用部品を読む。
    返り値：dict。セッション名から原順価格索引のパス・指紋・行数への対応。
    """
    files = [next((ROOT/"inputs").glob(pattern)) for pattern in (
        "00163*/価格索引/manifest.json", "00167*/原板数値索引/manifest.json",
        "00180*/原板数値索引/manifest.json", "00194*/NK225/原板数値索引/manifest.json")]
    files.append(ROOT/"work/216日経/前史十場と追加二場の索引参照.json")
    archives_by_day = {}
    for file in files:
        for scene in json.loads(file.read_bytes())["scenes"]:
            if scene["session"].endswith("_Day"):
                idx = scene["index"]
                archives_by_day.setdefault(scene["session"], (file.parent/idx["path"], idx["sha256"], scene["rows"]))
    return archives_by_day


def observe(trade: dict, records: np.ndarray) -> dict:
    """
    機能：新規から元決済の原行までについて、正常な返済側気配の費用後含み損益を測る。
    引数：trade（dict）は既知決済の建玉、records（np.ndarray）は当日の原順48バイト指数。
    返り値：dict。極値と最初の到達日時、決済、費用後返済見積りなど。
    """
    entry = trade["entry_index"]
    exit_index = trade["exit_index"]
    rows = records[entry:exit_index+1]
    quotes = rows[rows["normal"] == 1]
    assert len(quotes) and quotes["source_line"][0] == trade["entry_line"]
    assert quotes["source_line"][-1] == trade["exit_line"]
    assert (quotes["time"][0], quotes["time"][-1]) == (trade["entry_time"], trade["exit_time"])
    assert np.all(np.diff(quotes["time"]) >= 0)
    max_gap = float(max(np.diff(quotes["time"]), default=0))
    assert max_gap <= 300 and np.all(np.isfinite(quotes["bid"])) and np.all(np.isfinite(quotes["ask"]))
    buy = trade["side"] == 0
    price = trade["entry_price"]
    assert quotes["ask" if buy else "bid"][0] == price
    mark = quotes["bid" if buy else "ask"]
    nets = (mark-price) * (100 if buy else -100) - FEE
    assert mark[-1] == trade["exit_price"] and nets[-1] == trade["net"]
    assert int(nets[-1]) == nets[-1]
    # ----------------------------------------
    peak, trough = int(np.argmax(nets)), int(np.argmin(nets))
    start = float(quotes["time"][0])
    earliest = np.flatnonzero(nets > 0)
    minute = datetime.fromtimestamp(start, JST)
    clock = minute.hour*60 + minute.minute
    band = ("08:45～09:00", "09:00～11:30", "11:30～12:30", "12:30～15:30")[sum(clock >= e for e in (540,690,750))]
    out = {
        "場": trade["scene"], "方向": "買い" if buy else "売り", "新規帯": band,
        "新規日時": stamp(start), "新規原行": trade["entry_line"], "建値": price,
        "対称幅pt": trade["width"], "保有期限": trade["horizon"],
        "含み益初発": stamp(quotes["time"][earliest[0]]) if earliest.size else None,
        "最大時": stamp(quotes["time"][peak]), "最大原行": int(quotes["source_line"][peak]),
        "最大時実側気配": float(mark[peak]), "観測最大損益円": int(nets[peak]),
        "最小時": stamp(quotes["time"][trough]), "最小原行": int(quotes["source_line"][trough]),
        "最小時実側気配": float(mark[trough]), "観測最小損益円": int(nets[trough]),
        "返済時": stamp(quotes["time"][-1]), "返済原行": trade["exit_line"],
        "返済値": trade["exit_price"], "確定収支円": int(nets[-1]), "元決済": trade["status"],
        "最大から返済まで円": int(nets[peak]-nets[-1]), "最大から返済まで秒": float(quotes["time"][-1]-quotes["time"][peak]),
        "観測正常行数": len(quotes), "正常以外の行数": len(rows)-len(quotes), "正常間隔最大秒": max_gap,
    }
    for threshold in (5000,10000,15000,20000):
        hit = np.flatnonzero(nets >= threshold)
        out[f"{threshold}円初達"] = stamp(quotes["time"][hit[0]]) if hit.size else None
    for minutes in (5,15,30):
        deadline = start+60*minutes
        # 元決済と同時刻なら保有中の判断対象に含めない。
        if deadline < quotes["time"][-1]:
            pos = int(np.searchsorted(quotes["time"], deadline, "right"))-1
            out[f"{minutes}分時点損益"] = int(nets[pos])
            out[f"{minutes}分までの最大損益"] = int(nets[:pos+1].max())
        else:
            out[f"{minutes}分時点損益"] = None
            out[f"{minutes}分までの最大損益"] = None
    return out


def describe(rows: list) -> dict:
    """
    機能：含み益後に赤字になった建玉の件数、確定した損失、戻した額を集計する。
    引数：rows（list）は対象群で建てた全件の経路記録。
    返り値：dict。観測のみの戻しと、実際の既知損益を区別した内訳。
    """
    wins = [r for r in rows if r["確定収支円"] > 0]
    losses = [r for r in rows if r["確定収支円"] < 0]
    giveback = [r for r in losses if r["観測最大損益円"] > 0]
    return {
        "件数": len(rows), "黒字": len(wins), "赤字": len(losses),
        "利益": sum(r["確定収支円"] for r in wins), "損失": -sum(r["確定収支円"] for r in losses),
        "いったん含み益": sum(r["観測最大損益円"] > 0 for r in rows),
        "含み益後赤字": len(giveback), "その確定損失": -sum(r["確定収支円"] for r in giveback),
        "その観測最大からの戻し": sum(r["最大から返済まで円"] for r in giveback),
        "終始含み益なしの赤字": len(losses)-len(giveback),
        "最大含み益建玉の戻し合計": sum(r["最大から返済まで円"] for r in rows if r["観測最大損益円"] > 0),
    }


def main() -> None:
    """
    機能：元181件の原行に対して経路診断を実行し、期間・方向・時刻・利益到達額で集計する。
    引数：なし。先に試行218の片側対照を再生する。
    返り値：None。元帳と小計を作業領域へ保存する。
    """
    trades = json.loads((ROOT/"work/218片側/比較元帳.json").read_bytes())["元の両側"]
    assert len(trades) == 181 and all(t["net"] is not None for t in trades)
    dates = sorted({t["scene"] for t in trades})
    files = archives()
    all_rows = []
    for day in dates:
        records = load_records(*files[day])
        all_rows.extend(observe(t, records) for t in trades if t["scene"] == day)
    assert len(dates) == 45 and sum(r["確定収支円"] for r in all_rows) == 1020063
    by = {}
    for era, subset in (("全45",dates),("前24",dates[:24]),("後21",dates[24:])):
        samples = [r for r in all_rows if r["場"] in subset]
        for name, group in [("両側",samples), *((k,[r for r in samples if r["方向"]==k]) for k in ("買い","売り"))]:
            by[era+"_"+name] = describe(group)
            for slot in sorted({r["新規帯"] for r in samples}):
                by[era+"_"+name+"_"+slot] = describe([r for r in group if r["新規帯"]==slot])
    for threshold in (5000,10000,15000,20000):
        by[f"含み益{threshold}円以上"] = describe([r for r in all_rows if r[f"{threshold}円初達"]])
    # ----------------------------------------
    WORK.mkdir(parents=True, exist_ok=True)
    (WORK/"建玉経路.json").write_text(json.dumps(all_rows, ensure_ascii=False, allow_nan=False), encoding="utf8")
    (WORK/"経路小計.json").write_text(json.dumps(by, ensure_ascii=False, allow_nan=False), encoding="utf8")


if __name__ == "__main__":
    main()
