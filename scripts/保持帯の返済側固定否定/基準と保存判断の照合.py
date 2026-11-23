"""85の固定C0入口・当時保持帯出典・新hold欄とH0旧全会計を独立に照合する。"""

from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
from datetime import datetime, timedelta
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import tempfile

ROOT = Path(__file__).resolve().parents[2]
BASE_PATH = ROOT / 'scripts/現在の価格応答と数量確認/基準と保存判断の照合.py'
BASE_SHA = 'f13eec083772501416f68b7de7595c508e0a50ef8948ff4aae2cb9e43150f869'
KEYS = tuple(f'{mode}_D{delay}' for delay in (0,1) for mode in ('H0G1','H1G1'))


def sha(path: Path) -> str:
    """
    機能: 保存入力・依存・コードの本文指紋を取得する。
    引数: path (Path) は実ファイル。
    返り値: str はSHA256。
    """
    with path.open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()


def load_base() -> object:
    """
    機能: 停止84の純判断・候補・厳密比較helperを読取で再用する。
    引数: なし。既知SHAの固定Pythonだけを参照する。
    返り値: object は84保存監査モジュール。市場・Goを実行しない。
    """
    assert sha(BASE_PATH)==BASE_SHA,'固定84保存監査が変わりました'
    spec=importlib.util.spec_from_file_location('fixed84_for85_saved',BASE_PATH)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


OLD = load_base()
BASE = OLD.BASE


def valid_number(value: object) -> bool:
    """
    機能: 真偽値や非有限を数値と取り違えない。
    引数: value (object) は保存JSON値。
    返り値: bool は有限なint/floatなら真。
    """
    return BASE.finite(value)


def integer(value: object, minimum: int = 0) -> bool:
    """
    機能: 保存連番が真偽値や小数でないことを確認する。
    引数: value (object)、minimum (int) は値と下限。
    返り値: bool は下限以上のintだけ真。
    """
    return type(value) is int and value>=minimum


def strict(ok: bool, message: str) -> None:
    """
    機能: 不整合な候補出典を未知へ落とさず入力errorにする。
    引数: ok (bool) は成立条件、message (str) は原因。
    返り値: None。不成立はValueError。
    """
    if not ok:
        raise ValueError(message)


def valid_barrier(barrier: dict, evidence: dict) -> bool:
    """
    機能: 既知の回復点が当時までの有限価格と連番を持つことを検査する。
    引数: barrier/evidence (dict) は保存回復点と当時特徴。
    返り値: bool は未知点又は妥当な既知点なら真。
    """
    if type(barrier.get('known')) is not bool:
        return False
    if not barrier['known']:
        return True
    return all(valid_number(barrier.get(name)) for name in ('price','time')) and barrier['price']>0 and barrier['time']<=evidence['time'] and integer(barrier.get('index')) and barrier['index']<=evidence['source_index'] and integer(barrier.get('event')) and barrier['event']<=evidence['night']['price_event']


def fresh_barrier(barrier: dict, at: float, evidence: dict) -> bool:
    """
    機能: 構造の回復点が60秒/32価格更新の当時範囲内かを別式で確認する。
    引数: barrier/evidence (dict) は回復点と特徴、at (float) は要求時刻。
    返り値: bool は既知・正常・鮮度内なら真。
    """
    return valid_barrier(barrier,evidence) and barrier['known'] and 0<=at-barrier['time']<=60 and evidence['night']['price_event']-barrier['event']<=32


def policy_actions(book: dict, grids: dict) -> tuple[dict,dict]:
    """
    機能: 金融判断を保持し、C0必須未知の非占有待ちだけを方針判定不能へ分類する。
    引数: book (dict) は85会計、grids (dict) は時刻別共有判断。
    返り値: tuple[dict,dict] は金融判断と方針判断の件数。
    """
    financial,interpreted=Counter(),Counter()
    for decision in book['decisions']:
        action=decision['action'];financial[action]+=1
        grid=grids.get(decision['at'])
        if grid is not None:
            action=OLD.policy_action(action,grid['clock_allowed'],grid['policies']['C0']['required_unknown'])
        interpreted[action]+=1
    return dict(financial),dict(interpreted)


def canonical_sha(value: object) -> str:
    """
    機能: 保存値をキー順だけ正規化し、配列順序・型・数値を保持した内容指紋へ結ぶ。
    引数: value (JSON互換値) は共有判断又は玉診断。
    返り値: str はUTF-8 canonical JSONのSHA256。非有限値は拒否する。
    """
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode('utf-8')).hexdigest()


def diagnostic_rows(session: str, key: str, book: dict) -> list[dict]:
    """
    機能: 原保存Bookから集計と同じ玉診断の全フィールドを読取で抽出する。
    引数: session/key (str) は場と外会計、book (dict) は保存実会計。
    返り値: list[dict] は原玉順の診断行。金融値を変更・再計算しない。
    """
    rows=[]
    for lot in book['lots']:
        entries=[order for order in book['orders'] if order['position_id']==lot['id'] and order['kind']=='entry']
        strict(len(entries)==1,'玉診断の新規要求が一意でない')
        rows.append({'session':session,'key':key,'lot':lot,'entry_order':entries[0],
            'orders':[order for order in book['orders'] if order['position_id']==lot['id']],
            'closed':[closed for closed in book['closed'] if closed['position_id']==lot['id']]})
    return rows


