"""元連続再現の保存Signal/FillをNK原板の物理行へ独立結合する。売買を再生しない。"""

import argparse
import bisect
import concurrent.futures
import datetime as dt
import gzip
import hashlib
import json
import math
from pathlib import Path
import re
import sys


ROOT = Path(__file__).resolve().parents[2]
CORE = ROOT / 'scripts/FAR元三手法のmini連続再現'
MANIFEST_SHA = 'b939bc91b33fd86e933534c3b991d844b8a0200a5f14710e1bd5004edc1aab42'
FEATURES = ROOT.parent / 'SessionTradeExecuter/internal/strategy/features.go'
JST = dt.timezone(dt.timedelta(hours=9))
QUOTE_FIELDS = {'time', 'index', 'source_line', 'last', 'bid', 'ask', 'quote_ok'}


def digest(path: Path) -> str:
    """
    機能: ファイル本文のSHA256を得る。
    引数: path(Path)は固定入力又は保存結果。
    返り値: strはSHA256。
    """
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def load(path: Path) -> dict:
    """
    機能: 非有限JSONを拒否して保存値を読む。
    引数: path(Path)はJSON正本。
    返り値: dictは保存値。非有限定数は例外。
    """
    return json.loads(path.read_text(encoding='utf-8-sig'), parse_constant=bad_constant)


def bad_constant(value: str) -> None:
    """
    機能: JSON仕様外のNaN/Infinityを拒否する。
    引数: value(str)は不正定数。
    返り値: None。常にValueError。
    """
    raise ValueError(f'非有限JSON:{value}')


def finite(value) -> bool:
    """
    機能: boolを数値へ混ぜず有限数だけを認める。
    引数: value(any)は検査値。
    返り値: boolは有限数なら真。
    """
    return type(value) in (int, float) and math.isfinite(value)


class Audit:
    """照合件数を記録し、欠測や不整合を成功へ補完しない。"""

    def __init__(self):
        """
        機能: 照合件数を初期化する。
        引数: なし。
        返り値: None。
        """
        self.checks = 0

    def need(self, condition: bool, message: str) -> None:
        """
        機能: 一項目を確認し不成立なら即時拒否する。
        引数: condition(bool)、message(str)は条件と原因。
        返り値: None。不一致はValueError。
        """
        self.checks += 1
        if not condition:
            raise ValueError(message)

    def equal(self, actual, expected, message: str) -> None:
        """
        機能: 保存値を比較しboolの数値への読み替えを拒否する。
        引数: actual/expected(any)、message(str)は比較値と原因。
        返り値: None。不一致はValueError。
        """
        valid = actual == expected
        if type(actual) is bool or type(expected) is bool:
            valid = valid and type(actual) is type(expected)
        self.need(valid, f'{message}:保存={actual!r}/期待={expected!r}')


def session_clock(session: str) -> dict:
    """
    機能: 固定54場の日付からJST場時計を作る。
    引数: session(str)はDay/Night場ID。
    返り値: dictはstart/end/force/us。対象期間の米国開始は夏時間09:30NY=22:30JST。
    """
    day, kind = session.split('_')
    base = dt.datetime.fromisoformat(day).replace(tzinfo=JST)
    if kind == 'Day':
        start, end, us = base + dt.timedelta(hours=8, minutes=45), base + dt.timedelta(hours=15, minutes=45), 0
    elif kind == 'Night':
        start, end = base + dt.timedelta(hours=17), base + dt.timedelta(days=1, hours=6)
        us = (base + dt.timedelta(hours=22, minutes=30)).timestamp()
    else:
        raise ValueError('未知の場種')
    return {'start': start.timestamp(), 'end': end.timestamp(), 'force': end.timestamp()-600, 'us': us}


def parse_clock(value) -> float | None:
    """
    機能: Go RFC3339Nanoと同じナノ秒整数→float変換で価格時計を読む。
    引数: value(any)はCurrentPriceTime。
    返り値: float又はNoneは価格時計又は配置不能。
    """
    if not isinstance(value, str):
        return None
    match = re.fullmatch(r'(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.(\d+))?(Z|[+-]\d{2}:\d{2})', value)
    if not match:
        return None
    try:
        base = dt.datetime.fromisoformat(match[1]+match[3].replace('Z', '+00:00'))
        nano = int((match[2] or '')[:9].ljust(9, '0'))
        return float(int(base.timestamp()) * 1_000_000_000 + nano) / 1e9
    except (ValueError, OverflowError):
        return None


