"""75の観測帯と公開価格の反応を、新実装へ依存せず別算する。"""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from fractions import Fraction
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import re
import sys


HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
SOURCE=('session','index','minutes','start','end','confirm','confirm_line','publish','missing','open','high','low','close')
JST=timezone(timedelta(hours=9))


# ----------------------------------------
def finite(value: object) -> bool:
    """真偽値と非有限値を除く数値を判別する。

    引数: value(object)は保存値。
    返り値: boolは有限int/floatならTrue。
    """
    return isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value)


def number(value: object,required: bool = False) -> float:
    """数値型と必要な有限性を検証してfloatへ正規化する。

    引数: value(object)は値、required(bool)は有限値を必須とする旗。
    返り値: floatは正規化値。不正はValueError。
    """
    if isinstance(value,bool) or not isinstance(value,(int,float)):
        raise ValueError('数値型が必要')
    try:
        result=float(value)
    except (OverflowError,ValueError) as error:
        raise ValueError('有限範囲へ変換不能') from error
    if required and not math.isfinite(result):
        raise ValueError('有限数値が必要')
    return result


def key(now: float,line: int | None) -> dict:
    """原行とタイマーを区別した出典を作る。

    引数: now(float)は時計、line(int|None)は原行又はタイマー。
    返り値: dictはtime/line。
    """
    return {'time':now,'line':line}


def aggregate(events: list[dict],begin: float,end: float,publication: str = 'timer') -> dict:
    """終了markerまでの有限非後退prefixから観測帯を独立構成する。

    引数: events(list[dict])は架空又は固定6列、begin/end(float)は半開区間、publication(str)はtimer/row。
    返り値: dictは参照帯と同schema。未公開なら価格と品質も非開示。
    """
    if not isinstance(events,list):
        raise ValueError('イベントはlistが必要')
    begin,end=number(begin,True),number(end,True)
    if end<=begin or publication not in ('timer','row'):
        raise ValueError('帯区間又は公開種別が不正')
    visible=[];marker=None;maximum=-math.inf;line_seen=0
    for event in events:
        if not isinstance(event,dict) or 'now' not in event:
            raise ValueError('原行時計なし')
        now=number(event['now'])
        if not math.isfinite(now):
            continue
        line=event.get('line')
        if type(line) is not int or line<=line_seen:
            raise ValueError('原行番号の重複又は後退')
        line_seen=line
        if now<maximum:
            continue
        maximum=max(maximum,now)
        if now>=end:
            marker=key(now,line)
            break
        if begin<=now:
            visible.append(event)
    published=publication=='timer' or marker is not None
    result={'begin':begin,'end':end,'publication':publication,'published':published,
        'publication_key':key(end,None) if publication=='timer' else marker,'ready':False,'reason':'帯未公開',
        **{name:None for name in ('open','high','low','close','mid','sources','coverage','quality')}}
    if not published:
        return result
    # ----------------------------------------
    # 位置を先に固定してから正常な観測のみを索引化し、同値極値は先頭を残す。
    quality={'interval_rows':len(visible),'invalid_bbo':0,'invalid_last':0};accepted=[]
    for row in visible:
        if not all(name in row for name in ('last','bid','ask','valid')) or type(row['valid']) is not bool:
            raise ValueError('六列型が不正')
        last,bid,ask=(number(row[name]) for name in ('last','bid','ask'))
        bbo=row['valid'] and math.isfinite(bid) and math.isfinite(ask) and 0<bid<ask
        good=math.isfinite(last) and last>0
        quality['invalid_bbo']+=not bbo;quality['invalid_last']+=not good
        if bbo and good:
            accepted.append({'price':last,'key':key(float(row['now']),row['line'])})
    n=len(accepted)
    coverage={'normal_count':n,'first_key':None,'last_key':None,'head_gap':None,'tail_gap':None,'max_gap':None,'covered':False,'flat':None}
    result.update(quality=quality,coverage=coverage)
    if not n:
        result['reason']='正常Last観測なし'
        return result
    prices=[row['price'] for row in accepted];clocks=[row['key']['time'] for row in accepted]
    head,tail=clocks[0]-begin,end-clocks[-1]
    distances=[clocks[i]-clocks[i-1] for i in range(1,n)];gap=max(distances) if distances else None
    high,low=max(prices),min(prices);covered=n>=2 and all(x<=300 for x in (head,tail,gap)) if gap is not None else False
    coverage.update(first_key=deepcopy(accepted[0]['key']),last_key=deepcopy(accepted[-1]['key']),head_gap=head,tail_gap=tail,max_gap=gap,covered=covered,flat=high==low)
    reasons=[name for failed,name in ((n<2,'正常観測2件未満'),(head>300,'開始端空白300秒超'),(tail>300,'終了端空白300秒超'),(gap is not None and gap>300,'正常観測間空白300秒超')) if failed]
    result.update(ready=covered,reason='準備済み' if covered else '・'.join(reasons),open=prices[0],high=high,low=low,close=prices[-1],mid=high/2+low/2,
        sources={name:deepcopy(accepted[index]['key']) for name,index in (('open',0),('high',prices.index(high)),('low',prices.index(low)),('close',n-1))})
    return result


