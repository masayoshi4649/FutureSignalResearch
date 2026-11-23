"""固定口座の約定をViewer形式に変換し、指定時はローカルのViewerと照合する。"""
from argparse import ArgumentParser
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen
import json
import math


HERE = Path(__file__).resolve().parent
STUDY = HERE.parent
ROOT = STUDY.parents[1]
MARKET = ROOT.parent / 'JP_OSE_Data/future'
SCENE = '2026-11-19_Day'
JST = timezone(timedelta(hours=9))


# ----------------------------------------
def read(path: Path) -> dict:
    """
    機能：固定結果のJSONを展開する。
    引数：path（Path）は正本。
    返り値：dictは日別の固定結果。
    """
    return json.loads(path.read_text(encoding='utf-8'))


# ----------------------------------------
def fills(rows: list, method: str, point: int, fee: float, long_value: int, short_value: int) -> list:
    """
    機能：固定建玉の新規と返済を、同一の建玉IDを持つ約定片に変換する。
    引数：rows（list）は全建玉、method（str）は手法名、point（int）は円乗数、
          fee（float）は片道の費用円、long_value・short_value（int）は元台帳の買・売符号。
    返り値：listは時刻順の約定片。
    """
    result = []
    for number, trade in enumerate(rows, 1):
        assert trade['scene'] == SCENE and trade['side'] in (long_value, short_value)
        direction = 1 if trade['side'] == long_value else -1
        delta = direction * (trade['exit_price'] - trade['entry_price']) * point
        assert math.isclose(delta - 2*fee, trade['net'], abs_tol=1e-7)
        position = f'{method}-{number:02d}'
        for key, action in [('entry', 'N'), ('exit', 'R')]:
            side = 'Long' if direction == 1 else 'Short'
            clock = datetime.fromtimestamp(trade[key+'_time'], JST).isoformat()
            result.append({'id': position+action, 'timestamp': clock, 'type': side+action,
                           'position_id': position, 'qty': 1, 'price': trade[key+'_price'],
                           'fee_yen': fee, 'source_line': trade[key+'_line'], 'method_id': method})
    assert result == sorted(result, key=lambda r: (r['timestamp'], r['source_line']))
    return result


# ----------------------------------------
def main() -> None:
    """
    機能：3口座の一覧と約定片を保存し、任意のViewer APIで最終残と損益を照合する。
    引数：CLIの --api（str）は省略可能なローカルViewerのURL。
    返り値：None。API照合時は確認した件数・損益・建玉もJSONへ記録する。
    """
    parser = ArgumentParser()
    parser.add_argument('--api')
    args = parser.parse_args()
    nk = read(STUDY/'日経/固定結果.json')['結果']['建玉']
    tp = read(STUDY/'TOPIX/固定照合.json')['追加']['取得']
    sent = read(STUDY/'通知と同期の結果.json')['通知対照'][SCENE]['取得']
    cases = [('日経199_02', 'NK225', nk, 0, 1), ('TOPIX移植03', 'TOPIX', tp, 0, 1),
             ('日経通知でTOPIX', 'TOPIX', sent, 1, -1)]
    catalog = {'schema_version': 1, 'path_base': 'catalog', 'base_dir': str(HERE), 'resources': []}
    path = HERE / '一覧.resources.json'
    for method, symbol, trades, long_value, short_value in cases:
        product, point, fee = ('NK225mini', 100, 538.5) if symbol == 'NK225' else ('miniTOPIX', 1000, 291.8)
        rows = fills(trades, method, point, fee, long_value, short_value)
        pnl = HERE / (method+'.trades.jsonl')
        pnl.write_text(''.join(json.dumps(r, ensure_ascii=False)+'\n' for r in rows), encoding='utf-8')
        raw = MARKET / symbol / SCENE / 'book.jsonl'
        if not raw.is_file():
            raw = raw.with_suffix('.jsonl.gz')
        assert raw.is_file()
        catalog['resources'].append({'id': method, 'title': method+'　11月19日デイ', 'symbol': symbol,
                                     'session': SCENE, 'product': product, 'method_id': method, 'point_value': point,
                                     'pnl_format': 'trades', 'pnl_basis': 'net', 'market_path': str(raw),
                                     'pnl_path': pnl.name})
    path.write_text(json.dumps(catalog, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')

    # ----------------------------------------
    if args.api:
        checked = {}
        for method, _, trades, _, _ in cases:
            params = {'catalog_path': str(path), 'resource': method, 'interval': '5', 'price': 'last'}
            with urlopen(args.api.rstrip('/')+'/api/data?'+urlencode(params), timeout=120) as response:
                data = json.load(response)
            summary = data['summary']
            assert math.isclose(summary['realized_pnl_yen'], sum(t['net'] for t in trades), abs_tol=1e-7)
            assert summary['long_qty'] == summary['short_qty'] == summary['unrealized_pnl_yen'] == 0
            assert len(data['events']) == 2 * len(trades)
            checked[method] = {'約定片': len(data['events']), '確定損益円': round(summary['realized_pnl_yen'], 2),
                               '終了買建玉': summary['long_qty'], '終了売建玉': summary['short_qty'],
                               '終了含み円': summary['unrealized_pnl_yen']}
        (HERE/'Viewer照合.json').write_text(json.dumps(checked, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
        print(json.dumps(checked, ensure_ascii=False))


if __name__ == '__main__':
    main()
