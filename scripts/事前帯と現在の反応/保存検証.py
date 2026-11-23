"""75の帯・価格反応・即時運用を、新主処理に依存せず保存値から監査する。"""

import argparse
from collections import Counter, defaultdict
from copy import deepcopy
from datetime import datetime
from decimal import Decimal
import hashlib
import importlib.util
import json
from pathlib import Path
import statistics
import sys
from urllib.parse import urlencode, urljoin


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
STUDY = ROOT / 'study/00075_事前帯の外保持と内回帰を判別'
WORK = ROOT / 'work/事前帯と現在の反応/00075'
OLD = ROOT / 'study/00074_内包足の偽突破確認と局面切替'
OLDWORK = ROOT / 'work/内包足の偽突破と局面切替/00074'
LEDGER = OLDWORK.parent / '74完了記録.json'
LEDGER_SHA = '7f7c42a9ca883e426bda8a92ff473e99ab9ba19d3bd42dba4c6fd2d199e9c686'
SOURCE_STUDY = ROOT / 'study/00073_直近の集中と方向効率を組み合わせる'
SOURCE_WORK = ROOT / 'work/直近進行の集中と効率/00073'
FRAMES = ROOT / 'work/一目基準線/00028/全指標.jsonl.gz'
FRAME_SHA = 'db5afa37a5cd7de91a4f649b8f9cbcc21f301cb73e9ca4930d09cc24234cd6fa'
POLICIES = ('O0', 'P0', 'P1')
ALL_POLICIES = ('Q0', *POLICIES)
PERIODS = ('学習', '条件選択', '後続検査')
PURE = ('scheduled', 'time', 'line', 'side', 'role', 'atr', 'D', 'reason', 'ready', 'slot_id')
BINDING = ('session', 'slot_id', 'scheduled', 'time', 'line')


# ----------------------------------------
def load_fixed(path: Path, name: str, digest: str | None = None):
    """固定監査又は独立入力を固有名で読み、旧大域値を変更しない。

    引数: path(Path)はコード、name(str)は固有名、digest(str|None)は固定SHA。
    返り値: ModuleTypeは読込結果。正式経路から新I/主/Engineを読まない。
    """
    if digest is not None and hashlib.sha256(path.read_bytes()).hexdigest() != digest:
        raise ValueError('監査依存の変更:' + path.name)
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


R74 = load_fixed(ROOT / 'scripts/内包足の偽突破と局面切替/保存検証.py', '事前帯75の固定74監査',
    '460d7a89cb92921e34db3d3c4c5f26a9a22296f18c7e4a2fb245238f433819f6')
INPUT = load_fixed(HERE / '入力監査.py', '事前帯75の独立入力',
    'df6ee929f037fc25e5bdbce0793992c974878de3123c77b6c83052e4fc87318d')
R69, R68, R55, P, A = R74.R69, R74.R68, R74.R55, R74.P, R74.A


def reference(policy: str, session: str, bands: dict) -> dict:
    """既知のOR又は直前収録帯だけを、独立に当場向け識別へ装飾する。

    引数: policy/session(str)は政策と当場、bands(dict)は別算済み帯。
    返り値: dictは入力監査用参照帯。現在全期間帯を当場判断へ渡さない。
    """
    if policy == 'O0':
        value = deepcopy(bands['opening'][session])
        value.update(id='OR30:' + session, session=session, current_session=session,
            reference_type='OR30', prior_gap_seconds=None, reference_available=True)
        return value
    if policy not in ('P0', 'P1'):
        raise ValueError('未知の帯政策')
    prior = bands['previous'][session]
    if not prior['ready']:
        return {'ready': False, 'reason': prior['reason'], 'id': 'FULL:なし:' + session,
            'reference_available': False, 'published': False, 'current_session': session,
            'session': None, 'reference_type': 'FULL', 'prior_gap_seconds': None,
            'begin': None, 'end': None, 'publication': 'timer', 'publication_key': None,
            'open': None, 'high': None, 'low': None, 'close': None, 'sources': None, 'coverage': None}
    previous = prior['prior_session']
    value = deepcopy(bands['full'][previous])
    value.update(id='FULL:' + previous, session=previous, current_session=session,
        reference_type='FULL', prior_gap_seconds=prior['gap_seconds'], reference_available=True)
    return value


def read_sources(source, audit) -> dict:
    """固定28のSOURCE12だけを場別prefixへ射影する。

    引数: source/auditは固定読取補助と比較記録。
    返り値: dict[str,list[dict]]は当場3分足。指標・教師を再計算しない。
    """
    audit.check('固定SOURCE銀行SHA', source.sha(FRAMES), FRAME_SHA)
    fields = ('index', 'minutes', 'start', 'end', 'confirm', 'confirm_line', 'publish', 'missing', 'open', 'high', 'low', 'close')
    result = defaultdict(list)
    for row in source.json_rows(FRAMES):
        if row['minutes'] == 3:
            result[row['場']].append({'session': row['場'], **{name: row[name] for name in fields}})
    return dict(result)


