"""寄り前の全取得を日と売買方向で照合し、同じ向きでも結果が割れた例を描く。"""
from collections import Counter, defaultdict
from datetime import datetime, timedelta
import json
from 値動きを照合する import HERE, ROOT, JST, SYMBOLS, Midpoints, ledgers, load_scene, read


# ----------------------------------------
def chart(indices: dict, selected: dict) -> None:
    """
    機能：11月2日の実保有中だけ、原行の返済側価格を各商品のIFD幅に換算して描く。
    引数：indices（dict）は一場の両商品索引、selected（dict）は当該日の寄り前の建玉。
    返り値：None。PNGを試行フォルダに保存する。
    """
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    from matplotlib import font_manager
    font = next((f for f in ('Meiryo','Noto Sans CJK JP','Yu Gothic') if f in font_manager.get_font_names()),None)
    if font:
        plt.rcParams['font.family'] = font
    fig,ax = plt.subplots(figsize=(9.4,4.4),layout='constrained')
    for symbol,label,color,offset in [('NK225','日経225','#145583',(7,-12)),('TOPIX','TOPIX','#ad4a24',(9,8))]:
        trade = selected[symbol]
        assert trade['side']==0
        normal = indices[symbol].rows[trade['entry_index']:trade['exit_index']+1]
        normal = normal[normal['normal']==1]
        signed = (normal['bid']-trade['entry_price'])/trade['width']
        times = [datetime.fromtimestamp(t,JST) for t in normal['time']]
        ax.plot(times,signed,color=color,label=label,linewidth=1.15)
        ax.scatter(times[-1],signed[-1],color=color,s=27,zorder=4)
        ax.annotate(times[-1].strftime('%H:%M:%S'),(times[-1],signed[-1]),xytext=offset,
                    textcoords='offset points',color=color,fontsize=9)
    opened = datetime(2026,11,2,9,tzinfo=JST)
    ax.axvline(opened,linewidth=.9,linestyle=':',color='#586777')
    ax.text(opened+timedelta(seconds=8),1.11,'現物寄り付き',color='#586777',fontsize=9)
    for level in (-1,0,1):
        ax.axhline(level,linewidth=.7,linestyle='--',color='#9ca6ac',zorder=0)
    ax.set_title('11月2日　両先物が08:56に買いを建ててから決済するまで',loc='left',fontsize=15)
    ax.set_ylabel('建値からの値動き（IFD幅）')
    ax.set_xlabel('日本時間')
    ax.set_yticks([-1,-.5,0,.5,1],['−1  損切','−0.5','0  建値','＋0.5','＋1  利確'])
    ax.set_ylim(-1.22,1.29)
    ax.set_xlim(opened-timedelta(minutes=5),opened+timedelta(minutes=19))
    ax.xaxis.set_major_locator(mdates.MinuteLocator(byminute=[0,5,10,15,55],tz=JST))
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M',tz=JST))
    ax.legend(loc='lower right',frameon=False)
    ax.spines[['right','top']].set_visible(False)
    fig.savefig(HERE/'11月2日の買い建玉.png',dpi=160)
    plt.close(fig)


