"""固定出生・独立一覧oracle・生金融配列から167/168の自然全結果を検算する。"""
from pathlib import Path
from collections import Counter
from types import SimpleNamespace
import importlib.util
import math
import sys
import time

import numpy as np

ROOT=Path(__file__).resolve().parents[2]
HERE=Path(__file__).resolve().parent
P167=ROOT/'work/167固定入口の別期間'
P168=ROOT/'work/168数量枠の因果再生'
NEW=ROOT/'work/167追加七場の入力'


def module(path: Path,name: str) -> object:
    """
    機能: mainを呼ばずに独立確認用の純関数だけを取り込む。
    引数: path(Path)、name(str)はSourceと登録名。
    返り値: objectはmodule。
    """
    spec=importlib.util.spec_from_file_location(name,path);value=importlib.util.module_from_spec(spec)
    sys.modules[name]=value;spec.loader.exec_module(value);return value


IO_PATH=ROOT/'work/165自然独立確認/自然値を独立検算する.py'
LOCAL_PATH=ROOT/'work/166自然独立確認/階層と自然値を独立検算する.py'
ORACLE_PATH=ROOT/'work/168数量枠の独立確認/独立人工を確認する.py'
io=module(IO_PATH,'independent165_for167_168');local_qa=module(LOCAL_PATH,'independent166_for167_168')
quantity=module(ORACLE_PATH,'independent168_for167_168')
read=io.read;save=io.save;sha=io.sha


def load_dataset(old: bool) -> object:
    """
    機能: 旧cache又は追加接続器の価格特徴と生金融配列を別々に読む。
    引数: old(bool)は旧73場か追加7場か。
    返り値: SimpleNamespaceはfeatures/captures/arrays等。作者Contextを生成しない。
    """
    if old:
        cache=ROOT/'work/151過去場判別の評価/入口選択/cache/feature_only';meta=read(cache/'features_meta.json')
        q0=meta['q0_meta'];scenes=meta['scenes']
        with np.load(cache/'features.npz',allow_pickle=False) as source:
            buy=source['buy_X'].copy();sell=source['sell_X'].copy();columns=source['columns'].tolist()
        captures=read(ROOT/'inputs/00148_全1分入口母集団/取得対応.json.gz')['rows']
        directory=ROOT/'work/163任意幅の数値化/自然数値表'
    else:
        parent=NEW/'入口母集団';proof=read(parent/'完了.json')
        assert proof['success'] and proof['financial_labels_used'] is False and proof['strategy_selected'] is False
        for name,ref in proof['files'].items():assert sha(parent/name)==ref['sha256']
        feature=read(parent/'当時特徴.json.gz');fixed=read(parent/'固定取得入力.json.gz')
        scenes=[{name:row[name] for name in ('session','contract','start','end','force_close')} for row in fixed['scenes']]
        scene_index={row['session']:i for i,row in enumerate(scenes)};q0=[];buy=[];sell=[]
        columns=[row['name'] for row in feature['catalog']]
        for row in feature['rows']:
            quote=row['metadata']['q0']
            q0.append({'event_id':row['event_id'],'session':row['session'],'contract':row['contract'],
                       'session_index':scene_index[row['session']],'q0_time':quote['time'],
                       'q0_index':quote['index'],'q0_line':quote['source_line']})
            buy.append(row['buy']['x']);sell.append(row['sell']['x'])
        buy=np.asarray(buy,dtype=float).reshape(-1,100);sell=np.asarray(sell,dtype=float).reshape(-1,100)
        captures=read(parent/'取得対応.json.gz')['rows'];directory=NEW/'自然数値表'
    raw_meta=read(directory/'任意幅識別.json.gz')
    with np.load(directory/'任意幅配列.npz',allow_pickle=False) as source:arrays={name:source[name].copy() for name in source.files}
    assert raw_meta['session_order']==[row['session'] for row in scenes]
    assert len(columns)==100 and columns==sorted(columns) and buy.shape==sell.shape==(len(q0),100)
    assert not np.isinf(buy).any() and not np.isinf(sell).any()
    by_event={row['event_id']:row for row in captures};assert len(by_event)==len(q0)
    captures=[by_event[row['event_id']] for row in q0];mapping={name:i for i,name in enumerate(raw_meta['case_ids'])}
    events=[[] for _ in scenes];event_keys=[];event_scenes=[];pure_captures=[]
    for event,row in enumerate(q0):
        capture=captures[event];key=(row['q0_time'],row['q0_index'],row['q0_line'])
        assert io.key(capture['q0'])==key;events[row['session_index']].append(event)
        event_keys.append(key);event_scenes.append(row['session_index'])
        expiry=(capture['expires'],math.inf,math.inf)
        end=min(expiry,io.key(capture['terminated_at'])) if capture.get('terminated_at') is not None else expiry
        pure={'status':capture['status'],'finish_key':end}
        if capture['status']=='filled':
            case=mapping[capture['case_id']];pure.update(case=case,fill_key=io.key(capture['q1']))
            assert tuple(arrays['entry_'+name][case] for name in ('time','index','line'))==io.key(capture['q1'])
            assert int(arrays['session_index'][case])==row['session_index']
        pure_captures.append(pure)
    hours=np.zeros((len(scenes),3))
    for si,scene in enumerate(scenes):
        end=scene['end']-300
        if scene['session'].endswith('_Day'):hours[si,0]=(end-scene['start'])/3600
        else:
            boundary=io.ny_open(scene['session']);hours[si,1]=max(0,min(boundary,end)-scene['start'])/3600
            hours[si,2]=max(0,end-max(boundary,scene['start']))/3600
    assert np.all(arrays['known'][arrays['direction']!=0])
    assert np.all(arrays['label'][arrays['known']&(arrays['direction']==0)]==0)
    return SimpleNamespace(q0=q0,scenes=scenes,buy=buy,sell=sell,columns=columns,captures=captures,
                           arrays=arrays,meta=raw_meta,mapping=mapping,scene_events=events,hours=hours,
                           event_keys=event_keys,event_scenes=np.asarray(event_scenes,dtype=np.int16),pure_captures=pure_captures)


