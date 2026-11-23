"""日経デイの事前に定めた入口候補を、取得予約から終了15分前まで再生する。"""
import gzip
import csv
from datetime import datetime
import hashlib
from io import BytesIO
import json
from pathlib import Path
import runpy
from types import SimpleNamespace
from zipfile import ZipFile

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
WORK = ROOT/'work/217日経'
STUDY = ROOT/'study'
INPUT = ROOT/'inputs'
OLD = next(STUDY.glob('00199_*'))
DIRECT = ROOT/'work/216日経'
FINANCE = runpy.run_path(str(next(STUDY.glob('00213_*/金融再生.py'))))
SUMMARY = runpy.run_path(str(next(STUDY.glob('00216_*/全場を集計する.py'))))
COMPACT = runpy.run_path(str(ROOT/'work/今回移植/純入口を作る.py'))['compact']


# ----------------------------------------
def read(path: Path) -> dict:
    """
    機能：正本の通常または圧縮JSONを読み込む。
    引数：path（Path）は資料のパス。
    返り値：dictは展開後の内容。
    """
    with (gzip.open(path, 'rb') if path.suffix == '.gz' else path.open('rb')) as file:
        return json.load(file)


def parts() -> list:
    """
    機能：時系列順に旧73・追加7・1・2場・直近3デイの資料を指定する。
    引数：なし。
    返り値：listは特徴量、純入口、原板索引の組。
    """
    archive = OLD/'純入口.zip'
    return [
        (next(INPUT.glob('00148_*')), archive, '旧73_新入口.npz', next(INPUT.glob('00163*/価格索引/manifest.json'))),
        (next(INPUT.glob('00167*/入口母集団')), archive, '追加7_新入口.npz', next(INPUT.glob('00167*/原板数値索引/manifest.json'))),
        (next(INPUT.glob('00180*/入口母集団')), archive, '本日1_新入口.npz', next(INPUT.glob('00180*/原板数値索引/manifest.json'))),
        (next(INPUT.glob('00194*/NK225/入口母集団')), OLD/'追加二場/純入口.zip', '追加二場純出生.npz',
         next(INPUT.glob('00194*/NK225/原板数値索引/manifest.json'))),
        (DIRECT/'母集団', DIRECT/'純入口.npz', '', DIRECT/'前史十場と追加二場の索引参照.json'),
    ]


# ----------------------------------------
def inputs(folder: Path, archive: Path, member: str) -> tuple:
    """
    機能：全q0を当時特徴と照合し、判断・予約・当時の価格時計を揃える。
    引数：folder/archive（Path）は特徴群と純入口、member（str）は圧縮内のファイル名。
    返り値：tupleは場定義、純入力、実側特徴配列と列名。
    """
    scenes = read(folder/'固定取得入力.json.gz')['scenes']
    number = {s['session']:i for i,s in enumerate(scenes)}
    raw = read(folder/'当時特徴.json.gz')
    assert raw['financial_labels_used'] is False
    columns = [c['name'] for c in raw['catalog']]
    rows = raw['rows']
    values = {side:np.array([r[side]['x'] for r in rows], dtype=float) for side in ('buy','sell')}
    meta = []
    refs_by_scene = {}
    for row in rows:
        q = row['metadata']['q0']
        refs = row['metadata']['short_refs']
        assert refs[-1]['session'] == row['session'] and refs[-1]['available_at'] <= q['time']
        if row['session'].endswith('_Day'):
            arrived = refs_by_scene.setdefault(row['session'],{})
            for ref in refs:
                if ref['session'] != row['session'] or not ref['closed']:
                    continue
                stamp = (q['time'],q['index'],q['source_line'])
                assert ref['available_at']<=q['time'] and ref['contract']==row['contract']
                if ref['start'] not in arrived:
                    arrived[ref['start']] = (stamp,ref)
        meta.append(dict(event_id=row['event_id'], session_index=number[row['session']],
                         q0_index=q['index'], q0_line=q['source_line'], q0_time=q['time']))
    del raw, rows
    if member:
        clocks = COMPACT(SimpleNamespace(q0_meta=meta), read(folder/'取得対応.json.gz')['rows'])
        with ZipFile(archive) as z:
            name, = [n for n in z.namelist() if n.endswith(member)]
            with np.load(BytesIO(z.read(name)), allow_pickle=False) as a:
                fields = ('core','branches','technical','tier')
                for key in (*fields,'added','mw','fw','hi'):
                    clocks[key] = a['E199_02__' + ('birth__' if key in fields else '') + key]
    else:
        with np.load(archive, allow_pickle=False) as a:
            clocks = dict(a)
        np.testing.assert_array_equal(clocks['time'], [m['q0_time'] for m in meta])
        np.testing.assert_array_equal(clocks['line'], [m['q0_line'] for m in meta])
    assert all(len(v)==len(meta) for v in clocks.values())
    return scenes, clocks, values, columns, refs_by_scene