def read_banks(identities: set, source, audit) -> tuple:
    """旧55/69の成功測定から必要方向と当時気配だけを縮約する。

    引数: identities(set[str])は評価予定ID、source/auditは固定読取と記録。
    返り値: tuple[dict,dict]は測定索引と判断気配。旧未準備operation=Noneも保持する。
    """
    pins = source.read(SOURCE_STUDY / '固定.json')['ファイルSHA256']
    banks, quotes = {}, {}
    for kind, path in (('即時', R74.IMMEDIATE), ('条件', R74.CONDITIONAL)):
        audit.check('旧独立測定SHA:' + kind, source.sha(path), pins[path.relative_to(ROOT).as_posix()])
        bank = {}
        for row in source.json_rows(path):
            identity = row['slot_id']
            if identity not in identities:
                continue
            key = identity, row['side']
            if key in bank:
                raise ValueError('旧測定の方向重複')
            operation = row['operation']
            pure = row if kind == '即時' else operation['conditions'][identity]['slot']
            binding = {name: row[name] for name in (*BINDING, 'side')}
            binding.update({name: pure[name] for name in ('ready', 'atr', 'D')})
            bank[key] = {'barrier': row['barrier'], 'closed': deepcopy(operation['closed']) if operation is not None else None,
                'binding': binding, 'observed': operation['conditions'][identity]['last_observation_time'] if kind == '条件' else None}
            if kind == '即時':
                quote = row['decision_bbo']
                if identity in quotes:
                    audit.check('旧55両方向の判断気配同値', INPUT.canonical(quotes[identity]), INPUT.canonical(quote))
                else:
                    quotes[identity] = deepcopy(quote)
        audit.check('旧測定の全予定両方向:' + kind, set(bank), {(identity, side) for identity in identities for side in (1, -1)})
        banks[kind] = bank
    audit.check('旧55判断気配の全予定集合', set(quotes), identities)
    return banks, quotes


def close_sum(rows: list[dict], fee: int) -> float:
    """完結取引の保存十進額を合算する。

    引数: rows(list[dict])は完結、fee(int)は0/5/10。
    返り値: floatは観測額。品質注意と未解消を確定0へ補完しない。
    """
    return float(sum((Decimal(str(row['pnl' + str(fee)])) for row in rows), Decimal(0)))


def expected_summary(accounts: dict, labels: dict, slots: dict, observations: dict, source, summary) -> dict:
    """固定純集計と別の集合走査で、全主表・形成・比較を構成する。

    引数: accounts/labels/slots/observations(dict)は監査済み値、source/summaryは固定純監査。
    返り値: dictは独立した五集計。新主summarizeや新予測を呼ばない。
    """
    result = {name: {policy: {} for policy in ALL_POLICIES} for name in ('候補', '利益保護', '技法被覆', '形成別')}
    result['比較'] = {}
    for policy in ALL_POLICIES:
        for period in PERIODS:
            aa = [account for account in accounts[policy] if source.span(account['session']) == period]
            cc = [row for account in aa for row in account['closed']]
            ll = [row for row in labels[policy] if source.span(row['session']) == period]
            ss = [row for row in slots[policy] if source.span(row['session']) == period]
            entrance = R68.entry_summary(ll, period, source)
            operation = R68.operation_summary(aa, period, source, summary)
            result['候補'][policy][period] = {'入口': entrance, '運用': operation,
                '同時適格': entrance['70目標'] and operation['活動適格'] and operation['費用適格']}
            by_slot = {row['slot_id']: row for row in ss}
            barriers = {row['slot_id']: row for row in ll}
            red = [row for row in cc if row['arm'] and Decimal(str(row['pnl5'])) < 0]
            signs = Counter()
            for row in red:
                gross = Decimal(row['side']) * (Decimal(str(row['exit_price'])) - Decimal(str(row['entry_price'])))
                signs[(gross > 0) - (gross < 0)] += 1
            result['利益保護'][policy][period] = {'利益旗': sum(bool(row['arm']) for row in cc), '旗後赤': len(red),
                '同値': signs[0], '有利費用負け': signs[1], '不利': signs[-1],
                '先着250前の実退出': sum(barriers[row['slot_id']]['outcome'] == '250' and
                    (row['exit_time'], row['exit_line']) < (barriers[row['slot_id']]['end_time'], barriers[row['slot_id']]['end_line']) for row in cc)}
            if policy == 'Q0':
                continue
            local = [observations[row['slot_id']][policy] for row in ss]
            formations = [formation for obs in local for formation in obs['formations']]
            adopted = [row for row in ss if row['side']]
            ages = [next(candidate['k_age_seconds'] for candidate in observations[row['slot_id']][policy]['candidates']
                if candidate['id'] == row['pattern_id']) for row in adopted]
            result['技法被覆'][policy][period] = {'定時枠': len(ss), '準備済み': sum(obs['ready'] for obs in local),
                '理由別': dict(Counter(obs['reason'] for obs in local)), '形観測': len(formations),
                '形unique': len({formation['id'] for formation in formations}), '状態別': dict(Counter(formation['status'] for formation in formations)),
                '現在active観測': sum(len(obs['candidates']) for obs in local), '適格方向': len(adopted),
                '順行': sum(row['role'] == '順行' for row in adopted), '反転': sum(row['role'] == '反転' for row in adopted),
                '採用形unique': len({row['pattern_id'] for row in adopted}), '形成別採用': dict(Counter(row['formation'] for row in adopted)),
                '基本適格形成観測': sum(q['basic_qualified'] for obs in local for q in obs['qualifications'].values()),
                '位置除外形成観測': sum(q['basic_qualified'] and not q['position_qualified'] for obs in local for q in obs['qualifications'].values()),
                '基本不適格理由観測': dict(Counter(reason for obs in local for q in obs['qualifications'].values() for reason in q['basic_reasons'])),
                '位置除外理由観測': dict(Counter(reason for obs in local for q in obs['qualifications'].values() if q['basic_qualified'] for reason in q['position_reasons'])),
                '採用k経過秒': {'平均': sum(ages) / len(ages) if ages else None, '中央値': statistics.median(ages) if ages else None,
                    '最小': min(ages) if ages else None, '最大': max(ages) if ages else None},
                '同形成最大反復枠': max(Counter(row['pattern_id'] for row in adopted).values(), default=0)}
            result['形成別'][policy][period] = {}
            for kind in ('T', 'R'):
                selected = [row for row in adopted if row['formation'] == kind]
                group_l = [row for row in ll if by_slot[row['slot_id']]['formation'] == kind]
                group_c = [row for row in cc if by_slot[row['slot_id']]['formation'] == kind]
                result['形成別'][policy][period][kind] = {'純候補': len(selected), '形unique': len({row['pattern_id'] for row in selected}),
                    '入口': R68.entry_summary(group_l, period, source), '実完結': len(group_c),
                    '費用別観測円': {str(fee): close_sum(group_c, fee) for fee in (0, 5, 10)},
                    '役割別完結': {role: sum(row['role'] == role for row in group_c) for role in ('順行', '反転')}}
    # ----------------------------------------
    # 同じ元枠・方向と、さらに同じ実新規の経済差を別に保持する。
    for left, right in (('Q0', 'O0'), ('O0', 'P0'), ('P0', 'P1')):
        result['比較'][left + '対' + right] = {}
        for period in PERIODS:
            a = {row['slot_id']: row for row in slots[left] if source.span(row['session']) == period}
            b = {row['slot_id']: row for row in slots[right] if source.span(row['session']) == period}
            if set(a) != set(b):
                raise ValueError('比較する全予定枠が不一致')
            pure = Counter()
            for identity in a:
                x, y = a[identity]['side'], b[identity]['side']
                pure['双方待機' if not x and not y else '左のみ' if x and not y else '右のみ' if y and not x else '同方向' if x == y else '反対切替'] += 1
            ca = {(row['slot_id'], row['side']): row for account in accounts[left] if source.span(account['session']) == period for row in account['closed']}
            cb = {(row['slot_id'], row['side']): row for account in accounts[right] if source.span(account['session']) == period for row in account['closed']}
            common, drop, add = sorted(set(ca) & set(cb)), sorted(set(ca) - set(cb)), sorted(set(cb) - set(ca))
            exact = [identity for identity in common if all(ca[identity][key] == cb[identity][key] for key in ('entry_time', 'entry_line', 'entry_price'))]
            delta = float(sum((Decimal(str(cb[key]['pnl5'])) - Decimal(str(ca[key]['pnl5'])) for key in common), Decimal(0)))
            exact_delta = float(sum((Decimal(str(cb[key]['pnl5'])) - Decimal(str(ca[key]['pnl5'])) for key in exact), Decimal(0)))
            result['比較'][left + '対' + right][period] = {'純': dict(pure),
                '準備共通': sum(a[key]['ready'] and b[key]['ready'] for key in a),
                '左準備のみ': sum(a[key]['ready'] and not b[key]['ready'] for key in a),
                '右準備のみ': sum(b[key]['ready'] and not a[key]['ready'] for key in a),
                '実': {'左完結': len(ca), '右完結': len(cb), '共通元枠同方向': len(common), '左のみ': len(drop), '右のみ': len(add),
                    '共通元枠差額5': delta, '左のみ額5': close_sum([ca[key] for key in drop], 5), '右のみ額5': close_sum([cb[key] for key in add], 5),
                    '厳密同新規': len(exact), '厳密同新規出口差5': exact_delta}}
    return result


