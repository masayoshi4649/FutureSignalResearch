"""通知03の経路効率だけを近傍値へ動かし、45日で同じ口座を再生する。"""
import json
import sys

import 入口を比較する as primary
sys.path.insert(0,str(next((primary.ROOT/'study').glob('00216_*'))))
from 全場を集計する import calculate

LEVELS = (0.25, 0.30, 0.35, 0.40, 0.45)


def vetoes(tp: dict, nk: dict) -> list:
    """
    機能：12分逆行時のみ、経路効率に対する事前固定の近傍閾値を適用する。
    引数：tp・nk（dict）は通知直前の確定1分気配足の特徴。日経の追加特徴は使用しない。
    返り値：listは基準と各閾値についての見送り真偽。
    """
    return [False, *(tp['r12']<0 and tp['efficiency']>=cut for cut in LEVELS)]


def main() -> None:
    """
    機能：閾値を再選択せず、幅の近傍でも将来期間側・集中日除外側が同様か確認する。
    引数：なし。通知の主比較が完了していること。
    返り値：None。数値と判断差を当フォルダのJSONへ保存する。
    """
    working = primary.WORK
    baseline = primary.read(working/'比較元帳.json')
    dates = sorted({row[0] for row in primary.read(working/'通知採否.json')['通知00']})
    rules = {'通知00':'固定対照', **{f'通知感度{c*100:.0f}':'経路効率を比較' for c in LEVELS}}
    primary.replay(working/'感度',rules,vetoes)
    books = primary.read(working/'感度/比較元帳.json')
    assert books['通知感度35']==baseline['通知03']
    assert books['通知00']==baseline['通知00']
    output = {}
    for key,book in books.items():
        days,full = calculate(dates,book,'全体')
        largest = [d['場'] for d in sorted((d for d in days if not d['未知']),key=lambda x:-x['収支'])[:3]]
        original = {(t['scene'],t['signal_time']):t['net'] for t in books['通知00']}
        candidate = {(t['scene'],t['signal_time']):t['net'] for t in book}
        removed = [original[k] for k in original.keys()-candidate.keys()]
        gained = [candidate[k] for k in candidate.keys()-original.keys()]
        output[key] = {'全45':full,'後21':calculate(dates[24:],book,'全体')[1],
                       '除外建玉':[len(removed),sum(v is None for v in removed),round(sum(v for v in removed if v is not None),1)],
                       '追加建玉':[len(gained),sum(v is None for v in gained),round(sum(v for v in gained if v is not None),1)],
                       '自身上位3除外':calculate([d for d in dates if d not in largest],book,'全体')[1]}
    (primary.HERE/'効率閾値の感度.json').write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    baseline.update({k:b for k,b in books.items() if k not in {'通知00','通知感度35'}})
    (working/'比較元帳.json').write_text(json.dumps(baseline,ensure_ascii=False,allow_nan=False),encoding='utf8')


if __name__=='__main__':
    main()
