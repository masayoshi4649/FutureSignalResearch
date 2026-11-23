"""元連続mini/microの243資源を固定80のViewer部品で照合する。"""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from decimal import Decimal
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import tempfile
from urllib.parse import parse_qs, urlencode, urlparse


ROOT = Path(__file__).resolve().parents[2]
FIXED = ROOT / 'scripts/FAR後期15分移植/表示照合.py'
FIXED_SHA = '2b899795f527bddb9306a89a746d15a24eb73ade8846ff8183d7b9b9e24f9d45'
if hashlib.sha256(FIXED.read_bytes()).hexdigest() != FIXED_SHA:
    raise ValueError('固定80表示部品の指紋差')
SPEC = importlib.util.spec_from_file_location('元連続表示の固定80部品', FIXED)
BASE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BASE)
KEYS = {p + '_' + m for p in ('mini', 'micro') for m in ('D164_15', 'P164_06', 'U165_03')}
TOTALS = ('entry_quantity', 'close_quantity', 'gross_yen', 'fee_yen', 'slippage_yen', 'gross_minus_fee_yen', 'net_yen')
REFERENCE_GROSS = {'micro_D164_15': 1248500, 'micro_P164_06': 392000, 'micro_U165_03': 1181000}


def need(ok: bool, reason: str) -> None:
    """
    機能: 欠落・破損・未測定を正常値へ補わず拒否する。
    引数: ok(bool)、reason(str)は条件と原因。
    返り値: None。不成立はValueError。
    """
    if not ok:
        raise ValueError(reason)


def decimal(value: object) -> Decimal:
    """
    機能: 有限のJSON数値だけを厳密な十進値へ変換する。
    引数: value(object)は保存数値。
    返り値: Decimalは数値。bool/null/非有限はerror。
    """
    need(type(value) in (int, float) and math.isfinite(value), '有限数値が必要')
    return Decimal(str(value))


def number(value: Decimal) -> int | float:
    """
    機能: 半円を丸めず、固定80比較関数へ有限数値を渡す。
    引数: value(Decimal)は期待額。
    返り値: int|floatは整数又は0.5を保つ値。
    """
    return int(value) if value == value.to_integral_value() else float(value)


