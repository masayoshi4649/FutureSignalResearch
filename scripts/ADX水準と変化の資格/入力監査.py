"""78のT資格を、固定77の独立価格機械と別命題列から再構成する。"""

from copy import deepcopy
import hashlib
import importlib.util
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
LEGACY_PATH = ROOT / 'scripts/押戻し再開の確認幅/入力監査.py'
LEGACY_SHA = 'b681a6a2607ad3521c89c45cc9deb77c6604e94e64644da0938757b819daa5da'
POLICIES = ('S0', 'S1')
POLICY_MAP = {'S0': 'E0', 'S1': 'E1'}


def load_legacy():
    """停止版77の独立区間走査と公開辞書を明示SHAで読む。

    引数: なし。
    返り値: ModuleTypeは固定純補助。新I・主・Engineは読まない。
    """
    if hashlib.sha256(LEGACY_PATH.read_bytes()).hexdigest() != LEGACY_SHA:
        raise ValueError('固定77独立入力の変更')
    spec = importlib.util.spec_from_file_location('78固定77独立価格機械', LEGACY_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


LEGACY = load_legacy()
SOURCE, ATR_CLOCK, PURE = LEGACY.SOURCE, LEGACY.ATR_CLOCK, LEGACY.PURE
finite, exact, canonical = LEGACY.finite, LEGACY.exact, LEGACY.canonical
bind_atr = LEGACY.bind_atr


# ----------------------------------------
def structural_view(observation: dict) -> dict:
    """資格と最終選択以外の公開価格構造を全文投影する。

    引数: observation(dict)は新旧観測。
    返り値: dictは親/全形成/candidates/history/時計/準備/場所を含む不変部分。
    """
    return {key: deepcopy(value) for key, value in observation.items()
        if key not in ('qualifications', 'selected_by_policy', 'side', 'role', 'selected', 'reason')}


def continuation_qualification(candidate: dict, values: dict, quote: dict) -> dict:
    """Tの既知ADX水準と他技法を保ち、変化符号だけを要求しない。

    引数: candidate/values/quote(dict)は現在有効T・元float64値・判断気配。
    返り値: dictは資格/全拒否理由/DI役割/当時価格。未知を既知0へ補完しない。
    """
    side, di, background = candidate['side'], values['F01'], values['raw_background_direction']
    if candidate['kind'] != 'T':
        raise ValueError('T専用資格へRを渡した')
    tests = [(values['F02'] < 0, 'FastKの方向位置が負'),
        (values['F03'] <= 0, 'FastKの方向進行が非正'),
        (values['F07'] <= 0, '現在価格の方向進行が非正'),
        (background == 0 or di == 0, '上位DIが同値'),
        (di <= 0, '継続Tは上位DI同方向が必要'),
        (values['F51'] != 1 or values['F52'] != 1, '継続TのADX現値又は変化が未知'),
        (values['F47'] < .20, '継続TのADX20未満')]
    entry, premise = quote['ask'] if side == 1 else quote['bid'], candidate['premise_line']
    last_distance = side * (exact(quote['last']) - exact(premise))
    entry_distance = side * (exact(entry) - exact(premise))
    tests.extend(((last_distance <= 0, '現在Lastが前提線を否定'), (entry_distance <= 0, '現在新規BBOが前提線を否定')))
    reasons = [reason for failed, reason in tests if failed]
    return {'qualified': not reasons, 'role': '上位同値' if not di or not background else '順行' if di > 0 else '反転',
        'reasons': reasons, 'values': deepcopy(values), 'price': {'last': quote['last'], 'entry_proxy': entry,
            'premise_line': premise, 'last_distance': float(last_distance), 'entry_distance': float(entry_distance)}}


def derive(old_slot: dict, history_sources: list[dict], birth_atr_rows: list[dict], decision_quote: dict | None, prior_band: dict | None) -> dict:
    """77の可視親/形成を維持し、Tの現資格とS政策だけを独立再構成する。

    引数: old_slot(dict)は旧73判断、history_sources/birth_atr_rows(list)は全価格/可視76保存ATR、decision_quote/prior_bandは判断気配/診断帯。
    返り値: dictはS0/S1共有観測。新I・主・出生ATR本体を期待値に呼ばない。
    """
    baseline = LEGACY.derive(old_slot, history_sources, birth_atr_rows, decision_quote, prior_band)
    output = deepcopy(baseline)
    for candidate in output['candidates']:
        if candidate['kind'] == 'T' and candidate['id'] in output['qualifications']:
            prior = output['qualifications'][candidate['id']]
            output['qualifications'][candidate['id']] = continuation_qualification(candidate, prior['values'], decision_quote)
    reason = baseline['reason']
    if output['candidates'] and output['qualifications'] and not any(row['qualified'] for row in output['qualifications'].values()):
        reason = '局所波の現在複合条件不適格'
    output['selected_by_policy'] = {}
    for policy, legacy in POLICY_MAP.items():
        policy_reason = 'R形成はS0で採用対象外' if policy == 'S0' and output['candidates'] and output['candidates'][0]['kind'] == 'R' and output['ready'] else reason
        output['selected_by_policy'][policy] = LEGACY.LEGACY.choose_candidate(output['candidates'], output['qualifications'], 'L0' if legacy == 'E0' else 'L1', output['ready'], policy_reason)
    output.update({key: deepcopy(output['selected_by_policy']['S1'][key]) for key in ('side', 'role', 'selected', 'reason')})
    if canonical(structural_view(output)) != canonical(structural_view(baseline)):
        raise AssertionError('現資格変更が親/形成/候補/時計へ波及')
    for identity, prior in baseline['qualifications'].items():
        candidate = next(row for row in baseline['candidates'] if row['id'] == identity)
        if candidate['kind'] == 'R' and canonical(output['qualifications'][identity]) != canonical(prior):
            raise AssertionError('R資格が変更された')
        if prior['qualified'] and not output['qualifications'][identity]['qualified']:
            raise AssertionError('旧適格方向の喪失')
        if not prior['qualified'] and output['qualifications'][identity]['qualified']:
            if candidate['kind'] != 'T' or prior['values']['F48'] >= 0:
                raise AssertionError('既知ADX減速T以外の追加')
    return output


def choose(slot: dict, observation: dict, policy: str) -> dict:
    """S政策を深い局所コピーでEへ写し、77と同じ純射影を返す。

    引数: slot/observation(dict)は元定時と独立観測、policy(str)はS0/S1。
    返り値: dictは純10項目と由来、採用Tだけ確認3項目。元引数を変更しない。
    """
    if policy not in POLICY_MAP:
        raise ValueError('78政策はS0/S1のみ')
    local = deepcopy(observation)
    local['selected_by_policy'] = {legacy: deepcopy(observation['selected_by_policy'][name]) for name, legacy in POLICY_MAP.items()}
    result = LEGACY.choose(slot, local, POLICY_MAP[policy])
    result['policy'] = policy
    return result


# ----------------------------------------
def self_test() -> dict:
    """架空のADX水準・変化・既知性と不変価格機械を新Iへ比較する。

    引数: なし。
    返り値: dictは成功/系列数/照合数/差。新Iは人工の出力側だけ読む。
    """
    spec = importlib.util.spec_from_file_location('78人工出力側入力', HERE / '入力.py')
    implementation = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(implementation)
    fixture_spec = importlib.util.spec_from_file_location('78人工材料の固定76入力', ROOT / 'scripts/局所波の出生と切替/入力.py')
    fixture = importlib.util.module_from_spec(fixture_spec)
    fixture_spec.loader.exec_module(fixture)
    count = series = 0

    def check(actual: object, expected: object, name: str) -> None:
        """人工辞書の型を含めて同値を比べる。

        引数: actual/expected(object)は値、name(str)は検査名。
        返り値: None。差ではAssertionError。
        """
        nonlocal count
        count += 1
        if canonical(actual) != canonical(expected):
            raise AssertionError(name + ':' + str(actual)[:700] + ' != ' + str(expected)[:700])

    def compare(case: tuple, reject: bool = False) -> dict | None:
        """同一人工5引数を両実装へ渡し、不変構造と純包含も確認する。

        引数: case(tuple)は人工入力、reject(bool)は両拒否期待。
        返り値: dict|Noneは独立観測。入力は変更しない。
        """
        nonlocal series
        series += 1
        before, output, errors = canonical(case), [], []
        for function in (derive, implementation.extract):
            try:
                output.append(function(*case))
                errors.append(False)
            except ValueError:
                output.append(None)
                errors.append(True)
        check(errors, [reject, reject], '拒否境界')
        if not reject:
            check(output[0], output[1], '共有観測全文')
            baseline = LEGACY.derive(*case)
            check(structural_view(output[0]), structural_view(baseline), '親/形成/候補/時計全文不変')
            for policy, legacy in POLICY_MAP.items():
                chosen, old = choose(case[0], output[0], policy), LEGACY.choose(case[0], baseline, legacy)
                check(chosen, implementation.choose(case[0], output[1], policy), '純入力全文:' + policy)
                if old['side']:
                    check({key: chosen[key] for key in PURE}, {key: old[key] for key in PURE}, '元純方向包含')
        check(canonical(case), before, '入力非改変')
        return output[0]

    base = fixture.synthetic([100, 103, 106, 104, 105])
    for delta in (-.01, 0., .01):
        for level in (.199999, .20, .25):
            case = deepcopy(base)
            for vector in case[0]['feature']['vectors'].values():
                vector[46], vector[47] = level, delta
            got = compare(case)
            check(bool(got['side']), level >= .20, 'ADX20等号/変化符号の解除')
            mirrored = compare(fixture.reflected(case))
            check((mirrored['side'], mirrored['role']), (-got['side'], got['role']), '売買鏡像とADX不変')
    for mask in (50, 51):
        case = deepcopy(base)
        for vector in case[0]['feature']['vectors'].values():
            vector[mask] = 0
            if mask == 50:
                vector[46] = 0.
            else:
                vector[47] = 0.
        got = compare(case)
        check(got['side'], 0, 'ADX既知maskは外さない')
    for side, bg in ((-1, -1), (-1, 1)):
        for delta in (-.01, 0., .01):
            case = fixture.synthetic([100, 103, 106, 98, 96], side, bg)
            for vector in case[0]['feature']['vectors'].values():
                vector[47] = delta
            got = compare(case)
            old = LEGACY.derive(*case)
            check(got['qualifications'], old['qualifications'], 'RのF48反転資格を全文保持')
            compare(fixture.reflected(case))
    # ----------------------------------------
    # 非減速だけを外し、価格/DI/FastK/現在進行の失格を救済しない。
    for index, value in ((0, -.1), (1, -.1), (2, 0.), (6, 0.)):
        case = deepcopy(base)
        for vector in case[0]['feature']['vectors'].values():
            vector[47] = -.01
        if index == 0:
            case[0]['feature']['background_direction'] = -1
        case[0]['feature']['vectors']['1'][index] = value
        case[0]['feature']['vectors']['-1'][index] = -value
        got = compare(case)
        check(got['side'], 0, '他技法不適格を保持')
    case = deepcopy(base)
    case[3]['last'] = None
    compare(case)
    case = deepcopy(base)
    case[0].update(ready=False, line=None)
    case[0]['feature']['ready'] = False
    compare((case[0], None, None, None, None))
    case = deepcopy(base)
    future = deepcopy(case[1][-1])
    future.update(index=99, start=future['end'], end=future['end'] + 180, confirm=None, high=float('nan'))
    case[1].append(future)
    check(compare(case), derive(*base), '未来不正suffix非干渉')
    case = deepcopy(base)
    case[0]['feature']['vectors']['1'][47] = float('nan')
    compare(case, True)
    case = deepcopy(base)
    case[0]['feature']['vectors']['1'][51] = .5
    compare(case, True)
    check(hashlib.sha256(LEGACY_PATH.read_bytes()).hexdigest(), LEGACY_SHA, '旧コード不変')
    return {'成功': True, '人工成功': True, 'テスト件数': series, '照合項目数': count, '不一致数': 0,
        '本物入力読取': False, '新Iimport': '人工出力側だけ', '出生ATR再build': 0,
        '市場戦略再生': False, '本物fit': 0, '先着損益読取': False, '旧大域値変更': False}
