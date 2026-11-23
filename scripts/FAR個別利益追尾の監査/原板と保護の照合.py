"""固定94の原行・約定・全経路保有評価を独立照合する。市場実行は別途明示する。"""

import argparse
import bisect
import concurrent.futures
import copy
import csv
import gzip
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[2]
BASE_PATH = ROOT / 'scripts/FAR元連続再現の監査/原板照合.py'
BASE_SHA = '49825ac408513e9cea8e9f8d852360a00436546fb9e99ec0b5edf2f86cafb62b'
QUOTE_FIELDS = {'time', 'index', 'source_line', 'last', 'bid', 'ask', 'quote_ok'}
POSITION_MARK_FIELDS = (
    'first', 'last', 'first_unit_positive', 'first_whole_positive',
    'first_unit_nonpositive_after', 'first_unit_negative_after',
    'first_whole_nonpositive_after', 'first_whole_negative_after',
    'unit_max', 'unit_min', 'whole_max', 'whole_min',
)
METRIC_FIELDS = set(('rows bad_quote_rows timer_calls native_batches native_new_signals native_new_fills '
    'native_close_notices native_close_fills native_cancels entry_requests entry_accepted_quantity '
    'cap_clipped_entries cap_rejected_entries cancelled_entries source_exit_requests protection_exit_requests '
    'entry_fills exit_fills protection_exit_fills unit_positive_positions whole_positive_positions '
    'protection_activated_positions activated_closed_negative unit_positive_closed_negative '
    'whole_positive_closed_negative atr_deferred_positions').split())


def digest(path: Path) -> str:
    """
    機能: ファイルを分割読取してSHA256を計算する。
    引数: path(Path)はコード又は明示された入力。
    返り値: strはSHA256。
    """
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def import_fixed(path: Path, expected: str, name: str):
    """
    機能: 本文指紋が一致する固定helperだけを読み込む。
    引数: path(Path)、expected/name(str)は固定先と識別子。
    返り値: moduleは固定モジュール。不一致はValueError。
    """
    if digest(path) != expected:
        raise ValueError('固定helper指紋差:' + str(path))
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


BASE = import_fixed(BASE_PATH, BASE_SHA, '固定93原板監査94')
Audit = BASE.Audit


def load(path: Path):
    """
    機能: 非有限定数と重複キーを拒否してJSONを読む。
    引数: path(Path)は明示されたJSON又はgzip。
    返り値: dict/listは保存本文。
    """
    opener = gzip.open if path.suffix == '.gz' else open
    with opener(path, 'rt', encoding='utf-8-sig') as stream:
        return json.load(stream, parse_constant=BASE.bad_constant, object_pairs_hook=unique_pairs)


def unique_pairs(pairs: list) -> dict:
    """
    機能: JSON objectの重複キーを拒否する。
    引数: pairs(list)は順番付きキー/値。
    返り値: dictは一意のobject。
    """
    out = {}
    for key, value in pairs:
        if key in out:
            raise ValueError('JSON重複キー:' + key)
        out[key] = value
    return out


def finite(value) -> bool:
    """
    機能: boolを除いた有限数を判定する。
    引数: value(any)は検査値。
    返り値: boolは有限数なら真。
    """
    return type(value) in (int, float) and math.isfinite(value)


def quote_ok(q: dict) -> bool:
    """
    機能: 実fillと評価に使える正常気配を判定する。
    引数: q(dict)は原行気配。
    返り値: boolは正Lastとstrict正常BBOなら真。
    """
    return q['quote_ok'] and q['last'] > 0 and 0 < q['bid'] < q['ask']


def validate_quote(q: dict, audit: Audit, label: str) -> None:
    """
    機能: 原行気配の型と有限性を確認する。
    引数: q(dict)、audit(Audit)、label(str)は気配と出典。
    返り値: None。不整合は例外。
    """
    audit.need(type(q) is dict and set(q) == QUOTE_FIELDS, label + ':気配集合')
    audit.need(all(finite(q[k]) for k in ('time', 'last', 'bid', 'ask')), label + ':気配有限')
    audit.need(q['time'] > 0 and type(q['index']) is int and q['index'] >= 0, label + ':時計Index')
    audit.need(type(q['source_line']) is int and q['source_line'] > 0, label + ':物理行')
    audit.need(type(q['quote_ok']) is bool and q['quote_ok'] == (0 < q['bid'] < q['ask']), label + ':正常気配旗')


def walk_raw(path: Path, session: str, quality: dict):
    """
    機能: 固定93の採用規則で全原板を一走査しActor対象気配を渡す。
    引数: path(Path)、session(str)、quality(dict)は原板・場・品質出力。
    返り値: iterator[dict]はLast正の全受理行。悪いBBOも省略しない。
    """
    clock = BASE.session_clock(session)
    quality.update(lines=0, clock_missing=0, outside=0, backward=0, bad_last=0,
                   bad_quote=0, accepted=0, contracts=[])
    codes, previous, index = set(), clock['start'], -1
    with gzip.open(path, 'rt', encoding='utf-8') as stream:
        for line, text in enumerate(stream, 1):
            quality['lines'] = line
            row = json.loads(text, parse_constant=BASE.bad_constant, object_pairs_hook=unique_pairs)
            if type(row) is not dict or type(row.get('Symbol')) is not str:
                raise ValueError('原板Symbol不正:' + str(line))
            codes.add(row['Symbol'])
            at = BASE.parse_clock(row.get('CurrentPriceTime'))
            if at is None:
                quality['clock_missing'] += 1
                continue
            if not clock['start'] <= at < clock['end']:
                quality['outside'] += 1
                continue
            if at < previous:
                quality['backward'] += 1
                continue
            previous = at
            last = BASE.number(row, 'CurrentPrice')
            quality['bad_last'] += int(last <= 0)
            bbo = {}
            for side in ('Buy', 'Sell'):
                for depth in range(1, 11):
                    key = side + str(depth)
                    if key not in row or row[key] is not None and type(row[key]) is not dict:
                        raise ValueError('原板段型不正:' + str(line) + ':' + key)
                    level = row[key] or {}
                    price = BASE.number(level, 'Price')
                    BASE.number(level, 'Qty')
                    if depth == 1:
                        bbo[side] = price
            good = 0 < bbo['Buy'] < bbo['Sell']
            quality['bad_quote'] += int(not good)
            quality['accepted'] += 1
            if last <= 0:
                continue
            index += 1
            yield {'time': at, 'index': index, 'source_line': line, 'last': last,
                   'bid': bbo['Buy'], 'ask': bbo['Sell'], 'quote_ok': good}
    quality['contracts'] = sorted(codes)


# ----------------------------------------
class ATRSeries:
    """固定5分足から公開時刻付きATRを独立計算する。Sourceを実行しない。"""

    def __init__(self, candles: list, start: float):
        """
        機能: TRの指数平滑と公開時計列を初期化する。
        引数: candles(list[dict])、start(float)は確定足と場開始。
        返り値: None。非有限・逆行足はValueError。
        """
        self.rows, self.times = [], []
        previous, running, received_prefix, last_time = None, 0.0, start, None
        for i, bar in enumerate(candles):
            if not all(finite(bar[k]) for k in ('time', 'open', 'high', 'low', 'close')):
                raise ValueError('ATR足の非有限値')
            if last_time is not None and bar['time'] <= last_time:
                raise ValueError('ATR足の逆行又は重複')
            last_time = bar['time']
            if bar['low'] <= 0 or not bar['low'] <= min(bar['open'], bar['close']) <= max(bar['open'], bar['close']) <= bar['high']:
                raise ValueError('ATR足OHLC不整合')
            tr = bar['high'] - bar['low']
            if previous is not None:
                tr = max(tr, abs(bar['high'] - previous), abs(bar['low'] - previous))
            running = tr if i == 0 else running * (1 - 1 / 12) + tr * (1 / 12)
            previous = bar['close']
            nominal = bar['time'] + 300 + 60
            received = bar.get('received', nominal)
            if not finite(received) or received < bar['time'] + 300:
                raise ValueError('ATR足受信時計不正')
            received_prefix = max(received_prefix, received)
            available = max(nominal, received_prefix)
            value = max(running, 20.0) if i >= 2 else 0.0
            self.rows.append({'value': value, 'available': available, 'nominal': nominal})
            self.times.append(available)

    def asof(self, at: float) -> dict:
        """
        機能: 当時までに公開された最後のATRだけを返す。
        引数: at(float)は当原行価格時計。
        返り値: dictはvalue/available/nominal。種不足は0。
        """
        index = bisect.bisect_right(self.times, at) - 1
        return copy.deepcopy(self.rows[index]) if index >= 0 else {'value': 0.0, 'available': 0.0, 'nominal': 0.0}


