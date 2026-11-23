"""旧固定元帳と追加分を結合し、商品・手法別に日別収支と安定性を集計する。"""
import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OLD = next((ROOT/'study').glob('00215_*'))
sys.path.insert(0,str(OLD))
import 日別に集計する as prior
from 集計 import median

JST = timezone(timedelta(hours=9))
NY = ZoneInfo('America/New_York')
LAST_DAY = '2026-11-20_Day'


# ----------------------------------------
def routed(trades: list) -> list:
    """
    機能：転送口座の先着記号と保有終点を共通表現に写す。
    引数：trades（list）は実際に取得した通知建玉。
    返り値：listは統一した元帳。
    """
    return [dict(t,label={'F':1,'A':-1,'N':0,'C':2}[t['label']],confirmed_until=t['known_until']) for t in trades]


def pack_rows(pack: dict) -> list:
    """
    機能：保存された旧候補の列形式元帳と保有時間を対応させる。
    引数：pack（dict）は日経199又はTOPIX212の固定パック。
    返り値：listは場・フェーズ・既知終点と費用後損益を含む建玉。
    """
    ledger = pack['ledger']
    result = []
    for i,pos in enumerate(pack['positions']):
        row = {k:v[i] for k,v in ledger.items()}
        assert row['scene']==pos['scene'] and row['entry_time']==pos['fill']
        label = row['label']
        if isinstance(label,str):
            label = {'F':1,'A':-1,'N':0,'C':2}[label]
        result.append(dict(row,label=label,confirmed_until=pos['confirmed_until']))
    assert len(result)==len(ledger['net'])
    return result


def sources(scope: str) -> tuple:
    """
    機能：評価対象の全場と候補別の元帳を構築する。未取得場を残す。
    引数：scope（str）はデイ、ナイト又はTOPIX専用デイ。
    返り値：tupleは対象シーン、候補別取引、既使用場数。
    """
    read = prior.read
    if scope=='デイ':
        dates, previous = prior.accounts()
        extra = [read(HERE/'日経/固定結果.json')['結果']['建玉'], read(HERE/'TOPIX/固定照合.json')['追加']['取得'],
                 routed(read(HERE/'通知と同期の結果.json')['通知対照'][LAST_DAY]['取得'])]
        books = {k.replace('215:','216:'):v+new for (k,v),new in zip(previous.items(),extra,strict=True)}
        return dates+[LAST_DAY],books,42
    # ----------------------------------------
    fixed = read(next((ROOT/'study').glob('00212_*/金融正本/*D1*NF_native*.gz')))
    native = read(HERE/'TOPIX専用/追加七場.json.gz')
    kind = 'NIGHT' if scope=='ナイト' else 'DAY'
    dates = sorted({r['scene'] for pack in (fixed,native) for r in pack['sessions'] if r['kind']==kind})
    combined = pack_rows(fixed)+pack_rows(native)
    tp = [t for t in combined if t['scene'] in dates]
    if kind=='DAY':
        assert len(dates)==45
        return dates,{'216:TOPIX専用212デイ':tp},42
    # ----------------------------------------
    nk = []
    for path in [next((ROOT/'study').glob('00199_*/保存金融/*02__*.gz')),next((ROOT/'study').glob('00199_*/追加二場/保存金融/*02__*.gz'))]:
        nk.extend(t for t in pack_rows(read(path)) if t['scene'] in dates)
    extra = read(HERE/'日経/ナイト固定結果.json')['結果']
    assert len(dates)==45 and sorted(extra)==dates[-4:]
    for r in extra.values():
        nk.extend(r['建玉'])
    return dates,{'216:日経199ナイト':nk,'216:TOPIX専用212ナイト':tp},41


def windows(scene: str, band: str) -> tuple:
    """
    機能：夜間の米国開始境界と締切から、保有率を測る時刻範囲を決める。
    引数：scene（str）は場名、band（str）は全体・米前・米後。
    返り値：tupleは開始と終了のUnix秒。
    """
    day = datetime.fromisoformat(scene[:10]).replace(tzinfo=JST)
    if scene.endswith('_Day'):
        return (day+timedelta(hours=8,minutes=45)).timestamp(),(day+timedelta(hours=15,minutes=30)).timestamp()
    start = day.replace(hour=17)
    us = datetime.combine(start.astimezone(NY).date(),datetime.min.time(),NY)+timedelta(hours=9,minutes=30)
    end = day+timedelta(days=1,hours=5,minutes=45)
    return (us if band=='米後' else start).timestamp(),(us if band=='米前' else end).timestamp()


