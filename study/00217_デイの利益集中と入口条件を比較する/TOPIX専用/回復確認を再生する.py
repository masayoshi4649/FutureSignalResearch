"""TOPIXの押し戻し源時の即時取得と、源から五本以内の価格回復後の取得を比較する。"""
from collections import deque
from datetime import datetime
from デイを再生する import HERE, WORK, KEY, account, compare, inputs, positions

IDS = [f'T{i:02}' for i in range(13,22)]


# ----------------------------------------
def generate(direct: list, base: dict) -> list:
    """
    機能：当時の効率・時刻から即時、反対側、固定線を使った価格回復待機を分ける。
    引数：direct（list）は確定時間順の1分特徴、base（dict）は212の方向とIFD幅。
    返り値：listは九候補の全要求。保有・予約は後段で時系列再生する。
    """
    closes = deque(maxlen=12)
    pending = [None]*len(IDS)
    previous = None
    result = []
    for row in direct:
        key = tuple(row[k] for k in KEY)
        now = row['time']
        minute = int(now//60)
        if previous is None or row['session']!=previous['session'] or minute!=int(previous['time']//60)+1 or not 30<=now-previous['time']<=90:
            closes.clear()
            pending = [None]*len(IDS)
        closes.append(row['close'])
        clock = datetime.fromtimestamp(now,account.M.JST)
        morning = clock.hour==9
        wall = 60*clock.hour+clock.minute
        quiet = 690<=wall<750 or wall>=870
        side,width = base.get(key,(0,None))
        efficiency = None
        if side and len(closes)==12:
            prices = list(closes)
            variation = sum(abs(b-a) for a,b in zip(prices,prices[1:]))
            efficiency = side*(prices[-1]-prices[0])/variation if variation else 0
        efficient = efficiency is not None and efficiency>=.25
        reverse = side and efficiency is not None and efficiency<=-.25 and all(row['m5'][k] is not None and side*row['m5'][k]<0 for k in ('hist_delta','rsi_delta'))
        immediate = [morning,False,morning,morning,morning or efficient,True,morning or efficient,efficient,not quiet]
        wait = [False,True,not morning,not morning,False,False,not(morning or efficient),not efficient,quiet]
        directions,widths,origins = [0]*len(IDS),[None]*len(IDS),['旧190D4固定']*len(IDS)
        # ----------------------------------------
        for i,_ in enumerate(IDS):
            if side and immediate[i]:
                directions[i],widths[i] = (-side if i==5 and reverse and not morning else side),width
                pending[i] = None
                continue
            state = pending[i]
            if state is not None:
                source_minute,direction,source_width,level = state
                if minute-source_minute>5:
                    pending[i] = None
                else:
                    crossed = direction*(previous['close']-level)<=0<direction*(row['close']-level)
                    volume = row['rvol']
                    quality = i!=3 or (direction*row['m5']['di']>0 and volume is not None and volume>=.8)
                    if crossed and quality:
                        directions[i],widths[i],origins[i] = direction,source_width,'確定終値で源の値幅を回復'
                        pending[i] = None
                        continue
            if pending[i] is None and side and wait[i]:
                edge = row['high'] if side==1 else row['low']
                pending[i] = (minute,side,width,edge)
        if any(directions):
            result.append({**{k:row[k] for k in KEY},'signals':directions,'widths':widths,'origins':origins})
        previous = row
    return result


# ----------------------------------------
def main() -> None:
    """
    機能：二巡目九候補を全45日で再生し、前24日の基準で選択する。
    引数：なし。
    返り値：None。候補の比較元帳と期間別成績を保存する。
    """
    direct,base,resources = inputs()
    packs = account.replay(generate(direct,base),IDS,resources)
    books = {p['id']:positions(p) for p in packs}
    scenes = [r['session'] for r in resources]
    result = compare(books,scenes)
    old = account.read(WORK/'比較元帳.json')
    account.M.save(WORK/'比較元帳.json',{**old,**books})
    account.M.save(HERE/'二巡目集計.json',result)
    print('二巡目前24選択',result['前24選択'])


if __name__=='__main__':
    main()
