"""前24日で通知条件を選び、残りと集中日の影響を別に記録する。"""
from collections import Counter
from pathlib import Path
import json
import sys

from 入口を比較する import ROOT, HERE, WORK, RULES, read, follow
sys.path.insert(0,str(next((ROOT/'study').glob('00216_*'))))
from 全場を集計する import calculate


def main() -> None:
    """
    機能：既知の日別損益を時系列で比較し、10月20日と上位3日を外した成績を得る。
    引数：なし。生成済みの候補別元帳・通知の採否・指紋を使う。
    返り値：None。候補・選択規則・全探索の期間別成績を正式なJSONへ出力する。
    """
    books = {k:v for k,v in read(WORK/'比較元帳.json').items() if k in RULES}
    decisions = read(WORK/'通知採否.json')
    dates = sorted({r[0] for r in decisions['通知00']})
    common, _ = calculate(dates,books['通知00'],'全体')
    top = [d['場'] for d in sorted((d for d in common if not d['未知']),key=lambda r:-r['収支'])[:3]]
    # ----------------------------------------
    values = {}
    for rule,book in books.items():
        daily,full = calculate(dates,book,'全体')
        own = [d['場'] for d in sorted((d for d in daily if not d['未知']),key=lambda r:-r['収支'])[:3]]
        parts = {'前24':dates[:24],'後21':dates[24:],'末尾3':dates[-3:],'前24を除く後半から末尾3を除外':dates[24:-3],
                 '10月20日のみ':['2026-10-20_Day'],'10月20日除外':[d for d in dates if not d.startswith('2026-10-20')],
                 '基準の上位3日除外':[d for d in dates if d not in top],'自身の上位3日除外':[d for d in dates if d not in own]}
        reference = {(t['scene'],t['signal_time']) for t in books['通知00']}
        realized = {(t['scene'],t['signal_time']) for t in book}
        values[rule] = {'条件':RULES[rule],'元帳からの新取得':len(realized-reference),'元帳からの除外':len(reference-realized),
                        '自身の上位3日':own,'通知処理':dict(Counter(d[2] for d in decisions[rule])),
                        '全45':full, **{k:calculate(v,book,'全体')[1] for k,v in parts.items()}}
    # ----------------------------------------
    baseline = values['通知00']['前24']
    scores = {}
    for rule,v in values.items():
        t = v['前24']
        if (t['参加場']>=baseline['参加場']-1 and t['取得']>=.8*baseline['取得'] and t['保有率']>=.2
                and t['建玉中央値下限']>0 and t['場中央値下限']>0):
            scores[rule] = (t['赤字場'],t['場末DD既知'],t['損失'],rule)
    selected = min(scores,key=scores.get) if scores else None
    result = {'対象':dates,'固定対照全取引一致':len(books['通知00']),'通知総数':len(decisions['通知00']),
              '抽出コードSHA256':follow.digest(HERE/'入口を比較する.py'),'入力指紋':read(WORK/'入力指紋.json'),
              '基準上位3日':top,'前24選択':selected,'前24適格順位':sorted(scores,key=scores.get),'全候補':values}
    output = HERE/'期間と集中日の比較.json'
    output.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf8')
    for rule,v in values.items():
        q = lambda s,k:v[s][k]
        print(rule, '前24', [q('前24',k) for k in ('参加場','赤字場','場末DD既知','損失')],
              '後21',[q('後21',k) for k in ('参加場','赤字場','場末DD既知','収支')],
              '全場',[q('全45',k) for k in ('取得','参加場','赤字場','収支','場末DD既知')],
              '上位3除外収支',q('自身の上位3日除外','収支'))
    print('前24の選抜',selected, '基準上位3日',top)


if __name__=='__main__':
    main()