def number(raw: dict, name: str) -> float:
    """
    機能: Goのfloat64 fieldと同じ欠落/nullの0を読む。
    引数: raw(dict)、name(str)は原行の数値field。
    返り値: floatは有限値。型破損は例外。
    """
    value = raw.get(name)
    if value is None:
        return 0.0
    if not finite(value):
        raise ValueError(f'原板数値が不正:{name}')
    return float(value)


def scan_raw(path: Path, session: str, needed: set[int]) -> dict:
    """
    機能: NK原板を1走査し、元loaderの採用・Features連番・正常後原行を独立復元する。
    引数: path(Path)、session(str)、needed(set[int])は原板・場・必要物理行。
    返り値: dictは必要気配、正常行索引、品質、Source受理時計。指標/Source戦略は計算しない。
    """
    clock = session_clock(session)
    quality = dict(lines=0, clock_missing=0, outside=0, backward=0, bad_last=0, bad_quote=0, accepted=0, contracts=[])
    codes, by_line, normal, source_times = set(), {}, [], []
    previous, feature_index = clock['start'], -1
    with gzip.open(path, 'rt', encoding='utf-8') as stream:
        for line, text in enumerate(stream, 1):
            quality['lines'] = line
            row = json.loads(text, parse_constant=bad_constant)
            if not isinstance(row, dict) or not isinstance(row.get('Symbol'), str):
                raise ValueError(f'原板Symbol不正:{line}')
            codes.add(row['Symbol'])
            at = parse_clock(row.get('CurrentPriceTime'))
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
            last = number(row, 'CurrentPrice')
            if last <= 0:
                quality['bad_last'] += 1
            bbo = {}
            for side in ('Buy', 'Sell'):
                for depth in range(1, 11):
                    if side+str(depth) not in row:
                        raise ValueError(f'板段欠測:{line}:{side}{depth}')
                    level = row[side+str(depth)]
                    if level is None:
                        level = {}
                    if not isinstance(level, dict):
                        raise ValueError(f'板段型不正:{line}')
                    price = number(level, 'Price')
                    number(level, 'Qty')
                    if depth == 1:
                        bbo[side] = price
            bid, ask = bbo['Buy'], bbo['Sell']
            good = 0 < bid < ask
            if not good:
                quality['bad_quote'] += 1
            quality['accepted'] += 1
            # rawNKseqはLast0も進むが、RootのOnBoard呼出はLast>0だけ。
            if last <= 0:
                continue
            feature_index += 1
            source_times.append(at)
            q = dict(time=at, index=feature_index, source_line=line, last=last, bid=bid, ask=ask, quote_ok=good)
            if line in needed:
                by_line[line] = q
            if good:
                normal.append((feature_index, at, line))
    quality['contracts'] = sorted(codes)
    return {'quality': quality, 'by_line': by_line, 'normal': normal, 'source_times': source_times}


def validate_stamp(q: dict, raw: dict, audit: Audit, label: str) -> None:
    """
    機能: 保存気配をFeatures対象の原板物理行へ全文結合する。
    引数: q/raw(dict)、audit(Audit)、label(str)は保存気配・原板索引・検査器・出典。
    返り値: None。欠測/型/連番/価格不一致は例外。
    """
    audit.need(isinstance(q, dict) and set(q) == QUOTE_FIELDS, label+':気配field')
    audit.need(type(q['index']) is int and q['index'] >= 0 and type(q['source_line']) is int and q['source_line'] > 0 and type(q['quote_ok']) is bool, label+':原行型')
    audit.need(all(finite(q[k]) for k in ('time', 'last', 'bid', 'ask')), label+':有限気配')
    expected = raw['by_line'].get(q['source_line'])
    audit.need(expected is not None, label+':Source受理原行欠測')
    audit.equal(q, expected, label+':物理行全文')


def needed_lines(value: dict) -> set[int]:
    """
    機能: 保存台帳の気配出典だけを抽出する。
    引数: value(dict)はNativeJSON一場。
    返り値: set[int]はSignal/Fill/取消/片/所有の物理行。
    """
    out = set()
    for book in value['books'].values():
        quotes = [x['quote'] for field in ('signals', 'fills', 'cancellations') for x in book[field]]
        quotes += [h['entry_quote'] for h in book['holds']]
        quotes += [a[k] for f in book['fills'] for a in f['allocations'] for k in ('entry_quote', 'exit_quote')]
        out.update(q['source_line'] for q in quotes)
    return out


