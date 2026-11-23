"""86の共有C0判断・旧85H0全値・複合退出の保存証拠を照合する。"""

from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile

ROOT = Path(__file__).resolve().parents[2]
BASE_PATH = ROOT / 'scripts/保持帯の返済側固定否定/基準と保存判断の照合.py'
BASE_SHA = '06c79198ed041a37577bd2f623a29f90cc76ae1ba8cb14764225a03b2e11368c'
KEYS = tuple(f'{mode}_D{delay}' for delay in (0, 1) for mode in ('J0G1', 'J1G1'))
COUNTS = ('normal_quotes', 'price_not_breached_short_known', 'price_not_breached_short_unknown', 'price_breached_short_unknown', 'price_breached_not_opposed', 'confirmed')
FIRSTS = ('confirm_first_price_breach', 'confirm_first_unknown', 'confirm_first_confirmed')
ORDER_FIELDS = {'confirm_evidence'}
LOT_FIELDS = {'confirm_counts', *FIRSTS}
CLOSED_FIELDS = {'confirm_request_evidence', *FIRSTS}
METRIC_FIELDS = {'confirm_counts', 'confirm_confirmed_lots', 'confirm_exit_orders', 'confirm_exit_obligations', 'confirm_missing_quantity'}
EVIDENCE_FIELDS = {'rule_version', 'at', 'quote_index', 'source_line', 'feature_index', 'source_time', 'received', 'last', 'bid', 'ask', 'short', 'price_breached', 'short_known', 'opposed', 'confirmed', 'reason'}
SHORT_WINDOW_FIELDS = {'known', 'move', 'speed', 'elapsed', 'endpoint', 'delay', 'reason'}
EXIT_REASON = '保持帯両気配1tick・短秒反対確認'
REASONS = ('保持帯両気配1tick否定は未成立', '保持帯両気配1tick成立・短秒未知', '保持帯両気配1tick成立・短秒の両反対は不成立', EXIT_REASON)


