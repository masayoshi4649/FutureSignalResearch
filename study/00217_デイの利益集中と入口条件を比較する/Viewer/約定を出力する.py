"""デイの三つの比較場面を、既存の約定変換器と照合器で表示する。"""
from argparse import ArgumentParser
from csv import DictReader
from hashlib import file_digest
from pathlib import Path
import importlib.util
import json
import math

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
TARGETS = {
    '日経199_02':('日経','NK00','NK225','216_日経199_02'),
    '日経NK10':('日経','NK10','NK225','217_日経NK10'),
    '日経通知でTOPIX':('通知','通知00','TOPIX','216_日経通知でTOPIX'),
    '日経通知03でTOPIX':('通知','通知03','TOPIX','217_日経通知03でTOPIX'),
}
SCENES = {
    '2026-10-20_Day':('日経199_02','日経NK10'),
    '2026-11-19_Day':('日経199_02','日経NK10'),
    '2026-11-16_Day':('日経通知でTOPIX','日経通知03でTOPIX'),
}


def load(number: str) -> object:
    """
    機能：既存のViewer約定変換器または数値API照合器を読み込む。
    引数：number（str）は5桁の試行番号。
    返り値：objectは既存の実装を提供するモジュール。
    """
    source = next((ROOT/'study').glob(number+'_*/Viewer/約定を出力する.py'))
    spec = importlib.util.spec_from_file_location('約定'+number,source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def check_daily(rows: list, directory: str, scene: str) -> tuple:
    """
    機能：候補別の正式日次CSVと元帳の建玉回数・利益・損失・収支・未知なしを照合する。
    引数：rows（list）は建玉、directory・scene（str）はCSVの候補フォルダ・場。
    返り値：tupleは既知利益・損失・純益。
    """
    csv = next((ROOT/'outputs').glob('00'+directory[:3]+'_*/'+directory+'/デイ.csv'))
    with csv.open(encoding='utf-8-sig',newline='') as stream:
        record, = [r for r in DictReader(stream) if r['セッション']==scene]
    nets = [r['net'] for r in rows]
    assert len(rows)==int(record['建玉回数']) and int(record['未知件数'])==0 and None not in nets
    amounts = (round(sum(x for x in nets if x>0),1),round(-sum(x for x in nets if x<0),1),round(sum(nets),1))
    assert all(math.isclose(x,float(record[k]),abs_tol=1e-7)
               for x,k in zip(amounts,('既知利益円','既知損失円','確定収支円'),strict=True))
    return amounts


def main() -> None:
    """
    機能：選んだ3場面を口座ごとの6表示に変換し、指定時には配布版の全約定片を照合する。
    引数：--api（str、省略可）はローカルSessionTradeViewer数値APIの基底URL。
    返り値：None。共用原板への一覧と6表示の約定片・照合記録を保存する。
    """
    parser = ArgumentParser()
    parser.add_argument('--api')
    args = parser.parse_args()
    converter, audit = load('00215'),load('00216')
    books = {origin:json.loads((ROOT/'work'/('217'+origin)/'比較元帳.json').read_bytes()) for origin in ('日経','通知')}
    catalog = {'schema_version':1,'path_base':'catalog','base_dir':str(HERE),'resources':[]}
    catalog_path = HERE/'一覧.resources.json'
    prepared, results = {}, {}
    for scene,methods in SCENES.items():
        for method in methods:
            origin,rule,symbol,directory = TARGETS[method]
            group = [r for r in books[origin][rule] if r['scene']==scene]
            gain,loss,net = check_daily(group,directory,scene)
            point,one_way,product,buy,sell = (100,538.5,'NK225mini',0,1) if symbol=='NK225' else (1000,291.8,'miniTOPIX',1,-1)
            converter.SCENE = scene
            fragments = converter.fills(group,method,point,one_way,buy,sell)
            key = scene[:10]+'_'+method
            target = HERE/(key+'.trades.jsonl')
            target.write_text(''.join(json.dumps(v,ensure_ascii=False)+'\n' for v in fragments),encoding='utf8')
            market = ROOT.parent/'JP_OSE_Data/future'/symbol/scene
            raw = next(p for p in (market/'book.jsonl.gz',market/'book.jsonl') if p.is_file())
            catalog['resources'].append({'id':key,'title':scene[5:10]+' デイ '+method,'symbol':symbol,'session':scene,
                'method_id':method,'product':product,'point_value':point,'pnl_format':'trades','pnl_basis':'net',
                'market_path':str(raw),'pnl_path':target.name})
            results[key] = {'手法':rule,'建玉回数':len(group),'利益円':gain,'損失円':loss,'純益円':net,'片道費用円':one_way}
            prepared[key] = fragments,group
    catalog_path.write_text(json.dumps(catalog,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    # ----------------------------------------
    if args.api:
        for key,(fragments,trades) in prepared.items():
            results[key]['配布版'] = audit.verify(args.api,catalog_path,key,fragments,trades)
        exe = ROOT.parent/'SessionTradeViewer/dist/windows-amd64/SessionTradeViewer/session-trade-viewer.exe'
        with exe.open('rb') as stream:
            sha = file_digest(stream,'sha256').hexdigest()
        record = {'配布版SHA256':sha,'表示':results}
        (HERE/'Viewer照合.json').write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    print(json.dumps(results,ensure_ascii=False))


if __name__=='__main__':
    main()