def audit_directories(source: Path, baseline: Path, sessions: list[str], pins84: dict | None, audit: object) -> dict:
    """
    機能: 全66保存結果を2442予定枠と旧84本文指紋へ結び、入力の前後不変を検査する。
    引数: source/baseline (Path) は85/84保存根、sessions (list[str])、pins84 (dict|None) は旧正式SHA、audit (Audit) は差分台帳。
    返り値: dict は完了・132基準会計・方針判断・入力指紋。部分処理を成功にしない。
    """
    folders={'85':source,'84':baseline}
    before={name:BASE.inventory(folder) for name,folder in folders.items()}
    wanted={session+'.json' for session in sessions}
    audit.check(len(sessions)==len(set(sessions))==66,'固定66場','全体')
    for name,values in before.items():audit.check(set(values)==wanted,'全保存場集合',name,sorted(values),sorted(wanted))
    if pins84 is not None:audit.check(before['84']==pins84,'固定84本文指紋','全体')
    rows=[];complete=True
    try:
        for session in sessions:
            if any(session+'.json' not in before[name] for name in folders):continue
            current=BASE.read_json(source/(session+'.json'));old=BASE.read_json(baseline/(session+'.json'))
            rows.append(audit_scene(current,old,session,BASE.scheduled(session),audit))
    except Exception as error:
        complete=False;audit.check(False,'読取処理未完','全体',type(error).__name__+':'+str(error),'全場完了')
    after={name:BASE.inventory(folder) for name,folder in folders.items()}
    audit.check(before==after,'入力集合と本文の前後不変','全体')
    frames=sum(row['予定枠'] for row in rows)
    audit.check(len(rows)==66 and frames==2442,'66場2442枠完了','全体',(len(rows),frames),(66,2442))
    totals=Counter();holds=Counter()
    for row in rows:totals.update(row['政策件数']);holds.update(row['保持帯枠'])
    return {'処理完了':complete and len(rows)==66 and frames==2442,'場数':len(rows),'予定枠':frames,'基準会計数':sum(row['基準会計'] for row in rows),
        '入力不変':before==after,'入力SHA256前':before,'入力SHA256後':after,'対象場':rows,'政策件数合計':dict(totals),'政策全予定枠':{'C0':frames},'保持帯枠合計':dict(holds),'方針判断':[item for row in rows for item in row['方針判断']]}

MODE_ENABLED = {'H0G1':False,'H1G1':True}
HOLD_ORDER = {'hold_anchor','hold_active','hold_floor'}
HOLD_LOT = HOLD_ORDER | {'hold_activated_at','hold_entry_breached','hold_first_hit_at','hold_first_hit_index','hold_first_hit_line'}
HOLD_METRICS = {'hold_known_entries','hold_unknown_entries','hold_activated_lots','hold_entry_breached_lots','hold_hit_lots','hold_exit_orders'}
HOLD_FIELDS = {'known','kind','rule_version','at','side','quote_time','quote_index','source_line','feature_index','price_event','hold_id','hold_side','hold_bid','hold_ask','hold_time','hold_index','hold_event','tick','stop_price','reason'}
HOLD_KIND = 'E08保持帯返済側1tick'
UNKNOWN_REASON = '当時のC0候補がないため保持帯線は未使用'
KNOWN_REASON = '新規要求時点のfreshなE08同方向保持帯の返済側1tick否定'
HOLD_EXIT_REASON = '保持帯返済側1tick否定'


def unknown_hold() -> dict:
    """
    機能: 非候補枠を数値0・理由付きの正規な保持帯未使用として記録する。
    引数: なし。
    返り値: dict はknown=falseのHoldAnchor全フィールド。
    """
    value=dict.fromkeys(HOLD_FIELDS,0)
    value.update(known=False,kind=HOLD_KIND,rule_version=1,tick=10,reason=UNKNOWN_REASON)
    return value


def grid_price(value: object) -> bool:
    """
    機能: 10ptの価格格子をepsilonや丸めで広げず確認する。
    引数: value (object) は保存価格。
    返り値: bool は正有限で厳密10pt格子上なら真。
    """
    return valid_number(value) and value>0 and value%10==0


