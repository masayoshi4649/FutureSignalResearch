"""T17の足本数・方向効率・朝の許容時間・30分方向を一つずつ変更して再注文する。"""
from collections import deque
from datetime import datetime
from デイを再生する import HERE, WORK, KEY, account, compare, inputs, opposite, positions

IDS = [f'T{i:02}' for i in range(22,29)]
PARAMETERS = [
    (8,.25,600,False),(16,.25,600,False),(12,.15,600,False),(12,.35,600,False),
    (12,.25,570,False),(12,.25,630,False),(12,.25,600,True)]


# ----------------------------------------
def generate(direct: list, base: dict) -> list:
    """
    機能：連続した1分終値の累計移動量に対する正味変化から、基準方向を採るか選ぶ。
    引数：direct（list）は時系列特徴、base（dict）は212の入口方向と幅。
    返り値：listは7口座の要求。次の足や価格は参照しない。
    """
    seen = deque(maxlen=16)
    previous = None
    result = []
    for row in direct:
        key = tuple(row[k] for k in KEY)
        now = row['time']
        if previous is None or row['session']!=previous['session'] or int(now//60)-int(previous['time']//60)!=1 or not 30<=now-previous['time']<=90:
            seen.clear()
        seen.append(row['close'])
        previous = row
        side,width = base.get(key,(0,None))
        if not side:
            continue
        clock = datetime.fromtimestamp(now,account.M.JST)
        wall = clock.hour*60+clock.minute
        signals = []
        for bars,threshold,end,watch_long in PARAMETERS:
            prices = list(seen)[-bars:]
            travelled = sum(abs(b-a) for a,b in zip(prices,prices[1:]))
            enough = len(prices)==bars and travelled>0 and side*(prices[-1]-prices[0])/travelled>=threshold
            accept = 540<=wall<end or enough
            if watch_long and opposite(row['m30'],side):
                accept = False
            signals.append(side if accept else 0)
        if any(signals):
            result.append({**{k:row[k] for k in KEY},'signals':signals,'widths':[width]*len(IDS),'origins':['旧190D4固定']*len(IDS)})
    return result


# ----------------------------------------
def main() -> None:
    """
    機能：七近傍の保有・予約枠を個別に再生し、期間安定性と利益日集中を記録する。
    引数：なし。
    返り値：None。共通作業元帳と三巡目の結果を書き出す。
    """
    direct,base,resources = inputs()
    packs = account.replay(generate(direct,base),IDS,resources)
    books = {p['id']:positions(p) for p in packs}
    scenes = [r['session'] for r in resources]
    result = compare(books,scenes)
    old = account.read(WORK/'比較元帳.json')
    account.M.save(WORK/'比較元帳.json',{**old,**books})
    account.M.save(HERE/'三巡目集計.json',result)
    print('三巡目前24選択',result['前24選択'])


if __name__=='__main__':
    main()
