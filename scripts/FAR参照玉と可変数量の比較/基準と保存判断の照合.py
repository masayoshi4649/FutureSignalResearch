"""87の基準C0・Source全pool選別・要求出典・通知保存を監査する。"""

from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
OLD_PATH = ROOT/'scripts/保持帯喪失と短秒反対の複合退出/基準と保存判断の照合.py'
OLD_SHA = '13c922961ec54ab63782cf5c11d8e54f45619a74d906a415bc8128b52380b862'
KEYS = tuple(f'{mode}_D{delay}' for delay in (0, 1) for mode in ('R0G1', 'R1G1'))
POLICIES = {'R0G1': 'S', 'R1G1': 'SC'}
READ_FIELDS = {'reference','reference_initial_quantity','native_parent_initial_micro','native_parent_original_desired','small_initial_rule_applicable','native_small_initial_eligible','native_parent_initial_known','native_parent_initial_reason','native_parent_original_desired_applicable','native_parent_original_desired_known','native_parent_original_desired_reason','native_small_initial_known','native_small_initial_reason'}
SNAPSHOT_FIELDS = {'method','at','source_index','started','lots','closes'}
BINDING_FIELDS = {'policy','read_lot','snapshot_method','snapshot_at','snapshot_index','snapshot_started','rank','requested_quantity','reference_kind','c0_used','c0_allowed','c0_required_unknown','c0_side','c0_role','c0_reason'}
CONTEXT_FIELDS = {'policy','method','snapshot_at','snapshot_index','started','occupied','seen_before_count','seen_after_count','selected_id','required_unknown','c0_used'}
CHECK_FIELDS = {'rank','seen','eligible','c0_passed','required_unknown','selected','real_entry_stage','reason'}
EFFECT_FIELDS = {'id','reference_id','at','quote_time','quote_index','quote_line','origin','before','quantity','reason','pending_before','cancelled','unreserved_before','exit_requested','unreserved_after','exit_order_id','orders_before_count','orders_after_count'}
GRID_FIELDS = {'at','window','clock_allowed','block_reason','c0','source','source_line','structure_anchor'}
EVENT_FIELDS = {'at','origin','quote','method','source_at','source_index','source_line','closes'}
EQUIVALENCE_FIELDS = {'step_frames','force_frames','grid_frames','current_sha256','legacy_sha256','mismatches'}
SOURCE_UNUSED_REASON = 'FAR参照入口のためC0保持帯線は未使用'


def sha(path: Path) -> str:
    """
    機能: 明示した保存ファイルの本文指紋を取得する。
    引数: path (Path) は既存ファイル。
    返り値: str はSHA256。
    """
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def load_old() -> object:
    """
    機能: 停止86の型・有限値・canonical helperを読取再用する。
    引数: なし。固定Pythonだけを読む。
    返り値: object は86保存監査。新売買・原板・APIは実行しない。
    """
    assert sha(OLD_PATH) == OLD_SHA, '停止86保存監査の変更'
    spec = importlib.util.spec_from_file_location('saved86_for87', OLD_PATH)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


OLD = load_old()
BASE = OLD.BASE
strict = OLD.OLD.strict
finite = OLD.OLD.valid_number
integer = OLD.OLD.integer
canonical_sha = OLD.canonical_sha
diagnostic_rows = OLD.diagnostic_rows


def expected_c0(old_grid: dict) -> dict:
    """
    機能: 旧86のB1全文とC0 snapshotからfar84.Decision全体を正確に組み立てる。
    引数: old_grid (dict) は停止86の一予定枠。
    返り値: dict はBase/Addedを含むC0。候補供給boolは純判断へ混ぜない。
    """
    base, policy = old_grid['decision'], old_grid['policies']['C0']
    directions = []
    for old, current in zip(base['directions'], policy['directions'], strict=True):
        strict(old['side'] == current['side'], 'C0基準の方向順が不整合')
        directions.append({'base': deepcopy(old), **{name: deepcopy(current[name]) for name in ('allowed','role','reason','required_unknown')}, 'added': deepcopy(current['added_checks'])})
    return {'policy':'C0','base':deepcopy(base), **{name:deepcopy(policy[name]) for name in ('allowed','side','role','reason','required_unknown')}, 'directions':directions}


def validate_read_lot(row: dict, snapshot: dict) -> None:
    """
    機能: 元親量の既知/対象外と選定参照初期/現在量を別々に検査する。
    引数: row/snapshot (dict) はReadLotと当時snapshot。
    返り値: None。親量を現在量から推測せず、矛盾はValueError。
    """
    strict(type(row) is dict and set(row) == READ_FIELDS, 'ReadLot13tag集合')
    reference = row['reference']
    expected = {'id','internal_id','parent','source_id','method','owner','kind','side','quantity','entry','at','closing'}
    strict(type(reference) is dict and set(reference) == expected, 'ReferenceLot12tag集合')
    strict(all(type(reference[name]) is str and reference[name] for name in ('id','internal_id','parent','source_id','method','owner','kind')), '参照識別子・元段階')
    strict(type(reference['side']) is int and reference['side'] in (-1,1) and integer(reference['quantity'],1) and reference['quantity'] <= 100, '参照方向・現在量')
    strict(integer(row['reference_initial_quantity'],1) and row['reference_initial_quantity'] >= reference['quantity'], '参照初期量と現在量')
    strict(finite(reference['at']) and finite(reference['entry']) and reference['entry'] > 0 and reference['at'] <= snapshot['at'], '参照出生の当時性')
    strict(type(reference['closing']) is bool and reference['method'] == snapshot['method'], '参照method・返済予約型')
    for name in ('native_parent_initial_known','native_parent_original_desired_applicable','native_parent_original_desired_known','small_initial_rule_applicable','native_small_initial_known'):
        strict(type(row[name]) is bool, 'ReadLot既知/適用bool')
    for name in ('native_parent_initial_reason','native_parent_original_desired_reason','native_small_initial_reason'):
        strict(type(row[name]) is str and bool(row[name]), 'ReadLot未知/適用理由')
    for value, known in (('native_parent_initial_micro','native_parent_initial_known'),('native_parent_original_desired','native_parent_original_desired_known')):
        strict((row[value] is not None) == row[known] and (row[value] is None or integer(row[value],1)), '元親量のnullableと既知性')
    desired_applicable = reference['method'] == 'NK225_D164_15'
    small_applicable = reference['method'] == 'NK225_P164_06'
    strict(row['native_parent_original_desired_applicable'] == desired_applicable and row['small_initial_rule_applicable'] == small_applicable, '元親量・小量初回の適用method')
    strict(not row['native_parent_original_desired_known'] or desired_applicable, '対象外の元希望量を創作しない')
    strict(not row['native_parent_original_desired_known'] or row['native_parent_initial_known'], '元希望量だけを親初回未取得から創作しない')
    known = small_applicable and row['native_parent_initial_known']
    strict(row['native_small_initial_known'] == known and (row['native_small_initial_eligible'] is not None) == known, '小量初回の既知/対象外')
    if known:
        eligible = row['native_parent_initial_micro'] <= 20 and reference['kind'] in ('initial','delayed_initial')
        strict(type(row['native_small_initial_eligible']) is bool and row['native_small_initial_eligible'] == eligible, '元親初回からの小量規則')


