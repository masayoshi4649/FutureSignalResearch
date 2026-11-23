"""日経199_02の建玉を、日付・時間・方向・費用後の勝敗で図示する。"""
import csv
from datetime import datetime
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.font_manager import FontProperties


def main() -> None:
    """
    機能：全181件の新規約定の日本時間と最終損益の符号を方向別に描画する。
    引数：なし。試行218の日別CSVと建玉明細CSVを使用する。
    返り値：None。試行フォルダにPNGを保存する。
    """
    folder = Path(__file__).resolve().parent
    output = next((folder.parents[1]/"outputs").glob("00218_*"))/"218_日経199_02"
    with (output/"日別.csv").open(encoding="utf-8-sig", newline="") as stream:
        dates = [r["セッション日JST"] for r in csv.DictReader(stream)]
    with (output/"建玉明細.csv").open(encoding="utf-8-sig", newline="") as stream:
        trades = list(csv.DictReader(stream))
    assert len(trades) == 181 and len(dates) == 45
    days = {d: i for i,d in enumerate(dates)}
    japanese = Path("C:/Windows/Fonts/meiryo.ttc")
    plt.rcParams["font.family"] = FontProperties(fname=japanese).get_name() if japanese.exists() else "Noto Sans CJK JP"
    fig, panels = plt.subplots(2, 1, figsize=(10.7, 6.1), sharex=True)
    for ax, side in zip(panels, ("買い", "売り"), strict=True):
        subset = [r for r in trades if r["売買方向"] == side]
        for win, color, marker in ((True, "#137663", "o"), (False, "#b04821", "x")):
            selected = [datetime.fromisoformat(r["新規日時JST"]) for r in subset if (float(r["費用後損益円"]) > 0) == win]
            ax.scatter([days[t.date().isoformat()] for t in selected],
                       [t.hour*60+t.minute+t.second/60 for t in selected],
                       s=24 if win else 32, c=color, marker=marker, linewidths=1.1,
                       label="黒字" if win else "赤字", zorder=2)
        ax.set_title(f"{side}建て　{len(subset)}件", loc="left", fontsize=12)
        ax.axvline(days["2026-10-20"], color="#735683", linestyle=":", lw=1)
        ax.axvspan(23.5, 44.5, color="#f2f4f5", zorder=0)
        ax.set_yticks([525, 600, 690, 750, 840, 930], ["08:45", "10:00", "11:30", "12:30", "14:00", "15:30"])
        ax.set_ylim(935, 520)
        ax.grid(axis="y", color="#d8e0df", lw=.6)
        ax.spines[["top", "right"]].set_visible(False)
    panels[0].legend(loc="upper right", bbox_to_anchor=(1.0, 1.26), ncol=2, frameon=False)
    ticks = [0, 5, 10, 15, days["2026-10-20"], 25, 30, 35, 40, 44]
    panels[-1].set_xticks(ticks, [dates[i][5:].replace("-", "/") for i in ticks])
    panels[-1].set_xlim(-.6, 44.6)
    fig.suptitle("日経199_02　どの日の何時に建てたか", x=.085, ha="left", fontsize=16)
    fig.text(.085, .90, "各点は日経225mini 1枚の新規約定時刻（日本時間）。色と記号は費用後の決済結果。")
    fig.text(.085, .017, "縦の点線は10月20日。薄い背景は10月23日以降の後半21デイ。")
    fig.subplots_adjust(left=.085, right=.982, top=.80, bottom=.091, hspace=.43)
    fig.savefig(folder/"全建玉の日時.png", dpi=130)
    plt.close(fig)


if __name__ == "__main__":
    main()
