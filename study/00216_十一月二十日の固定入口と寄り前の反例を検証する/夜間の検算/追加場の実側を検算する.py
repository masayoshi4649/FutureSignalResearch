"""日経の追加4ナイトとTOPIX専用の追加7場を原板から線形走査して検算する。"""
from argparse import ArgumentParser
from datetime import datetime, timedelta
from pathlib import Path
from types import ModuleType
from zipfile import ZipFile
import gzip
import hashlib
import json
import sys

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0,str(ROOT/'work/pythonlibs'))
try:
    from orjson import loads
except ImportError:
    from json import loads
sys.path.insert(0,str(next((ROOT/'study').glob('00215_*'))/'朝の診断'))
import 原板で追加日を照合する as nk


# ----------------------------------------
def books(symbol: str, scene: str) -> tuple:
    """
    機能：共用ラージ原板の実側気配から商品固有の取得・決済代用に必要な配列を得る。
    引数：symbol（str）は商品、scene（str）は場名。
    返り値：tupleは原板と指紋。日経は原行列、TOPIXは両側1枚以上の正常気配のみ。
    """
    is_day = scene.endswith('_Day')
    date = datetime.fromisoformat(scene[:10]+'T00:00:00+09:00')
    start = (date+timedelta(hours=8,minutes=45) if is_day else date+timedelta(hours=17)).timestamp()
    close = start + (420 if is_day else 780)*60
    end = close-900
    folder = ROOT.parent/'JP_OSE_Data/future'/symbol/scene
    path = next(p for p in (folder/'book.jsonl',folder/'book.jsonl.gz') if p.is_file())
    sha = hashlib.sha256()
    clock_cache, rows = {}, []
    previous = start if symbol=='NK225' else -float('inf')
    old_state = None
    with (gzip.open(path,'rb') if path.suffix=='.gz' else path.open('rb')) as book:
        for line, buf in enumerate(book,1):
            sha.update(buf)
            v=loads(buf)
            stamp=v.get('CurrentPriceTime')
            if not stamp:
                continue
            if stamp not in clock_cache:
                clock_cache[stamp]=datetime.fromisoformat(stamp).timestamp()
            t=clock_cache[stamp]
            buy,sell = v.get('Buy1') or {},v.get('Sell1') or {}
            bid,ask = buy.get('Price') or 0,sell.get('Price') or 0
            if symbol=='NK225':
                if previous<=t<=close and (v.get('CurrentPrice') or 0)>0:
                    rows.append(nk.Quote(t,line,bid,ask))
                    previous=t
                continue
            # TOPIX専用口座の8列入力では状態不変の連続行を省き、時計の高水位を保持する。
            normal = 0<bid<ask and (buy.get('Qty') or 0)>=1 and (sell.get('Qty') or 0)>=1
            state=(stamp,v.get('CurrentPrice'),bid,ask,normal,v.get('TradingVolume'),v.get('TradingVolumeTime'))
            if state==old_state:
                continue
            old_state=state
            if t<previous:
                continue
            previous=t
            if start<=t<end and normal:
                rows.append(nk.Quote(t,line,bid,ask))
    proof={'原板名':path.name,'展開原板SHA256':sha.hexdigest(),'総行数':line,'採用行数':len(rows)}
    if symbol=='NK225':
        return (start,end,rows),proof
    times,lines,bids,asks=zip(*rows)
    return {'scene':scene,'start':start,'end':end,'force':end-60,'now':np.array(times),
            'line':np.array(lines),'bid':np.array(bids),'ask':np.array(asks)},proof


