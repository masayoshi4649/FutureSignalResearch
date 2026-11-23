"""二つの同一建玉について、返済側気配と起動後の保護価格を元の板から描く。"""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import runpy

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.font_manager import FontProperties
from matplotlib.ticker import FuncFormatter
import numpy as np

HERE = Path(__file__).resolve().parent
OLD = next(HERE.parent.glob("00219_*"))
ROOT = HERE.parents[1]
JST = timezone(timedelta(hours=9))


def draw(ax, trade: dict, old: dict, index, strategy: dict) -> None:
    """
    機能：決済までの気配と建値・損切・利確・保護床を描き、実際の再生元帳と照合する。
    引数：ax（Axes）は描画先、trade・old（dict）は同一取得の新旧建玉、index（PriceIndex）は正常板索引、
    strategy（dict）は完成足の失速・収縮を計算する共通条件。
    返り値：None。描画先へ原板の価格を追加する。
    """
    entry, trigger, close = (int(trade[k]) for k in ("entry_index","trigger_index","exit_index"))
    assert entry==old["entry_index"] and close<=old["exit_index"]
    ids = index.normal[(index.normal>=entry) & (index.normal<=old["exit_index"])]
    buy = trade["side"]==0
    sign = 1 if buy else -1
    mark = index.rows["bid" if buy else "ask"][ids]
    t = index.times[ids]
    start = datetime.fromtimestamp(t[0],JST).replace(hour=8,minute=45,second=0).timestamp()
    features = strategy["prepare"](index,{"start":start,"end":start+7*3600})
    width, paid = trade["width"],trade["entry_price"]
    deadline = min(t[0]+int(trade["horizon"][1:])*60,features["deadline"])
    active_ids = (ids>entry) & (ids<=trigger)
    active_t = t[active_ids]
    move = sign*(mark[active_ids]-paid)
    peak = np.maximum.accumulate(move)
    late = deadline-active_t<=600
    active = np.logical_or.accumulate((move>=.85*width) | (late & (move>=.45*width)))
    tight = late & features["squeeze"][trade["side"],features["bar"][ids[active_ids]]]
    floor = np.maximum.reduce((np.full(len(move),20.),peak-.8*width,np.where(tight,peak-.35*width,0.)))
    floor = np.maximum.accumulate(np.where(active,floor,-np.inf))
    assert active_t[np.flatnonzero(active)[0]]==trade["activation_time"]
    assert abs(floor[-1]-trade["floor_points"])<1e-6
    # ----------------------------------------
    held = ids<=close
    ax.plot(t[held],mark[held],color="#164960",lw=.85,label="保有中の返済側気配")
    ax.plot(t[ids>=close],mark[ids>=close],color="#869394",lw=.85,alpha=.8,label="元IFDの保有継続中")
    ax.hlines(paid,t[0],t[-1],color="#585e65",lw=.8,ls=":",label="建値")
    ax.hlines(paid-sign*trade["initial_stop_points"],t[0],trade["exit_time"],color="#ac4337",lw=1.3,ls="--",label="初期損切")
    ax.hlines(paid+sign*trade["target_points"],t[0],trade["exit_time"],color="#23745b",lw=1.3,ls="--",label="固定利確")
    ax.step(active_t[active],paid+sign*floor[active],where="post",color="#ba6200",lw=2,label="起動後の保護価格")
    ax.scatter([trade["exit_time"],old["exit_time"]],[trade["exit_price"],old["exit_price"]],color=["#ba6200","#535f65"],s=26,zorder=5)
    ax.xaxis.set_major_formatter(FuncFormatter(lambda value, _:datetime.fromtimestamp(value,JST).strftime("%H:%M")))
    ax.yaxis.set_major_formatter(FuncFormatter(lambda value, _:f"{value:,.0f}"))
    ax.set_xlim(t[0]-60,t[-1]+60)
    ax.grid(axis="y",lw=.5,alpha=.3)
    ax.spines[["top","right"]].set_visible(False)
    ax.set_ylabel("指数価格")
    ax.set_title(f"{trade['scene'][5:10].replace('-','/')}　{'買い' if buy else '売り'}　建値 {paid:,.0f}　｜　併用 {trade['net']:+,.0f}円　元IFD {old['net']:+,.0f}円",loc="left",fontsize=12)


def main() -> None:
    """
    機能：保護で損失を防いだ売りと、後の利益を小さくした買いを同じ表現で比較する。
    引数：なし。220ポイントのB400P3元帳と219が使用した原板索引を読む。
    返り値：None。試行フォルダにPNGを保存する。
    """
    books = json.loads((ROOT/"work/220ポイント/比較元帳.json").read_bytes())["口座再生"]
    engine = runpy.run_path(str(OLD/"口座再生.py"))
    trace = runpy.run_path(str(OLD/"経路診断/元の保有経路を測る.py"))
    strategy = runpy.run_path(str(HERE/"主比較/出口条件.py"))
    archives = trace["archives"]()
    jp = Path("C:/Windows/Fonts/meiryo.ttc")
    plt.rcParams["font.family"] = FontProperties(fname=jp).get_name() if jp.exists() else "Noto Sans CJK JP"
    fig,axes = plt.subplots(2,1,figsize=(9.4,7.1))
    for ax,scene,price in zip(axes,["2026-11-20_Day","2026-10-05_Day"],[56840,69790],strict=True):
        trade, = [t for t in books["B400P3"] if t["scene"]==scene and t["entry_price"]==price and t["exit_reason"]=="利益保護"]
        old, = [t for t in books["IFD"] if t["scene"]==scene and t["entry_index"]==trade["entry_index"]]
        index = engine["FINANCE"]["early179"].PriceIndex(trace["load_records"](*archives[scene]))
        draw(ax,trade,old,index,strategy)
    fig.suptitle("日経199_02　利確指値を残したまま追尾で返済した2建玉",x=.11,ha="left",fontsize=16)
    fig.legend(*axes[0].get_legend_handles_labels(),loc="lower center",ncols=3,frameon=False)
    fig.subplots_adjust(left=.11,right=.97,top=.87,bottom=.17,hspace=.48)
    fig.savefig(HERE/"利益保護と板の動き.png",dpi=135)
    plt.close(fig)


if __name__=="__main__":
    main()
