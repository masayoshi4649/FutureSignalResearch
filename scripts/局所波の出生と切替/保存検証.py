"""76の同原因親波と二つの一枚運用を、独立入力・原BBO・現金へ照合する。"""

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
from types import SimpleNamespace
from urllib.parse import urlencode, urljoin


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
STUDY = ROOT / 'study/00076_局所波の押戻しと起点喪失を分ける'
WORK = ROOT / 'work/局所波の出生と切替/00076'
OLD = ROOT / 'study/00075_事前帯の外保持と内回帰を判別'
OLDWORK = ROOT / 'work/事前帯と現在の反応/00075'
LEDGER = OLDWORK.parent / '75完了記録.json'
LEDGER_SHA = '13deab86d335ac62bc5ac93b3fe1f0006efbead2752ea0b26d2406dca1781031'
SOURCE_STUDY = ROOT / 'study/00073_直近の集中と方向効率を組み合わせる'
SOURCE_WORK = ROOT / 'work/直近進行の集中と効率/00073'
FRAMES = ROOT / 'work/一目基準線/00028/全指標.jsonl.gz'
FRAME_SHA = 'db5afa37a5cd7de91a4f649b8f9cbcc21f301cb73e9ca4930d09cc24234cd6fa'
STAGE = WORK.parent / '入力段階記録.json'
STAGE_SHA = 'd0617465782bf943fb0582c345a8dce079395fe2f5523c6c6fe085e880818635'
POLICIES = ('L0', 'L1')
REFERENCES = ('O0', 'P0')
ALL_POLICIES = (*REFERENCES, *POLICIES)
PERIODS = ('学習', '条件選択', '後続検査')
PURE = ('scheduled', 'time', 'line', 'side', 'role', 'atr', 'D', 'reason', 'ready', 'slot_id')
BINDING = ('session', 'slot_id', 'scheduled', 'time', 'line')


def load_fixed(path: Path, name: str, digest: str):
    """独立監査の停止版だけを固有名で読み、旧大域値を変えない。

    引数: path(Path)はコード、name(str)は固有名、digest(str)は固定SHA。
    返り値: ModuleTypeは純監査。新主・新入力・Engineを期待値へ読まない。
    """
    if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
        raise ValueError('監査依存の変更:' + path.name)
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


R74 = load_fixed(ROOT / 'scripts/内包足の偽突破と局面切替/保存検証.py', '局所76の固定74監査',
    '460d7a89cb92921e34db3d3c4c5f26a9a22296f18c7e4a2fb245238f433819f6')
INPUT = load_fixed(HERE / '入力監査.py', '局所76の独立親波',
    '1985e2b651e3a3058b7d3b380c2bc1a35499a1ffca74ba7b983b4f23ccf752ae')
ATR = load_fixed(HERE / '出生ATR監査.py', '局所76の独立出生ATR',
    '8f212caf19a91ecb9c00a42ac0f319208c3310f3630a20e0d6127d5289a6ba53')
R68, R55, P, A = R74.R68, R74.R55, R74.P, R74.A


# ----------------------------------------
def close_sum(rows: list[dict], fee: int) -> float:
    """完結観測額を十進加算し、未解消を0へ置換しない。

    引数: rows(list[dict])は完結、fee(int)は0/5/10。
    返り値: floatは観測額。確定性は政策期間全体へ別に照合する。
    """
    return float(sum((Decimal(str(row['pnl' + str(fee)])) for row in rows), Decimal(0)))


def distribution(values: list) -> dict:
    """有限の形成経過を四統計へまとめる。

    引数: values(list[float])は保存経過。
    返り値: dictは平均/中央値/最小/最大。空はNone。
    """
    return {'平均': sum(values) / len(values) if values else None, '中央値': statistics.median(values) if values else None,
        '最小': min(values) if values else None, '最大': max(values) if values else None}


def source_sessions(entries: list[dict], source, audit) -> tuple:
    """固定28SOURCEから元66場の価格だけを指紋付きで組み立てる。

    引数: entries(list[dict])は元台帳順、source/auditは固定読取と記録。
    返り値: tupleはATR監査用sessionsと場別SOURCE13。新しい指標は作らない。
    """
    audit.check('固定SOURCE銀行SHA', source.sha(FRAMES), FRAME_SHA)
    grouped = defaultdict(list)
    for row in source.json_rows(FRAMES):
        if row['minutes'] == 3:
            grouped[row['場']].append({key: row[key] for key in INPUT.SOURCE[1:]})
    audit.check('SOURCE全66場集合', set(grouped), {row['session'] for row in entries})
    sessions, histories = [], {}
    for entry in entries:
        session = entry['session']
        begin, _, end, _ = source.calendar(session)
        sessions.append({'session': session, 'contract': tuple(entry['in_session_contract_codes']),
            'begin': begin, 'end': end, 'frames3': grouped[session]})
        histories[session] = [{'session': session, **row} for row in grouped[session]]
    return sessions, histories


def visible_atr(package: dict, slot: dict) -> list:
    """全場ATRから当時可知な行だけを新本体へ依存せず選ぶ。

    引数: package(dict)は独立ATR、slot(dict)は旧判断。
    返り値: list[dict]はend/公開keyとも当時以内。基礎未準備なら空。
    """
    if not slot['ready']:
        return []
    return [deepcopy(row) for row in package['rows'] if row['end'] <= slot['scheduled'] and INPUT.finite(row['confirm'])
        and type(row['confirm_line']) is int and (row['confirm'], row['confirm_line']) <= (slot['time'], slot['line'])]