# ----------------------------------------
def bounds(session: str) -> tuple:
    """場の開始日と区分を固定49の連続区間へ写す。

    引数: session(str)は開始日付きDay/Night。
    返り値: tuple[float,float]は開始/終了Unix秒。
    """
    if not isinstance(session,str) or re.fullmatch(r'\d{4}-\d{2}-\d{2}_(Day|Night)',session) is None:
        raise ValueError('場名不正')
    date=datetime.fromisoformat(session[:10]).replace(tzinfo=JST)
    offsets=(31500,56400) if session.endswith('_Day') else (61200,107700)
    return tuple((date+timedelta(seconds=n)).timestamp() for n in offsets)


def choose_previous(entries: list[dict]) -> dict:
    """ホワイトリストmetadataだけで直前収録一行を独立に結合する。

    引数: entries(list[dict])は時系列の固定台帳。
    返り値: dictは現在場別の参照可否。価格の良否で過去を探し直さない。
    """
    if not isinstance(entries,list):
        raise ValueError('台帳はlistが必要')
    metas=[]
    for row in entries:
        if not isinstance(row,dict) or row.get('symbol')!='NK225':
            raise ValueError('NK225台帳が必要')
        start,stop=bounds(row.get('session'));contracts=row.get('in_session_contract_codes')
        if not isinstance(contracts,(list,tuple)) or any(not isinstance(x,str) or not x for x in contracts):
            raise ValueError('限月一覧不正')
        meta={'session':row['session'],'symbol':'NK225','contract':list(contracts),'begin':start,'end':stop}
        for name in ('source_path','source_size','source_mtime_ns','sha256_uncompressed','cache_path','cache_size','sha256_cache'):
            if name in row:
                meta[name]=deepcopy(row[name])
        metas.append(meta)
    result={}
    for i,current in enumerate(metas):
        if current['session'] in result or i and current['begin']<=metas[i-1]['begin']:
            raise ValueError('台帳の順序又は重複不正')
        record={'ready':False,'reason':'前収録なし','current_session':current['session'],'contract':deepcopy(current['contract']),
            'current_begin':current['begin'],'current_end':current['end'],'prior_session':None,'prior_begin':None,'prior_end':None,
            'gap_seconds':None,'calendar_adjacency':'未確認','prior':None}
        if i:
            prior=metas[i-1]
            record.update(prior_session=prior['session'],prior_begin=prior['begin'],prior_end=prior['end'],gap_seconds=current['begin']-prior['end'],prior=deepcopy(prior))
            violations=[(len(prior['contract'])!=1 or len(current['contract'])!=1,'限月が一意でない'),
                (prior['contract']!=current['contract'],'限月不一致'),
                (prior['session'].rsplit('_',1)[1]==current['session'].rsplit('_',1)[1],'前収録の区分不一致'),
                (prior['end']>=current['begin'],'前帯が現在場開始より前に終了していない')]
            reason=next((message for failed,message in violations if failed),None)
            record.update(ready=reason is None,reason=reason or '直前収録参照可能')
        result[current['session']]=record
    return result


# ----------------------------------------
VALUES={'F01':0,'F02':1,'F03':2,'F07':6,'F15':14,'F47':46,'F48':47,'F51':50,'F52':51}
POLICIES=('O0','P0','P1')
PURE=('scheduled','time','line','side','role','atr','D','reason','ready','slot_id')


def canonical(value: object) -> str:
    """既知不良価格も含む可視出典を固定JSONへ写す。

    引数: value(object)はSOURCE等。
    返り値: strは辞書順に依らない表現。NaNを有効価格へ補完しない。
    """
    return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=True)


def exact(value: object) -> Fraction:
    """有限保存値の十進表記を有理数へ写す。

    引数: value(object)は価格/幅。
    返り値: Fractionは比較正本。不正値はValueError。
    """
    if not finite(value):
        raise ValueError('精密値が未知')
    return Fraction(str(value))


def clock(slot: dict) -> tuple:
    """元slotの識別と判断時計を検査する。

    引数: slot(dict)は保存Q0の元判断。
    返り値: tupleはtime/line。未準備だけline=Noneを許す。
    """
    if not isinstance(slot,dict) or any(not isinstance(slot.get(n),str) or not slot[n] for n in ('session','slot_id')):
        raise ValueError('元場又は元ID不正')
    if type(slot.get('ready')) is not bool or not finite(slot.get('scheduled')) or not finite(slot.get('time')) or slot['time']<slot['scheduled']:
        raise ValueError('判断時計不正')
    if not (type(slot.get('line')) is int and slot['line']>=0 or not slot['ready'] and slot.get('line') is None):
        raise ValueError('判断原行不正')
    return slot['time'],slot['line']


def reference(row: dict) -> dict:
    """足の最小出典を作る。

    引数: row(dict)は可視SOURCE。
    返り値: dictはindex/keyのみ。
    """
    return {'index':row['index'],'key':[row['confirm'],row['confirm_line']]}


def price_reason(row: dict) -> str | None:
    """当時既知の足品質をreset理由に分類する。

    引数: row(dict)はschema検査後の可視足。
    返り値: str|Noneは不完全/価格不正又は正常。
    """
    complete=row['publish'] and row['missing']==0 and row['end']-row['start']==180 and row['confirm']>=row['end']
    if not complete:
        return '公開完全3分足でない'
    prices=[row[n] for n in ('open','high','low','close')]
    if not all(finite(p) and p>0 for p in prices):
        return '価格不正'
    if min(prices)!=row['low'] or max(prices)!=row['high']:
        return '価格不正'
    return None


