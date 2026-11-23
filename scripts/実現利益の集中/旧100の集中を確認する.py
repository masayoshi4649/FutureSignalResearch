"""既存集計と開始日別の実収支だけから利益の集中を調べる。"""

import argparse
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
P0_KEYS = tuple('E3S_B5Q_P0_C'+str(c)+'_D'+str(d) for c in (0,5) for d in (0,1))


def need(value, label):
    """
    機能: 集計額や日別集合の不一致を拒否する。
    引数: value(bool)、label(str)は条件と説明。
    返り値: None。不一致時はValueError。
    """
    if not value:
        raise ValueError(label)


def amount(value):
    """
    機能: 保存した有限金額を丸めず十進数へ揃える。
    引数: value(int|float|Decimal)は既存の金額。
    返り値: Decimalは有限の金額。bool/文字列を金額へ補完しない。
    """
    need(type(value) in (int,float,Decimal),'金額の型')
    result = Decimal(str(value))
    need(result.is_finite(),'非有限金額')
    return result


def number(value):
    """
    機能: 円・半円の保存値をJSON数値へ戻す。
    引数: value(Decimal)は円額。
    返り値: int|floatは元金額。半円より細かい値を黙って丸めない。
    """
    need(value*2 == (value*2).to_integral_value(),'円/半円以外の金額')
    return int(value) if value == value.to_integral_value() else float(value)


def fraction(numerator, denominator):
    """
    機能: 分母付きの利益寄与を表示用十進文字列にする。
    引数: numerator/denominator(Decimal)は円額。
    返り値: dictは分子/分母円と比率。分母0はnull。
    """
    return {'分子円':number(numerator),'分母円':number(denominator),
            '比率':None if denominator == 0 else str(numerator/denominator)}


def concentration(daily):
    """
    機能: 同じ成立取引の日別実収支を1開始日ずつ除いた記述統計を得る。
    引数: daily(list[tuple[str,Decimal]])は開始日と費用後実収支。
    返り値: dictは除外後min/max・正負ゼロ日数・最良日寄与。仮想約定は作らない。
    """
    need(bool(daily) and len({day for day,_ in daily}) == len(daily),'開始日空/重複')
    need(all(re.fullmatch(r'\d{4}-\d{2}-\d{2}',day) is not None for day,_ in daily),'開始日形式')
    daily = [(day,amount(net)) for day,net in daily]
    total = sum((net for _,net in daily),Decimal(0))
    best, worst = max(net for _,net in daily), min(net for _,net in daily)
    removed = [total-net for _,net in daily]
    positives = sum((net for _,net in daily if net>0),Decimal(0))
    return {'開始日数':len(daily),'実収支円':number(total),
            '黒字開始日':sum(net>0 for _,net in daily),'赤字開始日':sum(net<0 for _,net in daily),
            'ゼロ開始日':sum(net==0 for _,net in daily),
            '最良開始日':[day for day,net in daily if net==best],'最良日実収支円':number(best),
            '最良開始日を1つ除いた実収支円':number(total-best),
            '各開始日を1つ除いた実収支min円':number(min(removed)),
            '各開始日を1つ除いた実収支max円':number(max(removed)),
            '最大除外後収支を作る開始日':[day for day,net in daily if net==worst],
            '最良日の寄与_総純額分母':fraction(best,total),
            '最良日の寄与_黒字日の正額合計分母':fraction(best,positives)}


def analyze_summary(value, keys=P0_KEYS):
    """
    機能: 結果JSONの集計/日別だけを対象Actorへ射影して検算する。
    引数: value(dict)、keys(tuple[str])は既存結果と事前に指定したActor。
    返り値: dictはActor別の集中。Native/場内経路や退出後価格を参照しない。
    """
    need(value['成功'] is True and value['場数']==54 and value['会計数']==54*value['Actor数'],'完成54集計だけ')
    result, common_days = {}, None
    for key in keys:
        rows = [row for row in value['日別'] if row['key']==key]
        need(len(rows)==27 and all(type(row['場数']) is int and row['場数']==2 for row in rows),'Day/Night合算の27開始日')
        days = {row['日'] for row in rows}
        need(len(days)==27 and (common_days is None or days==common_days),'全感度の同一開始日集合')
        common_days = days
        total = value['集計'][key]
        for column in ('gross_yen','fee_yen','slip_yen','gross_minus_fee_yen','net_yen','closed_net_yen'):
            need(sum((amount(row['totals'][column]) for row in rows),Decimal(0)) == amount(total[column]), '日別/集計総額差:'+key+'/'+column)
        for row in rows:
            t=row['totals']
            need(amount(t['gross_yen'])-amount(t['fee_yen'])==amount(t['gross_minus_fee_yen'])
                 and amount(t['gross_minus_fee_yen'])-amount(t['slip_yen'])==amount(t['net_yen'])
                 and amount(t['net_yen'])==amount(t['closed_net_yen']), '日別の費用/完結額差')
        result[key] = concentration([(row['日'],amount(row['totals']['net_yen'])) for row in rows])
        result[key]['無取引開始日'] = sum(row['totals']['entry_quantity']==0 for row in rows)
        result[key]['取引ありゼロ収支開始日'] = sum(row['totals']['entry_quantity']>0 and amount(row['totals']['net_yen'])==0 for row in rows)
        result[key]['感度運転'] = 'C0/C5/D0/D1は動的別運転。固定の費用控除で差を再作成しない。'
    return result


