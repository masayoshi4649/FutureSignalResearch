"""建玉を判断した原板行の中値と、その日最初の正常気配の中値を比較する。"""
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / "work/218時刻"
sys.path.insert(0, str(ROOT / "scripts/複合検証"))
from データ準備 import build_one, session_bounds


def quote_cache(scene: str) -> Path:
    """
    機能：原順8列を参照し、追加日のキャッシュが存在しなければ原板から再形成する。
    引数：scene（str）は日経デイの場名。
    返り値：Path。該当する場の8列ファイル。
    """
    name = scene + ".npz"
    paths = [next((ROOT / "inputs").glob("NK225原順8列_*")) / name,
             next((ROOT / "inputs").glob("00194_*")) / "原順8列/NK225" / name,
             ROOT / "work/217通知/NK225" / name, WORK / "8列" / name]
    for path in paths:
        if path.is_file():
            return path
    raw_root = ROOT.parent / "JP_OSE_Data"
    folder = raw_root / "future/NK225" / scene
    source = next(p for p in (folder / "book.jsonl", folder / "book.jsonl.gz") if p.is_file())
    paths[-1].parent.mkdir(parents=True, exist_ok=True)
    build_one(source, paths[-1], "NK225", scene, raw_root)
    return paths[-1]


def classify(change: float | None) -> str:
    """
    機能：基準からの価格差を日本語の区分に対応づける。
    引数：change（floatまたはNone）は比較価格から基準価格を引いた点数。
    返り値：str。上昇・下落・同値・不明のいずれか。
    """
    if change is None:
        return "不明"
    if change == 0:
        return "同値"
    return "上昇" if change > 0 else "下落"


def bar_change(scene: str) -> float | None:
    """
    機能：参考診断として、確定1分足の08:45始値から15:29終値までの変化を得る。
    引数：scene（str）は評価するデイの場名。
    返り値：floatまたはNone。日中変化幅。該当足が不足すれば不明。
    """
    path = ROOT.parent / "JP_OSE_Data/future/NK225" / scene / "candle_1min.csv"
    with path.open(encoding="utf-8-sig", newline="") as stream:
        candles = {r["time"][11:16]: r for r in csv.DictReader(stream)
                   if r["closed"] == "true" and r["time"].startswith(scene[:10])}
    if "08:45" not in candles or "15:29" not in candles:
        return None
    return float(candles["15:29"]["close"]) - float(candles["08:45"]["open"])


def measure(scene: str, trades: list) -> list:
    """
    機能：日経の全取得を生んだ判断行を照合し、当時までの中値変化と事後の日変化を記録する。
    引数：scene（str）は場名、trades（list）は同日元口座の取得元帳。
    返り値：list。各件の判断行・見えていた気配と当時及び事後の区分。
    """
    opened, _ = session_bounds(scene)
    cutoff = opened + 24300
    results = []
    hindsight = bar_change(scene)
    with np.load(quote_cache(scene), allow_pickle=False) as quotes:
        lines, now, valid = quotes["line"], quotes["now"], quotes["valid"]
        bid, ask = quotes["bid"], quotes["ask"]
        start_rows = np.flatnonzero(valid & (now >= opened) & (now < cutoff))
        first = int(start_rows[0]) if start_rows.size else None
        for trade in trades:
            qtime, qline = trade["request_time"], trade["request_line"]
            q = int(lines.searchsorted(qline))
            matched = q < len(lines) and lines[q] == qline and now[q] == qtime
            ready = first is not None and first <= q and now[first] <= qtime
            opening_mid = float((ask[first] + bid[first]) / 2) if ready else None
            request_mid = float((ask[q] + bid[q]) / 2) if matched and valid[q] else None
            change = request_mid - opening_mid if opening_mid is not None and request_mid is not None else None
            results.append({"場": scene, "取得原行": trade["entry_line"], "判断原行": qline,
                            "判断Unix秒": qtime, "基準原行": int(lines[first]) if ready else None,
                            "基準Unix秒": float(now[first]) if ready else None,
                            "基準中値": opening_mid, "判断中値": request_mid, "中値差": change,
                            "判断時の位置": classify(change), "当日足変化": hindsight,
                            "15時30分時点の事後区分": classify(hindsight),
                            "方向": ("買い", "売り")[trade["side"]], "収支": trade["net"]})
    return results


def summarize(rows: list, dates: list) -> list:
    """
    機能：判断時と引け時を別々に、全期間・前24日・後21日の売買方向別に集計する。
    引数：rows（list）は照合済みの取得、dates（list）は日付順の全45場。
    返り値：list。各区分の取得・取得日・黒字取引数・費用後利益・損失・収支。
    """
    tables = []
    for period, subset in (("全45日", dates), ("前24日", dates[:24]), ("後21日", dates[24:])):
        for field in ("判断時の位置", "15時30分時点の事後区分"):
            for flag in ("上昇", "下落", "同値", "不明"):
                for side in ("買い", "売り"):
                    group = [r for r in rows if r["場"] in subset and r[field] == flag and r["方向"] == side]
                    nets = [r["収支"] for r in group]
                    assert all(v is not None for v in nets)
                    tables.append({"期間": period, "観測": field, "区分": flag, "方向": side, "取得": len(nets),
                                   "取得日": len({r["場"] for r in group}), "勝": sum(v > 0 for v in nets),
                                   "利益": sum(v for v in nets if v > 0), "損失": -sum(v for v in nets if v < 0),
                                   "収支": sum(nets)})
    return tables


def main() -> None:
    """
    機能：元の両側口座から価格位置の診断を再現して作業領域に保存する。
    引数：なし。先に同試行の片側口座再生で比較元帳を生成する。
    返り値：None。work/218時刻/当時位置.jsonに出力する。
    """
    ledger = json.loads((ROOT / "work/218片側/比較元帳.json").read_bytes())["元の両側"]
    by_day = defaultdict(list)
    for trade in ledger:
        by_day[trade["scene"]].append(trade)
    dates = sorted(by_day)
    assert len(dates) == 45 and len(ledger) == 181
    rows = [row for day in dates for row in measure(day, by_day[day])]
    assert len(rows) == 181 and sum(r["収支"] for r in rows) == 1020063
    # ----------------------------------------
    WORK.mkdir(parents=True, exist_ok=True)
    data = {"明細": rows, "集計": summarize(rows, dates)}
    (WORK / "当時位置.json").write_text(json.dumps(data, ensure_ascii=False, allow_nan=False), encoding="utf8")


if __name__ == "__main__":
    main()