def visible_prefix(slot: dict,history: list[dict],feature: dict) -> list:
    """可視性を先に選び、番号0からcurrentまでの全prefixを検査する。

    引数: slot/feature(dict)は元判断と旧特徴、history(list[dict])は当場全足。
    返り値: list[dict]は当時可視SOURCE13。未来の価格を検査しない。
    """
    if not isinstance(history,list):
        raise ValueError('全足配列なし')
    limit=clock(slot);selected=[]
    for raw in history:
        if not isinstance(raw,dict) or raw.get('session')!=slot['session'] or not finite(raw.get('end')):
            raise ValueError('足の可視性が不明')
        if raw['end']>slot['scheduled']:
            continue
        if not finite(raw.get('confirm')) or type(raw.get('confirm_line')) is not int or raw['confirm_line']<0:
            raise ValueError('足の公開key不正')
        if (raw['confirm'],raw['confirm_line'])>limit:
            continue
        valid=set(SOURCE)<=set(raw) and type(raw['index']) is int and raw['index']>=0 and type(raw['minutes']) is int and raw['minutes']==3
        valid=valid and type(raw['publish']) is bool and type(raw['missing']) is int and raw['missing']>=0 and finite(raw['start'])
        if not valid:
            raise ValueError('可視足schema不正')
        row={n:deepcopy(raw[n]) for n in SOURCE}
        if selected and (row['index']<=selected[-1]['index'] or (row['confirm'],row['confirm_line'])<=(selected[-1]['confirm'],selected[-1]['confirm_line'])):
            raise ValueError('足番号又は公開keyが非増加')
        selected.append(row)
    try:
        current={n:feature['base']['base']['sources']['current'][n] for n in SOURCE}
    except (KeyError,TypeError) as error:
        raise ValueError('current出典なし') from error
    if not selected or selected[0]['index']!=0 or canonical(selected[-1])!=canonical(current) or price_reason(selected[-1]) is not None:
        raise ValueError('全prefix/current不整合')
    return selected


def values_for(feature: dict) -> dict:
    """直接条件に使う旧float64の値域と鏡像を別検査する。

    引数: feature(dict)は旧64特徴。
    返り値: dictは両方向の直接値。再学習・再算出しない。
    """
    vectors=feature.get('vectors');bg=feature.get('background_direction')
    if not isinstance(vectors,dict) or set(vectors)!={'1','-1'} or type(bg) is not int or bg not in (-1,0,1):
        raise ValueError('両側入力又は背景不正')
    output={}
    for s in (1,-1):
        vector=vectors[str(s)]
        if not isinstance(vector,list) or len(vector)!=64:
            raise ValueError('旧64列なし')
        row={n:deepcopy(vector[i]) for n,i in VALUES.items()}
        if not all(finite(x) for x in row.values()) or any(row[n] not in (0,1) for n in ('F51','F52')) or not 0<=row['F47']<=1 or not -1<=row['F48']<=1:
            raise ValueError('直接値/mask/ADX値域不正')
        if row['F01'] and (1 if row['F01']>0 else -1)!=s*bg:
            raise ValueError('DI方向と背景不整合')
        output[str(s)]={**row,'raw_background_direction':bg}
    for n in ('F01','F02','F03','F07','F15'):
        if output['1'][n]+output['-1'][n]!=0:
            raise ValueError('方向鏡像不整合')
    for n in ('F47','F48','F51','F52'):
        if output['1'][n]!=output['-1'][n]:
            raise ValueError('不変値鏡像不整合')
    return output


def band_view(slot: dict,band: dict) -> dict:
    """当時不可視な公開markerも隠して、必要な帯だけを小型化する。

    引数: slot(dict)は元判断、band(dict)は選ばれた帯。
    返り値: dictは当時の公開/準備/高安。未来のqualityは残さない。
    """
    if not isinstance(band,dict) or type(band.get('reference_available')) is not bool or not isinstance(band.get('id'),str) or not band['id'] or band.get('current_session')!=slot['session']:
        raise ValueError('帯識別不正')
    if not band['reference_available']:
        if band.get('published') is not False or band.get('ready') is not False or not isinstance(band.get('reason'),str):
            raise ValueError('前帯なしと準備が矛盾')
        return {'id':band['id'],'session':band.get('session'),'current_session':slot['session'],'reference_type':band.get('reference_type'),
            'prior_gap_seconds':band.get('prior_gap_seconds'),'reference_available':False,'begin':None,'end':None,'publication':band.get('publication'),
            'publication_key':None,'published':False,'ready':False,'reason':band['reason'],'high':None,'low':None,'mid':None}
    if type(band.get('published')) is not bool or band.get('publication') not in ('row','timer'):
        raise ValueError('帯公開方式不正')
    if not finite(band.get('begin')) or not finite(band.get('end')) or band['end']<=band['begin']:
        raise ValueError('帯境界不正')
    result={n:deepcopy(band.get(n)) for n in ('id','session','current_session','reference_type','prior_gap_seconds','reference_available','begin','end','publication')}
    result.update(publication_key=None,published=False,ready=False,reason='帯未公開',high=None,low=None,mid=None)
    if not band['published']:
        return result
    publication=band.get('publication_key')
    if not isinstance(publication,dict) or not finite(publication.get('time')) or publication['time']<band['end']:
        raise ValueError('帯公開clock不正')
    if band['publication']=='timer' and publication.get('line') is not None or band['publication']=='row' and (type(publication.get('line')) is not int or publication['line']<0):
        raise ValueError('帯公開原行不正')
    if publication['time']>slot['time'] or band['publication']=='row' and (publication['time'],publication['line'])>clock(slot):
        return result
    if type(band.get('ready')) is not bool or not isinstance(band.get('reason'),str):
        raise ValueError('帯準備不正')
    result.update(publication_key=deepcopy(publication),published=True,ready=band['ready'],reason=band['reason'])
    if band['ready']:
        if not all(finite(band.get(n)) and band[n]>0 for n in ('high','low','mid')) or band['low']>band['high'] or exact(band['mid'])*2!=exact(band['high'])+exact(band['low']):
            raise ValueError('帯高安又は中央不正')
        result.update({n:deepcopy(band[n]) for n in ('high','low','mid')})
    return result


