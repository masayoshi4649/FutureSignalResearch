"""原板の数量フィールドと時計を金融ラベルなしで棚卸しする。"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
import gzip
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'work/pythonlibs'))
import orjson

BASE = ROOT / 'inputs/00194_20261116夜と1117昼の固定適用入力'
LEGACY = ROOT / 'scripts/FAR5分枠の技法判定の監査/数量の独立照合.py'
OUT = Path(__file__).with_name('観測結果.json')
spec = importlib.util.spec_from_file_location('quantity_inventory_legacy', LEGACY)
L = importlib.util.module_from_spec(spec)
spec.loader.exec_module(L)


def digest(path: Path) -> dict:
    """
    機能: 参照ファイルのサイズと内容指紋を記録する。
    引数: path(Path)は読取対象。
    返り値: dictは相対パス、サイズ、SHA256。
    """
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return {'path': str(path.relative_to(ROOT)), 'bytes': path.stat().st_size, 'sha256': h.hexdigest()}


def clocks(session: str) -> tuple[float, float]:
    """
    機能: 原板品質観測の場端を作る。金融の打切り条件は生成しない。
    引数: session(str)は日付とDay/Night。
    返り値: tuple[float,float]は開始・終了のUNIX秒。
    """
    day = datetime.fromisoformat(session[:10]).replace(tzinfo=timezone(timedelta(hours=9)))
    a, b = ((day + timedelta(hours=8, minutes=45), day + timedelta(hours=15, minutes=45))
            if session.endswith('Day') else (day + timedelta(hours=17), day + timedelta(days=1, hours=6)))
    return a.timestamp(), b.timestamp()


def q0_sources() -> tuple[dict, list]:
    """
    機能: 保存済み純特徴の判断原行だけを読み込む。
    引数: なし。
    返り値: tuple[dict,list]は商品場別の原行対応と入力指紋。金融結果は読まない。
    """
    result, refs = {}, []
    for symbol, name in [('NK225', 'NK225/入口母集団/当時特徴.json.gz'),
                         ('TOPIX', 'TOPIX/純特徴184直接.json.gz')]:
        path = BASE / name
        refs.append(digest(path))
        with gzip.open(path, 'rt', encoding='utf-8') as f:
            value = json.load(f)
        rows = value['rows'] if symbol == 'NK225' else value
        for row in rows:
            q = row['metadata']['q0'] if symbol == 'NK225' else row
            line = int(q['source_line'] if symbol == 'NK225' else q['line'])
            key = (symbol, row['session'])
            assert line not in result.setdefault(key, {})
            result[key][line] = {'time': q['time'], 'last': q['last'] if symbol == 'NK225' else q['close']}
    return result, refs


def histogram(values: list[float]) -> dict:
    """
    機能: 当時観測値の分布を端点と分位へ圧縮する。
    引数: values(list[float])は有限値のみ。
    返り値: dictは件数・最小・25/50/75百分位・最大。空集合は件数0。
    """
    if not values:
        return {'件数': 0}
    x = sorted(values)
    return {'件数': len(x), '最小': x[0], 'p25': x[int((len(x)-1)*.25)],
            '中央値': x[int((len(x)-1)*.5)], 'p75': x[int((len(x)-1)*.75)], '最大': x[-1]}


def finite(value) -> bool:
    """
    機能: boolを除外して数値の有限性を調べる。
    引数: value(any)は原板フィールド。
    返り値: boolは有限数値かどうか。
    """
    return type(value) in (int, float) and math.isfinite(value)


def scan(entry: dict, targets: dict) -> dict:
    """
    機能: 原順を保ち全物理行の数量・時計とq0原行の可用性を数える。
    引数: entry(dict)は既存入力票、targets(dict)は判断原行だけの対応。
    返り値: dictは品質集計。価格先着・決済・損益・将来ラベルは作らない。
    """
    symbol, session = entry['symbol'], entry['session']
    path = Path(entry['current_raw']['path'])
    start, end = clocks(session)
    counts, keys, fields, qcounts = Counter(), Counter(), Counter(), Counter()
    nested_keys, samples, qsamples = set(), [], []
    values = {k: [] for k in ('QI1', 'QI3', 'QI10', 'OFI30', 'E08量', '同一価格時計連続行数', '場内時計更新間隔秒')}
    h = hashlib.sha256()
    previous, accepted_time = None, start
    ofi, band, index = L.OFI30(), L.E08(), 0
    repeat_count = 0
    cached_time = {}

    def at(value):
        """
        機能: 繰返しの多い価格・量時計を同じ定義で読む。
        引数: value(any)は原板時計。
        返り値: float|NoneはUNIX秒。
        """
        if value not in cached_time:
            cached_time[value] = L.parse_clock(value)
        return cached_time[value]

    with path.open('rb') as f:
        for line, raw in enumerate(f, 1):
            h.update(raw)
            row = orjson.loads(raw)
            counts['物理行'] += 1
            keys.update(row.keys())
            current = at(row.get('CurrentPriceTime'))
            volume_at = at(row.get('TradingVolumeTime'))
            in_session = current is not None and start <= current < end
            levels = []
            for side in ('Buy', 'Sell'):
                for n in range(1, 11):
                    level = row.get(f'{side}{n}')
                    if isinstance(level, dict):
                        nested_keys.update(level)
                    for name in ('Price', 'Qty'):
                        value = level.get(name) if isinstance(level, dict) else None
                        state = '正値' if finite(value) and value > 0 else ('零' if value == 0 else '欠測又は不正')
                        fields[f'{side}{n}.{name}:{state}'] += 1
                    levels.append((level.get('Price'), level.get('Qty')) if isinstance(level, dict) else (None, None))
            bid, bq = levels[0]
            ask, aq = levels[10]
            book = tuple(levels)
            last = row.get('CurrentPrice')
            now = {'time': current, 'line': line, 'last': last, 'bid': bid, 'ask': ask, 'bq': bq, 'aq': aq,
                   'book': book, 'volume': row.get('TradingVolume'), 'volume_at': volume_at}
            normal = finite(bid) and finite(ask) and 0 < bid < ask
            qvalid = finite(bq) and finite(aq) and min(bq, aq) > 0
            counts['正常BBO'] += normal
            counts['最良両側量正値'] += qvalid
            counts['場内価格時計'] += in_session
            counts['価格時計欠測'] += current is None
            counts['価格時計場外'] += current is not None and not in_session
            counts['数量時計欠測'] += volume_at is None
            counts['数量時計と価格時計相違'] += current != volume_at
            counts['topAskとBuy1価格量一致'] += (row.get('AskPrice'), row.get('AskQty')) == levels[0]
            counts['topBidとSell1価格量一致'] += (row.get('BidPrice'), row.get('BidQty')) == levels[10]
            if previous is not None:
                same = current is not None and current == previous['time']
                price_changed = (bid, ask) != (previous['bid'], previous['ask'])
                qty_changed = (bq, aq) != (previous['bq'], previous['aq'])
                book_changed = book != previous['book']
                counts['隣接対'] += 1
                counts['同一価格時計対'] += same
                counts['双方価格時計欠測対'] += current is None and previous['time'] is None
                counts['価格時計後退対'] += current is not None and previous['time'] is not None and current < previous['time']
                counts['最良価格変化対'] += price_changed
                counts['最良数量変化対'] += qty_changed
                counts['十段変化対'] += book_changed
                counts['同時計で最良価格変化'] += same and price_changed
                counts['同時計で最良数量変化'] += same and qty_changed
                counts['同時計で十段変化'] += same and book_changed
                counts['同時計かつ量時計不変で十段変化'] += same and volume_at == previous['volume_at'] and book_changed
                counts['数量時計不変で累積量変化'] += volume_at == previous['volume_at'] and now['volume'] != previous['volume']
                counts['最良価格不変で最良量変化'] += not price_changed and qty_changed
                counts['最良不変で二段以深変化'] += not price_changed and not qty_changed and book_changed
                counts['場内同時計で十段変化'] += in_session and same and book_changed
                if same:
                    repeat_count += 1
                else:
                    values['同一価格時計連続行数'].append(repeat_count+1)
                    repeat_count = 0
                    if in_session and previous['time'] is not None and start <= previous['time'] < current:
                        values['場内時計更新間隔秒'].append(current-previous['time'])
                if same and book_changed and in_session and len(samples) < 3:
                    samples.append({'前原行': previous['line'], '原行': line, 'CurrentPriceTime': row.get('CurrentPriceTime'),
                                    'TradingVolumeTime': row.get('TradingVolumeTime'), '前L1': [previous['bid'], previous['bq'], previous['ask'], previous['aq']],
                                    'L1': [bid, bq, ask, aq], '最良価格変化': price_changed, '最良量変化': qty_changed})
            legacy_accepted = in_session and current >= accepted_time
            state = bstate = None
            if legacy_accepted:
                accepted_time = current
                if finite(last) and last > 0:
                    counts['旧数量器への投入行'] += 1
                    now['index'] = index
                    index += 1
                    state = ofi.add(now)
                    bstate = band.add(now)
            if line in targets:
                target = targets[line]
                assert current == target['time'], (symbol, session, line, current, target)
                if symbol == 'NK225':
                    assert last == target['last'], (symbol, session, line, last, target)
                else:
                    qcounts['q0公表足終値と原行Last相違'] += last != target['last']
                qcounts['q0同原行価格時計一致'] += 1
                qcounts['q0正常BBO'] += normal
                qcounts['q0最良量正値'] += qvalid
                qcounts['q0旧数量器受理'] += state is not None
                for n in (1, 3, 10):
                    bs, ass = levels[:n], levels[10:10+n]
                    if normal and all(finite(q) and q > 0 for _, q in bs+ass):
                        bsum, asum = sum(q for _, q in bs), sum(q for _, q in ass)
                        values[f'QI{n}'].append((bsum-asum)/(bsum+asum))
                        qcounts[f'q0QI{n}既知'] += 1
                if state is not None and state['known']:
                    qcounts['q0旧OFI30既知'] += 1
                    values['OFI30'].append(state['value'])
                else:
                    qcounts['q0旧OFI30不明:' + (state['reason'] if state else '原時計受理外')] += 1
                if bstate is not None and bstate['known'] and bstate['band']['quantity_known']:
                    qcounts['q0旧E08量既知'] += 1
                    v = bstate['band']
                    values['E08量'].append(v['bid_refill']+v['ask_deplete']-v['ask_refill']-v['bid_deplete'])
                if len(qsamples) < 2:
                    qsamples.append({'原行': line, 'time': current, '量': [bq, aq], '旧OFI30': state,
                                     '旧E08量既知': bool(bstate and bstate['known'] and bstate['band']['quantity_known'])})
            previous = now
    values['同一価格時計連続行数'].append(repeat_count+1)
    assert h.hexdigest() == entry['current_raw']['sha256']
    assert counts['物理行'] == entry['raw_lines']
    assert qcounts['q0同原行価格時計一致'] == len(targets)
    return {'商品': symbol, '場': session, '原板': entry['current_raw'], 'SHA一致': True, '全行': dict(counts),
            'フィールド存在行数': dict(sorted(keys.items())), '板段内フィールド集合': sorted(nested_keys),
            '同ディレクトリのファイル': sorted(p.name for p in path.parent.iterdir() if p.is_file()),
            '数量型': dict(fields), 'q0可用性': dict(qcounts),
            '分布': {k: histogram(v) for k, v in values.items()}, '同時計変化例': samples, 'q0例': qsamples}


def main() -> None:
    """
    機能: 既存4原板と純q0だけの棚卸しを保存する。
    引数: なし。
    返り値: None。金融候補・損益・先着結果は参照しない。
    """
    targets, refs = q0_sources()
    manifest = BASE / '原順8列/入力台帳.json'
    data = json.loads(manifest.read_text(encoding='utf-8'))
    results = []
    for entry in data['entries']:
        result = scan(entry, targets[(entry['symbol'], entry['session'])])
        results.append(result)
        print(json.dumps({'商品': result['商品'], '場': result['場'], '全行': result['全行'], 'q0可用性': result['q0可用性']}, ensure_ascii=False), flush=True)
    result = {'確認日': '2026-11-18', '金融ラベル参照': False, '新条件追加': False, 'Source': [digest(Path(__file__)), digest(LEGACY)],
              '純入力': refs + [digest(manifest)], '依存': {'Python': sys.version, 'orjson': orjson.__version__}, '結果': results}
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')


# ----------------------------------------
if __name__ == '__main__':
    main()