# ----------------------------------------
def verify_nikkei() -> dict:
    """
    機能：日経の固定台帳の全取得を原行と照合し、欠測の場合は期限と実気配の空白を示す。
    引数：なし。216の日経の追加4ナイトの取引を読む。
    返り値：dictは場別の照合結果。
    """
    pack=json.loads((HERE.parent/'日経/ナイト固定結果.json').read_bytes())['結果']
    results={}
    for scene, slot in pack.items():
        (nk.START,nk.CLOSE,rows),proof=books('NK225',scene)
        nk.SCENE=scene
        checked=nk.check_trades('NK225',rows,slot['建玉'])
        times=np.array([q.time for q in rows if q.normal])
        for t,d in zip(slot['建玉'],checked,strict=True):
            d.update(帯=t['判断帯'],決済時計=nk.clock(t['exit_time']) if t['net'] is not None else None,
                     順逆幅=t['width'],期限=t['horizon'])
            if t['net'] is not None:
                held=[q for q in rows[t['entry_index']:t['exit_index']+1] if q.normal]
                best=max((q.bid-t['entry_price'] if t['side']==0 else t['entry_price']-q.ask)
                         for q in held)
                d.update(最大順行ポイント=max(0,best),保有中最高費用後評価円=round(best*100-1077,1))
            if t['net'] is None:
                nominal=t['entry_time']+60*int(t['horizon'][1:])
                i=int(times.searchsorted(nominal))
                d.update(要求期限時計=nk.clock(nominal),猶予終了時計=nk.clock(nominal+30),
                         期限直前の最後の正常気配=nk.clock(times[i-1]),
                         期限以後の最初の正常気配=nk.clock(times[i]) if i<len(times) else None,
                         猶予内正常気配数=int(times.searchsorted(nominal+30,'right')-i),
                         確定保有終点=nk.clock(t['confirmed_until']))
                assert times[i-1]==t['confirmed_until'] and d['猶予内正常気配数']==0
        results[scene]={'原板':proof,'検算した建玉':checked}
    return results


# ----------------------------------------
def load_kernel() -> object:
    """
    機能：212が保存した独立線形検算器を指紋検査し、211の固定済みoracleを復元する。
    引数：なし。
    返り値：objectは生産用の価格探索木を使わない独立関数。
    """
    archive=next((ROOT/'study').glob('00212_*/独立確認Source.zip'))
    assert hashlib.sha256(archive.read_bytes()).hexdigest()=='03212bc751b04a101e07a901ce96d6b0535c608f0f6eaf97a9a5aebf442526ef'
    member='work/212独立確認/線形核を読む.py'
    with ZipFile(archive) as z:
        module=ModuleType('線形核216')
        module.__file__=str(ROOT/member)
        exec(compile(z.read(member),member,'exec'),module.__dict__)
    return module.load().oracle


# ----------------------------------------
def verify_topix() -> dict:
    """
    機能：TOPIX専用口座の実取得を原板の通知翌秒から再開し、決済時計・費用後収支まで検算する。
    引数：なし。216のTOPIX専用の追加7場元帳を読む。
    返り値：dictは場別の全建玉と未知理由。
    """
    oracle=load_kernel()
    pack=json.loads(gzip.decompress((HERE.parent/'TOPIX専用/追加七場.json.gz').read_bytes()))
    led=pack['ledger']
    results={}
    for record in pack['sessions']:
        scene=record['scene']
        book,proof=books('TOPIX',scene)
        checked=[]
        for i,session in enumerate(led['scene']):
            if session!=scene:
                continue
            t={k:v[i] for k,v in led.items()}
            actual=oracle(book,t['request_time'],t['request_line'],t['side'],t['width'],'H60')
            assert actual is not None
            for key in ('entry_time','entry_line','entry_price','exit_time','exit_line','exit_price',
                        'label','reason','unknown_reason','gross_pt'):
                assert t[key]==actual[key],(scene,i,key,t[key],actual[key])
            net=round(actual['gross_pt']*1000-583.6,1) if actual['gross_pt'] is not None else None
            assert t['net']==net
            checked.append({'売買':'買' if t['side']==1 else '売','幅':t['width'],'取得':nk.clock(t['entry_time']),
                            '決済':nk.clock(t['exit_time']) if t['exit_time'] else None,
                            '取得行':t['entry_line'],'決済行':t['exit_line'],'先着':t['label'],
                            '未知理由':t['unknown_reason'],'費用後円':net})
        results[scene]={'原板':proof,'検算した建玉':checked}
    assert len(results)==7
    return results


# ----------------------------------------
def main() -> None:
    """
    機能：指定商品の固定台帳を共用原板から検算し、機械可読の照合票を保存する。
    引数：コマンドラインの対象（str）は「日経」または「TOPIX」。
    返り値：None。各商品のJSONを当フォルダへ保存する。
    """
    arg=ArgumentParser(description=__doc__)
    arg.add_argument('対象',choices=('日経','TOPIX'))
    target=arg.parse_args().対象
    result=verify_nikkei() if target=='日経' else verify_topix()
    (HERE/(target+'の原板検算.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf8')


if __name__=='__main__':
    main()