def candles_from_csv(path: Path, session: str) -> list:
    """
    機能: 固定CSVから当場のclosed確定5分足を読む。
    引数: path(Path)、session(str)は明示されたCSVと場。
    返り値: list[dict]はOHLC。公開は足開始+360秒。
    """
    clock = BASE.session_clock(session)
    out = []
    with path.open('r', encoding='utf-8-sig', newline='') as stream:
        rows = csv.DictReader(stream)
        if not {'time', 'open', 'high', 'low', 'close', 'closed'} <= set(rows.fieldnames or []):
            raise ValueError('ATR足CSV列不足')
        for row in rows:
            if row['closed'] != 'true':
                continue
            at = BASE.parse_clock(row['time'])
            if at is None:
                raise ValueError('ATR足CSV時計不正')
            if not clock['start'] <= at < clock['end']:
                continue
            bar = {k: float(row[k]) for k in ('open', 'high', 'low', 'close')}
            bar['time'] = at
            out.append(bar)
    return out


def mtm_point(position: dict, q: dict, phase: str, cost: float) -> dict:
    """
    機能: 未返済量に対するu/Wを返済側気配から計算する。
    引数: position/q(dict)、phase(str)、cost(float)は当時残量・原行・往復費用。
    返り値: dictは型と同一の評価点。残0はValueError。
    """
    if position['quantity'] <= 0 or not quote_ok(q):
        raise ValueError('保有評価に残量又は正常気配がない')
    mark = q['bid'] if position['side'] == 1 else q['ask']
    gain = position['side'] * (mark - position['entry_price'])
    unit = gain * 100 - cost
    return {'quote': q, 'phase': phase, 'quantity': position['quantity'],
            'reserved': position['reserved'], 'mark_price': mark, 'gain_points': gain,
            'unit_net': unit, 'realized_net': position['realized_net'],
            'whole_net': position['realized_net'] + position['quantity'] * unit}


class PositionMarks:
    """全正常原行の両phaseから初回・返し・極値を逐次再構築する。"""

    def __init__(self):
        """
        機能: 値なしの保有評価記録を作る。
        引数: なし。
        返り値: None。
        """
        self.value = {k: None for k in POSITION_MARK_FIELDS}

    def observe(self, point: dict) -> None:
        """
        機能: 一評価点で旗とstrict極値を更新する。
        引数: point(dict)は当原行・当phaseのu/W。
        返り値: None。同値極値は先点を保持する。
        """
        value = self.value
        if value['first'] is None:
            value['first'] = point
        value['last'] = point
        for field, short in (('unit_net', 'unit'), ('whole_net', 'whole')):
            positive = 'first_' + short + '_positive'
            if point[field] > 0 and value[positive] is None:
                value[positive] = point
            if value[positive] is not None:
                for op, pass_test in (('nonpositive', point[field] <= 0), ('negative', point[field] < 0)):
                    key = 'first_' + short + '_' + op + '_after'
                    if pass_test and value[key] is None:
                        value[key] = point
            for suffix, better in (('max', 1), ('min', -1)):
                key = short + '_' + suffix
                if value[key] is None or better * point[field] > better * value[key][field]:
                    value[key] = point


class AccountMarks:
    """全正常行で同時保有を合算し、全経路DDを別計算する。"""

    def __init__(self):
        """
        機能: 口座の極値・DD・評価間隔を初期化する。
        引数: なし。
        返り値: None。
        """
        self.value = dict(first=None, last=None, peak=None, max=None, min=None,
                          max_drawdown=0.0, drawdown_peak=None, drawdown_trough=None,
                          count=0, max_gap_seconds=0.0)

    def observe(self, q: dict, phase: str, cash: float, positions: dict, side_cost: float) -> None:
        """
        機能: 約定済純現金と残玉の清算評価を合算する。
        引数: q(dict)、phase(str)、cash/side_cost(float)、positions(dict)は当時状態。
        返り値: None。金額の同値は先の出典を保持する。
        """
        equity, buy, sell = cash, 0, 0
        for p in positions.values():
            qty = p['quantity']
            if qty <= 0:
                continue
            mark = q['bid'] if p['side'] == 1 else q['ask']
            gain = p['side'] * (mark - p['entry_price'])
            equity += qty * (gain * 100 - side_cost)
            buy += qty if p['side'] == 1 else 0
            sell += qty if p['side'] == -1 else 0
        point = dict(quote=q, phase=phase, equity=equity,
                     cash_net=cash, open_buy=buy, open_sell=sell)
        value = self.value
        if value['first'] is None:
            value['first'] = point
        if value['last'] is not None:
            value['max_gap_seconds'] = max(value['max_gap_seconds'], q['time'] - value['last']['quote']['time'])
        value['last'] = point
        value['count'] += 1
        for key, direction in (('peak', 1), ('max', 1), ('min', -1)):
            if value[key] is None or direction * equity > direction * value[key]['equity']:
                value[key] = point
        drawdown = value['peak']['equity'] - equity
        if drawdown > value['max_drawdown']:
            value['max_drawdown'] = drawdown
            value['drawdown_peak'] = value['peak']
            value['drawdown_trough'] = point


def compare_tree(actual, expected, audit: Audit, label: str) -> None:
    """
    機能: 保存タグ集合も含め全階層の型と値を比較する。
    引数: actual/expected(any)、audit(Audit)、label(str)は比較対象。
    返り値: None。不一致はValueError。
    """
    if isinstance(expected, dict):
        audit.need(type(actual) is dict and set(actual) == set(expected), label + ':タグ集合')
        for key in expected:
            compare_tree(actual[key], expected[key], audit, label + '/' + key)
    elif isinstance(expected, list):
        audit.need(type(actual) is list and len(actual) == len(expected), label + ':長さ')
        for index, value in enumerate(expected):
            compare_tree(actual[index], value, audit, label + '/' + str(index))
    else:
        if finite(expected):
            audit.need(finite(actual), label + ':有限数型')
        else:
            audit.need(type(actual) is type(expected), label + ':型')
        audit.equal(actual, expected, label)


# ----------------------------------------
def empty_event(at: float, method: str, phase: str, kind: str, q: dict, **fields) -> dict:
    """
    機能: Source作用の全公開タグを初期化する。
    引数: at(float)、method/phase/kind(str)、q(dict)、fields(dict)は出典と作用。
    返り値: dictは0作用を省略しない記録。
    """
    event = dict(at=at, phase=phase, method=method, kind=kind, signal_id='',
                 execution_id='', hold_id='', notice_id='', quote=copy.deepcopy(q), side=0,
                 quantity=0, before=0, actual_pending_before=0, actual_new_cancelled=0,
                 actual_free_before=0, actual_exit_requested=0, actual_free_after=0,
                 actual_accepted=0, available=0, order_id='', reason='')
    event.update(fields)
    return event


