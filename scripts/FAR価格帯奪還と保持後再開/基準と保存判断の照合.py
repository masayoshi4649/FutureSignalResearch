"""92 work案。固定89の保存/金融を再用し、価格入口だけを別に照合する。"""

from copy import deepcopy
from collections import Counter
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]
KEYS=tuple(f'{p}G1_D{d}' for d in (0,1) for p in ('H0','H1'))
FIXED=ROOT/'scripts/FAR利益床と収穫配分の比較/基準と保存判断の照合.py'
FIXED_SHA='604602263965696407dfc8906e10c71ff51841115f1ba37b9a97fe207859437b'
SNAPSHOT_FIELDS={'at','window','epoch_start','directions'}
DIRECTION_FIELDS={'side','known','required_unknown','stage','reason','impulse','pullback','impulse_origin','high','low','reclaim','peak','hold','resume','trigger_valid','expires_at'}
COUNT_FIELDS={'records','bars','fresh_impulses','inherited_impulses','episodes','reclaims','peak_updates','holds','hold_updates','resumes','attempt_resets','expired_triggers','resets'}
PRICE_SHA='94f1789889e3448943ed588123abd3fccde7949102a76499618cb2de3eff7a56'


def load(path: Path, name: str, wanted: str | None = None) -> object:
    """
    機能: 明示helperを独立名で読取loadし、固定時は本文SHAを検査する。
    引数: path(Path)、name(str)、wanted(str|None)はコード/名前/任意の固定指紋。
    返り値: objectはAPI。旧ファイルや市場へ書き込まない。
    """
    if wanted is not None and hashlib.sha256(path.read_bytes()).hexdigest()!=wanted:raise ValueError('固定helper本文の変更:'+str(path))
    spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec);sys.modules[name]=module;spec.loader.exec_module(module);return module


OLD=load(FIXED,'saved89_for92_work',FIXED_SHA)
OLD.KEYS=KEYS
BASE=OLD.BASE
strict=OLD.strict
canonical_sha=OLD.canonical_sha


def project_grids(current: dict, policy: str) -> list[dict]:
    """
    機能: 元Sourceを変えず外供給ID列だけを固定89金融の入力へ射影する。
    引数: current(dict)、policy(str)は一場保存とH0/H1。
    返り値: list[dict]は元8field＋C0の定時列。旧E0/E1の順位を書き換えない。
    """
    prices={r['at']:r for r in current['price_decisions']};result=[]
    strict(len(prices)==len(current['price_decisions']),'価格定時の重複')
    for grid in current['grid_decisions']:
        row={n:deepcopy(grid[n]) for n in OLD.OLD.GRID_FIELDS};by={r['reference']['id']:r for r in grid['source']['lots']}
        supplied=prices[grid['at']]['policies'][policy]['supplied_ids'];strict(len(supplied)==len(set(supplied)),'供給IDの重複')
        row['source']['lots']=[deepcopy(by[i]) for i in supplied];result.append(row)
    return result


def audit_legacy(current: dict, baseline: dict, times: list, audit: object) -> dict:
    """
    機能: H0旧89金融とC0/E0/E1/event/Source等の基準scopeを全文照合する。
    引数: current/baseline(dict)、times(list)、audit(object)は92/89一場と予定枠。
    返り値: dictは共有互換の小型証拠。未計測人工の指紋は補完しない。
    """
    session=current['session'];strict(baseline['session']==session and set(current['books'])==set(KEYS),'場/4会計集合')
    BASE.inspect_finite(current,audit,session+'.新');BASE.inspect_finite(baseline,audit,session+'.旧')
    for name in ('quality','reference_counts','source_events','source_equivalence','entry_observations','technical_equivalence','seed_view','input_end','grid_decisions'):
        BASE.compare(current[name],baseline[name],audit,session,'固定89共有全文:'+name)
    strict([g['at'] for g in current['grid_decisions']]==times,'予定定時順')
    OLD.inspect_events(current,audit,session)
    OLD.OLD.verify_equivalence(current,times,audit,session)
    for delay in (0,1):BASE.compare(current['books'][f'H0G1_D{delay}'],baseline['books'][f'E1G1_D{delay}'],audit,session,'旧89 E1G1 control全Book')
    expected=[]
    for binding in baseline['entry_bindings']:
        if binding['book_key'] not in ('E1G1_D0','E1G1_D1'):continue
        row=deepcopy(binding);row['book_key']=row['book_key'].replace('E1G1','H0G1');expected.append(row)
    BASE.compare(current['entry_bindings'],expected,audit,session,'H0旧E1外binding全文/外book名だけ対応')
    return {'基準C0枠':len(times),'基準会計':2,'保存会計':4,'Source互換':deepcopy(current['source_equivalence']),'Technical互換':deepcopy(current['technical_equivalence'])}


