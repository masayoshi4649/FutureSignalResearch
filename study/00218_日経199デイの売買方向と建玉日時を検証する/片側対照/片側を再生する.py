"""日経199_02の固定入口を、両側・買い限定・売り限定の3口座で再生する。"""
import json
from pathlib import Path
import runpy

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
PREVIOUS = runpy.run_path(str(next((ROOT / 'study').glob('00217_*/日経/入口を再生する.py'))))
BOOKS = {'元の両側': 0, '買い限定': 1, '売り限定': -1}


def one_side(arrays: dict, sign: int) -> dict:
    """
    機能：固定条件が選んだ注文のうち、許可した向きだけを旧予約エンジンへ送る。
    引数：arrays（dict）は主・補完入口の時計・方向・幅など。sign（int）は買い1・売り−1・両側0。
    返り値：dictは同じ原行での主から補完への振替を禁止した口座入力。
    """
    if sign == 0:
        return arrays
    core = arrays['core']
    width = np.where(arrays['branches'] == 0, arrays['mw'], arrays['fw'])
    blocked_core = (core == -sign) & (width > 0)
    return dict(arrays, core=np.where(blocked_core, 0, core),
                branches=np.where(blocked_core, -1, arrays['branches']),
                technical=np.where(~blocked_core & (arrays['technical'] == sign), sign, 0))


def compare(dates: list, original: list, candidate: list, side: int) -> dict:
    """
    機能：同側取得原行で対応付け、元手法の取得と片側にした後の新しい取得を区別する。
    引数：dates（list）は45場、original・candidate（list）は元口座・片側口座、side（int）は買い0・売り1。
    返り値：dictは条件別・期間別成績と共通・差分件数、既知損益。
    """
    same_side = [t for t in original if t['side'] == side]
    assert all(t['side'] == side for t in candidate)
    old, new = [{(t['scene'], t['entry_line'], t['side']): t for t in values}
                for values in (same_side, candidate)]
    assert len(old) == len(same_side) and len(new) == len(candidate)
    common_keys = old.keys() & new.keys()
    matched_change = sum(old[k]['net'] != new[k]['net'] for k in common_keys)
    groups = {'共通の元の取得': [old[k] for k in common_keys],
              '共通の片側取得': [new[k] for k in common_keys],
              '元だけ': [old[k] for k in old.keys()-new.keys()],
              '片側だけ': [new[k] for k in new.keys()-old.keys()]}
    outcome = {k: {'件数': len(v), '既知収支': sum(t['net'] for t in v if t['net'] is not None),
                   '未知件数': sum(t['net'] is None for t in v)} for k, v in groups.items()}
    # ----------------------------------------
    totals = {}
    for name, rows in [('元の同側内訳', same_side), ('片側再生', candidate)]:
        spans = {'全45': dates, '前24': dates[:24], '後21': dates[24:],
                 '10月20日除外': [d for d in dates if not d.startswith('2026-10-20')]}
        daily, _ = PREVIOUS['SUMMARY']['calculate'](dates, rows, '全体')
        top = sorted((d for d in daily if d['確定収支'] is not None and d['収支'] > 0),
                     key=lambda d: (-d['収支'], d['場']))[:3]
        spans['各自の上位3日除外'] = [d for d in dates if d not in {r['場'] for r in top}]
        totals[name] = {label: PREVIOUS['SUMMARY']['calculate'](days, rows, '全体')[1]
                        for label, days in spans.items()}
    return {'共通原行で損益変更': matched_change, '入れ替わり': outcome, '期間': totals}


def main() -> None:
    """
    機能：元の両側を履歴照合し、片側の新規・補完・保有と単純IFDを全45日で再計算する。
    引数：なし。217と同じ日経の固定入力と原板数値索引を利用する。
    返り値：None。再現元帳をworkに、比較の要約を試行内に保存する。
    """
    dates, references, _ = PREVIOUS['SUMMARY']['sources']('デイ')
    reference = next(rows for key, rows in references.items() if '199' in key)
    ledgers = {name: [] for name in BOOKS}
    empty_days = {name: {} for name in BOOKS}
    used = set()
    for folder, archive, member, manifest in PREVIOUS['parts']():
        scenes, arrays, *_ = PREVIOUS['inputs'](folder, archive, member)
        indices = {s['session']: s for s in PREVIOUS['read'](manifest)['scenes']}
        for i, scene in enumerate(scenes):
            day = scene['session']
            if day not in dates or day in used:
                continue
            used.add(day)
            mask = arrays['scene'] == i
            events = {k: v[mask] for k, v in arrays.items()}
            index = PREVIOUS['FINANCE']['load_scene'](manifest.parent, indices[day])
            for name, sign in BOOKS.items():
                trades, audit = PREVIOUS['FINANCE']['account'](one_side(events, sign), i, scene, index, 1.0, 'NK225')
                assert audit['peak_global_reserved'] <= 1 and audit['filled'] == len(trades)
                ledgers[name].extend(trades)
                if not trades:
                    empty_days[name][day] = {k: audit[k] for k in ('effective_core_signal_events',
                                             'technical_eligible_before_first_fill', 'accepted_core',
                                             'accepted_technical', 'cancelled', 'capture_reason_core',
                                             'capture_reason_technical')}
    # ----------------------------------------
    assert used == set(dates) and len(used) == 45
    original = ledgers['元の両側']
    fields = ('scene', 'side', 'entry_line', 'entry_time', 'entry_price',
              'exit_line', 'exit_time', 'exit_price', 'net', 'label', 'confirmed_until')
    assert len(reference) == len(original) == 181
    assert all(tuple(r[k] for k in fields) == tuple(t[k] for k in fields)
               for r, t in zip(reference, original, strict=True))
    report = {'基準照合': {'全場数': len(dates), '建玉数': len(reference), '照合属性': list(fields)}, '未取得日': empty_days,
              '買い限定': compare(dates, original, ledgers['買い限定'], 0),
              '売り限定': compare(dates, original, ledgers['売り限定'], 1)}
    work = ROOT / 'work/218片側'
    work.mkdir(parents=True, exist_ok=True)
    (work / '比較元帳.json').write_text(json.dumps(ledgers, ensure_ascii=False, allow_nan=False), encoding='utf8')
    (HERE / '片側口座の比較.json').write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + '\n',
                                           encoding='utf8')


if __name__ == '__main__':
    main()