class ActorPath:
    """保存されたNative通知と全受理原行から実口座の監査期待値を作る。"""

    def __init__(self, actual: dict, audit: Audit):
        """
        機能: 12設定のうち一口座の監査状態を初期化する。
        引数: actual(dict)、audit(Audit)は保存結果と検査器。
        返り値: None。市場又はSourceの判断を生成しない。
        """
        self.actual, self.audit = actual, audit
        self.config, self.session = actual['config'], actual['session']
        audit.need(type(actual['finished']) is bool and type(actual['complete']) is bool and type(actual['failure']) is str, 'Actor終了型')
        cfg = self.config
        audit.need(cfg['policy'] in ('S0', 'P0', 'P1') and finite(cfg['slip_pts']) and cfg['slip_pts'] in (0, 5)
                   and type(cfg['delay_seconds']) is int and cfg['delay_seconds'] in (0, 1), 'Actor固定設定')
        self.key = f"{cfg['policy']}_C{cfg['slip_pts']:g}_D{cfg['delay_seconds']}"
        audit.equal(actual['key'], self.key, 'Actor保存key')
        self.side_cost = 38.5 + cfg['slip_pts'] * 100
        self.cost = 77 + 2 * cfg['slip_pts'] * 100
        self.orders, self.fills, self.positions, self.events = [], [], {}, []
        self.sources, self.holds, self.entry_sources, self.actual_holds = {}, {}, {}, {}
        self.cash, self.account = 0.0, AccountMarks()
        audit.equal(set(actual['metrics']), METRIC_FIELDS, 'Actor計数タグ集合')
        self.metrics = {k: 0 for k in actual['metrics']}
        self.source_executions = set()
        self.last, self.last_event = None, 0.0
        self.rows, self.normal_rows = 0, 0

    def count(self, key: str, quantity: int = 1) -> None:
        """
        機能: 公開計数名を未知補完せず増加させる。
        引数: key(str)、quantity(int)は計数と増分。
        返り値: None。未知タグはKeyError。
        """
        self.metrics[key] += quantity

    def request(self, kind: str, side: int, quantity: int, source: dict, at: float,
                q: dict, reason: str, position=None, native_signal='', notice='', point=None) -> dict:
        """
        機能: 原通知又は当時床が要求する実注文を監査期待値へ追加する。
        引数: kind/reason/native_signal/notice(str)、side/quantity(int)、source/q/position/point(dict)、at(float)。
        返り値: dictは次の期待注文。ID採番は取消を含む受理順。
        """
        serial = len(self.orders) + 1
        prefix = self.session['id'] + '-' + self.key
        pid = position['id'] if position is not None else prefix + f'-P{serial:06d}'
        order = dict(id=prefix + f'-O{serial:06d}', kind=kind, side=side, quantity=quantity,
                     position_id=pid, source=copy.deepcopy(source),
                     source_hold_id=position['source_hold_id'] if position is not None else '',
                     native_close_signal_id=native_signal, native_close_notice_id=notice,
                     request_time=at, request_quote=copy.deepcopy(q), reason=reason,
                     status='pending', fill_id='', cancel_time=None, cancel_reason='',
                     protection_point=copy.deepcopy(point))
        self.orders.append(order)
        if position is not None:
            self.audit.need(0 < quantity <= position['quantity'] - position['reserved'], '返済未予約量')
            position['reserved'] += quantity
            self.count('source_exit_requests' if point is None else 'protection_exit_requests')
        else:
            self.count('entry_requests')
            self.count('entry_accepted_quantity', quantity)
        return order

    def cancel(self, source_key: tuple, at: float, reason: str) -> int:
        """
        機能: 対応する未取得newだけを取消す。
        引数: source_key(tuple)、at(float)、reason(str)は元出生と原因。
        返り値: intは取消枚数。既取得又は見送りは0。
        """
        index = self.entry_sources.get(source_key)
        if index is None or self.orders[index]['status'] != 'pending':
            return 0
        order = self.orders[index]
        order.update(status='cancelled', cancel_time=at, cancel_reason=reason)
        self.count('cancelled_entries')
        return order['quantity']

    def prepare(self, at: float, q: dict, batches: list, timer: bool) -> list:
        """
        機能: 保存Native通知を型/時計へbindし、取消と源Fillを先に反映する。
        引数: at(float)、q(dict)、batches(list)、timer(bool)は今回の公開配送。
        返り値: listは正式手法名とdelta。Sourceアルゴリズムは動かさない。
        """
        prepared, methods, filled, cancelled = [], set(), set(), set()
        for batch in batches:
            method = 'NK225_' + batch['method'].removeprefix('NK225_')
            self.audit.need(method not in methods, '重複Source手法')
            methods.add(method)
            delta = batch['delta']
            self.audit.equal(delta['at'], at, 'Source配送時計')
            self.audit.equal(delta['origin'], 'timer' if timer else 'quote', 'Source配送位相')
            if timer:
                self.audit.equal(delta['fills'], [], 'timerにFillなし')
            else:
                self.audit.equal(delta['source_line'], q['source_line'], 'Source物理行')
            prepared.append((method, delta))
            for f in delta['fills']:
                filled.add((method, f['fill']['SignalID']))
            for c in delta['cancellations']:
                key = (method, c['signal_id'])
                self.audit.need(key not in cancelled, '元取消重複')
                cancelled.add(key)
        self.audit.need(not filled & cancelled, '同原行源Fillと取消の競合')
        for method, delta in prepared:
            for record in delta['signals']:
                s = record['signal']
                self.audit.need(type(s['id']) is str and bool(s['id']) and
                    all(finite(s[k]) for k in ('time', 'risk', 'boundary')), '元Signal型と有限性')
                self.audit.need(s['action'] in ('new', 'close'), '元Signal種別')
                self.audit.equal((s['time'], record['at'], s['source_index']), (at, at, record['quote']['index']), '元Signal時計')
                self.audit.need(type(s['side']) is int and s['side'] in (1, -1) and type(s['quantity']) is int and 1 <= s['quantity'] <= 10, '元Signal量方向')
                if not timer:
                    compare_tree(record['quote'], q, self.audit, '元Signal当原行')
                else:
                    self.audit.need(s['action'] == 'close' and record['quote']['time'] <= at, 'timer新規未来拒否')
                    compare_tree(record['quote'], q, self.audit, 'timer源要求の直前受理気配')
                if s['action'] == 'new':
                    key = (method, s['id'])
                    self.audit.need(key not in self.sources, '源出生重複')
                    evidence = s['evidence']
                    if type(evidence) is str:
                        evidence = json.loads(evidence, parse_constant=BASE.bad_constant)
                    self.audit.need(type(evidence) is dict and evidence.get('method') == method, '出生Evidence手法')
                    self.audit.need(all(type(evidence.get(k)) is str and evidence[k] for k in ('kind', 'parent', 'source_id'))
                        and type(evidence.get('quantity_micro')) is int and evidence['quantity_micro'] > 0, '出生Evidence既知性')
                    identity = dict(method=method, signal_id=s['id'], kind=evidence['kind'], parent=evidence['parent'],
                                    source_id=evidence['source_id'], quantity_micro=evidence['quantity_micro'],
                                    birth_quantity=s['quantity'], birth_time=at, birth_quote=copy.deepcopy(record['quote']))
                    self.sources[key] = dict(signal=s, identity=identity, state='pending', hold='')
                    self.count('native_new_signals')
        for method, delta in prepared:
            for c in delta['cancellations']:
                compare_tree(c['quote'], q, self.audit, '元取消の当時気配')
                key = (method, c['signal_id'])
                source = self.sources[key]
                self.audit.equal(source['state'], 'pending', '取消は源未取得')
                source['state'] = 'cancelled'
                qty = self.cancel(key, at, '元Sourceの未取得new取消')
                self.events.append(empty_event(at, method, 'before_fill', 'cancel', c['quote'],
                    signal_id=c['signal_id'], side=source['signal']['side'], quantity=source['signal']['quantity'],
                    actual_new_cancelled=qty, reason=c['reason']))
                self.count('native_cancels')
        for method, delta in prepared:
            for record in delta['fills']:
                f = record['fill']
                key = (method, f['SignalID'])
                source = self.sources[key]
                signal = source['signal']
                self.audit.equal(source['state'], 'pending', '源Fill先行予約')
                compare_tree(record['quote'], q, self.audit, '源Fill原行')
                self.audit.need(quote_ok(q) and q['index'] > signal['source_index'] and q['time'] >= signal['time'], '源Fill適格')
                self.audit.equal(f['Price'], q['ask'] if signal['side'] > 0 else q['bid'], '源Fill価格')
                self.audit.equal(f['Quantity'], signal['quantity'], '源Fill数量')
                self.audit.equal((record['action'], record['side']), (signal['action'], signal['side']), '源Fill種別方向')
                self.audit.equal(f['Time'], q['time'], '源Fill時計')
                self.audit.equal(f['Fee'], 0, '源内部費用0')
                execution_key = (method, f['ExecutionID'])
                self.audit.need(f['ExecutionID'] and execution_key not in self.source_executions, '源Executionの一意')
                self.source_executions.add(execution_key)
                if signal['action'] == 'new':
                    source['hold'] = f['HoldID']
                    hk = (method, f['HoldID'])
                    self.audit.need(hk not in self.holds, '源Hold重複')
                    self.holds[hk] = dict(source_key=key, quantity=f['Quantity'], reserved=0, side=signal['side'])
                    kind = 'new_fill'
                    self.count('native_new_fills')
                else:
                    compare_tree(f['Closed'], signal['targets'], self.audit, '源返済Targets')
                    for target in signal['targets']:
                        hold = self.holds[(method, target['id'])]
                        qty = target['quantity']
                        self.audit.need(0 < qty <= min(hold['quantity'], hold['reserved']), '源返済所有予約')
                        hold['quantity'] -= qty
                        hold['reserved'] -= qty
                    kind = 'close_fill'
                    self.count('native_close_fills')
                source['state'] = 'filled'
                self.events.append(empty_event(at, method, 'native_fill', kind, q, signal_id=f['SignalID'],
                    execution_id=f['ExecutionID'], hold_id=f['HoldID'], side=record['side'], quantity=f['Quantity']))
        self.count('native_batches', len(prepared))
        return prepared

    def close_sources(self, at: float, prepared: list) -> None:
        """
        機能: 元Targetsと独立源残/予約からBeforeと実比例返済を検査する。
        引数: at(float)、prepared(list)は当時の元通知。
        返り値: None。未取得取消は次fillより前後の契約通りにだけ作用する。
        """
        for method, delta in prepared:
            notice_index = 0
            for record in delta['signals']:
                s = record['signal']
                if s['action'] != 'close':
                    continue
                key = (method, s['id'])
                self.audit.need(key not in self.sources, '元close再送')
                total = 0
                for target in s.get('targets', []):
                    hk = (method, target['id'])
                    hold = self.holds[hk]
                    before, qty = hold['quantity'] - hold['reserved'], target['quantity']
                    self.audit.need(0 < qty <= before, '元close未予約量')
                    self.audit.equal(s['side'], -hold['side'], '元close返済方向')
                    notice = dict(id=s['id'] + '|' + target['id'], reference_id=target['id'],
                                  before=before, quantity=qty, reason=s['reason'])
                    if delta['closes'] is not None:
                        self.audit.need(notice_index < len(delta['closes']), '元close通知欠落')
                        compare_tree(delta['closes'][notice_index], notice, self.audit, '元close独立Before')
                    notice_index += 1
                    index = self.entry_sources.get(hold['source_key'])
                    pending = self.orders[index]['quantity'] if index is not None and self.orders[index]['status'] == 'pending' else 0
                    cancelled = self.cancel(hold['source_key'], at, 'Source close前のActual未取得new全取消')
                    pid = self.actual_holds.get(hk)
                    free, requested, oid = 0, 0, ''
                    if pid is not None:
                        p = self.positions[pid]
                        free = p['quantity'] - p['reserved']
                        requested = (free * qty + before - 1) // before
                        if requested:
                            order = self.request('exit', -p['side'], requested, p['source'], at, record['quote'],
                                                 s['reason'], p, s['id'], notice['id'])
                            oid = order['id']
                    hold['reserved'] += qty
                    total += qty
                    self.count('native_close_notices')
                    self.events.append(empty_event(at, method, 'source_close', 'close_notice', record['quote'],
                        signal_id=s['id'], hold_id=target['id'], notice_id=notice['id'], side=s['side'], quantity=qty,
                        before=before, actual_pending_before=pending, actual_new_cancelled=cancelled,
                        actual_free_before=free, actual_exit_requested=requested, actual_free_after=free-requested,
                        order_id=oid, reason=s['reason']))
                self.audit.equal(total, s['quantity'], '元返済総量')
                self.sources[key] = dict(signal=s, state='pending', hold='')
            if delta['closes'] is not None:
                self.audit.equal(notice_index, len(delta['closes']), '元余剰close拒否')

    def accept_sources(self, at: float, prepared: list) -> None:
        """
        機能: 連続出生を片側予約込み10へ一度だけ写す。
        引数: at(float)、prepared(list)は当時元通知。
        返り値: None。0受理も消費し後で復活させない。
        """
        for method, delta in prepared:
            for record in delta['signals']:
                signal = record['signal']
                if signal['action'] != 'new':
                    continue
                key = (method, signal['id'])
                self.audit.need(key not in self.entry_sources, '実出生再参加拒否')
                side = signal['side']
                used = sum(p['quantity'] for p in self.positions.values() if p['side'] == side)
                used += sum(o['quantity'] for o in self.orders if o['kind'] == 'entry' and o['status'] == 'pending' and o['side'] == side)
                self.audit.need(0 <= used <= 10, '予約込み片側cap')
                free = 10 - used
                qty, reason = min(signal['quantity'], free), '元Source出生量を受理'
                if self.sources[key]['state'] == 'cancelled':
                    qty, reason = 0, 'Native取消済みの出生は復活しない'
                elif qty == 0:
                    reason = '片側上限に空きなし'
                    self.count('cap_rejected_entries')
                elif qty < signal['quantity']:
                    reason = '片側上限で出生量を制限'
                    self.count('cap_clipped_entries')
                index, oid = None, ''
                if qty:
                    index = len(self.orders)
                    oid = self.request('entry', side, qty, self.sources[key]['identity'], at, record['quote'], signal['reason'])['id']
                self.entry_sources[key] = index
                self.events.append(empty_event(at, method, 'native_new', 'new_signal', record['quote'],
                    signal_id=signal['id'], side=side, quantity=signal['quantity'], actual_accepted=qty,
                    available=free, order_id=oid, reason=reason))

    def lock_atr(self, p: dict, q: dict, atr: dict) -> None:
        """
        機能: 取得又は初回既知の幅と当時公開出典を一度だけ固定する。
        引数: p/q/atr(dict)は実玉・原行・独立5分ATR。
        返り値: None。未知0は幅0へ読み替えない。
        """
        if p['atr'] is not None or atr['value'] == 0:
            return
        self.audit.need(0 < atr['nominal'] <= atr['available'] <= q['time'], 'ATR公開未来拒否')
        p['atr'] = dict(value=atr['value'], available=atr['available'], nominal=atr['nominal'],
                        age_seconds=q['time']-atr['available'], width=5*math.ceil(2*atr['value']/5),
                        quote=copy.deepcopy(q), after_entry=q['index'] > p['entry_quote']['index'])

    def fill_pending(self, q: dict, atr: dict) -> None:
        """
        機能: 全正常行で最初のeligible予約を確定し、後の行への飛越しを拒否する。
        引数: q/atr(dict)は原行と独立公開幅。
        返り値: None。保存Fillは最後にこの期待列へ全文照合する。
        """
        if not quote_ok(q):
            return
        for order in self.orders:
            if order['status'] != 'pending' or q['index'] <= order['request_quote']['index'] or q['time'] < order['request_time'] + self.config['delay_seconds']:
                continue
            price = q['ask'] if order['side'] == 1 else q['bid']
            qty = order['quantity']
            fee, slip = qty*38.5, qty*self.config['slip_pts']*100
            fill = dict(id=order['id']+'-F', order_id=order['id'], position_id=order['position_id'],
                        action='new' if order['kind'] == 'entry' else 'close', side=order['side'], quantity=qty,
                        price=price, quote=copy.deepcopy(q), source=copy.deepcopy(order['source']), source_hold_id=order['source_hold_id'],
                        native_close_signal_id=order['native_close_signal_id'], native_close_notice_id=order['native_close_notice_id'],
                        reason=order['reason'], fee_yen=fee, slip_yen=slip, gross_yen=0.0, net_contribution_yen=0.0, allocations=[])
            if order['kind'] == 'entry':
                key = (order['source']['method'], order['source']['signal_id'])
                source = self.sources[key]
                self.audit.need(source['state'] == 'filled' and source['hold'], '実取得時の源Hold未公開')
                hk = (key[0], source['hold'])
                self.audit.need(hk not in self.actual_holds, '同出生再取得拒否')
                order['source_hold_id'] = source['hold']
                fill['source_hold_id'] = source['hold']
                p = dict(id=order['position_id'], entry_order_id=order['id'], source=copy.deepcopy(order['source']),
                         source_hold_id=source['hold'], side=order['side'], initial_quantity=qty, quantity=qty, reserved=0,
                         closed_quantity=0, entry_price=price, entry_quote=copy.deepcopy(q), closed_quote=None,
                         gross_yen=0.0, realized_net=0.0, peak_gain=0.0, has_mark=False,
                         protection_active=False, activation=None, floor_gain=None, floor_updated=None,
                         first_floor_hit=None, atr=None, marks=PositionMarks())
                self.lock_atr(p, q, atr)
                if p['atr'] is None:
                    self.count('atr_deferred_positions')
                self.positions[p['id']] = p
                self.actual_holds[hk] = p['id']
                self.count('entry_fills')
            else:
                p = self.positions[order['position_id']]
                self.audit.need(0 < qty <= min(p['quantity'], p['reserved']), '実返済量と予約')
                gross = p['side'] * (price-p['entry_price']) * qty * 100
                net = gross - 2*fee - 2*slip
                allocation = dict(position_id=p['id'], source_hold_id=p['source_hold_id'], quantity=qty,
                    entry_price=p['entry_price'], entry_quote=copy.deepcopy(p['entry_quote']), exit_price=price,
                    exit_quote=copy.deepcopy(q), gross_yen=gross, entry_fee_yen=fee, exit_fee_yen=fee,
                    entry_slip_yen=slip, exit_slip_yen=slip, net_yen=net)
                fill['allocations'] = [allocation]
                fill['gross_yen'] = gross
                p['quantity'] -= qty
                p['reserved'] -= qty
                p['closed_quantity'] += qty
                p['gross_yen'] += gross
                p['realized_net'] += net
                if p['quantity'] == 0:
                    p['closed_quote'] = copy.deepcopy(q)
                self.count('exit_fills')
                if order['protection_point'] is not None:
                    self.count('protection_exit_fills')
            fill['net_contribution_yen'] = fill['gross_yen'] - fee - slip
            self.cash += fill['net_contribution_yen']
            order.update(status='filled', fill_id=fill['id'])
            self.fills.append(fill)

    def mark(self, q: dict, phase: str, atr: dict) -> None:
        """
        機能: 全正常行のu/Wと床を更新し、after_sourceだけで保護を要求する。
        引数: q/atr(dict)、phase(str)は当時公開状態。
        返り値: None。予約残もfillまでは保有評価へ含む。
        """
        for p in self.positions.values():
            if p['quantity'] == 0:
                continue
            point = mtm_point(p, q, phase, self.cost)
            p['marks'].observe(point)
            gain = point['gain_points']
            if not p['has_mark'] or gain > p['peak_gain']:
                p['peak_gain'] = gain
            p['has_mark'] = True
            self.lock_atr(p, q, atr)
            if self.config['policy'] == 'S0':
                continue
            if not p['protection_active'] and point['unit_net'] > 0:
                p['protection_active'], p['activation'] = True, point
            if not p['protection_active']:
                continue
            minimum = 5*math.ceil(self.cost/100/5) if self.config['policy'] == 'P1' else 0.0
            floor = minimum
            if p['atr'] is not None:
                floor = max(floor, p['peak_gain']-p['atr']['width'])
            if p['floor_gain'] is not None:
                floor = max(floor, p['floor_gain'])
            if p['floor_gain'] is None or floor > p['floor_gain']:
                p['floor_gain'], p['floor_updated'] = floor, point
            if gain <= floor:
                if p['first_floor_hit'] is None:
                    p['first_floor_hit'] = point
                free = p['quantity'] - p['reserved']
                if phase == 'after_source' and free > 0:
                    reason = '費用回収床と固定2ATR追尾' if self.config['policy'] == 'P1' else '最低建値床と固定2ATR追尾'
                    self.request('exit', -p['side'], free, p['source'], q['time'], q, reason, p, point=point)
        self.account.observe(q, phase, self.cash, self.positions, self.side_cost)
        whole = sum(p['realized_net'] + (p['quantity'] *
            (p['side']*((q['bid'] if p['side'] == 1 else q['ask'])-p['entry_price'])*100-self.cost))
            for p in self.positions.values())
        self.audit.need(abs(whole-self.account.value['last']['equity']) <= 1e-7, '全HoldWと口座現金式の独立一致')

    def step(self, q: dict, batches: list, atr: dict) -> None:
        """
        機能: 一原行を公開された順序で全監査状態へ通す。
        引数: q/atr(dict)、batches(list)は独立原行/ATRと保存された元通知。
        返り値: None。新しい売買候補やSourceを計算しない。
        """
        validate_quote(q, self.audit, '全受理原行')
        self.audit.need(q['last'] > 0 and q['time'] >= self.last_event, '受理Lastと時計')
        if self.last is not None:
            self.audit.need(q['index'] == self.last['index']+1 and q['source_line'] > self.last['source_line'], '全受理Indexとline欠落')
        prepared = self.prepare(q['time'], q, batches, False)
        self.count('rows')
        self.rows += 1
        if quote_ok(q):
            self.normal_rows += 1
            self.mark(q, 'pre_fill', atr)
        else:
            self.count('bad_quote_rows')
        self.fill_pending(q, atr)
        self.close_sources(q['time'], prepared)
        self.accept_sources(q['time'], prepared)
        if quote_ok(q):
            self.mark(q, 'after_source', atr)
        self.last, self.last_event = q, q['time']

    def timer(self, at: float, batches: list) -> None:
        """
        機能: 古いquoteを更新せず元Force通知のみ反映する。
        引数: at(float)、batches(list)は元timerと保存通知。
        返り値: None。評価・ATRlock・実fillは0回。
        """
        self.audit.need(at >= self.last_event, 'timer逆行')
        prepared = self.prepare(at, self.last, batches, True)
        self.close_sources(at, prepared)
        self.count('timer_calls')
        self.last_event = at

    def finish(self) -> dict:
        """
        機能: 全経路から再構成した公開注文/玉/極値/総額を保存値へ結合する。
        引数: なし。
        返り値: dictは照合scopeと行数。残玉を架空決済しない。
        """
        positions = []
        for p in self.positions.values():
            p = copy.deepcopy(p)
            p['marks'] = p['marks'].value
            positions.append(p)
            for mark, metric in (('first_unit_positive', 'unit_positive_positions'), ('first_whole_positive', 'whole_positive_positions')):
                if p['marks'][mark] is not None:
                    self.count(metric)
            if p['protection_active']:
                self.count('protection_activated_positions')
            if p['quantity'] == 0 and p['realized_net'] < 0:
                if p['protection_active']:
                    self.count('activated_closed_negative')
                if p['marks']['first_unit_positive'] is not None:
                    self.count('unit_positive_closed_negative')
                if p['marks']['first_whole_positive'] is not None:
                    self.count('whole_positive_closed_negative')
        totals = dict(entry_quantity=0, close_quantity=0, open_buy=0, open_sell=0,
                      pending_buy=0, pending_sell=0, gross_yen=0.0, fee_yen=0.0, slip_yen=0.0,
                      gross_minus_fee_yen=0.0, net_yen=0.0, closed_net_yen=0.0, open_entry_costs_yen=0.0)
        for f in self.fills:
            totals['entry_quantity' if f['action'] == 'new' else 'close_quantity'] += f['quantity']
            for key in ('gross_yen', 'fee_yen', 'slip_yen'):
                totals[key] += f[key]
            totals['net_yen'] += f['net_contribution_yen']
        for p in positions:
            totals['open_buy' if p['side'] == 1 else 'open_sell'] += p['quantity']
            totals['closed_net_yen'] += p['realized_net']
            totals['open_entry_costs_yen'] += p['quantity'] * self.side_cost
        for o in self.orders:
            if o['kind'] == 'entry' and o['status'] == 'pending':
                totals['pending_buy' if o['side'] == 1 else 'pending_sell'] += o['quantity']
        totals['gross_minus_fee_yen'] = totals['gross_yen']-totals['fee_yen']
        for key, expected in (('orders', self.orders), ('fills', self.fills), ('positions', positions),
                              ('source_events', self.events), ('metrics', self.metrics),
                              ('totals', totals), ('account', self.account.value)):
            compare_tree(self.actual[key], expected, self.audit, self.key+'/'+key)
        complete = not any(o['status'] == 'pending' for o in self.orders) and not any(p['quantity'] for p in positions)
        self.audit.equal(self.actual['complete'], complete and self.actual['failure'] == '', self.key+':終了会計')
        if self.actual['finished']:
            self.audit.need(complete and not self.actual['failure'], self.key+':完了の実残')
            self.audit.need(not any(s['state'] == 'pending' for s in self.sources.values()), self.key+':完了の源注文残')
            self.audit.need(not any(h['quantity'] or h['reserved'] for h in self.holds.values()), self.key+':完了の源所有残')
        return dict(key=self.key, rows=self.rows, normal_rows=self.normal_rows,
                    positions=len(positions), orders=len(self.orders), fills=len(self.fills),
                    source_events=len(self.events), all_path_mtm=True)


