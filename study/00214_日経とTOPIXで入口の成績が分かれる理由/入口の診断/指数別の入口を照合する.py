"""両指数の同じ公表分足と、注文時点までに見える相手の最新特徴を照合する。"""
from bisect import bisect_left
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path
from statistics import median
from tempfile import TemporaryDirectory
import gzip
import hashlib
import json
import sys
import zipfile

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
JST = timezone(timedelta(hours=9))
END = '2026-11-17_Day'
SOURCE = next((ROOT/'inputs').glob('00213_*'))
PRIOR = next((ROOT/'study').glob('00213_*'))
COLUMNS = ['m5_di_difference_to_side','m5_ema21_delta_to_side','m5_gap_to_side',
           'm5_rsi_delta_to_side','m5_hist_delta_to_side','m1_body_ratio_to_side',
           'm1_close_delta_atr5_to_side','m5_atr','m1_volume_relative_prior3',
           'q0_entry_minus_ema8_atr5_to_side']


# ----------------------------------------
def read(file: Path) -> dict:
    """
    機能：固定JSONまたは圧縮JSONを読む。
    引数：file（Path）は入力先。
    返り値：dictは読み込んだ値。
    """
    with (gzip.open(file,'rb') if file.suffix=='.gz' else file.open('rb')) as f:
        return json.load(f)


# ----------------------------------------
def digest(file: Path) -> str:
    """
    機能：入力の物理指紋を確認する。
    引数：file（Path）は入力先。
    返り値：strはSHA256。
    """
    with file.open('rb') as f:
        return hashlib.file_digest(f,'sha256').hexdigest()


# ----------------------------------------
def restore_rules(folder: Path) -> object:
    """
    機能：213の固定資料からLC複合条件の実装を隔離復元する。
    引数：folder（Path）は一時作業先。
    返り値：moduleは179の固定条件。
    """
    with zipfile.ZipFile(SOURCE/'再現Source.zip') as archive:
        for name in archive.namelist():
            if name.endswith('.py') and name.startswith('work/'):
                archive.extract(name,folder)
    sys.path.insert(0,str(folder/'work/179量と構造の純入口'))
    import rules179
    return rules179


# ----------------------------------------
def pure_columns(archive: Path, end: str, tag: str) -> dict:
    """
    機能：既存の固定日経純入口から使用候補の方向とLC印を得る。
    引数：archive（Path）はZIP、end/tag（str）はファイル名末尾と候補名。
    返り値：dictは主入口方向・LC印。
    """
    with zipfile.ZipFile(archive) as z:
        path, = [p for p in z.namelist() if p.endswith(end)]
        with np.load(BytesIO(z.read(path)),allow_pickle=False) as a:
            return {'core':a[tag+'__birth__core'], 'added':a[tag+'__added']}


# ----------------------------------------
def datasets() -> tuple:
    """
    機能：旧42日の日経と呼値換算TOPIXの純方向と、対応する当時100特徴を指定する。
    引数：なし。
    返り値：tupleは指数別の入力群と実取得。
    """
    n195 = next((ROOT/'study').glob('00195_*'))
    n199 = next((ROOT/'study').glob('00199_*'))
    specs = [('旧73','00148*/当時特徴.json.gz'),('追加7','00167*/入口母集団/当時特徴.json.gz'),
             ('本日1','00180*/入口母集団/当時特徴.json.gz'),('追加2','00194*/NK225/入口母集団/当時特徴.json.gz')]
    src = []
    trades = []
    for folder in (n199/'保存金融',n199/'追加二場/保存金融'):
        ledger = read(next(folder.glob('*02__C0_IFD.json.gz')))['ledger']
        trades.extend({k:v[i] for k,v in ledger.items()} for i,s in enumerate(ledger['scene']) if s.endswith('_Day'))
    for leg, pattern in specs:
        cols = (pure_columns(n199/'追加二場/純入口.zip','追加二場純出生.npz','E199_02') if leg=='追加2'
                else pure_columns(n195/'純入口.zip',leg+'_新入口.npz','E195_05'))
        src.append((next((ROOT/'inputs').glob(pattern)),cols,{t['event']:t for t in trades if t['leg']==leg}))
    # ----------------------------------------
    topo = read(next((PRIOR/'金融正本').glob('*03*.json.gz')))['取得']
    fields = read(SOURCE/'候補列.json')['呼値純入口']
    with np.load(SOURCE/'全純入口.npz',allow_pickle=False) as a:
        tp = {k:a[fields[k]] for k in ('core','added','time','line')}
    index = {tuple(k):i for i,k in enumerate(zip(tp['time'],tp['line'],strict=True))}
    mapping = {index[(t['request_time'],t['request_line'])]:t for t in topo if t['scene']<=END}
    return src, [(ROOT/'work/今回移植/呼値換算/母集団/当時特徴.json.gz',tp,mapping)]


