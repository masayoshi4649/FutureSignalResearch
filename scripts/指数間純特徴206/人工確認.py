"""206の固定端点、過去prefix、単位差、交換対称性を金融なしで確認する。"""
from pathlib import Path
import hashlib
import json
import numpy as np
from 特徴核 import features,timeline,range_max,DELAYS,HORIZONS

HERE=Path(__file__).parent


# ----------------------------------------
def data(rows: list[tuple]) -> dict:
    """
    機能: 人工の価格時計とLastを8列へ展開する。
    引数: rows(list[tuple[float,float]])はtime/Last。
    返り値: dict[str,np.ndarray]。
    """
    t=np.asarray([r[0] for r in rows],float);p=np.asarray([r[1] for r in rows],float)
    return dict(now=t,line=np.arange(1,len(t)+1,dtype=np.int64),last=p,bid=p-.1,ask=p+.1,
                valid=np.ones(len(t),bool),volume=np.arange(len(t),dtype=float),volume_time=t.copy())


# ----------------------------------------
def q0(raw: dict,line: int) -> list[dict]:
    """
    機能: 人工の判断原行を純識別子へ写す。
    引数: raw(dict)、line(int)は1始まり原行。
    返り値: list[dict]は1点。
    """
    i=line-1;return [dict(line=line,time=float(raw['now'][i]),last=float(raw['last'][i]))]


# ----------------------------------------
def same(a: dict,b: dict,keys: list | None=None) -> None:
    """
    機能: 配列内容を未知を含めて一致確認する。
    引数: a/b(dict)、keys(list|None)は対象列。
    返り値: None。
    """
    for key in (list(a) if keys is None else keys):np.testing.assert_array_equal(a[key],b[key],err_msg=key)