# ----------------------------------------
class NativeTape:
    """保存Shadowの通知列を元の物理行/timerへ索引化する。Sourceは再生しない。"""

    def __init__(self, shadows: dict, session: str, audit: Audit):
        """
        機能: 源Signal/Fill/取消の全件を物理行又はtimerへ分類する。
        引数: shadows(dict)、session(str)、audit(Audit)は保存Shadowと場。
        返り値: None。CloseNoticeはTargetsと独立所有から別途復元する。
        """
        self.by_line, self.by_timer, self.audit = {}, {}, audit
        self.clock, self.session = BASE.session_clock(session), session
        expected = {'D164_15'} if session.endswith('_Day') else {'P164_06', 'U165_03'}
        audit.equal(set(shadows), expected, '保存Shadow集合')
        self.source_rows = {m: 0 for m in expected}
        for method, ledger in shadows.items():
            audit.equal(ledger['method'], 'NK225_' + method, '保存Shadow手法')
            audit.equal(ledger['session']['id'], session, '保存Shadow場')
            for name in ('signals', 'fills', 'cancellations'):
                for record in ledger[name]:
                    if name == 'signals':
                        at, q = record['at'], record['quote']
                        timer = record['origin'] == 'timer'
                        audit.need(record['origin'] in ('timer', 'quote'), 'Shadow通知位相')
                    elif name == 'fills':
                        q = record['quote']
                        at, timer = q['time'], False
                    else:
                        at, q = record['at'], record['quote']
                        timer = at != q['time']
                    target, key = (self.by_timer, at) if timer else (self.by_line, q['source_line'])
                    delta = target.setdefault(key, {}).setdefault(method,
                        dict(at=at, origin='timer' if timer else 'quote',
                             source_line=0 if timer else q['source_line'], signals=[], fills=[], cancellations=[], closes=None))
                    audit.equal(delta['at'], at, 'Shadow物理行の時計一意')
                    delta[name].append(record)

    def methods(self, at: float) -> list:
        """
        機能: 固定Native窓で現在生成済みの全手法を列挙する。
        引数: at(float)は価格又はForce時計。
        返り値: list[str]は生成順。PはForce後も継続配送する。
        """
        if self.session.endswith('_Day'):
            return ['D164_15']
        return ['P164_06'] + (['U165_03'] if at >= self.clock['us']+900 else [])

    def take(self, at: float, line=None) -> list:
        """
        機能: 当行又はtimerの保存通知を一回だけ取り出す。
        引数: at(float)、line(int又はNone)は原行又はtimer。
        返り値: list[dict]はNativeBatch。空通知も生成済手法について維持する。
        """
        timer = line is None
        records = (self.by_timer if timer else self.by_line).pop(at if timer else line, {})
        methods = self.methods(at)
        self.audit.need(set(records) <= set(methods), '生成前又は窓外Source通知')
        out = []
        for method in methods:
            delta = records.get(method, dict(at=at, origin='timer' if timer else 'quote',
                source_line=0 if timer else line, signals=[], fills=[], cancellations=[], closes=None))
            out.append(dict(method=method, delta=delta))
            if not timer:
                self.source_rows[method] += 1
        return out

    def finish(self) -> None:
        """
        機能: 原行又はtimerへ未結合の通知がないことを確認する。
        引数: なし。
        返り値: None。通知欠落はValueError。
        """
        self.audit.equal(self.by_line, {}, '原行へ未結合のShadow通知')
        self.audit.equal(self.by_timer, {}, 'timerへ未結合のShadow通知')


