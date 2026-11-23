"""固定済みq0特徴を可読条件で判定し、後段で取得参照と旧対照を結合する。"""
from pathlib import Path
from collections import Counter
import argparse
import gzip
import hashlib
import json
import math


def sha(path: Path) -> str:
    """
    機能: 圧縮の有無によらず物理bytesの指紋を求める。
    引数: path(Path)は対象。
    返り値: strはSHA256。
    """
    digest = hashlib.sha256()
    with path.open('rb') as source:
        for block in iter(lambda: source.read(1048576), b''):
            digest.update(block)
    return digest.hexdigest()


# ----------------------------------------
def load(path: Path) -> object:
    """
    機能: UTF-8のJSON又はgzip JSONを全読し、gzip終端CRCも検査する。
    引数: path(Path)はJSON又はjson.gz。
    返り値: objectはJSON値。巨大解凍ファイルは書き出さない。
    """
    opener = gzip.open if path.suffix == '.gz' else Path.open
    with opener(path, 'rt', encoding='utf-8') as source:
        return json.load(source)


# ----------------------------------------
def save(path: Path, value: object) -> None:
    """
    機能: 有限値のJSONをUTF-8で排他保存する。
    引数: path(Path)は未作成先、value(object)は値。
    返り値: None。
    """
    with path.open('x', encoding='utf-8', newline='\n') as target:
        json.dump(value, target, ensure_ascii=False, indent=2, allow_nan=False)
        target.write('\n')


# ----------------------------------------
def validate(book: dict, catalog: list[dict]) -> tuple[dict, dict]:
    """
    機能: 列名・依存順・演算子・政策参照を条件実行前に検査する。
    引数: book(dict)は条件、catalog(list[dict])は共通列定義。
    返り値: tuple[dict,dict]は列番号と元列の役割。
    """
    index = {column['name']: i for i, column in enumerate(catalog)}
    roles = {column['name']: column['role'] for column in catalog}
    assert len(index) == len(catalog) == book['catalog_count']
    assert type(book['minimum_technical_roles']) is int and book['minimum_technical_roles'] >= 2
    available = set(index)
    for name, expression in book.get('derived', {}).items():
        assert name not in available and expression['op'] in ('sum', 'difference')
        assert len(expression['vars']) >= 2 and (expression['op'] != 'difference' or len(expression['vars']) == 2)
        assert all(variable in available for variable in expression['vars'])
        available.add(name)

    def inspect(expression: dict) -> set[str]:
        """
        機能: 条件木の文法と変数を再帰検査する。
        引数: expression(dict)は一つの条件。
        返り値: set[str]は参照変数名。
        """
        assert isinstance(expression, dict)
        if 'all' in expression or 'any' in expression:
            key = 'all' if 'all' in expression else 'any'
            assert set(expression) == {key} and expression[key]
            result = set()
            for child in expression[key]:
                result.update(inspect(child))
            return result
        assert set(expression) == {'var', 'op', 'value'}
        assert expression['var'] in available and expression['op'] in ('>', '>=', '<', '<=', '==')
        value = expression['value']
        assert type(value) in (int, float) and math.isfinite(value)
        return {expression['var']}

    inspect(book['common'])
    ids = []
    for rule in book['rules']:
        assert rule['id'] not in ids and rule['order_sign'] in (-1, 1)
        inspect(rule['when'])
        ids.append(rule['id'])
    assert book['union_id'] not in ids and book['legacy_id'] not in ids and book['main_id'] not in ids
    assert len({book['union_id'], book['legacy_id'], book['main_id']}) == 3
    members = book.get('union_rules', ids)
    assert members and len(members) == len(set(members)) and set(members) <= set(ids)
    return index, roles


# ----------------------------------------
def context(vector: list, index: dict, derived: dict) -> tuple[dict, dict]:
    """
    機能: 一方向の既知値と派生値を作り、派生の元列を追跡する。
    引数: vector(list)は当時特徴、index/derived(dict)は列定義と代数式。
    返り値: tuple[dict,dict]は値と元列依存。未知を0へ補完しない。
    """
    assert len(vector) == len(index)
    values = {name: vector[i] for name, i in index.items()}
    assert all(value is None or type(value) in (int, float) and math.isfinite(value) for value in values.values())
    dependencies = {name: {name} for name in values}
    for name, expression in derived.items():
        operands = [values[variable] for variable in expression['vars']]
        values[name] = (None if any(value is None for value in operands) else sum(operands)
                        if expression['op'] == 'sum' else operands[0] - operands[1])
        assert values[name] is None or math.isfinite(values[name])
        dependencies[name] = set().union(*(dependencies[variable] for variable in expression['vars']))
    return values, dependencies