def inspect_book(book: dict, key: str, session: str, raw: dict, audit: Audit) -> dict:
    """
    機能: 全要求の物理行と次正常約定/取消、所有別返済片を独立確認する。
    引数: book/raw(dict)、key/session(str)、audit(Audit)は一会計と原板索引。
    返り値: dictは短い件数。Source判断の再計算や新売買は行わない。
    """
    clock = session_clock(session)
    product, method = key.split('_', 1)
    audit.need(product in ('mini', 'micro'), key+':商品')
    audit.equal(book['method'], 'NK225_'+method, key+':手法')
    audit.need(book['finished'] is True and book['complete'] is True and book['failure'] == '' and book['pending'] == [], key+':終了完備')
    audit.equal(book['session']['id'], session, key+':場')
    for field, expected in [('start', clock['start']), ('end', clock['end']), ('force_close', clock['force']), ('us_open', clock['us'])]:
        audit.equal(book['session'][field], expected, key+':場時計:'+field)
    point, fee, cap = (100, 38.5, 10) if product == 'mini' else (10, 11, 100)
    audit.equal(book['config']['product'], 'NK225'+product, key+':商品型')
    for field, expected in [('cap', cap), ('point_value', point), ('fee_yen_per_side', fee), ('slippage_points', 5), ('large_tick', 10)]:
        audit.equal(book['config'][field], expected, key+':設定:'+field)
    signals, fills, cancels, owned = {}, {}, {}, {}
    normals = raw['normal']
    normal_indices = [r[0] for r in normals]
    for record in book['signals']:
        s, q = record['signal'], record['quote']
        label = key+':Signal:'+s['id']
        validate_stamp(q, raw, audit, label)
        audit.need(s['id'] not in signals and s['id'] != '', label+':一意ID')
        audit.need(type(s['quantity']) is int and s['quantity'] > 0 and type(s['side']) is int and s['side'] in (-1, 1) and s['action'] in ('new', 'close'), label+':量方向')
        audit.need(type(s['source_index']) is int and finite(s['time']) and finite(record['at']), label+':要求型')
        audit.equal(s['source_index'], q['index'], label+':Features出典')
        audit.equal(s['time'], record['at'], label+':要求時計')
        audit.need(record['origin'] in ('quote', 'timer'), label+':起源')
        if record['origin'] == 'quote':
            audit.equal(record['at'], q['time'], label+':当原行時計')
        else:
            audit.need(record['at'] >= q['time'] and record['at'] in {clock['force'], clock['us']-900}, label+':強制時計')
            audit.equal(s['action'], 'close', label+':timer返済のみ')
            latest = bisect.bisect_left(raw['source_times'], record['at'])-1
            audit.need(latest >= 0, label+':timer前原行欠測')
            audit.equal(q['index'], latest, label+':timer直前Source原行')
        signals[s['id']] = record
    for record in book['fills']:
        f, q = record['fill'], record['quote']
        label = key+':Fill:'+f['SignalID']
        validate_stamp(q, raw, audit, label)
        audit.need(type(f['Quantity']) is int and all(finite(f[k]) for k in ('Time', 'Price', 'Fee')), label+':実Fill型')
        audit.need(f['SignalID'] in signals and f['SignalID'] not in fills, label+':要求一回')
        s = signals[f['SignalID']]['signal']
        audit.need(q['quote_ok'] and 0 < q['bid'] < q['ask'], label+':正常BBO')
        audit.equal(record['action'], s['action'], label+':種別')
        audit.equal(record['side'], s['side'], label+':方向')
        audit.equal(f['Quantity'], s['quantity'], label+':全量')
        audit.equal(f['Time'], q['time'], label+':実時刻')
        audit.equal(f['Price'], q['ask'] if s['side'] > 0 else q['bid'], label+':実BBO価格')
        audit.equal(f['Fee'], 0, label+':元判断費用0')
        audit.need(q['index'] > s['source_index'] and q['time'] >= s['time'], label+':要求後')
        pos = bisect.bisect_right(normal_indices, s['source_index'])
        while pos < len(normals) and normals[pos][1] < s['time']:
            pos += 1
        audit.need(pos < len(normals), label+':次正常欠測')
        audit.equal((q['index'], q['time'], q['source_line']), normals[pos], label+':最初の正常後原行')
        audit.equal(record['fee_yen'], s['quantity']*fee, label+':外手数料')
        audit.equal(record['slippage_yen'], s['quantity']*5*point, label+':外滑り費用')
        if s['action'] == 'new':
            audit.need(f['HoldID'] != '' and f['HoldID'] not in owned and record['allocations'] == [] and not f['Closed'], label+':新規所有')
            owned[f['HoldID']] = {'fill': record, 'side': s['side'], 'remaining': f['Quantity']}
        else:
            audit.equal(f['HoldID'], '', label+':返済単一Hold空')
            audit.equal(f['Closed'], s.get('targets'), label+':元Targets')
            audit.equal([(a['hold_id'], a['quantity']) for a in record['allocations']], [(a['ID'] if 'ID' in a else a['id'], a['Quantity'] if 'Quantity' in a else a['quantity']) for a in f['Closed']], label+':所有片内訳')
            gross = 0
            for a in record['allocations']:
                hold = owned.get(a['hold_id'])
                audit.need(hold is not None and 0 < a['quantity'] <= hold['remaining'] and s['side'] == -hold['side'], label+':実所有残')
                entry = hold['fill']
                validate_stamp(a['entry_quote'], raw, audit, label+':片entry')
                validate_stamp(a['exit_quote'], raw, audit, label+':片exit')
                audit.equal(a['entry_quote'], entry['quote'], label+':片新規出典')
                audit.equal(a['exit_quote'], q, label+':片返済出典')
                audit.equal(a['entry_price'], entry['fill']['Price'], label+':片取得価格')
                audit.equal(a['exit_price'], f['Price'], label+':片返済価格')
                piece = hold['side']*(f['Price']-entry['fill']['Price'])*a['quantity']*point
                audit.equal(a['gross_yen'], piece, label+':原板粗益')
                audit.equal(a['net_yen'], piece-a['quantity']*(2*fee+10*point), label+':片往復費用')
                hold['remaining'] -= a['quantity']
                gross += piece
            audit.equal(record['gross_yen'], gross, label+':約定粗益')
        fills[f['SignalID']] = record
    for c in book['cancellations']:
        label = key+':取消:'+c['signal_id']
        validate_stamp(c['quote'], raw, audit, label)
        audit.need(c['signal_id'] in signals and c['signal_id'] not in fills and c['signal_id'] not in cancels, label+':未約定一回')
        s = signals[c['signal_id']]['signal']
        audit.need(s['action'] == 'new' and finite(c['at']) and c['at'] >= c['quote']['time'] and c['at'] >= s['time'], label+':新規取消時計')
        pos = bisect.bisect_right(normal_indices, s['source_index'])
        while pos < len(normals) and normals[pos][1] < s['time']:
            pos += 1
        if pos < len(normals):
            nxt = normals[pos]
            audit.need(c['at'] < nxt[1] or c['at'] == nxt[1] and c['quote']['index'] <= nxt[0], label+':先に約定できた原行の飛越し')
        cancels[c['signal_id']] = c
    audit.equal(set(signals), set(fills) | set(cancels), key+':全要求の最終処理')
    audit.need(all(h['remaining'] == 0 for h in owned.values()), key+':所有全返済')
    audit.equal([h['hold_id'] for h in book['holds']], list(owned), key+':全所有IDと取得順')
    for h in book['holds']:
        validate_stamp(h['entry_quote'], raw, audit, key+':所有entry')
        audit.need(h['hold_id'] in owned, key+':所有ID')
        entry = owned[h['hold_id']]['fill']
        audit.equal(h['entry_quote'], entry['quote'], key+':所有取得出典')
        audit.equal(h['entry_price'], entry['fill']['Price'], key+':所有取得価格')
        audit.equal(h['quantity'], 0, key+':最終残')
    audit.equal(len(book['holds']), len(owned), key+':全所有数')
    return {'key': key, 'signal': len(signals), 'fill': len(fills), 'cancel': len(cancels), 'hold': len(owned), 'allocation': sum(len(f['allocations']) for f in book['fills'])}


