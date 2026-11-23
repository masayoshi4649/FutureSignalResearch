"""元IFDと主要な出口候補の累計と、その時点までの最高残高からの下落を描く。"""
import csv
from pathlib import Path
import json

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.font_manager import FontProperties
import numpy as np


def main() -> None:
    """
    機能：同じ45デイの費用後収支と日末ドローダウンを比較できる図を作る。
    引数：なし。試行内の表示設定と公開先の候補別CSVを読む。
    返り値：None。研究フォルダへPNGを出力する。
    """
    here = Path(__file__).resolve().parent
    folder = next((here.parents[1]/"outputs").glob("00219_*"))
    names = json.loads((here/"閲覧候補.json").read_bytes())
    shown = json.loads((here/"グラフ表示.json").read_bytes())
    jp = Path("C:/Windows/Fonts/meiryo.ttc")
    plt.rcParams["font.family"] = FontProperties(fname=jp).get_name() if jp.exists() else "Noto Sans CJK JP"
    fig, (ax, dd) = plt.subplots(2, 1, figsize=(9.7,6.7), sharex=True, height_ratios=[2,1])
    colors = ["#475569","#00725d","#ad4a0b","#8049a0"]
    dates = None
    for code, color in zip(shown, colors):
        with (folder/("219_"+names[code])/"デイ.csv").open(encoding="utf-8-sig",newline="") as stream:
            rows = list(csv.DictReader(stream))
        current = [r["セッション"][:10] for r in rows]
        if dates is None:
            dates = current
        assert dates==current and len(current)==45
        y = np.r_[0,np.cumsum([float(r["既知収支円"])/10000 for r in rows])]
        style = "--" if code=="IFD" else "-"
        label = names[code] + ("（未知あり）" if sum(int(r["未知件数"]) for r in rows) else "")
        ax.plot(y, style, color=color, label=label, lw=1.9)
        dd.plot(y-np.maximum.accumulate(y),style,color=color,lw=1.45)
    for a in (ax, dd):
        a.axvspan(24.5,45.0,color="#edf4f1",zorder=0)
        a.axhline(0,color="#83948c",lw=.65)
        a.grid(axis="y",color="#d9dedd",lw=.6)
        a.spines[["right","top"]].set_visible(False)
        a.set_xlim(0,45)
    ax.set_ylabel("累計収支（万円）")
    dd.set_ylabel("日末下落額（万円）")
    ticks = [1,6,11,16,22,26,31,36,41,45]
    dd.set_xticks(ticks,[dates[i-1][5:].replace("-","/") for i in ticks])
    ax.legend(loc="upper left",frameon=False,ncol=2,fontsize=9)
    fig.suptitle("日経199_02　出口を変更した口座の45デイ",x=.105,ha="left",fontsize=16)
    fig.text(.105,.90,"mini 1枚、費用後。薄緑は10月23日以降の後半21日。確定した取引の損益を累計。")
    fig.subplots_adjust(left=.105,right=.96,top=.84,bottom=.085,hspace=.23)
    fig.savefig(here/"出口別の累計と下落.png",dpi=130)
    plt.close(fig)


if __name__=="__main__":
    main()
