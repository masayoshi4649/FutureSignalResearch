"""固定手法とデイ入口候補の各45日累計を、公開用の手法別CSVから描く。"""
import csv
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.font_manager import FontProperties
from matplotlib.ticker import MaxNLocator

HERE = Path(__file__).resolve().parent
OUTPUTS = HERE.parents[1] / "outputs"
OLD = next(OUTPUTS.glob("00216_*"))
NEW = next(OUTPUTS.glob("00217_*"))
PAIRS = [
    ("日経225mini", "199_02", "NK10", "216_日経199_02", "217_日経NK10"),
    ("日経の通知でミニTOPIX", "固定通知", "通知03", "216_日経通知でTOPIX", "217_日経通知03でTOPIX"),
    ("ミニTOPIX自身の判断", "212_06", "T26", "216_TOPIX専用212デイ", "217_TOPIX専用T26"),
]


def series(folder: Path) -> tuple:
    """
    機能：手法別CSVを読み、日付と日末の既知累計を取り出す。
    引数：folder（Path）は1口座の出力先。
    返り値：tuple。日付列と万円単位の累計列。
    """
    with (folder / "デイ.csv").open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    return [r["セッション"][:10] for r in rows], [float(r["既知累計円"])/10000 for r in rows]


def main() -> None:
    """
    機能：原点をそろえた商品別の累計曲線に、10月20日と前後期間の境界を示す。
    引数：なし。日本語フォントを備えた環境を使う。
    返り値：None。試行フォルダに閲覧用PNGを保存する。
    """
    font = Path("C:/Windows/Fonts/meiryo.ttc")
    if font.exists():
        plt.rcParams["font.family"] = FontProperties(fname=font).get_name()
    else:
        plt.rcParams["font.family"] = ["Noto Sans CJK JP", "sans-serif"]
    plt.rcParams.update({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False})
    fig, axes = plt.subplots(3, 1, figsize=(9.4, 7.7), sharex=True)
    for ax, (title, original, candidate, previous, current) in zip(axes, PAIRS, strict=True):
        dates, b = series(OLD / previous)
        d, c = series(NEW / current)
        assert dates == d and len(dates) == 45
        x = range(46)
        ax.axhline(0, color="#939ba5", lw=.75)
        ax.axvline(dates.index("2026-10-20")+1, color="#a96f29", ls=":", lw=1.4)
        ax.axvspan(24.5, 45, color="#edf3f1", zorder=0)
        ax.plot(x, [0, *b], label=original, color="#596776", ls="--", lw=1.6)
        ax.plot(x, [0, *c], label=candidate, color="#00745f", lw=2.2)
        ax.legend(loc="upper left", frameon=False, ncol=2)
        ax.set_title(title, loc="left", fontsize=12)
        ax.set_ylabel("万円")
        ax.yaxis.set_major_locator(MaxNLocator(5))
        ax.grid(axis="y", color="#d8dfdf", lw=.6)
    ticks = [1, 6, 11, 16, 22, 26, 31, 36, 41, 45]
    axes[-1].set_xticks(ticks, [dates[i-1][5:].replace("-", "/") for i in ticks])
    axes[-1].set_xlim(0, 45)
    fig.suptitle("デイ45日の費用後累計収支", x=.09, ha="left", fontsize=17)
    fig.text(.09, .921, "点線の縦線は10月20日。薄緑は10月23日からの後半21日。各図の縦軸は異なる。")
    fig.text(.09, .018, "日経の通知で取引する両口座は10月12日の1建玉が損益不明。曲線は確定した建玉だけの累計。", fontsize=9)
    fig.subplots_adjust(left=.09, right=.975, top=.86, bottom=.08, hspace=.52)
    fig.savefig(HERE / "デイ45日の累計収支.png", dpi=130)
    plt.close(fig)


if __name__ == "__main__":
    main()
