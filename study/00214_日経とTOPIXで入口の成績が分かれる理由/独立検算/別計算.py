"""本集計モジュールを呼ばずに、原行端点・公表足・固定約定の同期統計を検算する。"""
from pathlib import Path
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from statistics import correlation, mean, median
import csv
import gzip
import json
import math
import numpy as np

HERE=Path(__file__).resolve().parent
STUDY=HERE.parent
ROOT=STUDY.parents[1]
OLD=next((ROOT/'study').glob('00213*'))
SYMS=('NK225','TOPIX')
TZ=timezone(timedelta(hours=9))


# ----------------------------------------
def read(path:Path) -> object:
    """
    機能：固定JSONと元帳gzipを読む。
    引数：path（Path）。
    返り値：objectは解析値。
    """
    data=path.read_bytes()
    return json.loads(gzip.decompress(data) if path.suffix=='.gz' else data)


# ----------------------------------------
def sample(path:Path,start:int) -> dict:
    """
    機能：48byte原行ファイルから二分検索と直接の窓内gap調査で端点を選ぶ。
    引数：path（Path）、start（int）は範囲開始秒。
    返り値：dictは窓番号に対応する変化と変化率。
    """
    buf=gzip.decompress(path.read_bytes())
    assert buf[:8]==b'NQIDX163'
    data=np.frombuffer(buf,dtype=[('t','<f8'),('l','<i8'),('c','<f8'),('b','<f8'),('a','<f8'),('ok','<u8')],offset=8)
    data=data[data['ok']==1]
    t=data['t']
    midpoint=(data['a']+data['b'])*.5
    marks=[]
    for j in range(82):
        at=start+300*j
        i=np.searchsorted(t,at)-(1 if j else 0)
        marks.append(i if 0<=i<len(t) and abs(t[i]-at)<=30 else -1)
    result={}
    for j,(a,b) in enumerate(zip(marks,marks[1:])):
        if a>=0 and b>a and np.all(np.diff(t[a:b+1])<=300):
            v=float(midpoint[b]-midpoint[a])
            result[j]=(v,10000*v/float(midpoint[a]))
    return result


# ----------------------------------------
def closed(path:Path,start:int) -> dict:
    """
    機能：別の観測尺度として各5分足の終値−始値の変化率を求める。
    引数：path（Path）は取引所配信を保存した分足、start（int）は場開始。
    返り値：dictは組番号と騰落率。
    """
    result={}
    with path.open(encoding='utf-8-sig',newline='') as f:
        for r in csv.DictReader(f):
            at=int(datetime.fromisoformat(r['time']).timestamp())
            j=(at-start)//300
            if r['closed']=='true' and 0<=j<81 and r['open'] and r['close'] and float(r['open'])>0:
                result[j]=10000*(float(r['close'])/float(r['open'])-1)
    return result


# ----------------------------------------
def corr(pairs:list) -> float:
    """
    機能：独立の標準ライブラリ式でPearson相関を求める。
    引数：pairs（list）はペアの列。
    返り値：floatは相関。
    """
    a,b=zip(*pairs,strict=True)
    return correlation(a,b)


# ----------------------------------------
def reprice(path:Path, group:list, ratio:float, cutoff:int) -> list:
    """
    機能：両側の元決済が既知の通知を、新幅でTOPIX最良気配行を直接検索して再決済する。
    引数：path（Path）は48byte原行、group（list）は同期通知、ratio（float）は直前5日、cutoff（int）は15:30秒。
    返り値：listは両幅確定例の先着、幅、費用前後。
    """
    buf=gzip.decompress(path.read_bytes())
    data=np.frombuffer(buf,dtype=[('t','<f8'),('l','<i8'),('c','<f8'),('b','<f8'),('a','<f8'),('ok','<u8')],offset=8)
    out=[]
    for r in group:
        if not all(r[s] and r[s]['net'] is not None for s in SYMS):
            continue
        t=r['TOPIX']
        entry=t['entry_index']
        width=math.ceil(4*ratio*r['日経表記幅'])/4
        deadline=math.inf if t['horizon']=='SESSION' else t['entry_time']+60*int(t['horizon'][1:])
        normal=(data['ok']==1)
        indices=np.arange(len(normal))
        forced=(data['t']>=cutoff-59)&(data['t']<=cutoff)
        timed=(data['t']>=deadline)&(data['t']<=min(cutoff,deadline+30))
        closure=np.flatnonzero(normal&(indices>entry)&(forced|timed))
        last=int(closure[0]) if len(closure) and data['t'][closure[0]]<=deadline+30 else len(data)
        clock=min(deadline,cutoff,data['t'][last] if last<len(data) else math.inf)
        last_tick=last_good=t['entry_time']
        gap=len(data)
        for i in range(entry+1,min(len(data),np.searchsorted(data['t'],cutoff,'right')+1)):
            now=data['t'][i]
            if (last_tick<clock and now-last_tick>300) or (last_good<clock and now-last_good>300):
                gap=i
                break
            last_tick=now
            if normal[i]:
                last_good=now
            if min(last_tick,last_good)>=clock:
                break
        mark=data['b'] if t['side']==0 else data['a']
        sign=1 if t['side']==0 else -1
        hit=np.flatnonzero((indices>entry)&(indices<=last)&(indices<gap)&normal&
                          (data['t']<=min(deadline,cutoff))&(abs(mark-t['entry_price'])>=width))
        end=int(hit[0]) if len(hit) else last
        if end>=min(len(data),gap):
            continue
        gross=1000*sign*(mark[end]-t['entry_price'])
        out.append((int(np.sign(gross)) if len(hit) else 0, (gross-583.6)/(1000*width)))
    return out


