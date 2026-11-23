"""価格時計の遅延を仮定し、自己と相手の同じ固定端点を純特徴へ写す。"""
from dataclasses import dataclass
import numpy as np

DELAYS=(1,5,30,60)
HORIZONS=(60,300,900,1800)
OFFSETS=(0,*HORIZONS)
STALE_LIMIT=60
GAP_LIMIT=300
REASONS={0:'既知',1:'端点が場開始前',2:'過去の有効価格なし',3:'追加停滞60秒超',4:'判断時計が対象時間外',5:'自己の判断時計が既到達時計より後退',6:'自己の判断原行より後の参照'}
FIELDS=('now','line','last','bid','ask','valid','volume','volume_time')


# ----------------------------------------
@dataclass
class Timeline:
    times: np.ndarray
    lines: np.ndarray
    prices: np.ndarray
    positions: np.ndarray
    bad_prefix: np.ndarray
    maximum_tables: tuple
    quality: dict


# ----------------------------------------
def timeline(data: dict,start: float,end: float,max_line: int | None=None) -> Timeline:
    """
    機能: 原順の高水位より後退する時計を捨て、価格秒ごとの最初の有効Lastを作る。
    引数: data(dict[str,np.ndarray])は8列、start/end(float)は場の対象時計、max_line(int|None)は自己prefix上限。
    返り値: Timelineは初回価格と原行・途中時計間隔の索引。受信順を推定しない。
    """
    assert set(data)==set(FIELDS)
    n=len(data['now']);assert all(len(x)==n for x in data.values()) and np.all(np.diff(data['line'])>0)
    used=np.arange(n) if max_line is None else np.flatnonzero(data['line']<=max_line)
    times=data['now'][used];prices=data['last'][used]
    finite=np.isfinite(times)
    maximum=np.maximum.accumulate(np.where(finite,times,-np.inf))
    previous=np.r_[-np.inf,maximum[:-1]] if len(times) else np.empty(0)
    backward=finite&(times<previous)
    valid=finite&~backward&(times>=start)&(times<end)&np.isfinite(prices)&(prices>0)
    positions=used[np.flatnonzero(valid)]
    if len(positions):
        candidate=data['now'][positions];first=np.r_[True,np.diff(candidate)>0]
        positions=positions[first]
    t=np.asarray(data['now'][positions],dtype=np.float64)
    p=np.asarray(data['last'][positions],dtype=np.float64)
    lines=np.asarray(data['line'][positions],dtype=np.int64)
    assert np.all(np.diff(t)>0) and np.all(np.diff(lines)>0)
    gaps=np.r_[0.,np.diff(t)] if len(t) else np.empty(0)
    tables=[gaps]
    width=2
    while width<=len(t):
        half=width//2;prior=tables[-1]
        tables.append(np.maximum(prior[:-half],prior[half:]));width*=2
    quality={'保存行':len(used),'時計後退行':int(backward.sum()),'有効Last行':int(valid.sum()),
        '初回Last時計数':len(t),'小数時計行':int(np.sum(finite&(times!=np.floor(times)))),
        '価格時計300秒超間隔':int(np.sum(gaps>GAP_LIMIT))}
    return Timeline(t,lines,p,positions,np.cumsum(gaps>GAP_LIMIT),tuple(tables),quality)


# ----------------------------------------
def range_max(series: Timeline,lo: np.ndarray,hi: np.ndarray) -> np.ndarray:
    """
    機能: 始点採用時計の次から終点採用時計までの最大時計差を得る。
    引数: series(Timeline)、lo/hi(np.ndarray[int])は有効な端点添字。
    返り値: np.ndarray[float]。同じ採用時計なら0。
    """
    assert np.all(lo>=0) and np.all(hi>=lo) and np.all(hi<len(series.times))
    length=hi-lo;result=np.zeros(len(lo),dtype=np.float64)
    for level,table in enumerate(series.maximum_tables):
        width=1<<level;mask=(length>=width)&(length<2*width)
        if np.any(mask):result[mask]=np.maximum(table[lo[mask]+1],table[hi[mask]-width+1])
    return result