def quote_view(slot: dict,quote: dict | None) -> bool:
    """元気配の出典を結合し、現在の正常な価格人口を判定する。

    引数: slot(dict)は元判断、quote(dict|None)は旧55判断気配。
    返り値: boolはBBOとLastの現在前提を判定できるか。
    """
    if quote is None:
        return False
    if not isinstance(quote,dict) or set(quote)!={'now','line','valid','last','bid','ask'} or type(quote['valid']) is not bool or not finite(quote['now']) or type(quote['line']) is not int or quote['line']<0 or (quote['now'],quote['line'])!=clock(slot):
        raise ValueError('気配clock/schema不正')
    return quote['valid'] and all(finite(quote[n]) and quote[n]>0 for n in ('last','bid','ask')) and quote['bid']<quote['ask']


# ----------------------------------------
def route_history(slot: dict,prefix: list[dict],band: dict,start: float,d: int) -> tuple:
    """一端の外側/中立/内側の区間列から、同原因のT/Rを別構成する。

    引数: slot/band(dict)は時計と固定端、prefix(list)は可視全足、start(float)は反応開始、d(int)は外方向。
    返り値: tupleは試行・形成・reset・反応数。入力実装のEndpointは呼ばない。
    """
    level=band['high'] if d==1 else band['low'];trials=[];formations=[];resets=[]
    trial=trend=returning=None;previous=None;was_out=False;count=0
    def identity(row: dict,kind: str) -> str:
        """不変の足keyへ帯と端を付ける。

        引数: row(dict)は起点、kind(str)は形成種。
        返り値: strは形成ID。
        """
        return '|'.join((slot['session'],band['id'],f'{d:+d}',kind,str(row['index']),float(row['confirm']).hex(),str(row['confirm_line'])))
    def log(record: dict,row: dict,action: str) -> None:
        """形成の最小遷移だけを追加する。

        引数: record/row(dict)は形成と当足、action(str)は動作。
        返り値: None。
        """
        record['trace'].append({**reference(row),'action':action,'status':record['status'],'active':record['active']})
    def finish(record: dict | None,row: dict,reason: str,status: str = '取消') -> None:
        """最初の終了を固定し再点火を防ぐ。

        引数: record(dict|None)は形成、row(dict)は当足、reason/status(str)は終了情報。
        返り値: None。
        """
        if record is not None and record['cancel'] is None:
            record.update(active=False,status=status,cancel={**reference(row),'reason':reason});log(record,row,reason)
    def consume(row: dict,reason: str) -> None:
        """現外試行の再利用を禁止する。

        引数: row(dict)は消費時点、reason(str)は原因。
        返り値: None。
        """
        trial.update(consumed=True,consumed_at=reference(row),consume_reason=reason)
    def make(row: dict,kind: str,premise: float) -> dict:
        """保存形を作り、同じ外試行へ結ぶ。

        引数: row(dict)はrun先頭又はf、kind(str)はT/R、premise(float)は既知否定線。
        返り値: dictは登録済みの可変形成。
        """
        record={'id':identity(row,kind),'episode_id':trial['id'],'kind':kind,'side':d if kind=='T' else -d,'break_direction':d,
            'level':level,'premise_line':premise,'b':deepcopy(row if kind=='T' else trial['first_outside']),
            'last_outside':deepcopy(trial['last_outside']),'f':deepcopy(row) if kind=='R' else None,
            'k':None,'active':False,'status':'確認待ち','cancel':None,'trace':[]}
        formations.append(record)
        if kind=='T':trial['T_ids'].append(record['id'])
        else:trial['R_id']=record['id']
        log(record,row,'T外足1本目' if kind=='T' else 'R内回帰f')
        return record
    for row in prefix:
        if row['start']<start:continue
        count+=1
        reason=price_reason(row)
        discontinuity=previous is not None and (row['index']!=previous['index']+1 or row['start']!=previous['end'])
        problems=(['番号又はend不連続'] if discontinuity else [])+([reason] if reason is not None else [])
        if problems:
            text='・'.join(problems);resets.append({**reference(row),'reason':text})
            finish(trend,row,text,'品質reset');finish(returning,row,text,'品質reset')
            if trial is not None and not trial['consumed']:consume(row,text)
            trial=trend=returning=None;was_out=False
        if reason is not None:
            previous=row;continue
        q=d*(exact(row['close'])-exact(level));out=q>=5
        if trial is not None and not trial['consumed'] and row['index']-trial['last_outside']['index']>3:
            consume(row,'最後の外足後3本の内回帰なし')
        # ----------------------------------------
        # 既存の内回帰は当足の条件喪失を確認成立より先に処理する。
        if returning is not None and returning['cancel'] is None:
            r=returning;distance=r['side']*(exact(row['close'])-exact(r['premise_line']));n=row['index']-r['f']['index']
            if q>-5:finish(r,row,'内回帰の内側条件否定')
            elif r['k'] is not None and distance<=0:finish(r,row,'再開線終値否定')
            elif r['k'] is None:
                if 1<=n<=3 and distance>0:
                    r.update(k=deepcopy(row),active=True,status='有効');log(r,row,'R再開k')
                elif n>=3:finish(r,row,'f後3本の再開確認なし','確認期限切れ')
        if not out:
            finish(trend,row,'外保持の終値5未満');trend=None
        else:
            if trial is None or trial['consumed']:
                trial={'id':identity(row,'外試行'),'direction':d,'level':level,'first_outside':deepcopy(row),'last_outside':deepcopy(row),
                    'consumed':False,'consumed_at':None,'consume_reason':None,'T_ids':[],'R_id':None};trials.append(trial)
            trial['last_outside']=deepcopy(row)
            if not was_out or trend is None:trend=make(row,'T',level)
            else:
                trend['last_outside']=deepcopy(row)
                if trend['k'] is None:
                    trend.update(k=deepcopy(row),active=True,status='有効');log(trend,row,'T外保持k')
        if not out and trial is not None and not trial['consumed']:
            if q<=-5:
                returning=make(row,'R',row['high'] if d==-1 else row['low']);consume(row,'最初の内回帰f')
        was_out=out;previous=row
    return trials,formations,resets,count