def rule_direction(data: object,candidate: dict) -> np.ndarray:
    """
    機能: 固定辞書の原始条件を、作者の評価関数を使わず両実側へ適用する。
    引数: data(SimpleNamespace)、candidate(dict)は固定規則辞書。
    返り値: np.ndarray[int8,N]は競合時0の正逆方向。
    """
    index={name:i for i,name in enumerate(data.columns)};flags=[]
    for side in (data.buy,data.sell):
        passed=np.ones(len(side),dtype=bool)
        for term in candidate['conditions']:
            name=term['factor']
            value=np.abs(side[:,index['q0_last_minus_m1_close_atr5_to_side']]) if name=='abs_q0_close_gap' else side[:,index[name]]
            threshold=term['threshold'];operator=term['operator']
            if operator=='>':truth=value>threshold
            elif operator=='>=':truth=value>=threshold
            elif operator=='<':truth=value<threshold
            else:assert operator=='<=';truth=value<=threshold
            passed &= np.isfinite(value)&truth
        flags.append(passed)
    return np.asarray([1 if b and not s else -1 if s and not b else 0 for b,s in zip(*flags,strict=True)],dtype=np.int8)


def technical_old(data: object,width: int) -> np.ndarray:
    """
    機能: 165の17列全既知・8票・役割gateを独立に再構成する。
    引数: data(SimpleNamespace)、width(int)は150又は200。
    返り値: np.ndarray[int8,N]は高得点側のみの旧T方向。
    """
    index={name:i for i,name in enumerate(data.columns)};scores=[];flags=[]
    required=('m5_ema21_delta_to_side','m15_ema21_delta_to_side','m30_ema21_delta_to_side',
              'm5_di_difference_to_side','m15_di_difference_to_side','m30_di_difference_to_side',
              'm5_hist_delta_to_side','m15_hist_delta_to_side','m5_rsi_delta_to_side','m15_rsi_delta_to_side',
              'm5_body_ratio_to_side','m5_close_position_to_side','m1_volume_relative_prior3',
              'bb15_position_sigma_to_side','bb15_forward_room_125_ratio_to_side',
              'q0_entry_minus_ema8_atr5_to_side','m5_tr_atr_ratio')
    for side in (data.buy,data.sell):
        a={name:side[:,index[name]] for name in data.columns};known=np.isfinite(side[:,[index[name] for name in required]]).all(axis=1)
        ema=sum((a[f'm{m}_ema21_delta_to_side']>0).astype(np.int8) for m in (5,15,30))>=2
        di=sum((a[f'm{m}_di_difference_to_side']>0).astype(np.int8) for m in (5,15,30))>=2
        body=(a['m5_body_ratio_to_side']>0)&(a['m5_close_position_to_side']>.5)
        votes=[ema,di,(a['m5_hist_delta_to_side']>0)&(a['m15_hist_delta_to_side']>0),
               (a['m5_rsi_delta_to_side']>0)&(a['m15_rsi_delta_to_side']>=0),body,a['m1_volume_relative_prior3']>=1,
               (np.abs(a['bb15_position_sigma_to_side'])<=1)&(a['bb15_forward_room_125_ratio_to_side']*125/width>=.5),
               (np.abs(a['q0_entry_minus_ema8_atr5_to_side'])<=1)&(a['m5_tr_atr_ratio']<=1.5)]
        score=np.where(known,np.stack(votes).sum(axis=0),np.nan);scores.append(score)
        momentum=((a['m5_hist_delta_to_side']>0)&(a['m15_hist_delta_to_side']>=0))|\
                 ((a['m5_rsi_delta_to_side']>0)&(a['m15_rsi_delta_to_side']>=0))|body
        flag=(score>=5)&(ema|di)&momentum&(a['q0_spread_points']>0)&(a['q0_spread_points']<=20)&\
             (np.abs(a['q0_last_minus_m1_close_atr5_to_side'])<=1)&(a['q0_entry_minus_ema8_atr5_to_side']<=1)&\
             (a['m5_rsi_center_to_side']<=25)&(np.abs(a['m5_rsi_delta_to_side'])<=12)&(a['m1_volume_relative_prior3']>=.5)
        flags.append(flag)
    margin=scores[0]-scores[1]
    return np.asarray([1 if m>=1 and b else -1 if m<=-1 and s else 0 for m,b,s in zip(margin,*flags,strict=True)],dtype=np.int8)


