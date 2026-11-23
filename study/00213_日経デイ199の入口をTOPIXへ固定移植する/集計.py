"""日経からの移植比較を旧42デイと追加デイに分け、未知と未参加を含めて集計する。"""
from argparse import ArgumentParser
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
import gzip
import json
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / 'work/173追加なしの評価'))
from metrics173 import median_bounds

SECONDS = 6.75 * 3600
JST = timezone(timedelta(hours=9))


# ----------------------------------------
def nikkei() -> dict:
    """
    機能：固定済み日経台帳の42日と、比較条件を固定して適用した11月18日を結合する。
    引数：なし。
    返り値：dictは全43場を同じ集計へ渡すための元帳。
    """
    old = next((ROOT/'study').glob('00199_*'))
    trades = []
    for folder in (old/'保存金融', old/'追加二場/保存金融'):
        path = next(folder.glob('*02__C0_IFD.json.gz'))
        ledger = json.loads(gzip.decompress(path.read_bytes()))['ledger']
        for i,scene in enumerate(ledger['scene']):
            if scene.endswith('_Day'):
                t = {k:v[i] for k,v in ledger.items()}
                assert t['known']
                t.update(gross=t['net']+1077, confirmed_until=t['exit_time'])
                trades.append(t)
    assert len(trades)==162 and sum(t['net'] for t in trades)==1057526
    new = json.loads((HERE/'日経の追加デイ/追加デイの照合結果.json').read_bytes())
    trades.extend(new['結果']['純入口']['建玉'])
    assert len(trades)==168 and all(t['scene'].endswith('_Day') for t in trades)
    return {'取得':trades, '監査':{t['scene']:{} for t in trades}}


# ----------------------------------------
def money(value: float) -> float:
    """
    機能：一枚あたりの手数料を含む円表示を整える。
    引数：value（float）は円額。
    返り値：floatは小数第2位までの円額。
    """
    return round(value, 2)


# ----------------------------------------
def median(values: list, unknown: int) -> dict:
    """
    機能：未知を含めた中央値の上下限を計算し、金額の浮動小数誤差を除く。
    引数：values（list）は判明した円額、unknown（int）は不明な件数。
    返り値：dictは全件・既知のみの中央値と符号の範囲。
    """
    bounds = median_bounds(values, unknown)
    return {k:money(v) if isinstance(v,float) else v for k,v in bounds.items()}


# ----------------------------------------
def describe(trades: list) -> dict:
    """
    機能：既知損益と未知件数・利益損失・先着の内訳を集計する。
    引数：trades（list）は指定範囲に属する全取得。
    返り値：dictは未知を含めた建玉中央値の境界と既知損益。
    """
    nets = [t['net'] for t in trades if t['net'] is not None]
    unknown = len(trades) - len(nets)
    gross = money(sum(t['gross'] for t in trades if t['gross'] is not None))
    profit = money(sum(v for v in nets if v > 0))
    loss = money(-sum(v for v in nets if v < 0))
    known = money(sum(nets))
    signs = Counter(t['label'] for t in trades)
    assert money(profit - loss) == known
    return {'取得':len(trades), '未知':unknown, '利益':profit, '損失':loss, '収支':known,
            '費用前':gross, '費用':money(gross-known), '順':signs[1], '逆':signs[-1],
            '未到達':signs[0], '不足':signs[2], '赤字取引':sum(v < 0 for v in nets),
            '建玉中央値':median(nets, unknown)}


