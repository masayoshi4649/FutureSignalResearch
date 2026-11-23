"""旧十場を通して11月18日デイの日経199_02を再生する。"""
from pathlib import Path
from datetime import datetime, timezone, timedelta
from argparse import ArgumentParser
import gzip
import hashlib
import json
import subprocess
import sys

import numpy as np

HERE=Path(__file__).resolve().parent
STUDY=HERE.parent
ROOT=STUDY.parents[1]
OUT=ROOT/'work/213保留診断/日経追加'
OLD=next((ROOT/'inputs').glob('00194_*'))/'NK225'
NEW=('2026-11-17_Night','2026-11-18_Day')


# ----------------------------------------
def ref(path: Path) -> dict:
    """
    機能: 入力の物理指紋を取得する。
    引数: path(Path)は対象ファイル。
    返り値: dictはパス、サイズ、SHA256。
    """
    with path.open('rb') as stream:
        digest=hashlib.file_digest(stream,'sha256').hexdigest()
    return {'path':str(path),'bytes':path.stat().st_size,'sha256':digest}


# ----------------------------------------
def read(path: Path) -> object:
    """
    機能: UTF-8 JSONを読み込む。
    引数: path(Path)は圧縮又は通常のJSON。
    返り値: objectは復号結果。
    """
    payload=path.read_bytes()
    return json.loads(gzip.decompress(payload) if path.suffix=='.gz' else payload)


