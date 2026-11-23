"""77の終値反応確認を、固定76監査の純核と原BBOへ独立照合する。"""

import argparse
from collections import Counter, defaultdict
from copy import deepcopy
from datetime import datetime
from decimal import Decimal
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from urllib.parse import urlencode, urljoin


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
STUDY = ROOT / 'study/00077_押戻し再開の確認を早める'
WORK = ROOT / 'work/押戻し再開の確認幅/00077'
OLD = ROOT / 'study/00076_局所波の押戻しと起点喪失を分ける'
OLDWORK = ROOT / 'work/局所波の出生と切替/00076'
LEDGER = OLDWORK.parent / '76完了記録.json'
LEDGER_SHA = '74382ceb187474c57017729c7b1a8fcca56a506b5d51de4ff3244a9ecc32cb81'
POLICIES = ('E0', 'E1')
REFERENCES = ('L0', 'L1')
ALL_POLICIES = (*REFERENCES, *POLICIES)
PERIODS = ('学習', '条件選択', '後続検査')
PURE = ('scheduled', 'time', 'line', 'side', 'role', 'atr', 'D', 'reason', 'ready', 'slot_id')
SUMMARY_MAP = {'L0': 'O0', 'L1': 'P0', 'E0': 'L0', 'E1': 'L1'}


def load_fixed(path: Path, name: str, digest: str):
    """監査の停止版だけを固有名で読み、元の大域値を変えない。

    引数: path(Path)はコード、name(str)は固有名、digest(str)はSHA。
    返り値: ModuleTypeは固定純補助。動的ソース置換をしない。
    """
    if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
        raise ValueError('監査依存の変更:' + path.name)
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


R76 = load_fixed(ROOT / 'scripts/局所波の出生と切替/保存検証.py', '77固定76保存純核',
    'dc98fce801a950bf82fc91151c94282bcb824e2099da43ef3742774eaaa42787')
# 新独立入力は停止SHA確定後にここへ固定する。
INPUT_SHA = 'b681a6a2607ad3521c89c45cc9deb77c6604e94e64644da0938757b819daa5da'


def input_helpers():
    """77独立入力の停止版を明示SHAで読む。

    引数: なし。
    返り値: ModuleTypeは新I非依存の独立区間走査。
    """
    return load_fixed(HERE / '入力監査.py', '77独立親区間と終値反応', INPUT_SHA)


R74, R68, R55, P, A = R76.R74, R76.R68, R76.R55, R76.P, R76.A


# ----------------------------------------
def expected_summary(accounts: dict, labels: dict, slots: dict, observations: dict, source, summary) -> dict:
    """六集計の政策名だけを深い局所ビューへ射影し、固定76純核で別算する。

    引数: accounts/labels/slots/observations(dict)は監査済保存、source/summaryは固定補助。
    返り値: dictは新六集計。旧moduleの定数・関数・大域値を書き換えない。
    """
    prepared = []
    for material in (accounts, labels, slots):
        prepared.append({legacy: deepcopy(material[policy]) for policy, legacy in SUMMARY_MAP.items()})
    local = deepcopy(observations)
    for observation in local.values():
        observation['selected_by_policy'] = {SUMMARY_MAP[policy]: deepcopy(observation['selected_by_policy'][policy]) for policy in POLICIES}
    expected = R76.expected_summary(*prepared, local, source, summary)
    inverse = {value: key for key, value in SUMMARY_MAP.items()}
    output = {key: {inverse[policy]: value for policy, value in group.items()} for key, group in expected.items() if key != '比較'}
    output['比較'] = {inverse[key.split('対')[0]] + '対' + inverse[key.split('対')[1]]: value for key, value in expected['比較'].items()}
    return output


