"""213で固定した日経通知のTOPIX口座と、両指数の同時計の価格経路を追加日に適用する。"""
import json
import math
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PREVIOUS = next((ROOT / 'study').glob('00213_*'))
sys.path[:0] = list(map(str, (PREVIOUS, PREVIOUS / '日経取得通知の対照', ROOT / 'scripts/複合検証')))
import データ準備 as prep
import 追随を診断する as follow
from 金融再生 import read, closing, settle, load_scene
from 同時刻の両指数を照合する import summarize

JST = timezone(timedelta(hours=9))
ADDED = ('2026-11-18_Day', '2026-11-19_Day')


# ----------------------------------------
def notification(scene: str, cache: Path, orders: list, engine: object) -> dict:
    """
    機能：日経の取得通知をTOPIXの一枠口座で順次受け、原行の線形走査と区間木を照合する。
    引数：scene（str）は場、cache（Path）は原順8列、orders（list）は日経の建玉、engine（object）は211の検算器。
    返り値：dictは通知の採否・全取得・場の利益と損失。
    """
    start, continuous_end = prep.session_bounds(scene)
    end = continuous_end - 600
    book = follow.quotes(cache, start, end)
    routes = {h: engine.Route({'cache_absolute': str(cache), 'session': scene}, h) for h in ('H60','SESSION')}
    release, state = -math.inf, '空'
    trades, requests = [], []
    for order in orders:
        time = order['entry_time']
        row = {'通知': time, '日経原行': order['entry_line']}
        requests.append(row)
        if time <= release:
            row['判断'] = state + '中'
            continue
        k = int(book['now'].searchsorted(time)) - 1
        if k < 0 or time - book['now'][k] > 60:
            row['判断'] = '基準板不足'
            continue
        mid = float((book['ask'][k] + book['bid'][k]) / 2)
        width = math.ceil(4 * mid * order['width'] / order['entry_price']) / 4
        row.update(基準原行=int(book['line'][k]), 基準時刻=float(book['now'][k]), 基準価格=mid, 幅=width)
        cell = follow.exit_and_fill(book, order, width, end)
        other = routes[order['horizon']].cell(time, order['entry_line'], 1 if order['side']==0 else -1, width)
        if cell is None:
            assert other is None
            release, state = min(time + 30, end - 60), '予約'
            row['判断'] = '取得失効'
            continue
        for key in ('entry_time','entry_line','entry_price','exit_time','exit_line','exit_price','label','known_until'):
            assert cell[key] == other[key], (scene, time, key)
        release, state = (end if cell['net'] is None else cell['exit_time']), '保有'
        row['判断'] = '取得'
        cell.update(scene=scene, signal_time=time, nk_line=order['entry_line'], horizon=order['horizon'])
        trades.append(cell)
    return {'通知記録': requests, '取得': trades, '集計': follow.totals(trades)}


# ----------------------------------------
def synchronized(scene: str, accounts: dict, indices: dict) -> dict:
    """
    機能：元建玉の取得翌秒から両商品を同時照会し、元の期限と呼値数で順逆と費用後損益を測る。
    引数：scene（str）はデイ、accounts（dict）は商品別元帳、indices（dict）は商品別48バイト索引。
    返り値：dictは判断元別の全観測と平均。独立観測を口座として加算しない。
    """
    cut = datetime.fromisoformat(scene[:10]+'T15:30:00').replace(tzinfo=JST).timestamp()
    result = {}
    for origin, trades in accounts.items():
        pairs = []
        for order in trades:
            event = order['entry_time']
            width = order['width'] * (20 if origin == 'TOPIX' else 1)
            pair = {'場': scene, '通知': event, '側': order['side'], '日経表記幅': width, '期限': order['horizon']}
            for symbol, index in indices.items():
                i = index.first_normal(event+1)
                valid = i >= 0 and index.times[i] < min(event+30, cut-60)
                size = width / 20 if symbol=='TOPIX' else width
                pair[symbol] = settle(index,i,order['side'],size,order['horizon'],cut,closing(index,cut),symbol) if valid else None
            pairs.append(pair)
        complete = any(all(p[s] and p[s]['net'] is not None for s in indices) for p in pairs)
        result[origin] = {'観測': pairs, '集計': summarize(pairs) if complete else {'通知':len(pairs),'両側確定':0}}
    return result


# ----------------------------------------
def main() -> None:
    """
    機能：11月17日の旧通知対照を照合し、18・19日の通知口座と19日の同期診断を再生する。
    引数：なし。入力は213の固定結果、215で生成した両口座、共用原板。
    返り値：None。集計と照合明細を当試行に保存する。
    """
    out = ROOT / 'work/215通知'
    out.mkdir(parents=True,exist_ok=True)
    assert follow.digest(PREVIOUS/'日経取得通知の対照/条件.json') == follow.SCHEMA
    nikkei = {ADDED[0]:read(PREVIOUS/'日経の追加デイ/追加デイの照合結果.json')['結果']['純入口']['建玉'],
              ADDED[1]:read(HERE/'日経/固定結果.json')['結果']['建玉']}
    old_day = '2026-11-17_Day'
    old = read(PREVIOUS/'日経取得通知の対照/結果.json')
    history = read(next((ROOT/'study').glob('00199_*/追加二場/保存金融/*02__C0_IFD.json.gz')))['ledger']
    old_orders = [{k:v[i] for k,v in history.items()} for i,s in enumerate(history['scene']) if s==old_day]
    old_cache = next((ROOT/'inputs').glob('00194_*/原順8列/TOPIX/'+old_day+'.npz'))
    results, sources = {}, {}
    with TemporaryDirectory() as tmp:
        engine = follow.verification_engine(Path(tmp))
        witness = notification(old_day,old_cache,old_orders,engine)
        assert witness['取得'] == [t for t in old['取引'] if t['scene']==old_day]
        assert [r['判断'] for r in witness['通知記録']] == [r['判断'] for r in old['全通知'] if r['場']==old_day]
        for day in ADDED:
            folder = ROOT.parent/'JP_OSE_Data/future/TOPIX'/day
            source = next(p for p in (folder/'book.jsonl',folder/'book.jsonl.gz') if p.is_file())
            with TemporaryDirectory(dir=out) as data_tmp:
                cache = Path(data_tmp)/f'{day}.npz'
                info = prep.build_one(source,cache,'TOPIX',day,ROOT.parent/'JP_OSE_Data')
                sources[day] = {k:info[k] for k in ('source_path','raw_lines','sha256_uncompressed','sha256_cache') if k in info}
                sources[day]['原板ファイルSHA256'] = follow.digest(source)
                results[day] = notification(day,cache,nikkei[day],engine)
    # ----------------------------------------
    indices = {}
    for symbol, subdir in [('NK225','215日経'),('TOPIX','215TOPIX')]:
        directory = ROOT/'work'/subdir/'原行索引'
        item = next(r for r in read(directory/'manifest.json')['scenes'] if r['session']==ADDED[1])
        indices[symbol] = load_scene(directory,item)
    accounts = {'NK225':nikkei[ADDED[1]], 'TOPIX':read(HERE/'TOPIX/固定照合.json')['追加']['取得']}
    report = {'旧11月17日一致取得':len(witness['取得']),'原板指紋':sources,'通知対照':results,
              '11月19日同期':synchronized(ADDED[1],accounts,indices)}
    (HERE/'通知と同期の結果.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf8')


if __name__=='__main__':
    main()