def inspection_paths(value: dict, rows, atr: ATRSeries, native: NativeTape, audit: Audit) -> list:
    """
    機能: 全12口座を同じ原行の一走査へ接続する。
    引数: value(dict)、rows(iterator)、atr(ATRSeries)、native(NativeTape)、audit(Audit)は保存値と独立源。
    返り値: list[dict]は全口座照合範囲。毎原行MTMの保存複製は作らない。
    """
    keys = {f'{p}_C{c}_D{d}' for p in ('S0', 'P0', 'P1') for c in (0, 5) for d in (0, 1)}
    audit.equal(set(value['books']), keys, '12Actor集合')
    actors = [ActorPath(value['books'][key], audit) for key in sorted(keys)]
    clock = native.clock
    timers = sorted([clock['force']] + ([clock['us']-900] if clock['us'] else []))
    ti = 0
    for q in rows:
        while ti < len(timers) and timers[ti] <= q['time']:
            at = timers[ti]
            batches = native.take(at)
            for actor in actors:
                actor.timer(at, batches)
            ti += 1
        batches, width = native.take(q['time'], q['source_line']), atr.asof(q['time'])
        for actor in actors:
            actor.step(q, batches, width)
    while ti < len(timers):
        at = timers[ti]
        batches = native.take(at)
        for actor in actors:
            actor.timer(at, batches)
        ti += 1
    native.finish()
    compare_tree(value['source_rows'], native.source_rows, audit, '全Source受理行数')
    return [actor.finish() for actor in actors]


