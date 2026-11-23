"""92 work案。固定会計照合を再用する4外入口の小型集約。"""

from collections import Counter
from copy import deepcopy
import argparse
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]


def load(path: Path, name: str) -> object:
    """
    機能: 同じwork保存adapter又は停止会計を独立名で読む。
    引数: path(Path)、name(str)はコードと名前。
    返り値: objectはAPI。市場実行や成果物生成を自動起動しない。
    """
    s=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m


SAVED=load(Path(__file__).with_name('基準と保存判断の照合.py'),'saved92_for_summary')
BASE_PATH=ROOT/'scripts/FAR後期15分移植/集計.py'
BASE_SHA='7af9b626d31a0a509a75645b9ce3db2b76ab7f9509bb161d3c8ba04ab492ecad'
if hashlib.sha256(BASE_PATH.read_bytes()).hexdigest()!=BASE_SHA:raise ValueError('固定80会計照合の変更')
BASE=load(BASE_PATH,'cash80_for92_work')
KEYS=SAVED.KEYS


def policy_actions(scene: dict, key: str) -> dict:
    """
    機能: 保存adapterと同じ外政策未知の分類を再用する。
    引数: scene(dict)、key(str)は一場保存と外会計。
    返り値: dictは政策判断件数。金融原値は変更しない。
    """
    return SAVED.policy_actions(scene,key)


def comparison(diagnostics: list[dict], delay: int) -> dict:
    """
    機能: 恒久seenの一参照一実参加を同実入口/取得変更/片側へ分解する。
    引数: diagnostics(list[dict])、delay(int)は全玉診断と0/1遅延。
    返り値: dictは既存89と同じ二層の全額寄与。複数世代は拒否する。
    """
    keys=[f'H{k}G1_D{delay}' for k in (0,1)];groups=[]
    for key in keys:
        rows=[r for r in diagnostics if r['key']==key];group={(r['session'],r['lot']['reference_id']):r for r in rows}
        if len(group)!=len(rows):raise ValueError('恒久seenに複数実参加を混入')
        groups.append(group)
    a,b=groups;common=set(a)&set(b);same={t for t in common if a[t]['entry_order']['request_time']==b[t]['entry_order']['request_time'] and all(a[t]['lot'][n]==b[t]['lot'][n] for n in ('side','entry_time','entry_price','initial_quantity','entry_index','entry_line'))}
    changed=common-same;only_a=set(a)-set(b);only_b=set(b)-set(a);net=lambda group,subset:sum(group[t]['lot']['net_pnl'] for t in subset)
    out={'比較':keys,'同参照ID':len(common),'同実新規':len(same),'共通だが取得変更':len(changed),'Aのみ':len(only_a),'Bのみ':len(only_b),
      '同実新規A損益円':net(a,same),'同実新規B損益円':net(b,same),'同実新規出口差円':net(b,same)-net(a,same),
      '取得変更A損益円':net(a,changed),'取得変更B損益円':net(b,changed),'Aのみ損益円':net(a,only_a),'Bのみ損益円':net(b,only_b),'全差円':net(b,set(b))-net(a,set(a))}
    if out['全差円']!=out['同実新規出口差円']+out['取得変更B損益円']-out['取得変更A損益円']+out['Bのみ損益円']-out['Aのみ損益円']:raise ValueError('入口差の全額寄与不一致')
    return out


