"""Rootが指定した2Nativeだけを認証し、同実入口の実現差と当時公表値を記述する。"""
from pathlib import Path
from decimal import Decimal
from datetime import datetime,timezone,timedelta
from statistics import median
from copy import deepcopy
import gzip
import hashlib
import json

ROOT=Path(__file__).resolve().parents[2]
HERE=Path(__file__).resolve().parent
SESSIONS=('2026-09-30_Night','2026-10-26_Night')
KEYS=('TR_C0_D0','TR_XC_C0_D0','TR_XQ_C0_D0')
REFS={
 '金融完了':{'path':str(ROOT/'work/116金融F1/元54場/完了.json'),'sha256':'f41b76f8cc187e7dbd59ba7324ad2b23168de96b1d81378a37861b932be57147'},
 '独立結果':{'path':str(ROOT/'work/116独立保存F1/元54場/結果.json'),'sha256':'f5e3c4777dee3ef08030ef5f60f79edd5426699ffdfe02214fc3fc01735de501'},
 '保存確認':{'path':str(ROOT/'work/116独立保存F1/元54場/保存会計の確認.json'),'sha256':'0af2eb07920e47308c497023a320c5563411fd978b843a09feb98cdbda15958c'}}


def load(ref: dict,native: bool=False) -> dict:
    """
    機能: 明示された小metadata又は2場限定NativeをSHA認証して読む。
    引数: ref(dict)、native(bool)。返り値: dict。原板/CSV/他Nativeを受け付けない。
    """
    p=Path(ref['path'])
    if native and p.name not in [s+'.Native.json.gz' for s in SESSIONS]:raise ValueError('Root未許可Native')
    if not native and ref not in REFS.values():raise ValueError('Root未指定metadata')
    data=p.read_bytes()
    if hashlib.sha256(data).hexdigest()!=ref['sha256']:raise ValueError('Root参照SHA差')
    return json.loads(gzip.decompress(data) if native else data,parse_float=Decimal)


def inputs() -> tuple:
    """
    機能: 同F1元54金融成功と独立保存を結び、許可2場のNative参照だけを返す。
    引数: なし。返り値: tuple[dict,dict,dict,dict]は金融/結果/確認/2場Ref。
    """
    complete,result,check=(load(REFS[k]) for k in ('金融完了','独立結果','保存確認'))
    if not(complete['success'] and complete['trial']==116 and complete['stage']=='base54' and complete['sessions']==54 and complete['unchanged']):raise ValueError('同元54金融成功が必要')
    for v in (result,check):
        if not(v['成功'] and v['試行']==116 and v['stage']=='base54' and v['場数']==54 and v['会計数']==1944 and v['前後不変']):raise ValueError('同独立成功が必要')
        if v['金融完了SHA256']!=REFS['金融完了']['sha256'] or v['金融条件SHA256']!=complete['condition_sha256']:raise ValueError('独立と金融の同体差')
    rows={r['session']:r['native'] for r in complete['results'] if r['session'] in SESSIONS}
    if set(rows)!=set(SESSIONS):raise ValueError('Rootの許可2場だけ')
    for sid,ref in rows.items():
        prior=next(r for r in result['Native参照'] if r['session']==sid)
        if prior['sha256']!=ref['sha256'] or Path(prior['path']).resolve()!=Path(ref['path']).resolve():raise ValueError('独立保存とNative参照差')
    return complete,result,check,rows


def serial(value):
    """
    機能: 十進金融値を小JSONへ数値として保存する。
    引数: value(JSON補助値)。返り値: int|float。未対応型はTypeError。
    """
    if isinstance(value,Decimal):return int(value) if value==value.to_integral_value() else float(value)
    raise TypeError(type(value).__name__)


def jst(value) -> str:
    """
    機能: 保存価格時計をJSTへ表示する。
    引数: value(数値)。返り値: strは日時。受信時計と呼ばない。
    """
    return datetime.fromtimestamp(float(value),timezone(timedelta(hours=9))).isoformat()


def known(item: dict|None):
    """
    機能: 公開Known値だけを取り出し、未知0と区別する。
    引数: item(dict|None)。返り値: 数値|None。
    """
    return item['value'] if isinstance(item,dict) and item.get('known') is True else None


