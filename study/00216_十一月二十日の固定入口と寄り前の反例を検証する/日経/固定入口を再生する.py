"""固定日経199_02を11月19日ナイトの履歴から11月20日デイまで再生する。"""
import gzip
import hashlib
import json
import runpy
import subprocess
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
PREVIOUS = next((ROOT / 'study').glob('00215_*')) / '日経'
BASE = next((ROOT / 'study').glob('00213_*')) / '日経の追加デイ'
WORK = ROOT / 'work/216日経'
PREVIOUS_DAY = '2026-11-19_Day'
TARGET = '2026-11-20_Day'
SCENES = ('2026-11-17_Night', '2026-11-18_Day', '2026-11-18_Night', PREVIOUS_DAY,
          '2026-11-19_Night', TARGET)


# ----------------------------------------
def uncompressed_digest(path: Path) -> str:
    """
    機能：圧縮の有無にかかわらず、展開した原板に対してSHA256を計算する。
    引数：path（Path）は入力原板。
    返り値：strは非圧縮原板のSHA256。
    """
    opener = gzip.open if path.suffix == '.gz' else open
    with opener(path, 'rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


# ----------------------------------------
def main() -> None:
    """
    機能：旧日の判断と約定を照合し、固定条件で追加日の利益・損失・全建玉を保存する。
    引数：なし。取引開始前に利用できた判断を生成するため旧日前史も読み込む。
    返り値：None。物理ファイル・展開内容の指紋、当日の全建玉を固定結果.jsonへ記録する。
    """
    source = runpy.run_path(str(PREVIOUS / '固定入口を再生する.py'))
    preparer = source['previous']
    finance = source['finance']
    preparer.OUT = WORK
    preparer.NEW = SCENES
    scenes, items, appended = preparer.prepare(True)
    builder = ROOT / 'work/今回移植/純入口を作る.py'
    subprocess.run([sys.executable, str(builder), '--folder', str(WORK)], check=True)
    with np.load(WORK / '純入口.npz', allow_pickle=False) as output:
        arrays = dict(output)

    # ----------------------------------------
    # 正式保存した11月17・18日の全判断と11月19日の建玉を、それぞれの正本へ照合する。
    selected = np.isin(arrays['scene'], [9, 11])
    with np.load(BASE / '純入口の二デイ.npz', allow_pickle=False) as fixed:
        assert set(arrays) == set(fixed.files)
        for key in fixed.files:
            np.testing.assert_array_equal(arrays[key][selected], fixed[key])
    earlier = preparer.read(PREVIOUS / '固定結果.json')
    results = {}
    for number, spec in enumerate(scenes):
        day = spec['session']
        if day in (PREVIOUS_DAY, TARGET):
            assert items[number]['session'] == day
            index = finance.load_scene(WORK, items[number])
            trades, _ = finance.account(arrays, number, spec, index, 1.0, 'NK225')
            results[day] = source['summarize'](trades, spec)
    assert results[PREVIOUS_DAY] == earlier['結果']

    # ----------------------------------------
    # 215の物理ファイルと今回使用する圧縮ファイルで展開内容・分足・価格索引が一致するか調べる。
    old_pins = {row['場']: row['指紋'] for row in earlier['入力']}
    inputs = []
    for scene in appended[-4:]:
        name = scene['session']
        hashes = {k:{'名前':Path(scene[k]['path']).name, 'bytes':scene[k]['bytes'], 'sha256':scene[k]['sha256']}
                  for k in ('raw','csv_1m','csv_5m','quote_index')}
        path = Path(scene['raw']['path'])
        plain_sha = uncompressed_digest(path)
        if path.suffix == '.gz' and path.with_suffix('').is_file():
            assert plain_sha == uncompressed_digest(path.with_suffix('')), name
        if name in old_pins:
            assert old_pins[name]['raw']['名前'] == 'book.jsonl'
            assert plain_sha == old_pins[name]['raw']['sha256']
            for k in ('csv_1m','csv_5m','quote_index'):
                assert hashes[k]['sha256'] == old_pins[name][k]['sha256'], (name,k)
        else:
            inputs.append({'場':name, '限月コード':scene['contract'], '価格行数':scene['expected_accepted'],
                           '品質':scene['expected_quality'], '原板展開SHA256':plain_sha, '指紋':hashes})
    result = {'対象': TARGET, '履歴に追加した直前ナイト':SCENES[-2], '既存二デイ一致判断数':int(selected.sum()),
              '11月19日一致取引数':len(results[PREVIOUS_DAY]['建玉']), '旧原板展開と足と索引が一致した場':list(old_pins),
              '入力':inputs, '結果':results[TARGET]}
    preparer.save(HERE / '固定結果.json', result)
    print(json.dumps({k:v for k,v in result['結果'].items() if k != '建玉'}, ensure_ascii=False))


if __name__ == '__main__':
    main()