def summarize_scenes(scenes: list[dict], calendar_check: bool = True) -> dict:
    """
    機能: 渡された人工会計だけを固定80照合と既存玉診断で集約する。
    引数: scenes(list[dict])、calendar_check(bool)は保存一場列と全予定枠scope。
    返り値: dictは比較/場別/診断/会計のwork用値。金融数値器を新実装しない。
    """
    if not scenes or len({s['session'] for s in scenes})!=len(scenes):raise ValueError('一意な場入力が必要')
    diagnostics=[r for s in scenes for r in SAVED.diagnostic_rows(s)];checks=[];per_session=[];summaries={}
    for key in KEYS:
        cumulative=peak=dd=0;totals=Counter();counts=Counter();daily=Counter();actions=Counter();policy=Counter();values=[]
        for scene in scenes:
            book=scene['books'][key];m=book['metrics']
            if book['mode']!='S0G1' or book['source_policy']!='S' or book['fill_delay_seconds']!=int(key[-1]) or book['hold_enabled'] is not False or book['confirm_enabled'] is not False:raise ValueError('旧89金融の対応差')
            if calendar_check:checks.append({'session':scene['session'],'key':key,**BASE.cash_check(book)})
            if book['unresolved'] or m['open_quantity']!=0:raise ValueError('未完結会計')
            dd=max(dd,m['max_drawdown_yen'],peak-cumulative-m['min_equity_yen']);peak=max(peak,cumulative+m['equity_peak_yen']);cumulative+=m['net_pnl_yen'];values.append(m['net_pnl_yen']);daily[scene['session'][:10]]+=m['net_pnl_yen']
            for n,v in m.items():
                if n in ('cash_yen','net_pnl_yen','gross_pnl_yen','commission_yen','slippage_yen','total_cost_yen') or type(v) is int and not n.endswith('_yen') and n!='request_before_floor_violations':totals[n]+=v
            counts.update(m['confirm_counts']);financial=Counter(d['action'] for d in book['decisions']);pa=policy_actions(scene,key);actions.update(financial);policy.update(pa)
            per_session.append({'session':scene['session'],'key':key,'mode':key.split('_D')[0],'delay':int(key[-1]),'metrics':deepcopy(m),'累積損益円':cumulative,'判断':dict(financial),'方針判断':pa,'警告':deepcopy(book['warnings'])})
        rows=[r for r in diagnostics if r['key']==key];lots=[r['lot'] for r in rows];pieces=[c for r in rows for c in r['closed']];reason_qty=Counter();reason_net=Counter()
        for c in pieces:reason_qty[c['reason']]+=c['quantity'];reason_net[c['reason']]+=c['pnl5']
        summaries[key]={'mode':key.split('_D')[0],'追加遅延秒':int(key[-1]),'費用後損益円':cumulative,'最大DD円':dd,'全場':len(values),'赤字場数':sum(v<0 for v in values),'黒字場数':sum(v>0 for v in values),'同値場数':sum(v==0 for v in values),'日別円':dict(daily),'赤字日数':sum(v<0 for v in daily.values()),'日数':len(daily),
          '完結玉':len(lots),'新規枚数':sum(p['initial_quantity'] for p in lots),'総計':dict(totals),'複合確認5群':dict(counts),'判断':dict(actions),'方針判断':dict(policy),'返済理由別枚数':dict(reason_qty),'返済理由別損益円':dict(reason_net),
          '正益未観測の損益円':sum(p['net_pnl'] for p in lots if not p['flag']),'正益観測の損益円':sum(p['net_pnl'] for p in lots if p['flag']),'上位3場利益円':sum(sorted(values,reverse=True)[:3]),'最悪場円':min(values),'最大場円':max(values),
          '同約定0pt損益円':sum(c['pnl0'] for c in pieces),'同約定10pt損益円':sum(c['pnl10'] for c in pieces)}
        for flag,label,loss in (('flag','残玉旗','残玉旗後赤字'),('whole_flag','全玉旗','全玉旗後赤字')):summaries[key][label]=sum(p[flag] for p in lots);summaries[key][loss]=sum(p[flag] and p['net_pnl']<0 for p in lots)
    return {'状態':'未採番work人工','場数':len(scenes),'金融内部モード':{'H0G1':'S0G1','H1G1':'S0G1'},'比較':summaries,'場別':per_session,'出口間の同実新規分解':{f'H1G1対H0G1_D{d}':comparison(diagnostics,d) for d in (0,1)},'同実入口の定義':'要求時計/side/実取得時計/価格/初期量/実Index/物理Lineすべて同値','診断':diagnostics,'会計照合':checks,'暦全枠照合':calendar_check,'固定80会計SHA256':BASE_SHA,'固定89保存SHA256':SAVED.FIXED_SHA}


def write_artifacts(output: Path, scenes: list[dict], value: dict) -> None:
    """
    機能: 明示workの新規先へViewer互換約定と圧縮診断を保存する。
    引数: output(Path)、scenes(list)、value(dict)は新規work又は正式92先と検査済値。
    返り値: None。既存先/旧試行へ書き込まず内部価格や所有を改名しない。
    """
    work=(ROOT/'work').resolve();target=output.resolve()
    formal=(ROOT/'study/00092_価格帯奪還と保持後の独立再開/成果物').resolve()
    if not (target.is_relative_to(work) or target==formal) or target.exists():raise ValueError('新規work又は正式92成果物だけ出力可能')
    target.mkdir(parents=True);catalog=[]
    for scene in scenes:
        for key in KEYS:
            mode=key.split('_D')[0];rel=f'約定/{key}/{scene["session"]}.trades.jsonl';p=target/rel;p.parent.mkdir(parents=True,exist_ok=True)
            with p.open('x',encoding='utf-8',newline='\n') as stream:
                for trade in scene['books'][key]['trades']:stream.write(json.dumps({**trade,'method_id':mode},ensure_ascii=False,separators=(',',':'),allow_nan=False)+'\n')
            catalog.append({'id':f'92_{key}_{scene["session"]}','title':f'92 {key} {scene["session"]}','symbol':'NK225','session':scene['session'],'product':'NK225micro','method_id':mode,'point_value':10,'pnl_format':'trades','pnl_basis':'net','pnl_path':rel,'market_path':f'NK225/{scene["session"]}/book.jsonl.gz'})
    for name,data in (('結果.json',{k:v for k,v in value.items() if k not in ('診断','会計照合')}),('一覧.resources.json',{'schema_version':1,'path_base':'catalog','resources':catalog}),('約定会計照合.json',{'会計数':len(value['会計照合']),'不一致数':0,'照合':value['会計照合'],'暦全枠照合':value['暦全枠照合']})):
        with (target/name).open('x',encoding='utf-8',newline='\n') as stream:json.dump(data,stream,ensure_ascii=False,indent=2,allow_nan=False);stream.write('\n')
    with gzip.open(target/'取引診断.jsonl.gz','xt',encoding='utf-8') as stream:
        for row in value['診断']:stream.write(json.dumps(row,ensure_ascii=False,separators=(',',':'),allow_nan=False)+'\n')
    for name,rows in (('定時判断.jsonl.gz',[{n:s[n] for n in ('session','grid_decisions','source_events','source_equivalence','entry_observations','technical_equivalence','seed_view','profit_contexts','input_end','price_decisions','price_counts')} for s in scenes]),
                      ('参照判断と通知効果.jsonl.gz',[{'session':s['session'],'books':{key:{n:s['books'][key][n] for n in ('source_policy','decisions','source_effects')} for key in KEYS},'entry_bindings':s['entry_bindings'],'price_bindings':s['price_bindings']} for s in scenes])):
        with gzip.open(target/name,'xt',encoding='utf-8') as stream:
            for row in rows:stream.write(json.dumps(row,ensure_ascii=False,separators=(',',':'),allow_nan=False)+'\n')