# ----------------------------------------
def main() -> None:
    """
    機能：主たる件数・変化・直前5日による幅換算・4セル差を独立照合する。
    引数：なし。
    返り値：None。確認票を当フォルダに保存する。
    """
    report=read(STUDY/'値動きの集計.json')
    mornings=read(STUDY/'朝の該当日.json')
    files=[next((ROOT/'inputs').glob(p)) for p in ('00163*/価格索引/manifest.json','00167*/原板数値索引/manifest.json',
           '00180*/原板数値索引/manifest.json','00194*/NK225/原板数値索引/manifest.json')]
    maps=[{r['session']:p.parent/r['index']['path'] for p in manifests for r in read(p)['scenes']} for manifests in
          (files,[ROOT/'work/今回移植/原行索引/manifest.json'])]
    holidays=set(read(ROOT/'docs/データ監査/現物制度属性と入口の分布/分類前固定.json')['現物休場日'])
    pairs=read(OLD/'同期照合の明細.json.gz')
    dates=sorted({r['場'] for r in pairs['NK225']})
    windows,closes,daily,rolling=[],[],[],[]
    scaled={s:[] for s in SYMS}
    for date in dates:
        start=int((datetime.fromisoformat(date[:10]).replace(tzinfo=TZ)+timedelta(hours=8,minutes=45)).timestamp())
        two=[sample(mapping[date],start) for mapping in maps]
        jointly=sorted(set(two[0])&set(two[1]))
        assert len(jointly)==report['日別5分窓'][date]
        if len(daily)>=5:
            a,b=zip(*(x for day in daily[-5:] for x in day))
            ratio=(sum(v*v for v in b)/sum(v*v for v in a))**.5
            assert abs(ratio-report['直前5日倍率'][date]['倍率'])<1e-12
            rolling.append(ratio)
            for source in SYMS:
                matches=[r for r in pairs[source] if r['場']==date]
                scaled[source].extend(reprice(maps[1][date],matches,ratio,start+405*60))
        daily.append([(two[0][j][0],two[1][j][0]) for j in jointly])
        windows.extend((date,j,two[0][j][1],two[1][j][1]) for j in jointly)
        cash=[closed(ROOT.parent/'JP_OSE_Data/future'/s/date/'candle_5min.csv',start) for s in SYMS]
        closes.extend((date,j,cash[0][j],cash[1][j]) for j in sorted(cash[0].keys()&cash[1].keys()))
    answer={}
    for name,subset in [('全体',lambda d,j:True),('通常日寄り前',lambda d,j:d[:10] not in holidays and j<3),
                        ('通常日09時から09時半',lambda d,j:d[:10] not in holidays and 3<=j<9)]:
        raw=[(a,b) for d,j,a,b in windows if subset(d,j)]
        bar=[(a,b) for d,j,a,b in closes if subset(d,j)]
        assert len(raw)==report['5分同期']['旧42日'][name]['窓'] and abs(corr(raw)-report['5分同期']['旧42日'][name]['同時相関'])<1e-12
        answer[name]={'気配数':len(raw),'気配相関':corr(raw),'公表足数':len(bar),'公表足相関':corr(bar)}
    # ----------------------------------------
    values=[]
    for source in SYMS:
        known=[r for r in pairs[source] if all(r[s] and r[s]['net'] is not None for s in SYMS)]
        for symbol,mul in zip(SYMS,(100,1000)):
            values.append(mean(r[symbol]['net']/(r[symbol]['width']*mul) for r in known))
    a,b,c,d=values
    parts=[a-d, (a-c+b-d)/2, (a-b+c-d)/2]
    assert np.allclose(parts,report['213の幅差の分解']['旧42日']['対角差と判断元差と商品差'],atol=1e-12,rtol=0)
    tp=read(next((OLD/'金融正本').glob('*03*.gz')))['取得']
    early=[t for t in tp if t['scene'] in dates and t['scene'][:10] not in holidays and datetime.fromtimestamp(t['entry_time'],TZ).hour<9 and t['side']==0]
    ref=mornings['売買別']['TOPIX/買']
    assert len(early)==7==ref['件数'] and all(t['net']<0 for t in early) and ref['利益取引']==0
    assert abs(sum(t['net'] for t in early)-ref['費用後円'])<1e-7
    width_results={}
    for s,v in scaled.items():
        check=report['幅尺度の効果']['旧42日/'+s]
        old=check['TOPIX過去変動']
        signs,returns=zip(*v)
        assert len(v)==check['同時完了'] and [signs.count(i) for i in (1,-1,0)]==[old[k] for k in ('順','逆','未到達')]
        assert abs(mean(returns)-old['平均費用後幅比'])<1e-12
        width_results[s]={'両幅確定':len(v),'過去5日幅のTOPIX平均損益幅比':mean(returns)}
    answer.update(旧日数=len(dates), 過去5日倍率一致日数=len(rolling), 過去5日倍率中央値=median(rolling),
                  TOPIX通常日09時前買い={'件数':7,'敗数':7,'損益':round(sum(t['net'] for t in early),2)},
                  幅比4平均=values, 対角差と判断元差と商品差=parts, 新幅の独立決済=width_results)
    (HERE/'照合票.json').write_text(json.dumps(answer,ensure_ascii=False,indent=2)+'\n',encoding='utf8')


if __name__=='__main__':
    main()
