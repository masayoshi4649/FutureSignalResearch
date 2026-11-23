"""日経199_02の取得通知をTOPIXの正常板へ転送する補助対照。"""
from collections import Counter, defaultdict
from math import ceil, inf
from pathlib import Path
from statistics import median
from tempfile import TemporaryDirectory
from zipfile import ZipFile
import argparse
import gzip
import hashlib
import json
import sys

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = next(p for p in HERE.parents if (p / 'inputs').is_dir() and (p / 'study').is_dir())
SCHEMA = '65151fe4780391661887985e42046c8f646b6878096c53a46df2ad23d0bf76bc'


# ----------------------------------------
def digest(path: Path) -> str:
    """
    機能：ファイルの内容を読んでSHA256を算出する。
    引数：path（Path）は対象ファイル。
    返り値：strは16進指紋。
    """
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


# ----------------------------------------
def verification_engine(target: Path) -> object:
    """
    機能：211の恒久保存済み計算器を一時領域に展開して独立照合する。
    引数：target（Path）は空の一時ディレクトリ。
    返り値：objectは期限別の区間木計算器モジュール。
    """
    study = next((ROOT/'study').glob('00211_*'))
    expected = {'Source.zip':'dbba245acae8b1473d4bf620a4ba98e85e04eebfa1e5ddb5c472d85eebd9af5c',
                '追加依存Source.zip':'48c6155843bfbcea6eb311890d19c0ff6b754835fe46d8a51baae16f1ba306e3'}
    for name,sha in expected.items():
        assert digest(study/name)==sha
        with ZipFile(study/name) as archive:
            for source in archive.namelist():
                if source.endswith('.py'):
                    destination=target/source
                    assert destination.resolve().is_relative_to(target)
                    destination.parent.mkdir(parents=True,exist_ok=True)
                    destination.write_bytes(archive.read(source))
    sys.path.insert(0,str(target/'work/211期限比較'))
    import 期限接続211
    assert Path(期限接続211.__file__).is_relative_to(target)
    return 期限接続211


# ----------------------------------------
def materials() -> tuple:
    """
    機能：日経台帳の取得時に使える通知情報を読み、TOPIX板の指紋を確定する。
    引数：なし。
    返り値：tupleは場と通知、事後用の日経損益辞書、入力指紋辞書。
    """
    old = next((ROOT/'study').glob('00199_*'))
    manifests = [next((ROOT/'inputs').glob('TOPIX原順8列_*/台帳.json')),
                 next((ROOT/'inputs').glob('00194*/原順8列/入力台帳.json'))]
    cached = {r['session']: (ROOT/r['path'],r['sha256']) for r in json.loads(manifests[0].read_bytes())['entries']}
    for row in json.loads(manifests[1].read_bytes())['entries']:
        if row['symbol']=='TOPIX':
            cached[row['session']] = manifests[1].parent/'TOPIX'/(row['session']+'.npz'), row['sha256_cache']
    refs = {p.relative_to(ROOT).as_posix(): digest(p) for p in manifests}
    periods, benchmark = {}, {}
    for folder in (old/'保存金融',old/'追加二場/保存金融'):
        path = next(folder.glob('*_02__C0_IFD.json.gz'))
        refs[path.relative_to(ROOT).as_posix()] = digest(path)
        pack = json.loads(gzip.decompress(path.read_bytes()))
        for scene in pack['sessions']:
            if scene['kind']=='DAY':
                name = scene['scene']
                assert name not in periods
                periods[name] = (scene, cached[name], [])
        data = pack['ledger']
        for i, name in enumerate(data['scene']):
            if name not in periods:
                continue
            signal = {k:data[k][i] for k in ('entry_time','entry_price','side','horizon','width','entry_line')}
            periods[name][2].append(signal)
            benchmark[(name,signal['entry_line'])] = data['net'][i]
    assert len(periods)==42 and len(benchmark)==162 and round(sum(benchmark.values()),1)==1057526
    return periods,benchmark,refs


# ----------------------------------------
def quotes(path: Path, start: float, end: float) -> dict:
    """
    機能：正常板だけを価格時計の高水位と原行順で抽出する。
    引数：path（Path）はTOPIX原順8列、start/end（float）は対象時計。
    返り値：dictは当場の時刻、原行、買い板、売り板。
    """
    with np.load(path,allow_pickle=False) as cache:
        time = cache['now']
        finite = np.isfinite(time)
        high = np.maximum.accumulate(np.where(finite,time,-inf))
        mask = finite & (time>=high) & (time>=start) & (time<end) & cache['valid']
        result = {k:cache[k][mask] for k in ('now','line','bid','ask')}
    assert np.all(result['ask']>result['bid']) and np.all(np.diff(result['now'])>=0)
    return result