# ----------------------------------------
def conditions(features: np.ndarray, columns: list, elapsed: np.ndarray) -> list:
    """
    機能：買い又は売りを基準とした当時特徴から、見送り10案と補完2案の成立印を作る。
    引数：features（np.ndarray）は実側の特徴行列、columns（list）は列名、elapsed（np.ndarray）は開始後秒。
    返り値：list[np.ndarray]は条件ID順の見送り又は追加印。NaN比較は偽になる。
    """
    x = dict(zip(columns, features.T, strict=True))
    volume = x['m1_volume_relative_prior3']
    hist = x['m5_hist_delta_to_side']
    rsi = x['m5_rsi_delta_to_side']
    di = x['m5_di_difference_to_side']
    body = x['m1_body_ratio_to_side']
    medium = x['m15_ema21_delta_to_side']
    long = x['m30_ema21_delta_to_side']
    return [
        np.zeros(len(elapsed),dtype=bool),
        (medium<0) & (long<0) & (hist<=0),
        (x['q0_entry_minus_ema8_atr5_to_side']>1.5) & (rsi<=0) & (volume<1),
        (di<0) & (volume<0.8),
        (x['m1_forward_wick_ratio']>0.5) & (rsi<=0),
        (x['m15_adx']<20) & (x['m5_tr_previous_atr_ratio']<0.8),
        (x['q0_entry_minus_bbmean_sigma_to_side']>2) & (volume>=1) & (hist<=0),
        (elapsed>=900) & (elapsed<1800) & (di<0) & (body<0),
        x['q0_spread_points']>0.2*x['m5_atr'],
        (x['m5_ema8_delta_to_side']<0) & (x['m15_ema8_delta_to_side']<0) & (x['m1_close_position_to_side']<=0.5),
        (volume>=1.5) & (body < -0.25) & (di<=0),
        (x['m5_ema21_delta_to_side']>0) & (medium>0) & (long>0) & (di>=10) &
            (x['q0_last_minus_prior3_forward_edge_atr5_to_side']>0) & (volume>=1.25),
        (x['m15_price_ema21_atr_to_side'] < -1) & (body>0.5) & (rsi>0) & (hist>0) & (volume>=1.25),
    ]


def change(base: dict, rule: int, buy: np.ndarray, sell: np.ndarray) -> dict:
    """
    機能：固定主入口と補完の実売買方向に条件を掛け、同一判断内の見送りの迂回を防ぐ。
    引数：base（dict）は結合済み原条件、rule（int）は候補ID、buy/sell（np.ndarray）は当該条件印。
    返り値：dictは当時情報だけで更新した純入口。
    """
    result = dict(base)
    core = base['core']
    if rule not in (11,12):
        rejected = ((core==1)&buy) | ((core==-1)&sell)
        technical = base['technical']
        blocked = rejected | ((technical==1)&buy) | ((technical==-1)&sell)
        result.update(core=np.where(rejected,0,core), branches=np.where(rejected,-1,base['branches']),
                      technical=np.where(blocked,0,technical), added=base['added'] & ~rejected)
    else:
        direction = buy.astype(np.int8)-sell.astype(np.int8)
        extra = (core==0) & (direction!=0)
        result.update(core=np.where(extra,direction,core), branches=np.where(extra,0,base['branches']),
                      mw=np.where(extra,200,base['mw']), hi=np.where(extra,1,base['hi']))
    return result