def summarize(source: Path, output: Path, manifest: Path) -> dict:
    """
    機能: Root承認後に固定66場の保存JSONを集約する既定APIを提供する。
    引数: source/output/manifest(Path)は保存JSON根・新規work出力・固定台帳。
    返り値: dictは264会計の比較正本。原板/売買/APIを実行しない。
    """
    ledger=json.loads(manifest.read_text(encoding='utf-8'));entries=ledger['sessions']
    if len(entries)!=66 or len({e['id'] for e in entries})!=66:raise ValueError('固定66場の台帳が必要')
    scenes=[];fingerprints={}
    for entry in entries:
        path=source/(entry['id']+'.json');fingerprints[path.name]=hashlib.sha256(path.read_bytes()).hexdigest();scene=json.loads(path.read_text(encoding='utf-8'))
        if scene['session']!=entry['id'] or set(scene['books'])!=set(KEYS):raise ValueError('保存場/4会計集合差')
        for name,a,b in (('source_equivalence','current_sha256','legacy_sha256'),('technical_equivalence','actual_sha256','event_sha256')):
            eq=scene[name]
            if eq['mismatches']!=0 or eq[a]!=eq[b] or len(eq[a])!=64:raise ValueError('正式対象へ未計測互換を混入')
        scenes.append(scene)
    value=summarize_scenes(scenes);counts=Counter();resets=Counter();availability={}
    for scene in scenes:
        counts.update({k:v for k,v in scene['price_counts'].items() if k!='resets'});resets.update(scene['price_counts']['resets'])
    for policy in ('H0','H1'):
        pool=[p for scene in scenes for g in scene['price_decisions'] for p in g['policies'][policy]['pool']]
        availability[policy]={'原pool延べ候補':len(pool),'資格既知':sum(p['known'] for p in pool),'資格成立':sum(p['allowed'] for p in pool),'必須未知':sum(p['required_unknown'] for p in pool),
          '理由':dict(Counter(p['reason'] for p in pool)),'供給延べID':sum(len(g['policies'][policy]['supplied_ids']) for scene in scenes for g in scene['price_decisions'])}
    value.update({'試行':92,'状態':'固定条件の全66場集計','全場既使用':True,'保持帯床有効':False,'構造床有効':dict.fromkeys(('H0G1','H1G1'),False),'複合確認有効':dict.fromkeys(('H0G1','H1G1'),False),
      'Source入口':dict.fromkeys(('H0G1','H1G1'),'S'),'外入口':{'H0G1':'旧E1','H1G1':'現在E0＋独立価格v'},'利益配分':dict.fromkeys(('H0G1','H1G1'),'G1'),'入力台帳SHA256':hashlib.sha256(manifest.read_bytes()).hexdigest(),
      '再生結果SHA256':fingerprints,'入力品質':{s['session']:s['quality'] for s in scenes},'独立価格の分母':{**dict(counts),'resets':dict(resets)},'外資格と供給':availability})
    write_artifacts(output,scenes,value)
    if fingerprints!={e['id']+'.json':hashlib.sha256((source/(e['id']+'.json')).read_bytes()).hexdigest() for e in entries}:raise ValueError('保存入力が集計中に変化')
    return value


def main() -> None:
    """
    機能: Root承認後に明示66場JSONを集約するCLIを提供する。
    引数: --input/--out/--manifest(Path)は保存根・新規先・固定台帳。
    返り値: None。未完/不一致は非0。原板/市場/新APIを実行しない。
    """
    parser=argparse.ArgumentParser(description='92独立価格入口の固定金融集計')
    for name in ('input','out','manifest'):parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args();value=summarize(args.input,args.out,args.manifest)
    print(json.dumps({'場数':value['場数'],'会計数':len(value['場別']),'比較':{k:v['費用後損益円'] for k,v in value['比較'].items()}},ensure_ascii=False))


if __name__=='__main__':main()
