"""76の局所親波を、出生候補区間と親区間の独立走査から再構成する。"""

from copy import deepcopy
from fractions import Fraction
import hashlib
import importlib.util
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
POLICIES = ('L0', 'L1')
PURE = ('scheduled', 'time', 'line', 'side', 'role', 'atr', 'D', 'reason', 'ready', 'slot_id')
ATR_CLOCK = ('session', 'index', 'minutes', 'start', 'end', 'confirm', 'confirm_line', 'publish', 'missing')
OLD_PATH = ROOT / 'scripts/事前帯と現在の反応/入力監査.py'
OLD_SHA = 'df6ee929f037fc25e5bdbce0793992c974878de3123c77b6c83052e4fc87318d'


def fixed_helpers():
    """75の独立した公開時計・旧値検査だけを固定SHAで読む。

    引数: なし。
    返り値: ModuleTypeは純補助。新入力・出生ATR・主処理は読まない。
    """
    if hashlib.sha256(OLD_PATH.read_bytes()).hexdigest() != OLD_SHA:
        raise ValueError('固定75独立入力の指紋差')
    spec = importlib.util.spec_from_file_location('局所76の固定75独立純補助', OLD_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


OLD = fixed_helpers()
SOURCE = OLD.SOURCE
finite, exact, canonical = OLD.finite, OLD.exact, OLD.canonical


# ----------------------------------------
def point(row: dict | None, slot: dict | None = None) -> dict:
    """公開足又は判断タイマーの出典を分ける。

    引数: row(dict|None)は足、slot(dict|None)は判断時計。
    返り値: dictはindex/key/clock/end。タイマーへ架空足を与えない。
    """
    if row is not None:
        return {'index': row['index'], 'key': [row['confirm'], row['confirm_line']], 'clock': '公開足', 'end': row['end']}
    return {'index': None, 'key': [slot['time'], slot['line']], 'clock': '判断時刻', 'end': None}


def bind_atr(prefix: list[dict], rows: list[dict], slot: dict) -> list[dict]:
    """縮約出生ATRを全可視SOURCEへ、型・指紋・状態を独立結合する。

    引数: prefix(list[dict])は当時可視SOURCE、rows(list[dict])は縮約ATR、slot(dict)は判断。
    返り値: list[dict]はSOURCEと同順の参照。未知を0へ補完しない。
    """
    if not isinstance(rows, list) or len(rows) != len(prefix):
        raise ValueError('出生ATR可視行のlistが必要')
    selected = []
    for row in rows:
        if not isinstance(row, dict) or not finite(row.get('end')):
            raise ValueError('出生ATRの可視性不明')
        if row['end'] > slot['scheduled']:
            continue
        if not finite(row.get('confirm')) or type(row.get('confirm_line')) is not int or row['confirm_line'] < 0:
            raise ValueError('出生ATR公開key不正')
        if (row['confirm'], row['confirm_line']) > OLD.clock(slot):
            continue
        selected.append(row)
    if len(selected) != len(prefix):
        raise ValueError('出生ATRと価格prefixの全行集合差')
    output = []
    for source, row in zip(prefix, selected):
        for name in ATR_CLOCK:
            if canonical(row.get(name)) != canonical(source[name]):
                raise ValueError('出生ATRとSOURCEの型/時計差:' + name)
        if row.get('source_sha256') != hashlib.sha256(canonical(source).encode('utf-8')).hexdigest():
            raise ValueError('出生ATRとSOURCE全文指紋差')
        atr, valid = row.get('atr'), row.get('valid')
        if type(valid) is not bool or type(row.get('ready')) is not bool or type(row.get('numeric_count')) is not int or row['numeric_count'] < 0:
            raise ValueError('出生ATR状態型不正')
        if not isinstance(row.get('reset_reasons'), list) or any(not isinstance(reason, str) for reason in row['reset_reasons']):
            raise ValueError('出生ATRreset根拠不正')
        if atr is not None and (not finite(atr) or atr < 0):
            raise ValueError('出生ATR値不正')
        if not valid and (atr is not None or row['numeric_count'] != 0):
            raise ValueError('出生ATR価格無効と値の矛盾')
        ready = bool(valid and atr is not None and atr > 0)
        reason = '出生価格足未準備' if not valid else '出生ATR未準備' if atr is None else '出生ATR非正' if atr <= 0 else '出生ATR準備済み'
        if row['ready'] != ready or row.get('reason') != reason:
            raise ValueError('出生ATR準備の定義矛盾')
        output.append(deepcopy(row))
    return output


def tip(rows: list[dict], side: int) -> dict:
    """方向側OHLC極値の最初の足を取り、同値で後続へ更新しない。

    引数: rows(list[dict])は既知区間、side(int)は親方向。
    返り値: dictは価格とSOURCE。終値の極値や未来確定pivotではない。
    """
    field = 'high' if side == 1 else 'low'
    winner = max(rows, key=lambda row: side * exact(row[field]))
    return {'price': winner[field], 'source': deepcopy(winner)}


def event_id(slot: dict, row: dict, side: int) -> str:
    """出生公開時点から安定した親IDを構成する。

    引数: slot/row(dict)は場/出生足、side(int)は親方向。
    返り値: strは同じ親を複数定時で識別するID。
    """
    return f"{slot['session']}|W|{side:+d}|{row['index']}|{float(row['confirm']).hex()}|{row['confirm_line']}"


def eligible_price(candidate: dict, values: dict, quote: dict) -> dict:
    """指標資格と当時気配による前提維持を真偽命題で列挙する。

    引数: candidate/values/quote(dict)は有効形成・旧値・元気配。
    返り値: dictは役割、資格、拒否理由と現在距離。将来価格を参照しない。
    """
    side, kind, di, bg = candidate['side'], candidate['kind'], values['F01'], values['raw_background_direction']
    tests = [(values['F02'] < 0, 'FastKの方向位置が負'), (values['F03'] <= 0, 'FastKの方向進行が非正'),
        (values['F07'] <= 0, '現在価格の方向進行が非正'), (bg == 0 or di == 0, '上位DIが同値')]
    if kind == 'T':
        tests += [(di <= 0, '継続Tは上位DI同方向が必要'), (values['F51'] != 1 or values['F52'] != 1, '継続TのADX現値又は変化が未知'),
            (values['F47'] < .20, '継続TのADX20未満'), (values['F48'] < 0, '継続TのADXが減速')]
    elif di < 0:
        tests += [(values['F52'] != 1, '反転のADX変化が未知'), (values['F48'] >= 0, '反転のADXが非減速'), (values['F15'] <= 0, '反転の15分終値位置が非正')]
    entry = quote['ask'] if side == 1 else quote['bid']
    line = candidate['premise_line']
    last_distance, entry_distance = side * (exact(quote['last']) - exact(line)), side * (exact(entry) - exact(line))
    tests += [(last_distance <= 0, '現在Lastが前提線を否定'), (entry_distance <= 0, '現在新規BBOが前提線を否定')]
    reasons = [reason for failed, reason in tests if failed]
    return {'qualified': not reasons, 'role': '上位同値' if not di or not bg else '順行' if di > 0 else '反転',
        'reasons': reasons, 'values': deepcopy(values), 'price': {'last': quote['last'], 'entry_proxy': entry,
            'premise_line': line, 'last_distance': float(last_distance), 'entry_distance': float(entry_distance)}}


# ----------------------------------------
def scan_sections(slot: dict, prefix: list[dict], atrs: list[dict]) -> dict:
    """出生可能な3足区間を探し、その親区間を終端まで別の走査で確定する。

    引数: slot(dict)は判断、prefix/atrs(list[dict])は同順の可視価格/出生ATR。
    返り値: dictは内部区間記録。新実装のcontrollerや状態更新関数を呼ばない。
    """
    records, resets, rejected, buffer = [], [], [], []
    prepared = False
    cursor = 0
    defects, previous = [], None
    for i, row in enumerate(prefix):
        reason = OLD.price_reason(row)
        if previous is not None and (row['index'] != previous['index'] + 1 or row['start'] != previous['end']):
            reason = '番号又は足終端の不連続'
        if reason is None and not atrs[i]['ready']:
            reason = atrs[i]['reason']
        defects.append(reason)
        previous = row if reason is None else None
    while cursor < len(prefix):
        row = prefix[cursor]
        if defects[cursor] is not None:
            resets.append({'at': point(row), 'reason': defects[cursor]})
            prepared, buffer = False, []
            cursor += 1
            continue
        buffer = (buffer + [cursor])[-3:]
        cursor += 1
        if len(buffer) < 3:
            continue
        prepared = True
        a, m, b = [prefix[i] for i in buffer]
        first = exact(m['close']) - exact(a['close'])
        second = exact(b['close']) - exact(m['close'])
        if first * second <= 0:
            continue
        side = 1 if first > 0 else -1
        if side * (exact(b['close']) - exact(a['close'])) < exact(atrs[buffer[-1]]['atr']):
            continue
        deadline = b['end'] + 1620
        if b['confirm'] > deadline:
            rejected.append({'a': deepcopy(a), 'm': deepcopy(m), 'b': deepcopy(b), 'side': side,
                'deadline': deadline, 'at': point(b), 'reason': '出生公開が寿命後'})
            buffer = []
            continue
        origin = a['low'] if side == 1 else a['high']
        born_tip = tip([a, m, b], side)
        record = {'indices': list(buffer), 'side': side, 'origin': origin, 'deadline': deadline,
            'atr': deepcopy(atrs[buffer[-1]]), 'birth_tip': born_tip, 'tip_before_r': deepcopy(born_tip),
            'current_tip': deepcopy(born_tip), 'r': None, 'f': None, 'T_k': None, 'R_k': None,
            'T_end': None, 'R_end': None, 'end': None, 'r_deadline': None, 'events': [('birth', point(b), None)]}
        records.append(record)
        buffer = []
        # ----------------------------------------
        # 親が存在する区間は新出生探索を止め、最初のr/f/kと永久取消を抽出する。
        while cursor < len(prefix):
            current = prefix[cursor]
            event = point(current)
            if defects[cursor] is not None:
                record['end'] = {'at': event, 'reason': defects[cursor], 'kind': 'reset', 'status': '品質reset'}
                record['events'].append(('reset', event, defects[cursor]))
                resets.append({'at': event, 'reason': defects[cursor]})
                prepared = False
                cursor += 1
                break
            if current['end'] > deadline or current['confirm'] > deadline:
                record['end'] = {'at': event, 'reason': '親の出生後9本期限超過', 'kind': 'expiry', 'status': '期限終了'}
                record['events'].append(('expiry', event, '親の出生後9本期限超過'))
                cursor += 1
                break
            if record['f'] is not None and record['R_k'] is None and (current['end'] > record['r_deadline'] or current['confirm'] > record['r_deadline']):
                record['R_end'] = {'at': event, 'reason': '反対確認期限超過', 'status': '反対確認期限終了'}
                record['end'] = {**record['R_end'], 'kind': 'R_end'}
                record['events'].append(('R_expiry', event, None))
                cursor += 1
                break
            prior_tip = deepcopy(record['current_tip'])
            field = 'high' if side == 1 else 'low'
            if side * exact(current[field]) > side * exact(record['current_tip']['price']):
                record['current_tip'] = {'price': current[field], 'source': deepcopy(current)}
            if record['f'] is None:
                # 起点喪失はrやT確認より先であり、同じ足をR確認へ再利用しない。
                if side * (exact(current['close']) - exact(origin)) <= 0:
                    record['f'] = cursor
                    record['r_deadline'] = min(current['end'] + 540, deadline)
                    if record['T_end'] is None:
                        record['T_end'] = {'at': event, 'reason': '起点の終値喪失', 'status': '取消'}
                    record['events'].append(('f', event, None))
                    if deadline - current['end'] < 180:
                        record['R_end'] = {'at': event, 'reason': '遅い起点喪失で反対確認余地0本', 'status': '反対確認期限終了'}
                        record['end'] = {**record['R_end'], 'kind': 'R_end'}
                        record['events'].append(('R_late', event, None))
                elif record['T_end'] is None:
                    if record['T_k'] is not None:
                        r = prefix[record['r']]
                        premise = max(origin, r['low']) if side == 1 else min(origin, r['high'])
                        if side * (exact(current['close']) - exact(premise)) <= 0:
                            record['T_end'] = {'at': event, 'reason': 'T確認後の前提線終値否定', 'status': '取消'}
                            record['events'].append(('T_cancel', event, None))
                    elif record['r'] is None:
                        if side * (exact(current['close']) - exact(prefix[cursor - 1]['close'])) < 0:
                            record['r'] = cursor
                            record['tip_before_r'] = prior_tip
                            record['events'].append(('r', event, None))
                        else:
                            record['tip_before_r'] = tip([record['tip_before_r']['source'], current], side)
                    else:
                        r = prefix[record['r']]
                        confirmation = r['high'] if side == 1 else r['low']
                        if side * (exact(current['close']) - exact(confirmation)) > 0:
                            record['T_k'] = cursor
                            record['events'].append(('T_k', event, None))
            else:
                # f後は反対方向を検査し、反対確認後はf確認期限で打ち切らない。
                opposite = -side
                f = prefix[record['f']]
                if record['R_k'] is not None:
                    premise = max(origin, f['low']) if opposite == 1 else min(origin, f['high'])
                    if opposite * (exact(current['close']) - exact(premise)) <= 0:
                        record['R_end'] = {'at': event, 'reason': 'R確認後の前提線終値否定', 'status': 'R取消'}
                        record['end'] = {**record['R_end'], 'kind': 'R_end'}
                        record['events'].append(('R_cancel', event, None))
                elif opposite * (exact(current['close']) - exact(origin)) <= 0:
                    record['R_end'] = {'at': event, 'reason': '反対確認前に元起点を再獲得', 'status': 'R取消'}
                    record['end'] = {**record['R_end'], 'kind': 'R_end'}
                    record['events'].append(('R_recovered', event, None))
                elif opposite * (exact(current['close']) - exact(f['high'] if opposite == 1 else f['low'])) > 0:
                    record['R_k'] = cursor
                    record['events'].append(('R_k', event, None))
                elif current['index'] - f['index'] >= 3:
                    record['R_end'] = {'at': event, 'reason': 'f後3本の反対確認なし', 'status': '反対確認期限終了'}
                    record['end'] = {**record['R_end'], 'kind': 'R_end'}
                    record['events'].append(('R_no_k', event, None))
            cursor += 1
            if record['end'] is not None:
                break
        # ----------------------------------------
        # 判断タイマーは最後の可視足から先の価格を補わず、期限だけを処理する。
        if record['end'] is None:
            if slot['time'] > deadline:
                record['end'] = {'at': point(None, slot), 'reason': '親の出生後9本期限超過', 'kind': 'expiry', 'status': '期限終了'}
                record['events'].append(('expiry', point(None, slot), '親の出生後9本期限超過'))
            elif record['f'] is not None and record['R_k'] is None and slot['time'] > record['r_deadline']:
                record['R_end'] = {'at': point(None, slot), 'reason': '反対確認期限超過', 'status': '反対確認期限終了'}
                record['end'] = {**record['R_end'], 'kind': 'R_end'}
                record['events'].append(('R_expiry', point(None, slot), None))
        if record['end'] is not None:
            terminal = record['end']
            if record['T_end'] is None:
                record['T_end'] = {'at': terminal['at'], 'reason': terminal['reason'], 'status': terminal['status']}
            if record['f'] is not None and record['R_end'] is None:
                record['R_end'] = {'at': terminal['at'], 'reason': terminal['reason'], 'status': terminal['status']}
    return {'records': records, 'resets': resets, 'rejected': rejected, 'buffer': [deepcopy(prefix[i]) for i in buffer], 'prepared': prepared}


def public_history(scan: dict, prefix: list[dict], slot: dict) -> tuple:
    """独立区間記録を保存用親・形成・遷移schemaへ写す。

    引数: scan(dict)は区間走査、prefix(list[dict])は可視足、slot(dict)は場と時計。
    返り値: tuple[list,list]は親と形成。価格状態の再判定はしない。
    """
    parents, formations = [], []
    actions = {'birth': ('局所波出生b', '最初r待ち'), 'r': ('最初の逆終値r', '再開待ち'),
        'T_k': ('T再開k', 'T有効'), 'T_cancel': ('T取消・親は起点喪失待ち', '親起点喪失待ち'),
        'f': ('起点喪失f・同原因R待ち', '反対確認待ち'), 'R_k': ('R再開k', 'R有効')}
    for record in scan['records']:
        a, m, b = [prefix[i] for i in record['indices']]
        side = record['side']
        identity = event_id(slot, b, side)
        parent = {'id': identity, 'direction': side, 'a': deepcopy(a), 'm': deepcopy(m), 'b': deepcopy(b),
            'atr_b': record['atr']['atr'], 'birth_atr_source': deepcopy(record['atr']), 'origin': record['origin'],
            'deadline': record['deadline'], 'r': deepcopy(prefix[record['r']]) if record['r'] is not None else None,
            'f': deepcopy(prefix[record['f']]) if record['f'] is not None else None, 'T': None, 'R': None,
            'T_id': identity + '|T', 'R_id': identity + '|R' if record['f'] is not None else None,
            'birth_tip': deepcopy(record['birth_tip']), 'tip_before_r': deepcopy(record['tip_before_r']),
            'current_tip': deepcopy(record['current_tip']), 'active': record['end'] is None,
            'status': '最初r待ち', 'terminal': None, 'late_f': None, 'trace': []}
        for kind in ('T', 'R'):
            if kind == 'R' and record['f'] is None:
                continue
            direction = side if kind == 'T' else -side
            anchor = parent['r'] if kind == 'T' else parent['f']
            end = record[kind + '_end']
            k = record[kind + '_k']
            if anchor is None:
                line, premise = None, None
            else:
                line = anchor['high'] if direction == 1 else anchor['low']
                premise = max(parent['origin'], anchor['low']) if direction == 1 else min(parent['origin'], anchor['high'])
            formation = {'id': identity + '|' + kind, 'parent_id': identity, 'kind': kind, 'side': direction,
                'b': deepcopy(b), 'r': deepcopy(parent['r']) if kind == 'T' else None,
                'f': deepcopy(parent['f']) if kind == 'R' else None, 'k': deepcopy(prefix[k]) if k is not None else None,
                'trigger_line': line, 'premise_line': premise,
                'deadline': parent['deadline'] if kind == 'T' else record['r_deadline'],
                'active': k is not None and end is None,
                'status': end['status'] if end else '有効' if k is not None else '反対確認待ち' if kind == 'R' else '再開待ち' if anchor else '最初r待ち',
                'cancel': {**deepcopy(end['at']), 'reason': end['reason']} if end else None}
            parent[kind] = formation
            formations.append(formation)
        if parent['f'] is not None:
            remaining = int(min(3, max(0, (parent['deadline'] - parent['f']['end']) // 180)))
            parent['late_f'] = {'remaining_bars': remaining, 'reason': '確認余地0本' if remaining == 0 else '確認余地1本' if remaining == 1 else None}
        for code, at, _ in record['events']:
            if code in actions:
                action, status = actions[code]
                active = True
            else:
                terminal = record['end']
                action, status, active = terminal['reason'], terminal['status'], False
            parent['trace'].append({**deepcopy(at), 'action': action, 'status': status, 'active': active})
            parent['status'] = status
        if record['end'] is not None:
            parent['terminal'] = {**deepcopy(record['end']['at']), 'reason': record['end']['reason']}
        parents.append(parent)
    return parents, formations


def place(slot: dict, band: dict | None, quote: dict | None, normal: bool) -> tuple:
    """前帯の価格位置だけを独立に診断し、出生資格へ戻さない。

    引数: slot/band/quote(dict|None)は元判断と前帯/気配、normal(bool)は現在価格の正常性。
    返り値: tuple[dict|None,dict]は帯snapshotと両側の前方線。
    """
    view = OLD.band_view(slot, band) if band is not None else None
    ready = bool(view is not None and view['ready'] and normal)
    output = {'ready': ready, 'reason': '場所診断準備済み' if ready else '前帯不明' if view is None else view['reason'] if not view['ready'] else '現在BBO又はLastの観測不足', 'by_side': {}}
    for side in (1, -1):
        value = {'entry_proxy': None, 'position': '未知', 'levels': None, 'forward_lines': None}
        if ready:
            entry = quote['ask'] if side == 1 else quote['bid']
            if entry > view['high']:
                position = '上外'
            elif entry < view['low']:
                position = '下外'
            elif entry == view['high']:
                position = '上端'
            elif entry == view['low']:
                position = '下端'
            else:
                position = '帯内'
            levels = {name: {'price': view[name], 'signed_distance': float(side * (exact(view[name]) - exact(entry)))} for name in ('high', 'mid', 'low')}
            forward = sorted([{'name': name, **row} for name, row in levels.items() if row['signed_distance'] > 0], key=lambda row: (row['signed_distance'], row['name']))
            value.update(entry_proxy=entry, position=position, levels=levels, forward_lines=forward)
        output['by_side'][str(side)] = value
    return view, output


def choose_candidate(candidates: list[dict], qualifications: dict, policy: str, ready: bool, reason: str) -> dict:
    """同じ親観測の資格集合からT限定又はT/Rを選ぶ。

    引数: candidates/qualificationsは形成と資格、policy(str)はL0/L1、ready(bool)/reason(str)は状態。
    返り値: dictはside/role/reason/selected。低位資格への事後変更をしない。
    """
    eligible = [row for row in candidates if qualifications.get(row['id'], {}).get('qualified') and (policy == 'L1' or row['kind'] == 'T')]
    if len({row['side'] for row in eligible}) > 1:
        raise ValueError('反対方向同時資格の鏡像矛盾')
    ordered = sorted(eligible, key=lambda row: (row['k']['confirm'], row['k']['confirm_line'], row['kind'] == 'T'), reverse=True)
    selected = deepcopy(ordered[0]) if ordered and ready else None
    return {'side': selected['side'] if selected else 0, 'role': qualifications[selected['id']]['role'] if selected else '待機',
        'reason': '局所波の継続候補' if selected and selected['kind'] == 'T' else '同原因の起点喪失反対候補' if selected else reason,
        'selected': selected}


def derive(old_slot: dict, history_sources: list[dict], birth_atr_rows: list[dict], decision_quote: dict | None, prior_band: dict | None) -> dict:
    """当時可視prefixから親区間と現在の複合資格を別算法で再構成する。

    引数: old_slot(dict)は旧73判断、history_sources/birth_atr_rows(list)は全価格/可視ATR、decision_quote/prior_bandは旧気配/診断帯。
    返り値: dictは政策共有観測。新入力・出生ATR・主・Engineをimportしない。
    """
    OLD.clock(old_slot)
    feature = old_slot.get('feature')
    if not isinstance(feature, dict) or type(feature.get('ready')) is not bool or feature['ready'] is not old_slot['ready']:
        raise ValueError('旧基礎準備の不整合')
    output = {'base_ready': feature['ready'], 'ready': False, 'reason': '旧73特徴が未準備', 'source_count': 0,
        'source_sha256': None, 'atr_source_sha256': None,
        'history': {'current': None, 'resets': [], 'birth_buffer': [], 'preparation': {'ready': False, 'count': 0, 'required': 3, 'reason': '旧73特徴が未準備'}, 'rejected_births': []},
        'parents': [], 'formations': [], 'candidates': [], 'qualifications': {}, 'selected_by_policy': {},
        'band': None, 'location': None, 'side': 0, 'role': '待機', 'selected': None}
    if not feature['ready']:
        output['selected_by_policy'] = {policy: choose_candidate([], {}, policy, False, output['reason']) for policy in POLICIES}
        return output
    if not finite(old_slot.get('atr')) or old_slot['atr'] <= 0 or not finite(old_slot.get('D')) or old_slot['D'] <= 0 or feature.get('atr') != old_slot['atr'] or feature.get('D') != old_slot['D']:
        raise ValueError('旧現在幅の不整合')
    prefix = OLD.visible_prefix(old_slot, history_sources, feature)
    atrs, values = bind_atr(prefix, birth_atr_rows, old_slot), OLD.values_for(feature)
    scan = scan_sections(old_slot, prefix, atrs)
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
    for candidate in candidates:
        candidate.update(k_age_seconds=old_slot['time'] - candidate['k']['confirm'], k_end_age_seconds=old_slot['scheduled'] - candidate['k']['end'],
            tip_distance=float(candidate['side'] * (exact(parent['tip_before_r']['price']) - exact(candidate['k']['close']))))
        if normal:
            output['qualifications'][candidate['id']] = eligible_price(candidate, values[str(candidate['side'])], decision_quote)
    if candidates and normal and not any(row['qualified'] for row in output['qualifications'].values()):
        reason = '局所波の現在複合条件不適格'
    band, location = place(old_slot, prior_band, decision_quote, normal)
    rejected = [{name: deepcopy(row[name]) for name in ('a', 'm', 'b', 'deadline', 'reason')} | {'atr_b': atrs[next(i for i, source in enumerate(prefix) if source['index'] == row['b']['index'])]['atr']} for row in scan['rejected']]
    output.update(ready=ready, reason=reason, source_count=len(prefix),
        source_sha256=hashlib.sha256(canonical(prefix).encode('utf-8')).hexdigest(),
        atr_source_sha256=hashlib.sha256(canonical(atrs).encode('utf-8')).hexdigest(),
        history={'current': deepcopy(prefix[-1]), 'resets': [{**deepcopy(row['at']), 'reason': row['reason']} for row in scan['resets']],
            'birth_buffer': [point(row) for row in scan['buffer']],
            'preparation': {'ready': scan['prepared'], 'count': len(scan['buffer']), 'required': 3, 'reason': '出生入力準備済み' if scan['prepared'] else '出生準備待ち'},
            'rejected_births': rejected}, parents=parents, formations=formations, candidates=candidates, band=band, location=location)
    for policy in POLICIES:
        policy_reason = 'R形成はL0で採用対象外' if policy == 'L0' and candidates and candidates[0]['kind'] == 'R' and ready else reason
        output['selected_by_policy'][policy] = choose_candidate(candidates, output['qualifications'], policy, ready, policy_reason)
    output.update({key: deepcopy(output['selected_by_policy']['L1'][key]) for key in ('side', 'role', 'selected', 'reason')})
    return output


def choose(slot: dict, observation: dict, policy: str) -> dict:
    """共通観測から政策別の純10項目と最小由来を作る。

    引数: slot/observation(dict)は旧判断と独立観測、policy(str)はL0/L1。
    返り値: dictはO49用純入力と親/形成/前提線。未来の結果を含めない。
    """
    if policy not in POLICIES or not all(name in slot for name in PURE):
        raise ValueError('政策又は純10項目なし')
    OLD.clock(slot)
    decision = observation['selected_by_policy'][policy]
    candidate = decision['selected']
    if candidate is not None and (not observation['ready'] or candidate['side'] != decision['side'] or not observation['qualifications'][candidate['id']]['qualified'] or policy == 'L0' and candidate['kind'] != 'T'):
        raise ValueError('政策と資格が不整合')
    parent = next((row for row in observation['parents'] if candidate is not None and row['id'] == candidate['parent_id']), None)
    kind = candidate['kind'] if candidate else None
    result = {name: deepcopy(slot[name]) for name in PURE}
    result.update(session=slot['session'], policy=policy, side=decision['side'], role=decision['role'], reason=decision['reason'], ready=observation['ready'],
        origin='局所波継続' if kind == 'T' else '同原因起点喪失反対' if kind == 'R' else '局所波待機',
        pattern_id=candidate['id'] if candidate else None, parent_id=parent['id'] if parent else None, formation=kind,
        premise_line=candidate['premise_line'] if candidate else None, trigger_line=candidate['trigger_line'] if candidate else None,
        birth_atr=parent['atr_b'] if parent else None, band_id=observation['band']['id'] if observation['band'] else None)
    return result


# ----------------------------------------
def self_test() -> dict:
    """架空価格だけで新実装と別区間走査の全観測を比較する。

    引数: なし。
    返り値: dictは成功/系列数/照合数/不一致数。新I importはこの人工内だけ。
    """
    path = HERE / '入力.py'
    spec = importlib.util.spec_from_file_location('局所76独立人工の出力側入力', path)
    implementation = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(implementation)
    count = series = 0

    def difference(a: object, b: object, path: str = '') -> str:
        """人工の最初の相違位置を小型に表示する。

        引数: a/b(object)は比較値、path(str)は現在位置。
        返り値: strは相違箇所。市場内容は含まない。
        """
        if canonical(a) == canonical(b):
            return ''
        if isinstance(a, dict) and isinstance(b, dict) and set(a) == set(b):
            return next((value for key in a if (value := difference(a[key], b[key], path + '/' + key))), path)
        if isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
            return next((value for i, item in enumerate(a) if (value := difference(item, b[i], path + '/' + str(i)))), path)
        return path + ': ' + str(a)[:350] + ' != ' + str(b)[:350]

    def check(actual: object, expected: object, label: str) -> None:
        """人工の全文を固定JSONで比較する。

        引数: actual/expected(object)は値、label(str)は検査名。
        返り値: None。不一致なら小型の差を出して停止する。
        """
        nonlocal count
        count += 1
        if canonical(actual) != canonical(expected):
            raise AssertionError(label + ' ' + difference(actual, expected))

    def compare(case: tuple, reject: bool = False) -> dict | None:
        """同じ架空5引数から両算法の観測・政策射影を比較する。

        引数: case(tuple)は人工材料、reject(bool)は両拒否期待。
        返り値: dict|Noneは独立観測又は拒否。
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
            check(outputs[0], outputs[1], '親/形成/時刻/資格の全観測')
            for policy in POLICIES:
                check(choose(case[0], outputs[0], policy), implementation.choose(case[0], outputs[1], policy), '純射影:' + policy)
        check(canonical(case), before, '入力非改変')
        return outputs[0]

    paths = [[100], [100, 103], [100, 103, 106], [100, 100, 106], [100, 103, 105], [100, 103, 104],
        [100, 103, 106, 104, 106], [100, 103, 106, 104, 102, 106], [100, 103, 106, 104, 106, 105],
        [100, 103, 106, 104, 106, 103, 106], [100, 103, 106, 104, 106, 103, 98, 96],
        [100, 103, 106, 98, 99], [100, 103, 106, 98, 97, 98, 97],
        [100, 103, 106, 98, 96, 97, 98, 99], [100, 103, 106, 110, 111, 112, 114, 115, 116, 117, 118, 98],
        [100, 103, 106, 110, 111, 112, 114, 115, 116, 117, 98, 96],
        [100, 103, 106, 104, 106, 107, 108, 109, 110, 111, 112, 113, 114, 115, 116]]
    base = None
    for closes in paths:
        case = implementation.synthetic(closes)
        got = compare(case)
        compare(implementation.reflected(case))
        if closes == [100, 103, 106, 104, 106]:
            base = case
            check((got['side'], got['selected']['kind'], got['selected']['k']['index']), (1, 'T', 4), '既知T')
    for background in (1, -1):
        case = implementation.synthetic([100, 103, 106, 104, 106, 103, 98, 96], -1, background)
        if background == 1:
            for vector in case[0]['feature']['vectors'].values():
                vector[47] = -.01
        got = compare(case)
        check((got['side'], got['selected']['kind'], got['selected_by_policy']['L0']['side']), (-1, 'R', 0), '反対確認後だけL1採用')
        check(got['role'], '順行' if background == -1 else '反転', 'R形とDI役割は別')
        compare(implementation.reflected(case))
    # ----------------------------------------
    # 未知ATR・価格resetと再準備、正常終端後の既知待機を区別する。
    for unknown in (0, 1, 2, 3):
        case = implementation.synthetic([100, 103, 106, 104, 106, 107, 109])
        atr = case[2][unknown]
        atr.update(atr=None, ready=False, reason='出生ATR未準備', numeric_count=13)
        compare(case)
    case = implementation.synthetic([100, 103, 106, 104, 106, 103, 98, 96, 99, 101])
    got = compare(case)
    check((got['ready'], got['history']['preparation']['ready']), (True, True), '正常終端は未知へ戻さない')
    case = deepcopy(base)
    case[2][-1].update(atr=0, ready=False, reason='出生ATR非正')
    got = compare(case)
    check(got['ready'], False, 'ATR既知0は出生不可')
    case = deepcopy(base)
    case[1][1]['high'] = float('nan')
    implementation.refresh(case)
    compare(case)
    case = deepcopy(base)
    for source in case[1][3:]:
        source['index'] += 1
    implementation.refresh(case)
    got = compare(case)
    check((got['ready'], got['history']['preparation']['count']), (False, 1), '欠足reset足を再準備へ使わない')
    # ----------------------------------------
    # 期限の公開時計/実判断、未来suffix、気配不正、前帯未知を別検査する。
    case = implementation.synthetic([100, 103, 106])
    case[1][-1]['confirm'] = case[1][-1]['end'] + 1621
    case[0]['time'] = case[1][-1]['confirm']
    implementation.refresh(case)
    got = compare(case)
    check((len(got['parents']), got['reason']), (0, '出生公開が寿命後'), '遅い出生拒否')
    case = deepcopy(base)
    future = deepcopy(case[1][-1])
    future.update(index=future['index'] + 1, start=future['end'], end=future['end'] + 180, confirm=None, high=float('nan'))
    case[1].append(future)
    got = compare(case)
    check(got, derive(*base), '未来価格/公開不良suffix非干渉')
    case = deepcopy(base)
    case[3]['last'] = None
    compare(case)
    case = deepcopy(base)
    case[3]['valid'] = False
    compare(case)
    compare((*deepcopy(base[:4]), None))
    case = deepcopy(base)
    deadline = case[1][2]['end'] + 1620
    case[0]['time'] = deadline
    implementation.refresh(case)
    check(compare(case)['side'], 1, '実判断の親期限等号は可')
    case[0]['time'] = deadline + .01
    implementation.refresh(case)
    got = compare(case)
    check((got['side'], got['parents'][0]['terminal']['clock']), (0, '判断時刻'), '実判断の親期限strict超')
    case = implementation.synthetic([100, 103, 106, 98, 97, 98, 96], -1, -1)
    got = compare(case)
    check((got['side'], got['selected']['k']['index']), (-1, 6), 'R公開期限3足目等号可')
    case[1][-1]['confirm'] += .01
    case[0]['time'] = case[1][-1]['confirm']
    implementation.refresh(case)
    got = compare(case)
    check((got['side'], got['parents'][0]['R']['k']), (0, None), 'R公開期限strict超は過去へ戻さない')
    case = implementation.synthetic([100, 103, 106, 104, 106])
    case[1][3]['high'] = 999.
    implementation.refresh(case)
    got = compare(case)
    check(got['parents'][0]['tip_before_r']['source']['index'], 2, 'r足内の極値をr前tipへ加えない')
    case = deepcopy(base)
    case[0].update(ready=False, line=None)
    case[0]['feature']['ready'] = False
    case = (case[0], None, None, None, None)
    compare(case)
    # ----------------------------------------
    # 型・指紋・全可視集合の不整合は、都合のよい0補完をせず拒否する。
    case = deepcopy(base)
    case[2][-1]['source_sha256'] = '0' * 64
    compare(case, True)
    case = deepcopy(base)
    case[2].pop()
    compare(case, True)
    case = deepcopy(base)
    case[2][-1]['end'] = int(case[2][-1]['end'])
    if type(case[1][-1]['end']) is float:
        compare(case, True)
    case = deepcopy(base)
    case[0]['feature']['vectors']['1'][2] = -.1
    compare(case, True)
    return {'成功': True, '人工成功': True, 'テスト件数': series, '照合項目数': count, '不一致数': 0,
        '本物入力読取': False, '新市場': 0, '本物fit': 0, '先着損益読取': False,
        '新入力import': '人工出力側だけ。正式deriveは新入力/出生ATR/主非依存', '旧大域値変更': False}