# ----------------------------------------
def evaluate(expression: dict, values: dict, dependencies: dict) -> tuple[bool | None, set]:
    """
    機能: 三値論理で条件を評価し、成立に使った元特徴を返す。
    引数: expression/values/dependencies(dict)は条件と当時値。
    返り値: tuple[bool|None,set]。未知の否定で成立を作らない。
    """
    if 'all' in expression or 'any' in expression:
        key = 'all' if 'all' in expression else 'any'
        evaluated = [evaluate(child, values, dependencies) for child in expression[key]]
        if key == 'all':
            truth = False if any(value is False for value, _ in evaluated) else None if any(value is None for value, _ in evaluated) else True
        else:
            truth = True if any(value is True for value, _ in evaluated) else None if any(value is None for value, _ in evaluated) else False
        used = set().union(*(names for value, names in evaluated if value is True)) if truth is True else set()
        return truth, used
    value = values[expression['var']]
    if value is None:
        return None, set()
    boundary = expression['value']
    operator = expression['op']
    truth = (value > boundary if operator == '>' else value >= boundary if operator == '>='
             else value < boundary if operator == '<' else value <= boundary if operator == '<='
             else value == boundary)
    return truth, dependencies[expression['var']] if truth else set()


# ----------------------------------------
def decide(buy: list, sell: list, book: dict, index: dict, roles: dict) -> dict:
    """
    機能: 同じ条件を両方向へ適用し、根拠方向と注文方向を分ける。
    引数: buy/sell(list)、book/index/roles(dict)。q1やラベルは受け取らない。
    返り値: dictは各政策の方向、成立根拠、競合。品質共通条件は技法数へ数えない。
    """
    evidence = []
    for signal_side, vector in ((1, buy), (-1, sell)):
        values, dependencies = context(vector, index, book.get('derived', {}))
        common, _ = evaluate(book['common'], values, dependencies)
        if common is not True:
            continue
        for rule in book['rules']:
            matched, used = evaluate(rule['when'], values, dependencies)
            if matched is True:
                used_roles = sorted({roles[name] for name in used})
                assert len(used_roles) >= book['minimum_technical_roles'], (rule['id'], used_roles)
                evidence.append({'rule': rule['id'], 'signal_side': signal_side,
                    'order_side': signal_side * rule['order_sign'], 'roles': used_roles,
                    'derived': {name: values[name] for name in book.get('derived', {})}})
    directions = {}
    conflicts = {}
    members = set(book.get('union_rules', [rule['id'] for rule in book['rules']]))
    for policy in [rule['id'] for rule in book['rules']] + [book['union_id']]:
        sides = {row['order_side'] for row in evidence if row['rule'] in members and policy == book['union_id'] or row['rule'] == policy}
        directions[policy] = next(iter(sides)) if len(sides) == 1 else 0
        conflicts[policy] = len(sides) > 1
    return {'directions': directions, 'conflicts': conflicts, 'evidence': evidence}


# ----------------------------------------
def connect(decisions: list[dict], captures: list[dict], descriptors: list[dict], sessions: list[str], book: dict) -> dict:
    """
    機能: 全q0判断完成後に取得を結び、旧対照優先で物理q1を統合する。
    引数: decisions/captures/descriptors(list[dict])、sessions(list[str])、book(dict)。
    返り値: dictは政策別取得参照、候補/取消/競合/重複の計数。
    """
    by_event = {row['event_id']: row for row in captures}
    cases = {row['case_id']: row for row in descriptors}
    assert len(by_event) == len(captures) == len(decisions) == len({row['event_id'] for row in decisions})
    assert set(by_event) == {row['event_id'] for row in decisions} and len(cases) == len(descriptors)
    assert len(sessions) == len(set(sessions)) == book['session_count']
    order = {session: i for i, session in enumerate(sessions)}
    names = [rule['id'] for rule in book['rules']] + [book['union_id']]
    union_rules = set(book.get('union_rules', [rule['id'] for rule in book['rules']]))
    selected = {name: {} for name in names}
    counts = {name: Counter() for name in names}
    for row in sorted(decisions, key=lambda row: (order[row['session']], row['q0_index'], row['q0_line'], row['event_id'])):
        acquisition = by_event[row['event_id']]
        assert all(acquisition[name] == row[name] for name in ('session', 'contract'))
        assert (acquisition['q0']['time'], acquisition['q0']['index'], acquisition['q0']['source_line']) == (row['q0_time'], row['q0_index'], row['q0_line'])
        for policy in names:
            if row['decision']['conflicts'][policy]:
                counts[policy]['conflict_wait'] += 1
            side = row['decision']['directions'][policy]
            if not side:
                continue
            counts[policy]['born'] += 1
            counts[policy][acquisition['status']] += 1
            if acquisition['status'] != 'filled':
                continue
            case_id = acquisition['case_id']
            descriptor = cases[case_id]
            assert descriptor['session'] == row['session'] and descriptor['contract'] == row['contract']
            if case_id in selected[policy]:
                counts[policy]['duplicate_q1'] += 1
                continue
            stream = acquisition['buy_stream' if side == 1 else 'sell_stream']
            assert stream == descriptor['buy_stream' if side == 1 else 'sell_stream']
            evidence = [hit for hit in row['decision']['evidence'] if hit['order_side'] == side and
                        (policy == book['union_id'] and hit['rule'] in union_rules or hit['rule'] == policy)]
            selected[policy][case_id] = {'case_id': case_id, 'session': row['session'], 'side': side,
                'stream': stream, 'event_id': row['event_id'], 'feature_ref': row['event_id'],
                'q0_time': row['q0_time'], 'q0_index': row['q0_index'], 'q0_line': row['q0_line'],
                '成立ID': sorted({hit['rule'] for hit in evidence}), 'evidence': evidence, 'origin': policy}
    legacy = {case_id: {'case_id': case_id, 'session': row['session'], 'side': row['original_side'],
        'stream': 'original', 'event_id': None, 'feature_ref': None, 'origin': book['legacy_id']}
        for case_id, row in cases.items() if row['c1_reused']}
    assert len(legacy) == book['legacy_count']
    merged = dict(legacy)
    overlaps = []
    for case_id, row in selected[book['union_id']].items():
        if case_id in merged:
            overlaps.append({'case_id': case_id, 'legacy_side': merged[case_id]['side'],
                             'new_side': row['side'], 'opposite': merged[case_id]['side'] != row['side']})
        else:
            merged[case_id] = row
    selected[book['legacy_id']] = legacy
    selected[book['main_id']] = merged
    return {'政策': {name: list(rows.values()) for name, rows in selected.items()},
        '候補と取得': {name: dict(value) for name, value in counts.items()},
        '旧C1重複': overlaps, '全73場': sessions, '選択時の金融ラベル利用': False}


