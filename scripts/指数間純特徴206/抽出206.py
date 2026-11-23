"""既存8列と金融未使用q0だけから、両指数の固定端点純特徴を生成する。"""
from collections import Counter,defaultdict
from datetime import datetime,timedelta,timezone
from pathlib import Path
from zoneinfo import ZoneInfo
import argparse
import gzip
import hashlib
import json
import sys
import types
import zipfile
import numpy as np
from 特徴核 import features,timeline,DELAYS,HORIZONS,OFFSETS,REASONS,FIELDS

ROOT=Path(__file__).resolve().parents[2]
HERE=Path(__file__).parent
DEST=ROOT/'inputs/00206_両指数の固定端点相対変化'
PLAN=DEST/'抽出前固定.json.gz'
QPLAN=ROOT/'inputs/00201_両指数の板数量純特徴/抽出前固定.json.gz'
LEGACY=ROOT/'docs/データ監査/指数間の価格時計可用性/Source.zip'
JST=timezone(timedelta(hours=9))


# ----------------------------------------
def read(path: Path) -> object:
    """
    機能: UTF-8のJSON又はgzip JSONを読む。
    引数: path(Path)は対象。
    返り値: objectは解析値。
    """
    body=path.read_bytes();return json.loads(gzip.decompress(body) if path.suffix=='.gz' else body)


# ----------------------------------------
def ref(path: Path) -> dict:
    """
    機能: 入力を変更せず相対path・物理SHA・statを得る。
    引数: path(Path)は対象。
    返り値: dictは指紋とmtime。
    """
    before=path.stat()
    with path.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
    after=path.stat();assert (before.st_size,before.st_mtime_ns)==(after.st_size,after.st_mtime_ns)
    return {'path':path.relative_to(ROOT).as_posix(),'bytes':after.st_size,'sha256':digest,'mtime_ns':after.st_mtime_ns}


# ----------------------------------------
def save(path: Path,value: object) -> dict:
    """
    機能: 決定的JSONを新規保存し、既存なら同体を要求する。
    引数: path(Path)、value(object)。
    返り値: dictは保存指紋。
    """
    body=(json.dumps(value,ensure_ascii=False,separators=(',',':'),allow_nan=False)+'\n').encode()
    if path.suffix=='.gz':body=gzip.compress(body,mtime=0)
    path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists():assert path.read_bytes()==body,path
    else:path.write_bytes(body)
    return ref(path)


# ----------------------------------------
def bounds(session: str) -> tuple:
    """
    機能: 場開始と終了15分前の時計をUTC秒へ変換する。
    引数: session(str)は場名。
    返り値: tuple[float,float]。
    """
    day=datetime.fromisoformat(session[:10]).replace(tzinfo=JST)
    if session.endswith('_Day'):return day.replace(hour=8,minute=45).timestamp(),day.replace(hour=15,minute=30).timestamp()
    return day.replace(hour=17).timestamp(),(day+timedelta(days=1)).replace(hour=5,minute=45).timestamp()


# ----------------------------------------
def legacy_module() -> object:
    """
    機能: 既存の可用性調査Sourceを変更せず読み、初回価格系列の同体対照にする。
    引数: なし。
    返り値: objectは旧純時計module。旧mainは実行しない。
    """
    with zipfile.ZipFile(LEGACY) as archive:body=archive.read('可用性を確認する.py')
    module=types.ModuleType('legacy_clock206');module.__file__=str(ROOT/'work/指数間連動の純時計再現/可用性を確認する.py')
    exec(compile(body,module.__file__,'exec'),module.__dict__)
    return module


