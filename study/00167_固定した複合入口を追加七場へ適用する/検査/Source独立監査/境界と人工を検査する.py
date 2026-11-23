"""167固定適用のSource境界とゼロ取得・IFD成熟等を人工入力だけで監査する。"""
from pathlib import Path
from types import SimpleNamespace
from datetime import datetime,timezone,timedelta
import ast
import gzip
import importlib.util
import json
import math
import sys

import numpy as np

ROOT=Path(__file__).resolve().parents[2]
HERE=Path(__file__).resolve().parent
TARGET=ROOT/'work/167固定入口の別期間'
TRIAL=ROOT/'study/00167_固定した複合入口を追加七場へ適用する'
BOOK_SHA='73e16eabfc3364a9e038d9697472abe50bb91fbba49b488dd0c8ed8d5eaea9f4'
HELPER=ROOT/'work/165自然独立確認/自然値を独立検算する.py'
spec=importlib.util.spec_from_file_location('audit167_io',HELPER);io=importlib.util.module_from_spec(spec);spec.loader.exec_module(io)
read=io.read;save=io.save;sha=io.sha
sys.path.insert(0,str(TARGET))
spec=importlib.util.spec_from_file_location('audit167_target',TARGET/'適用基盤167.py')
target=importlib.util.module_from_spec(spec);spec.loader.exec_module(target)


class ArtificialTable:
    """自然価格を一切受け取らない最小の数値表。"""
    def __init__(self,scenes: list,cases: list) -> None:
        """
        機能: 人工caseだけから既存tableと同じ最小APIを用意する。
        引数: self(ArtificialTable)、scenes(list[dict])、cases(list[dict])。
        返り値: None。両実側・12幅・4期限の人工金融を保持する。
        """
        self.widths=(125,150,175,200,225,250,300,350,400,500,750,1000)
        self.horizons=('H30','H60','H120','SESSION');self.session_order=tuple(s['session'] for s in scenes)
        self.case_ids=tuple(c['id'] for c in cases);self.sessions=tuple(self.session_order[c['scene']] for c in cases)
        shape=(len(cases),2,12,4);self.arrays={
            'label':np.full(shape,2,dtype=np.int8),'known':np.zeros(shape,dtype=bool),
            'direction':np.zeros(shape,dtype=np.int8),'net':np.zeros(shape,dtype=np.int64),
            'exit_time':np.full(shape,np.nan),'known_at':np.full(shape,np.nan),
            'entry_time':np.asarray([c['q1']['time'] for c in cases],dtype=float),
            'entry_index':np.asarray([c['q1']['index'] for c in cases],dtype=np.int64),
            'entry_line':np.asarray([c['q1']['source_line'] for c in cases],dtype=np.int64),
            'session_index':np.asarray([c['scene'] for c in cases],dtype=np.int16)}
        for i,case in enumerate(cases):
            for name in ('label','known','direction','net'):self.arrays[name][i]=case[name]
            self.arrays['exit_time'][i]=case['q1']['time']+20
            self.arrays['known_at'][i]=case['q1']['time']+60 if case['label']==0 else np.nan

    def root_arrays(self) -> dict:
        """
        機能: GenericContextが読む配列のcopyを返す。
        引数: self(ArtificialTable)。
        返り値: dict[str,np.ndarray]は人工配列。
        """
        return {name:value.copy() for name,value in self.arrays.items() if name!='direction'}

    def case_to_index(self) -> dict:
        """
        機能: 人工caseIDを順序へ結ぶ。
        引数: self(ArtificialTable)。
        返り値: dict[str,int]は一意な対応。
        """
        return {name:i for i,name in enumerate(self.case_ids)}


def quote(at: float,index: int) -> dict:
    """
    機能: 自然値と無関係な正常BBO付き人工気配を作る。
    引数: at(float)、index(int)は人工時計と原行番号。
    返り値: dictは人工q0/q1。
    """
    return {'time':at,'index':index,'source_line':index+1,'last':1000,'bid':995,'ask':1005,'quote_ok':True}