def render(result):
    """
    機能: 4感度の実利益集中と限定scopeを短いMarkdownへ整形する。
    引数: result(dict)は入力SHA付き分析。
    返り値: strは既使用開始日を除いた記述統計。新しい合格gateは設けない。
    """
    lines=['# 旧100 P0の実現利益の開始日集中','',
           '固定100の既使用54場・27開始日のDay/Night合算を用いる。同じ成立取引の実収支を開始日単位で1つ除いた記述統計であり、約定を変更した再運転ではない。未知期間の安定性は主張しない。','',
           '|感度|全実収支円|最良開始日・円|最良日1つ除外円|1日ずつ除外min〜max円|黒/赤/ゼロ開始日|',
           '|---|---:|---|---:|---:|---|']
    for key,row in result['Actor別'].items():
        name=key.removeprefix('E3S_B5Q_P0_')
        lines.append('|'+name+'|'+str(row['実収支円'])+'|'+','.join(row['最良開始日'])+' / '+str(row['最良日実収支円'])+'|'
                     +str(row['最良開始日を1つ除いた実収支円'])+'|'+str(row['各開始日を1つ除いた実収支min円'])+'〜'+str(row['各開始日を1つ除いた実収支max円'])+'|'
                     +'/'.join(str(row[k]) for k in ('黒字開始日','赤字開始日','ゼロ開始日'))+' / 27|')
    lines += ['', '最良日の利益寄与は、最良日の費用後純額を全27日の純額で割る場合と、黒字開始日の正額合計で割る場合を別記した。前者は他日の損失を相殺するため100%を超え得る。勝率・ROI・因果効果ではない。分母0はnullとする。','']
    for key,row in result['Actor別'].items():
        a=row['最良日の寄与_総純額分母'];b=row['最良日の寄与_黒字日の正額合計分母']
        f=lambda d:'未定義' if d['比率'] is None else format(Decimal(d['比率'])*100,'.2f')+'%'
        lines.append('- '+key.removeprefix('E3S_B5Q_P0_')+'：総純額分母 '+str(a['分子円'])+'/'+str(a['分母円'])+' = '+f(a)+'。黒字日の正額合計分母 '+str(b['分子円'])+'/'+str(b['分母円'])+' = '+f(b)+'。')
    lines += ['', '式：T=Σ日別net、最良日b=max(日別net)、最良日除外=T−b、各1日除外の範囲=[T−max(日別net), T−min(日別net)]。同額の最良日が複数あれば日付を全て示し、1日だけを除く。ゼロ開始日は無取引を含む。','',
              'C5は想定5ptを組み込んだ別運転であり、C0額から一定額を引いた成績ではない。既使用データ内の集中を示すだけで、日付の除外を新しい売買ルールへ採用しない。機会損失、未参加/決済後の仮想利益、将来ピーク、仮想約定、ブートストラップ、新合格gateは使っていない。','',
              '入力：`'+result['入力']['path']+'`。SHA256 `'+result['入力']['SHA256']+'`。使用欄は完成metadata・`集計`・`日別`。Native/Raw/Tape/101途中出力は未読。','']
    return '\n'.join(lines)


def main():
    """
    機能: Root指定の既存結果だけを読み、新規JSON/MDへ保存する。
    引数: CLI --input(Path)/--input-sha(str)/--out(Path)は固定入力と新出力。
    返り値: None。既存成果物を上書きせず、前後SHAを確認する。
    """
    parser=argparse.ArgumentParser()
    parser.add_argument('--input',type=Path,required=True)
    parser.add_argument('--input-sha',required=True)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    need(re.fullmatch('[0-9a-f]{64}',args.input_sha or '') is not None,'未固定入力SHA')
    before=hashlib.sha256(args.input.read_bytes()).hexdigest()
    need(before==args.input_sha,'入力SHA差')
    data=json.loads(args.input.read_text(encoding='utf-8'),parse_float=Decimal)
    actors=analyze_summary(data)
    after=hashlib.sha256(args.input.read_bytes()).hexdigest()
    need(before==after,'入力前後差')
    result={'成功':True,'確認日':'2026-11-09','試行':data['試行'],'開始日数':27,'場数':54,
            '入力':{'path':str(args.input.resolve().relative_to(ROOT)).replace('\\','/'),'SHA256':before,'使用欄':['完成metadata','集計','日別']},
            'コードSHA256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'Actor別':actors,
            '式':{'最良日除外':'Σ日別net−max(日別net)','1日ずつ除外min':'Σ日別net−max(日別net)',
                  '1日ずつ除外max':'Σ日別net−min(日別net)','開始日':'日別に保存済みの同開始日Day/Night合算'},
            '前後不変':True,'未知期間の安定性実証':False,'新合格gate':False,'機会損失算出':False,
            'Native/Raw/Tape/101途中出力読取':0,'仮想約定/退出後値幅/金融再生':0}
    files=[args.out/'結果.json',args.out/'メモ.md']
    need(not any(p.exists() for p in files),'出力既存')
    args.out.mkdir(parents=True,exist_ok=True)
    with files[0].open('x',encoding='utf-8',newline='\n') as stream:
        json.dump(result,stream,ensure_ascii=False,indent=2)
        stream.write('\n')
    files[1].write_text(render(result),encoding='utf-8',newline='\n')
    print(json.dumps({key:row['最良開始日を1つ除いた実収支円'] for key,row in actors.items()},ensure_ascii=False))


if __name__=='__main__':
    main()
