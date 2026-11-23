"""92の3H1玉と旧対応2refだけを保存値から結ぶ。新しい入口/出口は実行しない。"""

import argparse
from collections import Counter
from datetime import datetime,timezone,timedelta
from decimal import Decimal
import gzip
import hashlib
import json
import math
from pathlib import Path

JST=timezone(timedelta(hours=9))


def need(ok: bool, reason: str) -> None:
    """
    機能: 出典/数量/会計の不一致を拒否する。
    引数: ok(bool)、reason(str)は条件と原因。
    返り値: None。不成立はValueError。
    """
    if not ok:raise ValueError(reason)


def sha(path: Path) -> str:
    """
    機能: 保存入力/本コードのbyte指紋を得る。
    引数: path(Path)は既存保存ファイル。
    返り値: strはSHA256。
    """
    with path.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()


def num(value: object) -> Decimal:
    """
    機能: 有限JSON数値を十進検算値へ変換する。
    引数: value(object)はint/float。
    返り値: Decimalは金額/価格/時計。boolを拒否する。
    """
    need(type(value) in (int,float,Decimal) and math.isfinite(value),'有限数値が必要');return Decimal(str(value))


def stamp(at: float | None) -> str | None:
    """
    機能: 保存Unix秒を日本時間で表示する。
    引数: at(float|None)は保存時計。
    返り値: str|Noneは年月日/時分秒。nullを0時にしない。
    """
    return datetime.fromtimestamp(at,JST).isoformat() if at is not None else None


def gz_rows(path: Path) -> list:
    """
    機能: 明示された圧縮診断だけを保存順で読む。
    引数: path(Path)はJSONL gzip。
    返り値: list[dict]は本文。原板や市場を開かない。
    """
    with gzip.open(path,'rt',encoding='utf-8') as f:return [json.loads(l) for l in f if l.strip()]


def context(scene: dict, row: dict, identity: str) -> dict:
    """
    機能: 要求時の現在資格/独立価格と全点の公開原行を結ぶ。
    引数: scene/row(dict)、identity(str)は共有保存・玉診断・小型出典ID。
    返り値: dictは入口前に公開済みだった値だけ。実取得後の値を混ぜない。
    """
    order=row['entry_order'];at=order['request_time'];side=row['lot']['side'];g=next(g for g in scene['grid_decisions'] if g['at']==at);price=next(p for p in scene['price_decisions'] if p['at']==at);d=next(d for d in price['snapshot']['directions'] if d['side']==side);now=next(d for d in g['entry']['directions'] if d['side']==side);q=g['c0']['base']['quote'];tech=g['c0']['base']['technical'];records={r['id']:r for r in scene['entry_observations']};points={}
    refs={'i':d['impulse'],'p':d['pullback'],'H':None if d['high'] is None else d['high']['point'],'b':d['reclaim'],'P':None if d['peak'] is None else d['peak']['point'],'h':d['hold'],'v':d['resume']}
    for name,p in refs.items():
        if p is None:points[name]=None;continue
        r=records[p['observation_id']];x=r['input'];t=x['technical'];quote=x['quote'];need(t['bar3_end']==p['bar_end'] and x['at']==p['published_at']<=at and quote['index']<=q['index'] and quote['line']<=q['line'],'公開点の未来/別原行')
        points[name]={'observation_id':r['id'],'ordinal':x['ordinal'],'bar_end':p['bar_end'],'published_at':p['published_at'],'公開JST':stamp(p['published_at']),'close':t['close3'],'origin':x['origin'],'quote_index':quote['index'],'quote_line':quote['line']}
    for name,field in (('H','high'),('p','low'),('P','peak')):
        if d[field] is not None:need(points[name]['close']==d[field]['close'],'固定Closeと公開record差')
    if row['key'].startswith('H1'):need(all(points.values()) and now['e0_allowed'] and d['trigger_valid'],'H1の現在E0/独立v/全点')
    return {'id':identity,'request_time':at,'要求JST':stamp(at),'side':side,'要求時気配':{n:q[n] for n in ('time','index','line','bid','ask','last')},'現在E0':now['e0_allowed'],'旧E1':now['e1_allowed'],'旧event有効':now['event_valid'],'旧event未知':now['event_required_unknown'],
      '現在check':[{n:c[n] for n in ('id','known','passed')} for c in now['checks']],'想定取得EMA距離ATR':now['placement_atr'],'公開技法':{n:tech[n] for n in ('ema8_3','ema8_15','ema21_15','atr3','histogram3','previous_histogram3','rsi3','previous_rsi3','tr3','previous_atr3','bar3_end','bar15_end')},
      'i出生':d['impulse_origin'],'独立段階':d['stage'],'独立v有効':d['trigger_valid'],'新v経過秒':None if d['resume'] is None else at-d['resume']['bar_end'],'p経過秒':None if d['pullback'] is None else at-d['pullback']['bar_end'],'価格点':points}