def qualification(candidate: dict,values: dict,quote: dict,D: float,mid: float,policy: str) -> dict:
    """直接gateを真偽命題として列挙し、位置前後の理由を保持する。

    引数: candidate/values/quote(dict)は形成/旧値/気配、D/mid(float)は幅/中央、policy(str)は政策。
    返り値: dictは資格・理由・当時距離。未来の回収を引数に取らない。
    """
    di,bg=values['F01'],values['raw_background_direction'];side=candidate['side'];kind=candidate['kind']
    role='待機' if not di or not bg else '順行' if di>0 else '反転'
    tests=[(not bg,'上位DI同値'),(not di,'DI優勢差同値'),(values['F02']<0,'FastK中央差が逆向き'),
        (values['F03']<=0,'FastK進行が非正'),(values['F07']<=0,'終値変化が非正')]
    if kind=='T':
        tests += [(di<=0,'外保持は上位DI同方向が必要'),(values['F51']!=1 or values['F52']!=1,'外保持のADX現値又は変化が未知'),
            (values['F47']<.20,'外保持のADX20未満'),(values['F48']<0,'外保持のADXが減速')]
    elif di<0:
        tests += [(values['F52']!=1,'反転のADX変化が未知'),(values['F48']>=0,'反転のADXが非減速'),(values['F15']<=0,'反転の15分終値位置が非正')]
    entry=quote['ask'] if side==1 else quote['bid'];line=candidate['premise_line']
    last_distance=side*(exact(quote['last'])-exact(line));entry_distance=side*(exact(entry)-exact(line))
    room=side*(exact(mid)-exact(entry)) if kind=='R' else None
    tests += [(last_distance<=0,'現在Lastが前提線を否定'),(entry_distance<=0,'現在新規BBOが前提線を否定')]
    reasons=[message for failed,message in tests if failed];basic=not reasons
    position_reasons=[message for failed,message in ((entry_distance<=0 or entry_distance>exact(D),'前提線までの新規距離がD範囲外'),
        (room is not None and room<250,'内回帰の中央余地250未満')) if failed]
    position=basic and not position_reasons
    return {'basic_qualified':basic,'position_qualified':position,'qualified':position if policy=='P1' else basic,'role':role,
        'reasons':reasons+(position_reasons if policy=='P1' else []),'basic_reasons':reasons,'position_reasons':position_reasons,'values':deepcopy(values),
        'price':{'last':quote['last'],'entry_proxy':entry,'premise_line':line,'last_distance':float(last_distance),'entry_distance':float(entry_distance),
            'mid_room':float(room) if room is not None else None,'D':D}}


def latest(candidates: list,qualifications: dict,field: str) -> dict | None:
    """資格集合の最大公開keyを選び、同keyはTを先にする。

    引数: candidates(list)は有効形成、qualifications(dict)は資格、field(str)は適用前後の旗。
    返り値: dict|Noneは独立選択。両方向資格や同型重複を拒否する。
    """
    eligible=[row for row in candidates if qualifications[row['id']][field]]
    if len({row['side'] for row in eligible})>1 or len({(r['kind'],r['side']) for r in eligible})!=len(eligible):
        raise ValueError('現在適格の方向又は同型重複矛盾')
    ordered=sorted(eligible,key=lambda r:(r['k']['confirm'],r['k']['confirm_line'],r['kind']=='T'),reverse=True)
    return deepcopy(ordered[0]) if ordered else None


