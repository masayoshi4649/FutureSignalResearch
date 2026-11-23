"""正式116完了後、Rootが2520一覧と11/06日夜72資源だけをHTTP照合する。準備段階では実行しない。"""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from decimal import Decimal
import hashlib
import json
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request,urlopen

SESSIONS={'2026-11-06_Day','2026-11-06_Night'}


def sha(path:Path)->str:
    """
    機能: 正式metadata・選択済実約定・検査コードのSHA256を確認する。
    引数: path(Path)。返り値: str。Raw/価格CSV/Nativeを渡さない。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path:Path)->dict:
    """
    機能: 正式metadataの数値を十進数で読む。
    引数: path(Path)。返り値: dict。自然Nativeは読まない。
    """
    return json.loads(path.read_text(encoding='utf-8-sig'),parse_float=Decimal)


def request(base:str,route:str,payload:dict|None=None)->tuple[dict,str]:
    """
    機能: Rootが起動した116専用Viewerへ許可された限定APIを要求する。
    引数: base/route(str)、payload(dict|None)。返り値: tuple[dict,str]は応答と全本文SHA。
    """
    assert route in ('/api/info','/api/catalogs/load') or route.startswith('/api/data?')
    body=None if payload is None else json.dumps(payload,ensure_ascii=False).encode('utf-8')
    with urlopen(Request(base+route,data=body,headers={'Content-Type':'application/json'}),timeout=60) as response:
        raw=response.read();digest=hashlib.sha256(raw).hexdigest()
        assert response.headers.get('x-chart-data-sha256',digest)==digest
        return json.loads(raw,parse_float=Decimal),digest


def check(trial:Path,base:str,item:tuple)->dict:
    """
    機能: 11/06の一資源について実約定全行・費用後現金増減・最終flatをHTTPと照合する。
    引数: trial(Path)、base(str)、item(tuple[catalogID,resource,expected])。返り値: dictは限定取得証拠。
    """
    catalog_id,resource,expected=item
    assert resource['session'] in SESSIONS
    path=(trial/'成果物'/resource['pnl_path']).resolve()
    assert path.parent==trial/'成果物' and path.name==f"{resource['id']}.trades.jsonl"
    original=path.read_bytes();lines=[json.loads(line,parse_float=Decimal) for line in original.decode('utf-8').splitlines() if line.strip()]
    query=urlencode({'catalog':catalog_id,'resource':resource['id'],'width':1,'interval':'raw','price':'last'})
    value,digest=request(base,'/api/data?'+query)
    assert len(value['events'])==len(lines)
    held={};net=Decimal(0)
    for index,(row,event) in enumerate(zip(lines,value['events']),1):
        for name in ('type','price','qty','position_id','method_id'):assert row[name]==event[name],(resource['id'],name)
        assert event['sequence']==index
        assert event['timestamp_ms']==round(datetime.fromisoformat(row['timestamp']).timestamp()*1000)
        cost=Decimal(row.get('fee_yen',0))+Decimal(row.get('slippage_yen',0))
        kind,pid,quantity=row['type'],row['position_id'],row['qty']
        if kind in ('LongN','ShortN'):
            assert pid not in held
            held[pid]={'side':1 if kind=='LongN' else -1,'price':row['price'],'quantity':quantity};delta=-cost
        else:
            assert kind in ('LongR','ShortR') and pid in held
            position=held[pid];assert position['side']==(1 if kind=='LongR' else -1) and 0<quantity<=position['quantity']
            delta=(row['price']-position['price'])*position['side']*quantity*100-cost;position['quantity']-=quantity
            if position['quantity']==0:del held[pid]
        assert event['realized_delta_yen']==delta,resource['id']
        net+=delta
    assert not held and net==expected
    summary=value['summary']
    assert summary['long_qty']==summary['short_qty']==summary['unrealized_pnl_yen']==0
    assert summary['realized_pnl_yen']==expected
    assert path.read_bytes()==original
    return {'id':resource['id'],'純額円':float(net),'全実約定行':len(lines),'応答SHA256':digest}


def main()->None:
    """
    機能: 正式完了後にRoot許可を確認し、2520一覧ID/11月06日夜72GETを検査する。
    引数: CLIのtrial/result-sha/catalog-sha/base/root-authorized。返り値: None。新証拠を一度だけ保存する。
    """
    parser=argparse.ArgumentParser(description='正式116専用Viewerの限定HTTP照合。準備時は起動/実行しない。')
    parser.add_argument('--trial',type=Path,required=True);parser.add_argument('--result-sha',required=True);parser.add_argument('--catalog-sha',required=True)
    parser.add_argument('--base',default='http://127.0.0.1:8100');parser.add_argument('--root-authorized',action='store_true')
    args=parser.parse_args();assert args.root_authorized,'Root正式完了後の明示実行が必要'
    assert args.base=='http://127.0.0.1:8100','他Viewerへ配送しない。別portに変更するならRootが新定義を確認する'
    trial=args.trial.resolve();root=trial.parents[1]
    assert trial==root/'study/00116_突破根拠の維持から失効への遷移で離脱する'
    output=trial/'検査/Viewer確認.json';assert not output.exists()
    catalog=trial/'成果物/閲覧用_市場絶対参照.resources.json';result=trial/'成果物/結果.json'
    assert sha(result)==args.result_sha and sha(catalog)==args.catalog_sha,'正式保存後に認証した正本SHAだけを渡す'
    resources,data=load(catalog)['resources'],load(result)
    assert len(resources)==2520 and len({r['id'] for r in resources})==2520
    assert len(data['場別'])==2520
    assert all(r['session']<='2026-11-06_Night' and r['id']==f"116_{r['method_id']}_{r['session']}" for r in resources)
    assert all(r['pnl_format']=='trades' and r['pnl_basis']=='net' and r['product']=='NK225mini' and r['point_value']==100 for r in resources)
    selected=[r for r in resources if r['session'] in SESSIONS]
    assert len(selected)==72 and all(sum(r['session']==s for r in selected)==36 for s in SESSIONS)
    before={str(p):sha(p) for p in (catalog,result,Path(__file__).resolve())}
    for resource in selected:
        path=(trial/'成果物'/resource['pnl_path']).resolve();assert path.parent==trial/'成果物' and path.name==f"{resource['id']}.trades.jsonl";before[str(path)]=sha(path)
    expected={(r['key'],r['session']):r['net_yen'] for r in data['場別']};assert len(expected)==2520
    info,info_sha=request(args.base,'/api/info')
    assert info['listen']=='127.0.0.1:8100' and Path(info['resource_root']).resolve()==trial
    assert Path(info['data_root']).resolve()==(root.parent/'JP_OSE_Data/future').resolve()
    loaded,catalog_sha=request(args.base,'/api/catalogs/load',{'path':'成果物/閲覧用_市場絶対参照.resources.json'})
    assert {r['id'] for r in loaded['resources']}=={r['id'] for r in resources}
    source_meta={r['id']:(r['session'],r['method_id'],r['product'],r['point_value'],r['pnl_format'],r['pnl_basis']) for r in resources}
    assert {r['id']:(r['session'],r['method_id'],r['product'],r['point_value'],r['pnl_format'],r['pnl_basis']) for r in loaded['resources']}==source_meta
    # ----------------------------------------
    # 72資源だけGETする。全2520の価格読取や11月09のアクセスはしない。
    with ThreadPoolExecutor(max_workers=4) as pool:
        details=list(pool.map(lambda item:check(trial,args.base,item),[(loaded['catalog_id'],r,expected[(r['method_id'],r['session'])]) for r in selected]))
    after={name:sha(Path(name)) for name in before};assert before==after
    proof={'成功':True,'試行':116,'一覧':2520,'実GET':72,'範囲':'全一覧ID/主要metadataと11月06日夜72資源の全実約定・費用後純額・残0。全2520GET/描画/目視確認ではない','server':args.base,'info応答SHA256':info_sha,'一覧応答SHA256':catalog_sha,'details':details,'前後不変':True,'前':before,'後':after,'他Viewer操作':0,'クライアントRaw_CSV_Native読取':0,'サーバ価格読取対象':'2026-11-06_Day/Nightのみ（data API）','11月09アクセス':0,'金融再実行':False}
    with output.open('x',encoding='utf-8') as stream:stream.write(json.dumps(proof,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'成功':True,'一覧':2520,'実GET':72,'証拠':str(output),'証拠SHA256':sha(output)},ensure_ascii=False))


if __name__=='__main__':main()