# ----------------------------------------
def market_shape(scene: str, clocks: dict, arrived: dict) -> dict:
    """
    機能：原CSVの1分足から判断時点までに参照済みの連続13本を照合して要約する。
    引数：scene（str）は対象セッション、clocks（dict）は判断原行、arrived（dict）は参照済み足の最初の判断原行。
    返り値：dictは方向効率、終値と重心の差、終値の値幅内位置、重心をまたいだ回数。
    """
    path = ROOT.parent/'JP_OSE_Data/future/NK225'/scene/'candle_1min.csv'
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    with path.open(encoding='utf-8-sig',newline='') as stream:
        bars = {int(datetime.fromisoformat(r['time']).timestamp()):r for r in csv.DictReader(stream)}
    valid = {}
    for at,(key,ref) in arrived.items():
        assert ref['id']==f'csv1m:{sha}:{at}'
        if not ref['price_known'] or not ref['volume_known']:
            continue
        bar = bars[at]
        assert bar['closed']=='true' and bar['volume_complete']=='true'
        valid[at] = (key, [float(bar[k]) for k in ('high','low','close','volume')])
    recorded = sorted(arrived, key=lambda at:arrived[at][0])
    last = None
    pointer = 0
    values = np.full((len(clocks['time']),4),np.nan)
    for i,key in enumerate(zip(clocks['time'],clocks['index'],clocks['line'],strict=True)):
        while pointer<len(recorded) and arrived[recorded[pointer]][0]<=key:
            latest = recorded[pointer]
            last = latest if last is None else max(last,latest)
            pointer += 1
        if last is None:
            continue
        times = range(last-720,last+60,60)
        if any(t not in valid or valid[t][0]>key for t in times):
            continue
        high,low,close,volume = np.array([valid[t][1] for t in times]).T
        steps = sum(abs(np.diff(close)))
        width = max(high)-min(low)
        if not steps or not width or not sum(volume):
            continue
        center = np.average((high+low+close)/3,weights=volume)
        direction = np.sign(close-center)
        distinct = direction[direction!=0]
        values[i] = ((close[-1]-close[0])/steps,close[-1]-center,(close[-1]-min(low))/width,
                     np.count_nonzero(distinct[1:]!=distinct[:-1]))
    return dict(zip(('効率','重心乖離','位置','往復'),values.T,strict=True))


def followup(features: np.ndarray, columns: list, market: dict, sign: int) -> list:
    """
    機能：利得日に依存した差があった初回後に、構造仮説5案と量閾値の感度2案を計算する。
    引数：features（np.ndarray）とcolumns（list）は当時特徴、market（dict）は直近の価格履歴要約、sign（int）は売買符号。
    返り値：listは二次比較の見送り判定。
    """
    x = dict(zip(columns,features.T,strict=True))
    volume = x['m1_volume_relative_prior3']
    body = x['m1_body_ratio_to_side']
    di = x['m5_di_difference_to_side']
    hist = x['m5_hist_delta_to_side']
    rsi = x['m5_rsi_delta_to_side']
    location = market['位置'] if sign==1 else 1-market['位置']
    return [
        (abs(market['効率'])<=0.25) & (location>=0.75) & (rsi<=0),
        (sign*market['効率'] < -0.4) & (sign*market['重心乖離']<0) & (rsi<=0),
        (sign*market['重心乖離']>x['m5_atr']) & (volume<1) & (hist<=0),
        (location>=0.75) & (volume>=1.25) & (body<0) & (rsi<=0),
        (market['往復']>=3) & (di<=0) & (hist<=0),
        (volume>=1.25) & (body < -0.25) & (di<=0),
        (volume>=1.75) & (body < -0.25) & (di<=0),
    ]


# ----------------------------------------
def replacement(base: list, new: list, clocks: dict, buy: np.ndarray, sell: np.ndarray) -> list:
    """
    機能：旧と新の同側・同原行建玉を照合し、旧にのみある建玉のうち見送り条件が成立したものを特定する。
    引数：base/new（list）は二口座の取得、clocks（dict）は当時の判断、buy/sell（np.ndarray）は条件成立印。
    返り値：listは入れ替わった建玉と変更理由。
    """
    keys = {(time,line):i for i,(time,line) in enumerate(zip(clocks['time'],clocks['line'],strict=True))}
    maps = [{(t['entry_line'],t['side']):t for t in group} for group in (base,new)]
    for key in maps[0].keys()&maps[1].keys():
        assert maps[0][key]['net']==maps[1][key]['net']
    result = []
    for source,other,title in [(maps[0],maps[1],'旧'),(maps[1],maps[0],'新')]:
        for key,trade in source.items():
            if key in other:
                continue
            event = keys[trade['request_time'],trade['request_line']]
            reject = (buy,sell)[trade['side']][event]
            if title=='新':
                assert not reject
            reason = '直接見送り' if reject else ('枠交代で旧から外れた' if title=='旧' else '新しく取得')
            result.append(dict(理由=reason,場=trade['scene'],取得秒=trade['entry_time'],
                               売買=('買','売')[trade['side']],費用後収支=trade['net']))
    return result