def births(data: object,candidate: dict,catalog: dict) -> dict:
    """
    機能: 純粋な原始条件・独立旧T・独立局所式から固定出生を作る。
    引数: data(SimpleNamespace)、candidate/catal​og(dict)は固定設定と固定辞書。
    返り値: dict[str,np.ndarray]は作者と比較する7方向属性。
    """
    a=rule_direction(data,catalog[candidate['profile']['momentum']]);b=-rule_direction(data,catalog[candidate['profile']['fade']])
    core=np.asarray([0 if x and y and x!=y else x if x else y for x,y in zip(a,b,strict=True)],dtype=np.int8)
    branch=np.asarray([-1 if not side else 0 if x else 1 for side,x in zip(core,a,strict=True)],dtype=np.int8)
    old=technical_old(data,int(candidate['integration'][1:]))
    local,eligible,score,seen,counts=local_qa.local_from_rows(data.buy,data.sell,data.columns,data.q0,data.scenes,[candidate['hierarchy']])
    technical=np.asarray([x if x else y for x,y in zip(old,local[0],strict=True)],dtype=np.int8)
    tier=np.asarray([1 if x else 2 if y else 0 for x,y in zip(old,local[0],strict=True)],dtype=np.int8)
    return {'core':core,'branches':branch,'technical':technical,'tier':tier,'oldtechnical':old,
            'local':local[0],'local_eligible':eligible[0]}


def independent_selection(data: object,born: dict,candidate: dict) -> tuple:
    """
    機能: capture当時時計だけで実取得と技術初参加補完を再構成する。
    引数: data(SimpleNamespace)、born/candidate(dict)は出生と固定幅。
    返り値: tupleは取得tuple・幅添字・tier・因果監査。
    """
    core=io.link(born['core'],data.captures,data.mapping)
    extra,audits=io.technical_controller(born['core'],born['technical'],data.captures,data.scene_events,data.scenes,data.mapping)
    rows=io.merged(core,extra,technical=True)
    widths=io.widths_for(rows,born['branches'],candidate['momentum_width'],candidate['fade_width'],int(candidate['integration'][1:]),data.meta['widths'])
    tiers=[int(born['tier'][row[2]]) if row[3]==2 else 0 for row in rows]
    return rows,widths,tiers,audits