def execution(row: dict, ctx: dict, detailed: bool) -> dict:
    """
    機能: 保存玉の取得属性と返済片の価格/実量/費用を検算する。
    引数: row/ctx(dict)、detailed(bool)は玉・要求時出典・H1の片明細指定。
    返り値: dictは小型実績。実取得/返済値を入口で既知だったと記さない。
    """
    p=row['lot'];o=row['entry_order'];binding=p['source_entry'];ref=binding['read_lot']['reference'];pieces=[];gross=commission=slip=net=0
    for c in row['closed']:
        q=c['quantity'];g=p['side']*(num(c['exit_price'])-num(p['entry_price']))*q*10;co=22*q;sl=100*q;n=g-co-sl
        need(g==num(c['gross_pnl']) and co==c['commission'] and sl==c['slippage'] and n==num(c['pnl5']),'返済片の実価格×量/費用/純額')
        matches=[x for x in row['orders'] if x['kind']=='exit' and x['fill_time']==c['exit_time'] and x['fill_line']==c['exit_line'] and x['reason']==c['reason'] and x['filled_quantity']==q];need(len(matches)==1,'返済片の注文元');order=matches[0]
        earlier=[x for x in row['closed'] if x['exit_time']<=order['request_time'] and x['exit_line']<=order['request_line']];realized=sum(x['pnl5'] for x in earlier);remaining=p['initial_quantity']-sum(x['quantity'] for x in earlier);request_whole=realized+remaining*c['request_net_per_unit']
        need(num(request_whole)==num(order['whole_net']),'要求以前の片だけから全玉評価を再構成')
        adverse=c['request_to_fill_adverse_yen']
        if adverse is not None:need(num(adverse)==p['side']*(num(c['request_mark'])-num(c['exit_price']))*q*10,'要求後悪化/改善の符号')
        pieces.append({'quantity':q,'request_time':order['request_time'],'要求JST':stamp(order['request_time']),'request_index':order['request_index'],'request_line':order['request_line'],'request_mark':c['request_mark'],'request_floor':c['request_floor'],'request_net_per_unit':c['request_net_per_unit'],
          '要求時全玉評価円':request_whole,'exit_time':c['exit_time'],'返済JST':stamp(c['exit_time']),'exit_line':c['exit_line'],'exit_price':c['exit_price'],'reason':c['reason'],'gross_yen':float(g),'commission_yen':co,'slippage_yen':sl,'net_yen':float(n),'要求後悪化円':adverse,'harvest':c['harvest'],'whole_net_before_fill':c['whole_net_before_fill'],'closed_net_after_fill':c['closed_net_after_fill'],'floor_jump':c['floor_jump'],'cost_loss':c['cost_loss']})
        gross+=g;commission+=co;slip+=sl;net+=n
    need(sum(c['quantity'] for c in row['closed'])==p['initial_quantity'] and net==num(p['net_pnl']),'玉全体の返済量/純額')
    atr=p['entry_atr'];distance=p['side']*(p['entry_price']-ctx['公開技法']['ema8_3']);levels={k:None if ctx['価格点'][k] is None else p['side']*(p['entry_price']-ctx['価格点'][k]['close']) for k in ('H','P','v')}
    need(o['request_time']>=ref['at'] and o['request_time']>=binding['snapshot_at'],'Source出生/当時snapshot')
    return {'key':row['key'],'position_id':p['id'],'context_id':ctx['id'],'要求量':o['quantity'],'取得後属性':{'entry_time':p['entry_time'],'取得JST':stamp(p['entry_time']),'entry_index':p['entry_index'],'entry_line':p['entry_line'],'entry_price':p['entry_price'],'quantity':p['initial_quantity'],'entry_atr':atr,'固定Dpt':p['d'],'実取得EMA距離pt':distance,'実取得EMA距離ATR':None if atr is None or atr<=0 else distance/atr,'実取得H/P/v差pt':levels},
      '元参照':{'at':ref['at'],'出生JST':stamp(ref['at']),'entry':ref['entry'],'kind':ref['kind'],'method':ref['method'],'参照初期量':binding['read_lot']['reference_initial_quantity'],'参照現在量':ref['quantity'],'出生から要求秒':o['request_time']-ref['at'],'snapshot鮮度秒':o['request_time']-binding['snapshot_at'],'元価格から方向取得差pt':p['side']*(p['entry_price']-ref['entry'])},
      '残玉旗':p['flag'],'全玉旗':p['whole_flag'],'flag_time':p['flag_time'],'flag_index':p['flag_index'],'flag_mark':p['flag_mark'],'flag_net_per_unit':p['flag_net_per_unit'],'whole_flag_time':p['whole_flag_time'],'whole_flag_index':p['whole_flag_index'],'whole_flag_line':p['whole_flag_line'],
      'G1':{n:p[n] for n in ('harvest_target','harvest_filled','cash_floor_active','cash_floor','cash_floor_at','funding_failed')},'現金':{'gross_yen':float(gross),'commission_yen':commission,'slippage_yen':slip,'cost_yen':commission+slip,'net_yen':float(net)},'返済片':pieces if detailed else None}