def audit_financial(current: dict, audit: object) -> dict:
    """
    機能: 固定89の純選別/不変binding/Source作用/利益snapshotを4会計へ適用する。
    引数: current(dict)、audit(object)は一場保存と照合台帳。
    返り値: dictは全会計の受理元・通知要約・利益出典。
    """
    session=current['session'];bindings={};effects={}
    for key in KEYS:
        book=current['books'][key];strict(book['mode']=='S0G1' and book['source_policy']=='S' and book['hold_enabled'] is False and book['confirm_enabled'] is False,'固定89 S/G1金融')
        OLD.OLD.validate_book_schema(book,audit,session+key);grids=project_grids(current,key[:2]);selected=OLD.bind_decisions(book,grids,session,key,audit)
        OLD.OLD.bind_entries(book,selected,grids,audit,session+key);effects[key]=OLD.OLD.bind_effects(book,current['source_events'],session,audit,session+key);bindings[key]=selected
    profit=OLD.inspect_profit_contexts(current,audit,session)
    return {'受理出典':bindings,'Source通知適用':effects,'初回利益観測':profit}


def diagnostic_rows(current: dict) -> list[dict]:
    """
    機能: 固定87/89の位置ID別玉診断を4外ラベルで再用する。
    引数: current(dict)は一場保存。
    返り値: list[dict]は実玉/注文/返済片。金融本文を複製実装しない。
    """
    return [row for key in KEYS for row in OLD.OLD.diagnostic_rows(current['session'],key,current['books'][key])]


def filter_price(policy: str, grid: dict, snapshot: dict) -> dict:
    """
    機能: 旧E1又はE0基礎poolから新政策の全評価と実供給順位を独立計算する。
    引数: policy(str)、grid/snapshot(dict)はH0/H1と旧定時/独立状態。
    返り値: dictは基礎と最終を区別したPriceSupply。時計不可でも基礎順位は純資格順。
    """
    strict(policy in ('H0','H1') and snapshot['at']==grid['at'],'価格政策/当定時')
    base='E1' if policy=='H0' else 'E0';_,pool=OLD.EVENT.filter_pool(base,grid['source'],grid['entry'])
    states={d['side']:d for d in snapshot['directions']};current={d['side']:d for d in grid['entry']['directions']};q=grid['c0']['base']['quote']
    result={'policy':policy,'base_policy':base,'supplied_ids':[],'pool':[]}
    for p in pool:
        side=p['side'];d=states[side];now=current[side]
        row={'reference_id':p['reference_id'],'side':side,'raw_rank':p['raw_rank'],'base_supplied_rank':p['supplied_rank'],'supplied_rank':None,
             'base_allowed':p['allowed'],'old_e0_allowed':now['e0_allowed'],'old_e1_allowed':now['e1_allowed'],'known':p['known'],'allowed':p['allowed'],'required_unknown':p['required_unknown'],'reason':p['reason']}
        if policy=='H1':
            row['known']=p['known'] and d['known'];row['required_unknown']=not row['known']
            bbo=grid['entry']['quote_time']<=grid['at'] and q['valid'] and 0<q['bid']<q['ask']
            above=d['high'] is not None and bbo and min(side*q['bid'],side*q['ask'])>side*d['high']['close']
            row['allowed']=p['allowed'] and d['known'] and d['trigger_valid'] and above
            row['reason']='現在資格又は独立価格の必要値が未知' if row['required_unknown'] else '現在E0資格が既知不成立' if not p['allowed'] else '現在E0と独立価格triggerと両気配維持が成立' if row['allowed'] else '独立価格trigger又は現在価格帯が不成立'
        if row['allowed'] and grid['clock_allowed']:
            result['supplied_ids'].append(p['reference_id']);row['supplied_rank']=len(result['supplied_ids'])
        result['pool'].append(row)
    return result