def check_api(base: str | None, resources: list[dict], accounts: list[dict], source, audit) -> dict:
    """新旧184資源と新E二政策代表をViewer数値へ照合する。

    引数: base(str|None)はURL、resources/accounts(list)は保存値、source/auditは固定補助。
    返り値: dictはAPI実行範囲。未指定時は未検証と明記する。
    """
    if not base:
        return {'実行': False, '理由': '--viewer-url未指定。API未検証、新92約定は全件照合'}
    query = {'catalog_path': (STUDY / '一覧.resources.json').relative_to(ROOT).as_posix()}
    listing, _, _ = source.fetch_json(base + '/api/resources?' + urlencode(query))
    audit.check('API184資源全集合', {row['id'] for row in listing['resources']}, {row['id'] for row in resources})
    audit.check('API184資源数', len(listing['resources']), 184)
    representatives = []
    for policy in POLICIES:
        account = min([row for row in accounts if row['candidate'] == policy], key=lambda row: (-abs(row['ledger']['5']), row['session']))
        resource = next(row for row in resources if row['method_id'] == policy and row['session'] == account['session'])
        parameters = {**query, 'resource': resource['id'], 'interval': '5', 'price': 'last', 'width': 1000, 'height': 700}
        meta, _, _ = source.fetch_json(base + '/api/chart?' + urlencode(parameters))
        data, raw, headers = source.fetch_json(urljoin(base + '/', meta['data_url']))
        audit.check('API本文SHA', hashlib.sha256(raw).hexdigest(), meta['data_sha256'])
        audit.check('APIヘッダSHA', headers.get('x-chart-data-sha256'), meta['data_sha256'])
        audit.check('API集計alias', data['summary'], meta['summary'])
        audit.check('API台帳5円', Decimal(str(data['summary']['realized_pnl_yen'])), Decimal(str(account['ledger']['5'])))
        trades = list(source.json_rows(ROOT / resource['pnl_path']))
        audit.check('API約定片数', len(data['events']), len(trades))
        for sequence, (trade, event) in enumerate(zip(trades, data['events']), 1):
            for name in ('type', 'qty', 'position_id', 'method_id', 'price'):
                audit.check('API約定:' + name, event[name], trade[name])
            audit.check('API約定順', event['sequence'], sequence)
            audit.check('API約定時計', abs(event['timestamp_ms'] - datetime.fromisoformat(trade['timestamp']).timestamp() * 1000) <= .001, True)
        representatives.append({'候補': policy, '場': account['session'], '資源ID': resource['id'], '台帳観測5円': account['ledger']['5'], '数値SHA256': meta['data_sha256']})
    return {'実行': True, '全資源数': 184, '新政策代表': representatives, '代表規約': '政策別最大絶対台帳観測額・場順。採否不使用'}


