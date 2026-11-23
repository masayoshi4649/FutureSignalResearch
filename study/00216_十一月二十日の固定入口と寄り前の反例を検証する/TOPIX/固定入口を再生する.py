"""215の最後のデイを対照にし、213_03の固定入口を新しいTOPIX板で照合する。"""
from copy import deepcopy
import gzip
import hashlib
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
PREVIOUS = next((ROOT / 'study').glob('00215_*/TOPIX'))
sys.path.insert(0, str(PREVIOUS))
import 固定入口を再生する as previous

finance = previous.finance
population = previous.population
scaling = previous.scaling
WORK = ROOT / 'work/216TOPIX'
INDEX = WORK / '原行索引'
CONVERTED = WORK / '呼値換算'
EXTRA = ('2026-11-19_Night', '2026-11-20_Day')
PIN_215 = '4f266bdaed060b9f0c379932fed3ca4356daac074f6461007d8d41ed9d96fc16'


# ----------------------------------------
def preceding() -> None:
    """
    機能：215の87場純入口を内容照合し、作業キャッシュがなければ同じ原板表記から216内へ復元する。
    引数：なし。旧原板の圧縮形だけがある場合は作業域へ一時展開し、215の物理指紋と一致させる。
    返り値：None。後続処理が参照する前史の生成先を設定する。
    """
    if not (previous.CONVERTED / '純入口.npz').is_file():
        previous.WORK = WORK / '前史215'
        previous.CONVERTED = previous.WORK / '呼値換算'
        previous.INDEX = previous.WORK / '原行索引'
        original_inputs = previous.inputs
        sources = finance.read(PREVIOUS / '固定照合.json')['入力']

        def historical_inputs() -> list:
            """
            機能：元検証の非圧縮原板SHA256に一致する2場の計画を組み立てる。
            引数：なし。
            返り値：listは旧215で使ったデイ・ナイトの入力計画。
            """
            metadata = original_inputs()
            for row, frozen in zip(metadata,sources,strict=True):
                scene = frozen['場']
                assert row['session']==scene and frozen['入力']['原板']['path']=='book.jsonl'
                folder = ROOT.parent / 'JP_OSE_Data/future/TOPIX' / scene
                plain = folder/'book.jsonl'
                if not plain.is_file():
                    plain = previous.WORK / scene / 'book.jsonl'
                    if not plain.is_file():
                        plain.parent.mkdir(parents=True,exist_ok=True)
                        with gzip.open(folder/'book.jsonl.gz','rb') as src, plain.open('wb') as dst:
                            shutil.copyfileobj(src,dst)
                row['raw'] = population.ref(plain)
                assert row['raw']['sha256']==frozen['入力']['原板']['sha256']
                row['expected_raw_stat']={'bytes':plain.stat().st_size,'mtime_ns':plain.stat().st_mtime_ns}
            return metadata

        previous.inputs = historical_inputs
        try:
            previous.build()
        finally:
            previous.inputs = original_inputs
    assert population.ref(previous.CONVERTED/'純入口.npz')['sha256']==PIN_215