# ----------------------------------------
def main() -> None:
    """
    機能：現物営業日の寄り前の約定日・側と開始からの価格方向を照合する。
    引数：なし。既使用42デイの固定取得と価格索引を用いる。
    返り値：None。日ごとの観測・集計・図を保存する。
    """
    trades,books = ledgers()
    refs = {s:{r['session']:(f.parent,r) for f in paths for r in read(f)['scenes']} for s,paths in books.items()}
    holidays=set(read(ROOT/'docs/データ監査/現物制度属性と入口の分布/分類前固定.json')['現物休場日'])
    days=sorted({t['scene'] for t in trades['NK225']})
    counts=Counter()
    by_side={}
    detail={}
    backgrounds=defaultdict(lambda:defaultdict(list))
    for scene in days:
        if scene[:10] in holidays:
            continue
        date=datetime.fromisoformat(scene[:10]).replace(tzinfo=JST)
        start=(date+timedelta(hours=8,minutes=45)).timestamp()
        selected={}
        for s in SYMBOLS:
            early=[t for t in trades[s] if t['scene']==scene and t['entry_time']<start+900]
            assert len(early)<=1
            if early:
                selected[s]=early[0]
        label='両方' if len(selected)==2 else next(iter(selected),'両方なし')
        counts[label]+=1
        if not selected:
            continue
        idx={s:load_scene(*refs[s][scene]) for s in SYMBOLS}
        mids={s:Midpoints(i) for s,i in idx.items()}
        preceding=sorted(set(refs['NK225']) & set(refs['TOPIX']))
        prior=next((name for name in reversed(preceding) if name<scene and name.endswith('_Night')),None)
        previous={}
        if prior is not None:
            prior_end=datetime.fromisoformat(prior[:10]).replace(tzinfo=JST)+timedelta(days=1,hours=5,minutes=55)
            for s in SYMBOLS:
                pm=Midpoints(load_scene(*refs[s][prior]))
                pos=pm.at(prior_end.timestamp())
                if pos is not None:
                    previous[s]=float(pm.mid[pos])
        group={}
        for s,trade in selected.items():
            direction=1 if trade['side']==0 else -1
            side='買' if direction==1 else '売'
            m=mids[s]
            follow=m.change(m.at(start,first=True),m.at(trade['entry_time']))
            after=m.change(m.at(start+900),m.at(start+1800))
            group[s]={'側':side,'取得':datetime.fromtimestamp(trade['entry_time'],JST).strftime('%H:%M:%S'),
                      '建値':trade['entry_price'],'決済':datetime.fromtimestamp(trade['exit_time'],JST).strftime('%H:%M:%S'),
                      '決済値':trade['exit_price'],'費用後円':trade['net'],'LC':trade['added'],
                      '開始から取得直前の売買方向bp':None if follow is None else direction*follow[1],
                      '09時から09時15分の売買方向bp':None if after is None else direction*after[1]}
            # ----------------------------------------
            # 双方が夜の最終気配から通知直前まで注文側に進んだかを、追加の時点診断として扱う。
            moves=[]
            for other in SYMBOLS:
                q=mids[other].at(trade['entry_time'])
                if other in previous and q is not None:
                    moves.append(float(direction*(mids[other].mid[q]/previous[other]-1)*10000))
            group[s]['直前ナイト']=prior
            group[s]['前夜比の両指数の方向付きbp']=moves if len(moves)==2 else None
            status='不明' if len(moves)<2 else '両方順' if min(moves)>0 else '両方逆' if max(moves)<0 else '混在または同値'
            backgrounds[s][status].append(trade['net'])
            c=by_side.setdefault(s+'/'+side,Counter())
            c['件数']+=1
            c['利益取引']+=int(trade['net']>0)
            c['費用後円']+=trade['net']
            if follow is not None:
                c['開始から取得直前が注文と同方向']+=int(direction*follow[0]>0)
                c['開始から取得直前が注文と逆方向']+=int(direction*follow[0]<0)
            if after is not None:
                c['寄り後15分が注文と同方向']+=int(direction*after[0]>0)
        if label=='両方':
            counts['両方同方向' if group['NK225']['側']==group['TOPIX']['側'] else '両方逆方向']+=1
        detail[scene]=group
        if scene=='2026-11-02_Day':
            chart(idx,selected)
    for values in by_side.values():
        values['費用後円']=round(values['費用後円'],1)
    bg={s:{k:{'件数':len(v),'黒字件数':sum(x>0 for x in v),'費用後円':round(sum(v),1)} for k,v in sets.items()}
        for s,sets in backgrounds.items()}
    result={'時間':'08:45以上09:00未満の取得・現物通常日のみ','日数':counts,'売買別':by_side,
            '追加診断の直前ナイト比':bg,'日別':detail}
    (HERE/'朝の該当日.json').write_text(json.dumps(result,ensure_ascii=False,indent=1)+'\n',encoding='utf-8')


if __name__=='__main__':
    main()
