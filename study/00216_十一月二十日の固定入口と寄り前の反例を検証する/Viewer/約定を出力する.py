"""11月20日の手法・場別の取引をViewer形式に変換し、配布版APIと照合する。"""
from argparse import ArgumentParser
from datetime import datetime
from pathlib import Path
from urllib.request import urlopen
from urllib.parse import urlencode
import gzip
import importlib.util
import json
import math

HERE = Path(__file__).resolve().parent
STUDY = HERE.parent
ROOT = STUDY.parents[1]
DAY, NIGHT = '2026-11-20_Day', '2026-11-20_Night'


# ----------------------------------------
def read(path: Path) -> dict:
    """
    機能：固定金融正本をJSONで読み取る。
    引数：path（Path）はUTF-8 JSON又はgzip圧縮JSON。
    返り値：dictは元の金融記録。
    """
    raw = path.read_bytes()
    return json.loads(gzip.decompress(raw) if path.suffix=='.gz' else raw)


# ----------------------------------------
def cases() -> list:
    """
    機能：候補・場単位で取引と帳簿ごとの買売符号を取り出す。
    引数：なし。11月20日デイと同日開始ナイトの固定台帳を使用する。
    返り値：listは手法名・商品・場・元明細・買符号・売符号。
    """
    nk_day = read(STUDY/'日経/固定結果.json')['結果']['建玉']
    nk_night = read(STUDY/'日経/ナイト固定結果.json')['結果'][NIGHT]['建玉']
    tp = read(STUDY/'TOPIX/固定照合.json')['追加']['取得']
    sent = read(STUDY/'通知と同期の結果.json')['通知対照'][DAY]['取得']
    entries = [('日経199_02','NK225',DAY,nk_day,0,1),('TOPIX移植03','TOPIX',DAY,tp,0,1),
               ('日経通知でTOPIX','TOPIX',DAY,sent,1,-1),('日経199_02','NK225',NIGHT,nk_night,0,1)]
    native = read(STUDY/'TOPIX専用/追加七場.json.gz')['ledger']
    for scene in (DAY,NIGHT):
        group = [{k:v[i] for k,v in native.items()} for i,s in enumerate(native['scene']) if s==scene]
        entries.append(('TOPIX専用212主6','TOPIX',scene,group,1,-1))
    return entries


# ----------------------------------------
def verify(api: str, catalog_path: Path, key: str, fragments: list, trades: list) -> dict:
    """
    機能：配布版の数値APIの全約定片・最終損益・残数・含みを元台帳と照合する。
    引数：api（str）はローカルURL、catalog_path（Path）は一覧、key（str）は表示ID、
          fragments・trades（list）は表示約定と元台帳。
    返り値：dictは数値・約定片数・照合結果。
    """
    params = {'catalog_path':str(catalog_path),'resource':key,'interval':'5','price':'last'}
    with urlopen(api.rstrip('/')+'/api/data?'+urlencode(params),timeout=120) as stream:
        data = json.load(stream)
    summary = data['summary']
    assert math.isclose(summary['realized_pnl_yen'], sum(t['net'] for t in trades), abs_tol=1e-6)
    assert summary['long_qty'] == summary['short_qty'] == summary['unrealized_pnl_yen'] == 0
    for i, (item, event) in enumerate(zip(fragments,data['events'],strict=True)):
        assert math.isclose(datetime.fromisoformat(item['timestamp']).timestamp()*1000,
                            event['timestamp_ms'],rel_tol=0,abs_tol=0.1)
        for field in ('type','price','qty','position_id','method_id'):
            assert event[field]==item[field], (key,field)
        expected = -item['fee_yen'] if i % 2 == 0 else trades[i//2]['net'] + item['fee_yen']
        assert math.isclose(event['realized_delta_yen'],expected,abs_tol=1e-6), (key,i)
    return {'約定片':len(fragments),'確定損益円':round(summary['realized_pnl_yen'],2),
            '終了買建玉':summary['long_qty'],'終了売建玉':summary['short_qty'],'終了含み円':summary['unrealized_pnl_yen']}


# ----------------------------------------
def main() -> None:
    """
    機能：原板への参照付き一覧を作り、指定時はViewerへ読み込んで検算する。
    引数：--api（str、省略可）は127.0.0.1のSessionTradeViewerのHTTP URL。
    返り値：None。各場の約定片・一覧とAPI照合結果を記録する。
    """
    parser = ArgumentParser()
    parser.add_argument('--api')
    args = parser.parse_args()
    code = next((ROOT/'study').glob('00215_*/Viewer/約定を出力する.py'))
    spec = importlib.util.spec_from_file_location('前回のViewer変換',code)
    converter = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(converter)
    catalog_path = HERE/'一覧.resources.json'
    catalog = {'schema_version':1,'path_base':'catalog','base_dir':str(HERE),'resources':[]}
    prepared, checked = {}, {}
    for method,symbol,scene,trades,long_value,short_value in cases():
        key = ('デイ' if scene==DAY else 'ナイト') + '_' + method
        unknown = sum(not t.get('known',True) or t['net'] is None or t['exit_time'] is None for t in trades)
        if unknown:
            checked[key] = {'決済未知':unknown,'表示':'確定残数を表示できないため、一覧には掲載しない'}
            continue
        product,point,fee = ('NK225mini',100,538.5) if symbol=='NK225' else ('miniTOPIX',1000,291.8)
        converter.SCENE = scene
        fragments = converter.fills(trades,method,point,fee,long_value,short_value)
        pnl = HERE/(key+'.trades.jsonl')
        pnl.write_text(''.join(json.dumps(item,ensure_ascii=False)+'\n' for item in fragments),encoding='utf8')
        folder = ROOT.parent/'JP_OSE_Data/future'/symbol/scene
        raw = next(p for p in (folder/'book.jsonl.gz',folder/'book.jsonl') if p.is_file())
        catalog['resources'].append({'id':key,'title':key,'symbol':symbol,'session':scene,'method_id':method,
            'product':product,'point_value':point,'pnl_format':'trades','pnl_basis':'net',
            'market_path':str(raw),'pnl_path':pnl.name})
        prepared[key] = fragments,trades
    catalog_path.write_text(json.dumps(catalog,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    # ----------------------------------------
    if args.api:
        for key,(fragments,trades) in prepared.items():
            checked[key] = verify(args.api,catalog_path,key,fragments,trades)
        (HERE/'Viewer照合.json').write_text(json.dumps(checked,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
        print(json.dumps(checked,ensure_ascii=False))


if __name__=='__main__':
    main()