def sha(path: Path) -> str:
    """
    機能: ファイル本文の指紋を取得する。
    引数: path (Path) は読取専用ファイル。
    返り値: str はSHA256。
    """
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def load_base() -> object:
    """
    機能: 停止85の保存検査helperを読取で再用する。
    引数: なし。既知SHAのPythonだけを参照する。
    返り値: object は85モジュール。市場・Goの実行は行わない。
    """
    assert sha(BASE_PATH) == BASE_SHA, '停止85保存監査が変わりました'
    spec = importlib.util.spec_from_file_location('fixed85_for86_saved', BASE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


OLD = load_base()
BASE = OLD.BASE
POLICY = OLD.OLD
canonical_sha = OLD.canonical_sha
diagnostic_rows = OLD.diagnostic_rows


def zero_counts() -> dict:
    """
    機能: 観測off用の正規0カウンターを作る。
    引数: なし。
    返り値: dict は6tag全て整数0の新しい写像。
    """
    return dict.fromkeys(COUNTS, 0)


def project_confirm(book: dict) -> dict:
    """
    機能: 宣言したconfirm欄だけを除いて停止85へ投影する。
    引数: book (dict) は86会計。
    返り値: dict は旧全field・配列順序・数値・IDを保持した複写。
    """
    value = deepcopy(book)
    value.pop('confirm_enabled', None)
    for container, name in BASE.CONTAINERS.items():
        fields = ORDER_FIELDS if name == 'ActualOrder' else LOT_FIELDS if name == 'ActualLot' else CLOSED_FIELDS
        for row in value[container]:
            for field in fields:
                row.pop(field, None)
    for field in METRIC_FIELDS:
        value['metrics'].pop(field, None)
    return value


def validate_counts(value: dict, audit: object, where: str) -> None:
    """
    機能: 正常残玉原行を5群へ分ける相互排他カウンターを検査する。
    引数: value (dict) は6tag、audit (Audit)、where (str) は検査場所。
    返り値: None。真偽値・負数・型違い・分母差を拒否する。
    """
    audit.check(type(value) is dict and set(value) == set(COUNTS), '確認6カウンター集合', where)
    if type(value) is not dict or set(value) != set(COUNTS):
        return
    valid = all(type(value[name]) is int and value[name] >= 0 for name in COUNTS)
    audit.check(valid, '確認カウンター非負整数', where)
    if valid:
        audit.check(value['normal_quotes'] == sum(value[name] for name in COUNTS[1:]), '確認5群と正常残玉分母', where)


def expected_evidence(value: dict, lot: dict) -> dict:
    """
    機能: 保存当原行の短秒時計と凍結帯から確認式を別Python式で再計算する。
    引数: value (dict) は16tag証拠、lot (dict) は所有と要求時HoldAnchor。
    返り値: dict は再計算した証拠。不整合・非有限・既知窓矛盾はValueError。
    """
    need = OLD.strict
    need(type(value) is dict and set(value) == EVIDENCE_FIELDS, '確認証拠16tag集合')
    need(type(value['rule_version']) is int and value['rule_version'] == 1, '確認証拠版')
    need(all(type(value[name]) is bool for name in ('price_breached', 'short_known', 'opposed', 'confirmed')), '確認証拠bool型')
    need(type(value['reason']) is str, '確認証拠理由型')
    need(all(OLD.valid_number(value[name]) for name in ('at', 'source_time', 'received', 'last', 'bid', 'ask')), '確認証拠有限値')
    need(all(OLD.integer(value[name]) for name in ('quote_index', 'feature_index')) and OLD.integer(value['source_line'], 1), '確認証拠の別連番')
    need(value['source_time'] == value['received'] == value['at'], '確認証拠の同原行時計')
    need(value['last'] > 0 and OLD.grid_price(value['bid']) and OLD.grid_price(value['ask']) and value['bid'] < value['ask'], '確認証拠の正常BBO格子')
    need(value['at'] >= lot['entry_time'] and value['source_line'] >= lot['entry_line'] and value['quote_index'] >= lot['entry_index'], '確認証拠は取得後')
    short = value['short']
    need(type(short) is dict and set(short) == {'time', 'mid', 'five', 'fifteen'}, '短秒4tag集合')
    need(OLD.valid_number(short['time']) and OLD.valid_number(short['mid']) and short['time'] == value['at'] and short['mid'] == value['bid'] + (value['ask']-value['bid'])/2, '短秒の同原行時計とMid')
    for name, horizon in (('five', 5), ('fifteen', 15)):
        window = short[name]
        need(type(window) is dict and set(window) == SHORT_WINDOW_FIELDS, '短秒窓7tag集合')
        need(type(window['known']) is bool and type(window['reason']) is str, '短秒既知理由型')
        need(all(OLD.valid_number(window[field]) for field in ('move', 'speed', 'elapsed', 'endpoint', 'delay')), '未知を含む短秒有限性')
        if window['known']:
            need(window['elapsed'] >= horizon and window['elapsed'] == short['time']-window['endpoint'] and window['endpoint'] <= short['time']-horizon and window['delay'] == window['elapsed']-horizon and 0 <= window['delay'] <= 15, '既知短秒の両端・実経過・遅れ')
            need(window['speed'] == window['move']/window['elapsed'], '既知短秒のpt毎秒厳密一致')
    anchor = lot['hold_anchor']
    need(anchor['known'] and anchor['side'] == lot['side'] and lot['side'] in (-1, 1), '確認の同方向凍結帯')
    side = lot['side']
    price = side*(value['bid']-anchor['hold_bid']) <= -10 and side*(value['ask']-anchor['hold_ask']) <= -10
    known = short['five']['known'] and short['fifteen']['known']
    opposed = known and side*short['five']['speed'] < 0 and side*short['fifteen']['speed'] < 0
    confirmed = price and opposed
    reason = REASONS[0] if not price else REASONS[1] if not known else REASONS[2] if not opposed else REASONS[3]
    return {**deepcopy(value), 'price_breached': price, 'short_known': known, 'opposed': opposed, 'confirmed': confirmed, 'reason': reason}


def validate_schema(book: dict, audit: object, where: str) -> dict:
    """
    機能: 新欄の厳密集合を検査し、宣言投影後の旧85全schemaも検査する。
    引数: book (dict)、audit (Audit)、where (str) は会計・差分台帳・場所。
    返り値: dict は確認欄だけを除いた旧85会計。
    """
    expected = BASE.schemas()
    audit.check(set(book) == expected['BookResult'] | {'hold_enabled', 'confirm_enabled'}, '86会計フィールド集合', where)
    for container, name in BASE.CONTAINERS.items():
        old_fields = OLD.HOLD_ORDER if name == 'ActualOrder' else OLD.HOLD_LOT
        additions = ORDER_FIELDS if name == 'ActualOrder' else LOT_FIELDS if name == 'ActualLot' else CLOSED_FIELDS
        for index, row in enumerate(book[container]):
            wanted = expected[name] | BASE.EXTRA[name] | old_fields | additions
            audit.check(set(row) == wanted, '86会計内フィールド集合', f'{where}.{container}[{index}]', sorted(row), sorted(wanted))
    wanted = expected['BookMetrics'] | BASE.EXTRA['BookMetrics'] | OLD.HOLD_METRICS | METRIC_FIELDS
    audit.check(set(book['metrics']) == wanted, '86集計フィールド集合', where)
    projected = project_confirm(book)
    OLD.validate_hold_schema(projected, expected, audit, where+'.旧85投影')
    return projected


def bind_confirmation(book: dict, enabled: bool, audit: object, where: str) -> None:
    """
    機能: 新証拠・初回時点・返済要求凍結値・全新counterを所有へ結ぶ。
    引数: book (dict)、enabled (bool)、audit (Audit)、where (str) は会計と設定。
    返り値: None。全原行の見逃し・実約定は独立原板監査へ分担する。
    """
    audit.check(type(book['confirm_enabled']) is bool and book['confirm_enabled'] == enabled, '複合確認off/on明示', where)
    lots = {lot['id']: lot for lot in book['lots']}
    total = Counter()
    for lot in book['lots']:
        place = where+'.lot.'+lot['id']
        counts = lot['confirm_counts']
        validate_counts(counts, audit, place)
        total.update(counts)
        if not enabled:
            BASE.compare(counts, zero_counts(), audit, place, 'J0観測off0')
        for name in FIRSTS:
            evidence = lot[name]
            if not enabled:
                audit.check(evidence is None, 'J0観測off初回null', place+'.'+name)
            if evidence is None:
                continue
            expected = expected_evidence(evidence, lot)
            BASE.compare(evidence, expected, audit, place+'.'+name, '凍結帯と当原行短秒の独立式')
            required = expected['price_breached'] if name == FIRSTS[0] else expected['price_breached'] and not expected['short_known'] if name == FIRSTS[1] else expected['confirmed']
            audit.check(required, '初回証拠の役割', place+'.'+name)
        price_count = sum(counts[name] for name in ('price_breached_short_unknown', 'price_breached_not_opposed', 'confirmed'))
        for name, count in ((FIRSTS[0], price_count), (FIRSTS[1], counts['price_breached_short_unknown']), (FIRSTS[2], counts['confirmed'])):
            audit.check((lot[name] is not None) == (count > 0), '初回と保存counterの存在対応', place+'.'+name)
        first = lot[FIRSTS[0]]
        if first is not None:
            for name in FIRSTS[1:]:
                if lot[name] is not None:
                    later = lot[name]
                    audit.check(first['at'] <= later['at'] and first['source_line'] <= later['source_line'] and first['quote_index'] <= later['quote_index'], '価格初回が未知又は成立初回以前', place+'.'+name)
    # ----------------------------------------
    for container, name in BASE.CONTAINERS.items():
        for index, row in enumerate(book[container]):
            place = f'{where}.{container}[{index}]'
            if name == 'ActualLot':
                if container == 'positions':
                    lot = lots.get(row['id'])
                    audit.check(lot is not None, '残玉の実玉所有', place)
                    if lot is not None:
                        for field in LOT_FIELDS:
                            BASE.compare(row[field], lot[field], audit, place+'.'+field, '残玉の確認状態')
                continue
            lot = lots.get(row['position_id'])
            if name == 'ActualOrder':
                evidence = row['confirm_evidence']
                expected_present = enabled and row['kind'] == 'exit' and row['reason'] == EXIT_REASON
                audit.check((evidence is not None) == expected_present, '新理由だけ要求証拠を凍結', place)
                if evidence is not None:
                    audit.check(lot is not None, '確認要求の実玉所有', place)
                    if lot is None:
                        continue
                    BASE.compare(evidence, expected_evidence(evidence, lot), audit, place, '追加返済要求の式')
                    audit.check(evidence['confirmed'] and (evidence['at'], evidence['quote_index'], evidence['source_line']) == (row['request_time'], row['request_index'], row['request_line']), '追加要求の当原行出典', place)
                    mark = evidence['bid'] if lot['side'] == 1 else evidence['ask']
                    audit.check(row['mark'] == mark, '確認返済要求の返済側価格', place)
                    first = lot[FIRSTS[2]]
                    audit.check(first is not None and first['source_line'] <= evidence['source_line'], '追加要求前に成立初回', place)
                continue
            audit.check(lot is not None, '返済片の実玉所有', place)
            if lot is None:
                continue
            matches = [order for order in book['orders'] if order['kind'] == 'exit' and order['position_id'] == row['position_id'] and order['request_time'] == row['request_time'] and order['reason'] == row['reason']]
            audit.check(len(matches) == 1, '返済片の要求一意結合', place)
            if len(matches) == 1:
                BASE.compare(row['confirm_request_evidence'], matches[0]['confirm_evidence'], audit, place, '返済片の要求凍結証拠')
            for field in FIRSTS:
                first = lot[field]
                expected = first if first is not None and first['source_line'] < row['exit_line'] else None
                BASE.compare(row[field], expected, audit, place+'.'+field, '全fill時点の初回snapshot・同原行後段非遡及')
    # ----------------------------------------
    metrics = book['metrics']
    validate_counts(metrics['confirm_counts'], audit, where+'.metrics')
    BASE.compare(metrics['confirm_counts'], {name: total[name] for name in COUNTS}, audit, where, '全玉確認counter合計')
    expected_metrics = {'confirm_confirmed_lots': sum(lot[FIRSTS[2]] is not None for lot in lots.values()),
        'confirm_exit_orders': sum(order['kind'] == 'exit' and order['reason'] == EXIT_REASON for order in book['orders']),
        'confirm_exit_obligations': total['confirmed'], 'confirm_missing_quantity': 0}
    for name, expected in expected_metrics.items():
        audit.check(type(metrics[name]) is int and metrics[name] == expected, '確認新集計の保存対応', where+'.'+name, metrics[name], expected)
    if not enabled:
        audit.check(all(metrics[name] == 0 for name in expected_metrics), 'J0の確認追加処理off', where)


def audit_scene(current: dict, baseline: dict, session: str, times: list[float], audit: object) -> dict:
    """
    機能: 一場の共有定時全文・全4会計・J0対85H0全値を照合する。
    引数: current/baseline (dict) は86/85、session (str)、times (list[float])、audit (Audit)。
    返り値: dict は場別証拠と共有判断/全玉診断canonical指紋。
    """
    for value, name in ((current, '86'), (baseline, '85')):
        BASE.inspect_finite(value, audit, session+name)
        audit.check(set(value) == {'session', 'quality', 'books', 'grid_decisions'} and value['session'] == session, '場本文schema', session+name)
    audit.check(set(current['books']) == set(KEYS), '86四会計集合', session)
    baseline_keys = set(baseline['books'])
    audit.check(baseline_keys in (set(OLD.KEYS), {'H0G1_D0', 'H0G1_D1'}), '停止85会計集合又は明示人工H0', session)
    BASE.compare(current['quality'], baseline['quality'], audit, session, '85品質全文')
    BASE.compare(current['grid_decisions'], baseline['grid_decisions'], audit, session, '85共有定時全文同値')
    grids = current['grid_decisions']
    audit.check([g['at'] for g in grids] == times, '86全予定順序', session)
    by_time, count, holds = {}, Counter(), Counter()
    for index, grid in enumerate(grids):
        at = grid['at']; where = session+f'.grid[{index}]'
        audit.check(at not in by_time, '定時重複なし', where); by_time[at] = grid
        audit.check(set(grid) == {'at', 'window', 'entry_policy', 'decision', 'clock_allowed', 'block_reason', 'candidate_accepted', 'structure_anchor', 'policies', 'hold_anchor'}, '86共有定時フィールド集合', where)
        audit.check(grid['entry_policy'] == 'C0' and set(grid['policies']) == {'C0'}, '固定C0共有政策', where)
        BASE.compare(grid['structure_anchor'], BASE.expected_anchor(at, grid['decision']['technical']), audit, where, 'EMA出典')
        refined = POLICY.refined(grid['decision'], 'C0', audit, where)
        refined['candidate_accepted'] = POLICY.candidate(session, grid, refined) is not None
        BASE.compare(grid['policies']['C0'], refined, audit, where, '固定C0純採否再計算')
        audit.check(grid['candidate_accepted'] == refined['candidate_accepted'], 'top候補C0', where)
        source = POLICY.candidate(session, grid, refined)
        anchor = OLD.expected_hold_anchor(grid, source['side'] if source else 0)
        BASE.compare(grid['hold_anchor'], anchor, audit, where, '保持帯出典20tag')
        holds['既知枠' if anchor['known'] else '未知未使用枠'] += 1
        for name, value in (('許可', refined['allowed']), ('候補', refined['candidate_accepted']), ('必須未知', refined['required_unknown']), ('既知不許可', not refined['allowed'] and not refined['required_unknown']), ('許可初動', refined['allowed'] and refined['role'] == '転換初動')):
            count['C0:'+name] += value
    actions, confirm = [], {}
    for key in KEYS:
        mode, delay_text = key.split('_D'); book = current['books'][key]; delay = int(delay_text)
        projected = validate_schema(book, audit, session+key)
        POLICY.bind_book(OLD.project_hold(projected), 'C0', delay, by_time, audit, session+key, BASE.schemas())
        audit.check(book['side_cap'] == 100, '固定100枚上限', session+key)
        OLD.bind_hold_metadata(projected, False, by_time, audit, session+key)
        bind_confirmation(book, mode == 'J1G1', audit, session+key)
        financial, interpreted = OLD.policy_actions(book, by_time)
        audit.check(sum(financial.values()) == sum(interpreted.values()) == len(times), '全予定枠の金融と方針判断', session+key)
        actions.append({'session': session, 'key': key, '金融判断': financial, '方針判断': interpreted})
        confirm[key] = {name: deepcopy(book['metrics'][name]) for name in sorted(METRIC_FIELDS)}
    for delay in (0, 1):
        old = baseline['books'][f'H0G1_D{delay}']
        OLD.validate_hold_schema(old, BASE.schemas(), audit, session+'.85H0')
        BASE.compare(project_confirm(current['books'][f'J0G1_D{delay}']), old, audit, session+f'.J0D{delay}', 'J0対85H0全旧会計')
    return {'場': session, '予定枠': len(grids), '基準会計': 2, '政策件数': dict(count), '保持帯枠': dict(holds), '方針判断': actions, '複合確認': confirm,
        '共有判断SHA256': canonical_sha(grids), '玉診断SHA256': {key: canonical_sha(diagnostic_rows(session, key, current['books'][key])) for key in KEYS}}


def audit_directories(source: Path, baseline: Path, sessions: list[str], pins85: dict | None, audit: object) -> dict:
    """
    機能: 全66保存を2442予定枠・132旧会計と前後入力指紋へ結ぶ。
    引数: source/baseline (Path) は86/85、sessions (list[str])、pins85 (dict|None)、audit (Audit)。
    返り値: dict は全場処理・政策/確認の小型証拠。途中処理を成功にしない。
    """
    folders = {'86': source, '85': baseline}
    before = {name: BASE.inventory(folder) for name, folder in folders.items()}
    wanted = {session+'.json' for session in sessions}
    audit.check(len(sessions) == len(set(sessions)) == 66, '固定66場', '全体')
    for name, values in before.items():
        audit.check(set(values) == wanted, '全保存場集合', name)
    if pins85 is not None:
        audit.check(before['85'] == pins85, '固定85本文指紋', '全体')
    rows = []; complete = True
    try:
        for session in sessions:
            if any(session+'.json' not in before[name] for name in folders):
                continue
            rows.append(audit_scene(BASE.read_json(source/(session+'.json')), BASE.read_json(baseline/(session+'.json')), session, BASE.scheduled(session), audit))
    except Exception as error:
        complete = False
        audit.check(False, '読取処理未完', '全体', type(error).__name__+':'+str(error), '全場完了')
    after = {name: BASE.inventory(folder) for name, folder in folders.items()}
    audit.check(before == after, '入力集合と本文の前後不変', '全体')
    frames = sum(row['予定枠'] for row in rows)
    audit.check(len(rows) == 66 and frames == 2442, '66場2442枠完了', '全体', (len(rows), frames), (66, 2442))
    totals, holds = Counter(), Counter()
    for row in rows:
        totals.update(row['政策件数']); holds.update(row['保持帯枠'])
    return {'処理完了': complete and len(rows) == 66 and frames == 2442, '場数': len(rows), '予定枠': frames, '基準会計数': sum(row['基準会計'] for row in rows),
        '入力不変': before == after, '入力SHA256前': before, '入力SHA256後': after, '対象場': rows, '政策件数合計': dict(totals), '政策全予定枠': {'C0': frames}, '保持帯枠合計': dict(holds), '方針判断': [item for row in rows for item in row['方針判断']]}


def fixture(session: str, times: list[float]) -> tuple[dict, dict]:
    """
    機能: 旧85人工を対照として全新欄を持つ86保存人工を作る。
    引数: session (str)、times (list[float]) は人工場と予定枠。
    返り値: tuple[dict,dict] は86/85。金融やSourceを再生した結果とはしない。
    """
    baseline, _ = OLD.fixture(session, times)
    for delay in (0, 1):
        book = baseline['books'][f'H0G1_D{delay}']
        for closed in book['closed']:
            order = deepcopy(book['orders'][0])
            order.update(id=order['id']+'_人工返済', kind='exit', request_time=closed['request_time'], reason=closed['reason'])
            book['orders'].append(order)
    current = {**deepcopy(baseline), 'books': {}}
    for delay in (0, 1):
        for mode in ('J0G1', 'J1G1'):
            book = deepcopy(baseline['books'][f'H0G1_D{delay}'])
            book['confirm_enabled'] = mode == 'J1G1'
            book['metrics'].update({name: 0 for name in METRIC_FIELDS if name != 'confirm_counts'})
            book['metrics']['confirm_counts'] = zero_counts()
            for container, name in BASE.CONTAINERS.items():
                for row in book[container]:
                    if name == 'ActualOrder':
                        row['confirm_evidence'] = None
                    elif name == 'ActualLot':
                        row['confirm_counts'] = zero_counts()
                        row.update(dict.fromkeys(FIRSTS))
                    else:
                        row['confirm_request_evidence'] = None
                        row.update(dict.fromkeys(FIRSTS))
            current['books'][f'{mode}_D{delay}'] = book
    return current, baseline


def self_test() -> dict:
    """
    機能: 全66/2442/132と証拠式境界・破損拒否を市場入力なしで検査する。
    引数: なし。固定80台帳は場IDだけを読む。
    返り値: dict は人工成功・照合数・反証数。約定監査完了とはしない。
    """
    manifest = BASE.read_json(ROOT/'study/00080_FAR後期三手法の15分移植と利益保護/入力台帳.json')
    sessions = [row['id'] for row in manifest['sessions']]
    audit = BASE.Audit()
    with tempfile.TemporaryDirectory(prefix='86保存人工_') as temp:
        source = Path(temp)/'86'; baseline = Path(temp)/'85'
        source.mkdir(); baseline.mkdir()
        for session in sessions:
            current, old = fixture(session, BASE.scheduled(session))
            for folder, value in ((source, current), (baseline, old)):
                (folder/(session+'.json')).write_text(json.dumps(value, ensure_ascii=False, allow_nan=False), encoding='utf-8')
        result = audit_directories(source, baseline, sessions, None, audit)
    assert result['処理完了'] and result['基準会計数'] == 132 and audit.bad == 0, audit.examples
    # ----------------------------------------
    rejected = []
    session = sessions[0]; current, old = fixture(session, BASE.scheduled(session)[:1])
    for name, mutation in (
        ('J0旧数値', lambda x: x['books']['J0G1_D0']['metrics'].__setitem__('cash_yen', 7)),
        ('共有定時', lambda x: x['grid_decisions'][0].__setitem__('block_reason', '破損')),
        ('未知confirm欄', lambda x: x['books']['J1G1_D0'].__setitem__('confirm_future', 1)),
        ('J0観測counter', lambda x: x['books']['J0G1_D0']['metrics']['confirm_counts'].__setitem__('normal_quotes', 1)),
        ('保持帯床併用', lambda x: x['books']['J1G1_D0'].__setitem__('hold_enabled', True)),
        ('新理由証拠欠落', lambda x: x['books']['J1G1_D0']['orders'][-1].__setitem__('reason', EXIT_REASON)),
    ):
        changed = deepcopy(current); mutation(changed); check = BASE.Audit()
        try:
            audit_scene(changed, old, session, BASE.scheduled(session)[:1], check)
            assert check.bad > 0, name
        except (ValueError, KeyError, TypeError):
            pass
        rejected.append(name)
    lot = current['books']['J1G1_D0']['lots'][0]
    t = lot['entry_time']; anchor = lot['hold_anchor']
    value = {'rule_version': 1, 'at': t, 'quote_index': lot['entry_index'], 'source_line': lot['entry_line'], 'feature_index': 777, 'source_time': t, 'received': t, 'last': 1000,
        'bid': anchor['hold_bid']-10, 'ask': anchor['hold_ask']-10, 'short': {'time': t, 'mid': anchor['hold_bid']-10+(anchor['hold_ask']-anchor['hold_bid'])/2,
            'five': {'known': True, 'move': -10, 'speed': -2, 'elapsed': 5, 'endpoint': t-5, 'delay': 0, 'reason': '人工既知'},
            'fifteen': {'known': True, 'move': -15, 'speed': -1, 'elapsed': 15, 'endpoint': t-15, 'delay': 0, 'reason': '人工既知'}},
        'price_breached': True, 'short_known': True, 'opposed': True, 'confirmed': True, 'reason': EXIT_REASON}
    assert expected_evidence(value, lot) == value
    boundary_count = 1
    for side in (-1, 1):
        own = deepcopy(lot); own['side'] = side; own['hold_anchor']['side'] = side
        event = deepcopy(value); event['bid'] = anchor['hold_bid']-10*side; event['ask'] = anchor['hold_ask']-10*side
        event['short']['mid'] = event['bid']+(event['ask']-event['bid'])/2
        for name in ('five', 'fifteen'):
            event['short'][name]['move'] *= side; event['short'][name]['speed'] *= side
        assert expected_evidence(event, own)['confirmed']; boundary_count += 1
        for name in ('five', 'fifteen'):
            zero = deepcopy(event); zero['short'][name].update(move=0, speed=0)
            assert not expected_evidence(zero, own)['confirmed']; boundary_count += 1
            unknown = deepcopy(event); unknown['short'][name]['known'] = False
            assert not expected_evidence(unknown, own)['short_known']; boundary_count += 1
    for name, mutation in (
        ('別原行時計', lambda x: x.__setitem__('source_time', t-1)),
        ('将来received', lambda x: x.__setitem__('received', t+1)),
        ('非格子BBO', lambda x: x.__setitem__('bid', x['bid']+1)),
        ('短秒別Mid', lambda x: x['short'].__setitem__('mid', 1)),
        ('既知速度矛盾', lambda x: x['short']['five'].__setitem__('speed', 999)),
        ('既知速度微小差', lambda x: x['short']['five'].__setitem__('speed', -2+1e-13)),
        ('既知未来端点', lambda x: x['short']['five'].__setitem__('endpoint', t+1)),
        ('未知非有限', lambda x: x['short']['five'].update(known=False, move=float('nan'))),
        ('余剰証拠欄', lambda x: x.__setitem__('future', 1)),
    ):
        changed = deepcopy(value); mutation(changed)
        try:
            expected_evidence(changed, lot)
        except ValueError:
            rejected.append(name)
        else:
            raise AssertionError(name)
    return {'成功': True, '場数': 66, '予定枠': 2442, '基準会計数': 132, '人工照合項目数': audit.count, '境界式': boundary_count, '拒否反証': rejected, '市場再生': 0, '本物原板読取': 0}


def main() -> None:
    """
    機能: 全66保存を停止85へ結び、成功・未完・入力前後指紋を新規証拠へ残す。
    引数: --input/--baseline/--out (Path) 全必須、又は --self-test (bool)。
    返り値: None。正式失敗は非0終了。新売買・本物原板の再読は行わない。
    """
    parser = argparse.ArgumentParser()
    for name in ('input', 'baseline', 'out'):
        parser.add_argument('--'+name, type=Path)
    parser.add_argument('--self-test', action='store_true'); args = parser.parse_args()
    if args.self_test:
        if any((args.input, args.baseline, args.out)):
            raise ValueError('人工と正式入力を混在させません')
        print(json.dumps(self_test(), ensure_ascii=False)); return
    if not all((args.input, args.baseline, args.out)):
        raise ValueError('input/baseline/outを全て明示してください')
    if args.out.exists() or any(args.out.resolve().is_relative_to(path.resolve()) for path in (args.input, args.baseline)):
        raise ValueError('新規証拠を入力外へ保存してください')
    audit = BASE.Audit(); small = {}; data = {'処理完了': False, '場数': 0, '予定枠': 0, '基準会計数': 0, '入力不変': False}
    try:
        manifest = ROOT/'study/00080_FAR後期三手法の15分移植と利益保護/入力台帳.json'
        result85 = ROOT/'study/00085_保持帯の返済側固定否定/成果物/結果.json'
        conditions = [ROOT/'study'/folder/'条件.json' for folder in ('00086_保持帯喪失と短秒反対の複合退出', '00085_保持帯の返済側固定否定', '00084_現在の価格応答と数量確認', '00083_構造否定と利益配分')]
        files = [manifest, result85, BASE_PATH, OLD.BASE_PATH, OLD.OLD.BASE_PATH, ROOT/'scripts/定時の現在根拠と部分利益保護/actual.go', *conditions]
        small = {path.relative_to(ROOT).as_posix(): sha(path) for path in files}
        sessions = [row['id'] for row in BASE.read_json(manifest)['sessions']]
        for path in conditions:
            condition = BASE.read_json(path)
            groups = [condition['コードと依存SHA256']] + [value for name, value in condition.items() if name.startswith('固定') and name.endswith('依存') and type(value) is dict]
            if '実行ファイル' in condition:
                groups.append({condition['実行ファイル']: condition['実行ファイルSHA256']})
            for group in groups:
                for name, wanted in group.items():
                    audit.check(sha(ROOT/name) == wanted, '新旧固定依存の不変', name)
        data = audit_directories(args.input.resolve(), args.baseline.resolve(), sessions, BASE.read_json(result85)['再生結果SHA256'], audit)
        audit.check({name: sha(ROOT/name) for name in small} == small, '小型固定依存の前後不変', '全体')
    except Exception as error:
        audit.check(False, '全体処理未完', '全体', type(error).__name__+':'+str(error), '完了')
    success = data['処理完了'] and audit.bad == 0
    output = {'試行': 86, '成功': success, **data, '照合項目数': audit.count, '不一致数': audit.bad, '不一致': audit.examples, '項目別比較数': dict(audit.scope),
        '固定小型入力SHA256': small, '照合コードSHA256': sha(Path(__file__)), '読取helperSHA256': BASE_SHA, '旧比較helperSHA256': OLD.BASE_SHA,
        '新売買再生': 0, '本物原板読取': 0, '範囲外': ['元FAR保持帯出生・EMA/ATRの独立生成', '保存されない全正常残玉原行の短秒再構成・成立見逃し・予約/約定先着（別の独立原板監査）']}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(output, stream, ensure_ascii=False, indent=2, allow_nan=False); stream.write('\n')
    print(json.dumps({name: output[name] for name in ('成功', '場数', '予定枠', '基準会計数', '照合項目数', '不一致数')}, ensure_ascii=False))
    if not success:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