def sorted_pool(snapshot: dict, at: float) -> list[dict]:
    """
    機能: 共有Sourceの全poolを検査しAt/IDの安定順へ写す。
    引数: snapshot (dict)、at (float) は当時の共有値と定時時計。
    返り値: list[dict] は全候補。未知親量は新しい発注gateにしない。
    """
    strict(type(snapshot) is dict and set(snapshot) == SNAPSHOT_FIELDS, 'ReadSnapshot6tag集合')
    strict(finite(snapshot['at']) and snapshot['at'] <= at and snapshot['closes'] == [] and type(snapshot['started']) is bool, 'Source定時の当時性とClose別配送')
    strict(type(snapshot['source_index']) is int and (snapshot['source_index'] >= 0 if snapshot['started'] else not snapshot['lots']), 'Source開始と原行番号')
    if snapshot['lots']:
        strict(snapshot['method'] in ('NK225_D164_15','NK225_P164_06','NK225_U165_03'), 'Source三手法')
    seen = set()
    for row in snapshot['lots']:
        validate_read_lot(row, snapshot); identity = row['reference']['id']
        strict(identity not in seen, 'Source全pool参照ID重複'); seen.add(identity)
    return sorted(snapshot['lots'], key=lambda row:(row['reference']['at'],row['reference']['id']))


def force_times(session: str) -> list[float]:
    """
    機能: 実新規取消の既定timerを価格時計で再構成する。
    引数: session (str) は日付_Day/Night。
    返り値: list[float] は場末と夜間米国前終了の要求時計。
    """
    day = datetime.fromisoformat(session[:10])
    local = day.replace(tzinfo=timezone(timedelta(hours=9)))
    if session.endswith('Day'):
        return [(local+timedelta(hours=15,minutes=35)).timestamp()]
    us = day.replace(hour=9,minute=30,tzinfo=ZoneInfo('America/New_York')).timestamp()
    return [us-900,(local+timedelta(days=1,hours=5,minutes=50)).timestamp()]


def event_before(effect: dict, at: float, line: int) -> bool:
    """
    機能: 定時が同時計の次原行より前という契約で通知の過去性を判定する。
    引数: effect (dict)、at (float)、line (int) は通知と評価点。
    返り値: bool はtimer又は既処理原行の通知なら真。
    """
    return effect['at'] < at or effect['at'] == at and (effect['origin'] == 'timer' or effect['quote_line'] <= line)


def filled_before(order: dict, at: float, line: int) -> bool:
    """
    機能: 実約定の同時計別原行を分けて評価点以前か判定する。
    引数: order (dict)、at (float)、line (int) は注文と評価点。
    返り値: bool は実fillが済んでいる場合だけ真。
    """
    return order['fill_time'] is not None and order['fill_time'] <= at and order['fill_line'] <= line


def pending_at(order: dict, book: dict, session: str, at: float, line: int, effects: list[dict] | None = None) -> int:
    """
    機能: Source取消・強制取消・実fillを区別し当時未約定新規量を再構成する。
    引数: order/book (dict)、session (str)、at (float)、line (int)、effects (list|None) は過去通知の限定。
    返り値: int は当時未約定量。終局のremainingを過去へ流用しない。
    """
    if order['request_time'] > at or filled_before(order,at,line):
        return 0
    if any(order['request_time'] < clock <= at for clock in force_times(session)):
        return 0
    earlier = book['source_effects'] if effects is None else effects
    cancelled = sum(effect['cancelled'] for effect in earlier if effect['reference_id'] == order['reference_id'] and event_before(effect,at,line))
    return max(0,order['quantity']-cancelled)


def ownership_at(book: dict, session: str, at: float, line: int) -> tuple[bool,bool]:
    """
    機能: 定時直前の実所有・未約定新規を保存約定片から再構成する。
    引数: book (dict)、session (str)、at (float)、line (int) は会計と過去境界。
    返り値: tuple[bool,bool] は占有有無と実残玉有無。返済予約で空きを先取りしない。
    """
    owned = False
    for lot in book['lots']:
        if lot['entry_time'] <= at and lot['entry_line'] <= line:
            exited = sum(closed['quantity'] for closed in book['closed'] if closed['position_id'] == lot['id'] and closed['exit_time'] <= at and closed['exit_line'] <= line)
            owned = owned or lot['initial_quantity'] > exited
    pending = any(order['kind'] == 'entry' and order['request_time'] < at and pending_at(order,book,session,at,line) > 0 for order in book['orders'])
    return owned or pending, owned