def observation_quote(observation: dict, line: int) -> tuple:
    """
    機能: API人工のGo Observationを気配と公開ATR値へ射影する。
    引数: observation(dict)、line(int)は手製公開API入力。
    返り値: tuple[dict,dict]は気配と手製ATR。原板源ATRの証明には使わない。
    """
    q = dict(time=observation['Time'], index=observation['Index'], source_line=line,
             last=observation['Last'], bid=observation['Bid'], ask=observation['Ask'], quote_ok=observation['QuoteOK'])
    e01 = observation['E01']
    atr = dict(value=observation['ATR'], available=e01['atr_available'], nominal=e01['atr_nominal'])
    if not all(finite(v) and v >= 0 for v in atr.values()):
        raise ValueError('API人工ATR非有限又は負値')
    if atr['value'] and not 0 < atr['nominal'] <= atr['available'] <= q['time']:
        raise ValueError('API人工ATR未来')
    return q, atr


def inspect_fixture(value: dict) -> dict:
    """
    機能: GoMarshal人工の保存Actorと全入力列を接続する。
    引数: value(dict)はbooksとcallsを持つ人工fixture。
    返り値: dictは全経路照合結果。Source自然発生/源ATR計算は証明しない。
    """
    audit = Audit()
    books = value.get('books', value.get('actors'))
    audit.need(type(books) is dict and len(books) == 12, '人工12Actor集合')
    actors = [ActorPath(book, audit) for book in books.values()]
    if 'calls' in value:
        calls = value['calls']
    else:
        calls, timers, ti = [], value['timers'], 0
        for step in value['steps']:
            while ti < len(timers) and timers[ti]['at'] <= step['observation']['Time']:
                calls.append(dict(timers[ti], kind='timer'))
                ti += 1
            calls.append(dict(step, kind='quote'))
        calls += [dict(row, kind='timer') for row in timers[ti:]]
    for call in calls:
        if call['kind'] == 'timer':
            for actor in actors:
                actor.timer(call['at'], call['batches'])
        elif call['kind'] == 'quote':
            q, atr = observation_quote(call['observation'], call['source_line'])
            for actor in actors:
                actor.step(q, call['batches'], atr)
        else:
            raise ValueError('人工呼出種別不正')
    details = [actor.finish() for actor in actors]
    return dict(成功=True, scope='Go公開API人工・全受理行MTM/注文/配賦/源通知作用。源ATR/自然Source生成は未計測',
                照合項目数=audit.checks, 会計数=len(details), details=details)