# ----------------------------------------
def main() -> None:
    """
    機能: 金融ラベルを使わず、構造上の不変条件と時計境界を人工検査する。
    引数: なし。
    返り値: None。成功票とSourceSHAを保存する。
    """
    cases=[]
    own=data([(t,100+t/1000) for t in range(0,2201,10)])
    other=data([(t,200+t/2000) for t in range(0,2201,10)])
    base,_=features(own,other,q0(own,201),0,2200)
    assert base['difference_known'].all();cases.append('全4遅延と全4窓の固定端点')
    for di,d in enumerate(DELAYS):
        for oi,h in enumerate((0,*HORIZONS)):
            assert np.all(base['endpoint_time'][0,di,oi]<=2000-d-h)
            assert np.all(base['endpoint_stale'][0,di,oi]==2000-d-h-base['endpoint_time'][0,di,oi])
    cases.append('遅延と追加停滞を区別し未来最近傍を使わない')
    for side in range(2):
        for di in range(4):
            for hi in range(4):
                p0=base['endpoint_last'][0,di,hi+1,side];p1=base['endpoint_last'][0,di,0,side]
                assert abs(base['log_return'][0,di,hi,side]-np.log(p1/p0))<1e-14
    cases.append('log returnは同じ固定端点の価格比')
    scaled_a={k:(v*100 if k in ('last','bid','ask') else v.copy()) for k,v in own.items()}
    scaled_b={k:(v*.01 if k in ('last','bid','ask') else v.copy()) for k,v in other.items()}
    scaled,_=features(scaled_a,scaled_b,q0(scaled_a,201),0,2200)
    for key in ('log_return','return_difference'):np.testing.assert_allclose(base[key],scaled[key],atol=1e-14,rtol=0)
    cases.append('各商品を独立の価格単位倍率にしてもreturn不変')
    swapped,_=features(other,own,q0(other,201),0,2200)
    np.testing.assert_allclose(swapped['return_difference'],-base['return_difference'],atol=1e-14,rtol=0)
    np.testing.assert_array_equal(swapped['log_return'],base['log_return'][...,::-1])
    cases.append('自己相手交換で差の符号だけ反転')
    inverse_a={k:(1e6/v if k=='last' else v.copy()) for k,v in own.items()}
    inverse_b={k:(1e6/v if k=='last' else v.copy()) for k,v in other.items()}
    inverse,_=features(inverse_a,inverse_b,q0(inverse_a,201),0,2200)
    np.testing.assert_allclose(inverse['log_return'],-base['log_return'],atol=1e-14,rtol=0)
    cases.append('逆数価格でlog returnの方向が鏡像')
    prefix_a={k:v[:201].copy() for k,v in own.items()};prefix_b={k:v[other['now']<=1999].copy() for k,v in other.items()}
    prefix,_=features(prefix_a,prefix_b,q0(prefix_a,201),0,2200);same(base,prefix)
    cases.append('自己q0原行prefixと相手t−1価格prefixが全列同体')
    altered_a={k:v.copy() for k,v in own.items()};altered_b={k:v.copy() for k,v in other.items()}
    altered_a['last'][201:]=99999;altered_b['last'][altered_b['now']>1999]=.001
    changed,_=features(altered_a,altered_b,q0(altered_a,201),0,2200);same(base,changed)
    cases.append('未来の価格変更で過去特徴が変わらない')
    duplicate=data([(0,100),(0,999),(60,110),(60,1),(120,120)])
    clock=timeline(duplicate,0,180)
    np.testing.assert_array_equal(clock.prices,[100,110,120]);np.testing.assert_array_equal(clock.lines,[1,3,5])
    duplicate['last'][[1,3]]=[1e8,1e-8]
    np.testing.assert_array_equal(timeline(duplicate,0,180).prices,clock.prices)
    cases.append('同秒最初の有効Lastだけ採用し未来同秒価格変更は不変')
    invalid=data([(0,float('nan')),(0,100),(60,110),(50,999),(60,888),(70,120)])
    clock=timeline(invalid,0,180)
    np.testing.assert_array_equal(clock.times,[0,60,70]);np.testing.assert_array_equal(clock.prices,[100,110,120])
    cases.append('不正Last後の初回有効価格と時計後退除外/高水位復帰')
    back,_=features(invalid,invalid,q0(invalid,4),0,180)
    assert back['q0_backward'][0] and np.all(back['endpoint_reason']==5) and not back['return_known'].any()
    cases.append('自己q0時計後退を未知に保持')
    sparse=data([(0,100),(40,101),(100,102),(101,103),(102,104)])
    fresh=data([(40,101)])
    at60,_=features(sparse,fresh,q0(sparse,4),0,200)
    at61,_=features(sparse,fresh,q0(sparse,5),0,200)
    assert at60['endpoint_known'][0,0,0,1] and at60['endpoint_stale'][0,0,0,1]==60
    assert at61['endpoint_reason'][0,0,0,1]==3 and at61['endpoint_stale'][0,0,0,1]==61
    cases.append('追加停滞60秒は既知/61秒は未知、古い採用値も追跡用に保存')
    beginning,_=features(sparse,sparse,q0(sparse,2),0,200)
    assert np.all(beginning['endpoint_reason'][0,:,1:,:]==1)
    cases.append('場開始前の固定始点を持ち越し補完しない')
    empty=data([])
    absent,_=features(sparse,empty,q0(sparse,4),0,200)
    assert absent['endpoint_reason'][0,0,0,1]==2 and not absent['difference_known'].any()
    cases.append('相手の空入力を全q0未知で残す')
    gap=data([(0,100),(301,110),(360,111),(600,120),(602,121)])
    result,_=features(gap,gap,q0(gap,5),0,1000)
    assert result['return_known'][0,0,1,0] and result['gap_count'][0,0,1,0]==0
    wide,_=features(gap,gap,q0(gap,4),-1000,1000)
    # 5分窓の始点299は0を採り追加停滞が299なので未知。端点鮮度を破ってgapを既知扱いしない。
    assert not wide['return_known'][0,0,1,0]
    long=data([(0,100),(300,110),(601,120),(900,130),(901,131)])
    long_result,_=features(long,long,q0(long,5),0,1000)
    assert long_result['return_known'][0,0,2,0] and long_result['gap_count'][0,0,2,0]==1
    assert long_result['max_clock_gap'][0,0,2,0]==301 and not long_result['quality_known'][0,0,2,0]
    assert np.isfinite(long_result['log_return'][0,0,2,0])
    cases.append('端点既知のreturnと内部301秒gap品質を分離')
    exact=data([(0,100),(300,110),(600,120),(900,130),(901,131)])
    exact_result,_=features(exact,exact,q0(exact,5),0,1000)
    assert exact_result['quality_known'][0,0,2,0] and exact_result['max_clock_gap'][0,0,2,0]==300
    cases.append('内部300秒ちょうどは超過扱いしない')
    zero=data([(0,100),(61,101)])
    zr,_=features(zero,zero,q0(zero,2),0,200)
    assert zr['return_known'][0,0,0,0] and zr['log_return'][0,0,0,0]==0 and zr['max_clock_gap'][0,0,0,0]==0
    cases.append('両端が同一採用価格ならreturn0とgap0')
    outside,_=features(own,other,q0(own,221),0,2200)
    assert not outside['q0_target'][0] and np.all(outside['endpoint_reason']==4)
    cases.append('終了15分前以後のq0は削除せず対象外旗')
    clock=timeline(own,0,2200)
    lo=np.asarray([0,1,20,80,199]);hi=np.asarray([1,19,20,200,219])
    expected=np.asarray([max(np.diff(clock.times[a:b+1]),default=0) for a,b in zip(lo,hi)])
    np.testing.assert_array_equal(range_max(clock,lo,hi),expected)
    cases.append('窓内最大時計差の索引は素朴な差分最大値と一致')
    sources=[]
    for name in ('特徴核.py','人工確認.py'):
        p=HERE/name;sources.append(dict(path=name,bytes=p.stat().st_size,sha256=hashlib.sha256(p.read_bytes()).hexdigest()))
    proof={'試行':206,'成功':True,'金融参照':False,'項目数':len(cases),'項目':cases,'Source':sources}
    (HERE/'人工確認.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'成功':True,'項目数':len(cases)},ensure_ascii=False),flush=True)


# ----------------------------------------
if __name__=='__main__':main()