def main() -> None:
    """
    機能：原行決済、固定対照一致、前24場選択、後21場評価を再現する。
    引数：なし。216の直近3デイの再生成済み当時特徴も使用する。
    返り値：None。全候補の元帳をworkへ、前24場選択をこの試行へ出力する。
    """
    dates, books, _ = SUMMARY['sources']('デイ')
    old = next(v for k,v in books.items() if '199' in k)
    ledgers = {f'NK{i:02d}':[] for i in range(20)}
    changes = {k:[] for k in ('NK04','NK10','NK14')}
    used = set()
    for folder, archive, member, manifest in parts():
        scenes, arrays, values, columns, refs = inputs(folder,archive,member)
        entries = {s['session']:s for s in read(manifest)['scenes']}
        for si,scene in enumerate(scenes):
            day = scene['session']
            if day not in dates or day in used:
                continue
            used.add(day)
            active = arrays['scene']==si
            a = {k:v[active] for k,v in arrays.items()}
            elapsed = a['time']-scene['start']
            market = market_shape(day,a,refs[day])
            buy,sell = [conditions(values[key][active],columns,elapsed)+followup(values[key][active],columns,market,sign)
                        for key,sign in (('buy',1),('sell',-1))]
            index = FINANCE['load_scene'](manifest.parent,entries[day])
            for i, name in enumerate(ledgers):
                variant = change(a,i,buy[i],sell[i])
                trades, _ = FINANCE['account'](variant,si,scene,index,1.0,'NK225')
                ledgers[name].extend(trades)
                if i==0:
                    original = trades
                if name in changes:
                    changes[name].extend(replacement(original,trades,a,buy[i],sell[i]))
        print('完了',folder.name,len(used),flush=True)
    # ----------------------------------------
    assert used==set(dates)
    fields = ('scene','side','entry_time','entry_line','exit_time','exit_line','net','label')
    expected = [[t[k] for k in fields] for t in old]
    assert [[t[k] for k in fields] for t in ledgers['NK00']]==expected
    WORK.mkdir(exist_ok=True,parents=True)
    (WORK/'比較元帳.json').write_text(json.dumps(ledgers,ensure_ascii=False,allow_nan=False),encoding='utf-8')
    # ----------------------------------------
    scores = {}
    counts = sum(t['scene'] in dates[:24] for t in old)
    for name,ledger in ledgers.items():
        if int(name[2:])>12:
            continue
        daily, stats = SUMMARY['calculate'](dates[:24],ledger,'全体')
        eligible = (stats['参加場']==24 and stats['保有率']>=0.2 and stats['取得']>=counts*0.75
                    and min(stats['建玉中央値下限'],stats['場中央値下限'])>0)
        worst = sum(sorted(r['収支'] for r in daily)[:3])
        scores[name] = dict(適格=eligible,赤字場=stats['赤字場'],最悪三場計=worst,損失=stats['損失'],取得=stats['取得'])
    chosen = min((k for k,v in scores.items() if v['適格']),
                 key=lambda k:(scores[k]['赤字場'],-scores[k]['最悪三場計'],scores[k]['損失'],k))
    above = {'前24場のみで選択':chosen,'前24場末日':dates[23],'前24場の比較':scores}
    (HERE/'前半の選択.json').write_text(json.dumps(above,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    diagnoses = {}
    for name,changed in changes.items():
        groups = {}
        for row in changed:
            result = groups.setdefault(row['理由'],{'件数':0,'既知収支':0,'未知':0})
            result['件数'] += 1
            if row['費用後収支'] is None:
                result['未知'] += 1
            else:
                result['既知収支'] += row['費用後収支']
        diagnoses[name] = {'全45場の入替':groups,'指定二日':[r for r in changed if r['場'][:10] in ('2026-10-20','2026-11-19')]}
    (HERE/'建玉の入れ替わり.json').write_text(json.dumps(diagnoses,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('前半選択',chosen,flush=True)


if __name__=='__main__':
    main()
