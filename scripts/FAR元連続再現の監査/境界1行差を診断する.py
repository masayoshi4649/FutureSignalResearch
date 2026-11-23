"""元のentry/qtyを固定し、timer返済の出口価格だけの1原行差を記述する。売買は再生しない。"""

import argparse
import bisect
from collections import defaultdict
import importlib.util
import json
import os
from pathlib import Path


ROOT=Path(__file__).resolve().parents[2]
AUDIT_PATH=ROOT/'scripts/FAR元連続再現の監査/原板照合.py'
spec=importlib.util.spec_from_file_location('native_raw_fixed',AUDIT_PATH)
RAW=importlib.util.module_from_spec(spec)
spec.loader.exec_module(RAW)
SOURCE_URL='https://github.com/masayoshi4649/FutureAlgorithmResearch/blob/cf0717daa1eed78759f78a428bce50129e7f705b/work/research166/replay/main.go#L98-L220'
OLD_GROSS={'D164_15':1248500,'P164_06':392000,'U165_03':1181000}


def boundary_rows(at: float, raw: dict) -> tuple[dict,dict]:
    """
    機能: 境界後の最初のSource原行と、そのstrict後の次正常原行を選ぶ。
    引数: at(float)、raw(dict)は境界と固定監査器の1走査結果。
    返り値: tuple[dict,dict]は要求を出すと仮定する原行と返済価格の評価原行。
    """
    first=bisect.bisect_left(raw['source_times'],at)
    by_index={q['index']:q for q in raw['by_line'].values()}
    if first>=len(raw['source_times']) or first not in by_index:
        raise ValueError('境界後Source原行がない')
    normal_indices=[x[0] for x in raw['normal']]
    target=bisect.bisect_right(normal_indices,first)
    if target>=len(normal_indices):
        raise ValueError('境界後初回Sourceのstrict後正常原行がない')
    q=by_index[normal_indices[target]]
    if q['index']<=first or q['time']<raw['source_times'][first] or not q['quote_ok']:
        raise ValueError('仮定価格の因果順不正')
    return by_index[first],q


def price_difference(close_side: int, quantity: int, price: float, alternative: float, point: float) -> float:
    """
    機能: 固定された所有量の返済価格差だけを円へ変換する。
    引数: close_side/quantity(int)、price/alternative/point(float)は返済方向・量・両価格・点価。
    返り値: floatは−返済方向×価格差×固定量×点価。代替戦略PnLではない。
    """
    if close_side not in (-1,1) or type(quantity) is not int or quantity<=0:
        raise ValueError('固定方向/数量不正')
    return -close_side*(alternative-price)*quantity*point


def fmt_time(at: float) -> str:
    """
    機能: UNIX秒をJST表示する。
    引数: at(float)は価格又は要求時計。
    返り値: strはISO時刻。
    """
    import datetime as dt
    return dt.datetime.fromtimestamp(at,RAW.JST).isoformat()