def inspect_price(current: dict, audit: object, finder_factory: object) -> object:
    """
    機能: 全既存Recordを独立finderへ送り全定時状態・全pool・供給を照合する。
    引数: current(dict)、audit(object)、finder_factory(callable)は一場/台帳/独立Python生成器。
    返り値: objectは全Record処理済finder。金融/Source/損益を入力しない。
    """
    records=current['entry_observations'];prices=current['price_decisions'];grids=current['grid_decisions'];finder=finder_factory(current['session']);cursor=0
    strict(len(prices)==len(grids) and [p['at'] for p in prices]==[g['at'] for g in grids],'価格全定時順')
    for g,p in zip(grids,prices,strict=True):
        while cursor<len(records):
            x=records[cursor]['input']
            if x['at']>g['at'] or x['at']==g['at'] and x['origin']=='quote':break
            finder.feed(records[cursor]);cursor+=1
        expected=finder.snapshot(g['at'])
        strict(set(p['snapshot'])==SNAPSHOT_FIELDS and len(p['snapshot']['directions'])==2 and {d['side'] for d in p['snapshot']['directions']}=={-1,1},'独立snapshot4tag/2方向')
        for d in p['snapshot']['directions']:
            strict(set(d)==DIRECTION_FIELDS and all(type(d[n]) is bool for n in ('known','required_unknown','trigger_valid')) and d['known'] is not d['required_unknown'],'独立方向16tag/既知型')
            for n in ('impulse','pullback','reclaim','hold','resume'):
                strict(d[n] is None or set(d[n])=={'observation_id','bar_end','published_at'},'独立Point3tag')
            for n in ('high','low','peak'):
                strict(d[n] is None or set(d[n])=={'point','close'} and set(d[n]['point'])=={'observation_id','bar_end','published_at'},'独立Level/Point集合')
        BASE.compare(p['snapshot'],expected,audit,current['session'],'独立価格snapshot全16tag')
        strict(set(p)=={'at','snapshot','policies'} and set(p['policies'])=={'H0','H1'},'追加価格定時/2政策集合')
        for policy in ('H0','H1'):BASE.compare(p['policies'][policy],filter_price(policy,g,expected),audit,current['session']+policy,'基礎E0/E1と独立v/気配/全供給順位')
    for record in records[cursor:]:finder.feed(record)
    counts=current['price_counts'];strict(set(counts)==COUNT_FIELDS and type(counts['resets']) is dict,'独立価格counter13tag')
    strict(all(type(v) is int and v>=0 for n,v in counts.items() if n!='resets') and all(type(v) is int and v>=0 for v in counts['resets'].values()),'独立価格counterの非負int型')
    BASE.compare(counts,finder.counts(),audit,current['session'],'全Record後の価格分母/共通reset call数')
    return finder


