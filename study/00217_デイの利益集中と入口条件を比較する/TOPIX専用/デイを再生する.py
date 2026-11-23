"""TOPIXデイの固定入口へ同時刻の相場状態と次足確認を加えて、全日を再注文する。"""
from pathlib import Path
from statistics import median
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
WORK = ROOT / 'work/217TOPIX'
OLD = ROOT / 'inputs/TOPIX原順8列_20260921_20261116'
EXTRA = next((ROOT/'inputs').glob('00194_*/TOPIX'))
LATEST = ROOT / 'work/216TOPIX専用'
sys.path[:0] = [str(ROOT/'scripts/TOPIX入口研究'), str(ROOT/'work/194追加二場'),
                str(ROOT/'work/192TOPIX'), str(ROOT/'work/210TOPIX')]
import 共通金融 as account
import TOPIX純接続194 as added
import 入口192 as seed_rule
import 入口210 as veto

IDS = [f'T{i:02}' for i in range(13)]
KEY = ('session','time','line')
FIELDS = ('scene','side','width','entry_time','exit_time','net','request_time','request_line','entry_price','exit_price')


# ----------------------------------------
def inputs() -> tuple:
    """
    機能：旧212の純成立と追加3デイの同じ要求を、当時の直接形成特徴につなぐ。
    引数：なし。
    返り値：tupleは全45デイの特徴、基準の方向と幅、場ごとの価格資源。
    """
    read = account.read
    old_births = read(next((ROOT/'inputs').glob('00212_*/純入口.json.gz')))
    base = {tuple(r[k] for k in KEY):(r['signals'][6],r['widths'][6]) for r in old_births if r['band']=='DAY'}
    direct = []
    for path in (OLD,EXTRA,LATEST):
        part = [r for r in read(path/'純特徴184直接.json.gz') if r['band']=='DAY']
        if path == LATEST:
            # 216の特徴は旧11月17日デイを含む。二重登録を防ぎ、継承を点検する。
            prior_last = [r for r in direct if r['session']=='2026-11-17_Day']
            assert prior_last == [r for r in part if r['session']=='2026-11-17_Day']
            part = [r for r in part if r['session']>'2026-11-17_Night']
            for key, formed in added.per_form(part,seed_rule).items():
                side,width,_ = added.control(None,formed)
                if side and veto.roles(formed['row'],side)['A']:
                    side = 0
                base[key] = side,width
        direct.extend(part)
    resources = [r for r in account.entries(True) if r['session'].endswith('Day')]
    resources.extend(read(p) for p in sorted((LATEST/'原順8列').glob('*Day.json')))
    assert len(resources)==45 and len({r['session'] for r in resources})==45
    direct_keys = {tuple(r[k] for k in KEY) for r in direct}
    assert len(direct_keys)==len(direct) and all(not side for k,(side,_) in base.items() if k not in direct_keys)
    return direct,base,resources


# ----------------------------------------
def opposite(channel: dict | None, side: int) -> bool:
    """
    機能：公表済み時間軸のEMA21傾きとDMI差が両方逆向きかを返す。
    引数：channel（dictまたはNone）は足、side（int）は実方向。
    返り値：bool。公表不足は逆行の判定に含めない。
    """
    return channel is not None and channel['slope'] is not None and side*channel['slope']<0 and side*channel['di']<0


# ----------------------------------------
def conditions(row: dict, side: int) -> tuple:
    """
    機能：当時公表済みの押し戻し・値幅・量を用いて全ての鏡像条件を作る。
    引数：row（dict）は直近の公表足、side（int）は212の実側。
    返り値：tupleは13方向と次の1分まで確認すべきか。
    """
    short = row['m5']
    assert all(v is None or v['published']<=row['time'] for v in (short,row['m15'],row['m30']))
    mid, long = opposite(row['m15'],side), opposite(row['m30'],side)
    momentum = all(short[v] is not None and side*short[v]<0 for v in ('hist_delta','rsi_delta'))
    body = side*row['body']
    position = row['position'] if side==1 else 1-row['position']
    volume = row['rvol']
    surge = volume is not None and volume>=1.5 and body<=-.3
    weak_close = position<=.25 and body<=-.3
    extended = short['bbz'] is not None and side*short['bbz']>=1.5 and short['hist_delta'] is not None and side*short['hist_delta']<=0
    expensive = (row['spread']+.5836)/row['atr']>.25
    exclusions = [False,mid,long,momentum,surge,weak_close,extended,expensive,volume is None,
                  long or surge,momentum or weak_close,weak_close]
    return [0 if skip else side for skip in exclusions]+[-side if long and momentum else side],weak_close


