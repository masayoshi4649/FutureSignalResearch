"""5分足と実際の新規、当時公表EMAを同じ時刻軸に描く。"""
import csv
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "work/11月06日のテクニカル診断"
TZ = timezone(timedelta(hours=9))
plt.rcParams["font.family"] = "Yu Gothic"
plt.rcParams["axes.unicode_minus"] = False


def main():
    """
    機能: 共有5分OHLCと保存実新規、公表EMAを2場の静止図へ描く。
    引数: なし。調べる.pyの検算済みJSONを参照。
    返り値: なし。図は金融再検証や売買ルール検証を意味しない。
    """
    d = json.loads((OUT / "当時公開値と実新規.json").read_text(encoding="utf-8"))
    fig, axes = plt.subplots(2, 1, figsize=(16, 10), layout="constrained")
    for ax, s in zip(axes, d["scenes"]):
        path = ROOT.parent / f"JP_OSE_Data/future/NK225/{s['session']}/candle_5min.csv"
        with path.open(encoding="utf-8-sig", newline="") as f:
            bars = list(csv.DictReader(f))
        for b in bars:
            x = mdates.date2num(datetime.fromisoformat(b["time"])) + 2.5 / 1440
            o, h, l, c = (float(b[k]) for k in ("open", "high", "low", "close"))
            color = "#bd6868" if c >= o else "#5f8b84"
            ax.vlines(x, l, h, color=color, linewidth=0.65)
            ax.add_patch(Rectangle((x - 1.7 / 1440, min(o, c)), 3.4 / 1440, max(1, abs(c - o)), facecolor=color, alpha=0.65, linewidth=0))
        gs = [g for g in s["公開チャート"] if g["Technical"]["trend_known"]]
        for k, label, color, ls in (("ema8_3", "確定3分 EMA8", "#b38630", "-"), ("ema21_3", "確定3分 EMA21", "#6e69a8", "-"),
                                    ("ema8_15", "確定15分 EMA8", "#b38630", "--"), ("ema21_15", "確定15分 EMA21", "#6e69a8", "--")):
            ax.plot([mdates.date2num(datetime.fromtimestamp(g["at"], TZ)) for g in gs], [g["Technical"][k] for g in gs], label=label, color=color, ls=ls, linewidth=1, alpha=0.8)
        for side, color, marker in (("買", "#bd2d31", "^"), ("売", "#116b60", "v")):
            es = [e for e in s["books"]["B0_C0_D0"]["entries"] if e["方向"] == side]
            grouped = {}
            for e in es:
                ident = (e["新規"], e["新規価格"])
                if ident not in grouped:
                    grouped[ident] = dict(e)
                    grouped[ident]["数量"] = 0
                grouped[ident]["数量"] += e["数量"]
            es = list(grouped.values())
            ax.scatter([datetime.fromisoformat(e["新規"]) for e in es], [e["新規価格"] for e in es], s=[30+12*e["数量"] for e in es],
                       marker=marker, color=color, edgecolors="white", linewidths=.5, zorder=5, label=f"実{side}新規（大きさ＝枚数）")
            for i, e in enumerate(es):
                ax.annotate(f"{e['新規'][11:16]} {e['数量']}枚", (mdates.date2num(datetime.fromisoformat(e["新規"])), e["新規価格"]),
                            xytext=(0, 12 if side == "買" else -17), textcoords="offset points", fontsize=7, ha="center", color=color)
        title = f"2026/11/06 {'デイ' if s['session'].endswith('Day') else 'ナイト'}  B0/C0D0  費用後実現 {s['books']['B0_C0_D0']['totals']['net_yen']:+,}円"
        ax.set_title(title, fontsize=12, loc="left")
        ax.set_ylabel("NK225 指数pt")
        lo = min(float(b["low"]) for b in bars)
        hi = max(float(b["high"]) for b in bars)
        hi = max(hi, max(g["Technical"]["ema21_15"] for g in gs))
        ax.set_ylim(lo - 70, hi + 70)
        ax.set_xlim(datetime.fromisoformat(bars[0]["time"]) - timedelta(minutes=5), datetime.fromisoformat(bars[-1]["time"]) + timedelta(minutes=10))
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M", tz=TZ))
        ax.xaxis.set_major_locator(mdates.HourLocator(interval=1, tz=TZ))
        ax.grid(alpha=.16)
        ax.legend(loc="upper left", ncols=3, fontsize=8)
    fig.suptitle("5分足と実際の新規／EMAは判断時点で公表済みの値。全体図は事後の見え方であり、将来情報を入口に使えない。", fontsize=11)
    fig.savefig(OUT / "11月06日の価格と実新規.png", dpi=150)


if __name__ == "__main__":
    main()