# ----------------------------------------
def features(own: dict,other: dict,q0: list[dict],start: float,end: float) -> tuple[dict,dict]:
    """
    機能: 全q0で4遅延・4窓の両指数log returnと端点/内部品質を作る。
    引数: own/other(dict)は自己/相手の8列、q0(list[dict])はline/time/last、start/end(float)は対象場。
    返り値: tuple[dict[str,np.ndarray],dict]は純配列と価格時計の品質。
    """
    qline=np.asarray([r['line'] for r in q0],dtype=np.int64)
    qtime=np.asarray([r['time'] for r in q0],dtype=np.float64)
    qlast=np.asarray([r['last'] for r in q0],dtype=np.float64)
    assert np.all(np.diff(qline)>0)
    pos=np.searchsorted(own['line'],qline)
    assert np.all(pos<len(own['line'])) and np.array_equal(own['line'][pos],qline)
    assert np.array_equal(own['now'][pos],qtime) and np.array_equal(own['last'][pos],qlast)
    if all('bid' in r and 'ask' in r for r in q0):
        np.testing.assert_array_equal(own['bid'][pos],[r['bid'] for r in q0])
        np.testing.assert_array_equal(own['ask'][pos],[r['ask'] for r in q0])
    high=np.maximum.accumulate(np.where(np.isfinite(own['now']),own['now'],-np.inf))
    before=np.r_[-np.inf,high[:-1]]
    outside=~np.isfinite(qtime)|(qtime<start)|(qtime>=end)
    backward=qtime<before[pos]
    n=len(q0);shape=(n,len(DELAYS),len(OFFSETS),2)
    endpoint_line=np.full(shape,-1,dtype=np.int64)
    endpoint_time=np.full(shape,np.nan,dtype=np.float64)
    endpoint_last=np.full(shape,np.nan,dtype=np.float64)
    endpoint_stale=np.full(shape,np.nan,dtype=np.float64)
    endpoint_reason=np.full(shape,2,dtype=np.uint8)
    indices=np.full(shape,-1,dtype=np.int64)
    query=qtime[:,None,None]-np.asarray(DELAYS)[None,:,None]-np.asarray(OFFSETS)[None,None,:]
    series=[timeline(own,start,end),timeline(other,start,end)]
    for side,clock in enumerate(series):
        idx=np.searchsorted(clock.times,query,side='right')-1
        indices[:,:,:,side]=idx
        exists=(idx>=0)&np.isfinite(query)
        after=np.zeros(exists.shape,dtype=np.bool_)
        if side==0 and len(clock.lines):
            after[exists]=clock.lines[idx[exists]]>np.broadcast_to(qline[:,None,None],query.shape)[exists]
            exists&=~after
        endpoint_reason[:,:,:,side][exists]=0
        endpoint_line[:,:,:,side][exists]=clock.lines[idx[exists]]
        endpoint_time[:,:,:,side][exists]=clock.times[idx[exists]]
        endpoint_last[:,:,:,side][exists]=clock.prices[idx[exists]]
        endpoint_stale[:,:,:,side][exists]=query[exists]-clock.times[idx[exists]]
        endpoint_reason[:,:,:,side][exists&(endpoint_stale[:,:,:,side]>STALE_LIMIT)]=3
        endpoint_reason[:,:,:,side][query<start]=1
        if side==0:endpoint_reason[:,:,:,side][after]=6
        endpoint_reason[:,:,:,side][backward]=5
        endpoint_reason[:,:,:,side][outside]=4
    known=endpoint_reason==0
    returns=np.full((n,len(DELAYS),len(HORIZONS),2),np.nan,dtype=np.float64)
    gap_count=np.full(returns.shape,-1,dtype=np.int32)
    max_gap=np.full(returns.shape,np.nan,dtype=np.float64)
    return_known=np.zeros(returns.shape,dtype=np.bool_)
    for d in range(len(DELAYS)):
        for h in range(len(HORIZONS)):
            for side,clock in enumerate(series):
                mask=known[:,d,0,side]&known[:,d,h+1,side]
                return_known[:,d,h,side]=mask
                if not np.any(mask):continue
                hi=indices[mask,d,0,side];lo=indices[mask,d,h+1,side]
                returns[mask,d,h,side]=np.log(clock.prices[hi]/clock.prices[lo])
                gap_count[mask,d,h,side]=clock.bad_prefix[hi]-clock.bad_prefix[lo]
                max_gap[mask,d,h,side]=range_max(clock,lo,hi)
    paired=np.all(return_known,axis=-1)
    difference=np.where(paired,returns[:,:,:,0]-returns[:,:,:,1],np.nan)
    quality_known=return_known&(gap_count==0)
    paired_quality=np.all(quality_known,axis=-1)
    result=dict(q0_line=qline,q0_time=qtime,q0_last=qlast,q0_target=~outside,q0_backward=backward,
        endpoint_line=endpoint_line,endpoint_time=endpoint_time,endpoint_last=endpoint_last,
        endpoint_stale=endpoint_stale,endpoint_known=known,endpoint_reason=endpoint_reason,
        log_return=returns,return_known=return_known,gap_count=gap_count,max_clock_gap=max_gap,
        quality_known=quality_known,return_difference=difference,difference_known=paired,difference_quality_known=paired_quality)
    return result,{'自己':series[0].quality,'相手':series[1].quality}