def expected_hold_anchor(grid: dict, side: int) -> dict:
    """
    機能: 要求時の保存Quote/Current/E08holdから別のPython式で全HoldAnchorを再構成する。
    引数: grid (dict) は共有保存判断、side (int) は候補方向±1又は非候補0。
    返り値: dict は正規未知又は厳密な既知線。不整合候補はValueError。
    """
    strict(type(side) is int and side in (-1,0,1),'保持帯方向の型又は値が不正')
    strict(valid_number(grid['at']),'非候補でも要求時計は有限値を必要とする')
    if side==0:
        return unknown_hold()
    at=grid['at'];decision=grid['decision'];q=decision['quote'];c=decision['evidence'];n=c['night'];band=n['band']
    hold,opposite=(n['buy'],n['sell']) if side==1 else (n['sell'],n['buy'])
    strict(valid_number(at),'要求時刻が正有限でない')
    strict(all(valid_number(q.get(name)) for name in ('time','last','bid','ask')) and q['last']>0 and grid_price(q['bid']) and grid_price(q['ask']) and q['ask']>q['bid'],'要求気配の価格又は格子が不整合')
    strict(q.get('valid') is True and integer(q.get('index')) and integer(q.get('line'),1) and 0<=at-q['time']<=15,'要求気配の正常性・鮮度・原行が不整合')
    strict(c.get('reference')=='NK225' and all(valid_number(c.get(name)) for name in ('time','received','last','bid','ask')),'当時特徴の参照又は有限性が不整合')
    strict(c['time']==q['time'] and c['time']<=c['received']<=at and all(c[name]==q[name] for name in ('last','bid','ask')),'当時特徴と要求気配が別時点')
    strict(integer(c.get('source_index')) and integer(c.get('source_line'),1) and c['source_line']==q['line'],'特徴連番又は物理原行が不整合')
    strict(n.get('available') is True and n.get('known') is True and n.get('invalid') is False and n.get('window')=='E08','当時E08構造が未確定又は不正')
    strict(valid_number(n.get('time')) and n['time']==c['time'] and integer(n.get('index')) and n['index']==c['source_index'] and integer(n.get('price_event')),'E08時計・特徴番号が不整合')
    strict(band.get('known') is True and integer(band.get('index')) and band['index']==c['source_index'] and integer(band.get('start_index')) and band['start_index']<=band['index'],'E08窓の特徴番号が不整合')
    strict(all(valid_number(band.get(name)) for name in ('time','start_time')) and band['time']==c['time'] and band['start_time']<=band['time'],'E08窓の時計が不整合')
    strict(hold.get('active') is True and hold.get('pressured') is False and type(hold.get('side')) is int and hold['side']==side and integer(hold.get('id'),1),'同方向の有効holdがない')
    strict(grid_price(hold.get('bid')) and grid_price(hold.get('ask')) and hold['ask']>hold['bid'],'hold出生価格又は格子が不整合')
    strict(valid_number(hold.get('time')) and hold['time']<=c['time'] and 0<=at-hold['time']<=60,'hold確認時刻又は鮮度が不整合')
    strict(integer(hold.get('index')) and hold['index']<=c['source_index'] and integer(hold.get('event')) and hold['event']<=n['price_event'] and n['price_event']-hold['event']<=32,'hold確認番号又は32更新鮮度が不整合')
    strict(all(valid_barrier(point,c) for point in (hold['barrier'],hold['support'],opposite['support'])),'既知回復点が当時入力と不整合')
    strict(side*(q['bid']-hold['bid'])>=0 and side*(q['ask']-hold['ask'])>=0,'要求時に両気配が帯の方向側にない')
    liquidation=q['bid'] if side==1 else q['ask']
    barrier_fresh=fresh_barrier(hold['barrier'],at,c)
    passed=not barrier_fresh or side*(liquidation-hold['barrier']['price'])>=10
    opposition=opposite.get('active') is True and opposite.get('quantity_support') is True and fresh_barrier(opposite['support'],at,c) and valid_number(opposite.get('time')) and 0<=at-opposite['time']<=60 and integer(opposite.get('index')) and opposite['index']<=c['source_index'] and integer(opposite.get('event')) and opposite['event']<=n['price_event'] and n['price_event']-opposite['event']<=32
    strict(passed and not opposition,'C0の反対圧力解消が保存構造と不整合')
    stop=hold['bid']-10 if side==1 else hold['ask']+10
    strict(grid_price(stop),'保持帯停止価格が正の10pt格子でない')
    return {'known':True,'kind':HOLD_KIND,'rule_version':1,'at':at,'side':side,'quote_time':q['time'],'quote_index':q['index'],'source_line':c['source_line'],'feature_index':c['source_index'],'price_event':n['price_event'],
        'hold_id':hold['id'],'hold_side':hold['side'],'hold_bid':hold['bid'],'hold_ask':hold['ask'],'hold_time':hold['time'],'hold_index':hold['index'],'hold_event':hold['event'],'tick':10,'stop_price':stop,'reason':KNOWN_REASON}


def project_hold(book: dict) -> dict:
    """
    機能: 宣言した新holdフィールドだけを除き、旧84全会計へ投影する。
    引数: book (dict) は85のH0又はH1会計。
    返り値: dict は配列順序・旧フィールド・ID・価格・modeを変えない複写。
    """
    value=deepcopy(book)
    value.pop('hold_enabled',None)
    for container,name in BASE.CONTAINERS.items():
        fields=HOLD_ORDER if name=='ActualOrder' else HOLD_LOT
        for row in value[container]:
            for field in fields:row.pop(field,None)
    for field in HOLD_METRICS:value['metrics'].pop(field,None)
    return value


def validate_hold_schema(book: dict, expected_keys: dict, audit: object, where: str) -> None:
    """
    機能: 新holdフィールドの許可集合と全旧必須フィールドを確認し、両側欠落も拒否する。
    引数: book (dict)、expected_keys (dict) は旧Go型、audit (Audit)、where (str) は検査場所。
    返り値: None。未定義追加フィールドをprefix一致で消さない。
    """
    audit.check(set(book)==expected_keys['BookResult']|{'hold_enabled'},'85会計フィールド集合',where,sorted(book),sorted(expected_keys['BookResult']|{'hold_enabled'}))
    for container,name in BASE.CONTAINERS.items():
        additions=HOLD_ORDER if name=='ActualOrder' else HOLD_LOT
        expected=expected_keys[name]|BASE.EXTRA[name]|additions
        for index,row in enumerate(book[container]):
            audit.check(set(row)==expected,'85会計内フィールド集合',f'{where}.{container}[{index}]',sorted(row),sorted(expected))
            audit.check(type(row['hold_anchor']) is dict and set(row['hold_anchor'])==HOLD_FIELDS,'HoldAnchor全フィールド',f'{where}.{container}[{index}]')
            anchor=row['hold_anchor']
            audit.check(type(anchor['known']) is bool and type(anchor['kind']) is str and type(anchor['reason']) is str,'HoldAnchor非数値型',f'{where}.{container}[{index}]')
            audit.check(all(type(anchor[field]) is int for field in ('rule_version','side','quote_index','source_line','feature_index','price_event','hold_id','hold_side','hold_index','hold_event')),'HoldAnchor整数型',f'{where}.{container}[{index}]')
    expected=expected_keys['BookMetrics']|BASE.EXTRA['BookMetrics']|HOLD_METRICS
    audit.check(set(book['metrics'])==expected,'85集計フィールド集合',where,sorted(book['metrics']),sorted(expected))
    BASE.validate_book(project_hold(book),expected_keys,True,audit,where+'.旧投影')


