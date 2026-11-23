"""将来発動・観測間隔・新入口先着の明示期待値を人工だけで検査する。"""

from copy import deepcopy
import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent


def load(path: Path, name: str):
    """人工対象だけを固有名で読む。

    引数: path(Path)はPython、name(str)は固有名。
    返り値: ModuleTypeは読込結果。Engine・主・本物入力を読まない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


L = load(HERE / "先着.py", "条件発動67の人工対象")


class Audit:
    """小型人工の照合数と不一致を保持する。"""

    def __init__(self) -> None:
        """空の記録を用意する。

        引数: なし。
        返り値: None。
        """
        self.count, self.bad, self.examples = 0, 0, []

    def check(self, name: str, actual: object, expected: object) -> None:
        """明示期待値と独立計算を比較する。

        引数: name(str)は項目、actual/expected(object)は比較対象。
        返り値: None。不一致を小型に保存する。
        """
        self.count += 1
        if actual != expected:
            self.bad += 1
            self.examples.append({"項目": name, "実際": str(actual)[:600], "期待": str(expected)[:600]})


def fixture(values: list[tuple], side: int = 1) -> tuple:
    """180秒設定・1080秒満了の架空足とイベントを作る。

    引数: values(list[tuple])はtime/Last/bid/ask/valid、side(int)は±1。
    返り値: tupleはevents/slot/condition。売りは2000を中心に価格を反射する。
    """
    events = [{"now": t, "line": i, "last": last, "bid": bid, "ask": ask, "valid": valid}
        for i, (t, last, bid, ask, valid) in enumerate(values, 1)]
    slot = {"slot_id": "人工枠", "session": "2026-10-01_Day", "policy": "G0", "scheduled": 180., "time": 180.,
        "line": 1, "side": side, "role": "順行", "ready": True, "reason": "人工", "atr": 50., "D": 50.}
    source = {"session": slot["session"], "index": 0, "minutes": 3, "start": 0., "end": 180., "confirm": 180.,
        "confirm_line": 1, "publish": True, "missing": 0, "open": 1000., "high": 1010., "low": 990., "close": 1000.}
    condition = {"high": 1010., "low": 990., "source": source, "expires": 1080.}
    if side == -1:
        for event in events:
            event["last"], event["bid"], event["ask"] = 2000 - event["last"], 2000 - event["ask"], 2000 - event["bid"]
    return events, slot, condition


def self_test() -> dict:
    """明示価格・時計から全境界と売買鏡像を確認する。

    引数: なし。
    返り値: dictは人工成功/照合項目数/不一致数/不一致。本物入力・fitは0。
    """
    audit = Audit()
    base = [(180, 1000, 999, 1001, True), (181, 1011, 1010, 1012, True),
        (182, 1012, 1011, 1013, True), (200, 1264, 1263, 1265, True)]
    for side in (1, -1):
        events, slot, condition = fixture(base, side)
        before = deepcopy((events, slot, condition))
        got = L.label(events, slot, condition, 1200, 1300)
        audit.check("新入口250鏡像:" + str(side), (got['condition_outcome'],got['filled'],got['outcome'],got['entry_time'],got['entry_line'],got['entry_price']),
            ('約定',True,'250',182,3,1013 if side==1 else 987))
        audit.check("発動と元定時を分離:" + str(side), (got['time'],got['line'],got['trigger']['time'],got['trigger']['line']), (180.,1,181,2))
        audit.check("入力非変更:" + str(side), (events,slot,condition), before)
        audit.check("索引API同値:" + str(side), L.label(L.prepare_events(events),slot,condition,1200,1300), got)
        changed = deepcopy(events)
        changed[0]['last'] = 1011 if side==1 else 989
        state = L.label(changed,slot,condition,1200,1300)
        audit.check("設定時既超過拒否:" + str(side), (state['condition_outcome'],state['filled'],state['watch_started'],state['watch_quality']), ('既超過',False,False,False))
        changed[0]['last'] = condition['high'] if side==1 else condition['low']
        audit.check("設定等号可:" + str(side), L.label(changed,slot,condition,1200,1300)['filled'], True)
        changed[0]['last'] = float('nan')
        state = L.label(changed,slot,condition,1200,1300)
        audit.check("設定Last不正は未監視・品質非加算:" + str(side), (state['condition_outcome'],state['watch_started'],state['watch_quality']), ('観測不足',False,False))
        for t, expected in ((480,True),(481,False)):
            sequence = [(180,1000,999,1001,True),(t,1011,1010,1012,True),(t+1,1012,1011,1013,True)]
            ev,s,c = fixture(sequence,side)
            state = L.label(ev,s,c,1200,1300)
            audit.check("監視300境界:" + str((side,t)), (state['filled'],state['watch_quality']), (expected,not expected))
        for final, expected in ((780,'未発動'),(779,'観測不足')):
            ev,s,c = fixture([(180,1000,999,1001,True),(480,1000,999,1001,True),(final,1000,999,1001,True),(1080,1011,1010,1012,True)],side)
            state = L.label(ev,s,c,1200,1300)
            audit.check("満了時gap・等号後行は不可:" + str((side,final)), (state['condition_outcome'],state['trigger'],state['end_time']), (expected,None,1080.))
        ev,s,c = fixture([(180,1000,999,1001,True),(180,1011,1010,1012,True),(180,1012,1011,1013,True),(181,1012,1011,1013,True)],side)
        state = L.label(ev,s,c,1200,1300)
        audit.check("同秒後行発動・+1秒で初fill:" + str(side), (state['trigger']['line'],state['entry_line'],state['entry_time']), (2,4,181))
        for fill_time, expected in ((211,True),(212,False)):
            ev,s,c = fixture([(180,1000,999,1001,True),(181,1011,1010,1012,True),(fill_time,1012,1011,1013,True)],side)
            audit.check("約定TTL30境界:" + str((side,fill_time)), L.label(ev,s,c,1200,1300)['filled'], expected)
        ev,s,c = fixture([(180,1000,999,1001,True),(480,1000,999,1001,True),(780,1000,999,1001,True),
            (1050,1011,1010,1012,True),(1080,1012,1011,1013,True)],side)
        state = L.label(ev,s,c,1200,1300)
        audit.check("次定時取消がTTL30等号より優先:" + str(side), (state['condition_outcome'],state['filled'],state['end_time'],state['end_line']), ('発動未約定',False,1080.,4))
        ev,s,c = fixture([(180,1000,999,1001,True),(480,1000,999,1001,True),(780,1000,999,1001,True),
            (999,1011,1010,1012,True),(1000,1012,1011,1013,True)],side)
        denied=False
        try:L.label(ev,s,c,1000,1300)
        except ValueError:denied=True
        audit.check("force前に条件満了しない入力を拒否:" + str(side), denied, True)
        # ----------------------------------------
        # force最初同秒正常BBOで期限を決め、後行の別障壁へ進まない。
        seq = [(180,1000,999,1001,True),(181,1011,1010,1012,True),(182,1012,1011,1013,True),
            (480,1000,1000,1002,True),(780,1000,1000,1002,True),(1080,1000,1000,1002,True),
            (1200,1013,1013,1015,True),(1200,1264,1263,1265,True)]
        ev,s,c = fixture(seq,side)
        state = L.label(ev,s,c,1200,1300)
        audit.check("force初同秒行を含み後行を除外:" + str(side), (state['outcome'],state['end_line']), ('期限',7))
        ev,s,c = fixture(base[:3]+[(483,1264,1263,1265,True)],side)
        state = L.label(ev,s,c,1200,1300)
        audit.check("保有先着300超は障壁より不足優先:" + str(side), (state['outcome'],state['mfe']), ('不足',250))
        ev,s,c = fixture(base[:3]+[(200,887,886,888,True)],side)
        audit.check("新entryの逆125:" + str(side), L.label(ev,s,c,1200,1300)['outcome'], '125')
    # ----------------------------------------
    # LastとBBOの条件、公開SOURCE、零幅、保存順の独立確認。
    ev,s,c = fixture([(180,1000,999,1020,True),(300,1000,999,1020,True),(600,1000,999,1020,True),(900,1000,999,1020,True)])
    audit.check("ask超過だけで発動しない", L.label(ev,s,c,1200,1300)['trigger'], None)
    ev,s,c = fixture([(180,1000,999,1001,True),(181,1011,1010,1012,False),(182,1000,999,1001,True),
        (480,1000,999,1001,True),(780,1000,999,1001,True),(1079,1000,999,1001,True)])
    audit.check("BBO不正Last突破を発動にしない", L.label(ev,s,c,1200,1300)['condition_outcome'], '未発動')
    ev,s,c = fixture([(180,1000,999,1001,True),(181,1011,1010,1012,True),(182,float('nan'),1011,1013,True),(200,1264,1263,1265,True)])
    audit.check("発動後のfillはBBOだけでよい", L.label(ev,s,c,1200,1300)['entry_line'], 3)
    ev,s,c = fixture([(180,1000,999,1001,True),(400,float('nan'),999,1001,True),(481,1011,1010,1012,True)])
    audit.check("Last不正BBOで監視gapを埋めない", L.label(ev,s,c,1200,1300)['watch_quality'], True)
    ev,s,c = fixture([(180,1000,999,1001,True),(481,float('nan'),999,1001,True),(482,1011,1010,1012,True)])
    audit.check("不正Last原行でgap取消時計を残す", (L.label(ev,s,c,1200,1300)['end_time'],L.label(ev,s,c,1200,1300)['end_line']), (481,2))
    ev,s,c = fixture([(180,1000,999,1001,True),(481,1000,999,1001,False)])
    audit.check("後続正常なしでも最初到着行でgap取消", (L.label(ev,s,c,1200,1300)['end_time'],L.label(ev,s,c,1200,1300)['end_line']), (481,2))
    ev,s,c = fixture([(180,1000,999,1001,True),(181,1011,1010,1012,True),(182,1012,1011,1013,True)])
    c['source'].update(open=1000.,high=1000.,low=1000.,close=1000.);c.update(high=1000.,low=1000.)
    audit.check("零幅sourceは有効", L.label(ev,s,c,1200,1300)['watch_started'], True)
    for kind in ('future','width','source_price','expires','duplicate_line','clock_back'):
        events,slot,condition = fixture(base)
        if kind=='future':condition['source']['confirm_line']=2
        elif kind=='width':condition['source']['start']=-1
        elif kind=='source_price':condition['high']+=1
        elif kind=='expires':condition['expires']+=1
        elif kind=='duplicate_line':events[1]['line']=1
        else:events[1]['now']=179
        denied = False
        try:L.label(events,slot,condition,1200,1300)
        except ValueError:denied=True
        audit.check("不正拒否:"+kind,denied,True)
    rows = [{'slot_id':'遅い元枠','session':'2026-10-01_Day','filled':True,'outcome':'250','entry_time':20,'entry_line':20,'end_time':30,'end_line':30},
        {'slot_id':'早い新規','session':'2026-10-01_Day','filled':True,'outcome':'125','entry_time':10,'entry_line':10,'end_time':25,'end_line':25},
        {'slot_id':'等号','session':'2026-10-01_Day','filled':True,'outcome':'250','entry_time':25,'entry_line':25,'end_time':28,'end_line':28},
        {'slot_id':'次','session':'2026-10-01_Day','filled':True,'outcome':'250','entry_time':26,'entry_line':26,'end_time':32,'end_line':32}]
    statistics = L.entry_stats(rows,'学習',lambda value:'学習')
    audit.check("entry順ソート後にstrict非重複", (statistics['約定'],statistics['間引き約定'],statistics['間引き250']), (4,2,1))
    return {'人工成功':audit.bad==0,'照合項目数':audit.count,'不一致数':audit.bad,'不一致':audit.examples,
        '本物入力読取':False,'fit':0,'Engine期待値import':False,'市場戦略再生':False}


if __name__ == '__main__':
    proof = self_test()
    print(json.dumps(proof,ensure_ascii=False,indent=2))
    raise SystemExit(0 if proof['人工成功'] else 1)
