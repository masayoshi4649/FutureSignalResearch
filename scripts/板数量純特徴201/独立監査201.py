"""特徴核を呼ばず、原行履歴から201の全純値を直接検算する。"""
from bisect import bisect_right
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path
import gzip
import hashlib
import json
import math
import re
import sys
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'work/pythonlibs'))
import orjson
DEST=ROOT/'inputs/00201_両指数の板数量純特徴'
NAMES=('QI1','QI3','QI10','OFI16','OFI64','BLOCK4_OFI','BLOCK4_MID_CHANGE')


# ----------------------------------------
def read(path):
    """
    機能: 純JSON資源だけを読む。
    引数: path(Path)は対象。
    返り値: objectは値。
    """
    with gzip.open(path,'rb') if path.suffix=='.gz' else path.open('rb') as f:return orjson.loads(f.read())


# ----------------------------------------
def sha(path):
    """
    機能: 物理SHAを読む。
    引数: path(Path)は対象。
    返り値: strはSHA256。
    """
    with path.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()


# ----------------------------------------
def finite(value):
    """
    機能: 数量と価格の型・有限性を確認する。
    引数: value(any)。
    返り値: boolは数値かつ有限。
    """
    return type(value) in (int,float) and math.isfinite(value)


# ----------------------------------------
def clock(value):
    """
    機能: RFC3339のナノ秒を明示して純q0と同じ秒表現にする。
    引数: value(any)は原板時計。
    返り値: float|Noneは価格時計。
    """
    if not isinstance(value,str):return None
    m=re.fullmatch(r'(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:[.,](\d+))?(Z|[+-]\d{2}:\d{2})',value)
    if not m:return None
    try:
        d=datetime.fromisoformat(m[1]+m[3].replace('Z','+00:00'))
        return float(int(d.timestamp())*1_000_000_000+int(((m[2] or '')+'000000000')[:9]))/1e9
    except ValueError:return None


# ----------------------------------------
def delta(p,q):
    """
    機能: 価格上昇/同値/下落の3場合からOFIを独立計算する。
    引数: p/q(tuple)はline,time,b,a,B,A,last。
    返り値: floatは両側平均深さで割った需給差分。
    """
    b=(q[4] if q[2]>p[2] else (-p[4] if q[2]<p[2] else q[4]-p[4]))
    a=(-q[5] if q[3]<p[3] else (p[5] if q[3]>p[3] else p[5]-q[5]))
    return 2*(a+b)/(p[4]+p[5]+q[4]+q[5])


# ----------------------------------------
def result(value,history,start,end,available,count):
    """
    機能: 保存実装の累積量を使わず、選んだ履歴範囲の出典を再作成する。
    引数: value(float),history(list),start/end/available/count(int)。
    返り値: dictは既知値と原行・時計尺度。
    """
    a,b=history[start],history[end]
    gap=max((history[i][1]-history[i-1][1] for i in range(start+1,end+1)),default=0)
    return dict(value=value,known=True,start_line=a[0],end_line=b[0],available_line=available,
                events=count,clock_span=b[1]-a[1],max_clock_gap=gap)


