"""199_02の元ナイトを旧台帳で照合し、未集計の4ナイトへ一枠のまま順に適用する。"""
import gzip
import json
import runpy
import subprocess
import sys
from datetime import datetime, time, timezone, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
DAY_WORK = ROOT / 'work/216日経'
WORK = DAY_WORK / 'ナイト'
FIXED = next((ROOT/'study').glob('00199_*'))
NEW = tuple(f'2026-11-{day}_Night' for day in (17,18,19,20))
JST = timezone(timedelta(hours=9))


# ----------------------------------------
def us_open(scene: str) -> float:
    """
    機能：当該ナイト開始日の米国東部09:30を、夏冬の時差を反映してUnix秒に直す。
    引数：scene（str）は開始日基準のナイト名。
    返り値：floatは米国現物寄りの時刻。
    """
    day = datetime.fromisoformat(scene[:10]).date()
    return datetime.combine(day, time(9,30), tzinfo=ZoneInfo('America/New_York')).timestamp()


# ----------------------------------------
def reference() -> dict:
    """
    機能：旧台帳の11月10、11、12、13、16日の全ナイトを読み、夜間口座の照合に使う。
    引数：なし。
    返り値：dictは場ごとの元取引と米国前後を分ける価格時計。
    """
    out = {}
    for folder in (FIXED/'保存金融', FIXED/'追加二場/保存金融'):
        file = next(folder.glob('*02__C0_IFD.json.gz'))
        packet = json.loads(gzip.decompress(file.read_bytes()))
        ledger = packet['ledger']
        for spec in packet['sessions']:
            day = spec['scene']
            if spec['kind']=='NIGHT' and '2026-11-10_Night' <= day < NEW[0]:
                assert spec['phases'][1]['start'] == us_open(day)
                out[day] = [{k:v[i] for k,v in ledger.items()} for i,s in enumerate(ledger['scene']) if s==day]
    assert len(out)==5
    return out


# ----------------------------------------
def main() -> None:
    """
    機能：夜間を含む元の199_02の判断器で、05:45までの単一口座を再生し、米国前後を個別集計する。
    引数：なし。先に固定入口を再生する.pyで作成した216デイまでの計画と純入口を使用する。
    返り値：None。旧ナイトの照合結果と新4ナイトの全明細・損益・原板指紋を正式保存する。
    """
    current = runpy.run_path(str(HERE / '固定入口を再生する.py'))
    source = runpy.run_path(str(current['PREVIOUS'] / '固定入口を再生する.py'))
    prep, finance = source['previous'], source['finance']
    history = WORK / 'デイまでの履歴'
    history.mkdir(parents=True,exist_ok=True)
    prep.save(history/'母集団接続計画.json', prep.read(DAY_WORK/'前史十場と追加二場の母集団計画.json'))
    prep.save(history/'前史八場と追加二場の索引参照.json', prep.read(DAY_WORK/'前史十場と追加二場の索引参照.json'))
    prep.OLD, prep.OUT, prep.NEW = history, WORK, (NEW[-1],)
    scenes, items, _ = prep.prepare(True)
    subprocess.run([sys.executable, str(ROOT/'work/今回移植/純入口を作る.py'), '--folder', str(WORK)],check=True)
    with np.load(WORK/'純入口.npz',allow_pickle=False) as new, np.load(DAY_WORK/'純入口.npz',allow_pickle=False) as old:
        arrays = dict(new)
        prior = arrays['scene'] < len(scenes)-1
        for key in old.files:
            np.testing.assert_array_equal(old[key],arrays[key][prior])
    # ----------------------------------------
    # 価格経路や後続注文を米国寄りで分断せず、一口座のまま発注判断の当時刻へ帯名を付ける。
    fixed = reference()
    matched, results, raws = {}, {}, {}
    fields = ('side','label','origin','added','phase','width','horizon','entry_index','entry_line','entry_time',
              'entry_price','exit_index','exit_line','exit_time','exit_price','net','status')
    for i, (spec, item) in enumerate(zip(scenes, items, strict=True)):
        day = spec['session']
        if not day.endswith('_Night'):
            continue
        assert day==item['session'] and (day in NEW or day in fixed)
        cut = spec['end'] - 900
        assert datetime.fromtimestamp(cut,JST).strftime('%H:%M')=='05:45'
        orders, _ = finance.account(arrays, i, spec, finance.load_scene(WORK,item), 1.0, 'NK225')
        for order in orders:
            order['phase'] = 1 if order['request_time'] < us_open(day) else 2
            order['判断帯'] = '米前' if order['phase']==1 else '米後'
            if order['exit_time'] is not None:
                assert order['exit_time'] <= cut
        if day in fixed:
            for ours, theirs in zip(orders, fixed[day], strict=True):
                for field in fields:
                    assert ours[field] == theirs[field], (day,field,ours[field],theirs[field])
            matched[day] = len(orders)
            continue
        summary = source['summarize'](orders,spec)
        sides = {}
        for band in ('米前','米後'):
            selected = [o for o in orders if o['判断帯']==band]
            sides[band] = {'建玉':len(selected), '未知':sum(o['net'] is None for o in selected),
                '利益':sum(o['net'] for o in selected if o['net'] is not None and o['net']>0),
                '損失':-sum(o['net'] for o in selected if o['net'] is not None and o['net']<0)}
        results[day] = {**summary, '判断帯別':sides}
        pin = {k:{'名前':Path(spec[k]['path']).name, 'bytes':spec[k]['bytes'], 'sha256':spec[k]['sha256']}
               for k in ('raw','csv_1m','csv_5m','quote_index')}
        raw = Path(spec['raw']['path'])
        plain = current['uncompressed_digest'](raw)
        if raw.suffix=='.gz' and raw.with_suffix('').is_file():
            assert plain==current['uncompressed_digest'](raw.with_suffix('')), day
        raws[day] = {'限月コード':spec['contract'],'価格行数':spec['expected_accepted'],
                     '品質':spec['expected_quality'],'指紋':pin,'原板展開SHA256':plain}
    assert set(results)==set(NEW) and set(fixed)==set(matched)
    prep.save(HERE/'ナイト固定結果.json', {'対象':list(NEW),'旧ナイト一致件数':matched,
        '一致属性':list(fields),'後続夜を追加して一致した既存判断':int(prior.sum()),'入力':raws,'結果':results})
    print(json.dumps({s:{k:v for k,v in rec.items() if k!='建玉'} for s,rec in results.items()},ensure_ascii=False))


if __name__=='__main__':
    main()