def main() -> None:
    """
    機能: 固定23timer/17場の出口価格差を集計し、新規JSON/MDへ保存する。
    引数: --work(Path)は元Native実行フォルダ、--out(Path)は未作成の新規診断フォルダ。
    返り値: None。未計測や入力変更は例外。
    """
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work',type=Path,required=True,help='全54場と入力前_正式54場.jsonを含む元Native実行フォルダ')
    parser.add_argument('--out',type=Path,required=True,help='新規診断フォルダ。既存フォルダは拒否')
    args=parser.parse_args()
    WORK=args.work.resolve()
    out_dir=args.out.resolve()
    if out_dir.exists():raise FileExistsError('診断フォルダは新規作成だけ')
    code_link=Path(os.path.relpath(Path(__file__).resolve(),out_dir)).as_posix()
    out_json=out_dir/'境界1行差の診断.json';out_md=out_dir/'境界1行差の診断.md' 
    if out_json.exists() or out_md.exists():raise FileExistsError('診断出力は新規作成だけ')
    # 売買や指標を運転せず、固定原板の選択と差額式を手計算で先に確認する。
    assert price_difference(-1,3,100,110,10)==300
    assert price_difference(1,3,100,90,10)==300
    fake={'source_times':[1,2,2,3], 'by_line':{10:{'index':0,'time':1,'quote_ok':True},11:{'index':1,'time':2,'quote_ok':False},12:{'index':2,'time':2,'quote_ok':True},13:{'index':3,'time':3,'quote_ok':True}},'normal':[(0,1,10),(2,2,12),(3,3,13)]}
    assert [x['index'] for x in boundary_rows(2,fake)]==[1,2]
    manifest_path=ROOT/'study/00080_FAR後期三手法の15分移植と利益保護/入力台帳.json'
    manifest=RAW.load(manifest_path);assert RAW.digest(manifest_path)==RAW.MANIFEST_SHA
    allowed={s['id']:s for s in manifest['sessions'] if '2026-09-21'<=s['id'].split('_')[0]<='2026-10-27'}
    assert len(allowed)==54
    completion_path=WORK/'全54場/完了.json';completion=RAW.load(completion_path);assert completion['場数']==54
    natives={name:RAW.digest(WORK/'全54場'/name) for name in completion['結果SHA256']}
    assert natives==completion['結果SHA256'] and {Path(p).stem for p in natives}==set(allowed)
    core_proof=RAW.load(WORK/'入力前_正式54場.json')
    code_before={p:RAW.digest(Path(p)) for p in core_proof['コード']}
    assert code_before==core_proof['コード'] and len(code_before)==11
    pure_before={p:RAW.digest(Path(manifest['純戦略repo'])/p) for p in manifest['純戦略SHA256']}
    assert pure_before==manifest['純戦略SHA256'] and len(pure_before)==43
    local_paths=[Path(__file__),AUDIT_PATH,ROOT.parent/'SessionTradeExecuter/internal/strategy/selected_source.go',ROOT.parent/'SessionTradeExecuter/internal/strategy/selected_runtime.go',ROOT.parent/'SessionTradeExecuter/internal/strategy/selected_ledger.go',completion_path,manifest_path]
    local_before={str(p.resolve()):RAW.digest(p) for p in local_paths}
    native_values={Path(name).stem:RAW.load(WORK/'全54場'/name) for name in natives}
    gross=defaultdict(float)
    actual_timers=[]
    records=[]
    for session,value in native_values.items():
        for key,b in value['books'].items():
            if not key.startswith('micro_'):continue
            assert b['complete'] and b['finished'] and not b['failure']
            gross[key.removeprefix('micro_')]+=b['totals']['gross_yen']
            actual_timers.extend((session,key,s['signal']['id']) for s in b['signals'] if s['origin']=='timer' and s['signal']['action']=='close')
            records.extend({'場':session,'key':key,'at':s['at'],'qty':s['signal']['quantity'],'id':s['signal']['id']} for s in b['signals'] if s['origin']=='timer' and s['signal']['action']=='close')
    assert set(actual_timers)=={(r['場'],r['key'],r['id']) for r in records} and len(actual_timers)==23
    assert len(records)==23 and len({x['場'] for x in records})==17
    by_session=defaultdict(list)
    for r in records:by_session[r['場']].append(r)
    differences=[];raw_before={}
    for session,requests in sorted(by_session.items()):
        value=native_values[session];item=allowed[session]['files']['NK225_book'];path=Path(manifest['source_root'])/item['path']
        before=RAW.digest(path);assert before==item['sha256'] and path.stat().st_size==item['size'];raw_before[str(path)]=before
        # 全Source出典を一時的に保持するが、原板本文を出力へ複写しない。
        raw=RAW.scan_raw(path,session,set(range(1,value['quality']['NK225']['lines']+1)))
        assert raw['quality']==value['quality']['NK225']
        for request in requests:
            b=value['books'][request['key']];slist=[s for s in b['signals'] if s['signal']['id']==request['id']];flist=[f for f in b['fills'] if f['fill']['SignalID']==request['id']]
            assert len(slist)==len(flist)==1;s=slist[0];f=flist[0];sig=s['signal']
            assert sig['time']==s['at']==request['at'] and sig['quantity']==f['fill']['Quantity']==request['qty']
            assert b['config']['point_value']==10 and s['origin']=='timer' and sig['action']=='close'
            first,alternative=boundary_rows(s['at'],raw)
            normal=[r for r in raw['normal'] if r[0]>sig['source_index'] and r[1]>=sig['time']]
            assert normal and (f['quote']['index'],f['quote']['time'],f['quote']['source_line'])==normal[0]
            assert f['quote']==raw['by_line'][f['quote']['source_line']]
            assert f['fill']['Price']==(f['quote']['ask'] if sig['side']>0 else f['quote']['bid'])
            alt_price=alternative['ask'] if sig['side']>0 else alternative['bid']
            delta=price_difference(sig['side'],request['qty'],f['fill']['Price'],alt_price,10)
            allocations=[]
            for a in f['allocations']:
                allocations.append({'hold_id':a['hold_id'],'quantity':a['quantity'],'entry_price':a['entry_price'],'entry_source':{k:a['entry_quote'][k] for k in ('time','index','source_line')},'native_exit_price':a['exit_price'],'hypothetical_exit_price':alt_price,'price_difference_yen':price_difference(sig['side'],a['quantity'],a['exit_price'],alt_price,10)})
            assert sum(a['quantity'] for a in allocations)==request['qty'] and sum(a['price_difference_yen'] for a in allocations)==delta
            window='デイ場末' if session.endswith('_Day') else 'ナイト米国前15分' if request['key'].endswith('P164_06') else 'ナイト場末'
            differences.append({'session':session,'key':request['key'],'signal_id':request['id'],'boundary':s['at'],'boundary_jst':fmt_time(s['at']),'window':window,'close_side':sig['side'],'quantity':request['qty'],'point_value':10,
                                'first_source_after_boundary':first,'native_fill_quote':f['quote'],'native_exit_price':f['fill']['Price'],'hypothetical_fill_quote':alternative,'hypothetical_exit_price':alt_price,'price_difference_pt':-sig['side']*(alt_price-f['fill']['Price']),'price_difference_yen':delta,
                                'source_rows_between_fills':alternative['index']-f['quote']['index'],'physical_lines_between_fills':alternative['source_line']-f['quote']['source_line'],'seconds_between_fills':alternative['time']-f['quote']['time'],'allocations':allocations})
        assert RAW.digest(path)==before
    methods={}
    for method in ('D164_15','P164_06','U165_03'):
        group=[r for r in differences if r['key']=='micro_'+method];delta=sum(r['price_difference_yen'] for r in group);needed=OLD_GROSS[method]-gross[method]
        methods[method]={'timer_notices':len(group),'sessions':len({r['session'] for r in group}),'native_gross_yen':gross[method],'old_reported_gross_yen':OLD_GROSS[method],'needed_difference_yen':needed,'boundary_price_difference_yen':delta,'difference_only_reconciliation_yen':gross[method]+delta,'matches_needed_difference':delta==needed,'nonzero_notices':sum(r['price_difference_yen']!=0 for r in group)}
    windows={w:{'timer_notices':len(g),'quantity':sum(r['quantity'] for r in g),'price_difference_yen':sum(r['price_difference_yen'] for r in g)} for w in sorted({r['window'] for r in differences}) if (g:=[r for r in differences if r['window']==w])}
    after={name:RAW.digest(WORK/'全54場'/name) for name in natives};assert after==natives
    raw_after={p:RAW.digest(Path(p)) for p in raw_before};assert raw_after==raw_before
    assert all(RAW.digest(Path(p))==v for p,v in {**code_before,**local_before}.items())
    assert pure_before=={p:RAW.digest(Path(manifest['純戦略repo'])/p) for p in pure_before}
    result={'診断':'境界の約定価格差','成功':True,'timer通知数':23,'原板場数':17,'全通知固定':True,'全3手法の必要差と一致':all(x['matches_needed_difference'] for x in methods.values()),'手法別':methods,'時間窓別':windows,'通知別':differences,
            '前提':'既存entry/所有qty/他の要求を固定し、境界後最初のLast>0 Source原行で返済を要求すると仮定。そのstrict後の次正常行のBBO価格差だけ。','代替戦略成績':False,'完全代替再生':False,'Source_金融_指標再生':0,'既存Native変更':0,'入力変更':0,
            '未検証':'元実行と当実行の全Signal/親状態/発行時点の同値、新規Core/Extraの相違、他の通知や保有への波及を再生していない。合計一致だけで完全再現済みとはしない。',
            'コード読取':{'確認日':'2026-11-08','FAR原run':{'url':SOURCE_URL,'commit':'cf0717daa1eed78759f78a428bce50129e7f705b','GitBlobSHA':'6d8f1a63c94006e6cf7e80c9e988f06d995e2acb','読取範囲':'98〜220行、GitHub connectorで123行のみ独立確認','事実':'rawループで先行pendingの次正常Fill→OnOrderDone→p.Observe(o,true)→Signal受付/取消。外timer Flatten呼出なし。UはUS+900未満のObserveをskip。'},
                         '純strategy':'selectedDeadlineはP=min(ForceClose,US−900)、他ForceClose。observeSelectedは当ObservationでTime>=deadlineならForced/Goalを設定しflushする。Flattenは外部呼出時にその場でGoal/返済要求を作る。','今回':'固定Native replayは各timer<=次原行時計で先にAdapter.Force→Portfolio.Flattenし、最初の適格原行で予約をFillする。'},
            'Native前後SHA256':{n:{'before':v,'after':after[n]} for n,v in natives.items()},'原板前後SHA256':{p:{'before':v,'after':raw_after[p]} for p,v in raw_before.items()},'core11SHA256':code_before,'純戦略43SHA256':pure_before,'読取コードと入力SHA256':local_before,'人工検査':'買売価格差式・badBBOを含むfirst Sourceとstrict後normalの3手計算成功'}
    lines=['# 境界の約定価格差','','これは既存のentry・所有量・他判断を固定した出口価格差の診断であり、代替戦略の損益ではない。Nativeの約定価格と正本は変更していない。','', '| 手法 | timer通知 | Native gross | 旧報告gross | 必要差 | 境界価格差だけ | 一致 |','| --- | ---: | ---: | ---: | ---: | ---: | --- |']
    for m,g in methods.items():lines.append(f"| {m} | {g['timer_notices']} | {g['native_gross_yen']:,.0f} | {g['old_reported_gross_yen']:,.0f} | {g['needed_difference_yen']:+,.0f} | {g['boundary_price_difference_yen']:+,.0f} | {'一致' if g['matches_needed_difference'] else '未一致'} |")
    lines+=['','## 何を変えた価格差か','','今回は境界timerを原行より先に処理し、最初の正常原行で返済する。本診断は、境界以後最初のLast>0 Source原行（badBBOも含む）で要求を出したと仮定し、そのIndexのstrict後にある最初の正常原行のBBOを同じ数量へ当てた。差は `−返済Side × (仮定exit − Native exit) × 数量 × 10円`。手数料/仮定滑り/新規価格/量の変更は0。','', '「1行差」は物理的に必ず1行・1秒後という意味ではない。Last0/配置不能行を除き、同時計でも原行Indexは進む。最初のSource行がbadBBOならNativeと仮定の約定行が同じ場合もある。','', '## 通知ごとの原行','','| 場・手法 | 固定量 | 境界JST | first Source line/index | Native line/index/価格 | 仮定 line/index/価格 | 価格差円 |','| --- | ---: | --- | --- | --- | --- | ---: |']
    for r in differences:
        a,b,c=r['first_source_after_boundary'],r['native_fill_quote'],r['hypothetical_fill_quote']
        lines.append(f"| {r['session']} / {r['key'].removeprefix('micro_')} | {r['quantity']} | {r['boundary_jst']} | {a['source_line']}/{a['index']} | {b['source_line']}/{b['index']}/{r['native_exit_price']:g} | {c['source_line']}/{c['index']}/{r['hypothetical_exit_price']:g} | {r['price_difference_yen']:+,.0f} |")
    lines+=['','## 呼出順の根拠と限界','',f'[元FAR166の固定run 98〜220行]({SOURCE_URL})を2026-11-08に123行だけ取得して確認した。先行pendingの約定後にObserveする順で、外部timer Forceは呼んでいない。純Portfolio側はdeadlineを越えたObservationで初めて返済希望を作るため、要求後strict次原行の価格と整合する。固定Nativeは原行前にForceを呼ぶので、要求済みの返済が最初の正常原行で約定する。','', '元runのCore/Extraは1/1、今回の商品設定はmini5/5・micro50/50である。selected内部の固定尺度との関係や全Signalの同値はこの価格差診断だけでは証明しない。17場23通知の合計が必要差へ一致しても、完全な代替運転・新しい達成成績とは呼ばない。','', 'Native全54、対象原板17、core11、純戦略43の前後SHAをJSONへ記録した。元巨大repoはcloneせず、未使用日・新金融・新Source再生は0。','', f'[全件・原行時計と指紋](境界1行差の診断.json) / [再現コード]({code_link})']
    out_dir.mkdir(parents=True,exist_ok=False)
    with out_json.open('x',encoding='utf-8') as stream:json.dump(result,stream,ensure_ascii=False,indent=2);stream.write('\n')
    with out_md.open('x',encoding='utf-8') as stream:stream.write('\n'.join(lines)+'\n')
    print(json.dumps({'成功':True,'timer通知':23,'場数':17,'必要差と全一致':result['全3手法の必要差と一致'],'手法別':methods},ensure_ascii=False),flush=True)


if __name__=='__main__':main()