def local_inputs(catalog_path: Path, result_path: Path, allow_reference_mismatch: bool = False) -> dict:
    """
    機能: 54場162会計から3費用基準243資源と全約定期待値を結ぶ。
    引数: catalog_path/result_path(Path)、allow_reference_mismatch(bool)は表示会計だけの明示許可。
    返り値: dictは供給期待値と指紋。市場原板・APIを読まない。
    """
    catalog_path, result_path = catalog_path.resolve(), result_path.resolve()
    raw_catalog, raw_result = catalog_path.read_bytes(), result_path.read_bytes()
    catalog, result = json.loads(raw_catalog), json.loads(raw_result)
    need(result['試行'] == 93 and result['場数'] == 54 and result['手法場数'] == 81 and result['商品手法会計数'] == 162, '54場/81手法場/162会計差')
    need(type(allow_reference_mismatch) is bool and type(result['元gross一致']) is bool, '参照不一致許可/元一致flagの型差')
    need(all(result[k] is False for k in ('新5分', '新利益追尾', '外テクニカル')), '元連続以外の政策')
    rows = {(r['session'], r['key']): r for r in result['場別']}
    sessions = {s for s, _ in rows}
    need(len(rows) == len(result['場別']) == 162 and len(sessions) == 54, '場別の重複/欠落')
    days = {s[:-4] for s in sessions if s.endswith('_Day')}
    nights = {s[:-6] for s in sessions if s.endswith('_Night')}
    need(len(days) == len(nights) == 27 and days == nights and all('2026-09-21' <= d <= '2026-10-27' for d in days), '元27開始日/昼夜の対象差')
    wanted = {(s, p + '_' + m) for s in sessions for p in ('mini', 'micro')
              for m in (('D164_15',) if s.endswith('_Day') else ('P164_06', 'U165_03'))}
    need(set(rows) == wanted and set(result['集計']) == KEYS, '商品/手法の全集合差')
    sums = {k: {n: Decimal(0) for n in TOTALS} for k in KEYS}
    expected = {}
    for (session, key), row in rows.items():
        totals = row['totals']
        qty = totals['entry_quantity']
        need(type(qty) is int and qty >= 0 and type(totals['close_quantity']) is int and totals['close_quantity'] == qty, '新規/返済実枚数差')
        need(type(row['fills']) is int and row['fills'] >= 0 and type(row['holds']) is int and row['holds'] >= 0, '約定/玉数の型差')
        point, fee = (100, Decimal('38.5')) if key.startswith('mini_') else (10, Decimal(11))
        gross = decimal(totals['gross_yen'])
        need(decimal(totals['fee_yen']) == 2 * fee * qty and decimal(totals['slippage_yen']) == 2 * 5 * point * qty, '指定手数料/仮定滑り差')
        need(decimal(totals['gross_minus_fee_yen']) == gross - decimal(totals['fee_yen']) and decimal(totals['net_yen']) == gross - decimal(totals['fee_yen']) - decimal(totals['slippage_yen']), '場別3金額列差')
        for name in TOTALS:
            sums[key][name] += decimal(totals[name])
        for basis in (('gross',) if key.startswith('micro_') else ('fee', 'slip')):
            method = key + '_' + basis
            identity = '93_' + method + '_' + session
            field = {'gross': 'gross_yen', 'fee': 'gross_minus_fee_yen', 'slip': 'net_yen'}[basis]
            expected[identity] = {'row': row, 'basis': basis, 'method': method, 'point': point, 'fee': fee,
                                  'net': number(decimal(totals[field]))}
    for key in KEYS:
        for name in TOTALS:
            need(decimal(result['集計'][key][name]) == sums[key][name], '場別/手法集計差:' + key + ':' + name)
    need(set(result['対照照合']) == {k for k in KEYS if k.startswith('micro_')}, '元gross対照の全集合差')
    for key, comparison in result['対照照合'].items():
        original, actual, difference = (decimal(comparison[n]) for n in ('元報告gross', '再現gross', '差'))
        need(original == REFERENCE_GROSS[key] and actual == sums[key]['gross_yen'] and difference == actual-original, '元gross固定期待/再現/差の算術不整合')
    matched = all(decimal(c['差']) == 0 for c in result['対照照合'].values())
    need(result['元gross一致'] is matched, '元gross一致flagと3差の不整合')
    need(matched or allow_reference_mismatch, '元gross不一致。表示会計だけを検査する明示許可が必要')
    resources = catalog['resources']
    need(catalog['schema_version'] == 1 and catalog['path_base'] == 'catalog', '一覧形式差')
    need(len(resources) == len({r['id'] for r in resources}) == 243 and {r['id'] for r in resources} == set(expected), '全243資源集合差')
    fingerprints = {str(catalog_path): hashlib.sha256(raw_catalog).hexdigest(), str(result_path): hashlib.sha256(raw_result).hexdigest(),
                    str(Path(__file__).resolve()): BASE.sha(Path(__file__).resolve()), str(FIXED): FIXED_SHA}
    trades, events = {}, {}
    for resource in resources:
        e = expected[resource['id']]
        key, session = e['row']['key'], e['row']['session']
        need((resource['symbol'], resource['session'], resource['product'], resource['point_value'], resource['method_id'], resource['pnl_format'], resource['pnl_basis']) ==
             ('NK225', session, 'NK225mini' if key.startswith('mini_') else 'NK225micro', e['point'], e['method'], 'trades', 'net'), '商品/動的倍率/費用基準ラベル差')
        need(resource['market_path'] == 'NK225/' + session + '/book.jsonl.gz', '原板参照ラベル差')
        path = (catalog_path.parent / resource['pnl_path']).resolve()
        need(path.is_relative_to(catalog_path.parent), '約定参照が出力外')
        body = path.read_bytes()
        fingerprints[str(path)] = hashlib.sha256(body).hexdigest()
        saved = [json.loads(line) for line in body.decode('utf-8').splitlines() if line.strip()]
        seen, owners = set(), set()
        entry_qty = exit_qty = 0
        previous = None
        unit_fee = Decimal(0) if e['basis'] == 'gross' else e['fee'] + (Decimal(5 * e['point']) if e['basis'] == 'slip' else 0)
        for trade in saved:
            need(isinstance(trade['id'], str) and trade['id'] and trade['id'] not in seen, '約定ID欠落/重複')
            seen.add(trade['id'])
            need(trade['method_id'] == e['method'] and trade['type'] in ('LongN', 'LongR', 'ShortN', 'ShortR'), '約定ラベル/種類差')
            need(isinstance(trade['position_id'], str) and trade['position_id'], '実所有ID欠落')
            need(type(trade['qty']) is int and trade['qty'] > 0 and decimal(trade['price']) > 0, '約定価格/実数量差')
            need(type(trade['source_line']) is int and trade['source_line'] > 0, '約定物理行欠落')
            stamp = datetime.fromisoformat(trade['timestamp'])
            need(stamp.utcoffset() is not None and (previous is None or stamp >= previous), '約定の時差欠落/逆順')
            previous = stamp
            need(decimal(trade['fee_yen']) == unit_fee * trade['qty'], '約定片の指定半円費用差')
            if trade['type'].endswith('N'):
                entry_qty += trade['qty']
                owners.add(trade['position_id'])
            else:
                exit_qty += trade['qty']
        need(entry_qty == exit_qty == e['row']['totals']['entry_quantity'] and len(owners) == e['row']['holds'], '約定/正本の実枚数又は実玉数差')
        calculated = BASE.trade_expectations(saved, resource['point_value'])
        need(sum((decimal(t['realized_delta_yen']) for t in calculated), Decimal(0)) == decimal(e['net']), '全約定別算と場別の費用基準額差')
        trades[resource['id']], events[resource['id']] = saved, calculated
    return {'catalog': catalog, 'result': result, 'resources': resources, 'expected': expected,
            'trades': trades, 'events': events, '入力SHA256': fingerprints}