def check_api(base: str | None, resources: list[dict], accounts: list[dict], source, audit) -> dict:
    """184資源と新三政策の各一代表をViewer数値へ照合する。

    引数: base(str|None)はURL、resources/accounts(list[dict])は保存値、source/auditは固定読取と記録。
    返り値: dictは実行範囲。URL未指定をAPI成功扱いしない。
    """
    if not base:
        return {'実行': False, '理由': '--viewer-url未指定。API未検証、新138保存約定は全件照合'}
    query = {'catalog_path': (STUDY / '一覧.resources.json').relative_to(ROOT).as_posix()}
    listing, _, _ = source.fetch_json(base + '/api/resources?' + urlencode(query))
    audit.check('API184資源全集合', {row['id'] for row in listing['resources']}, {row['id'] for row in resources})
    audit.check('API184資源数', len(listing['resources']), 184)
    representatives = []
    for policy in POLICIES:
        account = sorted([row for row in accounts if row['candidate'] == policy], key=lambda row: (-abs(row['ledger']['5']), row['session']))[0]
        resource = next(row for row in resources if row['method_id'] == policy and row['session'] == account['session'])
        parameters = {**query, 'resource': resource['id'], 'interval': '5', 'price': 'last', 'width': 1000, 'height': 700}
        meta, _, _ = source.fetch_json(base + '/api/chart?' + urlencode(parameters))
        data, raw, headers = source.fetch_json(urljoin(base + '/', meta['data_url']))
        audit.check('API本文SHA', hashlib.sha256(raw).hexdigest(), meta['data_sha256'])
        audit.check('APIヘッダSHA', headers.get('x-chart-data-sha256'), meta['data_sha256'])
        audit.check('API集計alias', data['summary'], meta['summary'])
        audit.check('API台帳純額5', Decimal(str(data['summary']['realized_pnl_yen'])), Decimal(str(account['ledger']['5'])))
        trades = list(source.json_rows(ROOT / resource['pnl_path']))
        audit.check('API約定片数', len(data['events']), len(trades))
        for sequence, (trade, event) in enumerate(zip(trades, data['events']), 1):
            for key in ('type', 'qty', 'position_id', 'method_id', 'price'):
                audit.check('API約定:' + key, event[key], trade[key])
            audit.check('API原順', event['sequence'], sequence)
            audit.check('API時計', abs(event['timestamp_ms'] - datetime.fromisoformat(trade['timestamp']).timestamp() * 1000) <= .001, True)
        representatives.append({'候補': policy, '場': account['session'], '資源ID': resource['id'],
            '台帳観測5円': account['ledger']['5'], '数値SHA256': meta['data_sha256']})
    return {'実行': True, '全資源数': 184, '新政策代表': representatives, '代表規約': '政策別最大絶対台帳観測額・場順。採否不使用'}