def prior_for(session: str, bands: dict) -> dict:
    """75保存前帯を診断専用のsnapshotへ装飾する。

    引数: session(str)は当場、bands(dict)は成功保存の帯。
    返り値: dictは直前収録帯又は参照なし。現在全期間帯を渡さない。
    """
    prior = bands['previous'][session]
    if not prior['ready']:
        return {'ready': False, 'reason': prior['reason'], 'id': 'FULL:なし:' + session,
            'reference_available': False, 'published': False, 'current_session': session,
            'session': None, 'reference_type': 'FULL', 'prior_gap_seconds': None, 'begin': None, 'end': None,
            'publication': 'timer', 'publication_key': None, 'open': None, 'high': None, 'low': None,
            'close': None, 'sources': None, 'coverage': None}
    name = prior['prior_session']
    result = deepcopy(bands['full'][name])
    result.update(id='FULL:' + name, session=name, current_session=session, reference_type='FULL',
        prior_gap_seconds=prior['gap_seconds'], reference_available=True)
    return result


def read_immediate(identities: set, source, audit) -> tuple:
    """旧55全予定の両方向を読み、原準備と未計測Noneを維持する。

    引数: identities(set[str])は全1702枠、source/auditは固定読取と記録。
    返り値: tuple[dict,dict]は方向測定と当時気配。69銀行は読まない。
    """
    pins = source.read(SOURCE_STUDY / '固定.json')['ファイルSHA256']
    audit.check('55成功固定測定SHA', source.sha(R74.IMMEDIATE), pins[R74.IMMEDIATE.relative_to(ROOT).as_posix()])
    bank, quotes = {}, {}
    for row in source.json_rows(R74.IMMEDIATE):
        identity = row['slot_id']
        if identity not in identities:
            continue
        key = identity, row['side']
        if key in bank:
            raise ValueError('旧55方向行が重複')
        operation = row['operation']
        binding = {name: row[name] for name in (*BINDING, 'side', 'ready', 'atr', 'D')}
        audit.check('55原ready型', type(binding['ready']) is bool, True)
        if binding['ready']:
            audit.check('55準備済みは実測と気配あり', operation is not None and row['decision_bbo'] is not None, True)
        else:
            audit.check('55技法未準備の未計測', (operation, row['decision_bbo']), (None, None))
        bank[key] = {'barrier': row['barrier'], 'closed': deepcopy(operation['closed']) if operation is not None else None,
            'binding': binding, 'observed': None}
        if identity in quotes:
            audit.check('55両方向の気配同値', INPUT.canonical(quotes[identity]), INPUT.canonical(row['decision_bbo']))
            audit.check('55両方向の準備同値', {name: bank[identity, 1]['binding'][name] for name in ('ready', 'atr', 'D')},
                {name: binding[name] for name in ('ready', 'atr', 'D')})
        else:
            quotes[identity] = deepcopy(row['decision_bbo'])
    audit.check('55全予定両方向の全集合', set(bank), {(identity, side) for identity in identities for side in (1, -1)})
    audit.check('55全予定気配集合', set(quotes), identities)
    return {'即時': bank}, quotes


