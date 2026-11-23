"""68の設定否定・発動前否定と旧67境界の順序差を人工で確認する。"""

from copy import deepcopy
import importlib.util
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent


def load(path: Path, name: str):
    """人工の実装と固定材料を固有名で読む。

    引数: path(Path)はPython、name(str)は固有名。
    返り値: ModuleTypeは読込結果。市場入力・Engineを期待値に読まない。
    """
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BASE=load(HERE.parent/'定時候補の価格発動/先着の人工検査.py','否定68人工の固定67材料')
L=load(HERE/'先着.py','否定68独立先着の人工対象')
Audit=BASE.Audit


def fixture(values: list[tuple], side: int = 1) -> tuple:
    """固定67の架空価格をそのまま使い候補名だけNへ写す。

    引数: values(list[tuple])はtime/Last/bid/ask/valid、side(int)は±1。
    返り値: tupleはevents/slot/condition。旧fixture・旧globalは変更しない。
    """
    events,slot,condition=BASE.fixture(values,side)
    slot['policy']='N0'
    return events,slot,condition


def self_test() -> dict:
    """否定の等号・gap優先・発動後不適用を明示期待値で検査する。

    引数: なし。
    返り値: dictは人工成功/照合項目数/不一致数/不一致。本物入力・fitは0。
    """
    audit=Audit()
    base=[(180,1000,999,1001,True),(181,1011,1010,1012,True),(182,1012,1011,1013,True),(200,1264,1263,1265,True)]
    for side in (1,-1):
        events,slot,condition=fixture(base,side)
        snapshot=deepcopy((events,slot,condition))
        audit.check('非否定は旧67全属性同値:'+str(side),L.label(events,slot,condition,1200,1300),BASE.L.label(events,slot,condition,1200,1300))
        audit.check('旧入力の非改変:'+str(side),(events,slot,condition),snapshot)
        for setting in (990,989):
            ev,s,c=fixture([(180,setting,setting-1,setting+1,True),*base[1:]],side)
            row=L.label(ev,s,c,1200,1300)
            audit.check('設定反対端の等号/外否定:'+str((side,setting)),
                (row['condition_outcome'],row['outcome'],row['condition_reason'],row['watch_started'],row['watch_quality'],row['filled']),
                ('設定否定','設定否定','設定時に反対端を否定',False,False,False))
            audit.check('設定否定は発動なし:'+str((side,setting)),(row['trigger'],row['end_time'],row['end_line']),(None,180.,1))
        for last in (990,989):
            ev,s,c=fixture([(180,1000,999,1001,True),(181,last,last-1,last+1,True),(182,1011,1010,1012,True),(183,1012,1011,1013,True)],side)
            row=L.label(ev,s,c,1200,1300)
            audit.check('発動前の正常反対端否定:'+str((side,last)),(row['condition_outcome'],row['condition_reason'],row['watch_started'],row['watch_quality'],row['filled']),
                ('前提否定','発動前に反対端を否定',True,False,False))
            audit.check('同枠復活なし:'+str((side,last)),(row['trigger'],row['end_time'],row['end_line']),(None,181,2))
            audit.check('旧67は否定後の回復で発動し得る:'+str((side,last)),BASE.L.label(ev,s,c,1200,1300)['trigger']['line'],3)
        for moment,outcome,quality in ((480,'前提否定',False),(481,'観測不足',True)):
            ev,s,c=fixture([(180,1000,999,1001,True),(moment,990,989,991,True)],side)
            row=L.label(ev,s,c,1200,1300)
            audit.check('gapと否定の優先:'+str((side,moment)),(row['condition_outcome'],row['watch_quality']),(outcome,quality))
        ev,s,c=fixture([(180,1000,999,1001,True),(180,990,989,991,True),(180,1011,1010,1012,True),(181,1012,1011,1013,True)],side)
        row=L.label(ev,s,c,1200,1300)
        audit.check('同秒後行否定で以後発動禁止:'+str(side),(row['condition_outcome'],row['end_line'],row['trigger']),('前提否定',2,None))
        ev,s,c=fixture([(180,1000,999,1001,True),(181,990,989,991,False),(182,1011,1010,1012,True),(183,1012,1011,1013,True)],side)
        audit.check('不正BBOの否定は採用しない:'+str(side),L.label(ev,s,c,1200,1300),BASE.L.label(ev,s,c,1200,1300))
        ev,s,c=fixture([(180,1000,999,1001,True),(181,1011,1010,1012,True),(181,990,989,991,True),(182,990,989,991,True)],side)
        row=L.label(ev,s,c,1200,1300)
        audit.check('entrypendingの否定では取り消さない:'+str(side),(row['filled'],row['trigger']['line'],row['entry_line']),(True,2,4))
        audit.check('発動後は旧67全属性同値:'+str(side),row,BASE.L.label(ev,s,c,1200,1300))
        ev,s,c=fixture([(180,1000,999,1001,True),(480,1000,999,1001,True),(780,1000,999,1001,True),(1080,990,989,991,True)],side)
        audit.check('満了等号は否定より先:'+str(side),L.label(ev,s,c,1200,1300)['condition_outcome'],'未発動')
        ev,s,c=fixture([(180,float('nan'),999,1001,True),(181,990,989,991,True)],side)
        row=L.label(ev,s,c,1200,1300)
        audit.check('設定Last不正は否定でなく観測不足:'+str(side),(row['condition_outcome'],row['watch_started'],row['watch_quality']),('観測不足',False,False))
    ev,s,c=fixture(base)
    c['source'].update(open=1000.,high=1000.,low=1000.,close=1000.);c.update(high=1000.,low=1000.)
    audit.check('零幅の設定等号は新設定否定',L.label(ev,s,c,1200,1300)['condition_outcome'],'設定否定')
    ev[0]['last']=1001
    audit.check('設定既超過を先に維持',L.label(ev,s,c,1200,1300)['condition_outcome'],'既超過')
    audit.check('旧entry集計を純再用',L.entry_stats is L.LEGACY.entry_stats,True)
    return {'人工成功':audit.bad==0,'照合項目数':audit.count,'不一致数':audit.bad,'不一致':audit.examples,
        '本物入力読取':False,'fit':0,'Engine期待値import':False,'市場戦略再生':False}


if __name__=='__main__':
    proof=self_test();print(json.dumps(proof,ensure_ascii=False,indent=2))
    raise SystemExit(0 if proof['人工成功'] else 1)