def bind_hold_metadata(book: dict, enabled: bool, grids: dict, audit: object, where: str) -> None:
    """
    機能: 新規要求の保持帯出典を玉・返済注文・各返済片へ結び、先行片への未来hitを拒否する。
    引数: book (dict)、enabled (bool) は固定H設定、grids (dict) は時刻別当時判断、audit (Audit)、where (str) は場所。
    返り値: None。取得後の実価格床・所有・約定先着は別原板監査に分担する。
    """
    audit.check(type(book['hold_enabled']) is bool and book['hold_enabled']==enabled,'保持帯設定の明示',where)
    anchors={};lot_by_id={lot['id']:lot for lot in book['lots']}
    for order in book['orders']:
        if order['kind']!='entry':continue
        g=grids.get(order['request_time']);audit.check(g is not None,'保持帯新規の予定枠',where)
        if g is None:continue
        expected=g['hold_anchor'];anchors[order['reference_id']]=expected
        audit.check(expected['known'] is True,'供給候補の保持帯既知必須',where)
        BASE.compare(order['hold_anchor'],expected,audit,where+'.entry','新規の保持帯全出典')
        audit.check(order['hold_active'] is False and order['hold_floor'] is None,'新規要求時の未活性',where)
    for container,name in BASE.CONTAINERS.items():
        for index,row in enumerate(book[container]):
            place=f'{where}.{container}[{index}]';expected=anchors.get(row['reference_id'])
            audit.check(expected is not None,'全保持帯状態の新規源',place)
            if expected is not None:BASE.compare(row['hold_anchor'],expected,audit,place,'保持帯の要求時出典継承')
            audit.check(type(row['hold_active']) is bool,'保持帯活性bool',place)
            audit.check(row['hold_floor'] is None or valid_number(row['hold_floor']),'保持帯床の有限数値型',place)
            if name=='ActualOrder':
                if row['kind']=='entry':audit.check(row['hold_active'] is False and row['hold_floor'] is None,'未取得注文の保持帯非活性',place)
                elif row['kind']=='exit':
                    lot=lot_by_id.get(row['position_id']);audit.check(lot is not None,'保持帯返済の玉所有',place)
                    if lot is not None:audit.check(row['hold_active']==lot['hold_active'] and row['hold_floor']==lot['hold_floor'],'返済要求の固定保持帯床',place)
                continue
            lot=row if name=='ActualLot' else lot_by_id.get(row['position_id'])
            audit.check(lot is not None,'保持帯片の玉所有',place)
            if lot is None:continue
            active=enabled and expected is not None and expected['known']
            audit.check(row['hold_active']==active and type(row['hold_entry_breached']) is bool,'取得後保持帯活性政策',place)
            if active:
                floor=lot['side']*(expected['stop_price']-lot['entry_price'])
                audit.check(row['hold_floor']==floor and row['hold_activated_at']==lot['entry_time'],'実建値からの固定保持帯床',place,(row['hold_floor'],row['hold_activated_at']),(floor,lot['entry_time']))
            else:
                audit.check(row['hold_floor'] is None and row['hold_activated_at'] is None and row['hold_entry_breached'] is False,'無効保持帯の非創作',place)
            at,hit_index,hit_line=row['hold_first_hit_at'],row['hold_first_hit_index'],row['hold_first_hit_line']
            audit.check(type(hit_index) is int and integer(hit_line),'保持帯hit連番型',place)
            audit.check((at is None)==(hit_index==-1)==(hit_line==0),'保持帯初回hit三点',place)
            if at is not None:
                audit.check(active and valid_number(at) and at>=lot['entry_time'] and integer(hit_index) and hit_index>=lot['entry_index'] and integer(hit_line,1) and hit_line>=lot['entry_line'],'保持帯初回hitの取得後当時性',place)
            if not active:audit.check(at is None and hit_index==-1 and hit_line==0,'無効保持帯にhitを創作しない',place)
            if name=='ClosedLot':
                if at is not None:audit.check(valid_number(row['exit_time']) and at<=row['exit_time'],'返済片へ未来時刻を転記しない',place)
                audit.check(row['hold_entry_breached']==lot['hold_entry_breached'],'返済片の取得時否定状態',place)
                hit=lot['hold_first_hit_at'];first_line=lot['hold_first_hit_line']
                if hit is None or row['exit_line']<=first_line:
                    audit.check(at is None and hit_index==-1 and hit_line==0,'先行返済片へ未来hit非転記',place)
                else:
                    audit.check((at,hit_index,hit_line)==(hit,lot['hold_first_hit_index'],first_line),'後続返済片の当時hit継承',place)
            elif active:
                if row['hold_entry_breached']:
                    audit.check(at==row['entry_time'] and hit_index==row['entry_index'] and hit_line==row['entry_line'],'新規取得時否定の同原行hit',place)
                if at is not None and hit_line==row['entry_line']:audit.check(row['hold_entry_breached'] is True,'同取得原行hitは取得時否定',place)
    lots=book['lots']
    expected_metrics={'hold_known_entries':sum(lot['hold_anchor']['known'] for lot in lots),'hold_unknown_entries':sum(not lot['hold_anchor']['known'] for lot in lots),'hold_activated_lots':sum(lot['hold_active'] for lot in lots),
        'hold_entry_breached_lots':sum(lot['hold_entry_breached'] for lot in lots),'hold_hit_lots':sum(lot['hold_first_hit_at'] is not None for lot in lots),
        'hold_exit_orders':sum(order['kind']=='exit' and order['reason']==HOLD_EXIT_REASON for order in book['orders'])}
    for name,expected in expected_metrics.items():audit.check(type(book['metrics'][name]) is int and book['metrics'][name]==expected,'保持帯6集計の保存対応',where+'.'+name,book['metrics'][name],expected)


