"""10月8日の入口と清算側気配の経路を照合し、比較用の図と診断値を作る。"""
from argparse import ArgumentParser
from datetime import datetime, timedelta, timezone
import gzip
import json
from pathlib import Path
import runpy

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from matplotlib.font_manager import FontProperties
import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
STUDY = ROOT / "study"
WORK = ROOT / "work"
DAY = "2026-10-08_Day"
JST = timezone(timedelta(hours=9))


def clock(t: float) -> str:
    """
    機能：原板の秒時刻を日本時間に直す。
    引数：t（float）はUnix秒。
    返り値：str。時分秒。
    """
    return datetime.fromtimestamp(t, JST).strftime("%H:%M:%S")


def book(folder: str, name: str) -> list:
    """
    機能：固定候補の口座元帳を読む。
    引数：folder・name（str）は作業フォルダ名と候補ID。
    返り値：list。建玉別の約定・損益。
    """
    return json.loads((WORK / folder / "口座元帳.json").read_bytes())["口座再生"][name]


def draw(index: object, trades: list, scene: dict, other: dict) -> None:
    """
    機能：清算可能な最良買気配と各買い建玉の費用後評価額の経路を保存する。
    引数：index（PriceIndex）は正常板索引、trades（list）は当日の二建玉、scene（dict）は場時計、other（dict）はK08の2件目。
    返り値：None。原行から各分の高安と最終値を求め、場末15:30までを描く。
    """
    plt.rcParams["font.family"] = FontProperties(fname="C:/Windows/Fonts/YuGothM.ttc").get_name()
    fig, (price, profit) = plt.subplots(2, 1, figsize=(9, 5.2), sharex=True, height_ratios=(1.1, 1))
    valid = index.normal[(index.times[index.normal] >= scene["start"]) &
                         (index.times[index.normal] < scene["end"] - 900)]
    colors = ("#156792", "#a2432d")
    series = [(price, valid, index.rows["bid"][valid], "#334859")]
    for trade, color in zip(trades, colors):
        rows = valid[(valid >= trade["entry_index"]) & (valid <= trade["exit_index"])]
        series.append((profit, rows, (index.rows["bid"][rows] - trade["entry_price"]) * 100 - 1077, color))
    for axis, rows, y, color in series:
        stamps = index.times[rows]
        minutes, starts = np.unique(stamps.astype("int64") // 60, return_index=True)
        ends = np.r_[starts[1:] - 1, len(stamps) - 1]
        when = [datetime.fromtimestamp(t * 60, JST) for t in minutes]
        axis.vlines(when, np.minimum.reduceat(y, starts), np.maximum.reduceat(y, starts),
                    color=color, linewidth=.7, alpha=.5)
        axis.plot(when, y[ends], color=color, linewidth=1.1)
    for i, (trade, color) in enumerate(zip(trades, colors), start=1):
        for field, marker in (("entry", "^"), ("exit", "x")):
            x = datetime.fromtimestamp(trade[field + "_time"], JST)
            price.scatter(x, trade[field + "_price"], c=color, marker=marker, s=42, zorder=3)
        t = datetime.fromtimestamp(trade["max_unrealized_time"], JST)
        profit.scatter(t, trade["max_unrealized_net"], c=color, s=35)
        profit.annotate(f"{i}件目  +{trade['max_unrealized_net']:,.0f}円", (t, trade["max_unrealized_net"]),
                        xytext=(0, 9), textcoords="offset points", ha="center", fontsize=9)
    early_exit = datetime.fromtimestamp(other["exit_time"], JST)
    price.scatter(early_exit, other["exit_price"], color="#663fa4", marker="D", s=28, zorder=4)
    profit.scatter(early_exit, other["net"], color="#663fa4", marker="D", s=27, zorder=4)
    profit.annotate(f"K08返済  {clock(other['exit_time'])}\n+{other['net']:,.0f}円", (early_exit, other["net"]),
                    xytext=(12, 8), textcoords="offset points", fontsize=9, color="#663fa4")
    profit.axhline(0, color="#888888", lw=.8)
    profit.margins(y=.2)
    price.set_title("2026年10月8日　日経199_02（▲は新規買い、×はRC20返済、◆はK08の変更返済）", fontsize=12)
    price.set_ylabel("ラージの最良買気配（円）")
    profit.set_ylabel("mini 1枚換算の含み損益（円）")
    profit.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M", tz=JST))
    for ax in (price, profit):
        ax.grid(color="#d7dfe1", alpha=.65, lw=.5)
        ax.spines[["right", "top"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(HERE / "二建玉の清算側経路.png", dpi=135)
    plt.close(fig)


def viewer(trades: dict, api: str | None) -> None:
    """
    機能：当日のRC20とK08を既存変換器で全約定片に変換し、指定時は配布版APIの読み込みを検算する。
    引数：trades（dict）は候補別当日全建玉、api（strまたはNone）はローカルViewerのURL。
    返り値：None。閲覧一覧と候補別約定、API指定時は金額と残数の照合結果をViewerに保存する。
    """
    load = runpy.run_path(str(next(STUDY.glob("00217*/Viewer/約定を出力する.py"))))["load"]
    converter = load("00215")
    converter.SCENE = DAY
    audit = load("00216")
    directory = HERE / "Viewer"
    directory.mkdir(exist_ok=True)
    market = ROOT.parent / "JP_OSE_Data/future/NK225" / DAY
    raw = next(p for p in (market / "book.jsonl.gz", market / "book.jsonl") if p.is_file())
    path = directory / "一覧.resources.json"
    catalog = {"schema_version": 1, "path_base": "catalog", "base_dir": str(directory), "resources": []}
    fragments = {}
    for key, rows in trades.items():
        fragments[key] = converter.fills(rows, key, 100, 538.5, 0, 1)
        file = directory / (key + ".trades.jsonl")
        file.write_text("".join(json.dumps(p, ensure_ascii=False) + "\n" for p in fragments[key]), encoding="utf8")
        catalog["resources"].append({"id": key, "title": "10月8日 " + key, "method_id": key, "symbol": "NK225",
                                     "product": "NK225mini", "session": DAY, "point_value": 100, "pnl_format": "trades",
                                     "pnl_basis": "net", "market_path": str(raw), "pnl_path": file.name})
    path.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf8")
    if api:
        proof = {key: audit.verify(api, path, key, fragments[key], rows) for key, rows in trades.items()}
        (directory / "配布版での検算.json").write_text(json.dumps(proof, ensure_ascii=False, indent=2) + "\n", encoding="utf8")


def main() -> None:
    """
    機能：10月8日の二件を原行・当時特徴・予約状態に突合し、既存出口と損失だけの日を集計する。
    引数：任意の --api（str）は配布版ViewerのURL。199・219・222・224・227・228の元帳等を読む。
    返り値：None。図を本試行、機械検算値をwork/228十月八日へ保存する。
    """
    parser = ArgumentParser()
    parser.add_argument("--api")
    args = parser.parse_args()
    rc = book("224反対追試", "RC20")
    trades = [t for t in rc if t["scene"] == DAY]
    boundary = runpy.run_path(str(next(STUDY.glob("00222*/建玉制限を再生する.py"))))
    engine, source = boundary["ENGINE"], boundary["SOURCE"]
    folder, archive, member, manifest = source["parts"]()[0]
    scenes, arrays, features, columns, _ = source["inputs"](folder, archive, member)
    number, scene = next((i, s) for i, s in enumerate(scenes) if s["session"] == DAY)
    spec = next(s for s in source["read"](manifest)["scenes"] if s["session"] == DAY)
    index = engine["FINANCE"]["load_scene"](manifest.parent, spec)
    keys, captures, a = boundary["after_open"](engine["orders"](arrays, number, scene, index), scene["start"] + 1200)
    by_entry = {t["entry_index"]: t for t in trades}

    def settle(event: int, entry: int, side: int, width: int) -> float:
        """
        機能：この日の元帳と取得・側・幅・決済時計を照合し、一枚枠を解放する。
        引数：event・entry・side・width（int）は要求行、取得板位置、売買側、IFD幅。
        返り値：float。決済が確定した秒。
        """
        trade = by_entry[entry]
        assert (keys[event][2], side, width) == (trade["request_line"], trade["side"], trade["width"])
        return trade["exit_time"]

    replay = engine["FINANCE"]["engine173"].replay(
        keys, np.zeros(len(keys), int), np.array([scene["start"]]), np.array([scene["end"] - 900]),
        captures, *(a[k] for k in ("core", "branches", "technical", "tier", "mw", "fw")), 200, settle)
    assert len(replay["records"]) == len(trades) == 2 and not any(t["activated"] for t in trades)
    # ----------------------------------------
    diagnostic = json.loads(gzip.decompress(next(WORK.glob("199*/旧73_純成立診断.json.gz")).read_bytes()))
    result = {"建玉": [], "予約": [], "他出口": {}, "損失のみの日": {}}
    measures = ("m5_hist_delta_to_side", "m5_rsi_delta_to_side", "m5_ema21_delta_to_side", "m5_di_difference_to_side",
                "m15_ema21_delta_to_side", "m30_ema21_delta_to_side", "q0_entry_prior3_percent_to_side",
                "m5_tr_atr_ratio", "m5_tr_previous_atr_ratio", "m5_close_position_to_side", "m1_volume_relative_prior3")
    for tr in trades:
        event, = np.flatnonzero((arrays["scene"] == number) & (arrays["line"] == tr["request_line"]))
        assert tr["side"] == tr["branch"] == tr["origin"] == 0 and not tr["added"]
        base = diagnostic["E199_00"]
        assert base["bo_setup"][event] and not base["mp_setup"][event] and not base["bo_confirmed"][event]
        assert not any(diagnostic["E199_02"][k][event] for k in ("guarded", "reverse_confirmed", "follow_confirmed"))
        val = {k: round(float(features["buy"][event, columns.index(k)]), 4) for k in measures}
        assert val["m5_di_difference_to_side"] > 0 and features["sell"][event, columns.index("m5_di_difference_to_side")] < 0
        rows = index.normal[(index.normal >= tr["entry_index"]) & (index.normal <= tr["exit_index"])]
        marks = (index.rows["bid"][rows] - tr["entry_price"]) * 100 - 1077
        times = index.times[rows]
        peak = int(marks.argmax())
        assert marks[peak] == tr["max_unrealized_net"] and marks.min() == tr["min_unrealized_net"]
        assert times[peak] == tr["max_unrealized_time"] and times[marks.argmin()] == tr["min_unrealized_time"]
        assert marks[-1] == tr["net"]
        crossed = np.flatnonzero(marks[peak:] <= 0)
        r = {"入口": clock(tr["entry_time"]), "入口価格": tr["entry_price"], "最初の黒字": clock(times[np.flatnonzero(marks > 0)[0]]),
             "最有利価格": index.rows["bid"][rows[peak]].item(), "最有利時刻": clock(times[peak]),
             "最悪価格": index.rows["bid"][rows[marks.argmin()]].item(), "最悪時刻": clock(times[marks.argmin()]),
             "最高含み益": marks[peak].item(), "ピーク後に再度費用後ゼロ以下": clock(times[peak + crossed[0]]),
             "決済": clock(tr["exit_time"]), "費用後": tr["net"], "当時特徴": {k: v if np.isfinite(v) else None for k,v in val.items()}}
        result["建玉"].append(r)
    for req in replay["requests"]:
        t = req["at"][0]
        owner = next((j for j,p in enumerate(trades, start=1) if p["entry_time"] <= t <= p["exit_time"]), 0)
        result["予約"].append([clock(t), "買" if req["side"] == 0 else "売", req["skip_reason"] or "受理", owner])
    result["予約監査"] = replay["audits"][0]
    for path, tag in (("222境界照合", "I20"), ("224反対追試", "RC20"), ("227確定足転換", "W12C20"),
                      ("227弱反転", "W01C20"), ("227弱反転", "W08C20"), ("227出来高", "D01C20"),
                      ("227出来高", "D05C20"), ("227停滞", "Z05C20"), ("228出口", "K08C20")):
        account = book(path, tag)
        day_trades = [t for t in account if t["scene"] == DAY]
        assert [(t["entry_line"], t["side"], t["entry_price"]) for t in day_trades] == [
            (t["entry_line"], t["side"], t["entry_price"]) for t in trades]
        result["他出口"][tag] = {"当日": [[clock(t["exit_time"]), t["net"]] for t in day_trades],
                               "全45日": sum(t["net"] for t in account)}
    for date in sorted({t["scene"] for t in rc}):
        day = [t for t in rc if t["scene"] == date]
        if all(t["net"] <= 0 for t in day) and any(t["net"] < 0 for t in day):
            result["損失のみの日"][date] = [[t["net"], t["max_unrealized_net"], t["exit_reason"]] for t in day]
    out = WORK / "228十月八日"
    out.mkdir(exist_ok=True)
    (out / "原行と照合した値.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf8")
    alternate = [t for t in book("228出口", "K08C20") if t["scene"] == DAY]
    assert trades[0]["exit_line"] == alternate[0]["exit_line"] and trades[1]["exit_time"] > alternate[1]["exit_time"]
    draw(index, trades, scene, alternate[1])
    viewer({"RC20": trades, "K08": alternate}, args.api)


if __name__ == "__main__":
    main()