def check_one(task: tuple, transport=None) -> dict:
    """
    機能: 1資源の全約定・半円増減・最終所有0を既存APIへ結ぶ。
    引数: task(tuple)はURL/資源/期待約定/期待純額/一覧、transport(callable|None)は人工用。
    返り値: dictは数値差とAPI未完を分けた小型結果。
    """
    url, resource, events, net, catalog = task
    audit, errors, complete = BASE.Audit(), [], False
    response_hash, final_quantities, actual_net = None, None, None
    try:
        data, raw, headers = (BASE.fetch_json if transport is None else transport)('GET', url)
        BASE.compare_data(data, raw, headers, resource, events, net, audit, catalog)
        response_hash = hashlib.sha256(raw).hexdigest()
        final_quantities = {name: data['summary'].get(name) for name in ('long_qty', 'short_qty')}
        actual_net = data['summary'].get('realized_pnl_yen')
        complete = True
    except BASE.ViewerError as error:
        errors.append({'種類': error.kind, 'URL': error.url, '説明': str(error)[:1000]})
    except (ValueError, AssertionError, KeyError, TypeError) as error:
        errors.append({'種類': '応答schema又は結合', '説明': str(error)[:1000]})
    return {'id': resource['id'], 'product': resource['product'], 'point_value': resource['point_value'],
            '完了': complete, '照合項目数': audit.count, '不一致数': audit.bad, '不一致': audit.examples,
            'APIエラー': errors, '約定片数': len(events), '費用基準': resource['method_id'].rsplit('_', 1)[1],
            'API最終数量': final_quantities, 'API費用基準額円': actual_net, '正本費用基準額円': net,
            '数値本文SHA256': response_hash}