def calculate(dates: list, trades: list, band: str) -> tuple:
    """
    機能：損益は注文判断の帯、実保有秒は各区間と重なる時間に帰属させる。
    引数：dates（list）は全対象場、trades（list）は一候補の全建玉、band（str）は集計帯。
    返り値：tupleは日別の辞書と期間全体の件数・損益・安定性。
    """
    daily, known_trades = [], []
    running = peak = dd = unknown_total = total_seconds = holding = 0
    totals = Counter()
    for day in dates:
        lower,upper = windows(day,band)
        group = [t for t in trades if t['scene']==day]
        assert all(a['exit_time'] is not None and a['exit_time']<b['entry_time'] for a,b in zip(group,group[1:]))
        held = sum(max(0,min(t['confirmed_until'],upper)-max(t['entry_time'],lower)) for t in group)
        assert 0<=held<=upper-lower
        chosen = group if band=='全体' else [t for t in group if t['phase']==(1 if band=='米前' else 2)]
        values = [t['net'] for t in chosen if t['net'] is not None]
        flags = Counter(t['label'] for t in chosen)
        assert set(flags)<={-1,0,1,2}
        profit = round(sum(v for v in values if v>0),2)
        loss = round(-sum(v for v in values if v<0),2)
        net = round(profit-loss,2)
        unknown = len(chosen)-len(values)
        counts = {'取得':len(chosen),'未知':unknown,'利益':profit,'損失':loss,'収支':net,
                  '勝':sum(v>0 for v in values),'敗':sum(v<0 for v in values),'順':flags[1],'逆':flags[-1],
                  '未到達':flags[0],'不足':flags[2]}
        totals.update(counts)
        known_trades.extend(values)
        holding += held
        total_seconds += upper-lower
        unknown_total += unknown
        running = round(running+net,2)
        peak = max(peak,running)
        dd = max(dd,round(peak-running,2))
        daily.append(dict(counts,場=day,確定収支=None if unknown else net,既知累計=running,
                          確定累計=None if unknown_total else running,保有率=held/(upper-lower)))
    known_days = [d['収支'] for d in daily if not d['未知']]
    m_trade = median(known_trades,unknown_total)
    m_day = median(known_days,len(dates)-len(known_days))
    summary = dict(totals,場数=len(dates),参加場=sum(d['取得']>0 for d in daily),黒字場=sum(v>0 for v in known_days),
                   赤字場=sum(v<0 for v in known_days),建玉中央値下限=m_trade['lower'],建玉中央値上限=m_trade['upper'],
                   場中央値下限=m_day['lower'],場中央値上限=m_day['upper'],保有率=holding/total_seconds,場末DD既知=dd)
    for k in ('利益','損失','収支'):
        summary[k] = round(summary[k],2)
    return daily,summary


def main() -> None:
    """
    機能：候補別の全45場を既存CSV作成器の型付き表へ変換する。
    引数：CLIの対象（str）はデイ・ナイト・TOPIX専用デイ。
    返り値：None。安定性の期間集計と中間表を保存する。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('対象',choices=('デイ','ナイト','TOPIX専用デイ'))
    scope = parser.parse_args().対象
    dates, books, used = sources(scope)
    spans = {'既使用期間':dates[:used], **{d[:10]:[d] for d in dates[used:]},'固定後追加':dates[used:],'全45場':dates}
    summary_keys = '場数 参加場 取得 未知 利益 損失 収支 勝 敗 順 逆 未到達 不足 黒字場 赤字場 保有率 建玉中央値下限 建玉中央値上限 場中央値下限 場中央値上限 場末DD既知'.split()
    summary_cols = '場数 参加場数 建玉回数 未知件数 既知利益円 既知損失円 既知収支円 利益取引件数 損失取引件数 順先着件数 逆先着件数 未到達件数 不足件数 黒字場数 赤字場数 保有時間率下限 建玉中央値下限円 建玉中央値上限円 場中央値下限円 場中央値上限円 場末DD既知円'.split()
    daily_keys = '利益 損失 収支 確定収支 既知累計 確定累計 取得 未知 敗 順 逆 未到達 不足 保有率'.split()
    daily_cols = '既知利益円 既知損失円 既知収支円 確定収支円 既知累計円 確定累計円 建玉回数 未知件数 既知赤字取引件数 順先着件数 逆先着件数 未到達件数 不足件数 保有時間率下限'.split()
    label = 'ナイト' if scope=='ナイト' else 'デイ'
    views = {label:'全体'}
    if scope=='ナイト':
        views.update({'ナイト_米前':'米前','ナイト_米後':'米後'})
    tables = {'候補比較':{'headers':['候補','期間']+summary_cols,'rows':[]}}
    for name in views:
        tables[name] = {'headers':['候補','セッション','区分']+daily_cols,'rows':[]}
    report = {}
    for candidate,trades in books.items():
        report[candidate] = {}
        for name, subset in spans.items():
            _, metrics = calculate(subset,trades,'全体')
            report[candidate][name] = metrics
            tables['候補比較']['rows'].append([candidate,name]+[metrics[k] for k in summary_keys])
        for name,band in views.items():
            daily,_ = calculate(dates,trades,band)
            for i,row in enumerate(daily):
                tag = '既使用' if i<used else ('今回最新' if i==len(dates)-1 else '固定後追加')
                tables[name]['rows'].append([candidate,row['場'],tag]+[row[k] for k in daily_keys])
    # ----------------------------------------
    work = ROOT/'work/216閲覧'
    work.mkdir(parents=True,exist_ok=True)
    names = {'候補比較':'集計',**{n:n for n in views}}
    for path,value in [(HERE/(scope+'の期間別成績.json'),report),(work/(scope+'の型付き入力.json'),{'tableNames':names,'tables':tables})]:
        path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf8')


if __name__ == '__main__':
    main()