def statistics(data: object,rows: list,widths: np.ndarray,hi: int,mask: np.ndarray|None=None,
               eligible: np.ndarray|None=None,hours: float|None=None) -> dict:
    """
    機能: 生NPZのIFD方向・金融既知・net5だけから可変場の全統計を計算する。
    引数: data(SimpleNamespace)、rows(list)、widths(np.ndarray)、hi(int)、mask/eligible(np.ndarray又はNone)、hours(float又はNone)。
    返り値: dictはFANC・既知利益損失・全件収支・参加・保有等。作者statisticsは使わない。
    """
    if mask is None:mask=np.ones(len(rows),dtype=bool)
    if eligible is None:eligible=np.ones(len(data.scenes),dtype=bool)
    if hours is None:hours=float(data.hours[eligible].sum())
    case=np.asarray([row[0] for row,keep in zip(rows,mask,strict=True) if keep],dtype=np.int32)
    side=np.asarray([row[1] for row,keep in zip(rows,mask,strict=True) if keep],dtype=np.int8);w=widths[mask]
    arrays=data.arrays;known=arrays['known'][case,side,w,hi];direction=arrays['direction'][case,side,w,hi]
    f=int((direction==1).sum());a=int((direction==-1).sum());n=int(((direction==0)&known).sum());c=int((~known).sum());count=len(case)
    assert f+a+n+c==count
    money=arrays['net5'][case,side,w,hi][known];profit=sum(int(v) for v in money if v>0);loss=-sum(int(v) for v in money if v<0)
    scenes=Counter(int(arrays['session_index'][ci]) for ci in case);duration=(arrays['exit_time'][case,side,w,hi]-arrays['entry_time'][case])[known]
    return {'count':count,'F':f,'A':a,'N':n,'C':c,'rate':f/(f+a) if f+a else None,
            'complete_rate':f/(f+a+n) if f+a+n else None,'all_rate':f/count if count else None,
            'profit':profit,'loss':loss,'net':profit-loss,'pf':profit/loss if loss else None,
            'known':int(known.sum()),'unknown':c,'all_net':profit-loss if c==0 else None,
            'wins':int((money>0).sum()),'loss_trades':int((money<0).sum()),'realized_win_rate':float((money>0).mean()) if len(money) else None,
            'scenes':len(scenes),'eligible_scenes':int(eligible.sum()),
            'all_scenes':bool(eligible.any() and all(scenes[int(i)]>0 for i in np.flatnonzero(eligible))),
            'hours':hours,'per_hour':count/hours if hours else None,'max_scene_share':max(scenes.values())/count if count else None,
            'hold_mean_seconds':float(duration.mean()) if len(duration) else None,
            'hold_median_seconds':float(np.median(duration)) if len(duration) else None}


def compare_statistics(actual: dict,expected: dict,where: object) -> int:
    """
    機能: 全統計項目の未知・整数・実数を照合する。
    引数: actual/expected(dict)、where(object)は結果と所在。
    返り値: intは検査した指標数。
    """
    for name,value in expected.items():
        got=actual[name]
        if value is None:assert got is None,(where,name,got,value)
        elif isinstance(value,(bool,int)):assert got==value,(where,name,got,value)
        else:assert got is not None and math.isclose(float(got),value,rel_tol=1e-12,abs_tol=1e-9),(where,name,got,value)
    return len(expected)


def phases(data: object,rows: list,clock: str) -> np.ndarray:
    """
    機能: q0出生又はq1取得の実時計から三帯を独立に付ける。
    引数: data(SimpleNamespace)、rows(list)、clock(str q0/q1)。
    返り値: np.ndarray[int8]は0DAY/1NY前/2NY後。
    """
    return np.asarray([io.band(data.meta['sessions'][row[0]],data.q0[row[2]]['q0_time'] if clock=='q0' else float(data.arrays['entry_time'][row[0]]))
                       for row in rows],dtype=np.int8)


def reference_match(data: object,rows: list,widths: np.ndarray,tiers: list,reference: dict) -> None:
    """
    機能: 実取得の全属性を保存参照へ比較する。
    引数: data(SimpleNamespace)、rows(list)、widths(np.ndarray)、tiers(list)、reference(dict)。
    返り値: None。不一致は例外。
    """
    for at,name in enumerate(('cases','sides','events','origins')):assert [row[at] for row in rows]==reference[name],name
    assert widths.tolist()==reference['widths'] and list(tiers)==reference['tiers']
    assert phases(data,rows,'q0').tolist()==reference['phases']