# ----------------------------------------
def prepare() -> dict:
    """
    機能: 既存純q0投影・166入力・仕様・Source・人工票を全抽出前に固定する。
    引数: なし。
    返り値: dictは金融なしの抽出前票。
    """
    prior=read(QPLAN);assert prior['financial_labels_used'] is False and prior['q0_counts']=={'NK225':40314,'TOPIX':35361}
    nk=ROOT/'inputs/NK225原順8列_20260921_20261116/入力台帳.json.gz'
    tx=ROOT/'inputs/TOPIX原順8列_20260921_20261116/台帳.json'
    add=ROOT/'inputs/00194_20261116夜と1117昼の固定適用入力/原順8列/入力台帳.json'
    expected={('NK225',r['session']):(r['cache_relative'],r['sha256_cache']) for r in read(nk)['entries']}
    expected.update({('TOPIX',r['session']):(r['path'],r['sha256']) for r in read(tx)['entries']})
    for r in read(add)['entries']:
        expected[(r['symbol'],r['session'])]=(f"inputs/00194_20261116夜と1117昼の固定適用入力/原順8列/{r['symbol']}/{r['session']}.npz",r['sha256_cache'])
    pure={(r['symbol'],r['session']):r['q0'] for r in prior['scenes']}
    scenes=sorted({k[1] for k in pure});assert len(scenes)==83 and set(expected)==set(pure)
    inputs=[];by={}
    for key,(name,digest) in sorted(expected.items()):
        row=ref(ROOT/name);assert row['sha256']==digest
        inputs.append(row);by[key]=row
    artificial=read(HERE/'人工確認.json');assert artificial['成功'] and not artificial['金融参照']
    for r in artificial['Source']:assert ref(HERE/r['path'])['sha256']==r['sha256']
    q0_sources=[]
    for r in prior['inputs'][:8]:
        p=Path(r['path']);current=ref(p);assert current['sha256']==r['sha256'];q0_sources.append(current)
    source=[ref(HERE/name) for name in ('特徴核.py','抽出206.py','人工確認.py','人工確認.json','仕様.md')]
    members=sorted({m for values in pure.values() for q in values for m in q['members']})
    manifest={'trial':206,'schema':'相対変化206_v1','financial_labels_used':False,'strategy_selected':False,
        '主条件':{'delay':1,'追加停滞上限秒':60},'delays':DELAYS,'horizons':HORIZONS,'offsets':OFFSETS,'reason_codes':REASONS,'member_order':members,
        'q0_counts':prior['q0_counts'],'q0_projection':ref(QPLAN),'q0_original_sources':q0_sources,
        'input_manifests':[ref(p) for p in (nk,tx,add)],'inputs':inputs,'legacy_source':ref(LEGACY),'Source':source,
        'scenes':[{'session':s,'start':bounds(s)[0],'end':bounds(s)[1],
                   'sources':{symbol:by[(symbol,s)] for symbol in ('NK225','TOPIX')},
                   'q0':{symbol:pure[(symbol,s)] for symbol in ('NK225','TOPIX')}} for s in scenes],
        'dependencies':{'Python':sys.version,'numpy':np.__version__},
        '時計の限界':'受信模型ではなく価格時計の公表遅延感度。相手の物理行は自己との前後判定に使わない。'}
    save(PLAN,manifest)
    print(json.dumps({'抽出前固定':True,'場':len(scenes),'8列入力':len(inputs),'8列byte':sum(r['bytes'] for r in inputs),'q0':prior['q0_counts']},ensure_ascii=False),flush=True)
    return manifest


# ----------------------------------------
def diagnose(arrays: dict,band: np.ndarray) -> dict:
    """
    機能: 金融を使わず端点可用性と遅延による純差分符号の変化を数える。
    引数: arrays(dict)は純特徴、band(np.ndarray[int8])はDAY/PRE/POST。
    返り値: dictは帯・遅延・窓別の件数。主遅延を再選択しない。
    """
    result={}
    for part,index in (('DAY',0),('PRE',1),('POST',2),('ALL',None)):
        mask=np.ones(len(band),bool) if index is None else band==index
        if not np.any(mask):continue
        for d,delay in enumerate(DELAYS):
            for h,width in enumerate(HORIZONS):
                known=arrays['difference_known'][:,d,h]&mask
                joint=known&arrays['difference_known'][:,0,h]
                current=arrays['return_difference'][:,d,h];base=arrays['return_difference'][:,0,h]
                row={'q0':int(mask.sum()),'自己端点既知':int(np.sum(arrays['return_known'][:,d,h,0]&mask)),
                    '相手端点既知':int(np.sum(arrays['return_known'][:,d,h,1]&mask)),'両端点既知':int(known.sum()),
                    '両指数内部gapなし':int(np.sum(arrays['difference_quality_known'][:,d,h]&mask)),
                    '差正':int(np.sum(known&(current>0))),'差零':int(np.sum(known&(current==0))),'差負':int(np.sum(known&(current<0))),
                    'd1との共通既知':int(joint.sum()),'d1から差符号変化':int(np.sum(joint&(np.sign(current)!=np.sign(base)))),
                    'd1から差値変化':int(np.sum(joint&(current!=base)))}
                result[f'{part}/d{delay}/h{width}']=row
    return result