def entry_identity(p: dict) -> dict:
    """
    機能: Source複合出生と実entry quote/price/qtyを同入口の条件として固定する。
    引数: p(dict)。返り値: dict。同SourceIDだけを同入口としない。
    """
    return {'product':'NK225mini','source':p['source'],'side':p['side'],'entry_price':p['entry_price'],'initial_quantity':p['initial_quantity'],'entry_quote':p['entry_quote']}


def pivot(value: dict,entry_at) -> dict|None:
    """
    機能: 公表済みpivotの形成区間・確認時刻と、取得に対する前後関係だけを残す。
    引数: value(dict)、entry_at(数値)。返り値: dict|None。高安のRaw到達時刻を捏造しない。
    """
    if not value.get('known'):return None
    return {k:value[k] for k in ('kind','price','center_start','center_end','confirm_end','published_at')}|{'center_start_JST':jst(value['center_start']),'center_end_JST':jst(value['center_end']),'published_JST':jst(value['published_at']),'形成足が完全に取得後':value['center_start']>=entry_at,'形成足が取得を跨ぐ':value['center_start']<entry_at<value['center_end'],'確認公表は取得後':value['published_at']>entry_at}


def frame_summary(pub: dict,side: int,boundary,entry_at,previous: list) -> dict:
    """
    機能: 一つの確定公表を方向/勢い/値幅/量/構造の役割へ射影する。
    引数: pub(dict)、side(int)、boundary/entry_at(数値)、previous(list)。返り値: dictは当時の保存値と単純派生値。
    """
    f=pub['frame']['frame'];t=f['technical'];d=pub['frame']['dmi'];structure=pub['frame']['structure'];v={k:known(t.get(k)) for k in ('ema8','ema21','ema8_delta','ema21_delta','gap','atr','previous_atr','tr','rsi','previous_rsi','histogram','previous_histogram')};dmi={k:known(d.get(k)) for k in ('plus_di','minus_di','adx','previous_plus_di','previous_minus_di','previous_adx')}
    signed={k:None if v[k] is None else side*v[k] for k in ('ema8_delta','ema21_delta','gap','histogram')};signed['hist_delta']=None if v['histogram'] is None or v['previous_histogram'] is None else side*(v['histogram']-v['previous_histogram']);signed['di']=None if dmi['plus_di'] is None or dmi['minus_di'] is None else side*(dmi['plus_di']-dmi['minus_di'])
    for key in ('ema8','ema21'):signed['close_'+key]=None if v[key] is None else side*(f['ohlc']['close']-v[key])
    oldvol=[p['frame']['frame']['volume'] for p in previous[-3:] if p['frame']['frame']['volume_known']];relative=None if len(oldvol)!=3 or median(oldvol)<=0 or not f['volume_known'] else f['volume']/median(oldvol)
    opposite=None
    if structure['known']:opposite=side*(f['ohlc']['close']-(structure['low'] if side==1 else structure['high']))
    return {'frame_id':f['id'],'width_seconds':f['width_seconds'],'stamp':pub['stamp'],'published_JST':jst(pub['stamp']['time']),'bar_start':f['start'],'bar_end':f['end'],'bar_start_JST':jst(f['start']),'bar_end_JST':jst(f['end']),'available_at':f['available_at'],'配送遅れ秒_足Endから':pub['stamp']['time']-f['end'],'price_known':f['price_known'],'ohlc':f['ohlc'],'technical':v,'dmi':dmi,'side_signed':signed,'出生固定境界との差':side*(f['ohlc']['close']-boundary),'直前3本反対端との差':opposite,'volume_known':f['volume_known'],'volume':f['volume'] if f['volume_known'] else None,'volume_直前3本中央値比':relative,'当足を含めない構造':{k:structure[k] for k in ('known','high','low','refs')},'pivots':{k:pivot(f[k],entry_at) for k in ('prior_high','prior_low','new_high','new_low')},'足全体が取得後':f['start']>=entry_at,'Endは取得後':f['end']>entry_at}