# ----------------------------------------
def summarize(trades: list, dates: list) -> tuple:
    """
    機能：未参加をゼロ、未確定損益は不明として全場の成績・集中・保有率を得る。
    引数：trades（list）は元帳、dates（list）は全対象場名。
    返り値：tupleは期間集計と場別結果。
    """
    selected = [t for t in trades if t['scene'] in dates]
    result = describe(selected)
    daily = []
    path = peak = drawdown = 0
    for date in dates:
        subset = [t for t in selected if t['scene'] == date]
        row = describe(subset)
        held = sum(t['confirmed_until'] - t['entry_time'] for t in subset)
        assert 0 <= held <= SECONDS
        assert all(t['exit_time'] is not None and t['exit_time'] < u['entry_time']
                   for t, u in zip(subset, subset[1:]))
        path = money(path + row['収支'])
        peak = max(peak, path)
        drawdown = max(drawdown, money(peak - path))
        daily.append({'場':date, **row, '既知累計':path, '保有秒下限':held})
    values = [r['収支'] for r in daily if r['未知'] == 0]
    known_positive = [r['収支'] for r in daily if r['収支'] > 0]
    groups = {'補完':[], '長期補完LC':[], '通常':[]}
    for trade in selected:
        label = '補完' if trade['origin'] == 2 else '長期補完LC' if trade['added'] else '通常'
        groups[label].append(trade)
    early = [t for t in selected if datetime.fromtimestamp(t['entry_time'],JST).hour < 9]
    result.update(場数=len(daily), 参加場=sum(r['取得'] > 0 for r in daily), 黒字場=sum(v>0 for v in values),
                  赤字場=sum(v<0 for v in values), 場中央値=median(values, len(daily)-len(values)),
                  保有率下限=sum(r['保有秒下限'] for r in daily)/(len(daily)*SECONDS),
                  場末DD既知寄与=drawdown, 最大赤字場既知寄与=min(r['収支'] for r in daily),
                  上位3場除外収支既知寄与=money(path-sum(sorted(known_positive,reverse=True)[:3])),
                  経路別={name:describe(rows) for name,rows in groups.items()}, 九時前=describe(early))
    return result, daily


# ----------------------------------------
def main() -> None:
    """
    機能：候補ごとの元帳を読み、型付きCSV入力と診断を作る。
    引数：CLI --folder（Path）、--typed（Path）、--summary（Path）。
    返り値：None。候補の混在する閲覧CSVは作成しない。
    """
    parser = ArgumentParser()
    parser.add_argument('--folder', required=True, type=Path)
    parser.add_argument('--typed', required=True, type=Path)
    parser.add_argument('--summary', required=True, type=Path)
    args = parser.parse_args()
    totals, records, details = [], [], {}
    packs = [(file.name.split('.')[0].replace('_', ':', 1),json.loads(gzip.decompress(file.read_bytes())))
             for file in sorted(args.folder.glob('*.json.gz'))]
    for candidate, pack in [('213:00日経199_02',nikkei()), *packs]:
        dates = sorted(pack['監査'])
        assert len(dates)==43 and dates[-1]=='2026-11-18_Day'
        spans = {'旧42日':dates[:-1], '旧前48場のデイ':dates[:24], '旧後25場のデイ':dates[24:37],
                 '追加7場のデイ':dates[37:40], '11月16日':dates[40:41], '11月17日':dates[41:42],
                 '追加11月18日':dates[-1:], '全43日':dates}
        details[candidate] = {}
        for name, period in spans.items():
            row, daily = summarize(pack['取得'], period)
            details[candidate][name] = row
            totals.append([candidate, name, row['場数'], row['参加場'], row['取得'], row['未知'],
                           row['利益'], row['損失'], row['収支'], row['費用前'], row['費用'],
                           row['赤字場'], row['保有率下限'], row['建玉中央値']['lower'],
                           row['場中央値']['lower'], row['場末DD既知寄与']])
            if name == '全43日':
                unknown_seen = False
                for d in daily:
                    unknown_seen |= bool(d['未知'])
                    records.append([candidate, d['場'], '既使用比較' if d['場'] != dates[-1] else '追加デイ',
                                    d['利益'], d['損失'], d['収支'], None if d['未知'] else d['収支'],
                                    d['既知累計'], None if unknown_seen else d['既知累計'],
                                    d['取得'], d['未知'], d['赤字取引'], d['順'], d['逆'], d['未到達'],
                                    d['不足'], d['保有秒下限']/SECONDS])
    assert details
    typed = {'tableNames':{'候補比較':'集計','デイ':'デイ'}, 'tables':{
        '候補比較':{'headers':['候補','期間','場数','参加場数','建玉回数','未知件数','既知利益円','既知損失円',
                            '既知収支円','既知費用前円','既知費用円','確定赤字場数','保有時間率下限',
                            '建玉中央値下限円','場中央値下限円','場末DD既知円'], 'rows':totals},
        'デイ':{'headers':['候補','セッション','区分','既知利益円','既知損失円','既知収支円','確定収支円',
                        '既知累計円','確定累計円','建玉回数','未知件数','既知赤字取引件数','順先着件数','逆先着件数',
                        '未到達件数','不足件数','保有時間率下限'], 'rows':records}}}
    for path, value in [(args.typed,typed),(args.summary,details)]:
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')


if __name__ == '__main__':
    main()