# ----------------------------------------
def run() -> None:
    """
    機能: 固定された83場を生成し、旧初回価格系列と入力不変を確認する。
    引数: なし。
    返り値: None。未知q0と未使用帯を削除しない。
    """
    plan=read(PLAN)
    for r in plan['Source']+[plan['q0_projection'],plan['legacy_source']]:assert ref(ROOT/r['path'])==r
    old=legacy_module();results=[];totals=defaultdict(Counter)
    for scene in plan['scenes']:
        data={}
        for symbol,r in scene['sources'].items():
            p=ROOT/r['path'];assert ref(p)==r
            with np.load(p,allow_pickle=False) as z:data[symbol]={k:z[k].copy() for k in FIELDS}
            legacy=old.timeline(p,scene['start'],scene['end']);new=timeline(data[symbol],scene['start'],scene['end'])
            np.testing.assert_array_equal(new.times,legacy[0]);np.testing.assert_array_equal(new.prices,legacy[1])
        for symbol in ('NK225','TOPIX'):
            other='TOPIX' if symbol=='NK225' else 'NK225'
            arrays,quality=features(data[symbol],data[other],scene['q0'][symbol],scene['start'],scene['end'])
            day=scene['session'].endswith('_Day')
            boundary=datetime.fromisoformat(scene['session'][:10]).replace(hour=9,minute=30,tzinfo=ZoneInfo('America/New_York')).timestamp()
            band=np.zeros(len(arrays['q0_line']),dtype=np.int8) if day else np.where(arrays['q0_time']<boundary,1,2).astype(np.int8)
            arrays['q0_band']=band
            arrays['q0_member_mask']=np.asarray([sum(1<<plan['member_order'].index(m) for m in q['members']) for q in scene['q0'][symbol]],dtype=np.uint16)
            path=DEST/symbol/(scene['session']+'.npz');path.parent.mkdir(parents=True,exist_ok=True)
            if path.exists():
                with np.load(path,allow_pickle=False) as z:
                    assert set(z.files)==set(arrays)
                    for name,array in arrays.items():np.testing.assert_array_equal(z[name],array)
            else:np.savez_compressed(path,**arrays)
            diagnostic=diagnose(arrays,band)
            for key,row in diagnostic.items():totals[symbol+'/'+key].update(row)
            output={'symbol':symbol,'session':scene['session'],'q0':len(band),'file':ref(path),'旧初回Last系列同体':True,
                    '自己原行価格時計Last照合':True,'対象時間外q0':int(np.sum(~arrays['q0_target'])),'自己時計後退q0':int(arrays['q0_backward'].sum()),
                    'endpoint_reason':{REASONS[int(k)]:int(v) for k,v in zip(*np.unique(arrays['endpoint_reason'],return_counts=True))},
                    'quality':quality,'診断':diagnostic}
            results.append(output)
        for r in scene['sources'].values():assert ref(ROOT/r['path'])==r
        print(scene['session'],flush=True)
    for r in plan['Source']+[plan['q0_projection'],plan['legacy_source']]:assert ref(ROOT/r['path'])==r
    counts={s:sum(r['q0'] for r in results if r['symbol']==s) for s in ('NK225','TOPIX')};assert counts==plan['q0_counts']
    done={'trial':206,'schema':plan['schema'],'financial_labels_used':False,'strategy_selected':False,'成功':True,'全83既使用':True,
        '抽出前固定':ref(PLAN),'q0_counts':counts,'files':results,'遅延感度と可用性':dict(totals),
        '全166入力の前後SHA同体':True,'原板再抽出なし':True,'旧初回Last系列全166同体':True,
        '保存byte':sum(r['file']['bytes'] for r in results)}
    save(DEST/'完了.json',done)
    print(json.dumps({'完了':True,'q0':counts,'保存byte':done['保存byte']},ensure_ascii=False),flush=True)


# ----------------------------------------
if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--prepare',action='store_true');parser.add_argument('--run',action='store_true');args=parser.parse_args()
    if args.prepare:prepare()
    if args.run:run()