def published_context(n: dict,q: dict,p: dict) -> dict:
    """
    機能: 同Rawの全公表後にある尺度別latestだけを当時情報として接合する。
    引数: n/q/p(dict)。返り値: dictは5/15/30最新。時刻同値の未来Indexも拒否する。
    """
    result={};histories={300:[],900:[],1800:[]};boundary=p['lifecycle116']['initial']['entry']['birth']['values']['boundary']
    for pub in n['actual']['entry_publications'] or []:
        if pub['stamp']['index']>q['index']:continue
        if pub['stamp']['time']>q['time']:raise ValueError('Index以前でも時計が未来の公表')
        f=pub['frame']['frame']
        if f['end']>pub['stamp']['time'] or f['available_at']>pub['stamp']['time'] or f['record_ordinal']!=pub['stamp']['index']+1:raise ValueError('公表終端/Available/実原行が不正')
        width=f['width_seconds'];result[str(width)]=frame_summary(pub,p['side'],boundary,p['entry_quote']['time'],histories[width]);histories[width].append(pub)
    return result


def position_summary(book: dict,p: dict) -> dict:
    """
    機能: 実entryと全実close allocationの収支・注文役割を保存する。
    引数: book/p(dict)。返り値: dict。新退出後の仮定損益を計算しない。
    """
    orders={o['id']:o for o in book['orders']};exits=[]
    for fill in book['fills']:
        if fill['position_id']!=p['id'] or fill['action']!='close':continue
        o=orders[fill['order_id']];role='life' if o.get('lifecycle_point') is not None else 'P100' if o['protection_point'] is not None else 'Source'
        exits.append({'order_id':o['id'],'request_quote':o['request_quote'],'request_JST':jst(o['request_time']),'fill_id':fill['id'],'fill_quote':fill['quote'],'fill_JST':jst(fill['quote']['time']),'price':fill['price'],'quantity':fill['quantity'],'gross_yen':fill['gross_yen'],'net_yen':sum(a['net_yen'] for a in fill['allocations']),'role':role,'reason':o['reason']})
    if sum(x['net_yen'] for x in exits)!=p['realized_net']:raise ValueError('実返済片と保存純額差')
    return {'key':book['key'],'position_id':p['id'],'entry_identity':entry_identity(p),'entry_JST':jst(p['entry_quote']['time']),'net_yen':p['realized_net'],'P100_active':p['protection_active'],'activation':p['activation'],'exits':exits}


def guard_context(native: dict,p: dict,life_point: dict) -> dict:
    """
    機能: 当life要求直前に実Actorが保持した3分Publicationを全公表列へ照合する。
    引数: native/p/life_point(dict)。返り値: dictは同秒の公開順を当時Snapshotで裏付けたBB等。
    """
    saved=life_point['after_P100_reservation']['before_snapshot']['latest'];name='buy' if p['side']==1 else 'sell';matches=[x for x in native['actual']['publications'] if x[name]['id']==saved['id'] and x[name]==saved]
    if len(matches)!=1:raise ValueError('当時P100保持Publicationの出典一意性')
    pub=matches[0]
    if pub['at']>life_point['quote']['time'] or saved['end']>life_point['quote']['time']:raise ValueError('3分公表の未来参照')
    ordinal=next(i for i,x in enumerate(native['actual']['publications']) if x is pub)
    earlier=[x[name]['bb'] for x in native['actual']['publications'][:ordinal+1] if x[name]['bb'] and x[name]['bb']['known']]
    return {'裏付け':'実life要求のafter_P100_reservation.before_snapshot.latest全値と同じ公表。場末snapshotを使わない。','publication':{k:saved[k] for k in ('id','start','end','available_at','c','m','v','close','prior_pivot','bb')},'published_at':pub['at'],'published_JST':jst(pub['at']),'frame_last_source':pub['frame']['last_source'],'frame_ohlc':pub['frame']['ohlc'],'frame_known':pub['frame']['known'],'frame_ema8':pub['frame']['ema8'],'frame_ema21':pub['frame']['ema21'],'frame_hist':pub['frame']['hist'],'P':pub['result'][name]['P'],'BB直前からの最後3幅':[b['width'] for b in earlier[-3:]],'vの意味':'当場3分H−Lの5本中央値。出来高ではない。'}