# ----------------------------------------
def source_rows(file: Path, pure: dict, trades: dict, rule_module: object) -> list:
    """
    機能：公表分足の終了時刻、主方向、LC全要件の成立/既知と実際の取得を接続する。
    引数：file（Path）、pure/trades（dict）、rule_module（module）は元の179。
    返り値：listは場・分足・価格原行順の判断レコード。
    """
    part = read(file)
    names = [c['name'] for c in part['catalog']]
    original = part.pop('rows')
    assert len(original)==len(pure['core'])
    scenes = list(dict.fromkeys(r['session'] for r in original))
    scene_idx = {s:i for i,s in enumerate(scenes)}
    starts = []
    for s in scenes:
        day = s.endswith('_Day')
        midnight = datetime.fromisoformat(s[:10]).replace(tzinfo=JST)
        starts.append((midnight+timedelta(hours=8,minutes=45) if day else midnight+timedelta(hours=17)).timestamp())
    meta = []
    bars, lines = [], []
    for row in original:
        q = row['metadata']['q0']
        meta.append({'session':row['session'],'session_index':scene_idx[row['session']],'contract':row['contract'],
                     'event_id':row['event_id'],'q0_time':q['time'],'q0_index':q['index'],'q0_line':q['source_line']})
        latest = row['metadata']['short_refs'][-1]
        bars.append(latest['end'])
        lines.append(q['source_line'])
        assert latest['session']==row['session'] and latest['available_at']<=q['time']
    sides = [np.array([r[side]['x'] for r in original],dtype=float) for side in ('buy','sell')]
    del original,part
    if 'line' in pure:
        np.testing.assert_array_equal(pure['line'],lines)
        np.testing.assert_array_equal(pure['time'],[m['q0_time'] for m in meta])
    # ----------------------------------------
    inputs = {'columns':names,'q0_meta':meta,'buy_X':sides[0],'sell_X':sides[1]}
    evaluator = rule_module.Evaluator179(inputs,starts)
    rule, = [r for r in rule_module.candidate_catalog() if r['id']=='VLC0003_EDGE']
    local = evaluator.evaluate_one(rule)
    condition_names = list(dict.fromkeys(t['factor'] for t in rule['conditions']))
    checks = {}
    for side in (0,1):
        for factor in condition_names:
            parts = [evaluator.comparison(side,t) for t in rule['conditions'] if t['factor']==factor]
            passed = np.logical_and.reduce([p for p,k in parts])
            known = np.logical_and.reduce([k for p,k in parts])
            checks[side,factor] = np.where(known,passed.astype(np.int8),-1)
        whole = np.logical_and.reduce([checks[side,f]==1 for f in condition_names])
        np.testing.assert_array_equal(whole,local[('buy_pass','sell_pass')[side]])
    rows = []
    for i,m in enumerate(meta):
        session=m['session']
        if not session.endswith('_Day') or session>END:
            continue
        core, added = int(pure['core'][i]),bool(pure['added'][i])
        if added:
            assert core==int(local['directions'][i]) and core!=0
        q = {'session':session,'time':m['q0_time'],'bar':int(bars[i]),'core':core,'added':added,
             'lc':int(local['directions'][i]),'passed':{},'features':{},'trade':trades.get(i)}
        for side, sign in enumerate((1,-1)):
            q['passed'][sign] = {f:int(checks[side,f][i]) for f in condition_names}
            vals = [float(sides[side][i,names.index(k)]) for k in COLUMNS]
            q['features'][sign] = {k:v if np.isfinite(v) else None for k,v in zip(COLUMNS,vals,strict=True)}
        if q['trade'] is not None:
            t=q['trade']
            sign=1 if t['side']==0 else -1
            assert t['scene']==session and t['added']==added and (t['origin']==2 or core==sign)
            assert m['q0_time']<=t['entry_time'] and m['q0_line']<t['entry_line']
        rows.append(q)
    return rows