def derive(slot: dict,history_sources: list[dict],band: dict,decision_quote: dict | None,policy: str) -> dict:
    """当時の帯・全prefix・旧値・気配から観測全文を別算する。

    引数: slot(dict)はfeature付き元判断、history_sources(list)は全当場足、band(dict)は一帯、decision_quote(dict|None)は当時気配、policy(str)は政策。
    返り値: dictは75観測schema。新入力/主/Engineを呼ばない。
    """
    if policy not in POLICIES:raise ValueError('政策不正')
    clock(slot);feature=slot.get('feature')
    if not isinstance(feature,dict) or type(feature.get('ready')) is not bool or feature['ready'] is not slot['ready']:
        raise ValueError('旧準備不整合')
    output={'ready':False,'reason':'旧73特徴が未準備','policy':policy,'source_count':0,'source_sha256':None,'reaction_count':0,'reaction_start':None,
        'band':None,'history':{'current':None,'resets':[]},'trials':[],'formations':[],'candidates':[],'qualifications':{},
        'selected_before_position':None,'selected':None,'side':0,'role':'待機'}
    if not feature['ready']:return output
    if not finite(slot.get('atr')) or slot['atr']<=0 or not finite(slot.get('D')) or slot['D']<=0 or feature.get('atr')!=slot['atr'] or feature.get('D')!=slot['D']:
        raise ValueError('旧幅不整合')
    prefix=visible_prefix(slot,history_sources,feature);values=values_for(feature)
    output.update(source_count=len(prefix),source_sha256=hashlib.sha256(canonical(prefix).encode('utf-8')).hexdigest())
    output['history']['current']=deepcopy(prefix[-1]);view=band_view(slot,band);output['band']=view
    if not view['ready']:
        output['reason']=view['reason'];return output
    output['ready']=True
    if view['high']==view['low']:
        output['reason']='平坦帯は反応対象外';return output
    start=view['end'] if policy=='O0' else prefix[0]['start']
    if 'reaction_start' in band and band['reaction_start']!=start:raise ValueError('反応開始不整合')
    output['reaction_start']=start
    records=[route_history(slot,prefix,view,start,d) for d in (1,-1)]
    output['trials']=deepcopy([row for record in records for row in record[0]])
    output['formations']=deepcopy([row for record in records for row in record[1]])
    output['reaction_count']=records[0][3];output['history']['resets']=records[0][2]
    output['candidates']=[{**deepcopy(row),'k_age_seconds':slot['time']-row['k']['confirm']} for row in output['formations'] if row['active']]
    if not quote_view(slot,decision_quote):
        output.update(ready=False,reason='現在BBO又はLastの観測不足');return output
    for candidate in output['candidates']:
        output['qualifications'][candidate['id']]=qualification(candidate,values[str(candidate['side'])],decision_quote,slot['D'],view['mid'],policy)
    output['selected_before_position']=latest(output['candidates'],output['qualifications'],'basic_qualified')
    output['selected']=latest(output['candidates'],output['qualifications'],'qualified')
    selected=output['selected']
    if selected is None:
        output['reason']='固定帯反応の複合条件不適格' if output['candidates'] else '現在有効な固定帯反応なし'
    else:
        output.update(side=selected['side'],role=output['qualifications'][selected['id']]['role'],reason='固定帯反応の複合候補')
    return output


def choose(slot: dict,observation: dict,policy: str) -> dict:
    """独立観測から旧純10項目と最小由来を構成する。

    引数: slot(dict)は元判断、observation(dict)は同政策の観測、policy(str)は政策。
    返り値: dictはO49入力と由来。旧予測・将来結果を持たない。
    """
    if policy not in POLICIES or not all(n in slot for n in PURE):raise ValueError('政策又は純項目なし')
    clock(slot)
    if not isinstance(observation,dict) or observation.get('policy')!=policy or type(observation.get('ready')) is not bool or type(observation.get('side')) is not int or observation['side'] not in (-1,0,1):raise ValueError('観測不正')
    selected=observation['selected'];side=observation['side']
    if side and (not observation['ready'] or selected is None or selected['side']!=side or not observation['qualifications'][selected['id']]['qualified']):raise ValueError('方向と形成不整合')
    kind=selected['kind'] if selected is not None else None
    result={n:deepcopy(slot[n]) for n in PURE}
    result.update(session=slot['session'],policy=policy,ready=observation['ready'],side=side,role=observation['role'],reason=observation['reason'],
        origin=('O30' if policy=='O0' else '前帯')+('外保持' if kind=='T' else '内回帰' if kind=='R' else '待機'),
        pattern_id=selected['id'] if selected is not None else None,formation=kind,premise_line=selected['premise_line'] if selected is not None else None,
        band_id=observation['band']['id'] if observation['band'] is not None else None)
    return result


