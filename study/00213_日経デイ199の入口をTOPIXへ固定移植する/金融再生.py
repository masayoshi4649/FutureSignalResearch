"""日経199の単一建玉・予約・決済時計を保存し、商品だけを替えて再生する。"""
from argparse import ArgumentParser
from collections import Counter
from pathlib import Path
import gzip
import json
import math
import sys

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
for directory in ('173追加なしの因果再生', '179終了前決済', '163任意幅の数値化'):
    sys.path.insert(0, str(ROOT / 'work' / directory))
import arrays163
import early179
import engine173

HORIZONS = ('H30', 'H60', 'H120', 'SESSION')


# ----------------------------------------
def read(path: Path) -> object:
    """
    機能：内容指紋で管理した入力を読む。
    引数：path（Path）はJSONまたは圧縮JSON。
    返り値：objectは展開値。
    """
    return json.loads(gzip.decompress(path.read_bytes()) if path.suffix == '.gz' else path.read_bytes())


# ----------------------------------------
def closing(index: early179.PriceIndex, cut: float) -> int:
    """
    機能：強制返済を要求した翌秒以降、締切までの最初の正常原行を得る。
    引数：index（PriceIndex）、cut（float）は終了15分前の価格時計。
    返り値：intは原行位置、欠測は−1。
    """
    found = index.first_normal(cut - 59)
    return found if found >= 0 and index.times[found] <= cut else -1


# ----------------------------------------
def settle(index: early179.PriceIndex, entry: int, side: int, width: float,
           horizon: str, cut: float, forced: int, symbol: str) -> dict:
    """
    機能：179と同じ期限・欠測打切り・実側IFDを一取得分再生し、線形走査とも照合する。
    引数：index（PriceIndex）、entry/side/forced（int）、width/cut（float）、horizon/symbol（str）。
    返り値：dictは建玉・決済原行、価格、費用後損益と確定保有終点。
    """
    rows = index.rows
    sign = 1 if side == 0 else -1
    price = float(rows['ask' if side == 0 else 'bid'][entry])
    mark = rows['bid' if side == 0 else 'ask']
    opened = float(index.times[entry])
    assert rows['normal'][entry] and opened < cut - 60
    deadline = math.inf if horizon == 'SESSION' else opened + int(horizon[1:]) * 60
    term = early179.terminal(index, entry, deadline, cut, forced)
    stop = term['touch_end']
    hit = index.first_outside(entry + 1, stop, price - width, price + width, side)
    points = mark[entry + 1:stop] - price
    cross = np.flatnonzero((rows['normal'][entry + 1:stop] == 1) & (abs(points) >= width))
    assert hit == (int(cross[0]) + entry + 1 if len(cross) else -1)
    end = hit if hit >= 0 else term['exit']
    result = {'side': side, 'width': width, 'horizon': horizon, 'entry_index': entry,
              'entry_line': int(rows['source_line'][entry]), 'entry_time': opened, 'entry_price': price,
              'spread': float(rows['ask'][entry] - rows['bid'][entry]), 'exit_index': end,
              'exit_time': None, 'exit_line': -1, 'exit_price': None, 'status': term['status'],
              'label': 2, 'gross': None, 'net': None, 'confirmed_until': term['lower']}
    if end >= 0:
        exit_price = float(mark[end])
        change = sign * (exit_price - price)
        multiplier, cost = (100, 1077) if symbol == 'NK225' else (1000, 583.6)
        label = (1 if change > 0 else -1) if hit >= 0 else 0
        result.update(exit_time=float(index.times[end]), exit_line=int(rows['source_line'][end]),
                      exit_price=exit_price, gross=change * multiplier, net=round(change * multiplier-cost, 2),
                      label=label, status=(1 if label == 1 else 2) if hit >= 0 else term['status'],
                      confirmed_until=float(index.times[end]))
    return result


# ----------------------------------------
def load_scene(folder: Path, item: dict) -> early179.PriceIndex:
    """
    機能：48バイト原行の指紋と単調性を検査し、価格探索木を作る。
    引数：folder（Path）は索引フォルダ、item（dict）は場の台帳。
    返り値：PriceIndexは原行順の両側価格索引。
    """
    record = item['index']
    return early179.PriceIndex(arrays163.load_records(folder / record['path'], record['sha256'], item['rows']))


# ----------------------------------------
def audit_nikkei() -> dict:
    """
    機能：日経199_02の既使用デイ全取得を原行から再決済して固定台帳と照合する。
    引数：なし。
    返り値：dictは照合取引・金額・セッション数。
    """
    old = next((ROOT / 'study').glob('00199_*'))
    packs = [read(next(folder.glob('*_02__C0_IFD.json.gz'))) for folder in
             [old / '保存金融', old / '追加二場/保存金融']]
    scenes = {s['scene']: s for pack in packs for s in pack['sessions'] if s['scene'].endswith('_Day')}
    trades = [{k: v[i] for k, v in pack['ledger'].items()} for pack in packs
              for i, scene in enumerate(pack['ledger']['scene']) if scene in scenes]
    manifests = [next((ROOT / 'inputs').glob(pattern)) for pattern in
                 ['00163*/価格索引/manifest.json', '00167*/原板数値索引/manifest.json',
                  '00180*/原板数値索引/manifest.json', '00194*/NK225/原板数値索引/manifest.json']]
    checked = set()
    for manifest in manifests:
        for item in read(manifest)['scenes']:
            scene = item['session']
            if scene not in scenes:
                continue
            index = load_scene(manifest.parent, item)
            cut = float(scenes[scene]['close_deadline'])
            forced = closing(index, cut)
            for saved in (t for t in trades if t['scene'] == scene):
                actual = settle(index, saved['entry_index'], saved['side'], saved['width'], saved['horizon'],
                                cut, forced, 'NK225')
                for key in ('entry_line','entry_price','entry_time','exit_line','exit_price','exit_time',
                            'exit_index','status','label','net'):
                    assert actual[key] == saved[key], (scene, key, actual[key], saved[key])
                checked.add((scene, saved['entry_index']))
    assert len(checked) == len(trades) == 162 and len(scenes) == 42
    return {'取引':len(checked),'デイ':len(scenes),'収支':sum(t['net'] for t in trades),'照合属性数':10}


