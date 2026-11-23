"""正常な中値の場内経路をRC20の実現損益に対応付けて日ごとの偏りを測る。"""
import csv
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from statistics import median
import runpy

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
LAST = runpy.run_path(str(next((ROOT/"study").glob("00224_*/再エントリーを再生する.py"))))
JST = timezone(timedelta(hours=9))
LABEL = "228:RC20_日別の形"
WORK = ROOT/"work/228日別の形"


def read(path: Path) -> list:
    """
    機能：正式CSVの全行を列名で参照できるように読み出す。
    引数：path（Path）はCSVの位置。返り値：list[dict]。文字列の行。
    """
    with path.open(encoding="utf-8-sig",newline="") as stream:
        return list(csv.DictReader(stream))


def shape(day: str, index: object) -> dict:
    """
    機能：売買可能窓の正常気配からOHLC、方向効率、前後反転、中心に近づく回数を測る。
    引数：day（str）はデイ名、index（PriceIndex）は照合済み原板索引。
    返り値：dict。中値の形状と利用できた時点数。欠測で判定できない量はNone。
    """
    start = datetime.fromisoformat(day[:10]+"T09:05:00").replace(tzinfo=JST).timestamp()
    duration = 384
    n = index.normal
    window = (index.times[n]>=start) & (index.times[n]<start+60*duration)
    ids = n[window]
    times = index.times[ids]
    assert len(times)>0 and np.all(index.rows["ask"][ids]>index.rows["bid"][ids])
    prices = (index.rows["ask"][ids]+index.rows["bid"][ids])/2
    op,cl,high,low = map(float,(prices[0],prices[-1],prices.max(),prices.min()))
    span,delta = high-low,cl-op
    minute = ((times-start)//60).astype(int)
    close = np.full(duration,np.nan)
    last_minute = np.r_[minute[1:]!=minute[:-1],True]
    close[minute[last_minute]] = prices[last_minute]
    path = [op]
    for i in range(0,duration,5):
        bar = close[i:i+5]
        valid = bar[np.isfinite(bar)]
        path.append(float(valid[-1]) if len(valid) else np.nan)
    distance = np.abs(np.diff(path)).sum()
    eff = abs(delta)/distance if np.isfinite(distance) and distance>0 else None
    # ----------------------------------------
    middle = np.searchsorted(times,start+190*60)-1
    assert middle>=0
    morning = float(prices[middle]-op)
    after = delta-morning
    flip = "その他"
    if morning*after<0 and min(abs(morning),abs(after))>=span/4:
        flip = "上昇後下落" if morning>0 else "下落後上昇"
    trials,returned = 0,0
    for t in range(30,duration-15+1,15):
        hist = close[t-30:t]
        final = close[t+15-1]
        if not np.isfinite(hist).all() or not np.isfinite(final):
            continue
        center = float(hist.mean())
        departure = abs(hist[-1]-center)
        if departure<max(10,np.ptp(hist)/4):
            continue
        trials += 1
        returned += int(abs(final-center)<departure)
    ratio = returned/trials if trials>=5 else None
    extent = abs(delta)/span if span else 0.
    first = datetime.fromtimestamp(times[0],JST).strftime("%H:%M:%S")
    last = datetime.fromtimestamp(times[-1],JST).strftime("%H:%M:%S")
    return {"最初の正常気配":first,"最後の正常気配":last,"正常気配のある分数":int(np.isfinite(close).sum()),
            "始値pt":op,"高値pt":high,"安値pt":low,"終値pt":cl,"始終差pt":delta,"始終変化％":100*delta/op,
            "値幅pt":span,"値幅％":100*span/op,"方向":"上昇" if delta>0 else "下落" if delta<0 else "同値",
            "始終差絶対値pt":abs(delta),"片道比":extent,"片道区分":"往復" if extent<=1/3 else "片道" if extent>=2/3 else "中間",
            "5分効率":eff,"12時15分までpt":morning,"12時15分以後pt":after,"切返し":flip,
            "距離縮小機会":trials,"距離縮小件数":returned,"中心回帰率":ratio,
            "中心回帰区分":"不足" if ratio is None else "高" if ratio>=.60 else "低" if ratio<=.40 else "中"}


def sums(trades: list) -> tuple:
    """
    機能：実売買の各収支を両側の価格と費用で検算して黒字額と赤字額を分ける。
    引数：trades（list[dict]）は任意の取得群。返り値：tuple[int,int,int]。総利益、総損失、収支。
    """
    pos,neg = 0,0
    for t in trades:
        signed = (float(t["決済値pt"])-float(t["建値pt"]))*(100 if t["方向"]=="買い" else -100)-1077
        assert signed==float(t["費用後収支円"])
        pos += int(max(0,signed))
        neg += int(max(0,-signed))
    return pos,neg,pos-neg


def grouped(rows: list) -> dict:
    """
    機能：分類内の日数・分布・売買別3金額・発生日当たりの額・期間別寄与を求める。
    引数：rows（list[dict]）は同じ区分に属するデイ。返り値：dict。分母付き集計。
    """
    daily = [r["収支円"] for r in rows]
    res = {"日数":len(rows),"黒字日":sum(v>0 for v in daily),"赤字日":sum(v<0 for v in daily),
           "利益ゼロ日":sum(r["利益円"]==0 for r in rows),"建玉回数":sum(r["建玉回数"] for r in rows),
           "日収支中央値円":median(daily),"日平均収支円":sum(daily)/len(rows),
           "建玉中央値円":median([v for r in rows for v in r["_各収支"]]),"最大黒字日除外収支円":sum(daily)-max(0,max(daily)),
           "前24日数":sum(r["期間"]=="前24" for r in rows),"後21日数":sum(r["期間"]=="後21" for r in rows)}
    for key in ("利益円","損失円","収支円","買い回数","買い利益円","買い損失円","買い収支円",
                "売り回数","売り利益円","売り損失円","売り収支円"):
        res[key] = sum(r[key] for r in rows)
    for period in ("前24","後21"):
        res[period+"収支円"] = sum(r["収支円"] for r in rows if r["期間"]==period)
    widths = [w for r in rows for w in r["_注文幅"]]
    res.update(黒字上位3日除外収支円=sum(daily)-sum(sorted((v for v in daily if v>0),reverse=True)[:3]),
               建玉平均収支円=sum(daily)/res["建玉回数"],値幅中央値pt=median(r["値幅pt"] for r in rows),
               当初片幅中央値pt=median(widths),
               注文幅対日値幅中央値=median(w/r["値幅pt"] for r in rows for w in r["_注文幅"] if r["値幅pt"]>0))
    for width in (150,200,350,400):
        res[f"当初片幅{width}pt件数"] = widths.count(width)
    return res


def main() -> None:
    """
    機能：全45日を同じ方法で評価し、気配範囲・RC20の日別照合、分類・順位相関を保存する。
    引数：なし。返り値：None。作業領域に候補別CSV用入力と診断JSONを出力する。
    """
    folder = next((ROOT/"outputs").glob("00224*/224_RC20*"))
    daily = {r["セッション"]:r for r in read(folder/"デイ.csv")}
    trades = read(folder/"建玉明細.csv")
    dates = sorted(daily)
    lookup = {}
    for _,_,_,manifest in LAST["SOURCE"]["parts"]():
        for m in LAST["SOURCE"]["read"](manifest)["scenes"]:
            lookup.setdefault(m["session"],(manifest.parent,m))
    # ----------------------------------------
    rows = []
    for number,day in enumerate(dates):
        prices = LAST["ENGINE"]["FINANCE"]["load_scene"](*lookup[day])
        row = {"セッション":day,"期間":"前24" if number<24 else "後21",**shape(day,prices)}
        todays = [t for t in trades if t["セッション"]==day]
        for side in ("","買い","売り"):
            part = [t for t in todays if not side or t["方向"]==side]
            row[side+"回数" if side else "建玉回数"] = len(part)
            for k,v in zip(("利益円","損失円","収支円"),sums(part),strict=True):
                row[side+k] = v
        assert tuple(row[k] for k in ("利益円","損失円","収支円","建玉回数"))==tuple(
            int(daily[day][k]) for k in ("既知利益円","既知損失円","確定収支円","建玉回数"))
        row["保有時間率"] = float(daily[day]["既知保有時間率"])
        row["_各収支"] = [int(t["費用後収支円"]) for t in todays]
        row["_注文幅"] = [int(t["IFD片幅pt"]) for t in todays]
        row["当初片幅中央値pt"] = median(row["_注文幅"])
        row["損益別"] = "黒字" if row["収支円"]>0 else "赤字" if row["収支円"]<0 else "同値"
        rows.append(row)
    assert len(rows)==45 and sum(r["建玉回数"] for r in rows)==133
    for key,label in (("値幅％","値幅区分"),("5分効率","効率区分")):
        available = sorted((r for r in rows if r[key] is not None),key=lambda r:(r[key],r["セッション"]))
        for r in rows:
            r[label] = "不足"
        for i,r in enumerate(available):
            r[label] = ("小","中","大")[i*3//len(available)]
    for r in rows:
        r["方向と片道"] = r["方向"]+"・"+r["片道区分"]
    keys = ("方向","片道区分","効率区分","中心回帰区分","切返し","値幅区分","方向と片道","期間","損益別")
    groups = [{"尺度":"全体","区分":"全45日",**grouped(rows)}]
    for key in keys:
        for label in sorted({r[key] for r in rows}):
            groups.append({"尺度":key,"区分":label,**grouped([r for r in rows if r[key]==label])})
    # ----------------------------------------
    ranks = {}
    for key in ("始終変化％","始終差絶対値pt","値幅％","片道比","5分効率","中心回帰率"):
        subset = [r for r in rows if r[key] is not None]
        values = []
        for field in (key,"収支円"):
            x = np.array([r[field] for r in subset])
            values.append([np.sum(x<v)+.5*(1+np.sum(x==v)) for v in x])
        ranks[key] = [len(subset),float(np.corrcoef(*values)[0,1])]
    columns = [k for k in rows[0] if not k.startswith("_")]
    tables = {"候補比較":{"headers":["候補",*groups[0]],"rows":[[LABEL,*g.values()] for g in groups]},
              "形と損益":{"headers":["候補",*columns],"rows":[[LABEL,*[r[k] for k in columns]] for r in rows]}}
    WORK.mkdir(parents=True,exist_ok=True)
    data = {"tableNames":{"候補比較":"集計","形と損益":"日別の形と損益"},"tables":tables}
    (WORK/"CSV入力.json").write_text(json.dumps(data,ensure_ascii=False,allow_nan=False),encoding="utf8")
    (WORK/"日別と分類.json").write_text(json.dumps({"日別":rows,"分類":groups,"順位相関":ranks},
                                     ensure_ascii=False,allow_nan=False),encoding="utf8")
    print(json.dumps(next(r for r in rows if r["セッション"]=="2026-10-08_Day"),ensure_ascii=False))


if __name__=="__main__":
    main()