# ----------------------------------------
def run(viewer_url: str | None = None) -> dict:
    """全66帯と評価46場の保存反応・三即時運用を正式に一度監査する。

    引数: viewer_url(str|None)は任意のViewer API。
    返り値: dictは公式proof。新I/主/Engineを期待値に呼ばず、売買を再生しない。
    """
    destination = STUDY / '保存物確認.json'
    if destination.exists():
        raise FileExistsError('75保存監査は保存済み。再実行しない')
    source, oracle, summary = A.helpers()
    audit = source.Audit()
    result, fixed, inputs = [source.read(STUDY / name) for name in ('結果.json', '固定.json', '入力台帳.json')]
    previous, proof74, ledger = [source.read(path) for path in (OLD / '結果.json', OLD / '保存物確認.json', LEDGER)]
    control, proof73 = [source.read(SOURCE_STUDY / name) for name in ('結果.json', '保存物確認.json')]
    preflight_path = WORK.parent / '入力確認.json'
    files = [STUDY / name for name in ('結果.json', '固定.json', '条件.json', '入力台帳.json', '一覧.resources.json')]
    files += [WORK / name for name in ('参照帯.json', '技法観測.jsonl.gz', '定時判断と運用.jsonl.gz', '入口先着.jsonl.gz', '実行完了.json')]
    files += [OLD / name for name in ('結果.json', '保存物確認.json', '固定.json')]
    files += [SOURCE_STUDY / name for name in ('結果.json', '保存物確認.json', '固定.json', '一覧.resources.json')]
    files += [SOURCE_WORK / name for name in ('定時判断と運用.jsonl.gz', '入口先着.jsonl.gz', '実行完了.json')]
    files += [LEDGER, R74.IMMEDIATE, R74.CONDITIONAL, source.MANIFEST, FRAMES, preflight_path, Path(__file__), HERE / '入力監査.py', HERE / '監査仕様.md']
    before = {path.relative_to(ROOT).as_posix(): source.sha(path) for path in files}
    for name, digest in fixed['ファイルSHA256'].items():
        audit.check('75固定:' + name, source.sha(ROOT / name), digest)
        before[name] = digest
    for group in ('参照SHA256', 'cacheSHA256'):
        for name, digest in inputs[group].items():
            audit.check('75入力:' + name, source.sha(ROOT / name), digest)
            before[name] = digest
    audit.check('74完了台帳SHA', source.sha(LEDGER), LEDGER_SHA)
    audit.check('74完了対象数', len(ledger['成果物SHA256']), 182)
    for name, digest in ledger['成果物SHA256'].items():
        audit.check('74固定成果物:' + name, source.sha(ROOT / name), digest)
        before[name] = digest
    audit.check('74成功監査', (proof74['全件一致'], proof74['不一致数'], proof74['結果SHA256']), (True, 0, source.sha(OLD / '結果.json')))
    audit.check('73成功監査', (proof73['全件一致'], proof73['不一致数'], proof73['結果SHA256']), (True, 0, source.sha(SOURCE_STUDY / '結果.json')))
    audit.check('75単一完了bind', source.read(WORK / '実行完了.json')['結果SHA256'], source.sha(STUDY / '結果.json'))
    audit.check('73単一完了bind', source.read(SOURCE_WORK / '実行完了.json')['結果SHA256'], source.sha(SOURCE_STUDY / '結果.json'))
    audit.check('75固定bind', (result['試行'], result['固定SHA256'], result['全66場既使用']), (75, source.sha(STUDY / '固定.json'), True))
    audit.check('75新処理範囲', tuple(result[key] for key in ('新fit', '新分類器fit', '新モデル', '新独立測定', '新運用数', '保存参照運用数', 'Viewer資源')), (0, 0, 0, 0, 138, 46, 184))
    audit.check('75政策集合', set(result['候補']), set(ALL_POLICIES))
    audit.check('75設定全文', result['設定'], source.read(STUDY / '条件.json'))
    audit.check('固定66台帳SHA', source.sha(source.MANIFEST), inputs['参照SHA256'][source.MANIFEST.relative_to(ROOT).as_posix()])
    entries = source.read(source.MANIFEST)['entries']
    evaluated = [entry['session'] for entry in entries[20:]]
    audit.check('既使用66場数', len(entries), 66)
    audit.check('75同46評価場', result['評価場'], evaluated)
    audit.check('73同46評価場', control['評価場'], evaluated)
    histories = read_sources(source, audit)
    audit.check('SOURCE全66場集合', set(histories), {entry['session'] for entry in entries})
    old = {row['session']: row for row in source.json_rows(SOURCE_WORK / '定時判断と運用.jsonl.gz') if row['policy'] == 'Q0'}
    audit.check('旧Q0保存46順', list(old), evaluated)
    identities = [slot['slot_id'] for block in old.values() for slot in block['slots']]
    audit.check('1702予定ID一意', (len(identities), len(set(identities))), (1702, 1702))
    banks, quotes = read_banks(set(identities), source, audit)
    observations, observed_order = {}, []
    for row in source.json_rows(WORK / '技法観測.jsonl.gz'):
        if row['slot_id'] in observations:
            raise ValueError('技法観測ID重複')
        observations[row['slot_id']] = row['observations']
        observed_order.append((row['session'], row['slot_id']))
    audit.check('保存観測順と全集合', observed_order, [(session, slot['slot_id']) for session in evaluated for slot in old[session]['slots']])
    detail = defaultdict(list)
    for block in source.json_rows(WORK / '定時判断と運用.jsonl.gz'):
        detail[block['session']].append(block)
    audit.check('新詳細の46場集合', set(detail), set(evaluated))
    resources = source.read(STUDY / '一覧.resources.json')['resources']
    resource_map = {(row['session'], row['method_id']): row for row in resources}
    audit.check('184資源一意', (len(resources), len(resource_map), len({row['id'] for row in resources})), (184, 184, 184))
    audit.check('184資源全集合', set(resource_map), {(session, policy) for session in evaluated for policy in ALL_POLICIES})
    for row in source.read(SOURCE_STUDY / '一覧.resources.json')['resources']:
        if row['method_id'] == 'Q0':
            audit.check('Q0資源参照全文', resource_map[row['session'], 'Q0'], row)
    accounts, labels, slots = ({policy: [] for policy in ALL_POLICIES} for _ in range(3))
    bands = {'full': {}, 'opening': {}, 'previous': INPUT.choose_previous(entries)}
    saved_bands = source.read(WORK / '参照帯.json')
    audit.check('直前収録の独立選定', saved_bands['previous'], bands['previous'])
    counts, summaries, cache_pins, viewer_pins = Counter(), [], {}, {}
    entry_matches = closed_matches = 0
    # ----------------------------------------
    # 66場を場単位で一度展開し、同じ原配列で帯と評価場の経済を検査する。
    for entry in entries:
        session = entry['session']
        tape, cache_path, digest, quality = R55.load_tape(entry, source, audit)
        cache_pins[cache_path] = digest
        raw = tape['events']
        events = [{'now': float(t), 'line': int(n), 'last': float(last), 'bid': float(bid), 'ask': float(ask), 'valid': bool(valid)}
            for t, n, last, bid, ask, valid in zip(*(raw[name] for name in ('now', 'line', 'last', 'bid', 'ask', 'valid')))]
        begin, end = INPUT.bounds(session)
        for name, stop, publication in (('full', end, 'timer'), ('opening', begin + 1800, 'row')):
            band = INPUT.aggregate(events, begin, stop, publication)
            bands[name][session] = band
            audit.check('独立帯全文:' + name + session, saved_bands[name][session], band)
            counts[name + '準備'] += bool(band['ready'])
            counts[name + '平坦'] += bool(band['coverage'] and band['coverage']['flat'])
        counts['帯照合'] += 2
        del events
        if session not in old:
            continue
        audit.check('評価cacheは73成功bind', digest, proof73['キャッシュSHA256'][cache_path])
        source_slots = {row['slot_id']: row for row in old[session]['slots']}
        chosen = {policy: [] for policy in POLICIES}
        for slot in old[session]['slots']:
            audit.check('55判断気配は原行同値', INPUT.canonical(quotes[slot['slot_id']]), INPUT.canonical(R55.decision_event(slot, tape)))
            for policy in POLICIES:
                obs = INPUT.derive(slot, histories[session], reference(policy, session, bands), quotes[slot['slot_id']], policy)
                audit.check('全prefix反応/直接gate全文:' + policy, INPUT.canonical(observations[slot['slot_id']][policy]), INPUT.canonical(obs))
                selected = INPUT.choose(slot, obs, policy)
                chosen[policy].append(selected)
                counts[policy + '準備'] += bool(obs['ready'])
                counts[policy + '方向'] += bool(selected['side'])
                counts['観測照合'] += 1
            p0, p1 = chosen['P0'][-1], chosen['P1'][-1]
            audit.check('P1は同方向又はWAIT', not p1['side'] or p1['side'] == p0['side'], True)
        reference_slots = [{**{key: row[key] for key in PURE}, 'session': session, 'policy': 'Q0', 'origin': '保存Q0', 'pattern_id': None, 'formation': None} for row in old[session]['slots']]
        slots['Q0'].extend(reference_slots)
        account = P.account(old[session]['operation'], source, audit)
        account['conditions'] = old[session]['operation']['conditions']
        accounts['Q0'].append(account)
        for slot in reference_slots:
            if slot['side']:
                label, _ = R74.label_for(slot, source_slots[slot['slot_id']], '条件', banks, audit)
                label['formation'] = None
                labels['Q0'].append(label)
        audit.check('三政策保存順', [block['policy'] for block in detail[session]], list(POLICIES))
        for block in detail[session]:
            policy, selected = block['policy'], chosen[block['policy']]
            audit.check('75純全17項目', block['slots'], selected)
            audit.check('評価phase不変', block['phase'], old[session]['phase'])
            audit.check('原板入力品質', block['input_quality'], quality)
            slots[policy].extend(selected)
            for slot in selected:
                if slot['side']:
                    label, _ = R74.label_for(slot, source_slots[slot['slot_id']], '即時', banks, audit)
                    label['formation'] = slot['formation']
                    labels[policy].append(label)
            account = R74.check_immediate({**block, 'conditions': {}}, tape, source, audit)
            accounts[policy].append(account)
            operation = block['operation']
            audit.check('新運用policy/場', (operation['candidate_id'], operation['session']), (policy, session))
            for order in operation['orders']:
                if order['kind'] == 'entry' and order['status'] == 'filled':
                    prior = banks['即時'][order['slot']['slot_id'], order['slot']['side']]['barrier']
                    audit.check('実新規の旧独立約定可否', prior['filled'], True)
                    audit.check('実新規の旧独立三属性', tuple(order['fill_' + key] for key in ('time', 'line', 'price')), tuple(prior['entry_' + key] for key in ('time', 'line', 'price')))
                    entry_matches += 1
            for closed in operation['closed']:
                single = banks['即時'][closed['slot_id'], closed['side']]['closed']
                audit.check('実完結の旧独立件数', len(single) if single is not None else None, 1)
                if single:
                    audit.check('実完結の非ID全文型', R55.strict_close_equal(closed, single[0]), True)
                closed_matches += 1
            resource = resource_map[session, policy]
            path = ROOT / resource['pnl_path']
            audit.check('新Viewer正規パス', path.resolve(), (STUDY / 'viewer' / (policy + '_' + session + '.trades.jsonl')).resolve())
            audit.check('新Viewer全約定', list(source.json_rows(path)), operation['trades'])
            audit.check('新Viewer元市場', resource['market_path'], entry['source_path'])
            audit.check('新Viewer商品/単位', (resource['symbol'], resource['product'], resource['point_value'], resource['pnl_format'], resource['pnl_basis']), ('NK225', 'NK225micro', 10, 'trades', 'net'))
            viewer_pins[path.relative_to(ROOT).as_posix()] = source.sha(path)
            summaries.append({'場': session, '候補': policy, '期間': source.span(session), '入力品質': quality, '運用品質': operation['quality'], '運用集計': operation['metrics']})
        print(session + ' 帯/公開prefix/即時BBO/保護/会計の独立照合', flush=True)
    audit.check('全帯保存全文', saved_bands, bands)
    preflight = source.read(preflight_path)
    expected_preflight = {'試行': 75, '成功': True, '全予定': 1702, **dict(counts),
        '旧独立測定から採否へ渡した情報': 'decision_bboのみ、両方向同値検査', '新運用': 0, '新独立測定': 0, '新市場取得': 0,
        '帯SHA256': source.sha(WORK / '参照帯.json'), '観測SHA256': source.sha(WORK / '技法観測.jsonl.gz'),
        'コードSHA256': {path.relative_to(ROOT).as_posix(): source.sha(path) for path in (HERE / '参照帯.py', HERE / '入力.py', HERE / '入力監査.py')}}
    audit.check('75事前入力全文', preflight, expected_preflight)
    audit.check('帯132/観測5106', (counts['帯照合'], counts['観測照合']), (132, 5106))
    audit.check('75場別138全文', result['場別'], summaries)
    audit.check('主二検査', result['検査'], {'実独立新規一致': entry_matches, '実独立完結一致': closed_matches})
    audit.check('新先着全保存順', list(source.json_rows(WORK / '入口先着.jsonl.gz')), [row for policy in POLICIES for row in labels[policy]])
    expected = expected_summary(accounts, labels, slots, observations, source, summary)
    for key, value in expected.items():
        audit.check('75独立全集計:' + key, result[key], value)
    audit.check('Q0保存主表全文', result['候補']['Q0'], control['候補']['Q0'])
    audit.check('75採用', result['採用'], [policy for policy in POLICIES if all(expected['候補'][policy][period]['同時適格'] for period in PERIODS[:2])])
    audit.check('75詳細三系列', set(result['詳細']), {'技法観測.jsonl.gz', '定時判断と運用.jsonl.gz', '入口先着.jsonl.gz'})
    for name, digest in result['詳細'].items():
        audit.check('75詳細SHA:' + name, source.sha(WORK / name), digest)
    audit.check('75帯SHA', result['帯SHA256'], source.sha(WORK / '参照帯.json'))
    api = check_api(viewer_url, resources, [account for policy in ALL_POLICIES for account in accounts[policy]], source, audit)
    for name, digest in {**before, **cache_pins, **viewer_pins}.items():
        audit.check('監査中参照不変:' + name, source.sha(ROOT / name), digest)
    payload = {'試行': 75, '確認日時': datetime.now(source.JST).isoformat(), '全件一致': audit.bad == 0,
        '照合項目数': audit.count, '不一致数': audit.bad, '不一致': audit.examples, '結果SHA256': source.sha(STUDY / '結果.json'),
        '新主処理import': False, '新入力import': False, '新参照帯import': False, 'Engine期待値import': False,
        '市場戦略再生': False, '本物fit再実行': False, '旧73特徴再構成': False,
        '固定SOURCE価格反応の独立再構成': True, '固定66場帯の独立再集約': True,
        '新fit': 0, '新独立測定': 0, '新運用数': 138, '保存参照運用数': 46, '予定枠数': 1702,
        '帯照合数': counts['帯照合'], '観測照合数': counts['観測照合'],
        '同一独立新規数': entry_matches, '同一独立完結数': closed_matches,
        '参照SHA256': before, 'キャッシュSHA256': cache_pins, '新Viewer約定SHA256': viewer_pins, 'ViewerAPI': api,
        '検証範囲': '74完了182対象/成功証明と73保存Q0、全66場の帯132/直前収録選定、評価1702枠×3政策の全prefix反応・複合gate・純17項目、新138即時運用の原BBO注文/全保護/現金/保有品質/活動、旧55先着・独立完結の非ID厳密結合、五集計全文、Viewer184/新三代表。',
        '限定': '当該66場は全て既使用。旧73の64特徴算術は再計算しない。旧55/69先着と独立回収は成功固定値を再用し新独立測定をしない。固定原板の読取と帯の別算は行うが、監査で市場売買の再生やfitはしない。形成反復は独立機会でなく、P1は位置条件後に同側の別T/Rへ変わり得る。観測額と全体確定nullを区別する。心理因果/原典再現/未見収益/70%保証を実証しない。'}
    with destination.open('x', encoding='utf-8') as stream:
        stream.write(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
    return payload


def validate(viewer_url: str | None = None) -> dict:
    """root用の正式一回監査APIを公開する。

    引数: viewer_url(str|None)はViewer URL。
    返り値: dictは保存した公式proof。既存proofを上書きしない。
    """
    return run(viewer_url)


def check(viewer_url: str | None = None) -> dict:
    """同じ正式監査をcheck名からも公開する。

    引数: viewer_url(str|None)はViewer URL。
    返り値: dictは一回の公式proof。二重起動を許可しない。
    """
    return run(viewer_url)


# ----------------------------------------
def self_test() -> dict:
    """人工の帯/反応・即時運用・形成集計を実装側と接続する。

    引数: なし。
    返り値: dictは成功/人工群数/照合数。新主とEngineは人工の出力側だけに使う。
    """
    source, oracle, summary = A.helpers()
    audit = source.Audit()
    engine = load_fixed(ROOT / 'scripts/定時帯反応/運用.py', '75人工の出力側固定49運用')
    conditional = load_fixed(ROOT / 'scripts/条件発動前の否定/運用.py', '75人工の出力側固定68運用')
    main = load_fixed(HERE / '検証.py', '75人工の出力側主集計')
    operations, accounts, slots, labels = ({policy: [] for policy in ALL_POLICIES} for _ in range(4))
    observations = {}
    for side in (1, -1):
        session = '2026-10-05_Day' if side == 1 else '2026-10-06_Day'
        _, force, _, scheduled = source.calendar(session)
        start = scheduled[0]
        values = [(0, 1000, 999, 1001), (1, 1011, 1010, 1012), (2, 1012, 1011, 1013),
            (3, 1030, 1029, 1031), (4, 1012, 1011, 1013), (5, 1013, 1012, 1014)]
        events = [{'now': start + t, 'line': i + 1, 'last': last if side == 1 else 2000 - last,
            'bid': bid if side == 1 else 2000 - ask, 'ask': ask if side == 1 else 2000 - bid, 'valid': True}
            for i, (t, last, bid, ask) in enumerate(values)]
        events.append({'now': force + 1, 'line': 7, 'last': 1000., 'bid': 999., 'ask': 1001., 'valid': True})
        tape = R74.artificial_tape(events, source)
        base = [{'scheduled': t, 'time': t, 'line': 1 if i == 0 else None, 'side': side if i == 0 else 0,
            'role': '順行' if i == 0 else '待機', 'atr': 10. if i == 0 else None, 'D': 10. if i == 0 else None,
            'reason': '人工候補' if i == 0 else '判断時計欠測', 'ready': i == 0, 'slot_id': session + '|' + str(i)} for i, t in enumerate(scheduled)]
        for policy in ALL_POLICIES:
            selected = [{**row, 'session': session, 'policy': policy, 'origin': '保存Q0' if policy == 'Q0' else '前帯外保持',
                'pattern_id': '人工形' + str(side) if i == 0 and policy != 'Q0' else None,
                'formation': 'T' if i == 0 and policy != 'Q0' else None} for i, row in enumerate(base)]
            pure = [{key: row[key] for key in PURE} for row in selected]
            conditions = {base[0]['slot_id']: {'high': 1010., 'low': 990., 'source': {'人工': True}, 'expires': start + 900}} if policy == 'Q0' else {}
            operation = conditional.replay(events, pure, conditions, session, policy) if policy == 'Q0' else engine.replay(events, pure, session, policy)
            block = {'session': session, 'policy': policy, 'slots': selected, 'conditions': conditions, 'operation': operation}
            if policy == 'Q0':
                identity = base[0]['slot_id']
                barrier, observed = R68.expected_label(tape, {**pure[0], 'session': session, 'policy': policy}, conditions[identity], force, source.calendar(session)[2], source, oracle)
                account = R69.check_operation(block, {identity: barrier}, {identity: observed}, tape, source, audit)
            else:
                account = R74.check_immediate(block, tape, source, audit)
                audit.check('鏡像利益旗後同値費用負け', [(row['arm'], row['entry_price'] == row['exit_price'], row['pnl5']) for row in operation['closed']], [(True, True, -122.)])
            operations[policy].append(operation)
            accounts[policy].append(account)
            slots[policy].extend(selected)
            for closed in operation['closed']:
                labels[policy].append({'session': session, 'slot_id': closed['slot_id'], 'side': side, 'role': '順行', 'filled': True,
                    'outcome': '250', 'time': start, 'line': 1, 'entry_time': closed['entry_time'], 'entry_line': closed['entry_line'],
                    'entry_price': closed['entry_price'], 'end_time': force, 'end_line': 7, 'formation': selected[0]['formation']})
            if policy != 'Q0':
                for i, row in enumerate(selected):
                    obs = {'ready': row['ready'], 'reason': '人工反応' if i == 0 else '人工未準備', 'side': row['side'],
                        'selected': {'k_age_seconds': 30.} if i == 0 else None,
                        'formations': [{'id': '人工形' + str(side), 'status': '有効'}] if i < 2 else [],
                        'candidates': [{'id': '人工形' + str(side), 'k_age_seconds': 30.}] if i == 0 else [],
                        'qualifications': {'人工': {'basic_qualified': True, 'position_qualified': policy != 'P1',
                            'basic_reasons': [], 'position_reasons': ['人工距離除外'] if policy == 'P1' else []}} if i == 0 else {}}
                    observations.setdefault(row['slot_id'], {})[policy] = obs
    before = INPUT.canonical((operations, accounts, slots, labels, observations))
    expected = expected_summary(accounts, labels, slots, observations, source, summary)
    audit.check('人工五全集計全文', main.summarize(operations, labels, slots, observations), expected)
    audit.check('人工入力不変', INPUT.canonical((operations, accounts, slots, labels, observations)), before)
    audit.check('反復観測とuniqueを分離', (expected['技法被覆']['P0']['学習']['形観測'], expected['技法被覆']['P0']['学習']['形unique']), (4, 2))
    audit.check('形成Tの完結2', expected['形成別']['P0']['学習']['T']['実完結'], 2)
    audit.check('未成立Rは空群保持', expected['形成別']['P0']['学習']['R']['入口']['率'], None)
    audit.check('P1位置除外の独立分母', expected['技法被覆']['P1']['学習']['位置除外形成観測'], 2)
    audit.check('未解消なしの0/5/10費用差', expected['形成別']['P0']['学習']['T']['費用別観測円'], {'0': -44., '5': -244., '10': -444.})
    audit.check('空期の主率は未知', expected['候補']['O0']['条件選択']['入口']['率'], None)
    audit.check('独立250前に実保護退出', expected['利益保護']['O0']['学習']['先着250前の実退出'], 2)
    audit.check('比較は同入口0差', expected['比較']['O0対P0']['学習']['実']['厳密同新規出口差5'], 0.)
    # ----------------------------------------
    # 旧独立結合は時計/ready/ATR/Dを保持し、未来currentやD差は検出する。
    slot = slots['O0'][0]
    old = {**slot, 'feature': {'base': {'base': {'sources': {'current': {'high': 1010., 'low': 990., 'end': slot['scheduled'], 'confirm': slot['time'], 'confirm_line': slot['line']}}}}}}
    barrier = {**{key: slot[key] for key in (*BINDING, 'side')}, 'filled': False, 'outcome': '未約定'}
    record = {'barrier': barrier, 'closed': [], 'binding': {key: slot[key] for key in (*BINDING, 'side', 'ready', 'atr', 'D')}, 'observed': slot['time']}
    bank = {'即時': {(slot['slot_id'], slot['side']): record}}
    copied, _ = R74.label_for(slot, old, '即時', bank, audit)
    audit.check('旧先着の値は由来だけ追加', set(copied) - set(barrier), {'policy', 'role', 'origin', 'pattern_id'})
    invalid = deepcopy(bank)
    invalid['即時'][slot['slot_id'], slot['side']]['binding']['D'] += 5
    probe = source.Audit()
    R74.label_for(slot, old, '即時', invalid, probe)
    audit.check('D結合の不一致検出', probe.bad > 0, True)
    # ----------------------------------------
    # 入力の全人工はleaf自身のself_testに分離し、ここでは実運用との接続だけ検査する。
    band = {'opening': {}, 'full': {}, 'previous': {}}
    material = INPUT.synthetic([990, 1006, 1007])
    fake_slot, history, prior, quote = material
    band['full'][prior['session']] = {key: value for key, value in prior.items() if key not in ('id', 'session', 'current_session', 'reference_type', 'prior_gap_seconds', 'reference_available')}
    band['previous'][fake_slot['session']] = {'ready': True, 'prior_session': prior['session'], 'gap_seconds': 10.}
    audit.check('参照装飾は固定前帯同値', reference('P0', fake_slot['session'], band), {**prior, 'id': 'FULL:' + prior['session']})
    band['previous'][fake_slot['session']] = {'ready': False, 'reason': '限月不一致'}
    unavailable = reference('P1', fake_slot['session'], band)
    obs = INPUT.derive(fake_slot, history, unavailable, quote, 'P1')
    audit.check('利用不可前帯の未来価格遮断', (obs['ready'], obs['side'], obs['band']['high'], obs['band']['publication_key']), (False, 0, None, None))
    return {'成功': audit.bad == 0, '人工成功': audit.bad == 0, 'テスト件数': 9, '照合項目数': audit.count,
        '不一致数': audit.bad, '不一致': audit.examples, '本物入力読取': False, '新fit': 0, '新独立測定': 0,
        '市場戦略再生': False, 'Engineは人工実装側のみ': True, '入力別算の範囲': '入力監査.self_testの128系列521比較は独立欄。ここへ重複加算しない'}


def main() -> None:
    """人工又はroot専用正式監査を公開し、標準出力を小型にする。

    引数: CLIのself-test/run(bool)とviewer-url(str|None)は段階とAPI。
    返り値: None。公式proofは全文JSON、標準出力は成功/件数だけ。
    """
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--run', action='store_true')
    group.add_argument('--self-test', action='store_true')
    parser.add_argument('--viewer-url')
    args = parser.parse_args()
    value = run(args.viewer_url) if args.run else self_test()
    keys = ('試行', '成功', '人工成功', '全件一致', 'テスト件数', '照合項目数', '不一致数', '不一致', '結果SHA256', '帯照合数', '観測照合数', '同一独立新規数', '同一独立完結数')
    print(json.dumps({key: value[key] for key in keys if key in value}, ensure_ascii=False, allow_nan=False), flush=True)
    raise SystemExit(0 if value.get('全件一致', value.get('成功', False)) else 1)


if __name__ == '__main__':
    main()