def run(catalog_path: Path, result_path: Path, url: str = 'http://127.0.0.1:8092', workers: int = 8, transport=None, progress: bool = True, allow_reference_mismatch: bool = False) -> dict:
    """
    機能: 明示許可後に全243資源のViewer数値を照合する。
    引数: catalog_path/result_path(Path)、url(str)、workers(int)、transport(callable|None)、progress/allow_reference_mismatch(bool)。
    返り値: dictは完了数/差/通信失敗/入力前後不変。起動・停止・設定変更はしない。
    """
    need(url.rstrip('/') in ('http://127.0.0.1:8092', 'http://localhost:8092') and type(workers) is int and 1 <= workers <= 8, '既存8092と並列1〜8だけを使う')
    catalog_path, result_path = catalog_path.resolve(), result_path.resolve()
    local = local_inputs(catalog_path, result_path, allow_reference_mismatch)
    base, request = url.rstrip('/'), BASE.fetch_json if transport is None else transport
    audit, rows, errors, info = BASE.Audit(), [], [], None
    try:
        info, _, _ = request('GET', base + '/api/info')
        root = Path(info['resource_root']).resolve()
        need(catalog_path.is_relative_to(root), '一覧がViewer resource_root外')
        loaded, _, _ = request('POST', base + '/api/catalogs/load', {'path': str(catalog_path.relative_to(root))})
        resolved = {r['id']: r for r in loaded['resources']}
        need(len(resolved) == len(loaded['resources']) == 243 and set(resolved) == set(local['expected']), 'API243資源の全集合差')
        need(Path(loaded['path']).resolve() == catalog_path, 'API一覧参照差')
        tasks = []
        for resource in local['resources']:
            target = {**resource, 'pnl_path': str((catalog_path.parent / resource['pnl_path']).resolve()),
                      'market_path': str((Path(info['data_root']) / resource['market_path']).resolve())}
            need(resolved[resource['id']] == target, 'API資源メタ情報差:' + resource['id'])
            query = urlencode({'catalog': loaded['catalog_id'], 'resource': resource['id'], 'width': 1, 'interval': 'raw', 'price': 'last'})
            tasks.append((base + '/api/data?' + query, target, local['events'][resource['id']], local['expected'][resource['id']]['net'], catalog_path))
        with ThreadPoolExecutor(workers) as pool:
            pending = [pool.submit(check_one, task, request) for task in tasks]
            for future in as_completed(pending):
                rows.append(future.result())
                if progress and len(rows) % 27 == 0:
                    print(f'表示監査 {len(rows)}/243', flush=True)
    except BASE.ViewerError as error:
        errors.append({'種類': error.kind, 'URL': error.url, '説明': str(error)[:1000]})
    except (ValueError, AssertionError, KeyError, TypeError) as error:
        errors.append({'種類': '一覧応答schema又は結合', '説明': str(error)[:1000]})
    rows.sort(key=lambda r: r['id'])
    before = local['入力SHA256']
    after = {p: BASE.sha(Path(p)) for p in before}
    audit.check('入力とコードの前後不変', after, before)
    errors += [{'id': r['id'], '詳細': r['APIエラー']} for r in rows if r['APIエラー']]
    differences = audit.bad + sum(r['不一致数'] for r in rows)
    complete = len(rows) == 243 and all(r['完了'] for r in rows) and not errors
    return {'試行': 93, '成功': complete and differences == 0 and before == after, '成功の範囲': 'Viewer保存会計一致',
            '参照不一致の明示許可': allow_reference_mismatch, '元gross一致': local['result']['元gross一致'],
            '元gross対照': local['result']['対照照合'], '元gross差円': {k: v['差'] for k, v in local['result']['対照照合'].items()},
            '全面再現を本検査で保証': False,
            '予定資源': 243, '完了資源': sum(r['完了'] for r in rows), '全資源検証完了': complete,
            '照合項目数': audit.count + sum(r['照合項目数'] for r in rows), '不一致数': differences,
            '共通不一致': audit.examples, 'APIエラー': errors, '資源': rows, 'Viewer設定': info,
            '基準内訳': {'micro_gross': 81, 'mini_fee': 81, 'mini_slip': 81}, '入力不変': before == after,
            '入力SHA256前': before, '入力SHA256後': after, '一覧SHA256': before[str(catalog_path)],
            '結果SHA256': before[str(result_path)], '監査コードSHA256': BASE.sha(Path(__file__)), '固定80部品SHA256': FIXED_SHA,
            'Viewer停止/再起動/設定変更': 0, '新売買再生': 0, '原板直接読取': 0, 'API本文複写': 0,
            '限界': '動的倍率の保存全約定と最終所有0/純額のAPI数値結合。原板との価格対応は別監査。画像品質・mini固有執行の証明ではない。'}


