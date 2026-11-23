"""77の終値反応確認を、固定76の独立区間走査から別に再構成する。"""

from copy import deepcopy
import hashlib
import importlib.util
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
LEGACY_PATH = ROOT / 'scripts/局所波の出生と切替/入力監査.py'
LEGACY_SHA = '1985e2b651e3a3058b7d3b380c2bc1a35499a1ffca74ba7b983b4f23ccf752ae'
POLICIES = ('E0', 'E1')
POLICY_MAP = {'E0': 'L0', 'E1': 'L1'}
EXTRA = ('confirmation_rule', 'confirmation_previous', 'confirmation_line')


def load_legacy():
    """固定76の独立した区間走査と公開辞書の純補助を読む。

    引数: なし。
    返り値: ModuleTypeは停止版。新I・主・Engineを読まない。
    """
    if hashlib.sha256(LEGACY_PATH.read_bytes()).hexdigest() != LEGACY_SHA:
        raise ValueError('76独立区間走査の指紋差')
    spec = importlib.util.spec_from_file_location('77独立監査の固定76区間', LEGACY_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


LEGACY = load_legacy()
OLD, SOURCE, PURE = LEGACY.OLD, LEGACY.SOURCE, LEGACY.PURE
ATR_CLOCK = LEGACY.ATR_CLOCK
finite, exact, canonical = LEGACY.finite, LEGACY.exact, LEGACY.canonical
bind_atr = LEGACY.bind_atr


# ----------------------------------------
def scan_reactions(slot: dict, prefix: list[dict], atrs: list[dict]) -> dict:
    """出生・親・Rの区間を保持し、最初r以後のT確認だけを再走査する。

    引数: slot(dict)は判断、prefix/atrs(list[dict])は同順の当時可視入力。
    返り値: dictは独立区間記録。新Machineの継承・呼出・ソース置換を使わない。
    """
    scan = LEGACY.scan_sections(slot, prefix, atrs)
    for record in scan['records']:
        events = [event for event in record['events'] if event[0] not in ('T_k', 'T_cancel')]
        r_index, side = record['r'], record['side']
        record['T_k'], record['T_end'] = None, None
        if r_index is not None:
            r = prefix[r_index]
            premise = max(record['origin'], r['low']) if side == 1 else min(record['origin'], r['high'])
            stop = record['f'] if record['f'] is not None else len(prefix)
            terminal = record['end']
            if terminal is not None and terminal['at']['index'] is not None:
                stop = min(stop, next(i for i, row in enumerate(prefix) if row['index'] == terminal['at']['index']))
            for i in range(r_index + 1, stop):
                current, previous = prefix[i], prefix[i - 1]
                progress = side * (exact(current['close']) - exact(previous['close']))
                holds = side * (exact(current['close']) - exact(premise)) > 0
                if record['T_k'] is None:
                    if progress > 0 and holds:
                        record['T_k'] = i
                        events.append(('T_k', LEGACY.point(current), None))
                elif not holds:
                    record['T_end'] = {'at': LEGACY.point(current), 'reason': 'T確認後の前提線終値否定', 'status': '取消'}
                    events.append(('T_cancel', LEGACY.point(current), None))
                    break
        if record['T_end'] is None:
            if record['f'] is not None:
                record['T_end'] = {'at': LEGACY.point(prefix[record['f']]), 'reason': '起点の終値喪失', 'status': '取消'}
            elif record['end'] is not None:
                terminal = record['end']
                record['T_end'] = {name: deepcopy(terminal[name]) for name in ('at', 'reason', 'status')}
        record['events'] = sorted(events, key=lambda event: tuple(event[1]['key']))
    return scan


def public_history(scan: dict, prefix: list[dict], slot: dict) -> tuple:
    """公開親Tへ確認直前足と固定終値を加え、同じ形成一覧へ反映する。

    引数: scan(dict)は独立走査、prefix(list[dict])/slot(dict)は出典と判断。
    返り値: tuple[list,list]は親と形成。Rへ新フィールドを混ぜない。
    """
    parents, formations = LEGACY.public_history(scan, prefix, slot)
    for record, parent in zip(scan['records'], parents):
        index = record['T_k']
        previous = deepcopy(prefix[index - 1]) if index is not None else None
        parent['T'].update(confirmation_rule='終値反応', confirmation_previous=previous,
            confirmation_line=previous['close'] if previous is not None else None)
    return parents, formations


def parent_invariant(observation: dict) -> dict:
    """変更対象Tとその親表示状態を除き、不変な出生・親・Rを抜き出す。

    引数: observation(dict)は新旧共有観測。
    返り値: dictは比較用投影。T確認の差をRの差として数えない。
    """
    parents = [{key: deepcopy(value) for key, value in parent.items() if key not in ('T', 'status', 'trace')}
        for parent in observation['parents']]
    return {'parents': parents, 'base_ready': observation['base_ready'], 'ready': observation['ready'],
        'source_count': observation['source_count'], 'source_sha256': observation['source_sha256'],
        'atr_source_sha256': observation['atr_source_sha256'], 'history': deepcopy(observation['history']),
        'band': deepcopy(observation['band']), 'location': deepcopy(observation['location'])}


# ----------------------------------------
def derive(old_slot: dict, history_sources: list[dict], birth_atr_rows: list[dict], decision_quote: dict | None, prior_band: dict | None) -> dict:
    """当時の親区間に終値反応確認を独立適用し、現資格と政策を構成する。

    引数: old_slot(dict)は旧73判断、history_sources/birth_atr_rows(list)は可視価格/固定76出生ATR、decision_quote/prior_bandは旧気配/診断帯。
    返り値: dictはE0/E1共通観測。新I・主・出生ATR本体・Engineを読まない。
    """
    # 76の入力契約を先に検査する。新しい価格・指標・ATR算術は加えない。
    baseline = LEGACY.derive(old_slot, history_sources, birth_atr_rows, decision_quote, prior_band)
    output = deepcopy(baseline)
    if not baseline['base_ready']:
        output['selected_by_policy'] = {policy: deepcopy(baseline['selected_by_policy'][legacy]) for policy, legacy in POLICY_MAP.items()}
        return output
    prefix = OLD.visible_prefix(old_slot, history_sources, old_slot['feature'])
    atrs = bind_atr(prefix, birth_atr_rows, old_slot)
    scan = scan_reactions(old_slot, prefix, atrs)
    parents, formations = public_history(scan, prefix, old_slot)
    parent = parents[-1] if parents and parents[-1]['active'] else None
    normal = OLD.quote_view(old_slot, decision_quote)
    ready = scan['prepared'] and normal
    reason = parent['status'] if parent else parents[-1]['terminal']['reason'] if parents and not scan['buffer'] else '出生待ち'
    if not scan['prepared']:
        reason = '出生準備待ち'
    elif not normal:
        reason = '現在BBO又はLastの観測不足'
    elif scan['rejected'] and scan['rejected'][-1]['b']['index'] == prefix[-1]['index']:
        reason = '出生公開が寿命後'
    candidates = [deepcopy(row) for row in formations if row['active']]
    if len(candidates) > 1:
        raise ValueError('一親で複数activeの矛盾')
    values, qualifications = OLD.values_for(old_slot['feature']), {}
    for candidate in candidates:
        candidate.update(k_age_seconds=old_slot['time'] - candidate['k']['confirm'],
            k_end_age_seconds=old_slot['scheduled'] - candidate['k']['end'],
            tip_distance=float(candidate['side'] * (exact(parent['tip_before_r']['price']) - exact(candidate['k']['close']))))
        if normal:
            qualifications[candidate['id']] = LEGACY.eligible_price(candidate, values[str(candidate['side'])], decision_quote)
    if candidates and normal and not any(row['qualified'] for row in qualifications.values()):
        reason = '局所波の現在複合条件不適格'
    output.update(ready=ready, reason=reason, parents=parents, formations=formations,
        candidates=candidates, qualifications=qualifications, selected_by_policy={})
    for policy, legacy in POLICY_MAP.items():
        policy_reason = 'R形成はE0で採用対象外' if policy == 'E0' and candidates and candidates[0]['kind'] == 'R' and ready else reason
        output['selected_by_policy'][policy] = LEGACY.choose_candidate(candidates, qualifications, legacy, ready, policy_reason)
    output.update({key: deepcopy(output['selected_by_policy']['E1'][key]) for key in ('side', 'role', 'selected', 'reason')})
    if canonical(parent_invariant(output)) != canonical(parent_invariant(baseline)):
        raise AssertionError('T確認の変更が出生・親・R又は準備へ波及')
    return output


def choose(slot: dict, observation: dict, policy: str) -> dict:
    """E政策を局所的な旧Lビューへ写し、Tの確認出典だけを追加する。

    引数: slot/observation(dict)は元判断と独立観測、policy(str)はE0/E1。
    返り値: dictは純10項目と由来。T採用時だけ確認3フィールドを持つ。
    """
    if policy not in POLICY_MAP:
        raise ValueError('77政策はE0/E1のみ')
    local = deepcopy(observation)
    local['selected_by_policy'] = {legacy: deepcopy(observation['selected_by_policy'][name]) for name, legacy in POLICY_MAP.items()}
    result = LEGACY.choose(slot, local, POLICY_MAP[policy])
    result['policy'] = policy
    selected = observation['selected_by_policy'][policy]['selected']
    if selected is not None and selected['kind'] == 'T':
        result.update({name: deepcopy(selected[name]) for name in EXTRA})
    return result


# ----------------------------------------
def self_test() -> dict:
    """架空入力だけで新Iと別区間走査、T変更とR不変を全文比較する。

    引数: なし。
    返り値: dictは成功/系列数/照合数/不一致数。新Iは人工出力側だけで読む。
    """
    implementation_path = HERE / '入力.py'
    spec = importlib.util.spec_from_file_location('77人工出力側入力', implementation_path)
    implementation = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(implementation)
    legacy_spec = importlib.util.spec_from_file_location('77架空材料の固定76入力', ROOT / 'scripts/局所波の出生と切替/入力.py')
    fixture = importlib.util.module_from_spec(legacy_spec)
    legacy_spec.loader.exec_module(fixture)
    count = series = 0

    def difference(left: object, right: object, path: str = '') -> str:
        """架空辞書の相違位置を小型表示する。

        引数: left/right(object)は比較値、path(str)は現在位置。
        返り値: strは最初の差。正式価格を扱わない。
        """
        if canonical(left) == canonical(right):
            return ''
        if isinstance(left, dict) and isinstance(right, dict) and set(left) == set(right):
            return next((value for key in left if (value := difference(left[key], right[key], path + '/' + key))), path)
        if isinstance(left, list) and isinstance(right, list) and len(left) == len(right):
            return next((value for i, item in enumerate(left) if (value := difference(item, right[i], path + '/' + str(i)))), path)
        return path + ': ' + str(left)[:250] + ' != ' + str(right)[:250]

    def check(actual: object, expected: object, label: str) -> None:
        """人工の全文・型・境界を固定JSONで比較する。

        引数: actual/expected(object)は比較値、label(str)は検査名。
        返り値: None。不一致時だけ理由を出す。
        """
        nonlocal count
        count += 1
        if canonical(actual) != canonical(expected):
            raise AssertionError(label + ' ' + difference(actual, expected))

    def compare(case: tuple, reject: bool = False) -> dict | None:
        """同じ架空5引数を新Iと独立算法へ渡す。

        引数: case(tuple)は人工入力、reject(bool)は両拒否期待。
        返り値: dict|Noneは独立観測。入力非改変も確認する。
        """
        nonlocal series
        series += 1
        before, outputs, errors = canonical(case), [], []
        for function in (derive, implementation.extract):
            try:
                outputs.append(function(*case))
                errors.append(False)
            except ValueError:
                outputs.append(None)
                errors.append(True)
        check(errors, [reject, reject], '拒否境界')
        if not reject:
            check(outputs[0], outputs[1], '共有観測全文')
            check(parent_invariant(outputs[0]), parent_invariant(LEGACY.derive(*case)), '出生/親/R/準備不変')
            for policy in POLICIES:
                check(choose(case[0], outputs[0], policy), implementation.choose(case[0], outputs[1], policy), '純射影:' + policy)
        check(canonical(case), before, '入力非改変')
        return outputs[0]

    paths = [[100], [100, 103], [100, 103, 106], [100, 100, 106], [100, 103, 104],
        [100, 103, 106, 104, 105], [100, 103, 106, 104, 104],
        [100, 103, 106, 104, 105, 103, 108],
        [100, 103, 106, 104, 102, 103, 104],
        [100, 103, 106, 104, 105, 98, 96],
        [100, 103, 106, 98, 96], [100, 103, 106, 98, 97, 98, 97],
        [100, 103, 106, 110, 111, 112, 114, 115, 116, 117, 98, 96],
        [100, 103, 106, 104, 105, 107, 108, 109, 110, 111, 112, 113, 114]]
    for closes in paths:
        case = fixture.synthetic(closes)
        compare(case)
        compare(fixture.reflected(case))
    early = fixture.synthetic([100, 103, 106, 104, 105])
    got = compare(early)
    check((got['selected']['k']['index'], got['selected']['confirmation_previous']['index'], got['selected']['confirmation_line']), (4, 3, 104), 'r高値未超でも終値反応を確認')
    check(LEGACY.derive(*early)['parents'][0]['T']['k'], None, '旧確認は未成立')
    check([name for name in EXTRA if name in choose(early[0], got, 'E0')], list(EXTRA), '採用T出典3項目')
    got = compare(fixture.synthetic([100, 103, 106, 104, 105, 103, 108]))
    check((got['parents'][0]['T']['k']['index'], got['parents'][0]['T']['cancel']['index'], got['side']), (4, 5, 0), '早期取消後に旧確認価格を超えても復活しない')
    # ----------------------------------------
    # k前の前提等号/一時喪失はorigin維持なら取消せず、最初の適合だけを使う。
    case = fixture.synthetic([100, 103, 106, 104, 102, 103, 104])
    got = compare(case)
    check(got['parents'][0]['T']['k']['index'], 6, '前提等号の反応足は確認せず次足で確認')
    check(got['parents'][0]['T']['confirmation_previous']['index'], 5, 'r以外のk直前足を固定')
    for i in (0, 3, 4):
        case = fixture.synthetic([100, 103, 106, 104, 105, 107, 109])
        case[2][i].update(atr=None, ready=False, reason='出生ATR未準備', numeric_count=13)
        compare(case)
    case = fixture.synthetic([100, 103, 106, 104, 103])
    check(compare(case)['parents'][0]['T']['k'], None, '終値増分非正かつ前提等号は未確認')
    case = fixture.synthetic([100, 103, 106, 104, 105])
    future = deepcopy(case[1][-1])
    future.update(index=99, start=future['end'], end=future['end'] + 180, confirm=None, high=float('nan'))
    case[1].append(future)
    check(compare(case), derive(*early), '未来不良suffix不変')
    for delta in (0., .01):
        case = deepcopy(early)
        case[0]['time'] = case[1][2]['end'] + 1620 + delta
        fixture.refresh(case)
        got = compare(case)
        check(bool(got['side']), delta == 0., '判断時刻期限の等号/strict超')
    case = fixture.synthetic([100, 103, 106, 98, 96], -1, -1)
    got = compare(case)
    check((got['selected']['kind'], any(name in got['selected'] for name in EXTRA), any(name in choose(case[0], got, 'E1') for name in EXTRA)), ('R', False, False), 'R観測/純入力にT新項目なし')
    case = deepcopy(early)
    case[0].update(ready=False, line=None)
    case[0]['feature']['ready'] = False
    got = compare((case[0], None, None, None, None))
    check(any(name in choose(case[0], got, 'E0') for name in EXTRA), False, 'WAIT純入力にT新項目なし')
    case = deepcopy(early)
    case[2][-1]['source_sha256'] = '0' * 64
    compare(case, True)
    case = deepcopy(early)
    case[2].pop()
    compare(case, True)
    return {'成功': True, '人工成功': True, 'テスト件数': series, '照合項目数': count, '不一致数': 0,
        '新Iimport': '人工出力側だけ', '本物入力読取': False, '出生ATR再build': 0,
        '市場戦略再生': False, '本物fit': 0, '先着損益読取': False, '旧大域値変更': False}