def audit_scene(current: dict, baseline: dict, session: str, times: list[float], audit: object) -> dict:
    """
    機能: 一場の固定C0入口・保持帯出典・全4会計とH0の旧全値を照合する。
    引数: current/baseline (dict) は85/84、session (str)、times (list[float]) は予定枠、audit (Audit) は差分台帳。
    返り値: dict は小型場別証拠。H1の実参加や占有を基準へ強制一致させない。
    """
    expected_keys=BASE.schemas()
    for value,name in ((current,'85'),(baseline,'84')):
        BASE.inspect_finite(value,audit,session+name)
        audit.check(set(value)=={'session','quality','books','grid_decisions'} and value['session']==session,'場本文schema',session+name)
    audit.check(set(current['books'])==set(KEYS),'85四会計集合',session)
    audit.check(set(baseline['books'])==set(OLD.KEYS),'旧84六会計集合',session)
    BASE.compare(current['quality'],baseline['quality'],audit,session,'84原板品質全文')
    grids=current['grid_decisions'];old_grids=baseline['grid_decisions']
    audit.check([g['at'] for g in grids]==times and [g['at'] for g in old_grids]==times,'85と84の全予定順序',session)
    by_time={};count=Counter();hold_counts=Counter()
    for index,g in enumerate(grids):
        at=g['at'];where=session+f'.grid[{index}]';audit.check(at not in by_time,'定時重複なし',where);by_time[at]=g
        audit.check(set(g)=={'at','window','entry_policy','decision','clock_allowed','block_reason','candidate_accepted','structure_anchor','policies','hold_anchor'},'85共有定時フィールド集合',where)
        audit.check(g['entry_policy']=='C0' and set(g['policies'])=={'C0'},'固定C0共有政策',where)
        if index<len(old_grids):
            old=old_grids[index]
            expected={**deepcopy(old),'entry_policy':'C0','candidate_accepted':old['policies']['C0']['candidate_accepted'],'policies':{'C0':deepcopy(old['policies']['C0'])}}
            BASE.compare({name:value for name,value in g.items() if name!='hold_anchor'},expected,audit,where,'84旧snapshotとC0全文')
        BASE.compare(g['structure_anchor'],BASE.expected_anchor(at,g['decision']['technical']),audit,where,'EMA線は当時EMAのまま')
        refined=OLD.refined(g['decision'],'C0',audit,where)
        refined['candidate_accepted']=OLD.candidate(session,g,refined) is not None
        BASE.compare(g['policies']['C0'],refined,audit,where,'固定C0純採否の再計算')
        audit.check(g['candidate_accepted']==refined['candidate_accepted'],'top候補はC0',where)
        source=OLD.candidate(session,g,refined);side=source['side'] if source is not None else 0
        expected=expected_hold_anchor(g,side)
        BASE.compare(g['hold_anchor'],expected,audit,where,'当時保持帯Anchor全フィールド')
        hold_counts['既知枠' if expected['known'] else '未知未使用枠']+=1
        for name,value in (('許可',refined['allowed']),('候補',refined['candidate_accepted']),('必須未知',refined['required_unknown']),('既知不許可',not refined['allowed'] and not refined['required_unknown']),('許可初動',refined['allowed'] and refined['role']=='転換初動')):count['C0:'+name]+=value
    actions=[]
    for key in KEYS:
        mode,delay_text=key.split('_D');book=current['books'][key];delay=int(delay_text)
        validate_hold_schema(book,expected_keys,audit,session+key)
        projected=project_hold(book)
        OLD.bind_book(projected,'C0',delay,by_time,audit,session+key,expected_keys)
        audit.check(book['side_cap']==100,'固定100枚上限',session+key)
        bind_hold_metadata(book,MODE_ENABLED[mode],by_time,audit,session+key)
        financial,interpreted=policy_actions(book,by_time)
        audit.check(sum(financial.values())==sum(interpreted.values())==len(times),'全予定枠の金融と方針判断',session+key)
        actions.append({'session':session,'key':key,'金融判断':financial,'方針判断':interpreted})
    for delay in (0,1):
        old=baseline['books'][f'C0G1_D{delay}'];BASE.validate_book(old,expected_keys,True,audit,session+'.84C0')
        BASE.compare(project_hold(current['books'][f'H0G1_D{delay}']),old,audit,session+f'.H0D{delay}','H0対84C0の全旧会計')
    return {'場':session,'予定枠':len(grids),'基準会計':2,'政策件数':dict(count),'保持帯枠':dict(hold_counts),'方針判断':actions,
        '共有判断SHA256':canonical_sha(grids),'玉診断SHA256':{key:canonical_sha(diagnostic_rows(session,key,current['books'][key])) for key in KEYS}}