def self_test() -> dict:
    """
    機能: 架空54場243資源の非0/半円と破損を通信代替だけで確認する。
    引数: なし。実一覧・市場・Viewer APIへアクセスしない。
    返り値: dictは人工の範囲と成功証拠。
    """
    with tempfile.TemporaryDirectory(prefix='mini表示人工_', dir=ROOT / 'work') as directory:
        temp = Path(directory).resolve()
        need(temp.is_relative_to((ROOT / 'work').resolve()), '人工保存先はwork内だけ')
        resources, rows, by_resource = [], [], {}
        groups = {k: {n: 0 for n in TOTALS} for k in KEYS}
        for day in range(27):
            date = (datetime(2026, 10, 1) + timedelta(days=day)).date().isoformat()
            for kind in ('Day', 'Night'):
                session = date + '_' + kind
                for product in ('micro', 'mini'):
                    point, fee = (10, 11) if product == 'micro' else (100, 38.5)
                    for method in (('D164_15',) if kind == 'Day' else ('P164_06', 'U165_03')):
                        key = product + '_' + method
                        last_move = 10
                        if product == 'micro' and day == 26:
                            last_move += (REFERENCE_GROSS[key] - 27*500)/20
                        gross = point * (30 + 2*last_move)
                        totals = {'entry_quantity': 3, 'close_quantity': 3, 'gross_yen': gross, 'fee_yen': 6*fee,
                                  'slippage_yen': 30*point, 'gross_minus_fee_yen': gross-6*fee, 'net_yen': gross-6*fee-30*point}
                        rows.append({'session': session, 'key': key, 'totals': totals, 'holds': 1, 'fills': 3})
                        for n in TOTALS:
                            groups[key][n] += totals[n]
                        for basis in (('gross',) if product == 'micro' else ('fee', 'slip')):
                            label = key + '_' + basis
                            rid = '93_' + label + '_' + session
                            path = temp / (rid + '.trades.jsonl')
                            unit = 0 if basis == 'gross' else fee + (5*point if basis == 'slip' else 0)
                            side = 1 if day % 2 == 0 else -1
                            at = datetime.fromisoformat(date + ('T09:00:00+09:00' if kind == 'Day' else 'T18:00:00+09:00'))
                            trades = [{'id': rid + str(i), 'timestamp': (at+timedelta(seconds=i)).isoformat(),
                                       'type': ('Long' if side == 1 else 'Short') + ('N' if i == 0 else 'R'),
                                       'position_id': rid, 'price': price, 'qty': qty, 'fee_yen': unit*qty,
                                       'method_id': label, 'source_line': 10+i}
                                      for i, (price, qty) in enumerate(((1000, 3), (1000+30*side, 1), (1000+last_move*side, 2)))]
                            path.write_text(''.join(json.dumps(t, ensure_ascii=False)+'\n' for t in trades), encoding='utf-8')
                            resource = {'id': rid, 'title': '人工', 'symbol': 'NK225', 'session': session,
                                        'product': 'NK225'+product, 'method_id': label, 'point_value': point,
                                        'pnl_format': 'trades', 'pnl_basis': 'net', 'pnl_path': path.name,
                                        'market_path': 'NK225/'+session+'/book.jsonl.gz'}
                            resources.append(resource)
                            by_resource[rid] = trades
        result = {'試行': 93, '場数': 54, '手法場数': 81, '商品手法会計数': 162, '元gross一致': True,
                  '集計': groups, '場別': rows, '新5分': False, '新利益追尾': False, '外テクニカル': False,
                  '対照照合': {k: {'元報告gross': groups[k]['gross_yen'], '再現gross': groups[k]['gross_yen'], '差': 0} for k in KEYS if k.startswith('micro_')}}
        catalog_path, result_path = temp/'一覧.resources.json', temp/'結果.json'
        catalog = {'schema_version': 1, 'path_base': 'catalog', 'resources': resources}
        catalog_path.write_text(json.dumps(catalog, ensure_ascii=False), encoding='utf-8')
        result_path.write_text(json.dumps(result, ensure_ascii=False), encoding='utf-8')
        resolved = {r['id']: {**r, 'pnl_path': str(temp/r['pnl_path']), 'market_path': str(temp/'市場'/r['market_path'])} for r in resources}

        def fake(method: str, url: str, payload=None):
            """
            機能: 既存APIのschemaに沿った架空応答を返す。
            引数: method/url(str)、payload(dict|None)は人工依頼。
            返り値: tuple[dict,bytes,dict]は本文・指紋。ネットワークは使わない。
            """
            if url.endswith('/api/info'):
                value = {'resource_root': str(temp), 'data_root': str(temp/'市場'), 'listen': '127.0.0.1:8092'}
            elif url.endswith('/api/catalogs/load'):
                need(method == 'POST' and payload == {'path': catalog_path.name}, '人工一覧依頼')
                value = {'catalog_id': '人工243', 'path': str(catalog_path), 'resources': list(resolved.values())}
            else:
                rid = parse_qs(urlparse(url).query)['resource'][0]
                events = BASE.trade_expectations(by_resource[rid], resolved[rid]['point_value'])
                net = number(sum((decimal(e['realized_delta_yen']) for e in events), Decimal(0)))
                value = {'resource': resolved[rid], 'summary': {'long_qty': 0, 'short_qty': 0, 'realized_pnl_yen': net, 'unrealized_pnl_yen': 0},
                         'state_columns': ['long_qty', 'short_qty', 'realized_pnl_yen', 'unrealized_pnl_yen'], 'states': [[0, 0, net, 0]],
                         'events': events, 'files': {'pnl': resolved[rid]['pnl_path'], 'market': resolved[rid]['market_path'], 'catalog': str(catalog_path)}}
            raw = json.dumps(value, ensure_ascii=False).encode('utf-8')
            return value, raw, {'x-chart-data-sha256': hashlib.sha256(raw).hexdigest()}

        prepared = local_inputs(catalog_path, result_path)
        for basis, wanted in (('fee', [-115.5, 2961.5, 1923]), ('slip', [-1615.5, 2461.5, 923])):
            first = next(r for r in resources if r['product'] == 'NK225mini' and r['method_id'].endswith('_' + basis))
            need([e['realized_delta_yen'] for e in prepared['events'][first['id']]] == wanted, '半円配賦の手計算:' + basis)
        good = run(catalog_path, result_path, transport=fake, workers=4, progress=False)
        need(good['成功'] and good['完了資源'] == 243 and good['不一致数'] == 0, '243正常人工')
        checked = ['243資源非0・micro倍率10/mini倍率100・買売鏡像・半円全約定・最終所有0', 'mini半円配賦の手計算2基準']
        for corruption in ('半円増減', '最終所有未知', '終状態数量', '倍率', '本文SHA', '資源欠落', '通信未完'):
            def damaged(method: str, url: str, payload=None):
                """
                機能: 1種類の破損を人工応答へ入れる。
                引数: method/url(str)、payload(dict|None)は人工依頼。
                返り値: tupleは破損応答。通信失敗時は固定例外を送出する。
                """
                if corruption == '通信未完' and '/api/data?' in url:
                    raise BASE.ViewerError('通信', url, '人工未取得')
                value, _, _ = fake(method, url, payload)
                if url.endswith('/api/catalogs/load') and corruption == '資源欠落':
                    value['resources'] = value['resources'][:-1]
                if '/api/data?' in url:
                    if corruption == '半円増減':
                        value['events'][0]['realized_delta_yen'] += .5
                    elif corruption == '最終所有未知':
                        value['summary']['long_qty'] = None
                    elif corruption == '終状態数量':
                        value['states'][-1][1] = 1
                    elif corruption == '倍率':
                        value['resource'] = {**value['resource'], 'point_value': 10 if value['resource']['point_value'] == 100 else 100}
                raw = json.dumps(value, ensure_ascii=False).encode('utf-8')
                return value, raw, {'x-chart-data-sha256': '破損' if corruption == '本文SHA' else hashlib.sha256(raw).hexdigest()}
            bad = run(catalog_path, result_path, transport=damaged, workers=4, progress=False)
            need(not bad['成功'], 'API破損の成功化:' + corruption)
            checked.append(corruption + 'を検出')
        first = next(r for r in resources if r['product'] == 'NK225mini')
        trade_path = temp/first['pnl_path']
        original = trade_path.read_bytes()
        saved = [json.loads(line) for line in original.decode().splitlines()]
        saved[0]['fee_yen'] += .5
        trade_path.write_text(''.join(json.dumps(t)+'\n' for t in saved), encoding='utf-8')
        try:
            local_inputs(catalog_path, result_path)
        except ValueError:
            checked.append('ローカル半円費用破損をAPI前に拒否')
        else:
            raise AssertionError('ローカル半円費用破損を受理')
        trade_path.write_bytes(original)
        empty = resources[0]
        empty_path = temp / empty['pnl_path']
        original_trades, original_result = empty_path.read_bytes(), result_path.read_bytes()
        empty_row = rows[0]
        old_totals = empty_row['totals']
        for name in TOTALS:
            groups[empty_row['key']][name] -= old_totals[name]
        empty_row['totals'], empty_row['holds'], empty_row['fills'] = {name: 0 for name in TOTALS}, 0, 0
        amount = groups[empty_row['key']]['gross_yen']
        result['対照照合'][empty_row['key']] = {'元報告gross': REFERENCE_GROSS[empty_row['key']], '再現gross': amount, '差': amount-REFERENCE_GROSS[empty_row['key']]}
        result['元gross一致'] = False
        empty_path.write_bytes(b'')
        by_resource[empty['id']] = []
        result_path.write_text(json.dumps(result, ensure_ascii=False), encoding='utf-8')
        empty_good = run(catalog_path, result_path, transport=fake, workers=4, progress=False, allow_reference_mismatch=True)
        need(empty_good['成功'], '無取引資源の最終所有0')
        checked.append('無取引資源を約定0・純額0・最終所有0で照合')
        empty_path.write_bytes(original_trades)
        result_path.write_bytes(original_result)
        by_resource[empty['id']] = [json.loads(line) for line in original_trades.decode().splitlines()]
        result = json.loads(original_result)
        changed_files = []
        for key, difference in (('micro_D164_15', -300), ('micro_P164_06', 5000)):
            chosen = next(r for r in result['場別'] if r['key'] == key)
            rid = '93_' + key + '_gross_' + chosen['session']
            resource = next(r for r in resources if r['id'] == rid)
            path = temp / resource['pnl_path']
            body = path.read_bytes()
            saved = [json.loads(line) for line in body.decode().splitlines()]
            saved[-1]['price'] += difference/20
            path.write_text(''.join(json.dumps(t)+'\n' for t in saved), encoding='utf-8')
            changed_files.append((path, body, rid))
            by_resource[rid] = saved
            for field in ('gross_yen', 'gross_minus_fee_yen', 'net_yen'):
                chosen['totals'][field] += difference
                result['集計'][key][field] += difference
            result['対照照合'][key]['再現gross'] += difference
            result['対照照合'][key]['差'] = difference
        result['元gross一致'] = False
        result_path.write_text(json.dumps(result, ensure_ascii=False), encoding='utf-8')
        try:
            local_inputs(catalog_path, result_path)
        except ValueError:
            checked.append('通常経路は元gross不一致を拒否')
        else:
            raise AssertionError('元gross不一致を無許可で受理')
        mismatch = run(catalog_path, result_path, transport=fake, workers=4, progress=False, allow_reference_mismatch=True)
        need(mismatch['成功'] and mismatch['元gross一致'] is False and mismatch['全面再現を本検査で保証'] is False and
             mismatch['元gross差円'] == {'micro_D164_15': -300, 'micro_P164_06': 5000, 'micro_U165_03': 0}, '参照不一致を保持した243表示照合')
        checked.append('明示時のみ元false/D−300/P＋5000/U0を保持して表示会計照合')
        result['対照照合']['micro_D164_15']['差'] += 1
        result_path.write_text(json.dumps(result, ensure_ascii=False), encoding='utf-8')
        try:
            local_inputs(catalog_path, result_path, True)
        except ValueError:
            checked.append('元gross差の1円算術破損を明示許可でも拒否')
        else:
            raise AssertionError('不正な参照差を受理')
        for path, body, rid in changed_files:
            path.write_bytes(body)
            by_resource[rid] = [json.loads(line) for line in body.decode().splitlines()]
        result_path.write_bytes(original_result)
        return {'成功': True, '人工項目': checked, '正常資源': 243, '正常照合項目': good['照合項目数'],
                '実API取得': 0, '実カタログ登録': 0, '市場/原板読取': 0, '本計算成果物読取': 0,
                '固定80部品SHA256': FIXED_SHA, '監査コードSHA256': BASE.sha(Path(__file__))}


