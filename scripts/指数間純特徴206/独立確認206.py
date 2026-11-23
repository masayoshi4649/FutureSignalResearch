"""206生産核を呼ばず、原順の単純走査と二分探索で全純特徴を独立照合する。"""
from bisect import bisect_right
from collections import Counter
from pathlib import Path
import gzip
import hashlib
import json
import math
import numpy as np

ROOT=Path(__file__).resolve().parents[2]
HERE=Path(__file__).parent
DEST=ROOT/'inputs/00206_両指数の固定端点相対変化'
DELAYS=(1,5,30,60);HORIZONS=(60,300,900,1800)
CHECKED=0;MAX_ERROR=0.


# ----------------------------------------
def read(path: Path) -> object:
    """
    機能: JSON又はgzip JSONを読む。
    引数: path(Path)。
    返り値: object。
    """
    body=path.read_bytes();return json.loads(gzip.decompress(body) if path.suffix=='.gz' else body)


# ----------------------------------------
def fingerprint(path: Path) -> dict:
    """
    機能: 検査Source・入力の内容指紋を得る。
    引数: path(Path)。
    返り値: dictは相対path・byte・SHA。
    """
    with path.open('rb') as stream:sha=hashlib.file_digest(stream,'sha256').hexdigest()
    return {'path':path.relative_to(ROOT).as_posix(),'bytes':path.stat().st_size,'sha256':sha}


# ----------------------------------------
def scan(raw: dict,start: float,end: float,q0: list[dict]) -> tuple:
    """
    機能: 高水位を逐次更新し、初回有効Lastと自己q0の後退状態を独立に求める。
    引数: raw(dict[str,np.ndarray])、start/end(float)、q0(list[dict])。
    返り値: tupleはtimes/lines/prices/gaps、q0後退旗。生産核は使わない。
    """
    requested={r['line']:r for r in q0};backward={};maximum=-math.inf;last_accepted=None
    times=[];lines=[];prices=[]
    for t,line,p in zip(raw['now'],raw['line'],raw['last'],strict=True):
        t=float(t);line=int(line);p=float(p)
        if line in requested:
            q=requested[line];assert t==q['time'] and p==q['last']
            backward[line]=t<maximum
        if not math.isfinite(t):continue
        if t<maximum:continue
        maximum=t
        if t<start or t>=end or not math.isfinite(p) or p<=0:continue
        if t==last_accepted:continue
        assert last_accepted is None or t>last_accepted
        times.append(t);lines.append(line);prices.append(p);last_accepted=t
    assert len(backward)==len(q0)
    return (times,lines,prices,np.diff(times)),backward


# ----------------------------------------
def compare(actual: np.ndarray,expected: np.ndarray,name: str,tolerance: bool=False) -> None:
    """
    機能: 未知を含む全配列を独立期待値へ照合し、属性数と数値誤差を記録する。
    引数: actual/expected(np.ndarray)、name(str)、tolerance(bool)はlog算術のみ。
    返り値: None。
    """
    global CHECKED,MAX_ERROR
    assert actual.shape==expected.shape,(name,actual.shape,expected.shape)
    if tolerance:
        np.testing.assert_allclose(actual,expected,atol=1e-12,rtol=0,equal_nan=True,err_msg=name)
        valid=np.isfinite(expected)
        if np.any(valid):MAX_ERROR=max(MAX_ERROR,float(np.max(np.abs(actual[valid]-expected[valid]))))
    else:np.testing.assert_array_equal(actual,expected,err_msg=name)
    CHECKED+=actual.size


# ----------------------------------------
def expected_pair(raw_own: dict,series: list,q0: list[dict],backward: dict,start: float,end: float) -> dict:
    """
    機能: 全固定端点をbisectで探索し、素朴な価格比と区間最大差を独立計算する。
    引数: raw_own(dict)、series(list)は自己/相手のscan返り値、q0(list)、backward(dict)、start/end(float)。
    返り値: dict[str,np.ndarray]は生産配列に対応する期待値。
    """
    n=len(q0);shape=(n,4,5,2)
    line=np.full(shape,-1,np.int64);time=np.full(shape,np.nan);price=np.full(shape,np.nan);stale=np.full(shape,np.nan)
    reason=np.full(shape,2,np.uint8);indices=np.full(shape,-1,np.int64)
    qline=np.asarray([q['line'] for q in q0],np.int64);qtime=np.asarray([q['time'] for q in q0],float)
    qlast=np.asarray([q['last'] for q in q0],float);target=(qtime>=start)&(qtime<end)
    back=np.asarray([backward[int(x)] for x in qline],bool)
    for qi,q in enumerate(q0):
        for di,delay in enumerate(DELAYS):
            for oi,offset in enumerate((0,*HORIZONS)):
                point=q['time']-delay-offset
                for side,(times,lines,prices,gaps) in enumerate(series):
                    at=bisect_right(times,point)-1;indices[qi,di,oi,side]=at
                    code=2
                    if at>=0:
                        if side==0 and lines[at]>q['line']:code=6
                        else:
                            line[qi,di,oi,side]=lines[at];time[qi,di,oi,side]=times[at];price[qi,di,oi,side]=prices[at]
                            stale[qi,di,oi,side]=point-times[at];code=0 if point-times[at]<=60 else 3
                    if point<start:code=1
                    if back[qi]:code=5
                    if not target[qi]:code=4
                    reason[qi,di,oi,side]=code
    known=reason==0;returns=np.full((n,4,4,2),np.nan);gap_count=np.full(returns.shape,-1,np.int32)
    maxgap=np.full(returns.shape,np.nan);return_known=np.zeros(returns.shape,bool)
    for qi in range(n):
        for di in range(4):
            for hi in range(4):
                for side,(times,lines,prices,gaps) in enumerate(series):
                    if not(known[qi,di,0,side] and known[qi,di,hi+1,side]):continue
                    return_known[qi,di,hi,side]=True
                    a=int(indices[qi,di,hi+1,side]);b=int(indices[qi,di,0,side]);assert b>=a
                    returns[qi,di,hi,side]=math.log(prices[b]/prices[a])
                    section=gaps[a:b]
                    gap_count[qi,di,hi,side]=sum(int(x>300) for x in section)
                    maxgap[qi,di,hi,side]=max(section,default=0.)
    paired=np.all(return_known,axis=-1);quality=return_known&(gap_count==0)
    return dict(q0_line=qline,q0_time=qtime,q0_last=qlast,q0_target=target,q0_backward=back,
        endpoint_line=line,endpoint_time=time,endpoint_last=price,endpoint_stale=stale,endpoint_known=known,endpoint_reason=reason,
        log_return=returns,return_known=return_known,gap_count=gap_count,max_clock_gap=maxgap,quality_known=quality,
        return_difference=np.where(paired,returns[:,:,:,0]-returns[:,:,:,1],np.nan),difference_known=paired,difference_quality_known=np.all(quality,axis=-1))