def audit_financial_parts(data: object,rows: list,widths: np.ndarray,tiers: list,born: dict,candidate: dict,
                          total: dict,scene_reports: list,band_reports: dict,branch_reports: dict,side_reports: dict,
                          band_style: str) -> int:
    """
    機能: 全場・三帯・枝・売買を同じ実取得分母で再計算する。
    引数: data/rows/widths/tiers/born/candidateは固定入力、各reportは保存された分解、band_style(str)は167又は168。
    返り値: intは検算した統計セル数。
    """
    hi=data.meta['horizon_ids'].index(candidate['horizon']);scene=np.asarray([data.arrays['session_index'][row[0]] for row in rows],dtype=np.int16)
    checked=compare_statistics(total,statistics(data,rows,widths,hi),'全期')
    for si,report in enumerate(scene_reports):
        assert report['session']==data.scenes[si]['session']
        eligible=np.arange(len(data.scenes))==si;actual=report['metrics'] if band_style=='167' else report
        checked+=compare_statistics(actual,statistics(data,rows,widths,hi,scene==si,eligible),('場',si))
    for clock,name in (('q0','q0出生'),('q1','q1取得')):
        for phase,(band_name,short_name) in enumerate(zip(('デイ','ナイト米国前','ナイト米国後'),('DAY','NY前','NY後'),strict=True)):
            current=phases(data,rows,clock);eligible=data.hours[:,phase]>0
            actual=band_reports[name][phase]['metrics'] if band_style=='167' else band_reports[clock][short_name]
            checked+=compare_statistics(actual,statistics(data,rows,widths,hi,current==phase,eligible,float(data.hours[:,phase].sum())),('帯',clock,phase))
    branches=np.asarray([int(born['branches'][row[2]]) if row[3]==0 else 2 if tier==1 else 3 for row,tier in zip(rows,tiers,strict=True)],dtype=np.int8)
    for bi,name in enumerate(('主順行','主失速','旧T','局所')):
        checked+=compare_statistics(branch_reports[name],statistics(data,rows,widths,hi,branches==bi),('枝',name))
    for side,name in enumerate(('BUY','SELL')):
        mask=np.asarray([row[1]==side for row in rows],dtype=bool)
        checked+=compare_statistics(side_reports[name],statistics(data,rows,widths,hi,mask),('実側',name))
    return checked


def oracle_data(data: object,born: dict,candidate: dict) -> dict:
    """
    機能: 独立一覧oracleへ金融net/labelを除き時計だけを渡す。
    引数: data(SimpleNamespace)、born/candidate(dict)は出生と固定設定。
    返り値: dictは独立oracleの入力。exitは既知clockだけを参照する。
    """
    hi=data.meta['horizon_ids'].index(candidate['horizon']);widths={w:i for i,w in enumerate(data.meta['widths'])}
    def lookup(case: int,side: int,width: int) -> float|None:
        """
        機能: 取得後の将来カレンダーへ既知exit時計だけを置く。
        引数: case/side/width(int)は取得識別。
        返り値: float又はNoneは既知時計又は未知。
        """
        wi=widths[width]
        return float(data.arrays['exit_time'][case,side,wi,hi]) if data.arrays['known'][case,side,wi,hi] else None
    return {'event_keys':data.event_keys,'event_scenes':data.event_scenes,'scene_starts':np.asarray([s['start'] for s in data.scenes]),
            'scene_ends':np.asarray([s['end'] for s in data.scenes]),'captures':data.pure_captures,
            'core':born['core'],'branches':born['branches'],'technical':born['technical'],'tiers':born['tier'],
            'momentum_width':int(candidate['momentum_width']),'fade_width':int(candidate['fade_width']),
            'technical_width':int(candidate['integration'][1:]),'exit_lookup':lookup,'after_seconds':2700}