def main() -> None:
    """
    機能: 人工又は明示された243資源を検査して新規証拠へ保存する。
    引数: --self-test/--run、--catalog/--result/--out(Path)、--url(str)、--workers(int)、--allow-reference-mismatch(bool)。
    返り値: None。不一致/未完は非0。既存サーバのプロセスへ作用しない。
    """
    parser = argparse.ArgumentParser(description='元連続mini/microの243Viewer数値照合')
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--self-test', action='store_true')
    mode.add_argument('--run', action='store_true')
    for name in ('catalog', 'result', 'out'):
        parser.add_argument('--'+name, type=Path, required=name == 'out')
    parser.add_argument('--url', default='http://127.0.0.1:8092')
    parser.add_argument('--workers', type=int, default=8)
    parser.add_argument('--allow-reference-mismatch', action='store_true', help='元gross不一致を保持してViewer保存会計だけを照合')
    args = parser.parse_args()
    need(not args.out.exists(), '出力は新規パスだけ')
    if args.self_test:
        need(args.catalog is None and args.result is None, '人工で本物の一覧/結果を読まない')
        value = self_test()
    else:
        need(args.catalog is not None and args.result is not None, '--runは一覧と結果を明示する')
        value = run(args.catalog, args.result, args.url, args.workers, allow_reference_mismatch=args.allow_reference_mismatch)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')
    print(json.dumps({k: value[k] for k in ('成功', '正常資源', '完了資源', '照合項目数', '不一致数') if k in value}, ensure_ascii=False))
    if not value['成功']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