def fixture(session: str, times: list[float], clock_allowed: bool = True, birth_shift: int = 0, hold_age: float = 2, event_age: int = 1) -> tuple[dict,dict]:
    """
    機能: 保持帯出典と4会計を持つ非0保存人工を作り、H0だけを旧84へ厳密対応させる。
    引数: session (str)、times (list[float])、clock_allowed (bool)、birth_shift (int)、hold_age (float)、event_age (int) は人工境界。
    返り値: tuple[dict,dict] は85と84。元特徴生成・実約定を証明する人工ではない。
    """
    old,_,_=OLD.fixture(session,times,clock_allowed=clock_allowed)
    for g in old['grid_decisions']:
        at=g['at'];q=g['decision']['quote'];feature=100+int(q['index'])
        point={'known':False,'price':0,'time':0,'index':0,'event':0}
        hold={'active':True,'quantity_support':True,'supply_passed':True,'pressured':False,'id':1,'side':1,'bid':1000+birth_shift,'ask':1010+birth_shift,'time':at-hold_age,'index':feature-1,'event':200-event_age,'pressure_event':0,'pressure_index':0,'barrier':deepcopy(point),'support':deepcopy(point)}
        opposite={**deepcopy(hold),'active':False,'quantity_support':False,'id':0,'side':-1,'bid':0,'ask':0,'time':0,'index':0,'event':0}
        night={'available':True,'known':True,'invalid':False,'window':'E08','time':q['time'],'index':feature,'price_event':200,'confirmed_side':1,'retest_side':0,'retest_id':0,'retest_hold_id':0,
            'band':{'known':True,'index':feature,'start_index':feature-8,'time':q['time'],'start_time':q['time']-10},'buy':hold,'sell':opposite}
        g['decision']['evidence']={'reference':'NK225','time':q['time'],'received':q['time'],'source_index':feature,'source_line':q['line'],'last':q['last'],'bid':q['bid'],'ask':q['ask'],'night':night}
    current={'session':session,'quality':deepcopy(old['quality']),'books':{},'grid_decisions':[]}
    for old_grid in old['grid_decisions']:
        g={**deepcopy(old_grid),'entry_policy':'C0','candidate_accepted':old_grid['policies']['C0']['candidate_accepted'],'policies':{'C0':deepcopy(old_grid['policies']['C0'])}}
        source=OLD.candidate(session,g,g['policies']['C0']);g['hold_anchor']=expected_hold_anchor(g,source['side'] if source else 0)
        current['grid_decisions'].append(g)
    anchor=current['grid_decisions'][0]['hold_anchor']
    for delay in (0,1):
        base=old['books'][f'C0G1_D{delay}']
        for lot in base['lots']:
            lot.update(entry_time=times[0]+1,entry_index=11,entry_line=21)
        for closed in base['closed']:
            closed.update(side=1,entry_time=times[0]+1,exit_time=times[0]+3,exit_line=23)
        for mode,enabled in MODE_ENABLED.items():
            book=deepcopy(base);book['hold_enabled']=enabled
            book['metrics'].update(dict.fromkeys(HOLD_METRICS,0))
            for container,name in BASE.CONTAINERS.items():
                for row in book[container]:
                    row.update(hold_anchor=deepcopy(anchor),hold_active=False,hold_floor=None)
                    if name!='ActualOrder':
                        row.update(hold_activated_at=None,hold_entry_breached=False,hold_first_hit_at=None,hold_first_hit_index=-1,hold_first_hit_line=0)
                        if enabled:
                            row.update(hold_active=True,hold_floor=row.get('side',1)*(anchor['stop_price']-row['entry_price']),hold_activated_at=times[0]+1)
                    elif row['kind']=='exit' and enabled:
                        lot=book['lots'][0];row.update(hold_active=True,hold_floor=lot['side']*(anchor['stop_price']-lot['entry_price']))
            qty=len(book['lots'])
            book['metrics'].update(hold_known_entries=qty,hold_activated_lots=qty if enabled else 0)
            current['books'][f'{mode}_D{delay}']=book
    return current,old


def add_partial_hit(current: dict) -> None:
    """
    機能: H1に同原行の部分fill後hitと後続最終片を持つ保存人工を追加する。
    引数: current (dict) は85人工。H0と84対照は変更しない。
    返り値: None。金融計算を再生した結果ではなく、metadata順序だけの人工。
    """
    for delay in (0,1):
        book=current['books'][f'H1G1_D{delay}'];lot=book['lots'][0];at=lot['entry_time']+1
        lot.update(hold_first_hit_at=at,hold_first_hit_index=12,hold_first_hit_line=22)
        first,second=deepcopy(book['closed'][0]),deepcopy(book['closed'][0])
        first.update(quantity=75,pnl5=2100,exit_time=at,exit_line=22)
        second.update(quantity=25,pnl5=700,hold_first_hit_at=at,hold_first_hit_index=12,hold_first_hit_line=22)
        book['closed']=[first,second];book['metrics']['hold_hit_lots']=1