def main() -> None:
    """
    機能: 167全26政策と168旧73/追加7の全要求・取得・金融を独立に照合する。
    引数: なし。固定二案を保持し、169 Source/データへ一切触れない。
    返り値: None。範囲を明記した自然QAと主案明細を保存する。CSV JSONは変更しない。
    """
    sys.stdout.reconfigure(encoding='utf-8');begin=time.monotonic()
    book167=ROOT/'study/00167_固定した複合入口を追加七場へ適用する/条件.json'
    book168=ROOT/'study/00168_固定複合入口を片側十枚の数量枠で再生する/条件.json'
    assert sha(book167)=='73e16eabfc3364a9e038d9697472abe50bb91fbba49b488dd0c8ed8d5eaea9f4'
    assert sha(book168)=='b8acd5daf5050b16a0d36c74d207db8e60d77a817b6fb62964f08b416c8b1f89'
    paths=[Path(__file__),IO_PATH,LOCAL_PATH,ORACLE_PATH,book167,book168,
           P167/'適用基盤167.py',P167/'適用する.py',P167/'全出生/完了.json',P167/'全出生/固定二案の出生.npz',
           P167/'比較/完了.json',P167/'比較/全比較と全場.json',P167/'比較/全取得参照.json',P167/'比較/因果監査.json',
           P168/'engine168.py',P168/'再生する.py',P168/'追加七場を再生する.py',
           ROOT/'work/162複合入口候補/rules162.py',ROOT/'work/166自然独立確認/自然の独立確認.json',
           ROOT/'work/151過去場判別の評価/入口選択/cache/feature_only/features.npz',
           ROOT/'work/151過去場判別の評価/入口選択/cache/feature_only/features_meta.json',
           ROOT/'inputs/00148_全1分入口母集団/取得対応.json.gz',
           ROOT/'work/163任意幅の数値化/自然数値表/任意幅配列.npz',ROOT/'work/163任意幅の数値化/自然数値表/任意幅識別.json.gz',
           ROOT/'work/166可用指標の階層化/全出生/階層化の出生.npz',ROOT/'work/166可用指標の階層化/比較/主案と探索結果.json',
           NEW/'生成の完了.json',NEW/'入口母集団/完了.json',NEW/'入口母集団/当時特徴.json.gz',
           NEW/'入口母集団/取得対応.json.gz',NEW/'入口母集団/固定取得入力.json.gz',
           NEW/'自然数値表/任意幅配列.npz',NEW/'自然数値表/任意幅識別.json.gz']
    for folder in (P168/'旧73比較',P168/'追加7比較'):
        paths.extend(folder/name for name in ('完了.json','全取得参照.json','無制限取得参照.json','数量と要求の監査.json.gz','二案の数量比較.json'))
    before={p.relative_to(ROOT).as_posix():sha(p) for p in paths}
    setting=read(book167);quantity_setting=read(book168);assert setting['candidates']==quantity_setting['candidates']
    new=load_dataset(False);old=load_dataset(True)
    assert len(new.scenes)==7 and len(old.scenes)==73 and [s['session'] for s in new.scenes]==setting['scenes']
    library=module(ROOT/'work/162複合入口候補/rules162.py','catalog_only_for167_168');catalog={row['id']:row for row in library.candidate_catalog()}
    all_births={};birth_checks=0;selected_new={};new_audits={}
    previous=read(ROOT/'work/166可用指標の階層化/比較/主案と探索結果.json')
    with np.load(P167/'全出生/固定二案の出生.npz',allow_pickle=False) as sealed,\
         np.load(ROOT/'work/166可用指標の階層化/全出生/階層化の出生.npz',allow_pickle=False) as old_sealed:
        for candidate,old_name in zip(setting['candidates'],('事前固定主案','前48場だけで選択'),strict=True):
            for period,data in (('旧73',old),('追加7',new)):
                born=births(data,candidate,catalog);all_births[period,candidate['id']]=born
                if period=='追加7':
                    for name,value in born.items():assert np.array_equal(value,sealed[candidate['id']+'__'+name]),(period,candidate['id'],name);birth_checks+=value.size
                else:
                    pi,li,mi,fi,hi,ti=previous[old_name]['position']
                    for name,expected in (('core',old_sealed['directions'][pi]),('branches',old_sealed['branches'][pi]),
                                          ('technical',old_sealed['technical'][li,ti]),('tier',old_sealed['technical_tier'][li,ti]),
                                          ('oldtechnical',old_sealed['oldtechnical'][ti]),('local',old_sealed['local_directions'][li]),
                                          ('local_eligible',old_sealed['local_eligible'][li])):
                        assert np.array_equal(born[name],expected),(period,candidate['id'],name);birth_checks+=expected.size
            selected_new[candidate['id']]=independent_selection(new,all_births['追加7',candidate['id']],candidate)
    # ----------------------------------------
    # 167は固定二候補×枝幅/12同幅対照を全件、全分解まで確認する。
    reports=read(P167/'比較/全比較と全場.json')['results'];refs={row['id']:row for row in read(P167/'比較/全取得参照.json')['rows']}
    audits={row['id']:row['rows'] for row in read(P167/'比較/因果監査.json')['rows']};stat_cells=0
    assert len(reports)==26
    for candidate in setting['candidates']:
        rows,widths,tiers,expected_audits=selected_new[candidate['id']]
        reference_match(new,rows,widths,tiers,refs[candidate['id']]);assert expected_audits==audits[candidate['id']]
    for report in reports:
        candidate=report['candidate'];rows,widths,tiers,_=selected_new[candidate['id']]
        if report['width_control'] is not None:widths=np.full(len(rows),new.meta['widths'].index(report['width_control']),dtype=np.int8)
        branches={name:row['metrics'] for name,row in zip(('主順行','主失速','旧T','局所'),report['branches'],strict=True)}
        sides={name:row['metrics'] for name,row in zip(('BUY','SELL'),report['sides'],strict=True)}
        stat_cells+=audit_financial_parts(new,rows,widths,tiers,all_births['追加7',candidate['id']],candidate,
                                         report['metrics'],report['sessions'],report['bands'],branches,sides,'167')
    print(__import__('json').dumps({'167全政策':len(reports),'検算統計セル':stat_cells,'出生照合セル':birth_checks},ensure_ascii=False),flush=True)
    # ----------------------------------------
    # 全自然要求はheap engineとは別の一覧oracleへ渡す。net/labelをoracleに渡さない。
    oracle_runs=0;oracle_requests=0;oracle_records=0;same_second=0;quantity_details=[];quantity_stats=0
    for period,data,folder in (('旧73',old,P168/'旧73比較'),('追加7',new,P168/'追加7比較')):
        report=read(folder/'二案の数量比較.json');reference_cap={r['id']:r for r in read(folder/'全取得参照.json')['rows']}
        reference_unlimited={r['id']:r for r in read(folder/'無制限取得参照.json')['rows']}
        audit={(r['id'],r['mode']):r for r in read(folder/'数量と要求の監査.json.gz')['rows']}
        for entry in report['rows']:
            candidate=entry['candidate'];born=all_births[period,candidate['id']];oracle_input=oracle_data(data,born,candidate)
            for mode,capacity,reference in (('無制限',None,reference_unlimited[candidate['id']]),('cap10',10,reference_cap[candidate['id']])):
                result=quantity.oracle(oracle_input,capacity);oracle_runs+=1;oracle_requests+=len(result['requests']);oracle_records+=len(result['records'])
                expected=audit[candidate['id'],mode];assert result['requests']==expected['requests'],(period,candidate['id'],mode,'全要求')
                assert result['peaks']==[r['peak_reserved_total'] for r in expected['audits']],(period,candidate['id'],mode,'予約peak')
                rows=[(r['case'],r['side'],r['event'],r['origin']) for r in result['records']]
                widths=np.asarray([data.meta['widths'].index(r['width']) for r in result['records']],dtype=np.int8)
                tiers=[r['tier'] for r in result['records']];reference_match(data,rows,widths,tiers,reference)
                hi=data.meta['horizon_ids'].index(candidate['horizon']);request_scene=Counter();fill_scene=Counter();unknown_scene=Counter()
                for request in result['requests']:
                    if not request['accepted']:request_scene[request['scene_index'],request['origin'],request['side']]+=1
                    if capacity is not None:assert request['held_before']+request['pending_before']<=capacity
                for row,w in zip(rows,widths,strict=True):
                    si=int(data.arrays['session_index'][row[0]]);fill_scene[si]+=1
                    if not data.arrays['known'][row[0],row[1],w,hi]:unknown_scene[si]+=1
                    elif data.arrays['exit_time'][row[0],row[1],w,hi] in {key[0] for key in data.event_keys}:same_second+=1
                for si,a in enumerate(expected['audits']):
                    assert a['filled']==fill_scene[si] and a['unknown_held_to_end']==unknown_scene[si]
                    assert a['quantity_rejected_core']==sum(request_scene[si,0,side] for side in (0,1))
                    assert a['quantity_rejected_technical']==sum(request_scene[si,2,side] for side in (0,1))
                    assert a['quantity_rejected_by_side']==[request_scene[si,0,side]+request_scene[si,2,side] for side in (0,1)]
                    assert a['held_at_scene_end']==[0,0] and a['pending_at_scene_end']==[0,0]
                    if capacity is not None:
                        for key in ('peak_held','peak_pending','peak_reserved_total'):assert max(a[key])<=capacity
                actual=entry[mode];quantity_stats+=audit_financial_parts(data,rows,widths,tiers,born,candidate,actual['periods']['全期'],
                          actual['scenes'],actual['timebands'],actual['branches'],actual['sides'],'168')
                scene=np.asarray([data.arrays['session_index'][row[0]] for row in rows],dtype=np.int16)
                if period=='旧73':
                    for name,eligible in (('前48場',np.arange(73)<48),('後25場',np.arange(73)>=48)):
                        quantity_stats+=compare_statistics(actual['periods'][name],statistics(data,rows,widths,hi,eligible[scene],eligible),(period,candidate['id'],mode,name))
                assert actual['quantity_rejected_core']==sum(r['quantity_rejected_core'] for r in expected['audits'])
                assert actual['quantity_rejected_technical']==sum(r['quantity_rejected_technical'] for r in expected['audits'])
                for name in ('peak_reserved_total','peak_held','peak_pending'):
                    assert actual[name]==np.max([r[name] for r in expected['audits']],axis=0).tolist()
                quantity_details.append({'期間':period,'候補':candidate['id'],'mode':mode,'全期':actual['periods']['全期'],
                                         '要求数':len(result['requests']),'取得数':len(rows),'peak_reserved_total':result['peaks'],
                                         '金融未知で場末まで保有':sum(unknown_scene.values())})
    assert all(sha(ROOT/name)==digest for name,digest in before.items())
    save(HERE/'自然の独立確認.json',{'成功':True,'対象試行':[167,168],'入力とSource':before,
         '旧73と追加7の固定出生照合セル':birth_checks,'新旧とも出生式同体':True,
         '167全政策数':26,'167全分解統計検算セル':stat_cells,'167全取得と因果制御':True,
         '168独立一覧oracle再生数':oracle_runs,'168全要求照合数':oracle_requests,'168全取得照合数':oracle_records,
         '168全分解統計検算セル':quantity_stats,'168全cap政策数':4,'168無制限同体':True,
         '自然にq0とexit秒が一致した取得の延べ数':same_second,
         '未知の扱い':'known=Falseのnet格納0を収支へ加えず全収支はnull。数量は場末まで枠を保持。',
         '同秒の扱い':'exitのindex/lineは不明なので秒末に解放。全原行キーのq0/q1・pending/cancelをoracleで照合。',
         'oracleの金融入力':'exit_lookupはknown/exit_timeのみ。net/label/利益額を渡さない。',
         '全場と三帯分母':'取得0場を残し、全対象ザラバ時間を分母に計算。q0/q1帯を別照合。',
         'CSV_JSON変更':False,'169への読取又は成績共有':False,'元入力変更':False,
         '限界':'元NPZと固定出生からの全政策検算。新原板の全件を第二Raw parserで再走査した確認ではない。待ち行列/mini実約定保証ではない。',
         '経過秒':time.monotonic()-begin})
    save(HERE/'数量の自然全要求照合.json',{'成功':True,'rows':quantity_details,
         '注意':'取得・数量の再生と全統計は同体。未知を含む既知差引と全件収支を区別する。'})
    save(HERE/'自然確認の停止.json',{'成功':True,'SourceSHA256':sha(Path(__file__)),'自然QA票SHA256':sha(HERE/'自然の独立確認.json'),
         '数量全要求票SHA256':sha(HERE/'数量の自然全要求照合.json'),'元入力不変':True})
    print(__import__('json').dumps({'成功':True,'167政策':26,'独立oracle再生':oracle_runs,'全要求':oracle_requests,
          '全取得':oracle_records,'自然QA票SHA256':sha(HERE/'自然の独立確認.json')},ensure_ascii=False),flush=True)


if __name__=='__main__':
    main()