def check_api(base: str | None, resources: list[dict], accounts: list[dict], source, audit) -> dict:
    """184資源と新二政策代表をViewer数値へ照合する。

    引数: base(str|None)はURL、resources/accountsは保存一覧/会計、source/auditは固定補助。
    返り値: dictはAPI範囲。未指定は未検証と明記する。
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
        representatives.append({'候補': policy, '場': account['session'], '資源ID': resource['id'],
            '台帳観測5円': account['ledger']['5'], '数値SHA256': meta['data_sha256']})
    return {'実行': True, '全資源数': 184, '新政策代表': representatives, '代表規約': '政策別最大絶対台帳観測額・場順。採否不使用'}


# ----------------------------------------
def expected_summary(accounts: dict, labels: dict, slots: dict, observations: dict, source, summary) -> dict:
    """独立会計から期・形成・場所を分け、主六集計を別構成する。

    引数: accounts/labels/slots/observationsは監査済み保存値、source/summaryは固定純監査。
    返り値: dictは六集計全文。新主summarizeを期待値へ呼ばない。
    """
    result = {name: {p: {} for p in ALL_POLICIES} for name in ('候補', '利益保護', '技法被覆', '形成別', '場所別')}
    result['比較'] = {}
    for policy in ALL_POLICIES:
        for period in PERIODS:
            aa = [row for row in accounts[policy] if source.span(row['session']) == period]
            cc = [row for account in aa for row in account['closed']]
            ll = [row for row in labels[policy] if source.span(row['session']) == period]
            ss = [row for row in slots[policy] if source.span(row['session']) == period]
            entrance = R68.entry_summary(ll, period, source)
            operation = R68.operation_summary(aa, period, source, summary)
            result['候補'][policy][period] = {'入口': entrance, '運用': operation,
                '同時適格': entrance['70目標'] and operation['活動適格'] and operation['費用適格']}
            lm = {row['slot_id']: row for row in ll}
            red = [row for row in cc if row['arm'] and Decimal(str(row['pnl5'])) < 0]
            signs = Counter()
            for row in red:
                gross = Decimal(row['side']) * (Decimal(str(row['exit_price'])) - Decimal(str(row['entry_price'])))
                signs[(gross > 0) - (gross < 0)] += 1
            result['利益保護'][policy][period] = {'利益旗': sum(bool(row['arm']) for row in cc), '旗後赤': len(red),
                '同値': signs[0], '有利費用負け': signs[1], '不利': signs[-1],
                '先着250前の実退出': sum(lm[row['slot_id']]['outcome'] == '250' and (row['exit_time'], row['exit_line']) < (lm[row['slot_id']]['end_time'], lm[row['slot_id']]['end_line']) for row in cc)}
            if policy in REFERENCES:
                continue
            oo = [observations[row['slot_id']] for row in ss]
            parents = [row for obs in oo for row in obs['parents']]
            formations = [row for obs in oo for row in obs['formations']]
            adopted = [row for row in ss if row['side']]
            picked = [obs['selected_by_policy'][policy]['selected'] for obs in oo if obs['selected_by_policy'][policy]['side']]
            result['技法被覆'][policy][period] = {'定時枠': len(ss), '基礎準備': sum(obs['base_ready'] for obs in oo),
                '準備済み': sum(obs['ready'] for obs in oo), '追加未準備': sum(obs['base_ready'] and not obs['ready'] for obs in oo),
                '理由別': dict(Counter(row['reason'] for row in ss)), '観測理由別': dict(Counter(obs['reason'] for obs in oo)),
                '親観測': len(parents), '親unique': len({row['id'] for row in parents}), '親状態別': dict(Counter(row['status'] for row in parents)),
                '起点喪失f観測': sum(row['f'] is not None for row in parents),
                '遅いf観測': sum(row['late_f'] is not None and row['late_f']['reason'] is not None for row in parents),
                '形観測': len(formations), '形unique': len({row['id'] for row in formations}), '状態別': dict(Counter(row['status'] for row in formations)),
                '現在active観測': sum(len(obs['candidates']) for obs in oo), '適格方向': len(adopted),
                '順行': sum(row['role'] == '順行' for row in adopted), '反転': sum(row['role'] == '反転' for row in adopted),
                '採用形unique': len({row['pattern_id'] for row in adopted}), '採用親unique': len({row['parent_id'] for row in adopted}),
                '形成別採用': dict(Counter(row['formation'] for row in adopted)),
                '基本不適格理由観測': dict(Counter(reason for obs in oo for q in obs['qualifications'].values() for reason in q['reasons'])),
                '採用k経過秒': distribution([row['k_age_seconds'] for row in picked]),
                '採用k終了経過秒': distribution([row['k_end_age_seconds'] for row in picked]),
                '採用tip距離pt': distribution([row['tip_distance'] for row in picked]),
                '同形成最大反復枠': max(Counter(row['pattern_id'] for row in adopted).values(), default=0),
                'reset観測': sum(len(obs['history']['resets']) for obs in oo), '出生拒否観測': sum(len(obs['history']['rejected_births']) for obs in oo)}
            by_id = {row['slot_id']: row for row in ss}
            result['形成別'][policy][period] = {}
            for kind in ('T', 'R'):
                group_s = [row for row in adopted if row['formation'] == kind]
                group_l = [row for row in ll if by_id[row['slot_id']]['formation'] == kind]
                group_c = [row for row in cc if by_id[row['slot_id']]['formation'] == kind]
                result['形成別'][policy][period][kind] = {'純候補': len(group_s), '形unique': len({row['pattern_id'] for row in group_s}),
                    '入口': R68.entry_summary(group_l, period, source), '実完結': len(group_c),
                    '費用別観測円': {str(fee): close_sum(group_c, fee) for fee in (0, 5, 10)},
                    '役割別完結': {role: sum(row['role'] == role for row in group_c) for role in ('順行', '反転')}}
            where = {row['slot_id']: observations[row['slot_id']]['location']['by_side'][str(row['side'])]['position'] for row in adopted}
            result['場所別'][policy][period] = {}
            for position in ('上外', '上端', '帯内', '下端', '下外', '未知'):
                group_s = [row for row in adopted if where[row['slot_id']] == position]
                group_l = [row for row in ll if where[row['slot_id']] == position]
                group_c = [row for row in cc if where[row['slot_id']] == position]
                result['場所別'][policy][period][position] = {'純候補': len(group_s), '入口': R68.entry_summary(group_l, period, source),
                    '実完結': len(group_c), '費用別観測円': {str(fee): close_sum(group_c, fee) for fee in (0, 5, 10)}}
    # ----------------------------------------
    # 集合の共通/追加/除外と、同じ実取得だけの出口差を別算する。
    for left, right in (('O0', 'L0'), ('O0', 'L1'), ('P0', 'L1'), ('L0', 'L1')):
        result['比較'][left + '対' + right] = {}
        for period in PERIODS:
            a = {row['slot_id']: row for row in slots[left] if source.span(row['session']) == period}
            b = {row['slot_id']: row for row in slots[right] if source.span(row['session']) == period}
            if set(a) != set(b):
                raise ValueError('比較の全予定集合不一致')
            counts = Counter()
            for identity in a:
                x, y = a[identity]['side'], b[identity]['side']
                counts['双方待機' if not x and not y else '左のみ' if x and not y else '右のみ' if y and not x else '同方向' if x == y else '反対切替'] += 1
            ca = {(row['slot_id'], row['side']): row for account in accounts[left] if source.span(account['session']) == period for row in account['closed']}
            cb = {(row['slot_id'], row['side']): row for account in accounts[right] if source.span(account['session']) == period for row in account['closed']}
            common, drop, add = sorted(set(ca) & set(cb)), sorted(set(ca) - set(cb)), sorted(set(cb) - set(ca))
            exact = [identity for identity in common if all(ca[identity][key] == cb[identity][key] for key in ('entry_time', 'entry_line', 'entry_price'))]
            result['比較'][left + '対' + right][period] = {'純': dict(counts),
                '準備共通': sum(a[key]['ready'] and b[key]['ready'] for key in a),
                '左準備のみ': sum(a[key]['ready'] and not b[key]['ready'] for key in a), '右準備のみ': sum(b[key]['ready'] and not a[key]['ready'] for key in a),
                '実': {'左完結': len(ca), '右完結': len(cb), '共通元枠同方向': len(common), '左のみ': len(drop), '右のみ': len(add),
                    '共通元枠差額5': float(sum((Decimal(str(cb[key]['pnl5'])) - Decimal(str(ca[key]['pnl5'])) for key in common), Decimal(0))),
                    '左のみ額5': close_sum([ca[key] for key in drop], 5), '右のみ額5': close_sum([cb[key] for key in add], 5),
                    '厳密同新規': len(exact), '厳密同新規出口差5': float(sum((Decimal(str(cb[key]['pnl5'])) - Decimal(str(ca[key]['pnl5'])) for key in exact), Decimal(0)))}}
    return result


# ----------------------------------------
def run(viewer_url: str | None = None) -> dict:
    """保存済み出生参照・親波・新92運用を正式に一度監査する。

    引数: viewer_url(str|None)はViewer URL。
    返り値: dictは排他的に保存する公式proof。市場戦略・新独立測定・fitを起動しない。
    """
    destination = STUDY / '保存物確認.json'
    if destination.exists():
        raise FileExistsError('76の保存監査は保存済み。再起動しない')
    source, _, summary = A.helpers()
    audit = source.Audit()
    result, fixed, inputs = [source.read(STUDY / name) for name in ('結果.json', '固定.json', '入力台帳.json')]
    old_result, old_proof, ledger = [source.read(path) for path in (OLD / '結果.json', OLD / '保存物確認.json', LEDGER)]
    stage, preflight = [source.read(path) for path in (STAGE, WORK.parent / '入力確認.json')]
    files = [STUDY / name for name in ('結果.json', '固定.json', '条件.json', '入力台帳.json', '一覧.resources.json')]
    files += [WORK / name for name in ('出生ATR参照.jsonl.gz', '技法観測.jsonl.gz', '定時判断と運用.jsonl.gz', '入口先着.jsonl.gz', '実行完了.json')]
    files += [OLD / name for name in ('結果.json', '保存物確認.json', '固定.json', '一覧.resources.json')]
    files += [OLDWORK / name for name in ('参照帯.json', '定時判断と運用.jsonl.gz', '入口先着.jsonl.gz', '実行完了.json')]
    files += [SOURCE_WORK / '定時判断と運用.jsonl.gz', SOURCE_STUDY / '固定.json', R74.IMMEDIATE,
        LEDGER, STAGE, WORK.parent / '入力確認.json', source.MANIFEST, FRAMES, Path(__file__), HERE / '監査仕様.md']
    before = {path.relative_to(ROOT).as_posix(): source.sha(path) for path in files}
    for name, digest in fixed['ファイルSHA256'].items():
        audit.check('76固定:' + name, source.sha(ROOT / name), digest)
        before[name] = digest
    for group in ('参照SHA256', 'cacheSHA256'):
        for name, digest in inputs[group].items():
            audit.check('76事前入力:' + name, source.sha(ROOT / name), digest)
            before[name] = digest
    audit.check('75完了台帳SHA', source.sha(LEDGER), LEDGER_SHA)
    audit.check('75完了対象数', len(ledger['成果物SHA256']), 190)
    for name, digest in ledger['成果物SHA256'].items():
        audit.check('75完了対象不変:' + name, source.sha(ROOT / name), digest)
        before[name] = digest
    audit.check('75成功proof結果bind', (old_proof['全件一致'], old_proof['不一致数'], old_proof['不一致'], old_proof['結果SHA256']), (True, 0, [], source.sha(OLD / '結果.json')))
    audit.check('75単一完了bind', source.read(OLDWORK / '実行完了.json')['結果SHA256'], source.sha(OLD / '結果.json'))
    audit.check('76単一完了bind', source.read(WORK / '実行完了.json')['結果SHA256'], source.sha(STUDY / '結果.json'))
    audit.check('76入力段階SHA', source.sha(STAGE), STAGE_SHA)
    audit.check('76入力段階成功', (stage['試行'], stage['入力']['成功'], stage['入力']['全予定']), (76, True, 1702))
    audit.check('76入力段階の正本全文', stage['入力'], preflight)
    for name, digest in stage['不変とする入力SHA256'].items():
        audit.check('入力段階後の不変:' + name, source.sha(ROOT / name), digest)
        before[name] = digest
    audit.check('76固定bind', (result['試行'], result['固定SHA256'], result['全66場既使用']), (76, source.sha(STUDY / '固定.json'), True))
    audit.check('76新処理範囲', tuple(result[key] for key in ('新fit', '新分類器fit', '新モデル', '新独立測定', '新運用数', '保存参照運用数', 'Viewer資源')), (0, 0, 0, 0, 92, 92, 184))
    audit.check('76政策集合', set(result['候補']), set(ALL_POLICIES))
    audit.check('76設定全文', result['設定'], source.read(STUDY / '条件.json'))
    audit.check('元66台帳SHA', source.sha(source.MANIFEST), inputs['参照SHA256'][source.MANIFEST.relative_to(ROOT).as_posix()])
    entries = source.read(source.MANIFEST)['entries']
    evaluated = [row['session'] for row in entries[20:]]
    audit.check('既使用66場', len(entries), 66)
    audit.check('同46場', result['評価場'], evaluated)
    audit.check('保存参考同46場', old_result['評価場'], evaluated)
    base = {row['session']: row for row in source.json_rows(SOURCE_WORK / '定時判断と運用.jsonl.gz') if row['policy'] == 'Q0'}
    reference = {(row['session'], row['policy']): row for row in source.json_rows(OLDWORK / '定時判断と運用.jsonl.gz') if row['policy'] in REFERENCES}
    audit.check('保存73全46判断', list(base), evaluated)
    audit.check('参考75全92運用', set(reference), {(session, policy) for session in evaluated for policy in REFERENCES})
    identities = [row['slot_id'] for session in evaluated for row in base[session]['slots']]
    audit.check('1702予定ID一意', (len(identities), len(set(identities))), (1702, 1702))
    bank, quotes = read_immediate(set(identities), source, audit)
    # ----------------------------------------
    # 出生ATRはTR/Wilderの独立算法、親波は区間走査で当時状態を再構成する。
    sessions, histories = source_sessions(entries, source, audit)
    expected_atr = ATR.derive_atr(sessions)
    saved_atr = {}
    for row in source.json_rows(WORK / '出生ATR参照.jsonl.gz'):
        if row['session'] in saved_atr:
            raise ValueError('出生ATR場の重複')
        saved_atr[row['session']] = row['package']
    audit.check('出生ATR66場順', list(saved_atr), [row['session'] for row in entries])
    for session, package in expected_atr.items():
        audit.check('出生ATR全値と源指紋:' + session, INPUT.canonical(saved_atr[session]), INPUT.canonical(package))
    observations, observed_order = {}, []
    for row in source.json_rows(WORK / '技法観測.jsonl.gz'):
        if row['slot_id'] in observations:
            raise ValueError('観測元枠の重複')
        observations[row['slot_id']] = row['observation']
        observed_order.append((row['session'], row['slot_id']))
    audit.check('観測全1702予定順', observed_order, [(session, row['slot_id']) for session in evaluated for row in base[session]['slots']])
    bands = source.read(OLDWORK / '参照帯.json')
    chosen = {policy: {} for policy in POLICIES}
    counts = Counter({'出生ATR場': len(expected_atr), '出生ATR行': sum(len(package['rows']) for package in expected_atr.values())})
    for session in evaluated:
        package = expected_atr[session]
        indexed = {row['index']: row for row in package['rows']}
        prior = prior_for(session, bands)
        for slot in base[session]['slots']:
            if slot['ready']:
                current = slot['feature']['base']['base']['sources']['current']
                row = indexed[current['index']]
                INPUT.bind_atr([{name: current[name] for name in INPUT.SOURCE}], [row], slot)
                units = INPUT.exact(row['atr']) / 5
                distance = min(125, max(5, -(-units.numerator // units.denominator) * 5))
                audit.check('現在ATR/Dと旧73同値', (row['ready'], row['atr'], distance), (True, slot['atr'], slot['D']))
                counts['判断ATR同値'] += 1
            obs = INPUT.derive(slot, histories[session], visible_atr(package, slot), quotes[slot['slot_id']], prior)
            audit.check('親波/複合/場所の全観測', INPUT.canonical(observations[slot['slot_id']]), INPUT.canonical(obs))
            for policy in POLICIES:
                chosen[policy][slot['slot_id']] = INPUT.choose(slot, obs, policy)
            left, right = chosen['L0'][slot['slot_id']], chosen['L1'][slot['slot_id']]
            audit.check('L0TはL1同純判断', not left['side'] or all(left[key] == right[key] for key in PURE), True)
            audit.check('L1だけの採用はR', not right['side'] or left['side'] != 0 or right['formation'] == 'R', True)
            counts['全予定'] += 1
            counts['基礎準備'] += bool(slot['ready'])
            counts['局所準備'] += bool(obs['ready'])
            counts['L0方向'] += bool(left['side'])
            counts['L1方向'] += bool(right['side'])
            counts['R追加'] += bool(right['side'] and not left['side'])
    expected_preflight = {'試行': 76, '成功': True, **dict(counts),
        '観測SHA256': source.sha(WORK / '技法観測.jsonl.gz'), '出生ATR参照SHA256': source.sha(WORK / '出生ATR参照.jsonl.gz'),
        'コードSHA256': {path.relative_to(ROOT).as_posix(): source.sha(path) for path in (HERE / '出生ATR.py', HERE / '出生ATR監査.py', HERE / '入力.py', HERE / '入力監査.py')},
        '新fit': 0, '新独立測定': 0, '新場内運用': 0, 'ラベルによる採否選択': False}
    audit.check('76損益前入力の全文別算', preflight, expected_preflight)
    # ----------------------------------------
    # 以降は新92保存運用だけ原BBO監査し、参考92は成功保存値を再集計する。
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
            audit.check('参考資源は同じ保存参照', resource_map[row['session'], row['method_id']], row)
    accounts, labels, slots = ({policy: [] for policy in ALL_POLICIES} for _ in range(3))
    for row in source.json_rows(OLDWORK / '入口先着.jsonl.gz'):
        if row['policy'] in REFERENCES:
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
        audit.check('75成功cachebind', digest, old_proof['キャッシュSHA256'][cache_path])
        audit.check('新二政策順', [block['policy'] for block in detail[session]], list(POLICIES))
        for block in detail[session]:
            policy = block['policy']
            selected = [chosen[policy][identity] for identity in old_slots]
            audit.check('新純20項目全文', block['slots'], selected)
            audit.check('評価phase保持', block['phase'], base[session]['phase'])
            audit.check('原板入力品質', block['input_quality'], quality)
            slots[policy].extend(selected)
            for slot in selected:
                if slot['side']:
                    audit.check('採用55気配の原行6項目同値', INPUT.canonical(quotes[slot['slot_id']]), INPUT.canonical(R55.decision_event(slot, tape)))
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
                    audit.check('実entryの旧55約定可否', prior['filled'], True)
                    audit.check('実entryと旧55全3属性', tuple(order['fill_' + key] for key in ('time', 'line', 'price')), tuple(prior['entry_' + key] for key in ('time', 'line', 'price')))
                    entry_matches += 1
            for closed in operation['closed']:
                single = bank['即時'][closed['slot_id'], closed['side']]['closed']
                audit.check('実closedの旧55件数', len(single) if single is not None else None, 1)
                if single:
                    audit.check('実closedの全非ID型/値', R55.strict_close_equal(closed, single[0]), True)
                closed_matches += 1
            resource = resource_map[session, policy]
            path = ROOT / resource['pnl_path']
            audit.check('新Viewer正規パス', path.resolve(), (STUDY / 'viewer' / (policy + '_' + session + '.trades.jsonl')).resolve())
            audit.check('新Viewer全約定', list(source.json_rows(path)), operation['trades'])
            audit.check('新Viewer元市場', resource['market_path'], entry['source_path'])
            audit.check('新Viewer商品/単位', (resource['symbol'], resource['product'], resource['point_value'], resource['pnl_format'], resource['pnl_basis']), ('NK225', 'NK225micro', 10, 'trades', 'net'))
            viewer_pins[path.relative_to(ROOT).as_posix()] = source.sha(path)
            summaries.append({'場': session, '候補': policy, '期間': source.span(session), '入力品質': quality, '運用品質': operation['quality'], '運用集計': operation['metrics']})
        print(session + ' 同原因親波/55結合/即時BBO/保護/会計を照合', flush=True)
    audit.check('76場別新92全文', result['場別'], summaries)
    audit.check('76主の厳密結合件数', result['検査'], {'実独立新規一致': entry_matches, '実独立完結一致': closed_matches})
    audit.check('新先着全文と保存順', list(source.json_rows(WORK / '入口先着.jsonl.gz')), [row for policy in POLICIES for row in labels[policy]])
    expected = expected_summary(accounts, labels, slots, observations, source, summary)
    for key, value in expected.items():
        audit.check('76独立六集計:' + key, result[key], value)
    for policy in REFERENCES:
        for group in ('候補', '利益保護'):
            audit.check('75参考再集計全文:' + policy + group, result[group][policy], old_result[group][policy])
    audit.check('76採用', result['採用'], [policy for policy in POLICIES if all(expected['候補'][policy][period]['同時適格'] for period in PERIODS[:2])])
    audit.check('76詳細四系列', set(result['詳細']), {'出生ATR参照.jsonl.gz', '技法観測.jsonl.gz', '定時判断と運用.jsonl.gz', '入口先着.jsonl.gz'})
    for name, digest in result['詳細'].items():
        audit.check('76詳細SHA:' + name, source.sha(WORK / name), digest)
    api = check_api(viewer_url, resources, [row for policy in ALL_POLICIES for row in accounts[policy]], source, audit)
    for name, digest in {**before, **cache_pins, **viewer_pins}.items():
        audit.check('監査中参照不変:' + name, source.sha(ROOT / name), digest)
    payload = {'試行': 76, '確認日時': datetime.now(source.JST).isoformat(), '全件一致': audit.bad == 0,
        '照合項目数': audit.count, '不一致数': audit.bad, '不一致': audit.examples, '結果SHA256': source.sha(STUDY / '結果.json'),
        '新主処理import': False, '新入力import': False, '新出生ATR本体import': False, 'Engine期待値import': False,
        '市場戦略再生': False, '本物fit再実行': False, '旧73特徴再構成': False, '出生ATR独立再構成': True,
        '親波独立再構成': True, '69条件銀行読取': False, '新fit': 0, '新独立測定': 0,
        '新運用数': 92, '保存参照運用数': 92, '予定枠数': 1702, '入力再照合': dict(counts),
        '同一独立新規数': entry_matches, '同一独立完結数': closed_matches,
        '参照SHA256': before, 'キャッシュSHA256': cache_pins, '新Viewer約定SHA256': viewer_pins, 'ViewerAPI': api,
        '検証範囲': '75完了190対象/成功証明と入力段階11指紋、元66場SOURCEから独立TR/Wilder出生ATR、同1702枠の親波・T/R・現在資格・場所・純20項目、旧55全予定両方向/原ready未計測None契約、採用方向の旧55先着と独立closed全非ID、新92の全予定/原BBO/TTL/保護/現金/保有品質、参考75 O0/P0の92保存同値・全六集計・Viewer184と新2代表。',
        '限定': '全66場既使用。旧73の64特徴算術は再計算しない。旧55の原準備と旧73readyを同一視せず、原未準備のbarrier存在を独立回収存在へ読み替えない。既存先着/回収をSHA固定再用し、新測定や戦略再生は0。出生ATRの独立再計算は価格SOURCEに限定し、新15分/量は計算しない。親/形成/遅いf/resetは全履歴の反復観測を含み、独立機会ではない。観測額と品質nullを区別する。心理因果/原典再現/未見利益/70%保証ではない。'}
    with destination.open('x', encoding='utf-8') as stream:
        stream.write(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
    return payload


# ----------------------------------------
def self_test() -> dict:
    """架空親波・有取引六集計・旧55欠測契約を出力実装へ接続する。

    引数: なし。
    返り値: dictは成功/人工群数/照合数。新主/Engineは人工の出力側だけ。
    """
    source, _, summary = A.helpers()
    audit = source.Audit()
    engine = R74.load_fixed(ROOT / 'scripts/定時帯反応/運用.py', '76人工出力側49')
    main = R74.load_fixed(HERE / '検証.py', '76人工出力側主集計')
    operations, accounts, labels, slots = ({p: [] for p in ALL_POLICIES} for _ in range(4))
    observations = {}
    for sample, (closes, desired) in enumerate((([100, 103, 106, 104, 106], 1), ([100, 103, 106, 98, 96], -1))):
        session = '2026-10-05_Day' if sample == 0 else '2026-10-06_Day'
        _, force, _, schedule = source.calendar(session)
        first = schedule[0]
        old, frames, prior, quote = INPUT.OLD.synthetic(closes, desired, desired)
        offset = first - frames[-1]['end']
        for frame in frames:
            frame.update(session=session, high=frame['close'] + 1, low=frame['close'] - 1)
            for key in ('start', 'end', 'confirm'):
                frame[key] += offset
        old.update(session=session, scheduled=first, time=first + 1, line=10000, slot_id=session + '|0', atr=100., D=100.)
        old['feature'].update(atr=100., D=100.)
        old['feature']['base']['base']['sources']['current'] = deepcopy(frames[-1])
        quote.update(now=old['time'], line=old['line'], last=closes[-1], bid=closes[-1] - 1, ask=closes[-1] + 1)
        atr_rows = [{**{key: deepcopy(frame[key]) for key in INPUT.ATR_CLOCK},
            'source_sha256': hashlib.sha256(INPUT.canonical(frame).encode('utf-8')).hexdigest(),
            'atr': 100. if i == len(frames) - 1 else 5., 'valid': True, 'numeric_count': 30,
            'reset_reasons': [], 'ready': True, 'reason': '出生ATR準備済み'} for i, frame in enumerate(frames)]
        obs = INPUT.derive(old, frames, atr_rows, quote, None)
        audit.check('人工親波はT/R実採用', (obs['side'], obs['selected']['kind']), (desired, 'T' if desired == 1 else 'R'))
        base = [old]
        for i, scheduled in enumerate(schedule[1:], 1):
            base.append({'scheduled': scheduled, 'time': scheduled, 'line': None, 'side': 0, 'role': '待機', 'atr': None, 'D': None,
                'reason': '判断時計欠測', 'ready': False, 'slot_id': session + '|' + str(i), 'session': session, 'feature': {'ready': False}})
        for i, slot in enumerate(base):
            observations[slot['slot_id']] = obs if i == 0 else INPUT.derive(slot, [], [], None, None)
        entry = (quote['ask'] if desired == 1 else quote['bid']) + 11 * desired
        events = [deepcopy(quote)]
        if desired == 1:
            events.append({'now': first + 2, 'line': 10001, 'last': entry - 1, 'bid': entry - 2, 'ask': entry, 'valid': True})
        else:
            events.append({'now': first + 2, 'line': 10001, 'last': entry + 1, 'bid': entry, 'ask': entry + 2, 'valid': True})
        for step, profit in enumerate((-1, 17, 0, 0), 3):
            mark = entry + desired * profit
            bid, ask = (mark, mark + 2) if desired == 1 else (mark - 2, mark)
            events.append({'now': first + step, 'line': 9999 + step, 'last': (bid + ask) / 2, 'bid': bid, 'ask': ask, 'valid': True})
        events.append({'now': force + 1, 'line': 10006, 'last': 100., 'bid': 99., 'ask': 101., 'valid': True})
        tape = R74.artificial_tape(events, source)
        for policy in ALL_POLICIES:
            applied = policy if policy in POLICIES else 'L1'
            selected = [INPUT.choose(slot, observations[slot['slot_id']], applied) for slot in base]
            for row in selected:
                row['policy'] = policy
                if policy in REFERENCES:
                    row.pop('parent_id', None)
            pure = [{key: row[key] for key in PURE} for row in selected]
            operation = engine.replay(events, pure, session, policy)
            block = {'session': session, 'policy': policy, 'slots': selected, 'conditions': {}, 'operation': operation}
            account = R74.check_immediate(block, tape, source, audit)
            operations[policy].append(operation)
            accounts[policy].append(account)
            slots[policy].extend(selected)
            for closed in operation['closed']:
                audit.check('人工保護後同値費用負け', (closed['arm'], closed['entry_price'], closed['exit_price'], closed['pnl5']), (True, entry, entry, -122.))
                labels[policy].append({'session': session, 'slot_id': closed['slot_id'], 'policy': policy, 'side': desired, 'role': '順行',
                    'time': first + 1, 'line': 10000, 'filled': True, 'outcome': '250', 'entry_time': closed['entry_time'],
                    'entry_line': closed['entry_line'], 'entry_price': closed['entry_price'], 'end_time': force, 'end_line': 10006})
    before = INPUT.canonical((operations, accounts, labels, slots, observations))
    calculated = expected_summary(accounts, labels, slots, observations, source, summary)
    audit.check('有取引六集計の全文', main.summarize(operations, labels, slots, observations), calculated)
    audit.check('六集計の入力不変', INPUT.canonical((operations, accounts, labels, slots, observations)), before)
    audit.check('L0Tだけ/L1TRの完結分母', (calculated['候補']['L0']['学習']['運用']['完結数'], calculated['候補']['L1']['学習']['運用']['完結数']), (1, 2))
    audit.check('R追加は同元枠Tではない', calculated['比較']['L0対L1']['学習']['実']['右のみ'], 1)
    audit.check('前帯未知を待機資格へ使わない', calculated['場所別']['L1']['学習']['未知']['純候補'], 2)
    audit.check('T/Rの空群と期間保持', calculated['形成別']['L0']['学習']['R']['入口']['率'], None)
    audit.check('先着成功と実旗後赤字を別計数', (calculated['利益保護']['L1']['学習']['先着250前の実退出'], calculated['利益保護']['L1']['学習']['同値']), (2, 2))
    caution = deepcopy(accounts)
    caution['L1'][0]['caution'] = True
    audit.check('品質注意期は観測を残し全体確定null', expected_summary(caution, labels, slots, observations, source, summary)['候補']['L1']['学習']['運用']['全体確定額円'], {'0': None, '5': None, '10': None})
    # ----------------------------------------
    # Noneは元55の未準備だけに許す。先着が残っていても独立完結へ補完しない。
    identity = '人工未準備'
    fake_rows = [{'session': '2026-10-05_Day', 'slot_id': identity, 'scheduled': 1., 'time': 1., 'line': 1,
        'side': side, 'ready': False, 'atr': None, 'D': None, 'barrier': {'filled': False, 'outcome': '未約定'},
        'operation': None, 'decision_bbo': None} for side in (1, -1)]
    relative = R74.IMMEDIATE.relative_to(ROOT).as_posix()
    mock = SimpleNamespace(sha=lambda path: '人工SHA', read=lambda path: {'ファイルSHA256': {relative: '人工SHA'}}, json_rows=lambda path: iter(fake_rows))
    fake_bank, fake_quotes = read_immediate({identity}, mock, audit)
    audit.check('未準備の先着残存と回収None', (fake_bank['即時'][identity, 1]['barrier']['outcome'], fake_bank['即時'][identity, 1]['closed'], fake_quotes[identity]), ('未約定', None, None))
    fake_rows[0]['ready'] = True
    probe = source.Audit()
    read_immediate({identity}, mock, probe)
    audit.check('readyTrueの偽Noneは検出', probe.bad > 0, True)
    return {'成功': audit.bad == 0, '人工成功': audit.bad == 0, 'テスト件数': 9, '照合項目数': audit.count,
        '不一致数': audit.bad, '不一致': audit.examples, '本物入力読取': False, '本物fit': 0,
        '市場戦略再生': False, '新独立測定': 0, '新主/Engineは人工出力側だけ': True,
        '別人工': '入力監査60系列306比較と出生ATR監査27群30255比較は別欄。重複加算しない'}


def validate(viewer_url: str | None = None) -> dict:
    """root用の正式監査を別名で公開する。

    引数: viewer_url(str|None)はViewer URL。
    返り値: dictは一度だけ保存した公式proof。
    """
    return run(viewer_url)


def check(viewer_url: str | None = None) -> dict:
    """同じ正式監査をcheck名で公開する。

    引数: viewer_url(str|None)はViewer URL。
    返り値: dictは公式proof。二重起動を許さない。
    """
    return run(viewer_url)


def main() -> None:
    """人工又はrootの正式監査を排他的に起動し、小型要約を返す。

    引数: CLIの--run/--self-test(bool)と--viewer-url(str|None)は段階とViewer。
    返り値: None。正式proof全文はJSONへ保存しstdoutへ展開しない。
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
