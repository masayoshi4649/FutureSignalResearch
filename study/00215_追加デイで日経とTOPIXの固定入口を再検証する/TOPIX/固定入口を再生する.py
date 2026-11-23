"""試行213の呼値換算によるTOPIX口座を、11月19日デイまで同一条件で再生する。"""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import gzip
import json
from pathlib import Path
import subprocess
import sys
import zipfile

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
ORIGINAL = next((ROOT / 'study').glob('00213_*'))
ASSETS = next((ROOT / 'inputs').glob('00213_*'))
SOURCE = ROOT / 'work/今回移植'
WORK = ROOT / 'work/215TOPIX'
CONVERTED = WORK / '呼値換算'
INDEX = WORK / '原行索引'
EXTRA = ('2026-11-18_Night', '2026-11-19_Day')
sys.path.insert(0, str(SOURCE))
sys.path.insert(0, str(ORIGINAL))
import 母集団 as population
import 呼値を揃える as scaling
import 金融再生 as finance


# ----------------------------------------
def write(path: Path, value: object) -> None:
    """
    機能：JSONを保存し、既存の場合は同一の結果を確認する。
    引数：path（Path）は出力先、value（object）はJSON値。
    返り値：None。
    """
    if path.is_file():
        assert finance.read(path) == value, path
    else:
        path.write_text(json.dumps(value, ensure_ascii=False, indent=1, allow_nan=False) + '\n', encoding='utf-8')


# ----------------------------------------
def inputs() -> list:
    """
    機能：追加二場の原板・銘柄・予定時間と物理指紋を決める。
    引数：なし。
    返り値：listは原板索引を作るための対象場一覧。
    """
    items = []
    for session in EXTRA:
        folder = ROOT.parent / 'JP_OSE_Data/future/TOPIX' / session
        raw = folder / 'book.jsonl.gz'
        if not raw.exists():
            raw = folder / 'book.jsonl'
        with (gzip.open(raw, 'rb') if raw.suffix == '.gz' else raw.open('rb')) as stream:
            contract = json.loads(stream.readline())['Symbol']
        date = datetime.fromisoformat(session[:10]).replace(tzinfo=timezone(timedelta(hours=9)))
        day = session.endswith('_Day')
        start = date + (timedelta(hours=8, minutes=45) if day else timedelta(hours=17))
        end = date + (timedelta(hours=15, minutes=45) if day else timedelta(days=1, hours=6))
        items.append({'session': session, 'contract': contract, 'start': start.timestamp(),
                      'end': end.timestamp(), 'force_close': end.timestamp() - 600, 'raw': population.ref(raw),
                      'expected_accepted': 0, 'expected_quality': None, 'entries': [],
                      'expected_raw_stat': {'bytes': raw.stat().st_size, 'mtime_ns': raw.stat().st_mtime_ns}})
    return items


# ----------------------------------------
def build() -> tuple:
    """
    機能：元値の原行を索引化し、呼値換算した旧85場と追加2場から当時特徴を作る。
    引数：なし。
    返り値：tupleは全87場の予定、追加2場の元値索引明細、入力の指紋。
    """
    CONVERTED.mkdir(parents=True, exist_ok=True)
    extra = inputs()
    original_plan = WORK / '追加場の索引計画.json'
    write(original_plan, {'trial': 215, 'scenes': extra, 'expected_entry_count': 0})
    if not (INDEX / 'manifest.json').is_file():
        subprocess.run([str(population.INDEX), '--mode', 'index', '--input', str(original_plan),
                        '--sha256', population.ref(original_plan)['sha256'], '--output-dir', str(INDEX),
                        '--workers', '2'], check=True)
    raw_records = finance.read(INDEX / 'manifest.json')['scenes']
    old_dir = SOURCE / '呼値換算'
    plan = finance.read(old_dir / '母集団計画.json')
    manifest = finance.read(old_dir / 'manifest.json')
    assert len(plan['scenes']) == len(manifest['scenes']) == 85
    fingerprints = []
    for spec, raw_record in zip(extra, raw_records, strict=True):
        scene = spec['session']
        assert raw_record['session'] == scene and raw_record['actual_raw_sha256'] == spec['raw']['sha256']
        folder = ROOT.parent / 'JP_OSE_Data/future/TOPIX' / scene
        index_path = INDEX / raw_record['index']['path']
        assert population.ref(index_path)['sha256'] == raw_record['index']['sha256']
        quote_ref = scaling.prices(index_path, CONVERTED / index_path.name)
        item = deepcopy(raw_record)
        item['index'] = {'path': quote_ref['path'], 'sha256': quote_ref['sha256']}
        item['index_bytes'] = quote_ref['bytes']
        manifest['scenes'].append(item)
        target = {k: spec[k] for k in ('session', 'contract', 'start', 'end', 'force_close', 'raw')}
        target.update(expected_accepted=item['rows'], expected_quality=item['quality'], quote_index=quote_ref)
        refs = {'原板': spec['raw'], '元値索引': population.ref(index_path)}
        for key, name in [('csv_1m', 'candle_1min.csv'), ('csv_5m', 'candle_5min.csv')]:
            target[key] = scaling.candles(folder / name, CONVERTED / (scene + '_' + name))
            refs[name] = population.ref(folder / name)
        fingerprints.append({'場': scene, '取込行数': item['rows'], '品質': item['quality'],
                             '入力': {k: {**v, 'path': Path(v['path']).name} for k, v in refs.items()}})
        plan['scenes'].append(target)
    # ----------------------------------------
    manifest_file = CONVERTED / '全場の換算索引.json'
    write(manifest_file, manifest)
    plan_file = CONVERTED / '全場の計画.json'
    plan.update(index_manifest=population.ref(manifest_file), trial=215)
    write(plan_file, plan)
    output = CONVERTED / '母集団'
    if not (output / '完了.json').exists():
        pin = population.ref(plan_file)
        subprocess.run([str(population.BRIDGE), '--execute-after-f0', '--plan', str(plan_file),
                        '--plan-sha', pin['sha256'], '--plan-bytes', str(pin['bytes']), '--output', str(output)],
                       check=True)
    if not (CONVERTED / '純入口.npz').exists():
        subprocess.run([sys.executable, str(SOURCE / '純入口を作る.py'), '--folder', str(CONVERTED)], check=True)
    return plan['scenes'], raw_records, fingerprints


