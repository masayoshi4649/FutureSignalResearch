"""純VWAP入力の起算・時計・未知を人工列で確認する。金融は読まない。"""
from pathlib import Path
from datetime import datetime
import importlib.util

HERE=Path(__file__).parent
spec=importlib.util.spec_from_file_location('vw204',HERE/'抽出204.py')
M=importlib.util.module_from_spec(spec);spec.loader.exec_module(M)


def event(line: int, stamp: str, qty: float=100., price: float=4000., **changes) -> dict:
    """
    機能: 内部整合するTOPIX原行の人工値を作る。
    引数: line(int)、stamp(str)、qty(float)、price(float)、changes(dict)。
    返り値: dictは同原行の小列。将来値や金融ラベルは持たない。
    """
    t=datetime.fromisoformat(stamp+'+09:00').timestamp()
    result={'line':line,'time':t,'last':price,'volume':qty,'volume_time':t,
        'native':price if qty else None,'value':qty*price*10000.,'opening_price':4000.,
        'opening_time':datetime.fromisoformat('2026-11-03T17:00:01+09:00').timestamp(),
        'contract':'161120005','exchange':23,'exchange_name':'大阪日通し'}
    result.update(changes);return result


def run() -> None:
    """
    機能: 既知基準と未知・後退・同秒更新の境界を確認して証跡を保存する。
    引数: なし。
    返り値: None。失敗時はassertで停止する。
    """
    checked=[]
    s=M.State('2026-11-04_Day','TOPIX')
    s.add(event(1,'2026-11-04T06:00:01'))
    s.add(event(2,'2026-11-04T08:45:01',110,4010,native=round(440100/110,4),value=440100*10000))
    a=s.snapshot();assert a['native_known'] and a['session_delta']==4010 and a['base']['line']==1
    assert a['native']!=a['session_delta'];checked.append('当日閉場後基準とnativeを別計算')
    # ----------------------------------------
    previous=a.copy();s.add(event(3,'2026-11-04T08:45:01',120,4010,native=round(480200/120,4),value=480200*10000))
    assert a==previous and a['line']==2 and s.snapshot()['line']==3
    checked.append('同秒後続行で過去スナップショットを改変しない')
    # ----------------------------------------
    s=M.State('2026-11-04_Night','TOPIX');s.add(event(1,'2026-11-04T15:45:01'))
    opened=datetime.fromisoformat('2026-11-04T17:00:01+09:00').timestamp()
    s.add(event(2,'2026-11-04T17:00:01',1,4001,opening_price=4001,opening_time=opened))
    a=s.snapshot();assert a['native_known'] and a['epoch']==1 and a['base'] is None and a['session_delta'] is None
    checked.append('夜間起算変更は旧日中基準を破棄')
    # ----------------------------------------
    s=M.State('2026-11-04_Day','TOPIX');s.add(event(1,'2026-11-04T08:45:00',10))
    assert s.snapshot()['native_known'] and s.snapshot()['base'] is None
    checked.append('開始原行の正数量を未観測ゼロへ推定しない')
    s=M.State('2026-11-04_Day','TOPIX');s.add(event(1,'2026-11-04T08:45:00',0))
    s.add(event(2,'2026-11-04T08:45:01',10,4001))
    assert s.snapshot()['session_delta']==4001 and s.snapshot()['base']['volume']==0
    checked.append('開始時の明示ゼロだけ当場基準に使用')
    # ----------------------------------------
    for kind in ('数量時計先行','価格時計後退','native不整合','起算識別欠測','数量欠測'):
        s=M.State('2026-11-04_Day','TOPIX');s.add(event(1,'2026-11-04T06:00:01'))
        good=event(2,'2026-11-04T08:45:02',110,4001);s.add(good)
        before=s.snapshot();bad=event(3,'2026-11-04T08:45:03',120,4001)
        if kind=='数量時計先行':bad['volume_time']=bad['time']+1
        elif kind=='価格時計後退':bad['time']=good['time']-1;bad['volume_time']=bad['time']
        elif kind=='native不整合':bad['native']+=1
        elif kind=='起算識別欠測':bad['opening_time']=None
        else:bad['volume']=None
        s.add(bad);current=s.snapshot()
        assert not current['native_known'] and current['session_delta'] is None and current['continuity']>before['continuity']
        s.add(event(4,'2026-11-04T08:45:04',130,4001));after=s.snapshot()
        assert after['native_known'] and after['continuity']>current['continuity']
        assert after['base']['line']==1
        checked.append(kind+'は当該行を不可、連続区間を分断')
    # ----------------------------------------
    for field in ('volume','value','volume_time','contract','exchange','exchange_name','opening_time','opening_price'):
        s=M.State('2026-11-04_Day','TOPIX');s.add(event(1,'2026-11-04T06:00:01'))
        a=event(2,'2026-11-04T08:45:01',110,4001);s.add(a)
        b=event(3,'2026-11-04T08:45:02',120,4001)
        if field=='volume':b[field]=1;b['value']=4001*10000
        elif field=='value':b[field]=10000;b['native']=round(1/120,4)
        elif field=='volume_time':b[field]=a[field]-1
        elif field=='contract':b[field]='161120006'
        elif field=='exchange':b[field]=24
        elif field=='exchange_name':b[field]='大阪別区間'
        else:b[field]+=1
        s.add(b);assert s.snapshot()['epoch']>=1 and s.snapshot()['base'] is None
        s.add(event(4,'2026-11-04T08:45:03',130,4001));assert s.snapshot()['base'] is None
        checked.append(field+'変更後も古い基準を復活させない')
    # ----------------------------------------
    s=M.State('2026-11-04_Day','TOPIX');s.add(event(1,'2026-11-04T06:00:01'))
    s.add(event(2,'2026-11-04T08:45:01'))
    assert s.snapshot()['native_known'] and s.snapshot()['session_delta'] is None and s.snapshot()['delta_volume']==0
    checked.append('差分数量ゼロを当場VWAPへ割り算しない')
    assert M.clock('2026-11-04T08:45:00',{}) is None and M.number(True) is None
    assert M.number(float('inf')) is None and M.number(0)==0
    checked.append('無時差時計と真偽値と非有限数は欠測')
    M.save(HERE/'人工確認.json',{'成功':True,'金融未使用':True,'SourceSHA':M.ref(HERE/'抽出204.py')['sha256'],
        '件数':len(checked),'確認':checked})
    print('人工確認',len(checked),'成功')


if __name__=='__main__':run()