def project_source(book: dict) -> dict:
    """
    機能: 宣言したSource追加欄だけを除き旧86の金融schemaへ投影する。
    引数: book (dict) は87会計。
    返り値: dict は旧全fieldを保持した複写。旧会計同値を主張する操作ではない。
    """
    value = deepcopy(book)
    for name in ('source_policy','source_effects'):
        value.pop(name,None)
    for container in BASE.CONTAINERS:
        for row in value[container]:
            row.pop('source_entry',None); row.pop('real_entry_stage',None)
    for row in value['decisions']:
        row.pop('source_context',None)
        for candidate in row['candidates']:
            candidate.pop('source_check',None)
    return value


def validate_book_schema(book: dict, audit: object, where: str) -> None:
    """
    機能: 87の新Source欄と全旧必須field、非活性hold/confirmを確認する。
    引数: book (dict)、audit (Audit)、where (str) は対象と差分台帳。
    返り値: None。未定義prefixをまとめて除去しない。
    """
    projected = project_source(book); OLD.validate_schema(projected,audit,where+'.旧金融schema')
    audit.check(set(book) == set(projected)|{'source_policy','source_effects'}, '87会計集合',where)
    for container in BASE.CONTAINERS:
        for index,row in enumerate(book[container]):
            audit.check(set(row) == set(projected[container][index])|{'source_entry','real_entry_stage'}, 'Source所有field集合',where+'.'+container)
    for index,row in enumerate(book['decisions']):
        audit.check(set(row) == set(projected['decisions'][index])|{'source_context'}, 'Source判断field集合',where)
        for j,candidate in enumerate(row['candidates']):
            audit.check(set(candidate) == set(projected['decisions'][index]['candidates'][j])|{'source_check'}, 'Source候補field集合',where)
    OLD.bind_confirmation(projected,False,audit,where)
    audit.check(book['hold_enabled'] is False and book['confirm_enabled'] is False, 'Source全旧追加保護off',where)
    unused = OLD.OLD.unknown_hold(); unused['reason'] = SOURCE_UNUSED_REASON
    for container,name in BASE.CONTAINERS.items():
        for row in book[container]:
            BASE.compare(row['hold_anchor'],unused,audit,where+'.'+container,'Source入口にfreshHoldを要求しない')
            audit.check(row['hold_active'] is False and row['hold_floor'] is None, '保持帯床off',where)
            if name != 'ActualOrder':
                audit.check(row['hold_activated_at'] is None and row['hold_entry_breached'] is False and row['hold_first_hit_at'] is None and row['hold_first_hit_index'] == -1 and row['hold_first_hit_line'] == 0, 'Source保持帯hit非創作',where)


def binding_value(policy: str, grid: dict, row: dict, rank: int, quantity: int) -> dict:
    """
    機能: 受理要求の当時Source全量とC0利用の有無を組み立てる。
    引数: policy (str)、grid/row (dict)、rank/quantity (int) は要求時点の値。
    返り値: dict は15tag不変出典。取得後のSource残量を転記しない。
    """
    source,c0 = grid['source'],grid['c0']
    return {'policy':policy,'read_lot':deepcopy(row),'snapshot_method':source['method'],'snapshot_at':source['at'],'snapshot_index':source['source_index'],'snapshot_started':source['started'],'rank':rank,'requested_quantity':quantity,'reference_kind':row['reference']['kind'],'c0_used':policy=='SC','c0_allowed':c0['allowed'],'c0_required_unknown':c0['required_unknown'],'c0_side':c0['side'],'c0_role':c0['role'],'c0_reason':c0['reason']}


def bind_decisions(book: dict, grids: list[dict], session: str, key: str, audit: object) -> dict:
    """
    機能: 全poolのstable順・seen・占有・同方向C0・一枠一IDと実要求を再計算する。
    引数: book (dict)、grids (list[dict])、session/key (str)、audit (Audit) は保存値。
    返り値: dict は要求参照ID別の期待Binding。元指標生成は再実装しない。
    """
    policy = POLICIES[key.split('_D')[0]]; seen = set(); bindings = {}
    audit.check(book['source_policy'] == policy and book['mode'] == 'S0G1' and book['side_cap'] == 100 and book['fill_delay_seconds'] == int(key[-1]), 'Source政策・金融mode・上限・遅延',session+key)
    audit.check([row['at'] for row in book['decisions']] == [g['at'] for g in grids], 'Source全定時順序',session+key)
    for decision,grid in zip(book['decisions'],grids,strict=True):
        at=grid['at']; source=grid['source']; c0=grid['c0']; quote=c0['base']['quote']; place=session+key+str(at)
        pool=sorted_pool(source,at) if grid['clock_allowed'] else []
        occupied,owned=ownership_at(book,session,at,quote['line'])
        quality=quote['valid'] and finite(quote['last']) and quote['last']>0 and finite(quote['time']) and quote['time']<=at and 0<=at-quote['time']<=15 and finite(quote['bid']) and finite(quote['ask']) and 0<quote['bid']<quote['ask'] and quote['index']>=0 and source['started'] and source['at']==quote['time']
        context={'policy':policy,'method':source['method'],'snapshot_at':source['at'],'snapshot_index':source['source_index'],'started':source['started'],'occupied':occupied,'seen_before_count':len(seen),'seen_after_count':len(seen),'selected_id':'','required_unknown':bool(pool and not quality and not occupied),'c0_used':policy=='SC'}
        action,reason=('保有継続','同時一建玉を維持') if owned else ('処理中','既存注文の約定待ち') if occupied else ('判定不能','直前Source・正常気配の当時性が不成立') if pool and not quality else ('待ち','有効な参照玉なし')
        candidates=[]
        for index,row in enumerate(pool):
            reference=row['reference']; identity=reference['id']; passed=c0['allowed'] and c0['side']==reference['side']
            check={'rank':index+1,'seen':identity in seen,'eligible':False,'c0_passed':passed,'required_unknown':False,'selected':False,'real_entry_stage':'初参加候補','reason':''}
            candidate={'reference_id':identity,'source_quantity':reference['quantity'],'requested_quantity':0,'side':reference['side'],'role':reference['kind'],'reason':'','source_check':check}
            if reference['closing']: text='参照返済予約あり'
            elif identity in seen: text='同じ参照HoldIDへ再参加しない'
            elif occupied: text='実保有又は注文で占有'
            elif not quality: text='Source又は気配品質が未知'; check['required_unknown']=True
            elif policy=='SC' and not passed: text='同方向の最終C0許可なし'; check['required_unknown']=c0['required_unknown']
            else:
                check['eligible']=True
                if context['selected_id']: text='同枠の先行参照玉を採用済み'
                else:
                    quantity=min(100,reference['quantity']); text='参照現在量以内の初参加要求'; check['selected']=True; candidate['requested_quantity']=quantity
                    bindings[identity]=binding_value(policy,grid,row,index+1,quantity); seen.add(identity); context['selected_id']=identity; action,reason='新規要求','15分定時の参照玉を変数量で初参加'
            candidate['reason']=text; check['reason']=text; context['required_unknown']=context['required_unknown'] or check['required_unknown']; candidates.append(candidate)
        if action=='待ち' and context['required_unknown']: action,reason='判定不能','必要な最終C0許可が未知'
        context['seen_after_count']=len(seen)
        expected={'at':at,'quote_time':quote['time'],'quote_index':quote['index'],'action':action,'reason':reason,'candidates':candidates,'source_context':context}
        BASE.compare(decision,expected,audit,place,'全pool・seen・占有からの純選別')
    entries=[order for order in book['orders'] if order['kind']=='entry']
    audit.check(len(entries)==len(bindings) and {order['reference_id'] for order in entries}==set(bindings), '受理要求と永久seen集合',session+key)
    return bindings