# ----------------------------------------
def run(viewer_url: str | None = None) -> dict:
    """新92の保存運用を原BBOで監査し、旧76親/Rと保存参考を結合する。

    引数: viewer_url(str|None)はViewer URL。
    返り値: dictは一度だけ保存する公式proof。出生ATR再build・市場戦略再生・fitは0。
    """
    destination = STUDY / '保存物確認.json'
    if destination.exists():
        raise FileExistsError('77の保存監査は保存済み。再起動しない')
    independent = input_helpers()
    source, _, summary = A.helpers()
    audit = source.Audit()
    result, fixed, inputs = [source.read(STUDY / name) for name in ('結果.json', '固定.json', '入力台帳.json')]
    old_result, old_proof, ledger = [source.read(path) for path in (OLD / '結果.json', OLD / '保存物確認.json', LEDGER)]
    preflight = source.read(WORK.parent / '入力確認.json')
    files = [STUDY / name for name in ('結果.json', '固定.json', '条件.json', '入力台帳.json', '一覧.resources.json')]
    files += [WORK / name for name in ('技法観測.jsonl.gz', '定時判断と運用.jsonl.gz', '入口先着.jsonl.gz', '実行完了.json')]
    files += [OLD / name for name in ('結果.json', '保存物確認.json', '固定.json', '一覧.resources.json')]
    files += [OLDWORK / name for name in ('出生ATR参照.jsonl.gz', '技法観測.jsonl.gz', '定時判断と運用.jsonl.gz', '入口先着.jsonl.gz', '実行完了.json')]
    files += [R76.SOURCE_WORK / '定時判断と運用.jsonl.gz', R76.SOURCE_STUDY / '固定.json', R74.IMMEDIATE,
        R76.OLDWORK / '参照帯.json', LEDGER, WORK.parent / '入力確認.json', source.MANIFEST, R76.FRAMES,
        Path(__file__), HERE / '監査仕様.md']
    before = {path.relative_to(ROOT).as_posix(): source.sha(path) for path in files}
    for name, digest in fixed['ファイルSHA256'].items():
        audit.check('77固定:' + name, source.sha(ROOT / name), digest)
        before[name] = digest
    for group in ('参照SHA256', 'cacheSHA256'):
        for name, digest in inputs[group].items():
            audit.check('77事前入力:' + name, source.sha(ROOT / name), digest)
            before[name] = digest
    audit.check('76完了台帳SHA', source.sha(LEDGER), LEDGER_SHA)
    audit.check('76完了対象数', len(ledger['成果物SHA256']), 142)
    for name, digest in ledger['成果物SHA256'].items():
        audit.check('76完了対象不変:' + name, source.sha(ROOT / name), digest)
        before[name] = digest
    audit.check('76成功proof結果bind', (old_proof['全件一致'], old_proof['不一致数'], old_proof['不一致'], old_proof['結果SHA256']), (True, 0, [], source.sha(OLD / '結果.json')))
    for folder, study in ((OLDWORK, OLD), (WORK, STUDY)):
        audit.check('単一完了bind:' + study.name, source.read(folder / '実行完了.json')['結果SHA256'], source.sha(study / '結果.json'))
    audit.check('77入力成功', (preflight['試行'], preflight['成功'], preflight['全予定']), (77, True, 1702))
    audit.check('77入力proof正本', result['入力確認'], preflight)
    audit.check('77固定bind', (result['試行'], result['固定SHA256'], result['全66場既使用']), (77, source.sha(STUDY / '固定.json'), True))
    audit.check('77新処理範囲', tuple(result[key] for key in ('新fit', '新分類器fit', '新モデル', '新独立測定', '新運用数', '保存参照運用数', 'Viewer資源')), (0, 0, 0, 0, 92, 92, 184))
    audit.check('77政策集合', set(result['候補']), set(ALL_POLICIES))
    audit.check('77設定全文', result['設定'], source.read(STUDY / '条件.json'))
    audit.check('元66台帳SHA', source.sha(source.MANIFEST), inputs['参照SHA256'][source.MANIFEST.relative_to(ROOT).as_posix()])
    entries = source.read(source.MANIFEST)['entries']
    evaluated = [row['session'] for row in entries[20:]]
    audit.check('既使用66場', len(entries), 66)
    audit.check('同46場', result['評価場'], evaluated)
    audit.check('参考同46場', old_result['評価場'], evaluated)
    base = {row['session']: row for row in source.json_rows(R76.SOURCE_WORK / '定時判断と運用.jsonl.gz') if row['policy'] == 'Q0'}
    reference = {(row['session'], row['policy']): row for row in source.json_rows(OLDWORK / '定時判断と運用.jsonl.gz')}
    audit.check('保存73全46判断', list(base), evaluated)
    audit.check('参考76全92運用', set(reference), {(session, policy) for session in evaluated for policy in REFERENCES})
    identities = [row['slot_id'] for session in evaluated for row in base[session]['slots']]
    audit.check('1702予定ID一意', (len(identities), len(set(identities))), (1702, 1702))
    bank, quotes = R76.read_immediate(set(identities), source, audit)
    # ----------------------------------------
    # 76の成功出生ATRをそのまま再用し、今回の独立再buildは行わない。
    _, histories = R76.source_sessions(entries, source, audit)
    saved_atr = {}
    for row in source.json_rows(OLDWORK / '出生ATR参照.jsonl.gz'):
        if row['session'] in saved_atr:
            raise ValueError('出生ATR場の重複')
        saved_atr[row['session']] = row['package']
    audit.check('76出生ATR66場順', list(saved_atr), [row['session'] for row in entries])
    observations, observed_order = {}, []
    for row in source.json_rows(WORK / '技法観測.jsonl.gz'):
        if row['slot_id'] in observations:
            raise ValueError('観測元枠の重複')
        observations[row['slot_id']] = row['observation']
        observed_order.append((row['session'], row['slot_id']))
    old_observations = {row['slot_id']: row['observation'] for row in source.json_rows(OLDWORK / '技法観測.jsonl.gz')}
    audit.check('新観測全1702予定順', observed_order, [(session, row['slot_id']) for session in evaluated for row in base[session]['slots']])
    audit.check('旧観測全1702集合', set(old_observations), set(identities))
    bands = source.read(R76.OLDWORK / '参照帯.json')
    chosen = {policy: {} for policy in POLICIES}
    counts = Counter()
    for session in evaluated:
        package = saved_atr[session]
        indexed = {row['index']: row for row in package['rows']}
        prior = R76.prior_for(session, bands)
        for slot in base[session]['slots']:
            if slot['ready']:
                current = slot['feature']['base']['base']['sources']['current']
                row = indexed[current['index']]
                independent.bind_atr([{name: current[name] for name in independent.SOURCE}], [row], slot)
                units = independent.exact(row['atr']) / 5
                distance = min(125, max(5, -(-units.numerator // units.denominator) * 5))
                audit.check('現在ATR/Dと旧73同値', (row['ready'], row['atr'], distance), (True, slot['atr'], slot['D']))
            obs = independent.derive(slot, histories[session], R76.visible_atr(package, slot), quotes[slot['slot_id']], prior)
            audit.check('新終値反応/複合/場所の全観測', independent.canonical(observations[slot['slot_id']]), independent.canonical(obs))
            audit.check('出生/親/r/f/R不変', independent.canonical(independent.parent_invariant(obs)), independent.canonical(independent.parent_invariant(old_observations[slot['slot_id']])))
            counts['親履歴不変件数'] += len(obs['parents'])
            for policy in POLICIES:
                chosen[policy][slot['slot_id']] = independent.choose(slot, obs, policy)
            left, right = chosen['E0'][slot['slot_id']], chosen['E1'][slot['slot_id']]
            audit.check('E0TはE1同純判断', not left['side'] or all(left[key] == right[key] for key in PURE), True)
            audit.check('E1だけの採用はR', not right['side'] or left['side'] != 0 or right['formation'] == 'R', True)
            counts['全予定'] += 1
            counts['基礎準備'] += bool(slot['ready'])
            counts['局所準備'] += bool(obs['ready'])
            counts['E0方向'] += bool(left['side'])
            counts['E1方向'] += bool(right['side'])
            counts['R追加'] += bool(right['side'] and not left['side'])
    expected_preflight = {'試行': 77, '成功': True, **dict(counts),
        '観測SHA256': source.sha(WORK / '技法観測.jsonl.gz'), '出生ATR参照SHA256': source.sha(OLDWORK / '出生ATR参照.jsonl.gz'), '出生ATR再計算': 0,
        'コードSHA256': {path.relative_to(ROOT).as_posix(): source.sha(path) for path in (HERE / '入力.py', HERE / '入力監査.py')},
        '新fit': 0, '新独立測定': 0, '新場内運用': 0, 'ラベルによる採否選択': False}
    audit.check('77損益前入力の全文別算', preflight, expected_preflight)
    # ----------------------------------------
    # 新92だけ原BBO監査する。参考92は成功76保存値を再用する。
    detail = defaultdict(list)
    for block in source.json_rows(WORK / '定時判断と運用.jsonl.gz'):
        detail[block['session']].append(block)
    audit.check('新詳細46場集合', set(detail), set(evaluated))
    resources = source.read(STUDY / '一覧.resources.json')['resources']
    resource_map = {(row['session'], row['method_id']): row for row in resources}
    audit.check('184資源一意', (len(resources), len(resource_map), len({row['id'] for row in resources})), (184, 184, 184))
    audit.check('184資源全集合', set(resource_map), {(session, policy) for session in evaluated for policy in ALL_POLICIES})
    for row in source.read(OLD / '一覧.resources.json')['resources']:
        if row['method_id'] in REFERENCES:
            audit.check('参考資源同保存参照', resource_map[row['session'], row['method_id']], row)
    accounts, labels, slots = ({policy: [] for policy in ALL_POLICIES} for _ in range(3))
    for row in source.json_rows(OLDWORK / '入口先着.jsonl.gz'):
        labels[row['policy']].append(deepcopy(row))
    cache_pins, viewer_pins, summaries = {}, {}, []
    entry_matches = closed_matches = 0
    for entry in entries[20:]:
        session = entry['session']
        old_slots = {row['slot_id']: row for row in base[session]['slots']}
        for policy in REFERENCES:
            block = reference[session, policy]
            audit.check('参考と同1702予定順', [row['slot_id'] for row in block['slots']], list(old_slots))
            slots[policy].extend(deepcopy(block['slots']))
            account = P.account(block['operation'], source, audit)
            account['conditions'] = {}
            accounts[policy].append(account)
        tape, cache_path, digest, quality = R55.load_tape(entry, source, audit)
        cache_pins[cache_path] = digest
        audit.check('76成功cachebind', digest, old_proof['キャッシュSHA256'][cache_path])
        audit.check('新二政策順', [block['policy'] for block in detail[session]], list(POLICIES))
        for block in detail[session]:
            policy = block['policy']
            selected = [chosen[policy][identity] for identity in old_slots]
            audit.check('新純入力とT確認出典全文', block['slots'], selected)
            audit.check('評価phase保持', block['phase'], base[session]['phase'])
            audit.check('原板入力品質', block['input_quality'], quality)
            slots[policy].extend(selected)
            for slot in selected:
                if slot['side']:
                    audit.check('採用55気配は原行6項目同値', independent.canonical(quotes[slot['slot_id']]), independent.canonical(R55.decision_event(slot, tape)))
                    label, _ = R74.label_for(slot, old_slots[slot['slot_id']], '即時', bank, audit)
                    label.update(parent_id=slot['parent_id'], formation=slot['formation'])
                    labels[policy].append(label)
            account = R74.check_immediate({**block, 'conditions': {}}, tape, source, audit)
            accounts[policy].append(account)
            operation = block['operation']
            audit.check('一枚運用場/policy', (operation['session'], operation['candidate_id']), (session, policy))
            for order in operation['orders']:
                if order['kind'] == 'entry' and order['status'] == 'filled':
                    prior = bank['即時'][order['slot']['slot_id'], order['slot']['side']]['barrier']
                    audit.check('実entry旧55約定可否', prior['filled'], True)
                    audit.check('実entry旧55全3属性', tuple(order['fill_' + key] for key in ('time', 'line', 'price')), tuple(prior['entry_' + key] for key in ('time', 'line', 'price')))
                    entry_matches += 1
            for closed in operation['closed']:
                single = bank['即時'][closed['slot_id'], closed['side']]['closed']
                audit.check('実closed旧55件数', len(single) if single is not None else None, 1)
                if single:
                    audit.check('実closed全非ID型/値', R55.strict_close_equal(closed, single[0]), True)
                closed_matches += 1
            resource = resource_map[session, policy]
            path = ROOT / resource['pnl_path']
            audit.check('新Viewer正規パス', path.resolve(), (STUDY / 'viewer' / (policy + '_' + session + '.trades.jsonl')).resolve())
            audit.check('新Viewer全約定', list(source.json_rows(path)), operation['trades'])
            audit.check('新Viewer元市場', resource['market_path'], entry['source_path'])
            audit.check('新Viewer商品/単位', (resource['symbol'], resource['product'], resource['point_value'], resource['pnl_format'], resource['pnl_basis']), ('NK225', 'NK225micro', 10, 'trades', 'net'))
            viewer_pins[path.relative_to(ROOT).as_posix()] = source.sha(path)
            summaries.append({'場': session, '候補': policy, '期間': source.span(session), '入力品質': quality, '運用品質': operation['quality'], '運用集計': operation['metrics']})
        print(session + ' 独立終値反応/55結合/原BBO/保護/会計を照合', flush=True)
    audit.check('77場別新92全文', result['場別'], summaries)
    audit.check('77主厳密結合件数', result['検査'], {'実独立新規一致': entry_matches, '実独立完結一致': closed_matches})
    audit.check('新先着全文と保存順', list(source.json_rows(WORK / '入口先着.jsonl.gz')), [row for policy in POLICIES for row in labels[policy]])
    expected = expected_summary(accounts, labels, slots, observations, source, summary)
    for key, value in expected.items():
        audit.check('77独立六集計:' + key, result[key], value)
    for policy in REFERENCES:
        for group in ('候補', '利益保護'):
            audit.check('76参考再集計全文:' + policy + group, result[group][policy], old_result[group][policy])
    audit.check('77採用', result['採用'], [policy for policy in POLICIES if all(expected['候補'][policy][period]['同時適格'] for period in PERIODS[:2])])
    audit.check('77詳細三系列', set(result['詳細']), {'技法観測.jsonl.gz', '定時判断と運用.jsonl.gz', '入口先着.jsonl.gz'})
    for name, digest in result['詳細'].items():
        audit.check('77詳細SHA:' + name, source.sha(WORK / name), digest)
    api = check_api(viewer_url, resources, [row for policy in ALL_POLICIES for row in accounts[policy]], source, audit)
    for name, digest in {**before, **cache_pins, **viewer_pins}.items():
        audit.check('監査中参照不変:' + name, source.sha(ROOT / name), digest)
    payload = {'試行': 77, '確認日時': datetime.now(source.JST).isoformat(), '全件一致': audit.bad == 0,
        '照合項目数': audit.count, '不一致数': audit.bad, '不一致': audit.examples, '結果SHA256': source.sha(STUDY / '結果.json'),
        '新主処理import': False, '新入力import': False, 'Engine期待値import': False, '動的ソース置換': False,
        '市場戦略再生': False, '本物fit再実行': False, '旧73特徴再構成': False, '出生ATR再build': 0,
        '親波独立再構成': True, '69条件銀行読取': False, '新fit': 0, '新独立測定': 0,
        '新運用数': 92, '保存参照運用数': 92, '予定枠数': 1702, '入力再照合': dict(counts),
        '同一独立新規数': entry_matches, '同一独立完結数': closed_matches,
        '参照SHA256': before, 'キャッシュSHA256': cache_pins, '新Viewer約定SHA256': viewer_pins, 'ViewerAPI': api,
        '検証範囲': '76完了142対象/成功proofと出生ATR保存参照、同1702の出生/親/r/f/R不変・新T確認/最初取消/直前SOURCE/現資格/純入力、旧55全予定両方向と原readyFalseのNone、採用方向先着/独立closed全非ID、新92全予定/原BBO/TTL/追尾/現金/holdgap品質、76参考92再集計・独立六集計・Viewer184新2代表。',
        '限定': '全66場既使用。Tの早期確認は早期永久取消も生む。先着とO49回収は別。出生ATRは成功76保存値を再用し再build0。親/形成/理由は全履歴の反復観測を含む。観測額/品質null・新旧参加構成差と厳密同新規出口差を区別し、心理因果/原典再現/未見利益/70%保証を主張しない。'}
    with destination.open('x', encoding='utf-8') as stream:
        stream.write(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
    return payload


# ----------------------------------------
def self_test() -> dict:
    """架空の早期TとRを原BBO・六集計・政策対応へ有取引接続する。

    引数: なし。
    返り値: dictは成功/群数/照合数。新主/Engineは人工の出力側だけ。
    """
    independent = input_helpers()
    source, _, summary = A.helpers()
    audit = source.Audit()
    engine = R74.load_fixed(ROOT / 'scripts/定時帯反応/運用.py', '77人工出力側49')
    main = R74.load_fixed(HERE / '検証.py', '77人工出力側主')
    fixture = R74.load_fixed(ROOT / 'scripts/局所波の出生と切替/入力.py', '77人工材料76')
    operations, accounts, labels, slots = ({p: [] for p in ALL_POLICIES} for _ in range(4))
    observations = {}
    for sample, (closes, desired) in enumerate((([100, 103, 106, 104, 105], 1), ([100, 103, 106, 98, 96], -1))):
        session = '2026-10-05_Day' if sample == 0 else '2026-10-06_Day'
        _, force, _, schedule = source.calendar(session)
        first = schedule[0]
        case = fixture.synthetic(closes, desired, desired)
        old, frames, atr_rows, quote, band = case
        offset = first - frames[-1]['end']
        for frame in frames:
            frame['session'] = session
            for key in ('start', 'end', 'confirm'):
                frame[key] += offset
        old.update(session=session, scheduled=first, time=first + 1, line=10000, slot_id=session + '|0', atr=100., D=100.)
        old['feature'].update(atr=100., D=100.)
        old['feature']['base']['base']['sources']['current'] = deepcopy(frames[-1])
        quote.update(now=old['time'], line=old['line'], last=closes[-1], bid=closes[-1] - 1, ask=closes[-1] + 1)
        atr_rows = [{**{key: deepcopy(frame[key]) for key in independent.ATR_CLOCK},
            'source_sha256': hashlib.sha256(independent.canonical(frame).encode('utf-8')).hexdigest(),
            'atr': 100. if i == len(frames) - 1 else 5., 'valid': True, 'numeric_count': 30,
            'reset_reasons': [], 'ready': True, 'reason': '出生ATR準備済み'} for i, frame in enumerate(frames)]
        obs = independent.derive(old, frames, atr_rows, quote, None)
        old_obs = independent.LEGACY.derive(old, frames, atr_rows, quote, None)
        audit.check('人工新T/R採用', (obs['side'], obs['selected']['kind']), (desired, 'T' if desired == 1 else 'R'))
        audit.check('人工親/R不変', independent.parent_invariant(obs), independent.parent_invariant(old_obs))
        if desired == 1:
            audit.check('人工早期Tは旧kなし', (old_obs['side'], obs['selected']['confirmation_previous']['index']), (0, 3))
        base = [old]
        old_observations = {old['slot_id']: old_obs}
        for i, scheduled in enumerate(schedule[1:], 1):
            base.append({'scheduled': scheduled, 'time': scheduled, 'line': None, 'side': 0, 'role': '待機', 'atr': None, 'D': None,
                'reason': '判断時計欠測', 'ready': False, 'slot_id': session + '|' + str(i), 'session': session, 'feature': {'ready': False}})
        for i, slot in enumerate(base):
            observations[slot['slot_id']] = obs if i == 0 else independent.derive(slot, [], [], None, None)
            if i:
                old_observations[slot['slot_id']] = independent.LEGACY.derive(slot, [], [], None, None)
        entry = (quote['ask'] if desired == 1 else quote['bid']) + 11 * desired
        events = [deepcopy(quote)]
        bid, ask = (entry - 2, entry) if desired == 1 else (entry, entry + 2)
        events.append({'now': first + 2, 'line': 10001, 'last': (bid + ask) / 2, 'bid': bid, 'ask': ask, 'valid': True})
        for step, profit in enumerate((-1, 17, 0, 0), 3):
            mark = entry + desired * profit
            bid, ask = (mark, mark + 2) if desired == 1 else (mark - 2, mark)
            events.append({'now': first + step, 'line': 9999 + step, 'last': (bid + ask) / 2, 'bid': bid, 'ask': ask, 'valid': True})
        events.append({'now': force + 1, 'line': 10006, 'last': 100., 'bid': 99., 'ask': 101., 'valid': True})
        tape = R74.artificial_tape(events, source)
        for policy in ALL_POLICIES:
            if policy in REFERENCES:
                selected = [independent.LEGACY.choose(slot, old_observations[slot['slot_id']], policy) for slot in base]
            else:
                selected = [independent.choose(slot, observations[slot['slot_id']], policy) for slot in base]
            pure = [{key: row[key] for key in PURE} for row in selected]
            operation = engine.replay(events, pure, session, policy)
            block = {'session': session, 'policy': policy, 'slots': selected, 'conditions': {}, 'operation': operation}
            account = R74.check_immediate(block, tape, source, audit)
            operations[policy].append(operation)
            accounts[policy].append(account)
            slots[policy].extend(selected)
            for closed in operation['closed']:
                audit.check('利益保護後同値費用負け', (closed['arm'], closed['entry_price'], closed['exit_price'], closed['pnl5']), (True, entry, entry, -122.))
                labels[policy].append({'session': session, 'slot_id': closed['slot_id'], 'policy': policy, 'side': desired, 'role': '順行',
                    'time': first + 1, 'line': 10000, 'filled': True, 'outcome': '250', 'entry_time': closed['entry_time'],
                    'entry_line': closed['entry_line'], 'entry_price': closed['entry_price'], 'end_time': force, 'end_line': 10006})
    before = independent.canonical((operations, accounts, labels, slots, observations))
    calculated = expected_summary(accounts, labels, slots, observations, source, summary)
    audit.check('新旧有取引六集計全文', main.summarize(operations, labels, slots, observations), calculated)
    audit.check('政策adapterの入力不変', independent.canonical((operations, accounts, labels, slots, observations)), before)
    audit.check('新E0T/E1TRの完結分母', (calculated['候補']['E0']['学習']['運用']['完結数'], calculated['候補']['E1']['学習']['運用']['完結数']), (1, 2))
    audit.check('旧L0対新E0の早期追加', calculated['比較']['L0対E0']['学習']['実']['右のみ'], 1)
    audit.check('R追加は別元枠', calculated['比較']['E0対E1']['学習']['実']['右のみ'], 1)
    audit.check('場所未知を採否へ戻さない', calculated['場所別']['E1']['学習']['未知']['純候補'], 2)
    audit.check('先着と利益旗後赤字を分ける', (calculated['利益保護']['E1']['学習']['先着250前の実退出'], calculated['利益保護']['E1']['学習']['同値']), (2, 2))
    caution = deepcopy(accounts)
    caution['E1'][0]['caution'] = True
    audit.check('品質注意は全体確定null', expected_summary(caution, labels, slots, observations, source, summary)['候補']['E1']['学習']['運用']['全体確定額円'], {'0': None, '5': None, '10': None})
    empty = {p: [] for p in ALL_POLICIES}
    audit.check('空集計も政策とnullを保持', main.summarize(deepcopy(empty), deepcopy(empty), deepcopy(empty), {}), expected_summary(deepcopy(empty), deepcopy(empty), deepcopy(empty), {}, source, summary))
    return {'成功': audit.bad == 0, '人工成功': audit.bad == 0, 'テスト件数': 10, '照合項目数': audit.count,
        '不一致数': audit.bad, '不一致': audit.examples, '本物入力読取': False, '本物fit': 0, '出生ATR再build': 0,
        '市場戦略再生': False, '新独立測定': 0, '新主/Engineは人工出力側だけ': True,
        '別人工': '入力監査42系列256比較は別欄。固定76監査の欠測/保有品質/現金の成功証拠を継承'}


def validate(viewer_url: str | None = None) -> dict:
    """root用に正式保存監査を別名で公開する。

    引数: viewer_url(str|None)はViewer URL。
    返り値: dictは排他的に保存するproof。
    """
    return run(viewer_url)


def check(viewer_url: str | None = None) -> dict:
    """同じ正式監査をcheck名で公開する。

    引数: viewer_url(str|None)はViewer URL。
    返り値: dictは公式proof。二重起動をしない。
    """
    return run(viewer_url)


def main() -> None:
    """人工又はrootの正式監査を排他起動し、小型結果を表示する。

    引数: CLIの--run/--self-test(bool)、--viewer-url(str|None)は段階とViewer。
    返り値: None。正式proof全文はJSONだけへ保存する。
    """
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--run', action='store_true')
    group.add_argument('--self-test', action='store_true')
    parser.add_argument('--viewer-url')
    args = parser.parse_args()
    value = run(args.viewer_url) if args.run else self_test()
    keys = ('試行', '成功', '人工成功', '全件一致', 'テスト件数', '照合項目数', '不一致数', '不一致', '結果SHA256', '同一独立新規数', '同一独立完結数')
    print(json.dumps({key: value[key] for key in keys if key in value}, ensure_ascii=False, allow_nan=False), flush=True)
    raise SystemExit(0 if value.get('全件一致', value.get('成功', False)) else 1)


if __name__ == '__main__':
    main()
