"""同じ取引集合から通知転送対照の候補別閲覧入力を作る。"""
from pathlib import Path
import argparse
import json

HERE = Path(__file__).resolve().parent
ID = '213:日経取得通知でTOPIX追随'


# ----------------------------------------
def tables(report: dict) -> dict:
    """
    機能：未知を満額の確定利益に含めず、全42日・決済実績の日別台帳を作る。
    引数：report（dict）は再計算された通知・約定結果。
    返り値：dictは既存CSV出力器で使う候補比較・日別の型付き表。
    """
    days = report['セッション']
    result = report['成績']
    summary = {'headers':['候補','対象','場数','参加場数','通知回数','建玉回数','金融未知件数',
                         '既知利益円','既知損失円','既知収支円','確定収支円','保有時間率下限',
                         '全建玉中央値下限円','全場中央値下限円'],
               'rows':[[ID,'デイ',len(days),report['参加場'],len(report['全通知']),result['取得'],result['未知'],
                        result['利益'],result['損失'],result['収支'],None if result['未知'] else result['収支'],
                        report['保有率下限'],report['全建玉中央値範囲'][0],report['全場中央値範囲'][0]]]}
    table = {'headers':['候補','セッション','通知回数','建玉回数','金融未知件数','既知利益円','既知損失円',
                       '既知収支円','確定収支円','既知累計収支円','確定累計収支円','保有時間率下限'],
             'rows':[]}
    running=0
    unknown=0
    for day,values in sorted(days.items()):
        running=round(running+values['収支'],1)
        unknown+=values['未知']
        assert len([r for r in report['取引'] if r['scene']==day])==values['取得']
        table['rows'].append([ID,day,values['通知数'],values['取得'],values['未知'],values['利益'],
                              values['損失'],values['収支'],None if values['未知'] else values['収支'],
                              running,None if unknown else running,values['保有下限秒']/24300])
    assert len(table['rows'])==42 and running==result['収支'] and unknown==result['未知']
    return {'tableNames':{'候補比較':'集計','デイ':'デイ'},'tables':{'候補比較':summary,'デイ':table}}


# ----------------------------------------
def main() -> None:
    """
    機能：保存済みの診断から、候補一件の日別閲覧用JSONを作成する。
    引数：--result/--output（Path）は入力結果と出力先。
    返り値：None。
    """
    parser=argparse.ArgumentParser()
    parser.add_argument('--result',type=Path,default=HERE/'結果.json')
    parser.add_argument('--output',type=Path,default=HERE/'型付き入力.json')
    args=parser.parse_args()
    data=tables(json.loads(args.result.read_bytes()))
    args.output.write_text(json.dumps(data,ensure_ascii=False,separators=(',',':'))+'\n',encoding='utf-8')


if __name__=='__main__':
    main()