def inspect_price_bindings(current: dict, audit: object) -> None:
    """
    機能: 全4会計の受理後に外価格根拠と基礎/最終順位を不変結合する。
    引数: current(dict)、audit(object)は一場保存と台帳。
    返り値: None。H0の価格状態を資格gateにせず、H1のE1falseを改名しない。
    """
    expected=[];legacy=[];prices={p['at']:p for p in current['price_decisions']}
    for g in current['grid_decisions']:
        p=prices[g['at']]
        for policy in ('H0','H1'):
            supply=p['policies'][policy]
            for delay in (0,1):
                key=f'{policy}G1_D{delay}';book=current['books'][key];d=next(d for d in book['decisions'] if d['at']==g['at'])
                if d['action']!='新規要求':continue
                orders=[o for o in book['orders'] if o['kind']=='entry' and o['request_time']==g['at']];strict(len(orders)==1,'外価格binding一枠一要求');o=orders[0]
                row=next(r for r in supply['pool'] if r['reference_id']==o['reference_id']);now=next(r for r in g['entry']['directions'] if r['side']==o['side']);state=next(r for r in p['snapshot']['directions'] if r['side']==o['side'])
                strict(g['clock_allowed'] and row['allowed'] and row['base_supplied_rank'] is not None and row['supplied_rank'] is not None and o['source_entry']['rank']==row['supplied_rank'],'受理と供給三順位')
                strict(now['e1_allowed'] if policy=='H0' else now['e0_allowed'] and state['trigger_valid'],'基礎E1/現在E0と新価格の独立境界')
                expected.append({'book_key':key,'policy':policy,'base_policy':supply['base_policy'],'delay_seconds':delay,'entry_order_id':o['id'],'position_id':o['position_id'],'reference_id':o['reference_id'],'at':g['at'],'requested_quantity':o['quantity'],
                  'raw_rank':row['raw_rank'],'base_supplied_rank':row['base_supplied_rank'],'supplied_rank':row['supplied_rank'],'source_method':g['source']['method'],'source_at':g['source']['at'],'source_index':g['source']['source_index'],
                  'pool_evaluation':deepcopy(row),'current_qualification':deepcopy(now),'price_qualification':deepcopy(state)})
                if policy=='H0':
                    oldrow=next(r for r in g['policies']['E1']['pool'] if r['reference_id']==o['reference_id'])
                    legacy.append({'book_key':key,'policy':'E1','delay_seconds':delay,'entry_order_id':o['id'],'position_id':o['position_id'],'reference_id':o['reference_id'],'at':g['at'],'requested_quantity':o['quantity'],'raw_rank':oldrow['raw_rank'],'supplied_rank':oldrow['supplied_rank'],
                      'source_method':g['source']['method'],'source_at':g['source']['at'],'source_index':g['source']['source_index'],'pool_evaluation':deepcopy(oldrow),'current_qualification':deepcopy(now)})
    BASE.compare(current['price_bindings'],expected,audit,current['session'],'全受理価格binding/旧資格原値と新根拠を凍結')
    BASE.compare(current['entry_bindings'],legacy,audit,current['session'],'旧E1外bindingはH0受理だけに保存')


def audit_scene(current: dict, baseline: dict, session: str, times: list, audit: object, require_shared: bool = True) -> dict:
    """
    機能: 旧89対照と新価格/全供給/受理・固定金融を一場分照合する。
    引数: current/baseline(dict)、session(str)、times(list)、audit(object)、require_shared(bool)は新旧保存と人工scope。
    返り値: dictは小型照合証拠。正式は全面scope、人工限定は未計測を明記。
    """
    strict(type(require_shared) is bool and current['session']==session and set(current)==OLD.TOP_FIELDS|{'price_decisions','price_bindings','price_counts'},'92本文集合/場/人工scope型')
    BASE.inspect_finite(current,audit,session)
    if require_shared:legacy=audit_legacy(current,baseline,times,audit)
    else:
        eq=current['source_equivalence'];strict(all(eq[n]==0 for n in ('step_frames','force_frames','grid_frames','mismatches')) and eq['current_sha256']==eq['legacy_sha256']=='','人工の未計測Source指紋を補完しない')
        for d in (0,1):BASE.compare(current['books'][f'H0G1_D{d}'],baseline['books'][f'E1G1_D{d}'],audit,session,'限定API旧89対照全Book')
        OLD.inspect_events(current,audit,session);legacy={'基準C0枠':0,'基準会計':2,'保存会計':4,'Source互換':'未計測','Technical互換':'旧全面同値scope外'}
    price=load(Path(__file__).with_name('価格構造.py'),'price92_saved_independent',PRICE_SHA);tracker=inspect_price(current,audit,price.PriceTracker);inspect_price_bindings(current,audit);financial=audit_financial(current,audit)
    shared={n:current[n] for n in ('grid_decisions','source_events','source_equivalence','entry_observations','technical_equivalence','seed_view','input_end','profit_contexts','price_decisions','price_counts')}
    source={'session':session,'books':{key:{n:current['books'][key][n] for n in ('source_policy','decisions','source_effects')} for key in KEYS},'entry_bindings':current['entry_bindings'],'price_bindings':current['price_bindings']}
    actions=[{'session':session,'key':key,'金融判断':dict(Counter(d['action'] for d in current['books'][key]['decisions'])),'方針判断':policy_actions(current,key)} for key in KEYS]
    return {'場':session,'予定枠':len(times),**legacy,'Source生成全面同値scope':require_shared,'独立価格':tracker.counts(),'初回利益観測':financial['初回利益観測'],'Source通知適用':financial['Source通知適用'],'方針判断':actions,'外新規binding':len(current['price_bindings']),'旧E1binding':len(current['entry_bindings']),'イベント入力':len(current['entry_observations']),
      '共有判断SHA256':canonical_sha(shared),'参照判断と通知効果SHA256':canonical_sha(source),'玉診断SHA256':{key:canonical_sha(OLD.OLD.diagnostic_rows(session,key,current['books'][key])) for key in KEYS},'本処理の新市場/原板読取':0}


