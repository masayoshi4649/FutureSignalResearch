"""68の発動前否定と保存条件運用をEngine再生なしで独立に照合する。"""

from bisect import bisect_left, bisect_right
from collections import Counter, defaultdict
from copy import deepcopy
from datetime import datetime
from decimal import Decimal
import argparse
import hashlib
import importlib.util
import json
import math
from pathlib import Path
from urllib.parse import urlencode, urljoin

ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT / "study/00068_発動前の反対端否定で条件を取り消す"
WORK = ROOT / "work/条件発動前の否定/00068"
OLD = ROOT / "study/00067_定時候補を将来価格の突破で発動"
OLDWORK = ROOT / "work/定時候補の価格発動/00067"
LEDGER = ROOT / "work/定時候補の価格発動/67完了記録.json"
PREFLIGHT = ROOT / "work/条件発動前の否定/保存接続確認.json"
POLICIES, CONTROLS = ("N0", "N1"), ("G0", "G1")
PERIODS = ("学習", "条件選択", "後続検査")
BINDING = ("slot_id", "session", "scheduled", "time", "line")
SLOT_FIELDS = {"scheduled", "time", "line", "side", "role", "atr", "D", "reason", "ready", "slot_id"}


def load(path: Path, name: str):
    """固定の読取補助だけを固有名で読み大域値を変えない。

    引数: path(Path)はPython、name(str)は固有名。
    返り値: ModuleTypeは読込結果。新Engine・主を期待値に呼ばない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


R67 = load(ROOT / "scripts/定時候補の価格発動/保存検証.py", "発動前否定68の固定67監査")
A, P, R55 = R67.A, R67.P, R67.R55
fingerprint = A.fingerprint


def expected_condition(slot: dict, frames: list[dict]) -> dict:
    """旧純判断の現在足を当時最新の公開3分銀行と独立に結ぶ。

    引数: slot(dict)は旧67純候補、frames(list[dict])はSOURCE13。
    返り値: dictは固定high/low/source/expires。新主のcondition_forは呼ばない。
    """
    visible = [row for row in frames if row["publish"] is True and row["end"] <= slot["scheduled"]
        and row["confirm"] is not None and row["confirm_line"] is not None
        and (row["confirm"], row["confirm_line"]) <= (slot["time"], slot["line"])]
    if not visible:
        raise ValueError("条件の当時公開足がない")
    current = max(visible, key=lambda row: (row["end"], row["index"]))
    saved = slot["feature"]["base"]["base"]["sources"]["current"]
    if not R67.R66.R65.S63.strict_equal(current, saved):
        raise ValueError("保存現在足と独立の最新公開足に差")
    if current["minutes"] != 3 or current["missing"] != 0 or current["end"] - current["start"] != 180 or current["confirm"] < current["end"]:
        raise ValueError("条件の完全公開3分足が不正")
    if not all(A.finite(current[key]) and current[key] > 0 for key in ("open", "high", "low", "close")):
        raise ValueError("条件の価格有限性不成立")
    if not current["low"] <= min(current["open"], current["close"]) <= max(current["open"], current["close"]) <= current["high"]:
        raise ValueError("条件OHLC順序不正")
    return {"high": current["high"], "low": current["low"], "source": deepcopy(current), "expires": slot["scheduled"] + 900}


def expected_label(tape: dict, slot: dict, condition: dict, force: float, end: float, source, oracle) -> tuple:
    """固定67の独立firstgap/crossより前の正常反対端否定を挿入する。

    引数: tape/slot/condition(dict)は原配列と凍結入力、force/end(float)は期限、source/oracleは固定補助。
    返り値: tuple[dict,float|None]は新label全文と最終正常時計。新label・Engineを期待値に呼ばない。
    """
    result,last=R67.expected_label(tape,slot,condition,force,end,source,oracle)
    if not result['watch_started']:
        return result,last
    events=tape['events'];np=source.np
    setting=int(np.searchsorted(events['line'],slot['line']))
    side=slot['side'];opposite=condition['low'] if side==1 else condition['high']
    if side*(float(events['last'][setting])-opposite)<=0:
        result.update(condition_outcome='設定否定',condition_reason='設定時に反対端を否定',outcome='設定否定',
            watch_started=False,watch_quality=False,trigger=None,request_time=None,request_line=None,
            filled=False,end_time=slot['time'],end_line=slot['line'])
        for key in ('entry_time','entry_line','entry_price','mfe','mae'):result.pop(key,None)
        return result,None
    deadline=min(condition['expires'],force,end)
    normal=events['valid'] & np.isfinite(events['bid']) & np.isfinite(events['ask']) & (events['bid']>0) & (events['bid']<events['ask'])
    observed=normal & np.isfinite(events['last']) & (events['last']>0)
    denied=np.flatnonzero(observed & (events['line']>slot['line']) & (events['now']<deadline) & (side*(events['last']-opposite)<=0))
    if not len(denied):
        return result,last
    position=int(denied[0]);key=(float(events['now'][position]),int(events['line'][position]))
    boundary=(result['trigger']['time'],result['trigger']['line']) if result['trigger'] is not None else (result['end_time'],result['end_line'])
    # ----------------------------------------
    # 同行gapは否定より先、発動後の否定は注文待ち・保有へ適用しない。
    if key>=boundary:
        return result,last
    result.update(condition_outcome='前提否定',condition_reason='発動前に反対端を否定',outcome='前提否定',
        watch_quality=False,trigger=None,request_time=None,request_line=None,filled=False,end_time=key[0],end_line=key[1])
    for name in ('entry_time','entry_line','entry_price','mfe','mae'):result.pop(name,None)
    return result,key[0]

def entry_summary(rows: list[dict], period: str, source) -> dict:
    """新entry key順に並べた先着へ旧支持算術だけを適用する。

    引数: rows(list[dict])は新label、period(str)は期、source(ModuleType)は旧監査。
    返り値: dictはC49互換の支持・率。入力の予定順を間引き順としない。
    """
    ordered = sorted(rows, key=lambda row: (row.get("entry_time", math.inf),row.get("entry_line",math.inf),row["slot_id"]))
    return source.entry_summary(ordered, period)


def check_orders(operation: dict, labels: dict, slots: dict, tape: dict, force: float, end: float, source, audit) -> None:
    """entryは条件出自と新期限、exitは固定49の純補助へ照合する。

    引数: operation/labels/slots/tape(dict)は保存運用と独立期待値、force/end(float)は場時計、source/auditは固定補助。
    返り値: None。新運用を再生せず要求・最初板・一枚を検査する。
    """
    audit.check("全注文ID一意",len(operation['orders']),len({row['id'] for row in operation['orders']}))
    entries = [order for order in operation['orders'] if order['kind']=='entry']
    triggered = {identity for identity,row in operation['conditions'].items() if row['registered'] and row['trigger'] is not None}
    audit.check("実発動とentry要求集合",{order['slot']['slot_id'] for order in entries},triggered)
    audit.check("同枠一回要求",len(entries),len(triggered))
    positions = {row['id']:row for row in operation['closed']}
    if operation['final_state']['position']:
        positions[operation['final_state']['position']['id']]=operation['final_state']['position']
    for order in entries:
        identity=order['slot']['slot_id']; expected=labels[identity]; slot=slots[identity]
        audit.check("要求はtrigger出典",(order['request_time'],order['request_line']),
            (expected['trigger']['time'],expected['trigger']['line']))
        audit.check("entry凍結純slot",order['slot'],{key:slot[key] for key in SLOT_FIELDS})
        audit.check("entry+1/TTL30",(order['eligible_time'],order['expires']),(order['request_time']+1,order['request_time']+30))
        audit.check("entry約定可否",order['status'],'filled' if expected['filled'] else 'cancelled')
        if expected['filled']:
            audit.check("entry最初正常BBO",(order['fill_time'],order['fill_line'],order['fill_price']),
                (expected['entry_time'],expected['entry_line'],expected['entry_price']))
            matching=[row for row in positions.values() if row['slot_id']==identity]
            audit.check("entry一建玉",len(matching),1)
            if matching:
                row=matching[0]
                audit.check("entry固定ATR/D/役割",(row['entry_atr'],row['D'],row['side'],row['role']),
                    (slot['atr'],slot['D'],slot['side'],slot['role']))
        else:
            audit.check("entry取消期限",order['cancel_time'],min(order['expires'],expected['condition']['expires'],force,end))
    exit_view={**operation,'orders':[row for row in operation['orders'] if row['kind']=='exit'],'decisions':[]}
    source.check_orders(exit_view,tape,audit)


def check_conditions(block: dict, expected: dict, observed: dict, tape: dict, source, audit) -> None:
    """全予定判断と登録されたwatchの出自・終端・保守活動を確認する。

    引数: block(dict)は保存詳細、expected/observed(dict)は独立labelと最終監視時計、tape(dict)は元配列、source/auditは固定補助。
    返り値: None。全Engineの戦略再実装はせず条件ごとに独立照合する。
    """
    operation, slots = block['operation'], block['slots']
    _, _, _, scheduled = source.calendar(block['session'])
    audit.check('全予定25/49',[row['scheduled'] for row in slots],scheduled)
    audit.check('全定時判断順',[row['scheduled'] for row in operation['decisions']],scheduled)
    audit.check('全条件集合',set(operation['conditions']),set(block['conditions']))
    audit.check('全条件と独立label集合',set(operation['conditions']),set(expected))
    events=tape['events']; trace=[]
    records=operation['conditions']
    decisions={row['slot_id']:row for row in operation['decisions']}
    audit.check('全定時ID一意',len(decisions),len(slots))
    for slot in slots:
        identity=slot['slot_id']; decision=decisions[identity]
        audit.check('純判断を不変保持',{key:decision[key] for key in SLOT_FIELDS},{key:slot[key] for key in SLOT_FIELDS})
        i=int(source.np.searchsorted(events['now'],slot['scheduled'],side='left'))
        present=i<len(events['now']) and events['now'][i]<=slot['scheduled']+30
        audit.check('最初価格行の定時bind',(slot['time'],slot['line']),
            (float(events['now'][i]),int(events['line'][i])) if present else (slot['scheduled'],None))
        normal=present and int(events['line'][i]) in tape['normal_lines']
        if not normal:
            action='判定不能'
        elif decision['pending_kind'] is not None:
            action='処理中'
        elif decision['holding']:
            action='保有継続'
        elif decision['watching']:
            action='処理中'
        elif not slot['ready']:
            action='判定不能'
        elif not slot['side']:
            action='待ち'
        else:
            state=expected[identity]
            action='判定不能' if not state['watch_started'] and state['condition_outcome']=='観測不足' else '待ち' if state['condition_outcome'] in ('既超過','設定否定') else '条件登録'
        audit.check('当時action優先',decision['action'],action)
        audit.check('待ち・判定不能bool',(decision['wait'],decision['activity_valid']),(action=='待ち',action!='判定不能'))
        logs=[log for log in operation['trail'] if log['action']=='定時判断' and log.get('decision',{}).get('slot_id')==identity]
        audit.check('定時ログ一件',len(logs),1)
        if logs:
            state=logs[0]['state']
            audit.check('定時保有snapshot',decision['holding'],state['position'] is not None)
            audit.check('定時pending snapshot',decision['pending_kind'],state['pending']['kind'] if state['pending'] else None)
        if identity not in records:
            continue
        record, prediction=records[identity],expected[identity]
        registered=action=='条件登録'
        audit.check('登録と定時action',record['registered'],registered)
        audit.check('条件出典全文',record['condition'],block['conditions'][identity])
        audit.check('条件元設定',record['origin_slot'],{key:slot[key] for key in BINDING})
        audit.check('条件の凍結純slot',record['slot'],{key:slot[key] for key in SLOT_FIELDS})
        audit.check('条件終了状態',record['status'],'終了')
        if not registered:
            outcome='観測不足' if action=='判定不能' else prediction['condition_outcome'] if prediction['condition_outcome'] in ('既超過','設定否定') and action=='待ち' and not decision['holding'] and decision['pending_kind'] is None else '未登録'
            audit.check('不登録の条件結果',record['condition_outcome'],outcome)
            audit.check('不登録でwatch/発動/entryなし',(record['watch_started'],record['watch_quality'],record['trigger'],record['entry_filled']),(False,False,None,False))
            audit.check('不登録終了key',(record['end_time'],record['end_line']),(slot['time'],slot['line']))
            trace.append({'action':'条件未登録','slot_id':identity,'time':slot['time'],'line':slot['line'],'reason':decision['decision_reason']})
            continue
        audit.check('登録監視の開始と品質',(record['watch_started'],record['watch_quality']),(True,prediction['watch_quality']))
        audit.check('独立発動key',record['trigger'],prediction['trigger'])
        audit.check('独立最終観測時計',record['last_observation_time'],observed[identity])
        audit.check('entry条件結果',(record['condition_outcome'],record['entry_filled']),(prediction['condition_outcome'],prediction['filled']))
        audit.check('条件のrequest key',(record['request_time'],record['request_line']),(prediction['request_time'],prediction['request_line']))
        trace.append({'action':'条件登録','slot_id':identity,'time':slot['time'],'line':slot['line'],'reason':str(slot['reason'])})
        if prediction['trigger']:
            trigger=prediction['trigger']
            trace.append({'action':'条件発動','slot_id':identity,'time':trigger['time'],'line':trigger['line'],'reason':'将来Lastのstrict突破'})
        if prediction['filled']:
            terminal=prediction['entry_time'],prediction['entry_line']
            reason='発動後の最初正常BBO'; terminal_action='条件新規約定'
            audit.check('条件実entry',(record['entry_time'],record['entry_line'],record['entry_price']),
                (prediction['entry_time'],prediction['entry_line'],prediction['entry_price']))
        else:
            terminal=prediction['end_time'],prediction['end_line']
            reason=prediction['condition_reason']; terminal_action='条件取消'
            if prediction['trigger']:
                reason='次定時満了' if block['conditions'][identity]['expires']<=prediction['trigger']['time']+30 else '新規TTL30秒'
                terminal_action='条件新規取消'
        audit.check('条件の終了key',(record['end_time'],record['end_line']),terminal)
        audit.check('条件の終了理由',record['condition_reason'],reason)
        trace.append({'action':terminal_action,'slot_id':identity,'time':terminal[0],'line':terminal[1],'reason':reason})
    sort=lambda row:(row['time'],-1 if row['line'] is None else row['line'],row['slot_id'],row['action'])
    audit.check('条件追尾の全遷移',sorted(operation['condition_trace'],key=sort),sorted(trace,key=sort))
    counts=Counter(row['action'] for row in operation['decisions'])
    registered=sum(row['registered'] for row in records.values())
    unfilled=sum(row['registered'] and not row['entry_filled'] for row in records.values())
    n=len(slots); wait=counts['待ち']; invalid=counts['判定不能']
    conservative=wait+invalid+unfilled
    audit.check('条件登録数とaction',registered,counts['条件登録'])
    metrics=operation['metrics']
    for key,value in {'予定枠数':n,'判断別数':{name:counts[name] for name in ('条件登録','待ち','保有継続','処理中','判定不能')},
        '待ち数':wait,'主待ち率':wait/n,'保守待ち率上限':conservative/n,'全枠判定可能':invalid==0,
        '待ち率条件適格':2*conservative<=n,'条件登録数':registered,'条件未約定':unfilled}.items():
        audit.check('条件活動:'+key,metrics[key],value)
    insufficient=sum(row['registered'] and row['watch_quality'] for row in records.values())
    audit.check('監視不足quality件数',operation['quality']['条件監視観測不足取消数'],insufficient)
    if insufficient:
        audit.check('監視不足は損益確定注意',bool(operation['quality']['損益注意理由']),True)
    audit.check('場末watchなし',operation['final_state']['watch'],None)


def operation_summary(accounts: list[dict], period: str, source, summary) -> dict:
    """旧現金集計へ実登録未約定の保守分子を独立に追加する。

    引数: accounts(list[dict])は独立会計と条件、period(str)は期、source/summaryは固定純補助。
    返り値: dictは主の新運用表。未発動を非待ち成功へ加えない。
    """
    result=summary.operation_summary(accounts,period,source)
    selected=[row for row in accounts if source.span(row['session'])==period]
    registered=sum(item['registered'] for row in selected for item in row['conditions'].values())
    unfilled=sum(item['registered'] and not item['entry_filled'] for row in selected for item in row['conditions'].values())
    n=result['予定枠']; numerator=result['待ち数']+result['判定不能']+unfilled
    result.update(条件登録数=registered,条件未約定=unfilled,待ち率保守上限=numerator/n if n else None,活動適格=bool(n) and 2*numerator<=n)
    return result


def stage_summary(slots: list[dict], labels: list[dict], accounts: list[dict], period: str, source) -> dict:
    """全枠から条件・発動・仮約定・実新規を別分母で数える。

    引数: slots/labels/accounts(list[dict])は保存純判断・独立先着・会計、period(str)は期、sourceは固定暦。
    返り値: dictは8項目。実条件登録は一建玉占有を反映した値。
    """
    ss=[row for row in slots if source.span(row['session'])==period]
    ll=[row for row in labels if source.span(row['session'])==period]
    aa=[row for row in accounts if source.span(row['session'])==period]
    records=[item for row in aa for item in row['conditions'].values()]
    return {'全予定枠':len(ss),'純候補':sum(bool(row['side']) for row in ss),
        '条件結果別':dict(Counter(row['condition_outcome'] for row in ll)),
        '発動':sum(row['trigger'] is not None for row in ll),'仮約定':sum(row['filled'] for row in ll),
        '実条件登録':sum(row['registered'] for row in records),'実新規':sum(len(row['closed'])+row['unresolved'] for row in aa),
        '実登録未約定':sum(row['registered'] and not row['entry_filled'] for row in records)}


def comparison_summary(new: list[dict], old: list[dict], period: str, source) -> dict:
    """同純候補の結果対と両約定時の取得差を独立算術で求める。

    引数: new/old(list[dict])は否定あり/なしの条件ラベル、period(str)は期、sourceは固定暦。
    返り値: dictは被覆と条件付き平均。両約定だけを全体改善としない。
    """
    before={row['slot_id']:row for row in old if source.span(row['session'])==period}
    after=[row for row in new if source.span(row['session'])==period]
    if {row['slot_id'] for row in after}!=set(before):
        raise ValueError('新旧純候補の入口集合差')
    pairs=[(row,before[row['slot_id']]) for row in after]
    both=[(a,b) for a,b in pairs if a['filled'] and b['filled']]
    prices=[float(Decimal(a['side'])*(Decimal(str(a['entry_price']))-Decimal(str(b['entry_price'])))) for a,b in both]
    return {'同じ純候補':len(pairs),'両約定':len(both),'旧のみ約定':sum(b['filled'] and not a['filled'] for a,b in pairs),
        '新のみ約定':sum(a['filled'] and not b['filled'] for a,b in pairs),
        '結果対':dict(Counter(b['outcome']+'→'+a['condition_outcome']+'/'+a['outcome'] for a,b in pairs)),
        '両約定の平均追随pt':sum(prices)/len(both) if both else None,
        '両約定の平均取得遅延秒':sum(a['entry_time']-b['entry_time'] for a,b in both)/len(both) if both else None}


def denial_summary(new: list[dict], old: list[dict], period: str, source, audit) -> dict:
    """否定された集合と、旧67の全属性を保つ集合を独立に分ける。

    引数: new/old(list[dict])は新旧条件ラベル、period(str)は期、source/auditは固定補助。
    返り値: dictは否定比較10項目。非否定の変化や新規追加を拒否する。
    """
    before={row['slot_id']:row for row in old if source.span(row['session'])==period}
    after=[row for row in new if source.span(row['session'])==period]
    if {row['slot_id'] for row in after}!=set(before) or len(after)!=len(before):
        raise ValueError('否定比較の純候補母数差')
    denied=[];retained=filled=new_only=0
    for row in after:
        prior=before[row['slot_id']]
        if row['condition_outcome'] in ('設定否定','前提否定'):
            audit.check('否定でtrigger/entry/品質注意なし',(row['trigger'],row['filled'],row['watch_quality']),(None,False,False))
            denied.append((row,prior))
        else:
            audit.check('非否定は旧67全属性同値',R67.R66.R65.S63.strict_equal({**row,'policy':prior['policy']},prior),True)
            retained+=1
        if row['filled']:
            new_only+=not prior['filled']
            audit.check('新fillは旧fillと同key価格結果',prior['filled'] and all(row[key]==prior[key] for key in
                ('entry_time','entry_line','entry_price','outcome','end_time','end_line','mfe','mae')),True)
            filled+=1
    return {'同じ純候補':len(after),'設定否定':sum(row['condition_outcome']=='設定否定' for row in after),
        '前提否定':sum(row['condition_outcome']=='前提否定' for row in after),'非否定の全属性一致':retained,
        '否定群の旧結果':dict(Counter(prior['condition_outcome']+'/'+prior['outcome'] for _,prior in denied)),
        '旧仮約定の除外':sum(prior['filled'] for _,prior in denied),'旧250の除外':sum(prior['outcome']=='250' for _,prior in denied),
        '旧125の除外':sum(prior['outcome']=='125' for _,prior in denied),'両約定の時刻価格結果一致':filled,'新のみ仮約定':new_only}


def check_api(base: str | None, resources: list[dict], accounts: list[dict], source, audit) -> dict:
    """184資源と新N0/N1各一代表の約定・台帳をHTTP照合する。

    引数: base(str|None)はURL、resources/accounts(list[dict])は保存値、source/auditは固定補助。
    返り値: dictはAPI範囲。未指定は未検証とする。
    """
    if not base:
        return {'実行':False,'理由':'--viewer-url未指定。API未検証、新92保存約定は全件照合'}
    query={'catalog_path':(STUDY/'一覧.resources.json').relative_to(ROOT).as_posix()}
    listing,_,_=source.fetch_json(base+'/api/resources?'+urlencode(query))
    audit.check('API184資源全集合',{row['id'] for row in listing['resources']},{row['id'] for row in resources})
    audit.check('API184資源数',len(listing['resources']),184)
    representatives=[]
    for policy in POLICIES:
        account=sorted([row for row in accounts if row['candidate']==policy],key=lambda row:(-abs(row['ledger']['5']),row['session']))[0]
        resource=next(row for row in resources if row['method_id']==policy and row['session']==account['session'])
        parameters={**query,'resource':resource['id'],'interval':'5','price':'last','width':1000,'height':700}
        meta,_,_=source.fetch_json(base+'/api/chart?'+urlencode(parameters))
        data,raw,headers=source.fetch_json(urljoin(base+'/',meta['data_url']))
        audit.check('API本文SHA',hashlib.sha256(raw).hexdigest(),meta['data_sha256'])
        audit.check('APIヘッダSHA',headers.get('x-chart-data-sha256'),meta['data_sha256'])
        audit.check('API集計alias',data['summary'],meta['summary'])
        audit.check('API台帳純額5',Decimal(str(data['summary']['realized_pnl_yen'])),Decimal(str(account['ledger']['5'])))
        trades=list(source.json_rows(ROOT/resource['pnl_path']))
        audit.check('API約定片数',len(data['events']),len(trades))
        for sequence,(trade,event) in enumerate(zip(trades,data['events']),1):
            for key in ('type','qty','position_id','method_id','price'):
                audit.check('API約定:'+key,event[key],trade[key])
            audit.check('API順',event['sequence'],sequence)
            audit.check('API時計',abs(event['timestamp_ms']-datetime.fromisoformat(trade['timestamp']).timestamp()*1000)<=.001,True)
        representatives.append({'候補':policy,'場':account['session'],'資源ID':resource['id'],'台帳観測5円':account['ledger']['5'],'数値SHA256':meta['data_sha256']})
    return {'実行':True,'全資源数':184,'新政策代表':representatives,'代表規約':'政策別最大絶対台帳観測額・場順。採否不使用'}


def run(viewer_url: str | None = None) -> dict:
    """旧67成功参照と否定追加・先着・92保存運用を正式一度照合する。

    引数: viewer_url(str|None)は任意Viewer API。
    返り値: dictはproof。既存proofを上書きせず、fit・Engine・新主を起動しない。
    """
    destination=STUDY/'保存物確認.json'
    if destination.exists():
        raise FileExistsError('保存物確認.jsonを上書きしません')
    source,oracle,summary=A.helpers(); audit=source.Audit()
    files=[STUDY/name for name in ('結果.json','固定.json','条件.json','入力台帳.json','一覧.resources.json')]
    files += [OLD/name for name in ('結果.json','保存物確認.json','固定.json','一覧.resources.json')]
    files += [WORK/name for name in ('定時判断と運用.jsonl.gz','入口先着.jsonl.gz')]
    files += [OLDWORK/name for name in ('定時判断と運用.jsonl.gz','入口先着.jsonl.gz')]
    files += [LEDGER,PREFLIGHT,source.MANIFEST,R67.R66.R65.FRAMES,Path(__file__),Path(__file__).with_name('先着.py'),
        Path(__file__).with_name('先着の人工検査.py'),Path(__file__).with_name('監査仕様.md')]
    before={path.relative_to(ROOT).as_posix():source.sha(path) for path in files}
    fixed,result=source.read(STUDY/'固定.json'),source.read(STUDY/'結果.json')
    inputs=source.read(STUDY/'入力台帳.json')
    audit.check('入力台帳試行',inputs['試行'],68)
    for name,digest in inputs['ファイルSHA256'].items():
        audit.check('入力台帳SHA:'+name,source.sha(ROOT/name),digest)
    for name,digest in fixed['ファイルSHA256'].items():
        audit.check('固定SHA:'+name,source.sha(ROOT/name),digest)
        if name.startswith('scripts/定時候補の価格発動/'):
            before[name]=digest
    for path in (Path(__file__),LEDGER,OLD/'保存物確認.json',R67.R66.R65.FRAMES):
        name=path.relative_to(ROOT).as_posix()
        audit.check('必要固定包含:'+name,fixed['ファイルSHA256'][name],source.sha(path))
    previous,proof,ledger=[source.read(path) for path in (OLD/'結果.json',OLD/'保存物確認.json',LEDGER)]
    audit.check('67完了台帳指定SHA',source.sha(LEDGER),'cc741ca48dc4efeac4a3732f070fce8c19aba599660dc414f42774cb254ca730')
    # ----------------------------------------
    # 旧完了証明と保存モデルは指紋で再用し、教師・特徴を再計算しない。
    audit.check('67単一完了',(ledger['試行'],ledger['市場実行終了'],ledger['本物実行回数'],ledger['不一致']),(67,True,1,0))
    audit.check('67成功証明',(proof['試行'],proof['全件一致'],proof['不一致数']),(67,True,0))
    audit.check('67結果bind',source.sha(OLD/'結果.json'),proof['結果SHA256'])
    for name,digest in ledger['成果物SHA256'].items():
        audit.check('67完了不変:'+name,source.sha(ROOT/name),digest);before[name]=digest
    audit.check('68固定bind',(result['試行'],result['固定SHA256']),(68,source.sha(STUDY/'固定.json')))
    audit.check('候補集合',set(result['候補']),{*CONTROLS,*POLICIES})
    audit.check('fit/木/計測/運用',tuple(result[key] for key in ('新回帰器fit','新分類器fit','新保存木数','参照モデル数','新独立計測','新運用数')),(0,0,0,3,0,92))
    references=('評価場','学習専用場','準備比較','旧教師一致','教師集合一致','独立測定','価格経路分布',
        '経路支持','状態分布','局面分布','数量分布','独立測定参照','モデル','回収集計','対照モデル')
    for key in references:
        audit.check('旧参照全辞書:'+key,result[key],previous[key])
    audit.check('旧証明検査',result['旧証明検査'],previous['検査'])
    audit.check('学習参照',result['学習参照'],{'元試行':65,'新fit':False,'教師再生成':False,'特徴再計算':False,
        'モデル同一':True,'回収集計同一':True,'旧即時入口の教師':True,'新条件入口を学習したか':False})
    audit.check('旧対照参照',result['対照参照'],{'候補':list(CONTROLS),'元試行':67,'同じ評価46場':True,'市場再生':False})
    model_pins={meta['path']:source.sha(ROOT/meta['path']) for meta in previous['モデル']+previous['回収集計']}
    for meta in previous['モデル']+previous['回収集計']:
        audit.check('旧モデルmetadataSHA',model_pins[meta['path']],meta['SHA256'])
        audit.check('旧モデル成功証明SHA',model_pins[meta['path']],proof['モデルSHA256'][meta['path']])
    entries=source.read(source.MANIFEST)['entries']; evaluated=[row['session'] for row in entries[20:]]
    # ----------------------------------------
    # 新しく検査するのは旧純判断からの固定価格条件と将来の価格経路である。
    audit.check('評価46順',result['評価場'],evaluated)
    old_blocks={}
    for block in source.json_rows(OLDWORK/'定時判断と運用.jsonl.gz'):
        key=block['session'],block['policy']
        if key in old_blocks or block['policy'] not in CONTROLS:
            raise ValueError('旧67場候補の重複又は政策差')
        old_blocks[key]=block
    audit.check('旧92集合',set(old_blocks),{(session,policy) for session in evaluated for policy in CONTROLS})
    frames=defaultdict(list)
    for row in source.json_rows(R67.R66.R65.FRAMES):
        if row['minutes']==3:
            frames[row['場']].append({'session':row['場'],**{key:row[key] for key in A.SOURCE if key!='session'}})
    detail=defaultdict(list)
    for block in source.json_rows(WORK/'定時判断と運用.jsonl.gz'):
        detail[block['session']].append(block)
    audit.check('新詳細46場',set(detail),set(evaluated))
    labels={policy:[] for policy in (*CONTROLS,*POLICIES)};slots_by_policy={policy:[] for policy in (*CONTROLS,*POLICIES)}
    for block in old_blocks.values():slots_by_policy[block['policy']].extend(block['slots'])
    for row in source.json_rows(OLDWORK/'入口先着.jsonl.gz'):
        if row['policy'] not in CONTROLS:raise ValueError('旧先着政策不正')
        labels[row['policy']].append(row)
    sequence=list(source.json_rows(WORK/'入口先着.jsonl.gz'))
    saved_labels={(row['policy'],row['slot_id']):row for row in sequence}
    audit.check('新先着一意',len(sequence),len(saved_labels))
    resources=source.read(STUDY/'一覧.resources.json')['resources']
    resource_map={(row['session'],row['method_id']):row for row in resources}
    audit.check('184資源集合',set(resource_map),{(session,policy) for session in evaluated for policy in (*CONTROLS,*POLICIES)})
    audit.check('資源ID一意',(len(resources),len({row['id'] for row in resources})),(184,184))
    for row in source.read(OLD/'一覧.resources.json')['resources']:
        if row['method_id'] in CONTROLS:audit.check('旧資源全属性',resource_map[row['session'],row['method_id']],row)
    accounts,summaries,cache_pins,viewer_pins=[],[],{},{}
    pure_count=condition_count=entry_count=0
    # ----------------------------------------
    # 旧戦略を再生せず、新保存運用の注文・現金・保護を照合する。
    new_blocks={};conditions_by_policy={policy:{} for policy in POLICIES}
    for entry in entries[20:]:
        session=entry['session'];tape,path,digest,input_quality=R55.load_tape(entry,source,audit)
        cache_pins[path]=digest;audit.check('67成功cachebind',digest,proof['キャッシュSHA256'][path])
        for control in CONTROLS:
            account=P.account(old_blocks[session,control]['operation'],source,audit)
            account['conditions']=old_blocks[session,control]['operation']['conditions'];accounts.append(account)
        audit.check('新二政策順',[block['policy'] for block in detail[session]],list(POLICIES))
        for block in detail[session]:
            policy=block['policy'];control=CONTROLS[POLICIES.index(policy)];old=old_blocks[session,control]
            audit.check('旧phaseを維持',block['phase'],old['phase'])
            expected_slots=[{**deepcopy(slot),'policy':policy} for slot in old['slots']]
            audit.check('旧純slot全文をpolicy以外維持',R67.R66.R65.S63.strict_equal(block['slots'],expected_slots),True)
            pure_count+=len(expected_slots);slots_by_policy[policy].extend(block['slots'])
            expected_conditions={slot['slot_id']:expected_condition(slot,frames[session]) for slot in expected_slots if slot['side']}
            audit.check('最新公開3分sourceと固定高安',block['conditions'],expected_conditions)
            audit.check('旧67条件4項目を完全維持',block['conditions'],old['conditions'])
            condition_count+=len(expected_conditions);new_blocks[session,policy]={key:block[key] for key in ('session','policy','phase','slots')}
            conditions_by_policy[policy][session]=expected_conditions
            _,force,end,_=source.calendar(session)
            expected_labels,observed={},{}
            for slot in expected_slots:
                if not slot['side']:continue
                value,last=expected_label(tape,slot,expected_conditions[slot['slot_id']],force,end,source,oracle)
                expected_labels[slot['slot_id']]=value;observed[slot['slot_id']]=last
                audit.check('新先着全属性',saved_labels[policy,slot['slot_id']],value)
                labels[policy].append(value)
            operation=block['operation'];audit.check('新運用識別',(operation['candidate_id'],operation['session']),(policy,session))
            audit.check('入力品質',block['input_quality'],input_quality)
            check_conditions(block,expected_labels,observed,tape,source,audit)
            check_orders(operation,expected_labels,{slot['slot_id']:slot for slot in expected_slots},tape,force,end,source,audit)
            source.check_trail(operation,tape,audit)
            entry_count+=sum(order['kind']=='entry' and order['status']=='filled' for order in operation['orders'])
            viewer=ROOT/resource_map[session,policy]['pnl_path']
            audit.check('新Viewer正規パス',viewer.resolve(),(STUDY/'viewer'/f'{policy}_{session}.trades.jsonl').resolve())
            viewer_pins[viewer.relative_to(ROOT).as_posix()]=source.sha(viewer)
            account=source.check_cash(operation,list(source.json_rows(viewer)),tape,audit)
            account['conditions']=operation['conditions'];accounts.append(account)
            summaries.append({'場':session,'候補':policy,'期間':source.span(session),'入力品質':input_quality,
                '運用品質':operation['quality'],'運用集計':operation['metrics']})
        print(session+' 条件出典/独立先着/新二運用照合',flush=True)
    audit.check('全旧純3404と新source488',(pure_count,condition_count),(3404,488))
    # ----------------------------------------
    # 主・役割・段階・取得比較の分母と、前後指紋を確認する。
    expected_checks={'旧67純判断一致':pure_count,'当時最新3分出典一致':condition_count,'同一条件実仮新規一致':entry_count}
    audit.check('主内今回3検査',result['検査'],expected_checks)
    preflight=source.read(PREFLIGHT)
    audit.check('接続時3検査',preflight['検査'],{**expected_checks,'同一条件実仮新規一致':0})
    for policy in POLICIES:
        ordered=[new_blocks[session,policy] for session in evaluated]
        audit.check('純接続指紋:'+policy,fingerprint(ordered),preflight['新純候補指紋'][policy])
        audit.check('条件接続指紋:'+policy,fingerprint(conditions_by_policy[policy]),preflight['条件指紋'][policy])
    audit.check('先着全文と保存順',sequence,[row for policy in POLICIES for row in labels[policy]])
    audit.check('新入口評価数',result['新条件入口評価'],len(sequence))
    audit.check('全場別',result['場別'],summaries)
    for policy in (*CONTROLS,*POLICIES):
        selected=[row for row in accounts if row['candidate']==policy]
        for period in PERIODS:
            entrance=entry_summary(labels[policy],period,source)
            operation=operation_summary(selected,period,source,summary)
            audit.check(policy+period+'入口',result['候補'][policy][period]['入口'],entrance)
            audit.check(policy+period+'運用',result['候補'][policy][period]['運用'],operation)
            audit.check(policy+period+'同時適格',result['候補'][policy][period]['同時適格'],entrance['70目標'] and operation['費用適格'] and operation['活動適格'])
            for role in ('順行','反転'):
                subset=[row for row in labels[policy] if row['role']==role]
                role_entry=entry_summary(subset,period,source)
                audit.check(policy+period+role,result['役割別入口'][policy][period][role],role_entry)
            if policy in POLICIES:
                audit.check(policy+period+'段階8項目',result['条件段階'][policy][period],stage_summary(slots_by_policy[policy],labels[policy],selected,period,source))
                control=CONTROLS[POLICIES.index(policy)]
                audit.check(policy+period+'取得比較',result['入口取得比較'][policy][period],comparison_summary(labels[policy],labels[control],period,source))
                audit.check(policy+period+'否定比較10項目',result['否定比較'][policy][period],denial_summary(labels[policy],labels[control],period,source,audit))
                reasons=dict(Counter(row['reason'] for row in slots_by_policy[policy] if source.span(row['session'])==period))
                audit.check(policy+period+'純判断理由',result['判断理由'][policy][period],reasons)
        if policy in CONTROLS:
            audit.check('旧保存対照全期間:'+policy,result['候補'][policy],previous['候補'][policy])
    audit.check('新採用',result['採用'],[policy for policy in POLICIES if all(result['候補'][policy][period]['同時適格'] for period in PERIODS[:2])])
    audit.check('新詳細二系列',set(result['詳細']),{'定時判断と運用.jsonl.gz','入口先着.jsonl.gz'})
    for name,digest in result['詳細'].items():audit.check('詳細SHA:'+name,source.sha(WORK/name),digest)
    api=check_api(viewer_url,resources,accounts,source,audit)
    for name,digest in {**before,**model_pins,**cache_pins,**viewer_pins}.items():audit.check('実行中不変:'+name,source.sha(ROOT/name),digest)
    payload={'試行':68,'確認日時':datetime.now(source.JST).isoformat(),'全件一致':audit.bad==0,'照合項目数':audit.count,
        '不一致数':audit.bad,'不一致':audit.examples,'結果SHA256':source.sha(STUDY/'結果.json'),
        '本物fit再実行':False,'新主処理import':False,'Engine期待値import':False,'市場戦略再生':False,
        '旧完了台帳対象数':len(ledger['成果物SHA256']),'新運用数':92,'新純比較数':pure_count,'条件SOURCE比較数':condition_count,'同一条件実仮新規数':entry_count,
        '参照SHA256':before,'モデルSHA256':model_pins,'キャッシュSHA256':cache_pins,'新Viewer約定SHA256':viewer_pins,'ViewerAPI':api,
        '検証範囲':'67成功と完了台帳、旧純3404と条件488、原配列firstgap/cross/denial順の別式先着、登録watchと新entry注文、旧49exit/現金/保護、条件未約定込み活動、段階8項目・取得比較・否定比較10項目、Viewer184。',
        '限定':'新Engineの独立全再実装や戦略再生をせず、保存遷移と原BBOの必要不変条件を照合。旧55独立回収を新入口の正解に流用しない。受信時計・心理主体・未見利益・70%を証明しない。'}
    destination.write_text(json.dumps(payload,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    return payload


def self_test() -> dict:
    """明示人工と別方式の累積配列監査を本物入力なしで照合する。

    引数: なし。
    返り値: dictは人工成功/照合項目数/不一致数/不一致。Engine期待値使用・本物入力・fitは0。
    """
    artificial=load(Path(__file__).with_name('先着の人工検査.py'),'発動前否定68保存監査の人工材料')
    result=artificial.self_test()
    source,oracle,summary=A.helpers(); audit=source.Audit()
    cases=[[(180,1000,999,1001,True),(181,1011,1010,1012,True),(182,1012,1011,1013,True),(200,1264,1263,1265,True)],
        [(180,1011,999,1001,True)],[(180,float('nan'),999,1001,True)],
        [(180,1000,999,1001,True),(481,float('nan'),999,1001,True),(482,1011,1010,1012,True)],
        [(180,1000,999,1001,True),(480,1000,999,1001,True),(780,1000,999,1001,True),(1080,1011,1010,1012,True)],
        [(180,1000,999,1001,True),(480,1000,999,1001,True),(779,1000,999,1001,True)],
        [(180,1000,999,1001,True),(480,1000,999,1001,True),(780,1000,999,1001,True),(1050,1011,1010,1012,True),(1080,1012,1011,1013,True)],
        [(180,1000,999,1001,True),(180,1011,1010,1012,True),(180,1012,1011,1013,True),(181,1012,1011,1013,True)],
        [(180,1000,999,1001,True),(181,1011,1010,1012,True),(211,1012,1011,1013,True)],
        [(180,1000,999,1001,True),(181,1011,1010,1012,True),(212,1012,1011,1013,True)],
        [(180,990,989,991,True),(181,1011,1010,1012,True),(182,1012,1011,1013,True)],
        [(180,1000,999,1001,True),(181,990,989,991,True),(182,1011,1010,1012,True),(183,1012,1011,1013,True)],
        [(180,1000,999,1001,True),(481,990,989,991,True)],
        [(180,1000,999,1001,True),(181,1011,1010,1012,True),(181,990,989,991,True),(182,990,989,991,True)]]
    for side in (1,-1):
        for number,values in enumerate(cases):
            events,slot,condition=artificial.fixture(values,side)
            raw={key:source.np.array([row[key] for row in events]) for key in ('now','line','last','bid','ask','valid')}
            mask=raw['valid'] & source.np.isfinite(raw['bid']) & source.np.isfinite(raw['ask']) & (raw['bid']>0) & (raw['bid']<raw['ask'])
            quotes={key:value[mask] for key,value in raw.items()}
            tape={'events':raw,'normal':quotes,'normal_lines':{int(line):i for i,line in enumerate(quotes['line'])}}
            expected,_=expected_label(tape,slot,condition,1200,1300,source,oracle)
            audit.check('別方式のwatch配列と期限補足:'+str((side,number)),artificial.L.label(events,slot,condition,1200,1300),expected)
    # ----------------------------------------
    # Engineは実装側の架空出力だけに使用し、期待値は上の独立配列と固定49補助とする。
    from types import SimpleNamespace
    engine=load(Path(__file__).with_name('運用.py'),'発動前否定68保存人工の実装側')
    legacy=load(ROOT/'scripts/定時帯反応/検証.py','発動前否定68保存人工の固定49集計')
    proxy=SimpleNamespace(**vars(source))
    proxy.calendar=lambda session:(0,1200,1300,[180.])
    for number in (0,2,3,6,10,11,12,13):
        events,slot,condition=artificial.fixture(cases[number])
        raw={key:source.np.array([row[key] for row in events]) for key in ('now','line','last','bid','ask','valid')}
        mask=raw['valid'] & source.np.isfinite(raw['bid']) & source.np.isfinite(raw['ask']) & (raw['bid']>0) & (raw['bid']<raw['ask'])
        quotes={key:value[mask] for key,value in raw.items()}
        tape={'events':raw,'normal':quotes,'normal_lines':{int(line):i for i,line in enumerate(quotes['line'])}}
        expected,last=expected_label(tape,slot,condition,1200,1300,source,oracle)
        operation=engine.replay(events,[{key:slot[key] for key in SLOT_FIELDS}],{slot['slot_id']:condition},slot['session'],'N0',{'start':0,'force':1200,'end':1300})
        block={'session':slot['session'],'policy':'N0','slots':[slot],'conditions':{slot['slot_id']:condition},'operation':operation}
        check_conditions(block,{slot['slot_id']:expected},{slot['slot_id']:last},tape,proxy,audit)
        check_orders(operation,{slot['slot_id']:expected},{slot['slot_id']:slot},tape,1200,1300,source,audit)
        source.check_trail(operation,tape,audit)
        account=source.check_cash(operation,operation['trades'],tape,audit)
        account['conditions']=operation['conditions']
        prior_account=P.account(operation,source,audit)
        prior_account['conditions']=operation['conditions']
        audit.check('旧条件対照のP.account互換',prior_account,account)
        actual=legacy.operation_stats([operation],'学習')
        registered=sum(row['registered'] for row in operation['conditions'].values())
        unfilled=sum(row['registered'] and not row['entry_filled'] for row in operation['conditions'].values())
        numerator=actual['待ち数']+actual['判定不能']+unfilled
        actual.update(条件登録数=registered,条件未約定=unfilled,待ち率保守上限=numerator/actual['予定枠'],活動適格=2*numerator<=actual['予定枠'])
        audit.check('新action/watch snapshot/集計接続:'+str(number),operation_summary([account],'学習',source,summary),actual)
    # ----------------------------------------
    # 否定比較の10項目を、除外250と残存125の明示値へ戻す。
    old_rows=[];new_rows=[]
    for identity,values in (('否定枠',cases[11]+[(200,1264,1263,1265,True)]),('残存枠',cases[0])):
        events,slot,condition=artificial.fixture(values)
        slot['slot_id']=identity
        prior=artificial.L.LEGACY.label(events,{**slot,'policy':'G0'},condition,1200,1300)
        after=artificial.L.label(events,slot,condition,1200,1300)
        old_rows.append(prior);new_rows.append(after)
    denial=denial_summary(new_rows,old_rows,'学習',source,audit)
    audit.check('否定比較10項目の明示値',denial,{'同じ純候補':2,'設定否定':0,'前提否定':1,
        '非否定の全属性一致':1,'否定群の旧結果':{'約定/250':1},'旧仮約定の除外':1,
        '旧250の除外':1,'旧125の除外':0,'両約定の時刻価格結果一致':1,'新のみ仮約定':0})
    return {'人工成功':result['人工成功'] and audit.bad==0,'照合項目数':result['照合項目数']+audit.count,
        '不一致数':result['不一致数']+audit.bad,'不一致':result['不一致']+audit.examples,
        '本物入力読取':False,'fit':0,'Engine期待値import':False,'Engine実装の人工比較':True,'新主import':False,'市場戦略再生':False}


def main() -> None:
    """人工又は親通知後の正式監査をCLIで一度起動する。

    引数: CLIの--self-test/--run、任意--viewer-url。
    返り値: None。不一致は終了1、既存proofは上書き拒否。
    """
    parser=argparse.ArgumentParser(description='68発動前否定・新入口・保存運用の独立監査')
    group=parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--self-test',action='store_true');group.add_argument('--run',action='store_true')
    parser.add_argument('--viewer-url')
    args=parser.parse_args();proof=self_test() if args.self_test else run(args.viewer_url)
    print(json.dumps(proof,ensure_ascii=False,indent=2,allow_nan=False))
    raise SystemExit(1 if proof['不一致数'] else 0)


if __name__=='__main__':
    main()
