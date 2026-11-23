"""74の新価格順序と三政策の保存運用を、原BBOと固定監査で独立照合する。"""

import argparse
from collections import Counter, defaultdict
from copy import deepcopy
from datetime import datetime
from decimal import Decimal
import hashlib
import importlib.util
import json
from pathlib import Path
import statistics
import sys
from urllib.parse import urlencode, urljoin


ROOT=Path(__file__).resolve().parents[2]
HERE=Path(__file__).resolve().parent
STUDY=ROOT/'study/00074_内包足の偽突破確認と局面切替'
WORK=ROOT/'work/内包足の偽突破と局面切替/00074'
OLD=ROOT/'study/00073_直近の集中と方向効率を組み合わせる'
OLDWORK=ROOT/'work/直近進行の集中と効率/00073'
LEDGER=OLDWORK.parent/'73完了記録.json'
LEDGER_SHA='8dee76e55114a68c18c40da3514a3c1b417f27d79969bf2ff91f14f9f00231ae'
IMMEDIATE=ROOT/'work/独立追尾回収/00055/独立測定.jsonl.gz'
CONDITIONAL=ROOT/'work/条件入口の教師/00069/条件独立測定.jsonl.gz'
POLICIES=('I0','H0','H1')
ALL_POLICIES=('Q0',*POLICIES)
PERIODS=('学習','条件選択','後続検査')
BINDING=('session','slot_id','scheduled','time','line')
PURE=('scheduled','time','line','side','role','atr','D','reason','ready','slot_id')


# ----------------------------------------
def load_fixed(path: Path,name: str,digest: str | None = None):
    """監査純補助だけを固有名で読み、旧大域値を変更しない。

    引数: path(Path)はコード、name(str)は固有名、digest(str|None)は固定SHA。
    返り値: ModuleTypeは読込結果。新I/主/Engineを正式期待値へ呼ばない。
    """
    if digest is not None and hashlib.sha256(path.read_bytes()).hexdigest()!=digest:
        raise ValueError('固定監査依存の変更:'+path.name)
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec);sys.modules[name]=module;spec.loader.exec_module(module)
    return module


R73=load_fixed(ROOT/'scripts/直近進行の集中と効率/保存検証.py','内包74の固定73監査','94d8fcc536418303648da1d60e433ecc5a6c1c6e85ca99ca045bf18816e4ac14')
INPUT=load_fixed(HERE/'入力監査.py','内包74の独立入力','e01f1577af451da5c32855134f35bb564111777361cbd8d7648f0ff14b314ae3')
R69,R68,R55,P,A=R73.R69,R73.R68,R73.R55,R73.P,R73.A


# ----------------------------------------
def close_sum(rows: list[dict],fee: int) -> float:
    """保存完結の十進現金を独立に合算する。

    引数: rows(list[dict])は完結、fee(int)は0/5/10。
    返り値: floatは観測円額。未解消や品質を確定0へ補完しない。
    """
    return float(sum((Decimal(str(row['pnl'+str(fee)])) for row in rows),Decimal(0)))


def distribution(values: list) -> dict:
    """元枠順の有限取得差を四統計にまとめる。

    引数: values(list[float])は符号付き価格又は時計差。
    返り値: dictは平均/中央値/最小/最大。空はNone。
    """
    return {'平均':sum(values)/len(values) if values else None,'中央値':statistics.median(values) if values else None,
        '最小':min(values) if values else None,'最大':max(values) if values else None}


def read_banks(identities: set,source,audit) -> dict:
    """成功指紋の旧55/69を読み、対象元枠の測定出典と経済情報だけを残す。

    引数: identities(set)は対象予定枠、source/auditは固定読取と検査。
    返り値: dictは即時/条件の方向索引。再測定せずoperationNoneも保持する。
    """
    pins=source.read(OLD/'固定.json')['ファイルSHA256']
    banks={}
    for kind,path in (('即時',IMMEDIATE),('条件',CONDITIONAL)):
        audit.check('旧測定指紋:'+kind,source.sha(path),pins[path.relative_to(ROOT).as_posix()])
        bank={}
        for row in source.json_rows(path):
            if row['slot_id'] not in identities:
                continue
            key=row['slot_id'],row['side']
            if key in bank:
                raise ValueError('旧方向測定重複')
            operation=row['operation']
            pure=row if kind=='即時' else operation['conditions'][row['slot_id']]['slot']
            binding={key:row[key] for key in (*BINDING,'side')}
            binding.update({name:pure[name] for name in ('ready','atr','D')})
            bank[key]={'barrier':row['barrier'],'closed':deepcopy(operation['closed']) if operation is not None else None,
                'binding':binding,'observed':operation['conditions'][row['slot_id']]['last_observation_time'] if kind=='条件' else None}
        banks[kind]=bank
    return banks