def bind_entries(book: dict, bindings: dict, grids: list[dict], audit: object, where: str) -> None:
    """
    機能: 要求時SourceEntryを注文・取得後玉・返済片へ不変継承し、変数量会計へ結ぶ。
    引数: book/bindings (dict)、grids (list[dict])、audit (Audit)、where (str) は保存資料。
    返り値: None。参照建値を実建値へ流用せず、要求量と取得量を別検査する。
    """
    by_time={grid['at']:grid for grid in grids}; entries={}; lots={lot['id']:lot for lot in book['lots']}
    for order in book['orders']:
        if order['kind']!='entry': continue
        identity=order['reference_id']; expected=bindings.get(identity); entries[identity]=order
        audit.check(expected is not None,'受理新規のSource選択源',where)
        if expected is None: continue
        BASE.compare(order['source_entry'],expected,audit,where+'.entry','要求時SourceEntry15tag')
        reference=expected['read_lot']['reference']; grid=by_time[order['request_time']]; q=grid['c0']['base']['quote']
        BASE.compare(order['source'],reference,audit,where+'.entry','参照値を再数量化しない')
        audit.check(order['quantity']==expected['requested_quantity'] and order['side']==reference['side'] and order['role']==reference['kind'],'参照当時量・方向・元段階',where)
        audit.check(order['request_index']==q['index'] and order['request_line']==q['line'],'Source要求の当時原行',where)
        audit.check(order['filled_quantity']+order['cancelled_quantity']+order['remaining']==order['quantity'],'要求・実fill・取消・待機量の保存',where)
        audit.check(order['structure_anchor']==grid['structure_anchor'],'Source要求時EMA出典',where)
    for container,name in BASE.CONTAINERS.items():
        for row in book[container]:
            expected=bindings.get(row['reference_id']); audit.check(expected is not None,'Source全世代の要求源',where+'.'+container)
            if expected is not None:
                BASE.compare(row['source_entry'],expected,audit,where+'.'+container,'SourceEntryを後の残量で上書きしない')
            stage='初参加要求' if name=='ActualOrder' and row['kind']=='entry' else '実初参加'
            audit.check(row['real_entry_stage']==stage,'元段階と実側初参加を区別',where+'.'+container)
    for lot in book['lots']:
        order=entries.get(lot['reference_id']); audit.check(order is not None,'実玉の受理新規',where)
        if order is None: continue
        audit.check(lot['initial_quantity']==order['filled_quantity'] and 0<lot['initial_quantity']<=order['quantity']<=100,'Source取消後の変数量取得',where)
        audit.check(lot['method']==order['source']['method'] and lot['owner']==order['source']['owner'] and lot['source_id']==order['source']['source_id'] and lot['parent']==order['source']['parent'] and lot['role']==order['source']['kind'],'実玉の元所有・段階',where)
        closed=[row for row in book['closed'] if row['position_id']==lot['id']]
        audit.check(sum(row['quantity'] for row in closed)==lot['closed_quantity'] and lot['initial_quantity']==lot['quantity']+lot['closed_quantity'],'変数量の取得・残玉・返済保存',where)
        audit.check(sum(row['pnl5'] for row in closed)==lot['net_pnl'],'変数量の確定純額保存',where)
        audit.check(all(row['entry_price']==lot['entry_price'] and row['entry_time']==lot['entry_time'] for row in closed),'参照建値と実建値を混同しない',where)
    total_entry=sum(order['filled_quantity'] for order in entries.values())
    total_exit=sum(row['quantity'] for row in book['closed'])
    metric=book['metrics']
    for name,value in (('entry_quantity',total_entry),('exit_quantity',total_exit),('commission_yen',11*(total_entry+total_exit)),('slippage_yen',50*(total_entry+total_exit)),('total_cost_yen',61*(total_entry+total_exit))):
        audit.check(metric[name]==value,'実約定量に対応する費用・数量',where+'.'+name,metric[name],value)


