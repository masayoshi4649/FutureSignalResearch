"""199_02の実取得と同期対照を、元の物理行の仲値・気配差・数量へ分解する。"""
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import mean, median
import csv
import gzip
import hashlib
import json
import math

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
DATA = ROOT.parent / 'JP_OSE_Data' / 'future'
JST = timezone(timedelta(hours=9))
NIKKEI = 'NK225'
TOPIX = 'TOPIX'
SYMBOLS = (NIKKEI, TOPIX)
MULTIPLIERS = {NIKKEI:100, TOPIX:1000}
FEES = {NIKKEI:77, TOPIX:83.6}
SLIPPAGE = {NIKKEI:1000, TOPIX:500}
TICKS = {NIKKEI:5, TOPIX:0.25}


# ----------------------------------------
def read(path: Path) -> object:
    """
    機能：JSONまたはgzip JSONを展開する。
    引数：path（Path）は元帳・台帳。
    返り値：objectはデコードした記録。
    """
    buf = path.read_bytes()
    return json.loads(gzip.decompress(buf) if path.suffix=='.gz' else buf)


# ----------------------------------------
def sha(path: Path) -> str:
    """
    機能：入力の内容指紋を得る。
    引数：path（Path）は物理ファイル。
    返り値：strはSHA256。
    """
    with path.open('rb') as file:
        return hashlib.file_digest(file, 'sha256').hexdigest()


# ----------------------------------------
def sources() -> tuple:
    """
    機能：対象の旧42デイと同期対照を固定台帳から取り出す。
    引数：なし。
    返り値：tupleは元帳・同期観測・原板指紋・使用した正式資源。
    """
    prior = next((ROOT/'study').glob('00213_*'))
    original = next((ROOT/'study').glob('00199_*'))
    nk_paths = [next(folder.glob('*02__C0_IFD.json.gz')) for folder in
                (original/'保存金融',original/'追加二場/保存金融')]
    tp_path = next((prior/'金融正本').glob('*03*.gz'))
    pair_path = prior/'同期照合の明細.json.gz'
    ledger = {NIKKEI:[], TOPIX:[t for t in read(tp_path)['取得'] if t['scene']<='2026-11-17_Day']}
    for path in nk_paths:
        data = read(path)['ledger']
        ledger[NIKKEI].extend({k:v[i] for k,v in data.items()} for i,s in enumerate(data['scene']) if s.endswith('_Day'))
    assert [len(ledger[s]) for s in SYMBOLS] == [162,135]
    manifest_paths = [next((ROOT/'inputs').glob(pattern)) for pattern in
                      ('00163*/価格索引/manifest.json','00167*/原板数値索引/manifest.json',
                       '00180*/原板数値索引/manifest.json','00194*/NK225/原板数値索引/manifest.json')]
    tp_manifest = next((ROOT/'inputs').glob('00213*/原板と分足の指紋.json'))
    raw_refs = {(NIKKEI,r['session']):r['raw'] for path in manifest_paths for r in read(path)['scenes']}
    raw_refs.update({(TOPIX,r['場']):r['raw'] for r in read(tp_manifest)})
    refs = [*nk_paths,tp_path,pair_path,*manifest_paths,tp_manifest]
    return ledger, read(pair_path), raw_refs, refs


# ----------------------------------------
def candles(path: Path) -> dict:
    """
    機能：一場の分足を開始時刻で索引化し、公表・品質の規則に使う。
    引数：path（Path）は場の1分CSV。
    返り値：dictは開始秒から完全な出来高（欠測None）への対応。
    """
    result = {}
    with path.open(encoding='utf-8-sig', newline='') as stream:
        for r in csv.DictReader(stream):
            t = int(datetime.fromisoformat(r['time']).timestamp())
            valid = r['closed']=='true' and r['volume_complete']=='true' and r['volume']!=''
            assert t not in result and t%60==0
            result[t] = float(r['volume']) if valid else None
    assert all(v is None or v>=0 for v in result.values())
    return result