# ----------------------------------------
def morning(at: float) -> bool:
    """
    機能：現物休場日を含む09:00より前の価格時計を判定する。
    引数：at（float）はUNIX秒。
    返り値：boolは日本時間09:00未満。
    """
    return datetime.fromtimestamp(at,JST).hour < 9


# ----------------------------------------
def compare_signals(left: list, right: list) -> dict:
    """
    機能：同じ1分足終了時刻で両指数の主入口とLCを対比する。
    引数：left/right（list）は日経とTOPIXの固定判断。
    返り値：dictは双方の公表可否と方向のクロス表。
    """
    maps = [{(r['session'],r['bar']):r for r in rows} for rows in (left,right)]
    assert len(maps[0])==len(left) and len(maps[1])==len(right)
    matched = set(maps[0])&set(maps[1])
    union = set(maps[0])|set(maps[1])
    result = {}
    for title,before in [('全体',False),('朝',True)]:
        use = sorted(k for k in union if not before or morning(k[1]+60))
        both = [k for k in use if k in matched]
        members = {}
        for kind in ('主入口','LC'):
            count=Counter()
            for key in both:
                a,b=[m[key] for m in maps]
                x,y=(a['core'],b['core']) if kind=='主入口' else (a['core'] if a['added'] else 0,b['core'] if b['added'] else 0)
                label = ('なし' if x==0 and y==0 else '日経のみ' if y==0 else 'TOPIXのみ' if x==0 else
                         '同方向' if x==y else '逆方向')
                count[label]+=1
            members[kind]=dict(count)
        result[title]={'共通判断':len(both),'日経だけ判断可':sum(k not in maps[1] for k in use),
                      'TOPIXだけ判断可':sum(k not in maps[0] for k in use),**members}
    return result


# ----------------------------------------
def group_result(rows: list) -> dict:
    """
    機能：既存取得群の件数・勝敗・収支を取得時計の変更なしで計算する。
    引数：rows（list）は対象LC取引。
    返り値：dictは群内の既知成績。
    """
    assert all(r['収支'] is not None for r in rows)
    return {'件数':len(rows),'勝ち':sum(r['収支']>0 for r in rows),
            '負け':sum(r['収支']<0 for r in rows),'収支':round(sum(r['収支'] for r in rows),2)}