def policy_actions(scene: dict, key: str) -> dict:
    """
    機能: 外価格/現在資格の未知を非占有の金融待ちだけへ別分類する。
    引数: scene(dict)、key(str)は保存一場と外会計。
    返り値: dictは政策判断件数。金融の原値を書き換えない。
    """
    book=scene['books'][key];grids={g['at']:g for g in scene['grid_decisions']};prices={g['at']:g for g in scene['price_decisions']};counts=Counter()
    for d in book['decisions']:
        g=grids[d['at']];action=d['action']
        if action=='待ち' and g['clock_allowed'] and not d['source_context']['occupied']:
            seen={o['reference_id'] for o in book['orders'] if o['kind']=='entry' and o['request_time']<g['at']}
            raw={r['reference']['id'] for r in g['source']['lots'] if not r['reference']['closing'] and r['reference']['id'] not in seen}
            q=g['c0']['base']['quote'];source=g['source'];quality=q['valid'] and q['last']>0 and 0<q['bid']<q['ask'] and q['index']>=0 and q['line']>0 and 0<=g['at']-q['time']<=15 and source['started'] and source['at']==q['time']
            if raw and (not quality or any(p['required_unknown'] for p in prices[g['at']]['policies'][key[:2]]['pool'] if p['reference_id'] in raw)):action='判定不能'
        counts[action]+=1
    return dict(counts)


def audit_directories(source: Path, baseline: Path, sessions: list, pinned: dict, audit: object) -> dict:
    """
    機能: 正式66場の新4会計/旧2対照と保存入力前後指紋を確認する。
    引数: source/baseline(Path)、sessions(list)、pinned(dict)、audit(object)は新旧JSON根と旧固定指紋。
    返り値: dictは小型全場証拠。原板又は新売買を起動しない。
    """
    roots={'92':source,'89':baseline};before={n:BASE.inventory(p) for n,p in roots.items()};wanted={s+'.json' for s in sessions};rows=[];complete=True
    strict(len(sessions)==len(set(sessions))==66,'固定一意66場')
    for name,files in before.items():audit.check(set(files)==wanted,'保存場集合',name)
    audit.check(before['89']==pinned,'旧89全保存指紋','全体')
    try:
        for session in sessions:
            rows.append(audit_scene(BASE.read_json(source/(session+'.json')),BASE.read_json(baseline/(session+'.json')),session,BASE.scheduled(session),audit))
    except Exception as error:
        complete=False;audit.check(False,'保存処理未完','全体',type(error).__name__+':'+str(error),'全場完了')
    after={n:BASE.inventory(p) for n,p in roots.items()};audit.check(before==after,'保存入力前後不変','全体')
    frames=sum(r['基準C0枠'] for r in rows);old_accounts=sum(r['基準会計'] for r in rows);accounts=sum(r['保存会計'] for r in rows)
    full=(len(rows),frames,old_accounts,accounts)==(66,2442,132,264);audit.check(full,'66場2442枠132対照264保存','全体')
    return {'処理完了':complete and full,'場数':len(rows),'予定枠':frames,'基準C0枠':frames,'基準会計':old_accounts,'保存会計':accounts,'入力不変':before==after,'入力SHA256前':before,'入力SHA256後':after,
      '対象場':rows,'方針判断':[a for r in rows for a in r['方針判断']],'イベント入力':sum(r['イベント入力'] for r in rows),'外新規binding':sum(r['外新規binding'] for r in rows)}


