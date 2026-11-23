"""金融未参照の人工入力で純板特徴の尺度と原順を確認する。"""
import hashlib
import json
import math
from pathlib import Path
from 特徴核 import State, NAMES


# ----------------------------------------
def row(line, time, sign=1, scale=1):
    """
    機能: 正常板を人工生成し、必要なら符号鏡像と数量倍率を適用する。
    引数: line(int)、time(float)、sign(int)、scale(float)。
    返り値: tuple[dict,tuple]はL1と20段。
    """
    b = 100 + (line % 7)
    buy = [(b-k, (20+k+line % 4)*scale) for k in range(10)]
    sell = [(b+1+k, (25+k+line % 3)*scale) for k in range(10)]
    if sign < 0:
        buy, sell = [(1000-p,q) for p,q in sell], [(1000-p,q) for p,q in buy]
    q = dict(line=line, time=time, last=(buy[0][0]+sell[0][0])/2, b=buy[0][0], a=sell[0][0],
             bq=buy[0][1], aq=sell[0][1], contract='人工')
    return q, (buy, sell)


# ----------------------------------------
def series(sign=1, scale=1, duplicate=False):
    """
    機能: 同じ意味の人工系列を原行数だけ変えて処理する。
    引数: sign(int)、scale(float)、duplicate(bool)は鏡像・量倍率・同値行追加。
    返り値: list[dict]は元観測時点ごとの特徴。
    """
    state, results, line = State(0,1000), [], 0
    for i in range(1,81):
        q, levels = row(i, 10+i//5, sign, scale)
        line += 1
        q['line'] = line
        state.add(q)
        results.append(state.snapshot(q, levels))
        if duplicate:
            for _ in range(3):
                line += 1
                q = dict(q, line=line)
                state.add(q)
    return results


# ----------------------------------------
def main():
    """
    機能: 原順・尺度・境界・未知復帰を検査しSource指紋と共に保存する。
    引数: なし。
    返り値: None。出力は人工確認.json。
    """
    base = series()
    checks = []
    for name, actual, factor in [('鏡像', series(-1), -1), ('数量倍率', series(scale=7), 1),
                                 ('同値行増挿入', series(duplicate=True), 1)]:
        for a,b in zip(base,actual):
            for key in NAMES:
                x,y=a[key],b[key]
                assert x['known']==y['known'] and x['reason']==y['reason'], (name,key)
                if x['known']:
                    assert math.isclose(x['value']*factor,y['value'],abs_tol=1e-12,rel_tol=1e-12),(name,key,x,y)
        checks.append(name)
    assert not base[15]['OFI16']['known'] and base[16]['OFI16']['known']
    assert not base[63]['OFI64']['known'] and base[64]['OFI64']['known']
    checks.append('16回64回の不足境界')
    state=State(0,1000)
    for i in range(1,70):
        q,levels=row(i,10+i//5);state.add(q)
    frozen=state.snapshot(q,levels)
    frozen_bytes=json.dumps(frozen,sort_keys=True)
    q2,levels2=row(70,q['time']);state.add(q2)
    assert json.dumps(frozen,sort_keys=True)==frozen_bytes
    expected=State(0,1000)
    for i in range(1,70):
        q,levels=row(i,10+i//5);expected.add(q)
    assert expected.snapshot(q,levels)==frozen
    checks.append('未来同秒行のprefix不変')
    state=State(0,1000)
    for i in range(1,5):
        q,levels=row(i,10+i);state.add(q)
        assert not state.snapshot(q,levels)['BLOCK4_OFI']['known']
    q,levels=row(5,15);state.add(q)
    x=state.snapshot(q,levels)
    assert x['BLOCK4_OFI']['known'] and x['BLOCK4_OFI']['end_line']==4 and x['BLOCK4_OFI']['available_line']==5
    q,levels=row(6,15);state.add(q)
    assert state.snapshot(q,levels)['BLOCK4_OFI']==x['BLOCK4_OFI']
    checks.append('現ブロック除外と4完了境界公表')
    q,levels=row(7,14);state.add(q)
    assert all(not v['known'] for v in state.snapshot(q,levels).values())
    q,levels=row(8,14.5);state.add(q)
    assert all(not v['known'] for v in state.snapshot(q,levels).values())
    q,levels=row(9,15);state.add(q)
    x=state.snapshot(q,levels)
    assert x['QI1']['known'] and not x['OFI16']['known'] and not x['BLOCK4_OFI']['known']
    checks.append('後退高水位復帰後の再助走')
    for bad in ('bq','a'):
        q,levels=row(10 if bad=='bq' else 12,16 if bad=='bq' else 18)
        q[bad]=0 if bad=='bq' else q['b']
        state.add(q)
        assert all(not v['known'] for v in state.snapshot(q,levels).values())
        q,levels=row(q['line']+1,q['time']+1);state.add(q)
        assert not state.snapshot(q,levels)['OFI16']['known']
    checks.append('零量不正常BBOによる窓破棄')
    state=State(0,1000)
    for i in range(1,18):
        q,levels=row(i,i);state.add(q)
    q=dict(q,line=18,time=200);state.add(q)
    q,levels=row(19,201);state.add(q)
    x=state.snapshot(q,levels)
    assert x['OFI16']['known'] and x['OFI16']['max_clock_gap']==183
    checks.append('同値板中の大時計ギャップも別記')
    here=Path(__file__).parent
    sources=[{'path':p.name,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in (Path(__file__),here/'特徴核.py')]
    result={'成功':True,'金融参照':False,'確認':checks,'Source':sources}
    (here/'人工確認.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False))


# ----------------------------------------
if __name__=='__main__':
    main()