# ----------------------------------------
def synthetic(closes: list[float],favored: int = 1,background: int = 1) -> tuple:
    """市場を開かず、全prefixと旧64値を持つ架空材料を作る。

    引数: closes(list[float])は終値列、favored/background(int)は短期/上位の方向。
    返り値: tupleは元slot/history/band/quote。教師・結果は含まない。
    """
    session='2026-01-01_Day'
    history=[{'session':session,'index':i,'minutes':3,'start':float(i*180),'end':float((i+1)*180),
        'confirm':float((i+1)*180),'confirm_line':10*i+1,'publish':True,'missing':0,
        'open':float(c),'high':float(c+10),'low':float(c-10),'close':float(c)} for i,c in enumerate(closes)]
    time=history[-1]['end'];vectors={}
    for s in (1,-1):
        vector=[0.]*64
        for name,value in {'F01':s*background*.3,'F02':s*favored*.2,'F03':s*favored*.1,'F07':s*favored*.1,
                'F15':s*favored*.2,'F47':.3,'F48':.01 if favored==background else -.01,'F51':1,'F52':1}.items():
            vector[VALUES[name]]=value
        vectors[str(s)]=vector
    feature={'ready':True,'atr':20.,'D':20.,'background_direction':background,'vectors':vectors,
        'base':{'base':{'sources':{'current':deepcopy(history[-1])}}}}
    slot={'session':session,'slot_id':'人工75','scheduled':time,'time':time+1,'line':10000,'side':0,'role':'待機','atr':20.,'D':20.,'ready':True,'reason':'旧待機','feature':feature}
    band={'id':'FULL:人工前帯','session':'2025-12-31_Night','current_session':session,'reference_type':'FULL','reference_available':True,'prior_gap_seconds':10.,
        'begin':-2000.,'end':-100.,'publication':'timer','published':True,'publication_key':key(-100.,None),'ready':True,'reason':'準備済み',
        'high':1000.,'low':100.,'mid':550.}
    quote={'now':time+1,'line':10000,'last':float(closes[-1]),'bid':float(closes[-1]-1),'ask':float(closes[-1]+1),'valid':True}
    return slot,history,band,quote