# ----------------------------------------
def births(direct: list, base: dict) -> list:
    """
    機能：13口座の全要求を時系列で作成し、T11だけは直近の弱い押し戻しを一足確認する。
    引数：direct（list）は公表済みデイ特徴、base（dict）は固定基準。
    返り値：listは経路再生へ渡す有効な要求。同時の直接成立を優先する。
    """
    result = []
    pending = None
    for row in direct:
        key = tuple(row[k] for k in KEY)
        side,width = base.get(key,(0,None))
        if side:
            signals,weak_close = conditions(row,side)
        else:
            signals,weak_close = [0]*len(IDS), False
        widths = [width]*len(IDS)
        origins = ['旧190D4固定']*len(IDS)
        if pending is not None and not signals[11]:
            prior, direction, old_width = pending
            contiguous = row['session']==prior['session'] and 30<=row['time']-prior['time']<=90 and int(row['time']//60)-int(prior['time']//60)==1
            middle = prior['close']-prior['body']*prior['atr']/2
            if contiguous and direction*(row['close']-middle)>0 and direction*(row['close']-prior['close'])>0 and direction*row['m5']['di']>0:
                signals[11],widths[11],origins[11] = direction,old_width,'翌1分回復確認'
        pending = (row,side,width) if weak_close else None
        if any(signals):
            result.append({**{k:row[k] for k in KEY},'signals':signals,'widths':widths,'origins':origins})
    return result


# ----------------------------------------
def positions(pack: dict) -> list:
    """
    機能：一口座の各取得を共通の元帳形式に変換する。
    引数：pack（dict）は同時保有禁止の金融正本。
    返り値：listは実際に取得した各建玉。
    """
    rows = []
    for i,position in enumerate(pack['positions']):
        ledger = pack['ledger']
        if position['scene'].endswith('Day'):
            assert position['scene']==ledger['scene'][i] and position['fill']==ledger['entry_time'][i]
            rows.append({**{k:ledger[k][i] for k in FIELDS},'confirmed_until':position['confirmed_until'],
                         'label':{'F':1,'A':-1,'N':0,'C':2}[ledger['label'][i]]})
    return rows


# ----------------------------------------
def metrics(trades: list, scenes: list) -> dict:
    """
    機能：日末残高・上位日除外・費用後損益と実保有時間を全対象日で比較する。
    引数：trades（list）は建玉、scenes（list）は対象日。
    返り値：dictはこの期間だけの評価結果。
    """
    values = [p for p in trades if p['scene'] in scenes]
    profits = [p['net'] for p in values if p['net'] is not None]
    daily = [round(sum(p['net'] for p in values if p['scene']==s and p['net'] is not None),1) for s in scenes]
    balance = peak = drawdown = 0
    for net in daily:
        balance += net
        peak = max(peak,balance)
        drawdown = max(drawdown,peak-balance)
    return {'日数':len(daily),'参加':len({p['scene'] for p in values}),'件数':len(values),'未知':len(values)-len(profits),
            '黒字日':sum(v>0 for v in daily),'赤字日':sum(v<0 for v in daily),'勝ち':sum(v>0 for v in profits),
            '収支':round(sum(daily),1),'利益':round(sum(max(v,0) for v in profits),1),'損失':round(-sum(min(v,0) for v in profits),1),
            'DD':round(drawdown,1),'日中央値':median(daily),'建玉中央値':median(profits) if profits else None,
            '上位3除外':round(sum(sorted(daily,reverse=True)[3:]),1),
            '10/20除外':round(sum(v for s,v in zip(scenes,daily) if not s.startswith('2026-10-20')),1),
            '保有':sum(p['confirmed_until']-p['entry_time'] for p in values)/(len(scenes)*24300)}


# ----------------------------------------
def compare(books: dict, scenes: list) -> dict:
    """
    機能：各巡共通の期間で集計し、前24日だけの固定順位を計算する。
    引数：books（dict）は候補別建玉、scenes（list）は全45デイ。
    返り値：dictは選択IDと全候補の各期間の数値。
    """
    parts = {'前24':scenes[:24],'後21':scenes[24:],'末3':scenes[-3:],'全45':scenes}
    results = {key:{name:metrics(trades,dates) for name,dates in parts.items()} for key,trades in books.items()}
    eligible = {}
    for key, periods in results.items():
        data = periods['前24']
        if data['参加']==24 and not data['未知'] and data['保有']>=.2 and data['建玉中央値']>0 and data['日中央値']>0:
            eligible[key] = (data['上位3除外']<=0,data['赤字日'],data['DD'],data['損失'],key)
    return {'前24選択':min(eligible,key=eligible.get,default=None),'候補':results}


# ----------------------------------------
def main() -> None:
    """
    機能：全45日を再注文して既存の全取引・価格・時刻を照合し、前半選択と期間別結果を残す。
    引数：なし。
    返り値：None。作業元帳と閲覧用小計を出力する。
    """
    direct,base,resources = inputs()
    rows = births(direct,base)
    packs = account.replay(rows,IDS,resources)
    books = {p['id']:positions(p) for p in packs}
    controls = [next((ROOT/'study').glob('00212_*/金融正本/*D1*NF_native*.gz')),
                next((ROOT/'study').glob('00216_*/TOPIX専用/追加七場.json.gz'))]
    assert books['T00']==[p for path in controls for p in positions(account.read(path))]
    # ----------------------------------------
    scenes = [r['session'] for r in resources]
    assert scenes==sorted(scenes) and sorted({p['scene'] for p in books['T00']})==scenes
    result = compare(books,scenes)
    account.M.save(WORK/'比較元帳.json',books)
    account.M.save(HERE/'集計.json',{**result,'対象日':scenes,
        '基準照合':{'一致建玉':len(books['T00']),'列':[*FIELDS,'confirmed_until','label']}})
    print('前24選択',result['前24選択'],'旧全取引一致',len(books['T00']),flush=True)


if __name__=='__main__':
    main()