def build(result: dict, trades: list, grids: list) -> dict:
    """
    機能: 全差を分解しH1全3refと旧共通2refだけを小型に抽出する。
    引数: result(dict)、trades/grids(list)は3保存正本。
    返り値: dictは後段記述統計。閾値選別/新売買を行わない。
    """
    need(result['試行']==92 and result['場数']==66,'固定92全66場');scenes={s['session']:s for s in grids};groups={k:{} for k in result['比較']}
    for r in trades:
        key=r['key'];token=r['session'],r['lot']['reference_id'];need(token not in groups[key],'恒久seenのref重複');groups[key][token]=r
    for key,group in groups.items():
        summary=result['比較'][key];need(len(group)==summary['完結玉'] and sum(r['lot']['initial_quantity'] for r in group.values())==summary['新規枚数'] and sum(r['lot']['net_pnl'] for r in group.values())==summary['費用後損益円'],'実参加/枚/純額と全成績の一致')
        need(sum(r['lot']['funding_failed'] for r in group.values())==summary['総計']['funding_failure_lots'] and sum(r['lot']['whole_flag'] for r in group.values())==summary['全玉旗'] and sum(r['lot']['whole_flag'] and r['lot']['net_pnl']<0 for r in group.values())==summary['全玉旗後赤字'],'予算不足/全玉旗の分母を結果へ結合')
    decomposition={};h1_targets=set(groups['H1G1_D0']);need(len(h1_targets)==3 and h1_targets==set(groups['H1G1_D1']),'H1の固定3参照')
    for delay in (0,1):
        left,right=[groups[f'H{k}G1_D{delay}'] for k in (0,1)];common=set(left)&set(right);only=set(left)-set(right);extra=set(right)-set(left);source=result['出口間の同実新規分解'][f'H1G1対H0G1_D{delay}']
        same={t for t in common if left[t]['entry_order']['request_time']==right[t]['entry_order']['request_time'] and all(left[t]['lot'][n]==right[t]['lot'][n] for n in ('side','entry_time','entry_price','initial_quantity','entry_index','entry_line'))};changed=common-same;cash=lambda g,keys:sum(g[t]['lot']['net_pnl'] for t in keys)
        need(len(common)==source['同参照ID'] and len(changed)==source['共通だが取得変更'] and len(same)==source['同実新規'] and len(only)==source['Aのみ'] and len(extra)==source['Bのみ'],'参加差の集合')
        removed=-cash(left,only);changed_delta=cash(right,changed)-cash(left,changed);extra_net=cash(right,extra);same_delta=cash(right,same)-cash(left,same);total=removed+changed_delta+extra_net+same_delta
        need(total==source['全差円']==result['比較'][f'H1G1_D{delay}']['費用後損益円']-result['比較'][f'H0G1_D{delay}']['費用後損益円'],'全差の3群再結合')
        excluded=[left[t]['lot'] for t in only];decomposition[f'D{delay}']={'旧側のみ':len(only),'不参加による差円':removed,'除外した黒字玉':sum(p['net_pnl']>0 for p in excluded),'除外黒字合計円':sum(p['net_pnl'] for p in excluded if p['net_pnl']>0),'除外した赤字玉':sum(p['net_pnl']<0 for p in excluded),'取得変更数':len(changed),'取得変更差円':changed_delta,'新ref数':len(extra),'新ref損益円':extra_net,'同実入口数':len(same),'同実出口差円':same_delta,'全差円':total}
    cases=[]
    for index,token in enumerate(sorted(h1_targets),1):
        session,ref=token;contexts=[];executions=[];ids={}
        for policy in ('H1','H0'):
            for delay in (0,1):
                key=f'{policy}G1_D{delay}';row=groups[key].get(token)
                if row is None:continue
                ct=(row['entry_order']['request_time'],row['lot']['side'])
                if ct not in ids:
                    ids[ct]=f'M{index}C{len(contexts)+1}';contexts.append(context(scenes[session],row,ids[ct]))
                c=next(c for c in contexts if c['id']==ids[ct]);executions.append(execution(row,c,policy=='H1'))
        cases.append({'id':f'M{index}','session':session,'reference_id':ref,'分類':'同ref取得変更' if token in groups['H0G1_D0'] else 'H1新ref','入口前出典':contexts,'実行後実績':executions})
    overview={}
    for key in groups:
        v=result['比較'][key];active=sum(r['key']==key and r['metrics']['entry_quantity']>0 for r in result['場別']);overview[key]={n:v[n] for n in ('費用後損益円','最大DD円','完結玉','新規枚数','赤字場数','全玉旗','全玉旗後赤字','正益未観測の損益円','正益観測の損益円')};overview[key].update(取引場=active,無取引場=66-active,保護予算不足玉=v['総計']['funding_failure_lots'])
    return {'試行':92,'成功':True,'範囲':'H1全3ref/6実玉と旧対応2refだけ。保存結果の記述統計で独立原板検査ではない','比較':overview,'全差分解':decomposition,'対象':cases,'限界':['3玉はすべて買い。売りの市場標本を含まず、人工の鏡像検査と区別する','現在参照量は元Source玉の量で、市場の現在出来高ではない','取得/返済/最終純額は実行後属性。入口で既知の条件へ後付けしない','旧他政策の利益/損失をH1が当時知り得た利益としない','閾値fit/未来最適出口/未使用日の本文読取/新売買/原板/APIは0']}