def flatten_events(events: list[dict], audit: object, where: str) -> list[tuple[dict,dict]]:
    """
    機能: 共有通知を元順に展開し、各通知IDと当時出典の正規集合を確認する。
    引数: events (list[dict])、audit (Audit)、where (str) は共有通知と場所。
    返り値: list[tuple[dict,dict]] はイベントとCloseの全順序。
    """
    flattened=[]; ids=set(); last_at=float('-inf')
    for event in events:
        strict(set(event)==EVENT_FIELDS,'SourceEvent8tag集合')
        strict(finite(event['at']) and event['at']>=last_at and event['origin'] in ('quote','timer'),'SourceEvent当時順・種別')
        last_at=event['at']; quote=event['quote']
        strict(finite(quote['time']) and quote['time']<=event['at'] and finite(event['source_at']) and event['source_at']<=event['at'],'通知Source/価格時計の非未来')
        strict(type(event['source_index']) is int and event['source_index']>=-1 and integer(event['source_line']),'通知の別Source番号/物理行')
        if event['origin']=='quote':
            strict(event['at']==quote['time'] and event['source_at']==quote['time'] and event['source_line']==quote['line'],'quote通知の同原行出典')
        strict(bool(event['closes']),'空通知イベントは保存しない')
        for close in event['closes']:
            strict(set(close)=={'id','reference_id','before','quantity','reason'},'ReferenceClose5tag集合')
            strict(type(close['id']) is str and close['id'] and close['id'] not in ids and type(close['reference_id']) is str and close['reference_id'],'Source通知ID一意')
            strict(integer(close['before'],1) and close['before']<=100 and integer(close['quantity'],1) and close['quantity']<=close['before'],'Source未通知残量比率')
            ids.add(close['id']); flattened.append((event,close))
    audit.check(len(ids)==len(flattened),'Source共有通知重複なし',where)
    return flattened


def bind_effects(book: dict, events: list[dict], session: str, audit: object, where: str) -> dict:
    """
    機能: 全通知の比例取消/未予約返済・0丸め・要求時刻を保存注文片から別式で検査する。
    引数: book (dict)、events (list[dict])、session (str)、audit (Audit)、where (str) は保存値。
    返り値: dict は通知/0作用/取消/返済量。全原行順序は別Source通知原板監査と分担する。
    """
    flattened=flatten_events(events,audit,where); effects=book['source_effects']; prior=[]; totals=Counter()
    audit.check(len(effects)==len(flattened),'全Source通知を全会計へ一度配送',where)
    previous_orders=0
    for effect,(event,close) in zip(effects,flattened,strict=True):
        strict(set(effect)==EFFECT_FIELDS,'SourceEffect18tag集合')
        quote=event['quote']; at=event['at']; line=quote['line']
        wanted={'id':close['id'],'reference_id':close['reference_id'],'at':at,'quote_time':quote['time'],'quote_index':quote['index'],'quote_line':line,'origin':event['origin'],'before':close['before'],'quantity':close['quantity'],'reason':close['reason']}
        BASE.compare({name:effect[name] for name in wanted},wanted,audit,where,'通知18欄の原共有イベント出典')
        for name in ('pending_before','cancelled','unreserved_before','exit_requested','unreserved_after','orders_before_count','orders_after_count'):
            strict(integer(effect[name]),'SourceEffect非負整数')
        before=effect['orders_before_count']; after=effect['orders_after_count']
        audit.check(previous_orders<=before<=after<=len(book['orders']),'SourceEffect当時の注文prefix',where); previous_orders=after
        prefix=book['orders'][:before]; identity=close['reference_id']
        pending=sum(pending_at(order,book,session,at,line,prior) for order in prefix if order['kind']=='entry' and order['reference_id']==identity)
        quantity=reserved=0
        for lot in book['lots']:
            if lot['reference_id']!=identity or lot['entry_time']>at or lot['entry_line']>line: continue
            quantity+=lot['initial_quantity']-sum(piece['quantity'] for piece in book['closed'] if piece['position_id']==lot['id'] and piece['exit_time']<=at and piece['exit_line']<=line)
        for order in prefix:
            if order['kind']=='exit' and order['reference_id']==identity and not filled_before(order,at,line): reserved+=order['quantity']
        available=max(0,quantity-reserved)
        cancel=pending if close['quantity']==close['before'] else pending*close['quantity']//close['before']
        requested=available if close['quantity']==close['before'] else available*close['quantity']//close['before']
        expected={'pending_before':pending,'cancelled':cancel,'unreserved_before':available,'exit_requested':requested,'unreserved_after':available-requested}
        BASE.compare({name:effect[name] for name in expected},expected,audit,where,'Source比例・floor0と全量末尾の別式')
        audit.check(after==before+int(requested>0),'Source返済注文追加件数',where)
        if requested:
            order=book['orders'][before]
            audit.check(effect['exit_order_id']==order['id'] and order['kind']=='exit' and order['reference_id']==identity and order['quantity']==requested and order['request_time']==at and order['request_line']==line and order['request_index']==quote['index'] and order['reason']=='参照返済:'+close['reason'],'Source返済要求と注文全対応',where)
        else: audit.check(effect['exit_order_id']=='','Source0丸めで注文非創作',where)
        prior.append(effect); totals['通知']+=1; totals['0作用']+=cancel==requested==0; totals['取消枚']+=cancel; totals['返済要求枚']+=requested; totals['timer通知']+=event['origin']=='timer'
    return dict(totals)


def verify_equivalence(current: dict, times: list[float], audit: object, where: str) -> dict:
    """
    機能: 別インスタンス固定80の全Frame互換件数と順次二指紋を結ぶ。
    引数: current (dict)、times (list[float])、audit (Audit)、where (str) は一場保存。
    返り値: dict は小型比較証拠。元Sourceの別実装との独立性は主張しない。
    """
    value=current['source_equivalence']; strict(set(value)==EQUIVALENCE_FIELDS,'SourceEquivalence6tag集合')
    for name in ('step_frames','force_frames','grid_frames','mismatches'): strict(integer(value[name]),'Source互換非負件数')
    audit.check(value['grid_frames']==len(times) and value['step_frames']==sum(current['reference_counts'].values()) and value['mismatches']==0,'Source全Step/定時比較の件数',where)
    valid=all(type(value[name]) is str and len(value[name])==64 and all(char in '0123456789abcdef' for char in value[name]) for name in ('current_sha256','legacy_sha256'))
    audit.check(valid and value['current_sha256']==value['legacy_sha256'],'Source別インスタンス二指紋一致',where)
    return deepcopy(value)