def self_test() -> dict:
    """帯・価格順序・採否の全文と手計算境界を架空材料だけで照合する。

    引数: なし。
    返り値: dictは人工成功/系列/照合数。新実装importはこの人工出力側だけ。
    """
    def load(path: Path,name: str):
        """人工出力側の新実装を固有名で読む。

        引数: path(Path)は新コード、name(str)は固有名。
        返り値: ModuleTypeは出力実装。正式deriveからは呼ばない。
        """
        spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec)
        sys.modules[name]=module;spec.loader.exec_module(module);return module
    actual=load(HERE/'入力.py','75独立人工の入力実装側');bands=load(HERE/'参照帯.py','75独立人工の帯実装側')
    count=series=0
    def check(a: object,b: object,name: str) -> None:
        """人工の型値全文を比較する。

        引数: a/b(object)は独立期待と実装値、name(str)は検査名。
        返り値: None。不一致は即座に人工停止。
        """
        nonlocal count
        count+=1
        if canonical(a)!=canonical(b):raise AssertionError(name+'\n'+canonical(a)[:1500]+'\n'+canonical(b)[:1500])
    def compare(material: tuple,expect_error: bool = False) -> dict | None:
        """同じ架空入力を両算法へ渡し、採否を含めて全政策を比較する。

        引数: material(tuple)は四材料、expect_error(bool)は拒否期待。
        返り値: dict|NoneはP0の独立観測又は拒否。
        """
        nonlocal series
        series+=1;slot,history,band,quote=material;before=canonical(material);result=None
        for policy in POLICIES:
            values=[];errors=[]
            for function in (derive,actual.extract):
                try:values.append(function(slot,history,band,quote,policy));errors.append(False)
                except ValueError:values.append(None);errors.append(True)
            check(errors,[expect_error,expect_error],'両算法の拒否')
            if expect_error:continue
            check(values[0],values[1],'全観測:'+policy)
            check(choose(slot,values[0],policy),actual.choose(slot,values[1],policy),'全純射影:'+policy)
            if policy=='P0':result=values[0]
        check(canonical(material),before,'入力非改変')
        return result
    # ----------------------------------------
    # T/Rの形成時点、3本境界、再取得と同原因非復活を手計算で固定する。
    paths=[([990,1005,1005],1),([990,1006,1007,1008],1),([990,1006,1007,1003],1),
        ([990,1006,1007,994,980],-1),([1006,1007,994,990,989,983],-1),
        ([1006,1007,994,990,989,985,980],-1),([1006,1007,994,980,984,980],-1),
        ([1006,1007,994,997,980],-1),([1006,1000,1000,1000,994],-1),
        ([990,1006,1007,1003,1006,1007,994,980],-1),([990,991,992],1),([1006,1000,1000,1000,1006,1007],1)]
    outputs=[]
    for closes,favored in paths:
        material=synthetic(closes,favored);outputs.append(compare(material))
        slot,history,band,quote=deepcopy(material);center=2000
        for row in history:
            high,low=row['high'],row['low'];row.update(open=center-row['open'],close=center-row['close'],high=center-low,low=center-high)
        slot['feature']['base']['base']['sources']['current']=deepcopy(history[-1]);slot['feature']['background_direction']*=-1
        slot['feature']['vectors']={str(s):deepcopy(material[0]['feature']['vectors'][str(-s)]) for s in (1,-1)}
        high,low=band['high'],band['low'];band.update(high=center-low,low=center-high,mid=center-band['mid'])
        bid,ask=quote['bid'],quote['ask'];quote.update(last=center-quote['last'],bid=center-ask,ask=center-bid)
        mirror=compare((slot,history,band,quote));check(mirror['side'],-outputs[-1]['side'],'鏡像純方向')
    check((outputs[0]['side'],outputs[0]['selected']['b']['index'],outputs[0]['selected']['k']['index']),(1,1,2),'T外側5等号の2本確認')
    check(outputs[2]['candidates'],[],'T5未満で取消')
    check((outputs[3]['selected']['kind'],outputs[3]['selected']['b']['index'],outputs[3]['selected']['f']['index'],outputs[3]['selected']['k']['index']),('R',1,3,4),'R別足順序')
    check(outputs[4]['selected']['k']['index'],5,'R3本目の確認可')
    check(any(r['status']=='確認期限切れ' for r in outputs[5]['formations']),True,'R3本確認なし失効')
    check(outputs[6]['candidates'],[],'k線等号否定の非復活')
    check(outputs[7]['candidates'],[],'内側条件否定の非復活')
    check(sum(r['kind']=='R' for r in outputs[8]['formations']),0,'最後外足後4本のf禁止')
    check(len(outputs[9]['trials']),1,'T再形成は同じ未消費外試行')
    check((len(outputs[11]['trials']),outputs[11]['trials'][0]['consumed_at']['index']),(2,4),'4本目外足より前に旧外試行失効')
    # ----------------------------------------
    # 出典prefix、gap reset、未公開future marker、未知と位置条件を分ける。
    base=synthetic([990,1006,1007,994,980],-1)
    for field,value in (('publish',False),('missing',1),('close',float('nan')),('start',1.)):
        material=deepcopy(base);material[1][1][field]=value;compare(material)
    material=deepcopy(base);material[1][1]['index']=0;compare(material,True)
    material=deepcopy(base);material[1].pop(0);compare(material,True)
    material=deepcopy(base);material[1][-1]['close']+=1;compare(material,True)
    material=deepcopy(base);material[1].append({'session':material[0]['session'],'end':999999,'confirm':None,'high':float('nan')});compare(material)
    material=deepcopy(base);material[1].append({'session':material[0]['session'],'end':material[0]['scheduled'],'confirm':material[0]['time']+1,'confirm_line':1234});compare(material)
    material=deepcopy(base);material[2].update(publication='row',publication_key=key(material[0]['time']+10,10001),high=float('nan'),low=None,mid=None)
    hidden=compare(material);check(hidden['band']['publication_key'],None,'未来marker非開示')
    material[2]['publication_key']=key(material[0]['time']+100,99999);check(compare(material),hidden,'未来marker差のprefix不変')
    material=deepcopy(base);material[2].update(high=1000.,low=1000.,mid=1000.);flat=compare(material);check((flat['ready'],flat['side']),(True,0),'既知平坦はreadyWAIT')
    material=deepcopy(base);material[2].update(reference_available=False,published=False,ready=False,reason='前収録なし',begin=None,end=None,high=float('nan'),mid=None)
    absent=compare(material);check((absent['ready'],absent['reason'],absent['band']['high']),(False,'前収録なし',None),'前帯なしは価格/clockより先にWAIT')
    material=deepcopy(base);material[0].update(ready=False,line=None);material[0]['feature']={'ready':False};compare(material)
    material=deepcopy(base);material[3]['valid']=False;unknown=compare(material);check((unknown['ready'],unknown['reason']),(False,'現在BBO又はLastの観測不足'),'気配未知')
    material=deepcopy(base);material[3]['line']-=1;compare(material,True)
    for index,value in ((2,0.),(6,0.),(0,0.)):
        material=deepcopy(base)
        for s in (1,-1):material[0]['feature']['vectors'][str(s)][index]=value
        if index==0:material[0]['feature']['background_direction']=0
        compare(material)
    material=deepcopy(base);material[0]['feature']['vectors']['-1'][2]=material[0]['feature']['vectors']['1'][2];compare(material,True)
    # ----------------------------------------
    # 帯と収録隣接の直接算法は旧人工100系列をこの自己検査にも明示する。
    for n in (0,1,2,4,8):
        for spacing in (0,299,300,301):
            events=[{'now':100.+i*spacing,'line':i+1,'last':100.+i%3,'bid':99.,'ask':101.,'valid':True} for i in range(n)]
            for publication in ('row','timer'):
                for marker in (False,True):
                    stream=deepcopy(events)+([{'now':1000.,'line':99},{'now':'未来不正'}] if marker else [])
                    check(aggregate(stream,100.,1000.,publication),bands.aggregate(stream,100.,1000.,publication),'帯全文');series+=1
    entries=[{'session':s,'symbol':'NK225','in_session_contract_codes':['202612'],'ignored_price':999} for s in ('2026-10-02_Day','2026-10-02_Night','2026-10-05_Day')]
    for mutation in ('normal','different','samekind','multi'):
        rows=deepcopy(entries)
        if mutation=='different':rows[1]['in_session_contract_codes']=['202703']
        elif mutation=='samekind':rows[1]['session']='2026-10-03_Day'
        elif mutation=='multi':rows[1]['in_session_contract_codes']=[]
        check(choose_previous(rows),bands.choose_previous(rows),'前収録全文');series+=1
    return {'成功':True,'人工成功':True,'テスト件数':series,'照合項目数':count,'不一致数':0,'不一致':[],
        '本物入力読取':False,'本物価格集約':False,'fit':0,'市場戦略再生':False,'新実装は人工出力側のみ':True}


if __name__=='__main__':
    print(json.dumps(self_test(),ensure_ascii=False,allow_nan=False))