def markdown(value: dict, json_name: str) -> str:
    """
    機能: 主点と現金内訳・入口の違い・次の問いだけをMarkdownにする。
    引数: value(dict)、json_name(str)は小型診断と出典名。
    返り値: strは読み物。玉/指標本文を全件再転記しない。
    """
    def yen(x: float) -> str:
        """
        機能: 表示金額を桁区切りにする。
        引数: x(float)は金額。
        返り値: strは整数円表示。
        """
        return f'{x:,.0f}'
    a,b=[value['比較'][f'H1G1_D{d}'] for d in (0,1)]
    lines=['# 入口と回収の診断','','保存3正本による試行92の後段記述統計。全66場は既使用。新しい条件・売買・原板検査は追加していない。','',
      f"H1は主{a['完結玉']}玉{a['新規枚数']}枚・{a['取引場']}/66場だけ取引し、{a['赤字場数']}/{a['取引場']}取引場が赤字。主{yen(a['費用後損益円'])}円、追加1秒{yen(b['費用後損益円'])}円。正益未観測の玉は主{yen(a['正益未観測の損益円'])}円／1秒{yen(b['正益未観測の損益円'])}円、正益観測の玉は主{yen(a['正益観測の損益円'])}円／1秒{yen(b['正益観測の損益円'])}円。全案赤字で安定利益は未確認。",'',
      '## 全差をどこから得たか','','| 遅延 | 旧側のみへの不参加 | 同ref取得変更 | 新ref | 同実出口差 | 全差円 |','| --- | ---: | ---: | ---: | ---: | ---: |']
    cash={d:{n:sum(e['現金'][n] for c in value['対象'] for e in c['実行後実績'] if e['key']==f'H1G1_D{d}') for n in ('gross_yen','cost_yen')} for d in (0,1)}
    lines[6:6]=[f"主は粗損益{yen(cash[0]['gross_yen'])}円−往復費用{yen(cash[0]['cost_yen'])}円、1秒は粗損益{yen(cash[1]['gross_yen'])}円−同費用{yen(cash[1]['cost_yen'])}円。",'']
    for k,d in value['全差分解'].items():lines.append(f"| {k} | {yen(d['不参加による差円'])} | {yen(d['取得変更差円'])} | {yen(d['新ref損益円'])} | {yen(d['同実出口差円'])} | {yen(d['全差円'])} |")
    d=value['全差分解']['D0'];lines+=['',f"主の同実入口は{d['同実入口数']}。差の多くは{d['旧側のみ']}玉への不参加で、その中には黒字{d['除外した黒字玉']}玉・計{yen(d['除外黒字合計円'])}円も含む。DDや赤字場数の減少を、取引した場の回収改善と同一視しない。",'',
      '## 入口前の資格と取得後実績','','| ID/場 | 要求JST | Source出生から秒 | vから秒 | 想定取得/ATR | 実取得/枚 | Dpt | 主/1秒純額円 |','| --- | --- | ---: | ---: | ---: | --- | ---: | --- |']
    for case in value['対象']:
        e=next(e for e in case['実行後実績'] if e['key']=='H1G1_D0');other=next(e for e in case['実行後実績'] if e['key']=='H1G1_D1');c=next(c for c in case['入口前出典'] if c['id']==e['context_id']);p=e['取得後属性'];lines.append(f"| {case['id']} {case['session']} | {c['要求JST'][11:19]} | {e['元参照']['出生から要求秒']} | {c['新v経過秒']} | {c['想定取得EMA距離ATR']:.4f} | {p['entry_price']}/{p['quantity']} | {p['固定Dpt']} | {yen(e['現金']['net_yen'])}/{yen(other['現金']['net_yen'])} |")
    lines+=['','3件とも要求時E0=true・旧E1=falseで、元Sourceの生存と現在の価格形は別の記録。参照量はSource玉の現量であり、現在出来高ではない。実取得価格・返済額は取得後属性としてJSONで区別した。','']
    for case in value['対象']:
        e=next(e for e in case['実行後実績'] if e['key']=='H1G1_D0');c=next(c for c in case['入口前出典'] if c['id']==e['context_id']);terms=[]
        for n,p in c['価格点'].items():terms.append(f"{n} {p['公開JST'][11:16]}/{p['close']:,.0f}" if p is not None else n+' 未形成')
        lines.append(f"- {case['id']}：文脈 "+'、'.join(terms[:3])+'。価格 '+ '、'.join(terms[3:])+f"。i出生={c['i出生']}。")
    lines+=['','M3のiは自身の完成vからの継承で、初生iの勢い条件を再検査した点ではない。H/Pは確定Close基準で、足高安ではない。','',
      '## 旧対応2refは同じ取得ではない','','| ID | H1要求−H0要求秒 | H1−H0方向取得差pt | 旧D→新D | 旧主→新主純額円 |','| --- | ---: | ---: | --- | ---: |']
    for case in value['対象']:
        e=next(e for e in case['実行後実績'] if e['key']=='H1G1_D0');old=next((e for e in case['実行後実績'] if e['key']=='H0G1_D0'),None)
        if old is None:continue
        cs={c['id']:c for c in case['入口前出典']};p=e['取得後属性'];o=old['取得後属性'];lines.append(f"| {case['id']} | {cs[e['context_id']]['request_time']-cs[old['context_id']]['request_time']} | {p['entry_price']-o['entry_price']} | {o['固定Dpt']}→{p['固定Dpt']} | {yen(old['現金']['net_yen'])}→{yen(e['現金']['net_yen'])} |")
    lines+=['','入口時ATR由来の幅も変わるため、共通G1でも純粋な出口差とは呼ばない。負の要求差はH1の方が早く、正は遅い取得。旧側の未来の結果をH1の事前資格へ使っていない。','',
      '## 旗後の全玉＋72円は予定保全成功とは限らない','','| 遅延/片 | 枚 | 要求mark→実返済 | 粗損益 | 往復費用 | 純額 | 要求後悪化円 |','| --- | ---: | --- | ---: | ---: | ---: | ---: |']
    profitable=next(c for c in value['対象'] if any(e['全玉旗'] for e in c['実行後実績'] if e['key'].startswith('H1')))
    profit_executions={e['key']:e for e in profitable['実行後実績'] if e['key'].startswith('H1')}
    for e in profitable['実行後実績']:
        if not e['key'].startswith('H1'):continue
        for p in e['返済片']:lines.append(f"| D{e['key'][-1]}/{'部分収穫' if p['harvest'] else '残玉'} | {p['quantity']} | {p['request_mark']}→{p['exit_price']} | {yen(p['gross_yen'])} | {yen(p['commission_yen']+p['slippage_yen'])} | {yen(p['net_yen'])} | {'未計測' if p['要求後悪化円'] is None else yen(p['要求後悪化円'])} |")
    first,second=[profit_executions[f'H1G1_D{d}'] for d in (0,1)];p0=next(p for p in first['返済片'] if p['harvest']);r0=next(p for p in first['返済片'] if not p['harvest']);p1=next(p for p in second['返済片'] if p['harvest']);r1=next(p for p in second['返済片'] if not p['harvest'])
    lines+=['',f"D0は部分{yen(p0['net_yen'])}円と残玉{yen(r0['net_yen'])}円で全玉{yen(first['現金']['net_yen'])}円。D1は部分{p1['quantity']}枚が{yen(p1['net_yen'])}円、残{r1['quantity']}枚が{yen(r1['net_yen'])}円、合計{yen(second['現金']['net_yen'])}円。改善は悪化円の負値として残す。",'',
      f"D1はfunding_failed={str(second['G1']['funding_failed']).lower()}、cash床{second['G1']['cash_floor']}pt。残玉要求時の単価純益は{r1['request_net_per_unit']}円、全玉評価は{yen(r1['要求時全玉評価円'])}円。要求後の次板改善により最終{yen(second['現金']['net_yen'])}円になった1例であり、旗後赤字0を予定保全の成功や利益保証としない。旗・要求・実返済の時刻/原行と費用はJSONへ保存した。",'',
      '## 解釈と次の問い','','観測事実：現在の複合資格と価格の再開が成立しても、3玉中2玉は正益前にATR損切りした。3件とも想定取得位置がEMAから約0.89〜1.00ATRだったが、この3件だけで新しい位置閾値を選ばない。Sourceの出生経過秒と現在snapshotの鮮度、vからの経過を分ける。','',
      '市場心理の仮説：Hを越えた保持とP越えは、旧売り圧力の消化や追随の再開を示す可能性がある。一方、確認までの進行が大きければ局所的な伸び切りにもなり得る。参加者の意図や新規/返済の内訳を観測した事実ではない。[背景となる外部整理](../../docs/議論/外部再調査/平均回復と価格帯奪還の確認時刻を分ける.md)と区別する。','',
      '次の問い：当時までの価格更新、EMA/MACD/RSI増分の持続、ATRに対するH/P/vと現在位置を組み合わせて、新しい再加速と戻り終盤を事前に区別できるか。条件は別試行で固定し、除外した勝ちや無取引も含めて再生する。今回の後知識を利益が出る閾値へfitしない。','',
      f'[小型出典・現金内訳]({json_name})。保存値の再結合であり、原板/Sourceの独立監査正本は別。',''];return '\n'.join(lines)