# ----------------------------------------
def main() -> None:
    """
    機能: 固定された条件とq0特徴を先に判定し、取得を後段で結合する。
    引数: CLI book/features/captures/metadataと各SHA、未作成output-dir。
    返り値: None。保存観測/Rawを開かず、新規JSONだけを保存する。
    """
    parser = argparse.ArgumentParser(description='固定当時特徴から可読条件を選択')
    for name in ('book', 'features', 'captures', 'metadata'):
        parser.add_argument('--' + name, type=Path, required=True)
        parser.add_argument('--' + name + '-sha256', required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    assert not args.output_dir.exists()
    paths = {name: getattr(args, name) for name in ('book', 'features', 'captures', 'metadata')}
    before = {name: sha(path) for name, path in paths.items()}
    assert all(before[name] == getattr(args, name + '_sha256') for name in paths)
    book = load(paths['book'])
    features = load(paths['features'])
    assert features['success'] and features['trial'] == book['parent_trial']
    assert not features['financial_labels_used'] and not features['strategy_selected'] and features['selected_trade_count'] is None
    assert features['catalog_definition_sha256'] == book['catalog_definition_sha256']
    index, roles = validate(book, features['catalog'])
    decisions = []
    for row in features['rows']:
        q0 = row['metadata']['q0']
        assert row['buy']['side'] == 1 and row['sell']['side'] == -1
        decisions.append({'event_id': row['event_id'], 'session': row['session'], 'contract': row['contract'],
            'q0_time': q0['time'], 'q0_index': q0['index'], 'q0_line': q0['source_line'],
            'decision': decide(row['buy']['x'], row['sell']['x'], book, index, roles)})
    # ----------------------------------------
    # ここまではq0だけの判断。取得結果は判断へ渡しません。
    captures = load(paths['captures'])
    metadata = load(paths['metadata'])
    assert captures['trial'] == metadata['trial'] == book['parent_trial']
    assert captures['success'] and metadata['success'] and not captures['financial_labels_used'] and not metadata['financial_labels_used']
    assert captures['sessions'] == metadata['sessions'] == features['sessions']
    for name in ('input_sha256', 'parent_source_sha256', 'parent_gzip_sha256', 'background_sha256',
                 'catalog_sha256', 'catalog_definition_sha256', 'counts', 'statuses'):
        assert captures[name] == features[name]
    result = connect(decisions, captures['rows'], metadata['population148']['cases'], features['sessions'], book)
    assert all(sha(path) == before[name] for name, path in paths.items())
    args.output_dir.mkdir(parents=True)
    save(args.output_dir / 'q0の判断.json', {'成功': True, '試行': book['trial'], '出生判断数': len(decisions),
        'q1結合前に全件判断': True, '金融ラベル利用': False, 'rows': decisions})
    save(args.output_dir / '選択対応.json', {'成功': True, '試行': book['trial'], '入力SHA256': before, **result})
    save(args.output_dir / '選択の確認.json', {'成功': True, '試行': book['trial'], '金融ラベル未読': True,
        '入力': {str(path.resolve()): before[name] for name, path in paths.items()},
        '出力': {path.name: sha(path) for path in sorted(args.output_dir.iterdir())},
        '政策別取得数': {name: len(rows) for name, rows in result['政策'].items()}})
    print(json.dumps({'成功': True, '判断数': len(decisions),
        '政策別取得数': {name: len(rows) for name, rows in result['政策'].items()}}, ensure_ascii=False))


if __name__ == '__main__':
    main()