# ----------------------------------------
def main() -> None:
    """
    機能: 全83場・全75675q0の端点/値/品質を別実装で確認する。
    引数: なし。
    返り値: None。金融ラベルと生産核は読まない。
    """
    plan=read(DEST/'抽出前固定.json.gz');done=read(DEST/'完了.json');assert not plan['financial_labels_used'] and not done['financial_labels_used']
    files={(r['symbol'],r['session']):r for r in done['files']};counts=Counter();checks=[]
    for scene in plan['scenes']:
        data={};series={};backward={}
        for symbol,r in scene['sources'].items():
            p=ROOT/r['path'];assert fingerprint(p)['sha256']==r['sha256']
            with np.load(p,allow_pickle=False) as z:data[symbol]={k:z[k].copy() for k in z.files}
            series[symbol],backward[symbol]=scan(data[symbol],scene['start'],scene['end'],scene['q0'][symbol])
        for symbol in ('NK225','TOPIX'):
            peer='TOPIX' if symbol=='NK225' else 'NK225';q0=scene['q0'][symbol]
            expected=expected_pair(data[symbol],[series[symbol],series[peer]],q0,backward[symbol],scene['start'],scene['end'])
            row=files[(symbol,scene['session'])];path=ROOT/row['file']['path'];assert fingerprint(path)['sha256']==row['file']['sha256']
            with np.load(path,allow_pickle=False) as z:
                assert set(z.files)==set(expected)|{'q0_band','q0_member_mask'}
                for name,value in expected.items():compare(z[name],value,name,name in ('log_return','return_difference'))
                mask=np.asarray([sum(1<<plan['member_order'].index(m) for m in q['members']) for q in q0],np.uint16)
                compare(z['q0_member_mask'],mask,'q0_member_mask')
                # 帯は純条件に使う属性なので既存開始終了に加え別のdatetime変換で検査する。
                from datetime import datetime
                from zoneinfo import ZoneInfo
                band=np.asarray([0 if scene['session'].endswith('_Day') else (1 if datetime.fromtimestamp(q['time'],ZoneInfo('America/New_York')).strftime('%Y-%m-%d %H:%M:%S')<scene['session'][:10]+' 09:30:00' else 2) for q in q0],np.int8)
                compare(z['q0_band'],band,'q0_band')
            counts[symbol]+=len(q0);checks.append({'symbol':symbol,'session':scene['session'],'q0':len(q0),'成功':True})
        for r in scene['sources'].values():assert fingerprint(ROOT/r['path'])['sha256']==r['sha256']
        print(scene['session'],flush=True)
    assert dict(counts)==plan['q0_counts'] and len(checks)==166
    proof={'試行':206,'成功':True,'金融参照':False,'生産核importなし':True,'初回価格は原順の逐次高水位で再構成':True,
        '全端点はbisectで独立探索':True,'内部差は素朴な区間差分走査':True,'q0':dict(counts),'照合属性':CHECKED,
        '最大log算術誤差':MAX_ERROR,'入力全166前後SHA同体':True,'場別':checks,
        'Source':fingerprint(Path(__file__)),'抽出前固定':fingerprint(DEST/'抽出前固定.json.gz'),'完了票':fingerprint(DEST/'完了.json')}
    output=DEST/'独立純特徴確認.json';body=json.dumps(proof,ensure_ascii=False,indent=2)+'\n'
    if output.exists():assert output.read_text(encoding='utf-8')==body
    else:output.write_text(body,encoding='utf-8')
    print(json.dumps({'成功':True,'q0':dict(counts),'照合属性':CHECKED,'最大log算術誤差':MAX_ERROR},ensure_ascii=False),flush=True)


# ----------------------------------------
if __name__=='__main__':main()