def inspect_one(task: tuple) -> dict:
    """
    機能: 明示許可後の一場について原板・固定足・保存口座を一走査で照合する。
    引数: task(tuple)は保存Path、InputSession、source_root。
    返り値: dictは全12Actorと原入力前後指紋。Source再運転は行わない。
    """
    result_path, input_session, source_root = task
    result_path, source_root = Path(result_path), Path(source_root)
    session = input_session['id']
    files = input_session['files']
    raw_path, csv_path = (source_root/files[k]['path'] for k in ('NK225_book', 'NK225_candle_300'))
    paths = [result_path, raw_path, csv_path, Path(__file__), BASE_PATH]
    before = {str(p): digest(p) for p in paths}
    for k, path in (('NK225_book', raw_path), ('NK225_candle_300', csv_path)):
        if before[str(path)] != files[k]['sha256'] or path.stat().st_size != files[k]['size']:
            raise ValueError('固定原入力SHA又はsize差:' + k)
    value, audit = load(result_path), Audit()
    audit.equal(value['session'], session, '保存場')
    audit.equal(value['contract'], input_session['contract'], '保存限月')
    audit.need('2026-09-21' <= session[:10] <= '2026-10-27', '既使用期間限定')
    config = value['feature_config']
    audit.need(config['atr_period'] == 12 and config['atr_min_bars'] == 3 and config['candle_delay_seconds'] == 60, '固定源ATR設定')
    clock = BASE.session_clock(session)
    audit.need(value['shadow_match']['all'] is True and all(v is True for v in value['shadow_match']['methods'].values()), '固定93Shadow比較の保存証拠')
    audit.equal(set(value['shadow_match']['methods']), set(value['shadows']), '固定93比較の全Source集合')
    expected_session = dict(id=session, kind=session.split('_')[1], start=clock['start'], end=clock['end'],
        force_close=clock['force'], us_open=clock['us'], extra_at=clock['us']+1800 if clock['us'] else clock['start']+225*60)
    for key, actor in value['books'].items():
        compare_tree(actor['session'], expected_session, audit, key+':場時計')
        audit.need(actor['finished'] is True and actor['complete'] is True and actor['failure'] == '', key+':正式完了')
    atr = ATRSeries(candles_from_csv(csv_path, session), clock['start'])
    native = NativeTape(value['shadows'], session, audit)
    quality = {}
    details = inspection_paths(value, walk_raw(raw_path, session, quality), atr, native, audit)
    compare_tree(value['quality']['NK225'], quality, audit, '全原板品質')
    audit.equal(quality['contracts'], [input_session['contract']], '原板限月')
    audit.need(all(digest(Path(p)) == h for p, h in before.items()), '入力code前後不変')
    return dict(session=session, 成功=True, 会計数=len(details), 照合項目数=audit.checks,
                不一致数=0, 全経路MTM=True, 入力前後不変=True, 入力SHA256=before,
                原板品質=quality, details=details)