# ----------------------------------------
def read_book(job: tuple) -> tuple:
    """
    機能：必要な物理行を原板から読み、売買気配と数量を取得する。
    引数：job（tuple）は商品・場・必要行・原板指紋。
    返り値：tupleは商品場、必要原行、独立の出来高、入力指紋。
    """
    symbol,scene,needed,ref = job
    folder = DATA/symbol/scene
    parts = Path(ref['path']).parts
    path = ROOT.joinpath(*parts[parts.index('inputs'):]) if 'inputs' in parts else folder/Path(ref['path']).name
    assert sha(path)==ref['sha256']
    opening = gzip.open if path.suffix=='.gz' else open
    out = {}
    with opening(path,'rb') as stream:
        for i,line in enumerate(stream,1):
            if i not in needed:
                continue
            r = json.loads(line)
            b,s = r['Buy1'],r['Sell1']
            assert 0<b['Price']<s['Price']
            out[i] = {'bid':b['Price'], 'ask':s['Price'], 'buy_size':b['Qty'], 'sell_size':s['Qty'],
                      'time':datetime.fromisoformat(r['CurrentPriceTime']).timestamp()}
            if len(out)==len(needed):
                break
    assert set(out)==needed
    path1 = folder/'candle_1min.csv'
    return (symbol,scene), out, candles(path1), {'商品':symbol,'場':scene,'原板SHA256':ref['sha256'],
            '物理ファイル':path.name,'1分足SHA256':sha(path1),'取得した相異なる物理行':len(out)}