# ----------------------------------------
def inspect(entry):
    """
    機能: 一場の全q0を原板prefixと直接式から独立照合する。
    引数: entry(dict)は金融前固定入力。
    返り値: dictは照合件数と既知数。特徴核・抽出実装はimportしない。
    """
    symbol,session=entry['symbol'],entry['session']
    source=Path(entry['raw']['path'])
    cached=DEST/symbol/(session+'.json.gz')
    stored=read(cached);assert stored['schema']=='純板201_v1' and not stored['financial_labels_used']
    wanted={r['line']:r for r in stored['rows']};planned={r['line']:r for r in entry['q0']}
    assert len(wanted)==len(stored['rows']) and set(wanted)==set(planned)
    day=datetime.fromisoformat(session[:10]).replace(tzinfo=timezone(timedelta(hours=9)))
    start=(day+timedelta(hours=8,minutes=45) if session.endswith('Day') else day+timedelta(hours=17)).timestamp()
    end=(day+timedelta(hours=15,minutes=45) if session.endswith('Day') else day+timedelta(days=1,hours=6)).timestamp()
    highest=None;contract=None;history=[];changes=[];closed=[];block_start=0
    parsed={};digest=hashlib.sha256();compared=0;knowns={k:0 for k in NAMES};max_error=0.0
    before=source.stat()
    with gzip.open(source,'rb') if source.suffix=='.gz' else source.open('rb') as stream:
        for line,raw in enumerate(stream,1):
            digest.update(raw);r=orjson.loads(raw);text=r.get('CurrentPriceTime')
            if text not in parsed:parsed[text]=clock(text)
            t=parsed[text];bu=r.get('Buy1') or {};se=r.get('Sell1') or {}
            q=(line,t,bu.get('Price'),se.get('Price'),bu.get('Qty'),se.get('Qty'),r.get('CurrentPrice'))
            code=r.get('Symbol')
            valid=finite(t) and start<=t<end and (highest is None or t>=highest)
            valid=valid and isinstance(code,str) and bool(code) and all(finite(x) and x>0 for x in q[2:]) and q[2]<q[3]
            if finite(t) and start<=t<end:highest=t if highest is None else max(highest,t)
            if not valid or contract is not None and code!=contract:
                history=[];changes=[];closed=[];block_start=0
            if valid:
                contract=code;index=len(history)
                if index and t>history[-1][1]:
                    closed.append((max(block_start-1,0),index-1,line))
                    block_start=index
                if index and q[2:6]!=history[-1][2:6]:changes.append(index)
                history.append(q)
            if line not in wanted:continue
            saved=wanted[line];plan=planned[line]
            assert (saved['time'],saved['last'],saved['bid'],saved['ask'])==(t,q[6],q[2],q[3])
            assert (plan['time'],plan['last'],plan['bid'],plan['ask'])==(t,q[6],q[2],q[3])
            assert saved['members']==plan['members'] and set(saved['features'])==set(NAMES)
            expected={key:dict(known=False) for key in NAMES}
            if valid:
                for depth in (1,3,10):
                    buy=[(r.get('Buy'+str(i)) or {}) for i in range(1,depth+1)]
                    sell=[(r.get('Sell'+str(i)) or {}) for i in range(1,depth+1)]
                    good=all(finite(z.get(k)) and z[k]>0 for z in buy+sell for k in ('Price','Qty'))
                    good=good and all(buy[i]['Price']>buy[i+1]['Price'] and sell[i]['Price']<sell[i+1]['Price'] for i in range(depth-1))
                    if good:
                        bsum=sum(z['Qty'] for z in buy);asum=sum(z['Qty'] for z in sell)
                        expected['QI'+str(depth)]=result((bsum-asum)/(bsum+asum),history,index,index,line,1)
                for size in (16,64):
                    if len(changes)>=size:
                        chosen=changes[-size:]
                        base=changes[-size-1] if len(changes)>size else 0
                        value=sum(delta(history[i-1],history[i]) for i in chosen)/size
                        expected['OFI'+str(size)]=result(value,history,base,chosen[-1],line,size)
                if len(closed)>=4:
                    a=closed[-4][0];b=closed[-1][1];pub=closed[-1][2]
                    subset=changes[bisect_right(changes,a):bisect_right(changes,b)]
                    expected['BLOCK4_MID_CHANGE']=result((history[b][2]+history[b][3]-history[a][2]-history[a][3])/2,history,a,b,pub,len(subset))
                    if subset:
                        value=sum(delta(history[i-1],history[i]) for i in subset)/len(subset)
                        expected['BLOCK4_OFI']=result(value,history,a,b,pub,len(subset))
            for key in NAMES:
                a=saved['features'][key];b=expected[key]
                assert a['known']==b['known'],(symbol,session,line,key,a,b)
                assert a['end_line']<=a['available_line']<=line
                if not b['known']:
                    assert a['value'] is None and a['reason'] and a['start_line']==a['end_line']==0
                else:
                    knowns[key]+=1;assert a['reason']==''
                    for field,value in b.items():
                        if field=='value':
                            error=abs(a[field]-value);max_error=max(max_error,error)
                            assert math.isclose(a[field],value,abs_tol=1e-12,rel_tol=1e-12),(symbol,session,line,key,field,a[field],value)
                        else:assert a[field]==value,(symbol,session,line,key,field,a[field],value)
                compared+=1
    assert digest.hexdigest()==entry['uncompressed_sha256']
    after=source.stat();assert (before.st_size,before.st_mtime_ns)==(after.st_size,after.st_mtime_ns)
    assert sha(source)==entry['raw']['sha256']
    return dict(symbol=symbol,session=session,q0=len(wanted),比較=compared,既知=knowns,最大誤差=max_error,
                原板行=line,原板SHA=entry['raw']['sha256'],純値SHA=sha(cached))


# ----------------------------------------
def main():
    """
    機能: 全83場2商品の独立純値検査を完了票へ保存する。
    引数: なし。
    返り値: None。
    """
    plan_path=DEST/'抽出前固定.json.gz';plan=read(plan_path)
    assert read(DEST/'完了.json')['success']
    for item in plan['Source']:assert sha(Path(item['path']))==item['sha256']
    results=[]
    with ProcessPoolExecutor(max_workers=2) as pool:
        futures=[pool.submit(inspect,e) for e in plan['scenes']]
        for future in as_completed(futures):
            value=future.result();results.append(value)
            print(json.dumps(dict(独立純確認=value['symbol']+'/'+value['session'],q0=value['q0']),ensure_ascii=False),flush=True)
    results.sort(key=lambda x:(x['symbol'],x['session']))
    assert len(results)==166 and sum(x['q0'] for x in results)==75675
    value=dict(成功=True,金融参照=False,特徴核呼出=False,Source=dict(path=str(Path(__file__).resolve()),sha256=sha(Path(__file__))),
               入力票SHA=sha(plan_path),q0=sum(x['q0'] for x in results),比較=sum(x['比較'] for x in results),結果=results)
    (DEST/'独立純特徴監査.json').write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


# ----------------------------------------
if __name__=='__main__':
    main()