def inspect_session(sid: str,native: dict,result: dict) -> dict:
    """
    機能: 主3口座の全Source出生を実入口で対応し、2指定例だけ当時技法を小要約する。
    引数: sid(str)、native/result(dict)。返り値: dict。条件探索/新手法の効果推定を行わない。
    """
    books=native['actual']['books'];old=books[KEYS[0]];groups=[];focus=[]
    for key in KEYS:
        row=next(r for r in result['場別'] if r['session']==sid and r['key']==key)
        if row['net_yen']!=books[key]['totals']['net_yen']:raise ValueError('独立保存とNativeの場別純額差')
    for base in old['positions']:
        birth=(base['source']['method'],base['source']['signal_id'],base['side']);matched={KEYS[0]:base};comparison={}
        for key in KEYS[1:]:
            same=[p for p in books[key]['positions'] if (p['source']['method'],p['source']['signal_id'],p['side'])==birth]
            if len(same)!=1:raise ValueError('指定2場ではSource出生が一意対応しない')
            matched[key]=same[0];comparison[key]={'Source複合出生一致':same[0]['source']==base['source'],'実入口全値一致':entry_identity(same[0])==entry_identity(base),'純額差':same[0]['realized_net']-base['realized_net']}
        groups.append({'source_method':birth[0],'signal_id':birth[1],'side':birth[2],'対応':comparison,'実取引':{k:position_summary(books[k],p) for k,p in matched.items()}})
        if not any(p.get('lifecycle116') and p['lifecycle116']['first_invalidation'] for p in matched.values()):continue
        if not all(v['実入口全値一致'] for v in comparison.values()):raise ValueError('主因果例は同入口でない')
        for key in KEYS[1:]:
            p=matched[key];life=p['lifecycle116'];birth=life['initial']['entry']['birth'];point=life['first_invalidation'];q=point['quote'];requests=life.get('requests') or [];req=next(r for r in requests if r['exit_order_id']);boundary=birth['values']['boundary']
            bars=[];prior=[];newpivots=[]
            for pub in native['actual']['entry_publications']:
                f=pub['frame']['frame']
                if f['width_seconds']!=300 or pub['stamp']['index']>q['index']:continue
                summary=frame_summary(pub,p['side'],boundary,p['entry_quote']['time'],prior)
                if pub['stamp']['index']>p['entry_quote']['index']:
                    bars.append(summary)
                    for name in ('new_high','new_low'):
                        if summary['pivots'][name] is not None:newpivots.append({'役割':name,'公表stamp':pub['stamp'],**summary['pivots'][name]})
                prior.append(pub)
            maximum=p['marks']['whole_max'];observedmax=maximum if maximum is not None and maximum['quote']['index']<=q['index'] else None
            focus.append({'key':key,'position_id':p['id'],'entry_identity':entry_identity(p),'入口分類':'T' if birth['trend']==2 else 'R' if birth['reversal']==2 else 'それ以外','出生票':{k:birth[k] for k in ('common','trend','reversal','combined','values')},'出生Snapshotの当足OHLC':birth['current']['snapshot']['scales'][0]['current']['frame']['ohlc'],'出生の固定3本構造':birth['current']['snapshot']['scales'][0]['current']['structure'],'出生側wide_pivots':{k:pivot(birth['current']['snapshot']['scales'][0]['current']['frame'][k],p['entry_quote']['time']) for k in ('prior_high','prior_low','new_high','new_low')},'取得時Source_ATR':p['atr'],'実取得時latest':published_context(native,p['entry_quote'],p),'arming_points':[{'quote':x['quote'],'JST':jst(x['quote']['time']),'decision':x['decision']} for x in life.get('arming_points') or []],'初失効':{'quote':q,'JST':jst(q['time']),'decision':point['decision'],'remaining':point['remaining'],'reserved':point['reserved'],'realized_net':point['realized_net']},'初要求':{'quote':req['quote'],'JST':jst(req['quote']['time']),'order_id':req['exit_order_id']},'失効時latest':published_context(native,q,p),'取得後に公表された5分足':bars,'取得後に新確認した5分pivot':newpivots,'当時の3分保護公表':guard_context(native,p,req),'失効までの保存W最大':observedmax,'H100全玉円閾値':p['initial_quantity']*10000,'量の限界':['5/15/30の保存volumeだけ。mini自身の約定量・売買主導/板厚/約定側・VWAP/OBVは当時値を持たない。','P100のvは値幅中央値であって出来高ではない。'],'未使用':['場末snapshotの遡及','新退出後の仮想利益','未来の極値から閾値選択','Raw/CSV再読/金融再走']})
    return {'session':sid,'場別純額':{k:books[k]['totals']['net_yen'] for k in KEYS},'Source出生対応':groups,'当時の技法':focus}