def main() -> None:
    """
    機能: 3明示正本から小型診断JSON/Markdownを新規生成する。
    引数: --result/--trades/--grids/--out-json/--out-md(Path)は全必須。
    返り値: None。先読み条件選別や新しい取引を実行しない。
    """
    p=argparse.ArgumentParser(description='92の入口と回収の後段診断')
    for n in ('result','trades','grids','out-json','out-md'):p.add_argument('--'+n,type=Path,required=True)
    a=p.parse_args();inputs={'result':a.result.resolve(),'trades':a.trades.resolve(),'grids':a.grids.resolve()};need(not a.out_json.exists() and not a.out_md.exists(),'新規診断先が必要');before={n:sha(f) for n,f in inputs.items()};value=build(json.loads(inputs['result'].read_text(encoding='utf-8')),gz_rows(inputs['trades']),gz_rows(inputs['grids']));value.update(入力={n:str(f) for n,f in inputs.items()},入力SHA256=before,再現コードSHA256=sha(Path(__file__)),新市場再生=0,原板読取=0,API取得=0)
    need(before=={n:sha(f) for n,f in inputs.items()},'入力読取中の変更');text=markdown(value,a.out_json.name);a.out_json.parent.mkdir(parents=True,exist_ok=True);a.out_md.parent.mkdir(parents=True,exist_ok=True)
    with a.out_json.open('x',encoding='utf-8',newline='\n') as f:json.dump(value,f,ensure_ascii=False,indent=2,allow_nan=False);f.write('\n')
    with a.out_md.open('x',encoding='utf-8',newline='\n') as f:f.write(text)
    need(before=={n:sha(f) for n,f in inputs.items()},'生成前後の入力変更');print(json.dumps({'成功':True,'H1参照':len(value['対象']),'出力byte':a.out_json.stat().st_size+a.out_md.stat().st_size},ensure_ascii=False))


if __name__=='__main__':main()