# ----------------------------------------
def exit_and_fill(book: dict, order: dict, width: float, end: float) -> dict | None:
    """
    機能：次秒の取得、利確指値・逆指値と期限返済を原順BBOの直接走査で求める。
    引数：book/order（dict）、width/end（float）は固定幅と終了時刻。
    返り値：dictは取引と保持終点、Noneは取得期限切れ。
    """
    t = book['now']
    time = order['entry_time']
    opened = int(np.searchsorted(t,time+1))
    if opened==len(t) or t[opened]>time+30 or t[opened]>=end-60:
        return None
    side = 1 if order['side']==0 else -1
    entry = float(book['ask' if side==1 else 'bid'][opened])
    mark = book['bid' if side==1 else 'ask']
    assert order['horizon'] in ('H60','SESSION')
    limit = min(t[opened]+3600,end-60) if order['horizon']=='H60' else end-60
    last = int(np.searchsorted(t,limit,side='right'))
    pnl = side*(mark[opened:last]-entry)
    touches = np.flatnonzero(abs(pnl)>=width)
    touch = opened+int(touches[0]) if touches.size else None
    flag = 'N' if touch is None else ('F' if side*(mark[touch]-entry)>=width else 'A')
    trigger = limit if touch is None else float(t[touch])
    done = touch if flag=='F' else int(np.searchsorted(t,trigger+1))
    ttl = min(trigger+30,end)
    valid = done<len(t) and t[done]<=ttl
    last = done if valid else min(int(np.searchsorted(t,ttl)),len(t)-1)
    gaps = np.flatnonzero(np.diff(t[opened:last+1])>300)
    expired = not valid or bool(len(gaps))
    if len(gaps):
        gap = opened+int(gaps[0])+1
        until = float(t[gap-1])
        if touch is None or gap<=touch:
            flag='C'
    elif not valid:
        until = float(t[max(opened,int(np.searchsorted(t,ttl,'right'))-1)])
        if touch is None:
            flag='C'
    else:
        until = float(t[done])
    price = None if expired else (entry+side*width if flag=='F' else float(mark[done]))
    gross = None if expired else side*(price-entry)*1000
    return {'side':side, 'width':width, 'label':flag,'entry_time':float(t[opened]),
            'entry_line':int(book['line'][opened]),'entry_price':entry,
            'exit_time':None if expired else float(t[done]),'exit_line':None if expired else int(book['line'][done]),
            'exit_price':price,'known_until':until,'gross':gross,'net':None if expired else round(gross-583.6,1)}


# ----------------------------------------
def totals(trades: list) -> dict:
    """
    機能：未知損益を除いた寄与と件数を集計する。
    引数：trades（list）は約定行の列。
    返り値：dictは当該集合の件数・既知利益・既知損失など。
    """
    net = [r['net'] for r in trades if r['net'] is not None]
    return {'取得':len(trades),'未知':len(trades)-len(net),'利益':round(sum(x for x in net if x>0),1),
            '損失':round(-sum(x for x in net if x<0),1),'収支':round(sum(net),1),
            '費用前収支':round(sum(r['gross'] for r in trades if r['gross'] is not None),1),
            '費用':round(583.6*len(net),1),'勝':sum(x>0 for x in net),'負':sum(x<0 for x in net),
            '順逆未達不足':dict(Counter(r['label'] for r in trades))}