# ----------------------------------------
def main() -> None:
    """
    機能：旧85場の純入口全列・旧最終デイ台帳を照合し、追加デイの単一建玉口座を保存する。
    引数：なし。
    返り値：None。
    """
    with zipfile.ZipFile(ASSETS / '再現Source.zip') as archive:
        for name in archive.namelist():
            assert (ROOT / name).read_bytes() == archive.read(name), name
    financial_seal = finance.read(ORIGINAL / '移植金融前の条件.json')['指紋']
    for name, sha256 in financial_seal.items():
        if name.endswith('.py'):
            assert population.ref(ROOT / name)['sha256'] == sha256, name
    # ----------------------------------------
    scenes, records, fingerprints = build()
    old_signal = SOURCE / '呼値換算/純入口.npz'
    with np.load(CONVERTED / '純入口.npz', allow_pickle=False) as current, np.load(old_signal, allow_pickle=False) as old:
        arrays = {name: current[name] for name in current.files}
        historical = arrays['scene'] < 85
        assert set(old.files) == set(arrays)
        for key in old.files:
            np.testing.assert_array_equal(arrays[key][historical], old[key])
    with np.load(ASSETS / '全純入口.npz', allow_pickle=False) as saved:
        mapping = finance.read(ASSETS / '候補列.json')['呼値純入口']
        for key, col in mapping.items():
            np.testing.assert_array_equal(arrays[key][historical], saved[col])
    original_records = finance.read(SOURCE / '原行索引/manifest.json')['scenes']
    original_ledger = finance.read(next((ORIGINAL / '金融正本').glob('213_03*.gz')))
    before = scenes[84]
    assert before['session'] == '2026-11-18_Day'
    trades, audit = finance.account(arrays, 84, before, finance.load_scene(SOURCE / '原行索引', original_records[-1]),
                                    0.05, 'TOPIX')
    assert trades == [t for t in original_ledger['取得'] if t['scene'] == before['session']]
    assert audit == original_ledger['監査'][before['session']]
    # ----------------------------------------
    after = scenes[86]
    assert after['session'] == EXTRA[1]
    rows, audit = finance.account(arrays, 86, after, finance.load_scene(INDEX, records[-1]), 0.05, 'TOPIX')
    write(HERE / '固定照合.json', {
        '条件': '213_03・入口価格20倍・決済幅0.05倍・miniTOPIX1枚・往復費用583.6円',
        '旧85場の純入力全列一致': int(historical.sum()), '旧純入力列数': len(arrays),
        '11月18日の取得と全監査一致': len(trades),
        '11月18日の既知収支': round(sum(t['net'] for t in trades), 2),
        '入力': fingerprints, '追加': {'場': after['session'], '取得': rows, '監査': audit}})
    print(after['session'], len(rows), round(sum(t['net'] for t in rows if t['net'] is not None), 2))


if __name__ == '__main__':
    main()