def audit_scene(current: dict, baseline: dict, session: str, times: list[float], audit: object) -> dict:
    """
    機能: 一場の基準C0全枠・Source互換・全4保存会計と共有canonicalを検査する。
    引数: current/baseline (dict) は87/86、session (str)、times (list[float])、audit (Audit)。
    返り値: dict は基準C0枠/保存会計と全小型証拠。旧会計全文同値とはしない。
    """
    BASE.inspect_finite(current,audit,session+'.87'); BASE.inspect_finite(baseline,audit,session+'.86')
    strict(set(current)=={'session','quality','reference_counts','books','grid_decisions','source_events','source_equivalence'},'87場本文7tag集合')
    audit.check(current['session']==baseline['session']==session and set(current['books'])==set(KEYS),'場IDと4会計集合',session)
    BASE.compare(current['quality'],baseline['quality'],audit,session,'旧86原板品質全文')
    grids=current['grid_decisions']; old_grids=baseline['grid_decisions']
    audit.check([row['at'] for row in grids]==[row['at'] for row in old_grids]==times,'基準C0全予定枠順',session)
    for grid,old in zip(grids,old_grids,strict=True):
        strict(set(grid)==GRID_FIELDS,'87共有定時8tag集合')
        BASE.compare(grid['c0'],expected_c0(old),audit,session+str(grid['at']),'旧86からのC0全Decision正確投影')
        for name in ('at','window','clock_allowed','block_reason','structure_anchor'):
            BASE.compare(grid[name],old[name],audit,session+str(grid['at']),name+'基準対応')
        sorted_pool(grid['source'],grid['at'])
        strict(integer(grid['source_line']),'共有Source物理行型')
    equivalent=verify_equivalence(current,times,audit,session)
    effects={}; actions=[]
    for key in KEYS:
        book=current['books'][key]; where=session+key
        validate_book_schema(book,audit,where)
        bindings=bind_decisions(book,grids,session,key,audit)
        bind_entries(book,bindings,grids,audit,where)
        effects[key]=bind_effects(book,current['source_events'],session,audit,where)
        financial=dict(Counter(row['action'] for row in book['decisions']))
        actions.append({'session':session,'key':key,'金融判断':financial,'方針判断':deepcopy(financial)})
    source_rows={'session':session,'books':{key:{'source_policy':current['books'][key]['source_policy'],'decisions':current['books'][key]['decisions'],'source_effects':current['books'][key]['source_effects']} for key in KEYS}}
    shared={'grid_decisions':grids,'source_events':current['source_events'],'source_equivalence':current['source_equivalence']}
    return {'場':session,'予定枠':len(times),'基準C0枠':len(times),'保存会計':4,'Source互換':equivalent,'Source通知適用':effects,'方針判断':actions,
        '共有判断SHA256':canonical_sha(shared),'参照判断と通知効果SHA256':canonical_sha(source_rows),
        '玉診断SHA256':{key:canonical_sha(diagnostic_rows(session,key,current['books'][key])) for key in KEYS}}


def audit_directories(source: Path, baseline: Path, sessions: list[str], pins86: dict | None, audit: object) -> dict:
    """
    機能: 全66保存を基準C0の2442枠・264保存会計と前後入力指紋へ結ぶ。
    引数: source/baseline (Path) は87/86、sessions (list[str])、pins86 (dict|None)、audit (Audit)。
    返り値: dict は全場証拠。132旧会計の全文同値とは表示しない。
    """
    roots={'87':source,'86':baseline}; before={name:BASE.inventory(path) for name,path in roots.items()}
    wanted={session+'.json' for session in sessions}
    audit.check(len(sessions)==len(set(sessions))==66,'固定66場','全体')
    for name,values in before.items(): audit.check(set(values)==wanted,'保存全場集合',name)
    if pins86 is not None: audit.check(before['86']==pins86,'基準86本文指紋','全体')
    rows=[]; complete=True
    try:
        for session in sessions:
            if any(session+'.json' not in before[name] for name in roots): continue
            rows.append(audit_scene(BASE.read_json(source/(session+'.json')),BASE.read_json(baseline/(session+'.json')),session,BASE.scheduled(session),audit))
    except Exception as error:
        complete=False; audit.check(False,'保存処理未完','全体',type(error).__name__+':'+str(error),'全場完了')
    after={name:BASE.inventory(path) for name,path in roots.items()}
    audit.check(before==after,'保存入力の前後不変','全体')
    frames=sum(row['基準C0枠'] for row in rows); accounts=sum(row['保存会計'] for row in rows)
    audit.check(len(rows)==66 and frames==2442 and accounts==264,'66場2442基準C0枠264保存会計','全体',(len(rows),frames,accounts),(66,2442,264))
    source_counts={name:sum(row['Source互換'][name] for row in rows) for name in ('step_frames','force_frames','grid_frames','mismatches')}
    return {'処理完了':complete and len(rows)==66 and frames==2442 and accounts==264,'場数':len(rows),'予定枠':frames,'基準C0枠':frames,'保存会計':accounts,
        '入力不変':before==after,'入力SHA256前':before,'入力SHA256後':after,'Source互換件数':source_counts,'対象場':rows,'方針判断':[action for row in rows for action in row['方針判断']]}