def inspect_one(args: tuple) -> dict:
    """
    機能: 一場のNativeJSONを元NK原板だけで監査する。
    引数: args(tuple)はsession、NativePath、InputSession、sourceRoot。
    返り値: dictは成功/件数/入力前後指紋又は未完了の原因。
    """
    session, result_path, input_session, source_root = args
    result_path, source_root = Path(result_path), Path(source_root)
    audit = Audit()
    before, raw_before = digest(result_path), None
    try:
        value = load(result_path)
        audit.equal(value['session'], session, 'Native場ID')
        expected_keys = {p+'_'+m for p in ('mini', 'micro') for m in (['D164_15'] if session.endswith('_Day') else ['P164_06', 'U165_03'])}
        audit.equal(set(value['books']), expected_keys, '全商品手法会計')
        item = input_session['files']['NK225_book']
        path = source_root / item['path']
        raw_before = digest(path)
        audit.equal(path.stat().st_size, item['size'], '原板bytes')
        audit.equal(raw_before, item['sha256'], '原板SHA')
        raw = scan_raw(path, session, needed_lines(value))
        audit.equal(raw['quality'], value['quality']['NK225'], 'NK品質全field')
        audit.equal(raw['quality']['contracts'], [input_session['contract']], '限月')
        details = []
        for key in sorted(value['books']):
            details.append(inspect_book(value['books'][key], key, session, raw, audit))
            birth = session_clock(session)['us']+900 if key.endswith('U165_03') else session_clock(session)['start']
            expected_rows = len(raw['source_times'])-bisect.bisect_left(raw['source_times'], birth)
            audit.equal(value['source_rows'][key], expected_rows, key+':全Source行数')
            audit.need(expected_rows > 0, key+':Source未計測禁止')
        audit.equal(digest(path), raw_before, '原板前後不変')
        audit.equal(digest(result_path), before, 'Native前後不変')
        return {'session': session, '成功': True, '会計数': len(details), '照合項目数': audit.checks, '不一致数': 0, 'NativeSHA256': before, '原板SHA256': raw_before, '入力前後不変': True, 'Source行数': len(raw['source_times']), 'details': details}
    except Exception as exc:
        return {'session': session, '成功': False, '照合項目数': audit.checks, '不一致数': 1, 'NativeSHA256': before, '原板SHA256': raw_before, 'error': f'{type(exc).__name__}:{exc}'}