def make_features(columns: list,scenes: list,events: list,buy: np.ndarray|None=None,sell: np.ndarray|None=None) -> object:
    """
    機能: 原100列の名前だけを使い、人工q0と未知特徴を接続する。
    引数: columns(list[str])、scenes/events(list[dict])、buy/sell(np.ndarray又はNone)。
    返り値: FeatureDatasetは新自然場を読まずに作った入力。
    """
    data=target.data_module();n=len(events)
    return data.feature_dataset_from_objects(columns,np.full((n,100),np.nan) if buy is None else buy,
        np.full((n,100),np.nan) if sell is None else sell,events,scenes,{'人工':True},len(scenes),n)


def artificial_loader(columns: list,scenes: list) -> None:
    """
    機能: 完了票付きの0q0接続を作り、型・SHA・価格未入力の検査を確認する。
    引数: columns(list[str])、scenes(list[dict])は人工列と人工場。
    返り値: None。fixtureはwork内だけへ保存する。
    """
    folder=HERE/'人工0取得';folder.mkdir(exist_ok=True)
    objects={'当時特徴.json.gz':{'success':True,'financial_labels_used':False,'rows':[],
                                  'catalog':[{'name':name} for name in columns]},
             '固定取得入力.json.gz':{'success':True,'financial_labels_used':False,'scenes':scenes},
             '取得対応.json.gz':{'success':True,'financial_labels_used':False,'rows':[]}}
    files={}
    for name,obj in objects.items():
        path=folder/name;path.write_bytes(gzip.compress(json.dumps(obj).encode('utf-8'),mtime=0))
        files[name]={'bytes':path.stat().st_size,'sha256':sha(path)}
    save(folder/'完了.json',{'success':True,'financial_labels_used':False,'strategy_selected':False,'files':files})
    features,captures,refs=target.load_features(folder)
    assert len(features.q0_meta)==0 and features.buy_X.shape==features.sell_X.shape==(0,100) and captures==[]
    assert refs==files and len(features.scenes)==len(scenes)
    # 入力の未知・0行を補完して偽q0を作らない。指紋不一致は拒否する。
    altered=folder/'当時特徴.json.gz';body=altered.read_bytes();altered.write_bytes(body+b'X')
    try:target.load_features(folder)
    except AssertionError:pass
    else:raise AssertionError('改ざん入力を拒否しなかった')
    altered.write_bytes(body)