def self_test() -> dict:
    """
    機能: 市場を開かずATR公開・u/W・両側・半円・DDを手計算照合する。
    引数: なし。
    返り値: dictは人工成功と照合件数。
    """
    audit = Audit()
    start = 1800000000.0
    candles = [dict(time=start + i * 300, open=1000, high=1010, low=990, close=1000) for i in range(4)]
    atr = ATRSeries(candles, start)
    audit.equal(atr.asof(start + 959)['value'], 0, '3足公開前')
    audit.equal(atr.asof(start + 960), dict(value=20, available=start + 960, nominal=start + 960), '3足等号公開')
    bars = copy.deepcopy(candles)
    bars[2]['received'] = start + 1000
    delayed = ATRSeries(bars, start)
    audit.equal(delayed.asof(start + 999)['value'], 0, '実受信前')
    audit.equal(delayed.asof(start + 1000)['value'], 20, '実受信後')
    seed_bars = copy.deepcopy(candles)
    seed_bars[0].update(high=1020, low=980)
    seed_atr = ATRSeries(seed_bars, start)
    audit.need(math.isclose(seed_atr.rows[2]['value'], 5300/144, rel_tol=0, abs_tol=1e-12), 'firstTR seedと指数重み手計算')
    audit.equal(5*math.ceil(2*seed_atr.rows[2]['value']/5), 75, '2ATR幅格子手計算')
    cases = []
    for side in (1, -1):
        mark = 1000 + side * 5
        q = dict(time=start + 1000, index=2, source_line=7, last=1000,
                 bid=mark if side == 1 else mark - 10, ask=mark + 10 if side == 1 else mark, quote_ok=True)
        p = dict(side=side, quantity=3, reserved=1, entry_price=1000, realized_net=-1500.5)
        point = mtm_point(p, q, 'pre_fill', 77)
        audit.equal(point['unit_net'], 423, '残単価手計算')
        audit.equal(point['whole_net'], -231.5, '全玉手計算')
        marks = PositionMarks()
        marks.observe(point)
        audit.need(marks.value['first_unit_positive'] is not None and marks.value['first_whole_positive'] is None, 'uとWの旗分離')
        p['realized_net'] = 2000
        adverse = copy.deepcopy(q)
        adverse['time'] += 2
        adverse['index'] += 1
        adverse['source_line'] += 1
        adverse['bid'] -= side * 10
        adverse['ask'] -= side * 10
        second = mtm_point(p, adverse, 'after_source', 77)
        audit.equal(second['unit_net'], -577, '逆行単価')
        audit.equal(second['whole_net'], 269, '確定益を混ぜない')
        marks.observe(second)
        audit.equal(marks.value['first_unit_negative_after'], second, '旗後赤字出典')
        audit.equal(marks.value['unit_max'], point, '単価最大出典')
        account = AccountMarks()
        p['realized_net'] = 0
        p['quantity'] = 3
        account.observe(q, 'pre_fill', -115.5, {'p': p}, 38.5)
        account.observe(adverse, 'after_source', -115.5, {'p': p}, 38.5)
        audit.equal(account.value['first']['equity'], 1269, '口座評価半円')
        audit.equal(account.value['last']['equity'], -1731, '口座逆行評価')
        audit.equal(account.value['max_drawdown'], 3000, '同時保有DD')
        audit.equal(account.value['max_gap_seconds'], 2, '評価間隔')
        cases.append({'side': side, 'u': point['unit_net'], 'W': point['whole_net']})
    rejected = 0
    for mutate in ('非有限', '逆行', '未確定OHLC'):
        bad = copy.deepcopy(candles)
        if mutate == '非有限':
            bad[0]['high'] = float('nan')
        elif mutate == '逆行':
            bad[1]['time'] = bad[0]['time']
        else:
            bad[0]['low'] = 1001
        try:
            ATRSeries(bad, start)
        except ValueError:
            rejected += 1
    audit.equal(rejected, 3, 'ATR不正拒否')
    with tempfile.TemporaryDirectory(dir=Path(__file__).parent, prefix='原板人工_') as name:
        folder = Path(name)
        audit.need(folder.resolve().is_relative_to(Path(__file__).parent.resolve()), '人工一時先のworkspace内確認')
        session = '2026-09-21_Day'
        clock = BASE.session_clock(session)
        row_spec = [(None, 1000, 990, 1010), (-1, 1000, 990, 1010),
                    (0, 1000, 990, 1010), (0, 1000, 1000, 1000),
                    (1, 0, 990, 1010), (0, 1000, 990, 1010),
                    (2, 1000, 1020, 1010), (2, 1000, 990, 1010),
                    (clock['end']-clock['start'], 1000, 990, 1010),
                    (3, 1000, 990, 1010)]
        path = folder/'原板.jsonl.gz'
        with gzip.open(path, 'wt', encoding='utf-8') as stream:
            for offset, last, bid, ask in row_spec:
                row = dict(Symbol='人工NK', CurrentPrice=last)
                if offset is not None:
                    row['CurrentPriceTime'] = BASE.dt.datetime.fromtimestamp(clock['start']+offset, BASE.JST).isoformat()
                for side, price in (('Buy', bid), ('Sell', ask)):
                    for depth in range(1, 11):
                        row[side+str(depth)] = dict(Price=price, Qty=1)
                stream.write(json.dumps(row, ensure_ascii=False)+'\n')
        quality = {}
        all_rows = list(walk_raw(path, session, quality))
        fixed = BASE.scan_raw(path, session, set(range(1, 11)))
        compare_tree(quality, fixed['quality'], audit, '固定93scanner全文')
        compare_tree(all_rows, list(fixed['by_line'].values()), audit, '固定93全受理行同値')
        audit.equal([q['source_line'] for q in all_rows], [3, 4, 7, 8, 10], 'Last0/欠測/逆行の手計算採用')
        audit.equal([q['index'] for q in all_rows], [0, 1, 2, 3, 4], 'SourceIndex手計算')
        audit.equal([q['source_line'] for q in all_rows if quote_ok(q)], [3, 8, 10], '正常同秒後原行')
        audit.equal((quality['accepted'], quality['bad_last'], quality['bad_quote']), (6, 1, 2), '品質手計算')
        timer_cancel = dict(signal_id='人工未取得',at=clock['force'],quote=all_rows[0],reason='場末前')
        shadow = {'D164_15':dict(method='NK225_D164_15',session=dict(id=session),signals=[],fills=[],cancellations=[timer_cancel])}
        tape = NativeTape(shadow,session,audit)
        audit.equal(tape.take(all_rows[0]['time'],all_rows[0]['source_line'])[0]['delta']['cancellations'],[], '旧quoteのlineへtimer取消を混入しない')
        audit.equal(tape.take(clock['force'])[0]['delta']['cancellations'],[timer_cancel], '元timer時計へ取消を一度配送')
        tape.finish()
    return {'成功': True, 'scope': '基礎算術人工のみ・Go出力/原板接続は未実施',
            '照合項目数': audit.checks, '両側': cases, 'ATR破損拒否数': rejected}


def main() -> int:
    """
    機能: 明示人工又は別途許可された既使用場の読取監査を実行する。
    引数: --self-test/--run(bool)、--fixture/--input/--manifest/--out(Path)、--workers/--limit(int)。
    返り値: intは成功0、不整合1。
    """
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--self-test', action='store_true')
    mode.add_argument('--fixture', type=Path)
    mode.add_argument('--run', action='store_true')
    parser.add_argument('--input', type=Path)
    parser.add_argument('--manifest', type=Path)
    parser.add_argument('--workers', type=int, default=1)
    parser.add_argument('--limit', type=int)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        parser.error('証拠の上書きを拒否する')
    if not 1 <= args.workers <= 8:
        parser.error('workerは1..8')
    if args.run and (args.input is None or args.manifest is None):
        parser.error('実読取は--run --input --manifestの明示が必要')
    before = {str(BASE_PATH): digest(BASE_PATH), str(Path(__file__)): digest(Path(__file__))}
    try:
        if args.self_test:
            proof = self_test()
        elif args.fixture is not None:
            before[str(args.fixture)] = digest(args.fixture)
            proof = inspect_fixture(load(args.fixture))
        else:
            before[str(args.manifest)] = digest(args.manifest)
            if before[str(args.manifest)] != BASE.MANIFEST_SHA:
                raise ValueError('固定80入力台帳の指紋差')
            manifest = load(args.manifest)
            selected = [s for s in manifest['sessions'] if '2026-09-21' <= s['id'][:10] <= '2026-10-27']
            if len(selected) != 54 or len({s['id'] for s in selected}) != 54:
                raise ValueError('既使用54場の集合差')
            if args.limit is not None:
                if not 1 <= args.limit <= 54:
                    raise ValueError('limit範囲外')
                selected = selected[:args.limit]
            tasks = []
            for s in selected:
                p = args.input/(s['id']+'.json')
                if not p.is_file():
                    raise ValueError('保存場JSON欠落:' + str(p))
                tasks.append((str(p), s, manifest['source_root']))
            if args.workers == 1:
                details = [inspect_one(task) for task in tasks]
            else:
                with concurrent.futures.ProcessPoolExecutor(max_workers=args.workers) as pool:
                    details = list(pool.map(inspect_one, tasks))
            proof = dict(成功=all(x['成功'] for x in details), scope='既使用54場内・保存源通知と全原行の読取監査・新Source/売買生成なし',
                         セッション数=len(details), 会計数=sum(x['会計数'] for x in details),
                         照合項目数=sum(x['照合項目数'] for x in details), 不一致数=0, details=details)
        proof['入力前後不変'] = all(digest(Path(p)) == h for p, h in before.items())
        proof['コードSHA256'] = before
        proof['成功'] = proof['成功'] and proof['入力前後不変']
    except Exception as error:
        proof = {'成功': False, '不整合': str(error), 'コードSHA256': before}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(proof, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'成功': proof['成功'], 'out': str(args.out)}, ensure_ascii=False))
    return 0 if proof['成功'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
