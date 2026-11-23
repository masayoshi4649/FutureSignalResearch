"""抽出器を呼ばず、全q0とその接頭基準を原板から再照合する。"""
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime,timedelta,timezone
from pathlib import Path
import gzip
import hashlib
import json
import math
import sys

ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'work/pythonlibs'))
import orjson
DEST=ROOT/'inputs/00204_両指数の配信VWAP純入力';JST=timezone(timedelta(hours=9))


def read(path: Path) -> object:
    """
    機能: 固定されたJSONを読む。
    引数: path(Path)。
    返り値: objectはJSONの値。
    """
    with gzip.open(path,'rb') if path.suffix=='.gz' else path.open('rb') as f:return orjson.loads(f.read())


def epoch(value: object, cache: dict) -> float | None:
    """
    機能: 原板の時差付き時計を独立に解釈する。
    引数: value(object)、cache(dict)。
    返り値: float|NoneはUnix秒。
    """
    if not isinstance(value,str):return None
    if value not in cache:
        try:
            d=datetime.fromisoformat(value);cache[value]=d.timestamp() if d.utcoffset() is not None else None
        except (ValueError,OverflowError):cache[value]=None
    return cache[value]


def compare(entry: dict) -> dict:
    """
    機能: 全原行の価格時計上限と対象q0・参照基準の値を別走査で検査する。
    引数: entry(dict)は201由来の原板/q0固定票。
    返り値: dictは属性一致数。区間変更状態全体の別実装ではない。
    """
    scene=entry['session'];obj=read(DEST/'TOPIX'/(scene+'.json.gz'))
    rows={r['line']:r for r in obj['rows']};assert set(rows)=={q['line'] for q in entry['q0']}
    needed=set(rows)|{r['base']['line'] for r in rows.values() if r['base']}
    path=Path(entry['raw']['path']);raw_cache={};times={};maximum=-math.inf;checks=0;digest=hashlib.sha256()
    date=datetime.fromisoformat(scene[:10]).replace(tzinfo=JST)
    if scene.endswith('_Day'):start=date.replace(hour=8,minute=45).timestamp();end=date.replace(hour=15,minute=45).timestamp();floor=date.replace(hour=6).timestamp()
    else:start=date.replace(hour=17).timestamp();end=(date+timedelta(days=1)).replace(hour=6).timestamp();floor=date.replace(hour=15,minute=45).timestamp()
    name={'last':'CurrentPrice','volume':'TradingVolume','native':'VWAP','value':'TradingValue','opening_price':'OpeningPrice',
          'exchange':'Exchange','exchange_name':'ExchangeName'}
    identity=('Symbol','Exchange','ExchangeName','OpeningPrice','OpeningPriceTime')
    with gzip.open(path,'rb') if path.suffix=='.gz' else path.open('rb') as f:
        for line,body in enumerate(f,1):
            digest.update(body);raw=orjson.loads(body);t=epoch(raw.get('CurrentPriceTime'),times)
            backward=t is not None and t<maximum
            if t is not None:maximum=max(maximum,t)
            if line not in needed:continue
            raw_cache[line]=raw
            if line not in rows:continue
            r=rows[line];assert r['time']==t;checks+=1
            for field,key in name.items():assert r[field]==raw.get(key),(scene,line,field);checks+=1
            assert r['contract']==str(raw['Symbol']);checks+=1
            qt=epoch(raw.get('TradingVolumeTime'),times);ot=epoch(raw.get('OpeningPriceTime'),times)
            assert r['volume_time']==qt and r['opening_time']==ot;checks+=2
            q,v,w=r['volume'],r['value'],r['native']
            comparable=q is not None and q>0 and v is not None and v>=0 and w is not None and w>0
            ratio=v/q/10000 if comparable else None
            assert r['ratio']==ratio and r['ratio_error']==(abs(w-ratio) if comparable else None);checks+=2
            ratio_ok=comparable and abs(w-ratio)<=.00010001
            inside=qt is not None and t is not None and start<=qt<=t
            identity_ok=all(raw.get(k) is not None for k in identity) and ot is not None and ot>0 and r['opening_price']>0 and t is not None and ot<=t
            expected=(ratio_ok and inside and identity_ok and not backward and t is not None and start<=t<end and r['last'] is not None and r['last']>0)
            assert r['ratio_ok']==bool(ratio_ok) and r['quantity_inside']==inside and r['native_known']==bool(expected);checks+=3
            base=r['base']
            if base:
                old=raw_cache[base['line']];bt=epoch(old.get('CurrentPriceTime'),times);bqt=epoch(old.get('TradingVolumeTime'),times)
                assert base['line']<=line and base['time']==bt and base['volume_time']==bqt;checks+=3
                assert base['volume']==old['TradingVolume'] and base['value']==old['TradingValue'];checks+=2
                assert (floor<=bt<start and floor<=bqt<start) or (bt==start and bqt<=start and base['volume']==base['value']==0);checks+=1
                same=all(old.get(k)==raw.get(k) for k in identity)
                dq=q-base['volume'] if expected and same else None;dv=v-base['value'] if expected and same else None
                assert r['delta_volume']==dq and r['delta_value']==dv;checks+=2
                wanted=dv/dq/10000 if dq is not None and dq>0 and dv>0 else None
                assert r['session_delta']==wanted;checks+=1
            else:assert r['session_delta'] is None and r['delta_volume'] is None and r['delta_value'] is None;checks+=3
    assert digest.hexdigest()==entry['uncompressed_sha256'] and set(raw_cache)==needed
    assert hashlib.sha256(path.read_bytes()).hexdigest()==entry['raw']['sha256']
    return {'session':scene,'q0':len(rows),'比較属性':checks,'原板展開SHA':digest.hexdigest()}


def main() -> None:
    """
    機能: 全83場を別走査し、成功時のみ監査正本を保存する。
    引数: なし。
    返り値: None。損益・先着・売買条件は読み込まない。
    """
    plan=read(DEST/'抽出前固定_TOPIX.json.gz');assert not plan['financial_labels_used']
    with ProcessPoolExecutor(max_workers=3) as pool:results=list(pool.map(compare,plan['scenes']))
    proof={'成功':True,'金融未使用':True,'場数':len(results),'q0':sum(x['q0'] for x in results),'比較属性':sum(x['比較属性'] for x in results),
        '範囲':'原板全行の価格時計上限、全q0値・内部比率・可否・参照基準原行と差分。区間変更状態の全原行別実装ではない。',
        'SourceSHA':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'scenes':results}
    body=(json.dumps(proof,ensure_ascii=False,indent=2)+'\n').encode();out=DEST/'TOPIX独立原行照合.json'
    if out.exists():assert out.read_bytes()==body
    else:out.write_bytes(body)
    print('全83場',proof['q0'],'q0',proof['比較属性'],'属性一致')


if __name__=='__main__':main()