def main() -> None:
    """
    機能: 明示66場の保存JSONだけを固定旧89へ照合して証拠を新規保存する。
    引数: --input/--baseline/--out(Path)は全必須。人工scopeをCLIへ公開しない。
    返り値: None。未完/変化/不一致は証拠保存後に非0終了。
    """
    parser=argparse.ArgumentParser(description='92独立価格入口の基準と保存判断照合')
    for name in ('input','baseline','out'):parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args();strict(not args.out.exists() and not any(args.out.resolve().is_relative_to(p.resolve()) for p in (args.input,args.baseline)),'新規証拠を保存入力外へ指定')
    audit=BASE.Audit();code=OLD.sha(Path(__file__));manifest=ROOT/'study/00080_FAR後期三手法の15分移植と利益保護/入力台帳.json';previous=ROOT/'study/00089_最低建値床を共通にした収穫配分の比較/成果物/結果.json';condition=ROOT/'study/00092_価格帯奪還と保持後の独立再開/条件.json'
    paths=(manifest,previous,condition,FIXED,Path(__file__).with_name('価格構造.py'),OLD.EVENT_PATH);small={};data={'処理完了':False,'場数':0,'基準C0枠':0,'基準会計':0,'保存会計':0,'入力不変':False}
    try:
        small={p.relative_to(ROOT).as_posix():OLD.sha(p) for p in paths};fixed=BASE.read_json(condition)
        for name,group in fixed.items():
            if name=='コードと依存SHA256' or name.startswith('固定') and name.endswith('依存') and type(group) is dict:
                for path,wanted in group.items():audit.check(OLD.sha(ROOT/path)==wanted,'固定依存SHA256',path)
        sessions=[r['id'] for r in BASE.read_json(manifest)['sessions']];data=audit_directories(args.input.resolve(),args.baseline.resolve(),sessions,BASE.read_json(previous)['再生結果SHA256'],audit)
        audit.check({n:OLD.sha(ROOT/n) for n in small}==small and OLD.sha(Path(__file__))==code,'小型依存/保存コード前後不変','全体')
    except Exception as error:audit.check(False,'全体処理未完','全体',type(error).__name__+':'+str(error),'完了')
    success=data['処理完了'] and audit.bad==0;output={'試行':92,'成功':success,**data,'照合項目数':audit.count,'不一致数':audit.bad,'不一致':audit.examples,'項目別比較数':dict(audit.scope),'固定小型入力SHA256':small,'照合コードSHA256':code,'固定89保存監査SHA256':FIXED_SHA,'読取helperSHA256':OLD.OLD_SHA,'独立価格コードSHA256':PRICE_SHA,'イベント照合コードSHA256':OLD.sha(OLD.EVENT_PATH),'本処理の新売買再生':0,'本物原板読取':0}
    args.out.parent.mkdir(parents=True,exist_ok=True)
    with args.out.open('x',encoding='utf-8',newline='\n') as stream:json.dump(output,stream,ensure_ascii=False,indent=2,allow_nan=False);stream.write('\n')
    print(json.dumps({k:output[k] for k in ('成功','場数','基準会計','保存会計','照合項目数','不一致数')},ensure_ascii=False))
    if not success:raise SystemExit(1)


if __name__=='__main__':main()