# ----------------------------------------
def save(path: Path, data: object) -> None:
    """
    機能: 新しい成果物を保存し、再実行時は同体を確認する。
    引数: path(Path)は保存先、data(object)はJSON化可能な結果。
    返り値: None。
    """
    if path.exists():
        assert read(path)==data,path
    else:
        path.write_text(json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')


# ----------------------------------------
def prepare(build_population: bool) -> tuple:
    """
    機能: 試行194の既存履歴へ2場だけ追加し、同じGo生成器で当時特徴を得る。
    引数: build_population(bool)は旧十場から非金融母集団も再生成するか。
    返り値: tupleは全12場の計画、索引参照、追加2場の原板・足の指紋。
    """
    OUT.mkdir(parents=True,exist_ok=True)
    old=read(OLD/'母集団接続計画.json')
    previous=read(OLD/'前史八場と追加二場の索引参照.json')['scenes']
    dates=timezone(timedelta(hours=9))
    input_rows=[]
    for name in NEW:
        folder=ROOT.parent/'JP_OSE_Data/future/NK225'/name
        raw=folder/'book.jsonl.gz'
        if not raw.exists():
            raw=folder/'book.jsonl'
        with (gzip.open(raw,'rb') if raw.suffix=='.gz' else raw.open('rb')) as stream:
            contract=json.loads(stream.readline())['Symbol']
        day=name.endswith('_Day')
        date=datetime.fromisoformat(name[:10]).replace(tzinfo=dates)
        start=date+(timedelta(hours=8,minutes=45) if day else timedelta(hours=17))
        end=date+(timedelta(hours=15,minutes=45) if day else timedelta(days=1,hours=6))
        input_rows.append({'session':name,'contract':contract,'start':start.timestamp(),'end':end.timestamp(),
                       'force_close':end.timestamp()-600,'raw':ref(raw),'expected_accepted':0,'expected_quality':None,
                       'expected_raw_stat':{'bytes':raw.stat().st_size,'mtime_ns':raw.stat().st_mtime_ns},'entries':[]})
    spec=OUT/'原板索引計画.json'
    save(spec,{'trial':213,'scenes':input_rows,'expected_entry_count':0})
    indexed=OUT/'原行索引'
    if not (indexed/'manifest.json').exists():
        subprocess.run([str(ROOT/'work/166可変場の観測/可変場観測.exe'),'--mode','index','--input',str(spec),
                        '--sha256',ref(spec)['sha256'],'--output-dir',str(indexed),'--workers','2'],check=True)
    items=read(indexed/'manifest.json')['scenes']
    extra=[]
    for row,item in zip(input_rows,items,strict=True):
        assert row['session']==item['session'] and item['success']
        folder=ROOT.parent/'JP_OSE_Data/future/NK225'/row['session']
        item['index']['path']=str(indexed/item['index']['path'])
        extra.append({**{k:row[k] for k in ('session','contract','start','end','force_close','raw')},
                      'expected_accepted':item['rows'],'expected_quality':item['quality'],
                      'quote_index':ref(Path(item['index']['path'])),
                      'csv_1m':ref(folder/'candle_1min.csv'),'csv_5m':ref(folder/'candle_5min.csv')})
    combined=OUT/'前史十場と追加二場の索引参照.json'
    save(combined,{'success':True,'scenes':previous+items})
    plan=OUT/'前史十場と追加二場の母集団計画.json'
    scenes=old['scenes']+extra
    save(plan,{**old,'trial':213,'index_manifest':ref(combined),'scenes':scenes})
    if build_population and not (OUT/'母集団/完了.json').exists():
        pin=ref(plan)
        subprocess.run([str(ROOT/'work/未見入口の同体接続/入口同体接続.exe'),'--execute-after-f0','--plan',str(plan),
                        '--plan-sha',pin['sha256'],'--plan-bytes',str(pin['bytes']),'--output',str(OUT/'母集団')],check=True)
    return scenes,previous+items,extra


# ----------------------------------------
def main() -> None:
    """
    機能: 固定入口の同体を点検し、旧デイと追加デイの単一建玉口座を再生する。
    引数: なし。外部データと再現Sourceを復元したリポジトリ内で実行する。
    返り値: None。
    """
    parser=ArgumentParser()
    parser.add_argument('--固定出生から',action='store_true')
    args=parser.parse_args()
    scenes,items,extra=prepare(not args.固定出生から)
    if not args.固定出生から:
        builder=ROOT/'work/今回移植/純入口を作る.py'
        subprocess.run([sys.executable,str(builder),'--folder',str(OUT)],check=True)
    sys.path.insert(0,str(STUDY))
    import 金融再生 as finance
    old=next((ROOT/'study').glob('00199_*'))
    saved=read(next((old/'追加二場/保存金融').glob('*_02__C0_IFD.json.gz')))['ledger']
    saved_rows=[{k:v[i] for k,v in saved.items()} for i,s in enumerate(saved['scene']) if s=='2026-11-17_Day']
    prefix=0
    if not args.固定出生から:
        for name in ('当時特徴.json.gz','取得対応.json.gz'):
            prior=read(OLD/'入口母集団'/name)['rows']
            projected=[r for r in read(OUT/'母集団'/name)['rows'] if r['session'] in ('2026-11-16_Night','2026-11-17_Day')]
            assert prior==projected,name
            prefix+=len(prior)
    runs={}
    for label in ('純入口','基準179'):
        fixed=HERE/(label+'の二デイ.npz')
        source=fixed if args.固定出生から else OUT/(label+'.npz')
        with np.load(source,allow_pickle=False) as data:
            arrays={k:data[k] for k in data.files}
        if not args.固定出生から:
            selected=np.isin(arrays['scene'],[9,11])
            reduced={k:values[selected] for k,values in arrays.items()}
            if not fixed.exists():
                np.savez_compressed(fixed,**reduced)
            with np.load(fixed,allow_pickle=False) as expected:
                for k,values in reduced.items():
                    np.testing.assert_array_equal(values,expected[k])
        rows=[]
        for i in (9,11):
            spec,item=scenes[i],items[i]
            assert spec['session'] in ('2026-11-17_Day',NEW[1]) and spec['session']==item['session']
            trades,_=finance.account(arrays,i,spec,finance.load_scene(OUT,item),1.0,'NK225')
            if i==9 and label=='純入口':
                assert len(trades)==len(saved_rows)
                for x,y in zip(trades,saved_rows,strict=True):
                    for k in ('entry_index','entry_line','entry_time','entry_price','exit_index','exit_line','exit_time','exit_price','side','width','horizon','net','origin'):
                        assert x[k]==y[k],(k,x[k],y[k])
            if i==11:
                rows=trades
        gains=sum(t['net'] for t in rows if t['net'] is not None and t['net']>0)
        losses=-sum(t['net'] for t in rows if t['net'] is not None and t['net']<0)
        unknown=sum(t['net'] is None for t in rows)
        held=sum(t['confirmed_until']-t['entry_time'] for t in rows)
        runs[label]={'建玉数':len(rows),'未知':unknown,'利益':gains,'損失':losses,'既知収支':gains-losses,
                     '保有時間率下限':held/(scenes[-1]['end']-900-scenes[-1]['start']),'建玉':rows}
    if args.固定出生から:
        assert read(HERE/'追加デイの照合結果.json')['結果']==runs
    else:
        result={'対象':NEW[1],'履歴':NEW[0],'既存前史2場の当時特徴行と取得対応行の一致合計':prefix,
            '11月17日デイ199_02の既存台帳一致数':len(saved_rows),'入力':extra,'結果':runs}
        save(HERE/'追加デイの照合結果.json',result)
    print(json.dumps({n:{k:v for k,v in row.items() if k!='建玉'} for n,row in runs.items()},ensure_ascii=False))


if __name__=='__main__':
    main()