def fixture(session: str, times: list[float]) -> tuple[dict,dict]:
    """
    機能: 停止86の保存人工から、Source1玉生存・一回受理・永久seenの合成人工を作る。
    引数: session (str)、times (list[float]) は人工場と時計。
    返り値: tuple[dict,dict] は87/基準86。FAR自然発生や原板約定の証明ではない。
    """
    baseline,_=OLD.fixture(session,times)
    for index,grid in enumerate(baseline['grid_decisions']):
        q=grid['decision']['quote']; q['index']=10+100*index; q['line']=20+100*index
        grid['decision']['evidence']['source_line']=q['line']
    old_book=baseline['books']['J0G1_D0']; reference=deepcopy(old_book['orders'][0]['source'])
    reference.update(method='NK225_D164_15' if session.endswith('Day') else 'NK225_P164_06',kind='initial')
    small=reference['method']=='NK225_P164_06'; desired=reference['method']=='NK225_D164_15'
    read={'reference':reference,'reference_initial_quantity':100,'native_parent_initial_micro':None,'native_parent_original_desired':None,'small_initial_rule_applicable':small,'native_small_initial_eligible':None,
        'native_parent_initial_known':False,'native_parent_initial_reason':'人工元親未取得','native_parent_original_desired_applicable':desired,'native_parent_original_desired_known':False,'native_parent_original_desired_reason':'人工元希望未取得' if desired else '対象外','native_small_initial_known':False,'native_small_initial_reason':'人工初回未取得' if small else '対象外'}
    grids=[]
    for grid in baseline['grid_decisions']:
        c0=expected_c0(grid)
        snapshot={'method':reference['method'],'at':grid['decision']['quote']['time'],'source_index':grid['decision']['quote']['index'],'started':True,'lots':[deepcopy(read)],'closes':[]}
        grids.append({**{name:deepcopy(grid[name]) for name in ('at','window','clock_allowed','block_reason','structure_anchor')},'c0':c0,'source':snapshot,'source_line':grid['decision']['quote']['line']})
    current={'session':session,'quality':deepcopy(baseline['quality']),'reference_counts':{reference['method'].removeprefix('NK225_'):len(times)},'books':{},'grid_decisions':grids,'source_events':[],
        'source_equivalence':{'step_frames':len(times),'force_frames':0,'grid_frames':len(times),'current_sha256':canonical_sha(grids),'legacy_sha256':canonical_sha(grids),'mismatches':0}}
    for key in KEYS:
        policy=POLICIES[key.split('_D')[0]]; delay=int(key[-1]); book=deepcopy(baseline['books'][f'J0G1_D{delay}'])
        book.update(source_policy=policy,source_effects=[]); binding=binding_value(policy,grids[0],read,1,100)
        unused=OLD.OLD.unknown_hold(); unused['reason']=SOURCE_UNUSED_REASON
        for container,name in BASE.CONTAINERS.items():
            for row in book[container]:
                row.update(source_entry=deepcopy(binding),real_entry_stage='初参加要求' if name=='ActualOrder' and row['kind']=='entry' else '実初参加',hold_anchor=deepcopy(unused))
                if name=='ActualOrder' and row['kind']=='entry': row['source']=deepcopy(reference); row['role']=reference['kind']
                if name=='ActualLot': row.update(method=reference['method'],role=reference['kind'],owner=reference['owner'],source_id=reference['source_id'],parent=reference['parent'])
        for order in book['orders']:
            entry=order['kind']=='entry'
            order.update(quantity=100,remaining=0,filled_quantity=100,cancelled_quantity=0,status='filled',request_time=times[0] if entry else times[0]+2,request_index=10 if entry else 12,request_line=20 if entry else 22,fill_time=times[0]+1 if entry else times[0]+3,fill_line=21 if entry else 23,fill_price=1010 if entry else 1025,reason='FAR参照の初参加要求' if entry else '人工返済')
        for lot in book['lots']: lot['closed_quantity']=100
        for closed in book['closed']: closed.update(quantity=100,request_time=times[0]+2,reason='人工返済')
        book['metrics'].update(hold_known_entries=0,hold_unknown_entries=len(book['lots']),commission_yen=2200,slippage_yen=10000,total_cost_yen=12200)
        book['decisions']=[]
        for index,grid in enumerate(grids):
            q=grid['c0']['base']['quote']; selected=index==0; text='参照現在量以内の初参加要求' if selected else '同じ参照HoldIDへ再参加しない'
            context={'policy':policy,'method':reference['method'],'snapshot_at':grid['source']['at'],'snapshot_index':grid['source']['source_index'],'started':True,'occupied':False,'seen_before_count':int(not selected),'seen_after_count':1,'selected_id':reference['id'] if selected else '','required_unknown':False,'c0_used':policy=='SC'}
            check={'rank':1,'seen':not selected,'eligible':selected,'c0_passed':grid['c0']['allowed'] and grid['c0']['side']==reference['side'],'required_unknown':False,'selected':selected,'real_entry_stage':'初参加候補','reason':text}
            candidate={'reference_id':reference['id'],'source_quantity':100,'requested_quantity':100 if selected else 0,'side':reference['side'],'role':reference['kind'],'reason':text,'source_check':check}
            book['decisions'].append({'at':grid['at'],'quote_time':q['time'],'quote_index':q['index'],'action':'新規要求' if selected else '待ち','reason':'15分定時の参照玉を変数量で初参加' if selected else '有効な参照玉なし','candidates':[candidate],'source_context':context})
        current['books'][key]=book
    return current,baseline