# ----------------------------------------
def build_inputs() -> tuple:
    """
    機能：前回までの87場に、元値の板を索引化したナイトとデイを時系列順に接続する。
    引数：なし。213の生成器と215の計画を読み、新規2場だけを索引化する。
    返り値：tupleは通算89場の計画、追加2場の元値索引、原板・分足指紋。
    """
    CONVERTED.mkdir(parents=True, exist_ok=True)
    previous.EXTRA = EXTRA
    extra = previous.inputs()
    input_plan = WORK / '追加場の索引計画.json'
    population.save(input_plan, {'trial':216, 'scenes':extra, 'expected_entry_count':0})
    pin = population.ref(input_plan)
    if (INDEX / 'manifest.json').exists():
        assert finance.read(INDEX / 'manifest.json')['input_sha256'] == pin['sha256'], '既存索引の入力が変わっています。新しい作業先で再生成してください'
    else:
        subprocess.run([str(population.INDEX),'--mode','index','--input',str(input_plan),'--sha256',pin['sha256'],
                        '--output-dir',str(INDEX),'--workers','2'],check=True)
    records = finance.read(INDEX / 'manifest.json')['scenes']
    old = previous.CONVERTED
    plan = finance.read(old / '全場の計画.json')
    manifest = finance.read(old / '全場の換算索引.json')
    assert len(plan['scenes']) == len(manifest['scenes']) == 87
    inputs = []
    for spec, record in zip(extra, records, strict=True):
        name = spec['session']
        assert record['session'] == name and record['actual_raw_sha256'] == spec['raw']['sha256']
        folder = ROOT.parent / 'JP_OSE_Data/future/TOPIX' / name
        index_path = INDEX / record['index']['path']
        assert population.ref(index_path)['sha256'] == record['index']['sha256']
        converted_index = scaling.prices(index_path, CONVERTED / index_path.name)
        cell = deepcopy(record)
        cell['index'] = {k:converted_index[k] for k in ('path','sha256')}
        cell['index_bytes'] = converted_index['bytes']
        manifest['scenes'].append(cell)
        scene = {k:spec[k] for k in ('session','contract','start','end','force_close','raw')}
        scene.update(expected_accepted=cell['rows'], expected_quality=cell['quality'], quote_index=converted_index)
        canonical = Path(spec['raw']['path'])
        if canonical.suffix == '.gz':
            with gzip.open(canonical, 'rb') as stream:
                raw_hash = hashlib.file_digest(stream, 'sha256').hexdigest()
        else:
            raw_hash = spec['raw']['sha256']
        files = {'原板の展開後SHA256':raw_hash,'元値索引SHA256':record['index']['sha256']}
        for key, filename in [('csv_1m','candle_1min.csv'),('csv_5m','candle_5min.csv')]:
            scene[key] = scaling.candles(folder / filename, CONVERTED / (name+'_'+filename))
            files[filename+'のSHA256'] = population.ref(folder / filename)['sha256']
        inputs.append({'場':name,'入力':files,'取込行数':record['rows'],'品質':record['quality']})
        plan['scenes'].append(scene)
    # ----------------------------------------
    manifest_path = CONVERTED / '全場の換算索引.json'
    population.save(manifest_path, manifest)
    plan.update(index_manifest=population.ref(manifest_path), trial=216)
    plan_path = CONVERTED / '全場の計画.json'
    population.save(plan_path, plan)
    pin = population.ref(plan_path)
    output = CONVERTED / '母集団'
    if not (output / '完了.json').exists():
        subprocess.run([str(population.BRIDGE),'--execute-after-f0','--plan',str(plan_path),'--plan-sha',pin['sha256'],
                        '--plan-bytes',str(pin['bytes']),'--output',str(output)],check=True)
    assert finance.read(output / '完了.json')['plan_reference']['sha256']==pin['sha256']
    if not (CONVERTED / '純入口.npz').exists():
        subprocess.run([sys.executable,str(previous.SOURCE / '純入口を作る.py'),'--folder',str(CONVERTED)],check=True)
    return plan['scenes'], records, inputs


# ----------------------------------------
def main() -> None:
    """
    機能：213の実装指紋と215の旧87場全純入口・11月19日監査を照合し、新規デイを一枠で再生する。
    引数：なし。
    返り値：None。追加デイの取引・棄却・固定入力照合を同じフォルダに出力する。
    """
    with zipfile.ZipFile(previous.ASSETS / '再現Source.zip') as archive:
        for filename in archive.namelist():
            assert (ROOT / filename).read_bytes() == archive.read(filename), filename
    seals = finance.read(previous.ORIGINAL / '移植金融前の条件.json')['指紋']
    for name, fingerprint in seals.items():
        if name.endswith('.py'):
            assert population.ref(ROOT / name)['sha256'] == fingerprint, name
    # ----------------------------------------
    preceding()
    scenes, records, inputs = build_inputs()
    count = len(scenes)-2
    with np.load(CONVERTED / '純入口.npz', allow_pickle=False) as source:
        signals = {k:source[k] for k in source.files}
    historical = signals['scene'] < count
    with np.load(previous.CONVERTED / '純入口.npz', allow_pickle=False) as past:
        assert set(signals) == set(past.files)
        for key in past.files:
            np.testing.assert_array_equal(signals[key][historical],past[key])
    old = finance.read(PREVIOUS / '固定照合.json')['追加']
    old_record = finance.read(previous.INDEX / 'manifest.json')['scenes'][-1]
    assert old_record['session'] == old['場'] == scenes[count-1]['session']
    old_trades, old_audit = finance.account(signals,count-1,scenes[count-1],
                                          finance.load_scene(previous.INDEX,old_record),0.05,'TOPIX')
    assert old_trades == old['取得'] and old_audit == old['監査']
    # ----------------------------------------
    new_id = len(scenes)-1
    name = scenes[new_id]['session']
    assert name == EXTRA[1] == records[-1]['session']
    rows, audit = finance.account(signals,new_id,scenes[new_id],finance.load_scene(INDEX,records[-1]),0.05,'TOPIX')
    previous.write(HERE / '固定照合.json', {
        '条件':'213_03・入口価格20倍・決済幅0.05倍・miniTOPIX1枚・往復費用583.6円',
        '旧87場の純入力全列一致':int(historical.sum()),'旧純入力列数':len(signals),
        '11月19日の取得と全監査一致':len(old_trades),'11月19日の既知収支':round(sum(t['net'] for t in old_trades),2),
        '入力':inputs,'追加':{'場':name,'取得':rows,'監査':audit}})
    print(name, len(rows), round(sum(r['net'] for r in rows if r['net'] is not None), 2))


if __name__ == '__main__':
    main()