# ----------------------------------------
def main() -> None:
    """
    機能：固定条件を42デイへ再生し、任意で旧211区間木計算と全取得属性を照合する。
    引数：CLIの--verifyは独立比較を実行、--output（Path）は出力先。
    返り値：None。全要求・取得・期間別成績を日本語JSONで保存する。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('--verify',action='store_true')
    parser.add_argument('--output',type=Path,default=HERE/'結果.json')
    args = parser.parse_args()
    assert digest(HERE/'条件.json')==SCHEMA
    staging=TemporaryDirectory() if args.verify else None
    if args.verify:
        ref=verification_engine(Path(staging.name))
    periods,nk,files = materials()
    all_requests,all_trades,sessions = [],[],{}
    checked = 0
    for name,(scene,(path,expected),orders) in sorted(periods.items()):
        assert digest(path)==expected
        files[path.relative_to(ROOT).as_posix()] = expected
        end=scene['close_deadline']
        book=quotes(path,scene['start'],end)
        release,state=-inf,'空'
        if args.verify:
            routes={h:ref.Route({'cache_absolute':str(path),'session':name},h) for h in ('H60','SESSION')}
        trades=[]
        for order in orders:
            time=order['entry_time']
            request={'通知':time,'日経原行':order['entry_line'],'日経取得価格':order['entry_price'],
                     '日経幅':order['width'],'期限':order['horizon'],'場':name}
            all_requests.append(request)
            if time<=release:
                request['判断']=state+'中'
                continue
            t=book['now']
            k=int(np.searchsorted(t,time))-1
            if k<0 or time-t[k]>60:
                request['判断']='基準板不足'
                continue
            mid=float(book['bid'][k]+book['ask'][k])/2
            width=ceil(4*mid*order['width']/order['entry_price'])/4
            request.update(幅=width,基準時刻=float(t[k]),基準原行=int(book['line'][k]),基準価格=mid)
            cell=exit_and_fill(book,order,width,end)
            if args.verify:
                reference=routes[order['horizon']].cell(time,order['entry_line'],1 if order['side']==0 else -1,width)
                if cell is None or reference is None:
                    assert cell is None and reference is None
                else:
                    for key in ('entry_time','entry_line','entry_price','exit_time','exit_line','exit_price','label','known_until'):
                        assert reference[key]==cell[key],(name,k,key)
                checked+=1
            if cell is None:
                release,state=min(time+30,end-60),'予約'
                request['判断']='取得失効'
                continue
            release,state=(end if cell['net'] is None else cell['exit_time']),'保有'
            request['判断']='取得'
            cell.update(scene=name,signal_time=time,nk_line=order['entry_line'],horizon=order['horizon'])
            trades.append(cell)
        all_trades.extend(trades)
        sessions[name]={**totals(trades),'通知数':len(orders),
                        '保有下限秒':sum(r['known_until']-r['entry_time'] for r in trades)}
    assert len(all_requests)==162
    matched=[r for r in all_trades if r['net'] is not None]
    dates=sorted(sessions)
    known_trades=[r['net'] for r in matched]
    known_days=[s['収支'] for s in sessions.values() if s['未知']==0]
    unknown_trades=len(all_trades)-len(known_trades)
    unknown_days=len(sessions)-len(known_days)
    report={'入力指紋':files,'条件指紋':SCHEMA,'本体指紋':digest(Path(__file__)),
            '成績':totals(all_trades),'参加場':sum(s['取得']>0 for s in sessions.values()),
            '黒字場':sum(s['収支']>0 and s['未知']==0 for s in sessions.values()),
            '赤字場':sum(s['収支']<0 and s['未知']==0 for s in sessions.values()),
            '保有率下限':sum(v['保有下限秒'] for v in sessions.values())/(42*24300),
            '判明建玉中央値':median(r['net'] for r in matched) if matched else None,
            '判明場中央値':median(s['収支'] for s in sessions.values() if s['未知']==0),
            '全建玉中央値範囲':[round(median(known_trades+[bound]*unknown_trades),1) for bound in (-inf,inf)],
            '全場中央値範囲':[round(median(known_days+[bound]*unknown_days),1) for bound in (-inf,inf)],
            '両側既知の日経合計':sum(nk[r['scene'],r['nk_line']] for r in matched),
            '両側既知の損益符号一致':sum((nk[r['scene'],r['nk_line']]>0)==(r['net']>0) for r in matched),
            '通知結果':dict(Counter(r['判断'] for r in all_requests)),'決済照合要求数':checked,
            '期間':{label:totals([r for r in all_trades if r['scene'] in part]) for label,part in
                    [('前48中デイ',dates[:24]),('後25中デイ',dates[24:37]),('追加7中デイ',dates[37:40]),
                     ('11月16日',dates[40:41]),('11月17日',dates[41:42])]},
            'セッション':sessions,'全通知':all_requests,'取引':all_trades}
    args.output.write_text(json.dumps(report,ensure_ascii=False,separators=(',',':'))+'\n',encoding='utf-8')
    if staging is not None:
        staging.cleanup()
    print({k:v for k,v in report.items() if k not in ('入力指紋','全通知','取引','セッション')})


if __name__=='__main__':
    main()