def self_test() -> dict:
    """
    機能: 保持帯出典・4会計・旧投影・hit片順序と66場集合の破損検出を確認する。
    引数: なし。新旧の本物保存・原板・API・Goを使わない。
    返り値: dict は人工の比較件数と破損検出証拠。
    """
    session='2026-11-02_Day';times=[BASE.scheduled(session)[0]];results=[]
    good=fixture(session,times)
    for label,options in (('非0保持帯とH0全旧会計',{}),('出生価格と確認時BBOが異なる',{'birth_shift':-10}),('60秒32更新を含む',{'hold_age':60,'event_age':32}),('時計拒否は通常未知',{'clock_allowed':False})):
        current,old=fixture(session,times,**options);audit=BASE.Audit();audit_scene(current,old,session,times,audit)
        assert audit.bad==0,audit.examples
        results.append({'人工':label,'照合':audit.count,'不一致':0})
    current,old=deepcopy(good);add_partial_hit(current);audit=BASE.Audit();audit_scene(current,old,session,times,audit)
    assert audit.bad==0,audit.examples;results.append({'人工':'先行部分片と同原行後段hitを分離','照合':audit.count,'不一致':0})
    mutations=(
        ('停止線1tick破損',lambda v:v['grid_decisions'][0]['hold_anchor'].update(stop_price=1000)),
        ('quote番号とfeature番号混同',lambda v:v['grid_decisions'][0]['hold_anchor'].update(feature_index=10)),
        ('未知偽装',lambda v:v['grid_decisions'][0]['hold_anchor'].update(known=False)),
        ('H0価格1pt',lambda v:v['books']['H0G1_D0']['trades'][0].update(price=1011)),
        ('H0数値1円',lambda v:v['books']['H0G1_D0']['metrics'].update(net_pnl_yen=2801)),
        ('H1未定義追加フィールド',lambda v:v['books']['H1G1_D1']['metrics'].update(hold_fake=0)),
        ('新規anchor別出典',lambda v:v['books']['H1G1_D0']['orders'][0]['hold_anchor'].update(source_line=99)),
        ('H0有効化偽装',lambda v:v['books']['H0G1_D0'].update(hold_enabled=True)),
        ('H1床1pt',lambda v:v['books']['H1G1_D0']['lots'][0].update(hold_floor=-19)),
        ('H1活性時点破損',lambda v:v['books']['H1G1_D0']['lots'][0].update(hold_activated_at=0)),
        ('EMAを保持帯と偽装',lambda v:v['grid_decisions'][0]['structure_anchor'].update(price=990)),
        ('旧C0政策破損',lambda v:v['grid_decisions'][0]['policies']['C0'].update(allowed=False)),
        ('top候補を旧A0へ戻す',lambda v:v['grid_decisions'][0].update(candidate_accepted=False)),
        ('定時重複',lambda v:v['grid_decisions'].append(deepcopy(v['grid_decisions'][0]))),
        ('保持帯集計破損',lambda v:v['books']['H1G1_D0']['metrics'].update(hold_known_entries=0)),
    )
    for label,mutate in mutations:
        current,old=deepcopy(good);mutate(current);audit=BASE.Audit()
        try:audit_scene(current,old,session,times,audit)
        except (ValueError,KeyError,TypeError):audit.check(False,'人工の入力error',label)
        assert audit.bad>0,label;results.append({'人工':label,'検出':audit.bad})
    current,old=deepcopy(good);add_partial_hit(current);current['books']['H1G1_D0']['closed'][0].update(hold_first_hit_at=times[0]+2,hold_first_hit_index=12,hold_first_hit_line=22)
    audit=BASE.Audit();audit_scene(current,old,session,times,audit);assert audit.bad>0
    results.append({'人工':'先行片への未来hit転記','検出':audit.bad})
    current,old=deepcopy(good)
    current['books']['H0G1_D0']['metrics'].pop('total_cost_yen');old['books']['C0G1_D0']['metrics'].pop('total_cost_yen')
    audit=BASE.Audit();audit_scene(current,old,session,times,audit);assert audit.bad>0
    results.append({'人工':'両側同じ旧フィールド欠落','検出':audit.bad})
    raw=deepcopy(good[0]['grid_decisions'][0])
    invalid=(('別物理行',lambda g:g['decision']['evidence'].update(source_line=99)),('未来確認',lambda g:g['decision']['evidence']['night']['buy'].update(time=g['at']+1)),
        ('60秒超過',lambda g:g['decision']['evidence']['night']['buy'].update(time=g['at']-60.001)),('32更新超過',lambda g:g['decision']['evidence']['night']['buy'].update(event=167)),
        ('非格子出生',lambda g:g['decision']['evidence']['night']['buy'].update(bid=1001)),('非格子要求',lambda g:g['decision']['quote'].update(bid=1001)),
        ('hold方向逆',lambda g:g['decision']['evidence']['night']['buy'].update(side=-1)),('未知構造',lambda g:g['decision']['evidence']['night'].update(known=False)),
        ('bool連番',lambda g:g['decision']['quote'].update(index=True)),('HoldIDゼロ',lambda g:g['decision']['evidence']['night']['buy'].update(id=0)),('非有限要求',lambda g:g['decision']['quote'].update(bid=float('nan'))),('特徴番号とQuote番号の交換',lambda g:g['decision']['evidence'].update(source_index=g['decision']['quote']['index'])))
    for label,mutate in invalid:
        changed=deepcopy(raw);mutate(changed)
        try:expected_hold_anchor(changed,1)
        except (ValueError,KeyError,TypeError):results.append({'人工':label,'入力error検出':True})
        else:raise AssertionError(label+'を拒否しなかった')
    # ----------------------------------------
    # 未来・未知の入力を通常非候補ではcanonical unknownと分離します。
    no_candidate=deepcopy(raw);no_candidate['decision']['evidence']['night']['known']=False
    assert expected_hold_anchor(no_candidate,0)==unknown_hold()
    results.append({'人工':'通常非候補の未知正規化','成功':True})
    no_candidate['at']=float('nan')
    try:expected_hold_anchor(no_candidate,0)
    except ValueError:results.append({'人工':'非候補の非有限要求時刻も拒否','成功':True})
    else:raise AssertionError('非候補NaN要求時刻を拒否しなかった')
    with tempfile.TemporaryDirectory(prefix='85保存人工_',dir=ROOT/'work') as directory:
        source,baseline=Path(directory)/'85',Path(directory)/'84';source.mkdir();baseline.mkdir()
        sessions=[(datetime(2026,1,1)+timedelta(days=i)).date().isoformat()+'_'+kind for i in range(33) for kind in ('Day','Night')]
        for s in sessions:
            current,old=fixture(s,BASE.scheduled(s))
            for path,value in ((source/(s+'.json'),current),(baseline/(s+'.json'),old)):
                path.write_text(json.dumps(value,ensure_ascii=False,allow_nan=False),encoding='utf-8')
        audit=BASE.Audit();data=audit_directories(source,baseline,sessions,None,audit)
        assert audit.bad==0 and data['処理完了'] and data['基準会計数']==132,audit.examples
        results.append({'人工':'全66保存2442枠132基準会計','照合':audit.count,'不一致':0})
        (source/(sessions[0]+'.json')).unlink();(source/'余剰.json').write_text('{}',encoding='utf-8')
        audit=BASE.Audit();data=audit_directories(source,baseline,sessions,None,audit)
        assert audit.bad>0 and not data['処理完了'];results.append({'人工':'欠落余剰を未完検出','検出':audit.bad})
    assert canonical_sha({'a':1,'b':2})==canonical_sha({'b':2,'a':1}) and canonical_sha([1,2])!=canonical_sha([2,1]) and canonical_sha(True)!=canonical_sha(1)
    results.append({'人工':'canonical指紋は配列順序と型を保持','成功':True})
    return {'成功':True,'人工系列':len(results),'人工':results,'正式新保存結果読取':0,'本物原板読取':0,'新売買再生':0,'Go実行':0}