# ----------------------------------------
def account(a: dict, scene_number: int, scene: dict, index: early179.PriceIndex,
            scale: float, symbol: str) -> tuple:
    """
    機能：一場分の元入口全イベントを予約込み単一枠へ流し、取得後の幅と商品費用を適用する。
    引数：a/scene（dict）、scene_number（int）、index（PriceIndex）、scale（float）、symbol（str）。
    返り値：tupleは取得明細と場別の監査件数。
    """
    cut = scene['end'] - 900
    active = np.flatnonzero((a['scene'] == scene_number) & (a['time'] < cut - 60))
    forced = closing(index, cut)
    keys, captures = [], []
    for row in active:
        keys.append((float(a['time'][row]), int(a['index'][row]), int(a['line'][row])))
        at = float(a['finish_time'][row])
        q1 = int(a['q1_index'][row])
        if at >= cut - 60:
            capture = {'status':'cancelled', 'finish_key':(cut-60, math.inf, math.inf)}
        elif q1 >= 0:
            assert index.times[q1] == at and index.rows['source_line'][q1] == a['finish_line'][row]
            capture = {'status':'filled', 'fill_key':(at, q1, int(a['finish_line'][row])), 'case':q1}
        else:
            capture = {'status':'cancelled', 'finish_key':(at, int(a['finish_index'][row]), int(a['finish_line'][row]))}
        captures.append(capture)
    settled = {}

    def lookup(event: int, case: int, side: int, width: int) -> float | None:
        """
        機能：一件の取得後に、その出口時計だけを元の予約エンジンへ返す。
        引数：event/case/side/width（int）は場内イベント・原行・実側・日経表記幅。
        返り値：floatまたはNoneは既知の決済秒または未知。
        """
        row = active[event]
        horizon = HORIZONS[int(a['hi'][row])] if a['core'][row] != 0 else 'H60'
        trade = settle(index, case, side, width*scale, horizon, cut, forced, symbol)
        trade.update(scene=scene['session'], request_time=keys[event][0], request_line=keys[event][2],
                     added=bool(a['added'][row]), branch=int(a['branches'][row]))
        settled[event] = trade
        return trade['exit_time']

    positions = engine173.replay(keys, np.zeros(len(keys), int), np.array([scene['start']]),
                                 np.array([cut]), captures, *(a[key][active] for key in
                                 ('core','branches','technical','tier','mw','fw')), 200, lookup)
    trades = []
    for record in positions['records']:
        trade = settled[record['event']]
        trade['origin'] = record['origin']
        trades.append(trade)
    return trades, positions['audits'][0]


# ----------------------------------------
def main() -> None:
    """
    機能：旧日経照合、または純入口を事前に指定した倍率で全デイへ固定適用する。
    引数：CLIの種類・入力ディレクトリ・純入力・幅倍率・出力先。
    返り値：None。出力は日本語UTF-8 JSON。
    """
    parser = ArgumentParser()
    parser.add_argument('--audit', action='store_true')
    parser.add_argument('--input', type=Path)
    parser.add_argument('--pure', type=Path)
    parser.add_argument('--scale', type=float, choices=(1.0, 0.05))
    parser.add_argument('--symbol', choices=('NK225','TOPIX'), default='TOPIX')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    if args.audit:
        result = audit_nikkei()
    else:
        with np.load(args.pure, allow_pickle=False) as data:
            a = {k:data[k] for k in data.files}
        spec = read(args.input / '索引計画.json')['scenes']
        folder = args.input / '原行索引'
        entries = read(folder / 'manifest.json')['scenes']
        trades, audits = [], {}
        for si, (scene, item) in enumerate(zip(spec, entries, strict=True)):
            assert scene['session'] == item['session']
            if not scene['session'].endswith('_Day'):
                continue
            filled, audit = account(a, si, scene, load_scene(folder, item), args.scale, args.symbol)
            trades.extend(filled)
            audits[scene['session']] = audit
        result = {'倍率':args.scale, '商品':args.symbol, '純入口SHA256':arrays163.sha(args.pure),
                  '取得':trades, '監査':audits, '状態':dict(Counter(t['status'] for t in trades))}
    encoded = (json.dumps(result, ensure_ascii=False, separators=(',', ':'), allow_nan=False)+'\n').encode()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes(gzip.compress(encoded, mtime=0) if args.out.suffix=='.gz' else encoded)


if __name__ == '__main__':
    main()