def expected_condition(old: dict) -> dict:
    """旧73の当時currentを、そのまま既存68の固定条件へ写す。

    引数: old(dict)は旧Q0の準備済み純slot/feature。
    返り値: dictはhigh/low/source/expires。H形のI端とは取り違えない。
    """
    row=old['feature']['base']['base']['sources']['current']
    if row['end']>old['scheduled'] or (row['confirm'],row['confirm_line'])>(old['time'],old['line']):
        raise ValueError('条件currentが当時不可視')
    return {'high':row['high'],'low':row['low'],'source':deepcopy(row),'expires':old['scheduled']+900}


def label_for(slot: dict,old: dict,kind: str,banks: dict,audit) -> tuple:
    """採用方向を旧独立先着へ厳密結合し、説明由来だけを新政策へ写す。

    引数: slot/old(dict)は新純/元Q0、kind(str)は即時/条件、banks(dict)は旧測定、auditは検査。
    返り値: tuple[dict,dict]は新先着と旧縮約測定。教師・将来情報を採否へ戻さない。
    """
    record=banks[kind][slot['slot_id'],slot['side']]
    binding={key:slot[key] for key in (*BINDING,'side','ready','atr','D')}
    audit.check('独立測定凍結入力:'+kind,record['binding'],binding)
    prior=record['barrier']
    if prior is None:
        raise ValueError('採用方向の旧独立先着なし')
    clock=prior.get('origin_slot',prior)
    for key in (*BINDING,'side'):
        audit.check('旧先着元入力:'+key,clock.get(key,prior.get(key)),slot[key])
    if kind=='条件':
        audit.check('旧独立と同current条件',prior['condition'],expected_condition(old))
    value=deepcopy(prior)
    value.update(policy=slot['policy'],role=slot['role'],origin=slot['origin'],pattern_id=slot['pattern_id'])
    return value,record


def check_immediate(block: dict,tape: dict,source,audit) -> dict:
    """即時49の全定時・最初BBO・現金・保護・保有品質を独立照合する。

    引数: block/tape(dict)は保存運用/原配列、source/auditは固定49と記録。
    返り値: dictは独立会計account。戦略を再生しない。
    """
    operation=block['operation']
    audit.check('即時は条件監視なし',block['conditions'],{})
    source.check_decisions(block,tape,audit)
    for decision in operation['decisions']:
        logs=[row for row in operation['trail'] if row['action']=='定時判断' and row.get('decision',{}).get('slot_id')==decision['slot_id']]
        audit.check('即時定時snapshot一件',len(logs),1)
        if logs:
            state=logs[0]['state']
            audit.check('即時定時保有snapshot',decision['holding'],state['position'] is not None)
            expected_pending='entry' if decision['action'] in ('買い新規要求','売り新規要求') else decision['pending_kind']
            audit.check('即時定時pending snapshot',state['pending']['kind'] if state['pending'] else None,expected_pending)
    source.check_orders(operation,tape,audit)
    source.check_trail(operation,tape,audit)
    R55.check_measurement_quality(operation,tape,audit)
    result=source.check_cash(operation,operation['trades'],tape,audit)
    result['conditions']={}
    return result


