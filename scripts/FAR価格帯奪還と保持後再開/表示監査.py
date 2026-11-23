"""固定91の数値照合部品を再用する92のViewer読取。起動/停止/設定変更機能は持たない。"""

import argparse
from concurrent.futures import ThreadPoolExecutor,as_completed
import hashlib
import importlib.util
import json
from pathlib import Path
from urllib.parse import urlencode

ROOT=Path(__file__).resolve().parents[2]
FIXED=ROOT/'scripts/FAR利確完了後の新event再参加/表示監査.py'
FIXED_SHA='de6bdfa775c388a68ec990e6e19632c07282583bd994588b7403d24bdff3fb2c'
if hashlib.sha256(FIXED.read_bytes()).hexdigest()!=FIXED_SHA:raise ValueError('停止91表示照合の変更')
SPEC=importlib.util.spec_from_file_location('viewer91_parts_for92',FIXED);OLD=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(OLD)
KEYS={f'H{p}G1_D{d}' for d in (0,1) for p in (0,1)}


def local_inputs(catalog_path: Path,result_path: Path) -> dict:
    """
    機能: APIに接続せず92の264資源/場/純額とローカル約定を準備する。
    引数: catalog_path/result_path(Path)は明示の一覧と正本。
    返り値: dictは解決済み入力。process/Viewerへ作用しない。
    """
    catalog=json.loads(catalog_path.read_text(encoding='utf-8'));result=json.loads(result_path.read_text(encoding='utf-8'));resources=catalog['resources']
    expected={f"92_{r['key']}_{r['session']}":r for r in result['場別']}
    if result['試行']!=92 or result['場数']!=66 or len(resources)!=len(expected) or len(expected)!=264 or len(result['場別'])!=264 or set(expected)!={r['id'] for r in resources}:raise ValueError('92の264資源集合差')
    if {r['key'] for r in result['場別']}!=KEYS:raise ValueError('外4会計集合差')
    sessions={r['session'] for r in result['場別']}
    if len(sessions)!=66 or {(r['session'],r['key']) for r in result['場別']}!={(s,k) for s in sessions for k in KEYS}:raise ValueError('66場×4会計の対象差')
    paths=[catalog_path,result_path];trades={}
    for r in resources:
        if (r['product'],r['point_value'],r['pnl_basis'])!=('NK225micro',10,'net'):raise ValueError('Viewerの商品/倍率/費用基準差')
        row=expected[r['id']]
        if r['symbol']!='NK225' or r['session']!=row['session'] or r['method_id']!=row['key'].split('_D')[0] or r['pnl_format']!='trades':raise ValueError('Viewerの外ラベル/場/形式差')
        p=(catalog_path.parent/r['pnl_path']).resolve()
        if not p.is_relative_to(catalog_path.parent):raise ValueError('約定参照が成果物外')
        paths.append(p);trades[r['id']]=[json.loads(l) for l in p.read_text(encoding='utf-8').splitlines() if l.strip()]
    return {'catalog':catalog,'result':result,'resources':resources,'expected':expected,'trades':trades,'入力SHA256':{str(p):OLD.digest(p) for p in paths}}


def main() -> None:
    """
    機能: 明示後に既存8092の264資源を読取照合し証拠を保存する。
    引数: --catalog/--result/--out(Path)、--url(str)、--workers(int)は一覧/結果/先/既存接続/並列数。
    返り値: None。不一致又はAPI未完は非0。Viewerの再起動/停止/仕様変更は行わない。
    """
    p=argparse.ArgumentParser(description='92の既存Viewer数値照合')
    for n in ('catalog','result','out'):p.add_argument('--'+n,type=Path,required=True)
    p.add_argument('--url',default='http://127.0.0.1:8092');p.add_argument('--workers',type=int,default=8);a=p.parse_args()
    if a.out.exists() or not 1<=a.workers<=16 or a.url.rstrip('/') not in ('http://127.0.0.1:8092','http://localhost:8092'):raise ValueError('新規先/並列数/既存8092接続が必要')
    catalog_path=a.catalog.resolve();result_path=a.result.resolve();data=local_inputs(catalog_path,result_path);base=a.url.rstrip('/');info,_,_=OLD.BASE.fetch_json('GET',base+'/api/info');root=Path(info['resource_root']).resolve()
    if not catalog_path.is_relative_to(root):raise ValueError('一覧はViewerのresource_root配下が必要')
    loaded,_,_=OLD.BASE.fetch_json('POST',base+'/api/catalogs/load',{'path':str(catalog_path.relative_to(root))});resolved={r['id']:r for r in loaded['resources']}
    if len(resolved)!=264 or set(resolved)!=set(data['expected']):raise ValueError('Viewer読込の全264集合差')
    tasks=[]
    for r in data['resources']:
        target={**r,'pnl_path':str((catalog_path.parent/r['pnl_path']).resolve()),'market_path':str((Path(info['data_root'])/r['market_path']).resolve())}
        if resolved[r['id']]!=target:raise ValueError('Viewer参照解決差')
        query=urlencode({'catalog':loaded['catalog_id'],'resource':r['id'],'width':1,'interval':'raw','price':'last'});tasks.append((base+'/api/data?'+query,target,data['trades'][r['id']],data['expected'][r['id']]['metrics']['net_pnl_yen'],catalog_path))
    rows=[]
    with ThreadPoolExecutor(a.workers) as pool:
        futures=[pool.submit(OLD.check_one,t) for t in tasks]
        for f in as_completed(futures):
            rows.append(f.result())
            if len(rows)%32==0:print(f'表示監査 {len(rows)}/264',flush=True)
    rows.sort(key=lambda r:r['id']);before=data['入力SHA256'];after={n:OLD.digest(Path(n)) for n in before};errors=[r for r in rows if r['APIエラー']];differences=sum(r['不一致数'] for r in rows);success=len(rows)==264 and all(r['完了'] for r in rows) and not errors and differences==0 and before==after
    value={'試行':92,'成功':success,'完了資源':sum(r['完了'] for r in rows),'予定資源':264,'照合項目数':sum(r['照合項目数'] for r in rows),'不一致数':differences,'APIエラー':errors,'入力不変':before==after,'入力SHA256前':before,'入力SHA256後':after,'監査コードSHA256':OLD.digest(Path(__file__)),'固定91照合部品SHA256':FIXED_SHA,'一覧SHA256':OLD.digest(catalog_path),'結果SHA256':OLD.digest(result_path),'資源':rows,'Viewer設定':info,'Viewer再起動':0,'新売買再生':0}
    a.out.parent.mkdir(parents=True,exist_ok=True)
    with a.out.open('x',encoding='utf-8',newline='\n') as stream:json.dump(value,stream,ensure_ascii=False,indent=2,allow_nan=False);stream.write('\n')
    print(json.dumps({k:value[k] for k in ('成功','完了資源','照合項目数','不一致数')},ensure_ascii=False))
    if not success:raise SystemExit(1)


if __name__=='__main__':main()