def small_result(out: dict,detail: dict) -> dict:
    """
    機能: 圧縮当時値を参照しつつ、同入口/実収支/主な技法の小要約だけを作る。
    引数: out/detail(dict)。返り値: dict。新しい閾値・効果推定を追加しない。
    """
    scenes=[]
    for scene in out['場別']:
        contexts=[]
        for item in scene['当時の技法']:
            latest=item['失効時latest'];guard=item['当時の3分保護公表'];pub=guard['publication'];five=latest['300'];point=item['初失効']
            contexts.append({'key':item['key'],'入口分類':item['入口分類'],'固定境界':item['出生票']['values']['boundary'],'出生値':item['出生票']['values'],'取得JST':jst(item['entry_identity']['entry_quote']['time']),'初armJST':item['arming_points'][0]['JST'] if item['arming_points'] else None,'初失効JST':point['JST'],'初失効Quote':point['quote'],'life条件票':point['decision']['values'],'正常BBO':point['decision']['quote_ok'],'実残':point['remaining'],'既予約':point['reserved'],'失効時5分':{k:five[k] for k in ('bar_end_JST','published_JST','配送遅れ秒_足Endから','ohlc','technical','side_signed','出生固定境界との差','直前3本反対端との差','volume','volume_直前3本中央値比')},'失効時15分':{k:latest['900'][k] for k in ('bar_end_JST','published_JST','technical','dmi','side_signed')},'失効時30分':{k:latest['1800'][k] for k in ('bar_end_JST','published_JST','technical','dmi','side_signed')},'取得後の新確認pivot':item['取得後に新確認した5分pivot'],'3分診断':{'c':pub['c'],'m':pub['m'],'P':guard['P'],'prior_pivot':pub['prior_pivot'],'v_値幅中央値':pub['v'],'BB':pub['bb'],'BB最後3幅':guard['BB直前からの最後3幅']},'Source取得時ATR':item['取得時Source_ATR']['value'] if item['取得時Source_ATR'] is not None else None,'H100全玉円閾値':item['H100全玉円閾値'],'失効までの保存W最大':item['失効までの保存W最大']})
        scenes.append({'session':scene['session'],'場別純額':scene['場別純額'],'同Sourceと実入口の対応':scene['Source出生対応'],'当時の要点':contexts})
    return {k:out[k] for k in ('試行','成功','記述診断','市場再生','対象Native','上流','前後不変','Native読取許可は2場だけ','Raw/CSV/11月09/他Native読取','金融条件/閾値変更','研究上の新退出効果推定','全Raw最初性の独立証明ではない')}|{'詳細Ref':detail,'場別':scenes}


def main() -> None:
    """
    機能: 許可2場だけを再現可能な小JSONへ記述し、入力SHA不変を確認する。
    引数: なし。返り値: None。正式成果物・全停止フォルダを変更しない。
    """
    _,result,_,refs=inputs();sessions=[]
    for sid,ref in refs.items():
        sessions.append(inspect_session(sid,load(ref,True),result))
    before={r['path']:r['sha256'] for r in [*REFS.values(),*refs.values()]};after={p:hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in before}
    if before!=after:raise ValueError('許可2場/上流metadataの前後差')
    out={'試行':116,'成功':True,'記述診断':True,'市場再生':False,'対象Native':refs,'上流':REFS,'場別':sessions,'入力SHA256前':before,'入力SHA256後':after,'前後不変':True,'Native読取許可は2場だけ':True,'Raw/CSV/11月09/他Native読取':False,'金融条件/閾値変更':False,'研究上の新退出効果推定':False,'全Raw最初性の独立証明ではない':True}
    ledger=HERE/'当時値の詳細.json.gz';packed=gzip.compress((json.dumps(out,ensure_ascii=False,separators=(',',':'),default=serial)+'\n').encode('utf-8'),mtime=0)
    with ledger.open('xb') as f:f.write(packed)
    detail={'path':str(ledger),'sha256':hashlib.sha256(packed).hexdigest(),'bytes':len(packed)};path=HERE/'同入口の要点.json'
    with path.open('x',encoding='utf-8',newline='\n') as f:f.write(json.dumps(small_result(out,detail),ensure_ascii=False,indent=2,default=serial)+'\n')
    print(json.dumps({'成功':True,'要点':{'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'bytes':path.stat().st_size},'詳細':detail},ensure_ascii=False))


if __name__=='__main__':main()