# ----------------------------------------
def diagnose(rows: list, other: list, use_asof: bool, price_scale: float) -> tuple:
    """
    機能：実際のLC取得について、同じ足、または厳密に過去の相手判断でLC各条件を分解する。
    引数：rows/other（list）は自指数と相手の固定判断、use_asof（bool）は過去のみの選択、price_scale（float）は日経表記への換算。
    返り値：tupleは全群の集計とLC取得ごとの理由。
    """
    mapping = {(r['session'],r['bar']):r for r in other}
    times,order = defaultdict(list),defaultdict(list)
    for r in other:
        times[r['session']].append(r['time'])
        order[r['session']].append(r)
    examples = []
    for r in rows:
        t=r['trade']
        if not t or not r['added']:
            continue
        side=r['core']
        if use_asof:
            ix=bisect_left(times[r['session']],r['time'])-1
            peer=order[r['session']][ix] if ix>=0 else None
            if peer and r['time']-peer['time']>90:
                peer=None
        else:
            peer=mapping.get((r['session'],r['bar']))
        result={'場':r['session'],'時計':int(r['time']),'足の終了':r['bar'],'取得':t['entry_time'],'側':side,
                '収支':t['net'],'先着':t['label'],'朝':morning(t['entry_time']),
                '取得価格':t['entry_price'],'決済時刻':t['exit_time'],'決済価格':t['exit_price'],
                '対象幅対ATR5':t['width']*price_scale/r['features'][side]['m5_atr'],
                '自特徴':r['features'][side],'相手判断':None}
        if peer:
            flags=peer['passed'][side]
            result['相手判断']={'時計':peer['time'],'足の終了':peer['bar'],'主':peer['core'],'元LC方向':peer['lc'],
                'LC':peer['core'] if peer['added'] else 0,'既知不成立':[k for k,v in flags.items() if v==0],
                '不明':[k for k,v in flags.items() if v<0],'全要件成立':all(v==1 for v in flags.values()),
                '方向付き特徴':peer['features'][side]}
        examples.append(result)
    buckets={}
    for key,subset in [('全LC',examples),('朝LC',[v for v in examples if v['朝']]),
                       ('九時以後LC',[v for v in examples if not v['朝']])]:
        known=[v for v in subset if v['相手判断'] is not None]
        ranks=Counter(k for v in known for k in v['相手判断']['既知不成立'])
        missing=Counter(k for v in known for k in v['相手判断']['不明'])
        key_flags=Counter()
        for v in known:
            o=v['相手判断']; key_flags['自方向の全要件成立']+=int(o['全要件成立'])
            key_flags['新発火も同方向']+=int(o['元LC方向']==v['側'])
            key_flags['主入口が同方向']+=int(o['主']==v['側'])
            key_flags['主入口が逆方向']+=int(o['主']==-v['側'])
        feat={}
        for col in COLUMNS:
            comparison={}
            for k, vals in [('自', [v['自特徴'][col] for v in subset]),
                            ('相手',[v['相手判断']['方向付き特徴'][col] for v in known])]:
                arr=[v for v in vals if v is not None]
                comparison[k]={'既知':len(arr),'正':sum(a>0 for a in arr),'中央値':median(arr) if arr else None}
            feat[col]=comparison
        votes=defaultdict(list)
        positions={k:[] for k in ('上限超過','範囲内','下限割れ','算出不能','相手判断なし')}
        for v in subset:
            src=v['自特徴']
            macd=src['m5_hist_delta_to_side']>0
            rsi=src['m5_rsi_delta_to_side']>0
            assert macd or rsi
            votes['両方' if macd and rsi else 'MACDだけ' if macd else 'RSIだけ'].append(v)
            peer=v['相手判断']
            if peer is None:
                positions['相手判断なし'].append(v)
            else:
                distance=peer['方向付き特徴']['q0_entry_minus_ema8_atr5_to_side']
                bin_name=('算出不能' if distance is None else '上限超過' if distance>1.5
                          else '下限割れ' if distance < -2 else '範囲内')
                positions[bin_name].append(v)
        buckets[key]={'取得':len(subset),'相手判断あり':len(known),'判明収支':round(sum(v['収支'] for v in subset),2),
            '自指数の幅対5分ATR中央値':median(v['対象幅対ATR5'] for v in subset),
            '相手判定':dict(key_flags),'相手の既知不成立':dict(ranks.most_common()),'相手の未知':dict(missing.most_common()),
            '方向付き特徴':feat,'売買別':{name:group_result([v for v in subset if v['側']==sign])
                    for name,sign in [('買い',1),('売り',-1)]},
            '当時の5分動力':{k:group_result(v) for k,v in votes.items()},
            '相手価格のEMA8からの位置':{k:group_result(v) for k,v in positions.items()}}
    return buckets,examples


# ----------------------------------------
def main() -> None:
    """
    機能：二つの指数の固定入口を読んで、同一足・過去向きの診断と検査票を保存する。
    引数：なし。
    返り値：None。旧期の取得と朝の収支を213の原簿に照合する。
    """
    groups = datasets()
    all_rows = []
    fingerprints={}
    with TemporaryDirectory() as tmp:
        rules=restore_rules(Path(tmp))
        for sources in groups:
            rows=[]
            for file,pure,trades in sources:
                rows.extend(source_rows(file,pure,trades,rules))
                fingerprints[file.relative_to(ROOT).as_posix()]=digest(file)
            all_rows.append(rows)
    nk,tp=all_rows
    assert len({r['session'] for r in nk})==len({r['session'] for r in tp})==42
    assert [sum(bool(r['trade']) for r in rows) for rows in all_rows]==[162,135]
    summary={'対象場数':42,'同じ完了足':compare_signals(nk,tp),'特徴入力指紋':fingerprints}
    details={}
    for symbol,rows,other in [('日経',nk,tp),('TOPIX',tp,nk)]:
        for label,asof in [('同じ足',False),('直前90秒',True)]:
            summary[symbol+label],details[symbol+label]=diagnose(rows,other,asof,1 if symbol=='日経' else 20)
        old=summary[symbol+'同じ足']['全LC']
        assert (old['取得'],old['判明収支']) == ((23,440229) if symbol=='日経' else (25,-102090))
    for file,body in [('集計.json',summary),('LCの照合明細.json.gz',details)]:
        raw=(json.dumps(body,ensure_ascii=False,indent=1,allow_nan=False)+'\n').encode()
        (HERE/file).write_bytes(gzip.compress(raw,mtime=0) if file.endswith('.gz') else raw)


if __name__=='__main__':
    main()