def self_test() -> dict:
    """
    機能: 市場なしで全66/2442C0枠/264保存会計と破損拒否を検査する。
    引数: なし。固定台帳から場IDだけを使用する。
    返り値: dict は保存人工の成功証拠。Source自然発生・原板監査とは区別する。
    """
    import tempfile
    manifest=BASE.read_json(ROOT/'study/00080_FAR後期三手法の15分移植と利益保護/入力台帳.json'); sessions=[row['id'] for row in manifest['sessions']]
    audit=BASE.Audit()
    with tempfile.TemporaryDirectory(prefix='87保存人工_') as directory:
        source=Path(directory)/'87'; baseline=Path(directory)/'86'; source.mkdir(); baseline.mkdir()
        for session in sessions:
            current,old=fixture(session,BASE.scheduled(session))
            for folder,value in ((source,current),(baseline,old)):
                (folder/(session+'.json')).write_text(json.dumps(value,ensure_ascii=False,allow_nan=False),encoding='utf-8')
        result=audit_directories(source,baseline,sessions,None,audit)
    strict(result['処理完了'] and audit.bad==0,'保存合成人工不一致:'+str(audit.examples[:4]))
    # ----------------------------------------
    session=sessions[0]; times=BASE.scheduled(session)[:1]; current,old=fixture(session,times); rejected=[]
    for label,mutation in (
        ('基準C0投影',lambda x:x['grid_decisions'][0]['c0'].__setitem__('side',-1)),
        ('Source全pool脱落',lambda x:x['grid_decisions'][0]['source']['lots'].clear()),
        ('seen偽造',lambda x:x['books']['R0G1_D0']['decisions'][0]['source_context'].__setitem__('seen_before_count',1)),
        ('SへC0強制',lambda x:x['books']['R0G1_D0']['decisions'][0]['source_context'].__setitem__('c0_used',True)),
        ('要求時元量上書き',lambda x:x['books']['R0G1_D0']['orders'][0]['source_entry']['read_lot'].__setitem__('reference_initial_quantity',50)),
        ('元Kindと実段階混同',lambda x:x['books']['R0G1_D0']['lots'][0].__setitem__('real_entry_stage','source_add')),
        ('小量初回を現在量から捏造',lambda x:x['grid_decisions'][0]['source']['lots'][0].__setitem__('native_small_initial_known',True)),
        ('Source二指紋差',lambda x:x['source_equivalence'].__setitem__('legacy_sha256','0'*64)),
        ('Source比較回数差',lambda x:x['source_equivalence'].__setitem__('grid_frames',0)),
        ('新たな保持帯gate',lambda x:x['books']['R0G1_D0'].__setitem__('hold_enabled',True)),
    ):
        value=deepcopy(current); mutation(value); check=BASE.Audit(); refused=False
        try:
            audit_scene(value,old,session,times,check)
        except (ValueError,KeyError,TypeError,AssertionError): refused=True
        strict(refused or check.bad>0,'反証を拒否しなかった:'+label)
        rejected.append(label)
    return {'成功':True,'場数':66,'基準C0枠':2442,'保存会計':264,'照合項目数':audit.count,'破損拒否':rejected,'市場再生':0,'本物原板読取':0,'元Source別実装ではない':True}


def main() -> None:
    """
    機能: 明示87/86保存を監査し、全対象完了と入力前後不変を新規証拠へ残す。
    引数: --input/--baseline/--out (Path) 全必須、又は --self-test (bool)。
    返り値: None。失敗は非0。新売買・本物原板・APIは実行しない。
    """
    parser=argparse.ArgumentParser()
    for name in ('input','baseline','out'): parser.add_argument('--'+name,type=Path)
    parser.add_argument('--self-test',action='store_true'); args=parser.parse_args()
    if args.self_test:
        strict(not any((args.input,args.baseline,args.out)),'人工と正式入力を混在させない')
        print(json.dumps(self_test(),ensure_ascii=False)); return
    strict(all((args.input,args.baseline,args.out)),'input/baseline/out全て明示必須')
    strict(not args.out.exists() and not any(args.out.resolve().is_relative_to(path.resolve()) for path in (args.input,args.baseline)),'新規証拠を入力外へ保存する')
    audit=BASE.Audit(); small={}; data={'処理完了':False,'場数':0,'基準C0枠':0,'保存会計':0,'入力不変':False}
    try:
        manifest=ROOT/'study/00080_FAR後期三手法の15分移植と利益保護/入力台帳.json'; result86=ROOT/'study/00086_保持帯喪失と短秒反対の複合退出/成果物/結果.json'
        conditions=[ROOT/'study'/folder/'条件.json' for folder in ('00087_FAR参照玉と可変数量の比較','00086_保持帯喪失と短秒反対の複合退出')]
        files=[manifest,result86,OLD_PATH,OLD.BASE_PATH,OLD.OLD.BASE_PATH,ROOT/'scripts/定時の現在根拠と部分利益保護/actual.go',*conditions]
        small={path.relative_to(ROOT).as_posix():sha(path) for path in files}
        for path in conditions:
            condition=BASE.read_json(path); groups=[condition['コードと依存SHA256']]+[value for name,value in condition.items() if name.startswith('固定') and name.endswith('依存') and type(value) is dict]
            groups.append({condition['実行ファイル']:condition['実行ファイルSHA256']})
            for group in groups:
                for name,wanted in group.items(): audit.check(sha(ROOT/name)==wanted,'新旧固定依存不変',name)
        sessions=[row['id'] for row in BASE.read_json(manifest)['sessions']]
        data=audit_directories(args.input.resolve(),args.baseline.resolve(),sessions,BASE.read_json(result86)['再生結果SHA256'],audit)
        audit.check({name:sha(ROOT/name) for name in small}==small,'小型依存の前後不変','全体')
    except Exception as error:
        audit.check(False,'全体処理未完','全体',type(error).__name__+':'+str(error),'完了')
    success=data['処理完了'] and audit.bad==0
    output={'試行':87,'成功':success,**data,'照合項目数':audit.count,'不一致数':audit.bad,'不一致':audit.examples,'項目別比較数':dict(audit.scope),
        '固定小型入力SHA256':small,'照合コードSHA256':sha(Path(__file__)),'読取helperSHA256':OLD_SHA,'本処理の新売買再生':0,'本物原板読取':0,
        '範囲外':['旧86との132金融会計全文同値','元Sourceの独立した別実装','保存されない全原行のSource通知タイミング/G1連続保護（別原板監査）']}
    args.out.parent.mkdir(parents=True,exist_ok=True)
    with args.out.open('x',encoding='utf-8',newline='\n') as stream:
        json.dump(output,stream,ensure_ascii=False,indent=2,allow_nan=False); stream.write('\n')
    print(json.dumps({name:output[name] for name in ('成功','場数','基準C0枠','保存会計','照合項目数','不一致数')},ensure_ascii=False))
    if not success: raise SystemExit(1)


if __name__=='__main__':
    main()
