"""固定台帳から候補ごとの全デイの日次損益と期間集計を作成する。"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PREVIOUS = next((ROOT/'study').glob('00213_*'))
sys.path.insert(0, str(PREVIOUS))
from 金融再生 import read
from 集計 import nikkei, summarize, SECONDS


# ----------------------------------------
def accounts() -> tuple:
    """
    機能：両指数の固定台帳と日経通知から建てた別口座を追加日まで連結する。
    引数：なし。過去の金融正本と追加日の金融明細を参照する。
    返り値：tupleは全評価日の列と候補名をキーにした建玉明細。
    """
    nk = nikkei()['取得'] + read(HERE/'日経/固定結果.json')['結果']['建玉']
    tp_old = read(next((PREVIOUS/'金融正本').glob('*_03*.gz')))
    tp = tp_old['取得'] + read(HERE/'TOPIX/固定照合.json')['追加']['取得']
    previous = read(PREVIOUS/'日経取得通知の対照/結果.json')
    extra = read(HERE/'通知と同期の結果.json')['通知対照']
    routed = previous['取引'] + [row for value in extra.values() for row in value['取得']]
    # 213の共通集計器用に先着・保有終点を表現変換。通知口座は独立して約定済み。
    follow = [dict(r, label={'F':1,'A':-1,'N':0,'C':2}[r['label']],
                   confirmed_until=r['known_until'], added=False, origin=0) for r in routed]
    dates = sorted(set(previous['セッション']) | set(extra))
    assert dates == sorted(set(tp_old['監査']) | {dates[-1]}) and len(dates)==44
    return dates, {'215:日経199_02':nk,'215:TOPIX移植03':tp,'215:日経通知でTOPIX':follow}


# ----------------------------------------
def main() -> None:
    """
    機能：44デイを時系列に集計し、各表の型付き入力と既知収支の照合票を作る。
    引数：なし。損益は費用後、未知を含む場の確定値は空欄。
    返り値：None。CSV生成器用入力を作業域へ、期間別成績を試行フォルダへ保存する。
    """
    dates, books = accounts()
    spans = {'既使用42日':dates[:-2], '11月18日':dates[-2:-1], '11月19日':dates[-1:],
             '追加2日':dates[-2:], '全44日':dates}
    columns = ['候補','期間','場数','参加場数','建玉回数','未知件数','既知利益円','既知損失円','既知収支円',
               '確定収支円','利益取引数','損失取引数','順先着件数','逆先着件数','未到達件数','不足件数',
               '黒字場数','赤字場数','保有時間率下限','建玉中央値下限円','建玉中央値上限円',
               '場中央値下限円','場中央値上限円','場末DD既知円']
    daily_columns = ['候補','セッション','区分','既知利益円','既知損失円','既知収支円','確定収支円',
                     '既知累計円','確定累計円','建玉回数','未知件数','既知赤字取引件数','順先着件数','逆先着件数',
                     '未到達件数','不足件数','保有時間率下限']
    totals, daily, report = [], [], {}
    for candidate, trades in books.items():
        report[candidate] = {}
        for name, days in spans.items():
            summary, rows = summarize(trades, days)
            wins = sum(t['net'] is not None and t['net']>0 for t in trades if t['scene'] in days)
            record = [candidate,name,summary['場数'],summary['参加場'],summary['取得'],summary['未知'],
                      summary['利益'],summary['損失'],summary['収支'],None if summary['未知'] else summary['収支'],
                      wins,summary['赤字取引'],summary['順'],summary['逆'],summary['未到達'],summary['不足'],
                      summary['黒字場'],summary['赤字場'],summary['保有率下限'],summary['建玉中央値']['lower'],
                      summary['建玉中央値']['upper'],summary['場中央値']['lower'],summary['場中央値']['upper'],
                      summary['場末DD既知寄与']]
            totals.append(record)
            report[candidate][name] = dict(zip(columns[2:],record[2:],strict=True))
            if name != '全44日':
                continue
            unknown_seen = False
            for d in rows:
                tag = '旧42日' if d['場'] < dates[-2] else ('11月18日' if d['場']==dates[-2] else '今回追加')
                unknown_seen |= bool(d['未知'])
                daily.append([candidate,d['場'],tag,d['利益'],d['損失'],d['収支'],None if d['未知'] else d['収支'],
                              d['既知累計'],None if unknown_seen else d['既知累計'],d['取得'],d['未知'],d['赤字取引'],
                              d['順'],d['逆'],d['未到達'],d['不足'],d['保有秒下限']/SECONDS])
        assert report[candidate]['全44日']['既知収支円'] == round(
            report[candidate]['既使用42日']['既知収支円'] + report[candidate]['追加2日']['既知収支円'], 2)
    # ----------------------------------------
    typed = {'tableNames':{'候補比較':'集計','デイ':'デイ'}, 'tables':{
        '候補比較':{'headers':columns,'rows':totals}, 'デイ':{'headers':daily_columns,'rows':daily}}}
    work = ROOT/'work/215閲覧'
    work.mkdir(parents=True,exist_ok=True)
    for path, data in [(work/'型付き入力.json',typed),(HERE/'期間別成績.json',report)]:
        path.write_text(json.dumps(data,ensure_ascii=False,allow_nan=False,indent=2)+'\n',encoding='utf8')


if __name__=='__main__':
    main()