# ----------------------------------------
def check_api(base: str | None,resources: list[dict],accounts: list[dict],source,audit) -> dict:
    """184資源と新三政策の各一代表をViewerの数値へ結ぶ。

    引数: base(str|None)はURL、resources/accounts(list[dict])は保存値、source/auditは固定読取と記録。
    返り値: dictはAPI検証範囲。未指定を成功扱いしない。
    """
    if not base:
        return {'実行':False,'理由':'--viewer-url未指定。API未検証、新138保存約定は全件照合'}
    query={'catalog_path':(STUDY/'一覧.resources.json').relative_to(ROOT).as_posix()}
    listing,_,_=source.fetch_json(base+'/api/resources?'+urlencode(query))
    audit.check('API184資源全集合',{r['id'] for r in listing['resources']},{r['id'] for r in resources})
    audit.check('API184資源数',len(listing['resources']),184)
    representatives=[]
    for policy in POLICIES:
        account=sorted([r for r in accounts if r['candidate']==policy],key=lambda r:(-abs(r['ledger']['5']),r['session']))[0]
        resource=next(r for r in resources if r['method_id']==policy and r['session']==account['session'])
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
    """保存された形・純候補・三つの一枚運用を独立に照合する。

    引数: viewer_url(str|None)は任意のViewer API。
    返り値: dictは一度だけ保存する公式proof。新I/主/Engineを期待値として呼ばない。
    """
    destination=STUDY/'保存物確認.json'
    if destination.exists():
        raise FileExistsError('74保存監査は作成済み。再実行しません')
    source,_,summary=A.helpers()
    audit=source.Audit()
    result,fixed,inputs=[source.read(STUDY/name) for name in ('結果.json','固定.json','入力台帳.json')]
    previous,proof,ledger=[source.read(path) for path in (OLD/'結果.json',OLD/'保存物確認.json',LEDGER)]
    preflight_path=WORK.parent/'入力確認.json'
    files=[STUDY/name for name in ('結果.json','固定.json','条件.json','入力台帳.json','一覧.resources.json')]
    files += [WORK/name for name in ('技法観測.jsonl.gz','定時判断と運用.jsonl.gz','入口先着.jsonl.gz','実行完了.json')]
    files += [OLD/name for name in ('結果.json','保存物確認.json','固定.json','一覧.resources.json')]
    files += [OLDWORK/name for name in ('定時判断と運用.jsonl.gz','入口先着.jsonl.gz','実行完了.json')]
    files += [LEDGER,IMMEDIATE,CONDITIONAL,preflight_path,source.MANIFEST,Path(__file__),HERE/'入力監査.py']
    before={path.relative_to(ROOT).as_posix():source.sha(path) for path in files}
    for name,digest in fixed['ファイルSHA256'].items():
        audit.check('74固定:'+name,source.sha(ROOT/name),digest);before[name]=digest
    for name,digest in inputs['参照SHA256'].items():
        audit.check('74入力:'+name,source.sha(ROOT/name),digest);before[name]=digest
    audit.check('73台帳SHA',source.sha(LEDGER),LEDGER_SHA)
    audit.check('73完了対象数',len(ledger['成果物SHA256']),259)
    for name,digest in ledger['成果物SHA256'].items():
        audit.check('73完了不変:'+name,source.sha(ROOT/name),digest);before[name]=digest
    audit.check('73成功監査',(proof['全件一致'],proof['不一致数'],proof['結果SHA256']),(True,0,source.sha(OLD/'結果.json')))
    audit.check('73単一完了',source.read(OLDWORK/'実行完了.json')['結果SHA256'],source.sha(OLD/'結果.json'))
    audit.check('74単一完了',source.read(WORK/'実行完了.json')['結果SHA256'],source.sha(STUDY/'結果.json'))
    audit.check('74固定bind',(result['試行'],result['固定SHA256'],result['全66場既使用']),(74,source.sha(STUDY/'固定.json'),True))
    audit.check('74新処理範囲',tuple(result[k] for k in ('新fit','新分類器fit','新モデル','新独立測定','新運用数','保存参照運用数','Viewer資源')),(0,0,0,0,138,46,184))
    audit.check('74政策集合',set(result['候補']),set(ALL_POLICIES))
    audit.check('74設定全文',result['設定'],source.read(STUDY/'条件.json'))
    audit.check('既使用台帳SHA',source.sha(source.MANIFEST),inputs['参照SHA256'][source.MANIFEST.relative_to(ROOT).as_posix()])
    entries=source.read(source.MANIFEST)['entries']
    audit.check('既使用66場',len(entries),66)
    evaluated=[r['session'] for r in entries[20:]]
    audit.check('同46評価場',result['評価場'],evaluated)
    audit.check('旧73同46評価場',previous['評価場'],evaluated)
    old={r['session']:r for r in source.json_rows(OLDWORK/'定時判断と運用.jsonl.gz') if r['policy']=='Q0'}
    audit.check('旧Q0保存46',list(old),evaluated)
    identities=[s['slot_id'] for block in old.values() for s in block['slots']]
    audit.check('全1702予定一意',(len(identities),len(set(identities))),(1702,1702))
    # ----------------------------------------
    # 価格SOURCE15だけの別算法を使い、旧73特徴算術や教師を再生成しない。
    observations={}
    observed_order=[]
    for row in source.json_rows(WORK/'技法観測.jsonl.gz'):
        if row['slot_id'] in observations:
            raise ValueError('保存技法観測の重複')
        observations[row['slot_id']]=row['observation'];observed_order.append((row['session'],row['slot_id']))
    audit.check('全観測集合',set(observations),set(identities))
    audit.check('全観測保存順',observed_order,[(s['session'],s['slot_id']) for block in old.values() for s in block['slots']])
    chosen={policy:{} for policy in POLICIES}
    ready=adopted=0
    for session in evaluated:
        block=old[session]
        for slot in block['slots']:
            obs=INPUT.derive(slot,slot['feature'])
            audit.check('SOURCE15/形/直接gate全文',observations[slot['slot_id']],obs)
            ready+=obs['ready']
            for policy in POLICIES:
                chosen[policy][slot['slot_id']]=INPUT.choose(slot,obs,policy)
            a,b=chosen['H0'][slot['slot_id']],chosen['H1'][slot['slot_id']]
            audit.check('H0H1純同値',{k:v for k,v in a.items() if k!='policy'},{k:v for k,v in b.items() if k!='policy'})
            audit.check('I0旧Q0純10同値',{k:chosen['I0'][slot['slot_id']][k] for k in PURE},{k:slot[k] for k in PURE})
            adopted+=a['origin']=='内包偽突破'
    preflight=source.read(preflight_path)
    expected_preflight={'試行':74,'成功':True,'全予定':1702,'準備済み':ready,'別算一致':1702,'新H採用':adopted,
        '保存Q0正本の読取':True,'旧独立測定読取':False,'先着損益による新候補選択':False,'新先着回収計算':False,'新市場再生':False,
        '観測SHA256':source.sha(WORK/'技法観測.jsonl.gz'),'入力コードSHA256':source.sha(HERE/'入力.py'),'入力監査コードSHA256':source.sha(HERE/'入力監査.py')}
    audit.check('74事前入力全文',preflight,expected_preflight)
    banks=read_banks(set(identities),source,audit)
    detail=defaultdict(list)
    for block in source.json_rows(WORK/'定時判断と運用.jsonl.gz'):
        detail[block['session']].append(block)
    audit.check('新詳細46場',set(detail),set(evaluated))
    resources=source.read(STUDY/'一覧.resources.json')['resources']
    resource_map={(r['session'],r['method_id']):r for r in resources}
    audit.check('184資源一意',(len(resources),len({r['id'] for r in resources}),len(resource_map)),(184,184,184))
    audit.check('184資源全集合',set(resource_map),{(s,p) for s in evaluated for p in ALL_POLICIES})
    for row in source.read(OLD/'一覧.resources.json')['resources']:
        if row['method_id']=='Q0':
            audit.check('保存Q0資源全文',resource_map[row['session'],'Q0'],row)
    labels={p:[] for p in ALL_POLICIES};slots={p:[] for p in ALL_POLICIES};accounts={p:[] for p in ALL_POLICIES}
    phase_by_session={r['session']:phase['id'] for phase in R69.phases(entries,source) for r in phase['evaluation']}
    cache_pins,viewer_pins,summaries={},{},[]
    entry_matches=closed_matches=0
    for entry in entries[20:]:
        session=entry['session'];old_slots={r['slot_id']:r for r in old[session]['slots']}
        reference=[{**{k:s[k] for k in PURE},'session':session,'policy':'Q0','origin':'保存Q0','pattern_id':None} for s in old[session]['slots']]
        slots['Q0'].extend(reference)
        account=P.account(old[session]['operation'],source,audit)
        account['conditions']=old[session]['operation']['conditions'];accounts['Q0'].append(account)
        for slot in reference:
            if slot['side']:
                label,_=label_for(slot,old_slots[slot['slot_id']],'条件',banks,audit);labels['Q0'].append(label)
        tape,cache_path,digest,quality=R55.load_tape(entry,source,audit)
        cache_pins[cache_path]=digest
        audit.check('73成功cachebind',digest,proof['キャッシュSHA256'][cache_path])
        audit.check('新三政策順',[b['policy'] for b in detail[session]],list(POLICIES))
        for block in detail[session]:
            policy=block['policy'];kind='条件' if policy=='H0' else '即時'
            selected=[chosen[policy][r['slot_id']] for r in old[session]['slots']]
            audit.check('74純全14項目',block['slots'],selected)
            audit.check('74評価phase',block['phase'],phase_by_session[session])
            slots[policy].extend(selected)
            expected_conditions={s['slot_id']:expected_condition(old_slots[s['slot_id']]) for s in selected if s['side']} if kind=='条件' else {}
            audit.check('74同current条件全文',block['conditions'],expected_conditions)
            audit.check('74原板入力品質',block['input_quality'],quality)
            expected,observed={},{}
            for slot in selected:
                if slot['side']:
                    label,record=label_for(slot,old_slots[slot['slot_id']],kind,banks,audit)
                    labels[policy].append(label);expected[slot['slot_id']]=label;observed[slot['slot_id']]=record['observed']
            account=R69.check_operation(block,expected,observed,tape,source,audit) if kind=='条件' else check_immediate(block,tape,source,audit)
            accounts[policy].append(account)
            operation=block['operation']
            audit.check('運用候補と場',(operation['candidate_id'],operation['session']),(policy,session))
            for order in operation['orders']:
                if order['kind']=='entry' and order['status']=='filled':
                    prior=banks[kind][order['slot']['slot_id'],order['slot']['side']]['barrier']
                    audit.check('新実と独立入口可否',prior['filled'],True)
                    audit.check('新実と独立新規三属性',tuple(order['fill_'+k] for k in ('time','line','price')),tuple(prior['entry_'+k] for k in ('time','line','price')))
                    entry_matches+=1
            for closed in operation['closed']:
                single=banks[kind][closed['slot_id'],closed['side']]['closed']
                audit.check('新実と独立完結件数',len(single) if single is not None else None,1)
                if single:
                    audit.check('新実と独立完結非ID全文',R55.strict_close_equal(closed,single[0]),True)
                closed_matches+=1
            resource=resource_map[session,policy]
            path=ROOT/resource['pnl_path']
            audit.check('新Viewer正規パス',path.resolve(),(STUDY/'viewer'/f'{policy}_{session}.trades.jsonl').resolve())
            audit.check('新Viewer全約定',list(source.json_rows(path)),operation['trades'])
            audit.check('新Viewer元市場',resource['market_path'],entry['source_path'])
            audit.check('新Viewer商品/単位',(resource['symbol'],resource['product'],resource['point_value'],resource['pnl_format'],resource['pnl_basis']),('NK225','NK225micro',10,'trades','net'))
            viewer_pins[path.relative_to(ROOT).as_posix()]=source.sha(path)
            summaries.append({'場':session,'候補':policy,'期間':source.span(session),'入力品質':quality,'運用品質':operation['quality'],'運用集計':operation['metrics']})
        print(session+' SOURCE15/先着再用/即時・条件運用照合',flush=True)
    audit.check('74新138場別',result['場別'],summaries)
    audit.check('主二検査',result['検査'],{'実独立新規一致':entry_matches,'実独立完結一致':closed_matches})
    sequence=list(source.json_rows(WORK/'入口先着.jsonl.gz'))
    audit.check('新先着全文保存順',sequence,[r for p in POLICIES for r in labels[p]])
    expected=expected_summary(accounts,labels,slots,observations,source,summary)
    for key,value in expected.items():
        audit.check('74独立全集計:'+key,result[key],value)
    audit.check('保存Q0再集計全文',result['候補']['Q0'],previous['候補']['Q0'])
    audit.check('74採用',result['採用'],[p for p in POLICIES if all(expected['候補'][p][period]['同時適格'] for period in PERIODS[:2])])
    audit.check('74詳細三系列',set(result['詳細']),{'技法観測.jsonl.gz','定時判断と運用.jsonl.gz','入口先着.jsonl.gz'})
    for name,digest in result['詳細'].items():
        audit.check('74詳細SHA:'+name,source.sha(WORK/name),digest)
    api=check_api(viewer_url,resources,[r for p in ALL_POLICIES for r in accounts[p]],source,audit)
    for name,digest in {**before,**cache_pins,**viewer_pins}.items():
        audit.check('監査中参照不変:'+name,source.sha(ROOT/name),digest)
    payload={'試行':74,'確認日時':datetime.now(source.JST).isoformat(),'全件一致':audit.bad==0,'照合項目数':audit.count,
        '不一致数':audit.bad,'不一致':audit.examples,'結果SHA256':source.sha(STUDY/'結果.json'),
        '新主処理import':False,'新入力import':False,'Engine期待値import':False,'市場戦略再生':False,'本物fit再実行':False,
        '旧73特徴再構成':False,'SOURCE15価格順序の独立再構成':True,'新fit':0,'新独立測定':0,'新運用数':138,'保存参照運用数':46,
        '予定枠数':1702,'準備済み枠数':ready,'新H純候補数':adopted,'同一独立新規数':entry_matches,'同一独立完結数':closed_matches,
        '参照SHA256':before,'キャッシュSHA256':cache_pins,'新Viewer約定SHA256':viewer_pins,'ViewerAPI':api,
        '検証範囲':'旧73完了259対象と成功proof、旧Q0保存46場1702枠/SOURCE15形・直接gate・三政策14項目、旧55即時/69条件先着と独立完結の厳密再用、新138の原BBO注文・条件・保護・現金・保有/監視品質・活動、四政策集計/由来/保護/取得差、Viewer184と新三代表。',
        '限定':'旧73特徴64値は成功保存物を参照し算術再構成しない。旧55/69の先着は成功固定SHAで再用し、49初監査129差の旧末行期限算法は新先着へ適用しない。独立測定の総額は同時実行戦略の損益ではない。由来別完結小計は未解消を網羅しない。原典price-crossの再現ではなく終値確認への独自適応。心理因果・未見収益・70%保証の実証ではない。'}
    with destination.open('x',encoding='utf-8') as stream:
        stream.write(json.dumps(payload,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    return payload


# ----------------------------------------
def expected_summary(accounts: dict,labels: dict,slots: dict,observations: dict,source,summary) -> dict:
    """純・一枚・由来・保護・取得差を独立会計と入力観測へ帰属する。

    引数: accounts/labels/slots/observations(dict)は検算済み保存、source/summaryは固定監査純集計。
    返り値: dictは主5項目の全期待値。新主summarizeを呼ばず経済分母を分離する。
    """
    result={key:{} for key in ('候補','由来別','利益保護','比較','技法被覆')}
    for policy in ALL_POLICIES:
        result['候補'][policy],result['由来別'][policy],result['利益保護'][policy]={},{},{}
        slot_map={row['slot_id']:row for row in slots[policy]}
        label_map={row['slot_id']:row for row in labels[policy]}
        for period in PERIODS:
            aa=[row for row in accounts[policy] if source.span(row['session'])==period]
            cc=[{**row,'session':account['session']} for account in aa for row in account['closed']]
            ll=[row for row in labels[policy] if source.span(row['session'])==period]
            ss=[row for row in slots[policy] if source.span(row['session'])==period]
            entrance=R68.entry_summary(ll,period,source)
            operation=R68.operation_summary(aa,period,source,summary)
            result['候補'][policy][period]={'入口':entrance,'運用':operation,'同時適格':entrance['70目標'] and operation['活動適格'] and operation['費用適格']}
            origins={}
            for origin in ('保存Q0','内包偽突破'):
                subset=[row for row in cc if slot_map[row['slot_id']]['origin']==origin]
                subset_labels=[row for row in ll if slot_map[row['slot_id']]['origin']==origin]
                caution=[account['session'] for account in aa if account['caution'] and any(slot_map[row['slot_id']]['origin']==origin for row in account['closed'])]
                origins[origin]={'純候補':sum(row['side']!=0 and row['origin']==origin for row in ss),
                    '入口':R68.entry_summary(subset_labels,period,source),'実完結':len(subset),'費用別観測円':{str(f):close_sum(subset,f) for f in (0,5,10)},
                    '利益旗':sum(bool(row['arm']) for row in subset),'旗後赤':sum(row['arm'] and row['pnl5']<0 for row in subset),
                    '役割別完結':{role:sum(row['role']==role for row in subset) for role in ('順行','反転')},'品質注意場':caution,
                    '品質注意場の範囲':'同由来の完結がある場の全体品質注意。由来別の未解消を網羅しない。額は観測小計で、確定性は政策全体を参照'}
            result['由来別'][policy][period]=origins
            red=[row for row in cc if row['arm'] and Decimal(str(row['pnl5']))<0]
            signs=Counter((Decimal(row['side'])*(Decimal(str(row['exit_price']))-Decimal(str(row['entry_price'])))>0)-
                (Decimal(row['side'])*(Decimal(str(row['exit_price']))-Decimal(str(row['entry_price'])))<0) for row in red)
            before250=sum(label_map[row['slot_id']]['outcome']=='250' and (row['exit_time'],row['exit_line'])<(label_map[row['slot_id']]['end_time'],label_map[row['slot_id']]['end_line']) for row in cc)
            result['利益保護'][policy][period]={'利益旗':sum(bool(row['arm']) for row in cc),'旗後赤':len(red),'同値':signs[0],
                '有利費用負け':signs[1],'不利':signs[-1],'先着250前の実退出':before250}
    # ----------------------------------------
    # 一枚完結は元枠と実sideで結合し、同方向でも取得の差があり得ることを保持する。
    for left,right in (('Q0','I0'),('Q0','H0'),('I0','H1'),('H0','H1')):
        by_period={}
        for period in PERIODS:
            old={row['slot_id']:row for row in slots[left] if source.span(row['session'])==period}
            new={row['slot_id']:row for row in slots[right] if source.span(row['session'])==period}
            if set(old)!=set(new):
                raise ValueError('比較の全予定集合不一致')
            pure=Counter()
            for identity in old:
                a,b=old[identity]['side'],new[identity]['side']
                category='双方待機' if a==b==0 else '左のみ' if a and not b else '右のみ' if b and not a else '同方向' if a==b else '反対切替'
                pure[category]+=1
            ca={(r['slot_id'],r['side']):r for a in accounts[left] if source.span(a['session'])==period for r in a['closed']}
            cb={(r['slot_id'],r['side']):r for a in accounts[right] if source.span(a['session'])==period for r in a['closed']}
            common,drop,add=sorted(set(ca)&set(cb)),sorted(set(ca)-set(cb)),sorted(set(cb)-set(ca))
            exact=[key for key in common if all(ca[key][field]==cb[key][field] for field in ('entry_time','entry_line','entry_price'))]
            by_period[period]={'純':{key:pure[key] for key in ('同方向','左のみ','右のみ','反対切替','双方待機')},
                '実':{'左完結':len(ca),'右完結':len(cb),'共通元枠同方向':len(common),'左のみ':len(drop),'右のみ':len(add),
                '共通元枠差額5':float(sum((Decimal(str(cb[k]['pnl5']))-Decimal(str(ca[k]['pnl5'])) for k in common),Decimal(0))),
                '左のみ額5':close_sum([ca[k] for k in drop],5),'右のみ額5':close_sum([cb[k] for k in add],5),'厳密同新規':len(exact),
                '厳密同新規出口差5':float(sum((Decimal(str(cb[k]['pnl5']))-Decimal(str(ca[k]['pnl5'])) for k in exact),Decimal(0)))},
                '取得差':{'件数':len(common),'実方向価格差pt':distribution([ca[k]['side']*(cb[k]['entry_price']-ca[k]['entry_price']) for k in common]),
                '時間差秒':distribution([cb[k]['entry_time']-ca[k]['entry_time'] for k in common])}}
        result['比較'][left+'対'+right]=by_period
    for period in PERIODS:
        ss=[row for row in slots['H0'] if source.span(row['session'])==period]
        reference={row['slot_id']:row for row in slots['Q0']}
        local=[observations[row['slot_id']] for row in ss]
        patterns=[row for obs in local for row in obs['candidates']]
        adopted=[row for row in ss if row['origin']=='内包偽突破']
        result['技法被覆'][period]={'定時枠':len(ss),'準備済み':sum(row['ready'] for row in local),'形観測':len(patterns),
            '形unique':len({row['id'] for row in patterns}),'状態別':dict(Counter(row['status'] for row in patterns)),
            '適格方向':sum(row['side']!=0 for row in local),'順行適格':sum(row['side']!=0 and row['role']=='順行' for row in local),
            '反転適格':sum(row['side']!=0 and row['role']=='反転' for row in local),
            '新H追加':sum(reference[row['slot_id']]['side']==0 for row in adopted),
            '新H同方向':sum(reference[row['slot_id']]['side']==row['side'] for row in adopted),
            '新H反対切替':sum(reference[row['slot_id']]['side']==-row['side'] for row in adopted)}
    return result


# ----------------------------------------
def artificial_tape(events: list[dict],source) -> dict:
    """架空の有限原行だけから、独立監査用配列を作る。

    引数: events(list[dict])は人工6列、sourceは固定NumPy補助。
    返り値: dictは全原行/正常BBO/原行索引。市場ファイルは開かない。
    """
    raw={key:source.np.array([row[key] for row in events]) for key in ('now','line','last','bid','ask','valid')}
    mask=raw['valid'] & source.np.isfinite(raw['bid']) & source.np.isfinite(raw['ask']) & (raw['bid']>0) & (raw['bid']<raw['ask'])
    normal={key:value[mask] for key,value in raw.items()}
    return {'events':raw,'normal':normal,'normal_lines':{int(line):i for i,line in enumerate(normal['line'])}}


def self_test() -> dict:
    """人工の即時鏡像・条件四例・独立全集計を実APIへ接続する。

    引数: なし。
    返り値: dictは人工成功/照合数/差。新I/主/Engineは人工の実装側に限り使用できる。
    """
    source,oracle,summary=A.helpers();audit=source.Audit()
    operation49=load_fixed(ROOT/'scripts/定時帯反応/運用.py','74人工の実装側固定49')
    operation68=load_fixed(ROOT/'scripts/条件発動前の否定/運用.py','74人工の実装側固定68')
    main=load_fixed(HERE/'検証.py','74人工の集計実装側')
    session='2026-10-05_Day';_,force,_,times=source.calendar(session);first=times[0]
    all_operations={p:[] for p in ALL_POLICIES};all_accounts={p:[] for p in ALL_POLICIES}
    all_slots={p:[] for p in ALL_POLICIES};all_labels={p:[] for p in ALL_POLICIES};observations={}
    for side in (1,-1):
        current_session=session if side==1 else '2026-10-06_Day'
        _,current_force,_,schedule=source.calendar(current_session);start=schedule[0]
        values=[(0,1000,999,1001),(1,1011,1010,1012),(2,1012,1011,1013),(3,1030,1029,1031),(4,1012,1011,1013),(5,1013,1012,1014)]
        events=[{'now':start+t,'line':i+1,'last':last if side==1 else 2000-last,
            'bid':bid if side==1 else 2000-ask,'ask':ask if side==1 else 2000-bid,'valid':True} for i,(t,last,bid,ask) in enumerate(values)]
        events.append({'now':current_force+1,'line':7,'last':1000.,'bid':999.,'ask':1001.,'valid':True})
        tape=artificial_tape(events,source)
        base=[{'scheduled':time,'time':time,'line':1 if i==0 else None,'side':side if i==0 else 0,
            'role':'順行' if i==0 else '待機','atr':10. if i==0 else None,'D':10. if i==0 else None,
            'reason':'人工候補' if i==0 else '判断時計欠測','ready':i==0,'slot_id':current_session+'|'+str(i)} for i,time in enumerate(schedule)]
        for policy in ALL_POLICIES:
            selected=[{**row,'session':current_session,'policy':policy,'origin':'内包偽突破' if i==0 and policy.startswith('H') else '保存Q0',
                'pattern_id':'人工形'+str(side) if i==0 and policy.startswith('H') else None} for i,row in enumerate(base)]
            pure=[{k:s[k] for k in PURE} for s in selected]
            identity=base[0]['slot_id'];conditions={identity:{'high':1010.,'low':990.,'source':{'人工':True},'expires':start+900}}
            operation=operation68.replay(events,pure,conditions,current_session,policy) if policy in ('Q0','H0') else operation49.replay(events,pure,current_session,policy)
            block={'session':current_session,'policy':policy,'slots':selected,'conditions':conditions if policy in ('Q0','H0') else {},'operation':operation}
            if policy in ('I0','H1'):
                account=check_immediate(block,tape,source,audit)
                audit.check('即時鏡像の同値旗後赤字',[(r['arm'],r['entry_price']==r['exit_price'],r['pnl5']) for r in operation['closed']],[(True,True,-122.)])
            else:
                expected,last=R68.expected_label(tape,{**pure[0],'session':current_session,'policy':policy},conditions[identity],current_force,source.calendar(current_session)[2],source,oracle)
                account=R69.check_operation(block,{identity:expected},{identity:last},tape,source,audit)
            all_operations[policy].append(operation);all_accounts[policy].append(account);all_slots[policy].extend(selected)
            for closed in operation['closed']:
                all_labels[policy].append({'session':current_session,'slot_id':closed['slot_id'],'side':side,'role':'順行','filled':True,'outcome':'250',
                    'time':start,'line':1,'entry_time':closed['entry_time'],'entry_line':closed['entry_line'],'entry_price':closed['entry_price'],
                    'end_time':current_force,'end_line':7,'origin':selected[0]['origin']})
            for i,row in enumerate(selected):
                observations[row['slot_id']]={'ready':row['ready'],'side':side if i==0 else 0,'role':'順行' if i==0 else '待機',
                    'candidates':[{'id':'人工形'+str(side),'status':'有効'}] if i==0 else []}
        audit.check('元人工入力非改変',base[0]['side'],side)
    before=deepcopy((all_operations,all_accounts,all_slots,all_labels,observations))
    calculated=expected_summary(all_accounts,all_labels,all_slots,observations,source,summary)
    audit.check('由来/保護/比較/被覆/主集計の全辞書',main.summarize(all_operations,all_labels,all_slots,observations),calculated)
    audit.check('人工集計入力非改変',(all_operations,all_accounts,all_slots,all_labels,observations),before)
    audit.check('由来別fallback分離',calculated['由来別']['H0']['学習']['内包偽突破']['実完結'],2)
    audit.check('取得差の鏡像符号',calculated['比較']['H0対H1']['学習']['取得差']['実方向価格差pt'],{'平均':-1.,'中央値':-1.,'最小':-1.,'最大':-1.})
    audit.check('空期の率は未知',calculated['候補']['I0']['条件選択']['入口']['率'],None)
    audit.check('先着250前実退出を独立計数',calculated['利益保護']['I0']['学習']['先着250前の実退出'],2)
    # ----------------------------------------
    # 保存先着結合の元時計/D/current不一致は、経済値が同じでも検出する。
    slot=all_slots['I0'][0];old={**slot,'feature':{'base':{'base':{'sources':{'current':{'high':1010.,'low':990.,'end':slot['scheduled'],'confirm':slot['time'],'confirm_line':slot['line']}}}}}}
    barrier={**{k:slot[k] for k in (*BINDING,'side')},'filled':False,'outcome':'未約定'}
    binding={k:slot[k] for k in (*BINDING,'side','ready','atr','D')}
    record={'barrier':barrier,'closed':[],'binding':binding,'observed':slot['time']}
    bank={'即時':{(slot['slot_id'],slot['side']):record}}
    label,_=label_for(slot,old,'即時',bank,audit)
    audit.check('結合で元理由を上書きしない',set(label)-set(barrier),{'policy','role','origin','pattern_id'})
    bad=deepcopy(bank);bad['即時'][slot['slot_id'],slot['side']]['binding']['D']+=5
    probe=source.Audit();label_for(slot,old,'即時',bad,probe)
    audit.check('D結合不一致検出',probe.bad>0,True)
    original=deepcopy(old);old['feature']['base']['base']['sources']['current']['confirm']+=1
    rejected=False
    try:
        expected_condition(old)
    except ValueError:
        rejected=True
    audit.check('不可視current拒否',rejected,True)
    audit.check('正常current固定4項目',expected_condition(original),{'high':1010.,'low':990.,'source':original['feature']['base']['base']['sources']['current'],'expires':slot['scheduled']+900})
    # ----------------------------------------
    # 設定否定/監視否定/監視不足/約定保護は固定原配列oracleへ接続する。
    artificial=load_fixed(ROOT/'scripts/条件入口の教師/保存検証の人工検査.py','74人工の固定69接続')
    measure=load_fixed(ROOT/'scripts/条件入口の教師/計測.py','74人工の実装側固定69計測')
    material=load_fixed(ROOT/'scripts/条件発動前の否定/先着の人工検査.py','74人工の固定68材料')
    artificial.check_operations(R69,measure,material,audit,source,oracle)
    return {'人工成功':audit.bad==0,'テスト件数':11,'照合項目数':audit.count,'不一致数':audit.bad,'不一致':audit.examples,
        '本物入力読取':False,'本物fit':0,'新fit':0,'市場戦略再生':False,'Engineは人工実装側のみ':True,
        '入力監査の別証拠':'34系列5836比較差0。今回ここで重複再実行しない'}


def main() -> None:
    """人工又はroot専用の正式保存監査を排他的に公開する。

    引数: CLIのself-test/run(bool)、viewer-url(str|None)は実行段階とViewer。
    返り値: None。既存proofは上書きしない。
    """
    parser=argparse.ArgumentParser()
    group=parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--run',action='store_true');group.add_argument('--self-test',action='store_true')
    parser.add_argument('--viewer-url')
    args=parser.parse_args()
    value=run(args.viewer_url) if args.run else self_test()
    print(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False))
    raise SystemExit(0 if value.get('全件一致',value.get('人工成功',False)) else 1)


if __name__=='__main__':
    main()