# ----------------------------------------
def decompose(trade: dict, symbol: str, scene: str, books: dict, volumes: dict) -> dict:
    """
    機能：同一の取得・返済原行で仲値損益から実側収支までを円と幅比に分解する。
    引数：trade（dict）は確定買売、symbol・scene（str）、books・volumes（dict）は原板と完全分足。
    返り値：dictは時計・符号・価格・数量の診断値。
    """
    quotes = books[symbol,scene]
    start,end = (quotes[trade[k]] for k in ('entry_line','exit_line'))
    side = 1 if trade['side']==0 else -1
    assert (trade['entry_time'],trade['exit_time']) == (start['time'],end['time'])
    assert start['ask' if side==1 else 'bid']==trade['entry_price']
    assert end['bid' if side==1 else 'ask']==trade['exit_price']
    multiplier = MULTIPLIERS[symbol]
    spreads = [r['ask']-r['bid'] for r in (start,end)]
    mid = side * ((end['ask']+end['bid'])-(start['ask']+start['bid']))/2*multiplier
    gross = side*(trade['exit_price']-trade['entry_price'])*multiplier
    entry_cost, exit_cost = [v*multiplier/2 for v in spreads]
    net = gross-FEES[symbol]-SLIPPAGE[symbol]
    assert math.isclose(mid - entry_cost - exit_cost, gross, abs_tol=1e-7)
    assert math.isclose(trade['net'],net,abs_tol=1e-7)
    ywidth = trade['width']*multiplier
    values = {'仲値変化':mid,'取得半スプレッド':entry_cost,'返済半スプレッド':exit_cost,
              '気配差控除後':gross,'手数料':FEES[symbol],'追加滑り':SLIPPAGE[symbol],'最終':net}
    # ----------------------------------------
    # 価格時計上で公表済みの最新1本と、その前の20分を固定長の時計で観測する。
    last_bar = int(start['time']//60)*60-120
    volume = volumes[symbol,scene]
    recent = volume.get(last_bar)
    previous = [volume.get(last_bar-60*i) for i in range(1,21)]
    relative = None
    if recent is not None and all(v is not None for v in previous) and sum(previous)>0:
        relative = recent/mean(previous)
    buy,sell = start['buy_size'],start['sell_size']
    quantity = start['sell_size' if side==1 else 'buy_size']
    exit_quantity = end['buy_size' if side==1 else 'sell_size']
    imbalance = side*(buy-sell)/(buy+sell) if buy is not None and sell is not None and buy+sell>0 else None
    return {'場':scene,'早朝':datetime.fromtimestamp(start['time'],JST).hour < 9,
            '費用額':values,'幅比':{k:v/ywidth for k,v in values.items()}, '取得スプレッドtick':spreads[0]/TICKS[symbol],
            '返済スプレッドtick':spreads[1]/TICKS[symbol], '取得対向枚数':quantity,'返済対向枚数':exit_quantity,
            '方向別数量不均衡':imbalance,'直近1分枚数':recent,'直近1分相対量':relative}


# ----------------------------------------
def summarize(rows: list, total: bool) -> dict:
    """
    機能：一取引を一票とする平均幅比・板数量・取引高の支持を集計する。
    引数：rows（list）は確定観測、total（bool）は実口座の円合計を扱うか。
    返り値：dictは対象数、平均寄与、数量中央値と欠測。
    """
    result = {'取引':len(rows)}
    if not rows:
        return result
    result['平均幅比'] = {k:mean(r['幅比'][k] for r in rows) for k in rows[0]['幅比']}
    if total:
        result['円合計'] = {k:round(sum(r['費用額'][k] for r in rows),2) for k in rows[0]['費用額']}
    for field in ('取得スプレッドtick','返済スプレッドtick','取得対向枚数','返済対向枚数',
                  '方向別数量不均衡','直近1分枚数','直近1分相対量'):
        values = [r[field] for r in rows if r[field] is not None]
        result[field]={'既知':len(values),'未知':len(rows)-len(values),'中央値':median(values) if values else None}
        if field.endswith('枚数') or field.endswith('tick'):
            result[field]['1以下件数']=sum(v<=1 for v in values)
            result[field]['ゼロ件数']=sum(v==0 for v in values)
    return result


# ----------------------------------------
def main() -> None:
    """
    機能：元台帳と原板を照合し、実口座と二つの同期観測集合の差を出力する。
    引数：なし。
    返り値：None。固定入力の指紋と結果を日本語JSONに保存する。
    """
    ledger,pairs,refs,files = sources()
    wanted = defaultdict(set)
    for symbol, entries in ledger.items():
        for t in entries:
            assert t['net'] is not None
            wanted[symbol,t['scene']].update((t['entry_line'],t['exit_line']))
    for group in pairs.values():
        for r in group:
            for symbol in SYMBOLS:
                t = r[symbol]
                if t is not None and t['net'] is not None:
                    wanted[symbol,r['場']].update((t['entry_line'],t['exit_line']))
    assert len(wanted)==84
    jobs = [(s,d,lines,refs[s,d]) for (s,d),lines in sorted(wanted.items())]
    books,volumes,provenance = {},{},[]
    with ThreadPoolExecutor(max_workers=4) as pool:
        for key,quotes,volume,ref in pool.map(read_book,jobs):
            books[key],volumes[key]=quotes,volume
            provenance.append(ref)
    # ----------------------------------------
    native = {}
    for symbol, entries in ledger.items():
        grouped=defaultdict(list)
        for t in entries:
            r = decompose(t,symbol,t['scene'],books,volumes)
            group = '初参加補完' if t['origin']==2 else 'LC' if t['added'] else '通常'
            for name in ('全件',group,'09時前' if r['早朝'] else '09時以後'):
                grouped[name].append(r)
        native[symbol] = {k:summarize(v,True) for k,v in grouped.items()}
    synced = {}
    for origin, group in pairs.items():
        keep = [r for r in group if all(r[s] is not None and r[s]['net'] is not None for s in SYMBOLS)]
        synced[origin] = {'通知':len(group),'両側確定':len(keep),
                          'いずれか取得なし':sum(any(r[s] is None for s in SYMBOLS) for r in group)}
        for symbol in SYMBOLS:
            values = [decompose(r[symbol],symbol,r['場'],books,volumes) for r in keep]
            synced[origin][symbol] = summarize(values, False)
    result={'実口座':native,'同期対照':synced, '判明取引だけ':True,
            '原行照合数':sum(len(rows) for rows in books.values()),
            '参照元':{p.relative_to(ROOT).as_posix():sha(p) for p in files}, '原板と分足':provenance}
    (HERE/'結果.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')


if __name__=='__main__':
    main()
