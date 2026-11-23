"""90の3正本からp固定床の取得位置・同実出口差・参加差を記述する。"""

import argparse
from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path

KEYS=tuple(f'{mode}_D{delay}' for delay in (0,1) for mode in ('P0','P1'))
REASON='押戻し確定終値固定否定'


def need(condition: bool, reason: str) -> None:
    """
    機能: 診断入力の不足・対応矛盾を通常の未知へ補完せず停止する。
    引数: condition(bool)、reason(str)は成立条件と原因。
    返り値: None。不成立はValueError。
    """
    if not condition:raise ValueError(reason)


def sha(path: Path) -> str:
    """
    機能: 圧縮正本・結果・診断コードを本文指紋へ結ぶ。
    引数: path(Path)は既存入力。
    返り値: strはSHA256。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rows(path: Path) -> list[dict]:
    """
    機能: 明示したgzip診断を辞書行へ読む。
    引数: path(Path)は玉又は共有正本。
    返り値: list[dict]は有限JSON値の行。
    """
    with gzip.open(path,'rt',encoding='utf-8') as stream:value=[json.loads(line) for line in stream if line.strip()]
    need(all(isinstance(r,dict) for r in value),'圧縮正本の辞書行が必要');json.dumps(value,allow_nan=False)
    return value


def sign(value: float) -> str:
    """
    機能: 最終損益符号を事後の記述ラベルへ写す。
    引数: value(float)は費用後円。
    返り値: strは黒字/赤字/同値。
    """
    return '黒字' if value>0 else '赤字' if value<0 else '同値'


def exact(a: dict, b: dict) -> bool:
    """
    機能: 同参照の要求と実取得の全条件が一致するか確認する。
    引数: a/b(dict)は同参照の玉診断。
    返り値: boolは要求時刻/方向/実取得時刻/価格/量が同じ場合に真。
    """
    return a['entry_order']['request_time']==b['entry_order']['request_time'] and all(a['lot'][n]==b['lot'][n] for n in ('side','entry_time','entry_price','initial_quantity'))


def group_metrics(items: list[dict]) -> dict:
    """
    機能: 一つの事後群の母数と純額を全件で集計する。
    引数: items(list[dict])は小型の玉観測。
    返り値: dictは玉/枚/純額/全玉・残玉旗と各赤字分母。
    """
    return {'玉':len(items),'枚':sum(r['初期量'] for r in items),'費用後円':sum(r['費用後円'] for r in items),
      '残玉正益':sum(r['残玉正益'] for r in items),'残玉正益後赤字':sum(r['残玉正益'] and r['費用後円']<0 for r in items),
      '全玉正益':sum(r['全玉正益'] for r in items),'全玉正益後赤字':sum(r['全玉正益'] and r['費用後円']<0 for r in items)}


def analyze(result: dict, trades: list[dict], shared_rows: list[dict]) -> dict:
    """
    機能: 既存264会計からp線の位置と同参照二層対応を記述集計する。
    引数: result(dict)、trades/shared_rows(list[dict])は3正本の本文。
    返り値: dictは4会計観測・2比較・実玉だけの小型出典。新戦略は作らない。
    """
    need(result['試行']==90 and result['場数']==66 and len(result['場別'])==264 and set(result['比較'])==set(KEYS),'90の66場264会計が必要')
    shared={r['session']:r for r in shared_rows};need(len(shared)==len(shared_rows)==66,'共有66場の一意性')
    gridmap={s:{g['at']:g for g in r['grid_decisions']} for s,r in shared.items()}
    levelmap={}
    for session,scene in shared.items():
        for level in scene['pullback_levels']:
            token=session,level['at'],level['reference_id'];need(token not in levelmap,'候補p線の重複');levelmap[token]=level
    grouped={key:{} for key in KEYS};observed={key:[] for key in KEYS}
    for row in trades:
        session,key,p,order=row['session'],row['key'],row['lot'],row['entry_order'];need(key in grouped and session in shared,'対象外の玉')
        identity=session,p['reference_id'];need(identity not in grouped[key],'同参照の実新規重複')
        need(p['quantity']==0 and p['closed_quantity']==p['initial_quantity'] and sum(c['quantity'] for c in row['closed'])==p['initial_quantity'] and sum(c['pnl5'] for c in row['closed'])==p['net_pnl'],'完結玉の数量/純額差')
        token=session,order['request_time'],p['reference_id'];need(token in levelmap,'実新規の要求p候補が欠落')
        level=levelmap[token];anchor=level['anchor'];price=anchor['price'];side=p['side'];grid=gridmap[session][order['request_time']];q=grid['c0']['base']['quote']
        need(anchor['reference_id']==p['reference_id'] and anchor['side']==side and price==anchor['close']-side*10 and anchor['at']==order['request_time'],'実玉のp線/方向/要求時点差')
        quote_known=q['valid'] and q['last']>0 and 0<q['bid']<q['ask'] and q['time']<=grid['at']
        mark=q['bid'] if side==1 else q['ask'];request_breached=side*(mark-price)<=0 if quote_known else None
        fp=side*(price-p['entry_price']);distance='p線が近い' if fp>-p['d'] else '同値' if fp==-p['d'] else 'p線が遠い'
        on=key.startswith('P1_');entry_breached=p['structure_entry_breached'] if on else None;hit=p['structure_first_hit_at'] if on else None
        if on:
            need(p['structure_active'] and p['structure_anchor']=={'known':True,'price':price,'at':anchor['at'],'bar_end':anchor['event']['pullback']['bar_end'],'reason':REASON} and p['structure_floor']==fp,'P1のgeneric価格線/活性/床差')
        new_orders=[o for o in row['orders'] if o['kind']=='exit' and o['reason']==REASON]
        strict_pieces=[c for c in row['closed'] if c['reason']==REASON]
        small={'場':session,'参照ID':p['reference_id'],'実玉ID':p['id'],'要求時刻':order['request_time'],'実取得時刻':p['entry_time'],'方向':side,'初期量':p['initial_quantity'],
          'p候補元順位':level['raw_rank'],'p候補供給順位':level['supplied_rank'],'p観測ID':anchor['event']['pullback']['observation_id'],'p確定Close':anchor['close'],'固定価格P':price,
          '実新規価格':p['entry_price'],'要求時の返済側BBO':mark if quote_known else None,'実約定玉の要求時既否定':request_breached,
          '取得時既否定known':on,'取得時既否定':entry_breached,'実建値からp床pt':fp,'初期ATR幅Dpt':p['d'],'初期ATR床との位置':distance,
          'p初回hitknown':on,'p初回hit時刻':hit,'p初回hit実Index':p['structure_first_hit_index'] if on else None,
          '保存strict新理由注文':len(new_orders),'保存strict新理由要求枚':sum(o['quantity'] for o in new_orders),'保存strict新理由返済枚':sum(c['quantity'] for c in strict_pieces),'保存strict新理由純額円':sum(c['pnl5'] for c in strict_pieces),
          '費用後円':p['net_pnl'],'残玉正益':p['flag'],'全玉正益':p['whole_flag'],'返済理由枚':dict(Counter({reason:sum(c['quantity'] for c in row['closed'] if c['reason']==reason) for reason in sorted({c['reason'] for c in row['closed']})}))}
        grouped[key][identity]=row;observed[key].append(small)
    accounts={}
    for key,items in observed.items():
        total=group_metrics(items);formal=result['比較'][key]
        need(total['玉']==formal['完結玉'] and total['枚']==formal['新規枚数'] and total['費用後円']==formal['費用後損益円'] and total['全玉正益']==formal['全玉旗'] and total['全玉正益後赤字']==formal['全玉旗後赤字'],'玉観測と正式集計差')
        accounts[key]={**total,'要求時既否定':group_metrics([r for r in items if r['実約定玉の要求時既否定'] is True]),'要求時既知未否定':group_metrics([r for r in items if r['実約定玉の要求時既否定'] is False]),'要求時未知':sum(r['実約定玉の要求時既否定'] is None for r in items),
          '取得時既否定既知玉':sum(r['取得時既否定known'] for r in items),'取得時既否定':group_metrics([r for r in items if r['取得時既否定'] is True]),'取得時未知玉':sum(not r['取得時既否定known'] for r in items),
          '初期ATR床との位置':{label:group_metrics([r for r in items if r['初期ATR床との位置']==label]) for label in ('p線が近い','同値','p線が遠い')},
          'p初回hit既知玉':sum(r['p初回hitknown'] for r in items),'p初回hit観測玉':sum(r['p初回hit時刻'] is not None for r in items),
          '保存strict新理由注文':sum(r['保存strict新理由注文'] for r in items),'保存strict新理由返済枚':sum(r['保存strict新理由返済枚'] for r in items),'保存strict新理由純額円':sum(r['保存strict新理由純額円'] for r in items)}
    comparisons={}
    for delay in (0,1):
        k0,k1=f'P0_D{delay}',f'P1_D{delay}';a,b=grouped[k0],grouped[k1];common=set(a)&set(b);same={i for i in common if exact(a[i],b[i])};changed=common-same;only0=set(a)-set(b);only1=set(b)-set(a)
        labels={};differences=[]
        for identity in sorted(same):
            x,y=a[identity]['lot'],b[identity]['lot'];pa,pb=x['net_pnl'],y['net_pnl'];label=sign(pa)+'→'+sign(pb)
            item=labels.setdefault(label,{'玉':0,'P0円':0,'P1円':0,'差円':0,'差0玉':0})
            for name,value in (('玉',1),('P0円',pa),('P1円',pb),('差円',pb-pa),('差0玉',pa==pb)):item[name]+=value
            differences.append({'場':identity[0],'参照ID':identity[1],'量':x['initial_quantity'],'P0円':pa,'P1円':pb,'差円':pb-pa,'P0残玉正益':x['flag'],'P1残玉正益':y['flag'],'P0全玉正益':x['whole_flag'],'P1全玉正益':y['whole_flag']})
        parts={'同実出口差円':sum(b[i]['lot']['net_pnl']-a[i]['lot']['net_pnl'] for i in same),'取得変更差円':sum(b[i]['lot']['net_pnl']-a[i]['lot']['net_pnl'] for i in changed),'P0のみ損益円':sum(a[i]['lot']['net_pnl'] for i in only0),'P1のみ損益円':sum(b[i]['lot']['net_pnl'] for i in only1)}
        delta=accounts[k1]['費用後円']-accounts[k0]['費用後円'];need(delta==parts['同実出口差円']+parts['取得変更差円']-parts['P0のみ損益円']+parts['P1のみ損益円'],'4寄与の全差保存')
        formal=result['出口間の同実新規分解'][f'P1対P0_D{delay}'];need((len(common),len(same),len(changed),len(only0),len(only1),parts['同実出口差円'])==tuple(formal[n] for n in ('同参照ID','同実新規','共通だが取得変更','Aのみ','Bのみ','同実新規出口差円')),'二層対応と正式結果差')
        comparisons[f'P1対P0_D{delay}']={'比較':[k0,k1],'同参照':len(common),'同実新規':len(same),'取得変更':len(changed),'P0のみ':len(only0),'P1のみ':len(only1),'全差円':delta,**parts,'同実の最終符号遷移':labels,'同実の全玉差':differences}
    return {'会計別':accounts,'対応比較':comparisons,'実玉の位置と出典':observed}


def diagnose(result_path: Path, trades_path: Path, grids_path: Path, output: Path, markdown: Path) -> dict:
    """
    機能: 3正本を前後不変で読取し、寄与記述統計を新規JSON/MDへ保存する。
    引数: result_path/trades_path/grids_path(Path)は正本、output/markdown(Path)は新規先。
    返り値: dictは限定診断。閾値探索/新売買/原板/APIは0。
    """
    paths={'結果':result_path,'玉診断':trades_path,'共有判断':grids_path};before={n:sha(p) for n,p in paths.items()}
    need(not output.exists() and not markdown.exists() and output.resolve()!=markdown.resolve() and not any(p.resolve() in (output.resolve(),markdown.resolve()) for p in paths.values()),'入力外の新規2出力が必要')
    result=json.loads(result_path.read_text(encoding='utf-8'));data=analyze(result,rows(trades_path),rows(grids_path));need(before=={n:sha(p) for n,p in paths.items()},'診断読取中の入力変更')
    value={'試行':90,'成功':True,'入力':{n:str(p.resolve()) for n,p in paths.items()},'入力SHA256':before,'診断コードSHA256':sha(Path(__file__)),**data,
      '範囲':'実約定して完結した玉の新規要求と取得。未約定/取消要求だけのp線は本玉分母に含めず、正式判断/Source監査を参照。',
      '限定':['P0の取得時既否定/hitはoff欄のfalseを流用せず未計測とする。P1の実金融fieldだけが既知。','p線対ATRは実建値基準のFpと初期−Dの幾何比較で、実際のG1/cash床や先行Source予約の拘束判定ではない。','strict新理由は保存注文/返済片の理由ラベル。旧床との差の独立再計算は正式原板監査へ分担。初回hitと新理由注文は同一事象ではない。hitは先行fill/Source後の残玉段階で、全返済fillで残0ならその原行の線跨ぎをhitへ遡及しない。','最終黒赤は事後ラベル。正益旗の分母減、同参照の取得変更、少数玉を改善確定や新しい戦略損益へ読み替えない。'],
      '新市場再生':0,'新原板読取':0,'API':0,'閾値探索':0,'条件変更':0}
    lines=['# 90：押戻し価格床の寄与','','既存の結果・玉診断・共有判断だけを用いた記述統計。p線の要求時位置、P1の取得時否定、同実入口の出口差と参加差を分ける。新戦略/閾値選別ではない。','',
      '| 会計 | 玉/枚 | 費用後円 | 実玉の要求時既否定 | 取得時既否定/既知 | p初回hit/既知 | strict新理由返済枚 | 全玉正益後赤字/正益 |','| --- | --- | ---: | ---: | --- | --- | ---: | --- |']
    for key,r in data['会計別'].items():
        lines.append(f"| {key} | {r['玉']}/{r['枚']} | {r['費用後円']:,} | {r['要求時既否定']['玉']} | {r['取得時既否定']['玉']}/{r['取得時既否定既知玉']} | {r['p初回hit観測玉']}/{r['p初回hit既知玉']} | {r['保存strict新理由返済枚']} | {r['全玉正益後赤字']}/{r['全玉正益']} |")
    lines+=['','P0の取得否定/hitは未計測で、0/0を否定なしと解釈しない。要求時は実約定玉の要求時点の返済側BBOによる同値を含む到達。未約定/取消だけの新規要求はこの玉分母にない。','',
      '| 比較 | 同参照 | 同実新規 | 取得変更 | P0のみ/P1のみ | 同実出口差円 | 全差円 |','| --- | ---: | ---: | ---: | --- | ---: | ---: |']
    for key,r in data['対応比較'].items():lines.append(f"| {key} | {r['同参照']} | {r['同実新規']} | {r['取得変更']} | {r['P0のみ']}/{r['P1のみ']} | {r['同実出口差円']:,} | {r['全差円']:,} |")
    lines+=['','同実は要求/方向/実取得時刻/価格/初期量まで一致する群。全差=同実出口差＋取得変更差−P0のみ損益＋P1のみ損益。小型JSONに差0を含む黒赤遷移・全玉差と、近い/同値/遠いの全分母を残す。','',
      '線対ATRは`方向×(P−実建値)`と`−D`の初期距離比較で、動的なATR/G1/cash床の支配を直接表さない。strict新理由は保存ラベルで、同値時の旧理由優先と実際の不足義務は正式原板監査へ分担する。hitは先行fill/Source後の残玉段階で、全返済fillによる残0の同原行跨ぎを遡及しない。先行予約のある玉をp要求漏れとみなさない。','',
      f'[全群と小型出典]({output.name})。最終符号と途中の正益後赤字、早切りで観測しなくなる後の正益を区別する。原板・新売買・API・閾値探索・条件変更は0。','']
    for path,text in ((output,json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n'),(markdown,'\n'.join(lines))):
        path.parent.mkdir(parents=True,exist_ok=True)
        with path.open('x',encoding='utf-8',newline='\n') as stream:stream.write(text)
    return value


def main() -> None:
    """
    機能: 明示3正本から新規の寄与診断を生成する。
    引数: --result/--trades/--grids/--out/--md(Path)は全必須。
    返り値: None。未完/不一致/既存出力は非0。
    """
    parser=argparse.ArgumentParser(description='90の既存3正本によるp床の寄与診断')
    for name in ('result','trades','grids','out','md'):parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args();value=diagnose(args.result,args.trades,args.grids,args.out,args.md)
    print(json.dumps({'成功':value['成功'],'会計':len(value['会計別']),'比較':len(value['対応比較']),'新売買':0},ensure_ascii=False))


if __name__=='__main__':main()