def main() -> None:
    """
    機能: 固定条件・依存SHA・非金融Source境界と人工の分母/成熟/制御を検査する。
    引数: なし。追加7場の自然母集団・Raw・金融は開かない。
    返り値: None。Source監査票と停止票を保存する。
    """
    sys.stdout.reconfigure(encoding='utf-8');assert sha(TRIAL/'条件.json')==BOOK_SHA
    paths=[Path(__file__),HELPER,TARGET/'適用基盤167.py',TARGET/'適用する.py',TARGET/'旧73の同体を確認する.py',
           TARGET/'旧73の同体.json',TRIAL/'条件.json',TRIAL/'検査/F0_追加価格参照前.json',
           ROOT/'work/165順行と回復失敗の複合/出生を作る.py',ROOT/'work/165順行と回復失敗の複合/評価基盤165.py',
           ROOT/'work/166可用指標の階層化/local166.py',ROOT/'work/162複合入口候補/rules162.py',
           ROOT/'work/162入口探索/評価基盤.py',ROOT/'work/161三時間帯入口のデータ/data161.py',
           ROOT/'inputs/00148_全1分入口母集団/100特徴の列定義.json']
    before={p.relative_to(ROOT).as_posix():sha(p) for p in paths};setting=read(paths[6]);old=read(paths[5])
    assert old['成功'] and old['追加七場価格未読']
    assert old['Source']['適用基盤167.py']==sha(paths[2])
    for ref in setting['source_references'].values():assert sha(ROOT/ref['path'])==ref['sha256']
    assert [row['id'] for row in setting['candidates']]==['PRIMARY','FRONT48']
    previous=read(ROOT/'work/166可用指標の階層化/比較/主案と探索結果.json')
    for candidate,name in zip(setting['candidates'],('事前固定主案','前48場だけで選択'),strict=True):
        origin=previous[name]
        for key in ('profile','hierarchy','momentum_width','fade_width','horizon','integration'):assert candidate[key]==origin[key]
    assert target.GenericContext.link is target.Context.link
    assert target.GenericContext.technical_integrate is target.Context165.technical_integrate
    tree=ast.parse(paths[2].read_text(encoding='utf-8'));functions={node.name:node for node in tree.body if isinstance(node,ast.FunctionDef)}
    assert [arg.arg for arg in functions['births'].args.args]==['features','candidate']
    forbidden={'open','read','load','load_table','statistics','GenericContext','selection'}
    called={node.func.id for node in ast.walk(functions['births']) if isinstance(node,ast.Call) and isinstance(node.func,ast.Name)}
    assert not called&forbidden
    runner=ast.parse(paths[3].read_text(encoding='utf-8'));generation=next(node for node in runner.body if isinstance(node,ast.FunctionDef) and node.name=='generate')
    names={node.id for node in ast.walk(generation) if isinstance(node,ast.Name)}
    assert not {'adapter','GenericContext','numeric','statistics','evaluate'}&names
    columns=[row['name'] for row in read(paths[14])]
    starts=[datetime.fromisoformat(day+'T08:45:00').replace(tzinfo=timezone(timedelta(hours=9))).timestamp()
            for day in ('2020-01-06','2020-01-07','2020-01-08')]
    scenes=[{'session':day+'_Day','contract':'ARTIFICIAL','start':start,'end':start+7*3600,'force_close':start+6*3600}
            for day,start in zip(('2020-01-06','2020-01-07','2020-01-08'),starts,strict=True)]
    artificial_loader(columns,scenes)
    empty=make_features(columns,scenes,[]);table=ArtificialTable(scenes,[]);context=target.GenericContext(empty,table,[])
    zero_tests=0
    for candidate in setting['candidates']:
        born=target.births(empty,candidate)
        assert all(array.shape==(0,) for array in born.values())
        selected,origins,widths,tiers,audits=target.selection(context,born,candidate)
        assert len(selected.cases)==0 and len(audits)==3
        value=target.statistics(context,selected,widths,1)
        assert value['count']==value['F']==value['A']==value['N']==value['C']==value['net']==0
        assert value['rate'] is value['realized_win_rate'] is value['pf'] is None
        assert value['all_net']==0 and value['eligible_scenes']==3 and not value['all_scenes']
        assert abs(value['hours']-3*(7-5/60))<1e-12 and value['per_hour']==0
        zero_tests+=1
    # ----------------------------------------
    # strictがCでも打切り前touchはF/Aとして成熟し、未確定はC/全収支未知を残す。
    cases=[];events=[];captures=[]
    for i,(label,known,direction,net) in enumerate(((2,True,1,1000),(2,True,-1,-1100),(0,True,0,-10),
                                               (2,False,0,0),(1,True,1,2000),(-1,True,-1,-2100))):
        q=quote(starts[0]+300+i*60,i*10);q1=quote(q['time']+1,i*10+1);identifier=f'artificial{i}'
        events.append({'event_id':identifier,'session':scenes[0]['session'],'contract':'ARTIFICIAL','session_index':0,
                       'q0_time':q['time'],'q0_index':q['index'],'q0_line':q['source_line']})
        cases.append({'id':identifier,'scene':0,'q1':q1,'label':label,'known':known,'direction':direction,'net':net})
        captures.append({'event_id':identifier,'q0':q,'q1':q1,'case_id':identifier,'status':'filled',
                         'expires':q['time']+30,'terminated_at':q1})
    features=make_features(columns,scenes,events);table=ArtificialTable(scenes,cases);context=target.GenericContext(features,table,captures)
    assert context.arrays['label'][:,0,0,0].tolist()==[1,-1,0,2,1,-1]
    assert context.arrays['known_at'][:,0,0,0][[0,1,4,5]].tolist()==context.arrays['exit_time'][:,0,0,0][[0,1,4,5]].tolist()
    assert math.isnan(context.arrays['known_at'][3,0,0,0])
    chosen=context.link(np.ones(6,dtype=np.int8));widths=np.zeros(6,dtype=np.int8)
    value=target.statistics(context,chosen,widths,0)
    assert value['count']==6 and (value['F'],value['A'],value['N'],value['C'])==(2,2,1,1)
    assert (value['profit'],value['loss'],value['net'],value['known'],value['unknown'])==(3000,3210,-210,5,1)
    assert value['all_net'] is None and value['rate']==.5 and value['realized_win_rate']==.4
    only_n=np.arange(6)==2;zero_arrivals=target.statistics(context,chosen,widths,0,only_n)
    assert zero_arrivals['rate'] is None and zero_arrivals['complete_rate']==0 and zero_arrivals['all_net']==-10
    only_c=np.arange(6)==3;unknown=target.statistics(context,chosen,widths,0,only_c)
    assert unknown['net']==0 and unknown['known']==0 and unknown['all_net'] is None
    none=target.statistics(context,chosen,widths,0,np.zeros(6,dtype=bool),np.zeros(3,dtype=bool))
    assert none['per_hour'] is None and none['hours']==0 and not none['all_scenes']
    # ----------------------------------------
    # 人工q0だけで未来prefix不変・売買反射・旧T優先を確認する。
    n=18;fake_events=[]
    for i in range(n):
        fake_events.append({'event_id':f'prefix{i}','session':scenes[0]['session'],'contract':'ARTIFICIAL',
                            'session_index':0,'q0_time':starts[0]+3*3600+i*60,'q0_index':100+i*10,'q0_line':101+i*10})
    rng=np.random.default_rng(167);buy=rng.uniform(-1,1,(n,100));sell=rng.uniform(-1,1,(n,100))
    # 必要列をランダムに欠測させ、長期増分は後半で初めて公表する。
    buy[rng.random(buy.shape)<.1]=np.nan;sell[rng.random(sell.shape)<.1]=np.nan
    ci=columns.index('m15_hist_delta_to_side');buy[:12,ci]=np.nan;sell[:12,ci]=np.nan
    full=make_features(columns,scenes,fake_events,buy,sell);mirrored=make_features(columns,scenes,fake_events,sell,buy)
    prefix_tests=0
    for candidate in setting['candidates']:
        born=target.births(full,candidate);mirror=target.births(mirrored,candidate)
        for name in ('core','technical','oldtechnical','local'):assert np.array_equal(born[name],-mirror[name])
        for length in range(n+1):
            prefix=make_features(columns,scenes,fake_events[:length],buy[:length],sell[:length]);out=target.births(prefix,candidate)
            for name,value in born.items():assert np.array_equal(out[name],value[:length]),(name,length)
            prefix_tests+=1
        assert np.array_equal(born['technical'][born['oldtechnical']!=0],born['oldtechnical'][born['oldtechnical']!=0])
    assert all(sha(ROOT/name)==digest for name,digest in before.items())
    save(HERE/'Sourceと人工の確認.json',{'成功':True,'trial':167,'条件SHA256':BOOK_SHA,'Sourceと固定入力':before,
         '候補固定':'PRIMARY/FRONT48は166記録と全設定一致。追加価格に合わせる選択・再推定なし。',
         '出生の金融引数':False,'出生生成の金融読取':False,'旧73同体票を指紋確認':True,
         '当時制御':'Context.link/Context165.technical_integrateを関数同体で再利用。q0/q1原行キー検査。',
         '人工0取得候補数':zero_tests,'人工IFD成熟ケース数':6,'人工0到達と未定義分母':True,
         '人工未知全収支null':True,'人工改ざん入力拒否':True,'人工売買反射候補数':2,'人工未来prefix回数':prefix_tests,
         '本監査の追加7場価格読取':False,'元Source変更':False,
         '限界':'Source境界と人工のみ。追加7場の自然結果、全26政策、接続器自体の全実装の再監査は別途。'})
    save(HERE/'Source監査の停止.json',{'成功':True,'SourceSHA256':sha(Path(__file__)),
         '検査票SHA256':sha(HERE/'Sourceと人工の確認.json'),'追加自然価格未読':True})
    print(json.dumps({'成功':True,'人工prefix':prefix_tests,'検査票SHA256':sha(HERE/'Sourceと人工の確認.json')},ensure_ascii=False))


if __name__=='__main__':
    main()
