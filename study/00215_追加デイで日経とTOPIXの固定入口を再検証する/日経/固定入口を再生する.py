"""試行213の固定入口と同じ公表履歴・実側決済で日経199_02を1日進める。"""
from pathlib import Path
import json
import subprocess
import sys

import numpy as np


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
PREVIOUS = next((ROOT / 'study').glob('00213_*'))
WORK = ROOT / 'work/215日経'
EARLIER_DAY = '2026-11-18_Day'
TARGET = '2026-11-19_Day'
SCENES = ('2026-11-17_Night', EARLIER_DAY, '2026-11-18_Night', TARGET)
sys.path.insert(0, str(PREVIOUS / '日経の追加デイ'))
sys.path.insert(0, str(PREVIOUS))
import 追加デイを確認する as previous
import 金融再生 as finance


# ----------------------------------------
def summarize(trades: list, scene: dict) -> dict:
    """
    機能：確定した収支、未知件数、実保有時間を集計する。
    引数：trades（list）は取得明細、scene（dict）は場の開始・終了時計。
    返り値：dictは日経mini1枚換算の当日成績と取得明細。
    """
    gains = sum(t['net'] for t in trades if t['net'] is not None and t['net'] > 0)
    losses = -sum(t['net'] for t in trades if t['net'] is not None and t['net'] < 0)
    held = sum(t['confirmed_until'] - t['entry_time'] for t in trades)
    return {'建玉数': len(trades), '未知': sum(t['net'] is None for t in trades),
            '利益': gains, '損失': losses, '既知収支': gains - losses,
            '保有時間率下限': held / (scene['end'] - 900 - scene['start']), '建玉': trades}


# ----------------------------------------
def main() -> None:
    """
    機能：既存日を照合した同一の判断列から追加デイの単一建玉を実側気配で再生する。
    引数：なし。
    返り値：None。入力指紋・照合件数・追加日の全取引を正式フォルダに記録する。
    """
    # 同じ履歴の起点・索引器・公表処理を再利用し、追加日の価格まで時系列順に進める。
    previous.OUT = WORK
    previous.NEW = SCENES
    scenes, items, added = previous.prepare(True)
    builder = ROOT / 'work/今回移植/純入口を作る.py'
    subprocess.run([sys.executable, str(builder), '--folder', str(WORK)], check=True)
    with np.load(WORK / '純入口.npz', allow_pickle=False) as data:
        arrays = dict(data)

    # ----------------------------------------
    # 213で確定した二つのデイの全判断・取得対応と11月18日の全決済を照合する。
    selected = np.isin(arrays['scene'], [9, 11])
    with np.load(PREVIOUS / '日経の追加デイ/純入口の二デイ.npz', allow_pickle=False) as fixed:
        assert set(arrays) == set(fixed.files)
        for key in fixed.files:
            np.testing.assert_array_equal(arrays[key][selected], fixed[key])
    day_results = {}
    for number, scene in enumerate(scenes):
        if scene['session'] not in (EARLIER_DAY, TARGET):
            continue
        day = scene['session']
        item = items[number]
        assert day == item['session']
        index = finance.load_scene(WORK, item)
        trades, _ = finance.account(arrays, number, scene, index, 1.0, 'NK225')
        day_results[day] = summarize(trades, scene)
    earlier = previous.read(PREVIOUS / '日経の追加デイ/追加デイの照合結果.json')['結果']['純入口']
    assert day_results[EARLIER_DAY] == earlier

    # ----------------------------------------
    # 機械固有の絶対パスを含めず、正式な結果を再計算するための実入力を識別する。
    inputs = []
    for scene in added[-2:]:
        refs = {}
        for field in ('raw', 'csv_1m', 'csv_5m', 'quote_index'):
            ref = scene[field]
            refs[field] = {'名前': Path(ref['path']).name, 'bytes': ref['bytes'], 'sha256': ref['sha256']}
        inputs.append({'場': scene['session'], '限月コード': scene['contract'], '価格行数': scene['expected_accepted'],
                       '品質': scene['expected_quality'], '指紋': refs})
    result = {'対象': TARGET, '履歴に追加した直前ナイト': SCENES[-2], '既存二デイ一致判断数': int(selected.sum()),
              '11月18日一致取引数': len(earlier['建玉']), '入力': inputs, '結果': day_results[TARGET]}
    previous.save(HERE / '固定結果.json', result)
    print(json.dumps({k: v for k, v in result['結果'].items() if k != '建玉'}, ensure_ascii=False))


if __name__ == '__main__':
    main()