def main() -> int:
    """
    機能: 完成runの固定54場prefixを監査し、コード/全入力/Native指紋を新規保存する。
    引数: --results/--manifest/--out(Path)、--core-proof(Path)、--limit/--workers(int)。
    返り値: intは全差0なら0、不完了・不一致は1。既存出力は上書きしない。
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--results', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--core-proof', type=Path, default=ROOT/'work/93元連続再現/入力前_正式54場.json')
    parser.add_argument('--limit', type=int, default=54)
    parser.add_argument('--workers', type=int, default=4)
    args = parser.parse_args()
    if args.out.exists():
        raise FileExistsError(args.out)
    proof = {'成功': False, '処理完了': False, '市場再生': 0, 'Source指標再計算': 0, 'scope': 'NativeのNK気配/要求/次正常Fill/取消/所有別片を原板1走査で監査。元判断の妥当性/mini固有板は未検証。'}
    try:
        if not 1 <= args.limit <= 54 or not 1 <= args.workers <= 16:
            raise ValueError('固定54場prefix/worker範囲が不正')
        if digest(args.manifest) != MANIFEST_SHA:
            raise ValueError('固定80台帳SHAが不一致')
        manifest = load(args.manifest)
        all_sessions = [s for s in manifest['sessions'] if '2026-09-21' <= s['id'].split('_')[0] <= '2026-10-27']
        if len(all_sessions) != 54:
            raise ValueError('元54場が揃わない')
        selected = all_sessions[:args.limit]
        completion_path = args.results/'完了.json'
        completion_before = digest(completion_path)
        completion = load(completion_path)
        if completion['場数'] != args.limit or completion['台帳SHA256'] != MANIFEST_SHA or (args.results/'不完了.json').exists():
            raise ValueError('Native runが指定prefixで完了していない')
        expected_names = {s['id']+'.json' for s in selected}
        if set(completion['結果SHA256']) != expected_names:
            raise ValueError('Native完了指紋の場集合不一致')
        result_hashes = {name: digest(args.results/name) for name in expected_names}
        if result_hashes != completion['結果SHA256']:
            raise ValueError('Native結果指紋不一致')
        core_proof = load(args.core_proof)
        core_proof_before = digest(args.core_proof)
        code = core_proof['コード']
        if len(code) != 11 or any(Path(p).resolve().parent != CORE and CORE not in Path(p).resolve().parents for p in code):
            raise ValueError('Root固定core11の範囲不一致')
        if any(digest(Path(p)) != v for p, v in code.items()):
            raise ValueError('固定core本文不一致')
        pure = {p: digest(Path(manifest['純戦略repo'])/p) for p in manifest['純戦略SHA256']}
        if pure != manifest['純戦略SHA256'] or len(pure) != 43:
            raise ValueError('純戦略43本文不一致')
        raw_hashes = {}
        for session in selected:
            for item in session['files'].values():
                path = Path(manifest['source_root'])/item['path']
                if path.stat().st_size != item['size'] or digest(path) != item['sha256']:
                    raise ValueError(f'固定入力不一致:{path}')
                raw_hashes[str(path)] = item['sha256']
        audit_code = {str(Path(__file__).resolve()): digest(Path(__file__)), str(FEATURES): digest(FEATURES)}
        tasks = [(s['id'], args.results/(s['id']+'.json'), s, manifest['source_root']) for s in selected]
        if args.workers == 1:
            details = [inspect_one(t) for t in tasks]
        else:
            with concurrent.futures.ProcessPoolExecutor(max_workers=args.workers) as pool:
                details = list(pool.map(inspect_one, tasks))
        unchanged = all(digest(Path(p)) == v for p, v in {**code, **raw_hashes, **audit_code}.items())
        unchanged = unchanged and result_hashes == {name: digest(args.results/name) for name in expected_names}
        unchanged = unchanged and digest(args.manifest) == MANIFEST_SHA and pure == {p: digest(Path(manifest['純戦略repo'])/p) for p in pure}
        unchanged = unchanged and digest(completion_path) == completion_before and digest(args.core_proof) == core_proof_before
        native_after = {name: digest(args.results/name) for name in expected_names}
        input_after = {p: digest(Path(p)) for p in raw_hashes}
        code_after = {p: digest(Path(p)) for p in code}
        audit_after = {p: digest(Path(p)) for p in audit_code}
        unchanged = unchanged and native_after == result_hashes and input_after == raw_hashes and code_after == code and audit_after == audit_code
        success = unchanged and all(d['成功'] for d in details)
        proof.update(成功=success, 処理完了=True, 場数=len(details), 会計数=sum(d.get('会計数', 0) for d in details), 照合項目数=sum(d['照合項目数'] for d in details), 不一致数=sum(d['不一致数'] for d in details), 入力前後不変=unchanged, 詳細=details,
                     台帳SHA256=MANIFEST_SHA, Native完了SHA256=digest(completion_path), NativeSHA256=result_hashes, 原入力SHA256=raw_hashes, core11SHA256=code, 監査コードSHA256=audit_code, 純戦略SHA256=pure, 固定証拠SHA256=digest(args.core_proof), 限定='元54場全体' if args.limit == 54 else f'固定54場の先頭{args.limit}場のみ',
                     Index定義='Features市場別Counts。NativeはLast<=0をOnBoardへ渡さないので、場内/時計採用/非逆行でLast>0のNK行数−1。raw受理行（Last0含む）連番やTOPIX合算とは異なる。')
        proof.update(Native前後SHA256={k: {'before': v, 'after': native_after[k]} for k, v in result_hashes.items()}, 原入力前後SHA256={k: {'before': v, 'after': input_after[k]} for k, v in raw_hashes.items()}, core11前後SHA256={k: {'before': v, 'after': code_after[k]} for k, v in code.items()}, 監査コード前後SHA256={k: {'before': v, 'after': audit_after[k]} for k, v in audit_code.items()}, Native完了前後SHA256={'before': completion_before, 'after': digest(completion_path)}, 固定証拠前後SHA256={'before': core_proof_before, 'after': digest(args.core_proof)})
    except Exception as exc:
        proof.update(error=f'{type(exc).__name__}:{exc}', 不一致数=1)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(proof, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    print(json.dumps({k: proof.get(k) for k in ('成功', '処理完了', '場数', '会計数', '照合項目数', '不一致数', 'error')}, ensure_ascii=False))
    return 0 if proof['成功'] else 1


if __name__ == '__main__':
    sys.exit(main())