def main() -> None:
    """
    機能: 全66保存結果を旧84正本へ照合し、失敗・未完も新規証拠に残す。
    引数: --input/--baseline/--out (Path) 全必須、又は --self-test (bool)。
    返り値: None。正式失敗は非0終了。市場原板・新売買は実行しない。
    """
    parser=argparse.ArgumentParser()
    for name in ('input','baseline','out'):parser.add_argument('--'+name,type=Path)
    parser.add_argument('--self-test',action='store_true');args=parser.parse_args()
    if args.self_test:
        if any((args.input,args.baseline,args.out)):raise ValueError('人工と正式入力を混在させません')
        print(json.dumps(self_test(),ensure_ascii=False));return
    if not all((args.input,args.baseline,args.out)):raise ValueError('input/baseline/outを全て明示してください')
    if args.out.exists() or any(args.out.resolve().is_relative_to(path.resolve()) for path in (args.input,args.baseline)):raise ValueError('新規証拠を入力外へ保存してください')
    audit=BASE.Audit();small={};data={'処理完了':False,'場数':0,'予定枠':0,'基準会計数':0,'入力不変':False}
    try:
        manifest=ROOT/'study/00080_FAR後期三手法の15分移植と利益保護/入力台帳.json'
        result84=ROOT/'study/00084_現在の価格応答と数量確認/成果物/結果.json'
        conditions=[ROOT/'study'/folder/'条件.json' for folder in ('00085_保持帯の返済側固定否定','00084_現在の価格応答と数量確認','00083_構造否定と利益配分')]
        old_schema=ROOT/'scripts/定時の現在根拠と部分利益保護/actual.go'
        files=[manifest,result84,BASE_PATH,OLD.BASE_PATH,old_schema,*conditions]
        small={path.relative_to(ROOT).as_posix():sha(path) for path in files}
        sessions=[row['id'] for row in BASE.read_json(manifest)['sessions']]
        for path in conditions:
            condition=BASE.read_json(path)
            groups=[condition['コードと依存SHA256']]+[value for name,value in condition.items() if name.startswith('固定') and name.endswith('依存') and type(value) is dict]
            if '実行ファイル' in condition:groups.append({condition['実行ファイル']:condition['実行ファイルSHA256']})
            for group in groups:
                for name,wanted in group.items():audit.check(sha(ROOT/name)==wanted,'新旧固定依存の不変',name)
        data=audit_directories(args.input.resolve(),args.baseline.resolve(),sessions,BASE.read_json(result84)['再生結果SHA256'],audit)
        audit.check({name:sha(ROOT/name) for name in small}==small,'小型固定依存の前後不変','全体')
    except Exception as error:
        audit.check(False,'全体処理未完','全体',type(error).__name__+':'+str(error),'完了')
    success=data['処理完了'] and audit.bad==0
    output={'試行':85,'成功':success,**data,'照合項目数':audit.count,'不一致数':audit.bad,'不一致':audit.examples,'項目別比較数':dict(audit.scope),
        '固定小型入力SHA256':small,'照合コードSHA256':sha(Path(__file__)),'読取helperSHA256':BASE_SHA,'旧比較helperSHA256':OLD.BASE_SHA,
        '新売買再生':0,'本物原板読取':0,'範囲外':['元FAR保持帯出生・EMA/ATRの独立生成','要求物理原行と原板の結合、全占有時系列・約定先着・出口床の再計算（別原板監査）']}
    args.out.parent.mkdir(parents=True,exist_ok=True)
    with args.out.open('x',encoding='utf-8',newline='\n') as stream:json.dump(output,stream,ensure_ascii=False,indent=2,allow_nan=False);stream.write('\n')
    print(json.dumps({name:output[name] for name in ('成功','場数','予定枠','基準会計数','照合項目数','不一致数')},ensure_ascii=False))
    if not success:raise SystemExit(1)


if __name__=='__main__':main()
