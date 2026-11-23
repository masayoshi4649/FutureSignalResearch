"""完了証拠へ結合した固定54内の先頭2場又は全54場のチャートだけを照合する。"""

import argparse
import copy
import datetime as dt
import gzip
import hashlib
import heapq
import importlib.util
import json
import math
from pathlib import Path
import re
import sys

from chart_numeric import Bank


ROOT = Path(__file__).resolve().parents[2]
READER_PATH = ROOT/'scripts/FAR5分判断と出生一回の監査/出生と5分境界の照合.py'
READER_SHA = '329fb9958f708bbf34fd939978f358e35333ad80053e4b5ce78521d95afca693'
MANIFEST_SHA = 'b939bc91b33fd86e933534c3b991d844b8a0200a5f14710e1bd5004edc1aab42'
ALLOWED = ['2026-09-21_Day', '2026-09-21_Night']
ABS_TOL, REL_TOL = 1e-8, 1e-12
CORE = {
 'scripts/複数尺度チャートの助走/bank.go':'e727cc2589d3ba1f4b8d81ff8266f29117264dbe08560c9033e68b2c4442f612',
 'scripts/FAR後期15分移植/technical.go':'ba63bd64bfaaf74adfc1ab780f627828d8f92783647dbb3ee8e66968ae8082a9',
 'scripts/チャートの現在性と補助確認/chart.go':'17891935b6b7bce106423e0cb711a0387aef3efe66b640d0b9c740dc7ecffefa',
 'scripts/FAR5分枠の順行反転と数量/chart_seeds.go':'8ec331393e99b39cddf174790f2d2828f6287448f6b44ef94476647795f632f1',
 'scripts/FAR5分枠の順行反転と数量/replay.go':'bf9cc5bc849e2d6d863260cbd5e64a0dbea928579b50d5ee42bd7bac2f68b4ec',
 'scripts/FAR5分枠の順行反転と数量/grid_clock.go':'133618eef51363f740323972329fea186c85fe7525117d35a7eb19a1eb67ac4c',
 'scripts/FAR5分枠の順行反転と数量/input.go':'c1f531eaf96294a6f4e2cc40130e6da02a44a3f6bc2e1b079093ed3ff3d8d597',
}


def digest(path: Path) -> str:
    """
    機能: ファイル本文の前後指紋を得る。
    引数: path(Path)は許可入力又はコード。
    返り値: strはSHA256。
    """
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1048576), b''):
            h.update(block)
    return h.hexdigest()


def unique(pairs: list) -> dict:
    """
    機能: 重複JSONキーを拒否する。
    引数: pairs(list)はJSONの組。
    返り値: dictは一意のobject。
    """
    out = {}
    for k, v in pairs:
        if k in out:
            raise ValueError('JSON重複キー:'+k)
        out[k] = v
    return out


def load(path: Path):
    """
    機能: 型破損JSONを成功へ補完せず読む。
    引数: path(Path)は明示入力。
    返り値: dict/listは保存値。
    """
    with path.open(encoding='utf-8-sig') as stream:
        return json.load(stream, object_pairs_hook=unique, parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)))


def reader():
    """
    機能: 停止95→94→93の時刻/原板field読取だけを再用する。
    引数: なし。
    返り値: moduleはparse_clock/number/session_clockを持つ固定93部品。
    """
    if digest(READER_PATH) != READER_SHA:
        raise ValueError('固定95reader指紋差')
    spec = importlib.util.spec_from_file_location('固定95reader96numeric', READER_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.BASE.BASE


class Comparison:
    """数値許容誤差とstrict符号の検査を別に記録する。"""

    def __init__(self):
        """
        機能: 照合数と未知skipを初期化する。
        引数: なし。
        返り値: None。
        """
        self.checks = self.numeric = self.unknown = self.strict = 0
        self.max_error, self.worst = 0.0, ''

    def need(self, condition: bool, label: str) -> None:
        """
        機能: 不整合で即時停止する。
        引数: condition(bool)、label(str)は条件と出典。
        返り値: None。
        """
        self.checks += 1
        if not condition:
            raise ValueError(label)

    def tree(self, actual, expected, label: str, approximate: bool = False) -> None:
        """
        機能: 集合/順序/型を厳密に、既知指標値だけ許容誤差付きで比較する。
        引数: actual/expected(any)、label(str)、approximate(bool)は値/箇所/指標指定。
        返り値: None。
        """
        if isinstance(expected, dict):
            self.need(type(actual) is dict and set(actual) == set(expected), label+':field集合')
            for k in expected:
                self.tree(actual[k], expected[k], label+'.'+k, approximate)
        elif isinstance(expected, list):
            self.need(type(actual) is list and len(actual) == len(expected), label+':長さ')
            for i, e in enumerate(expected):
                self.tree(actual[i], e, f'{label}[{i}]', approximate)
        elif type(expected) is bool:
            self.need(type(actual) is bool and actual == expected, label+':bool')
        elif type(expected) in (int, float):
            self.need(type(actual) in (int, float) and math.isfinite(actual), label+':数値型/有限')
            delta = abs(actual-expected)
            if approximate:
                self.numeric += 1
                if delta > self.max_error:
                    self.max_error, self.worst = delta, label
                self.need(math.isclose(actual, expected, rel_tol=REL_TOL, abs_tol=ABS_TOL), f'{label}:数値差{delta}')
            else:
                self.need(actual == expected, f'{label}:値{actual!r}!={expected!r}')
        else:
            self.need(type(actual) is type(expected) and actual == expected, label+':型/値')

    def snapshot(self, actual: dict, expected: dict, mask: dict, label: str) -> None:
        """
        機能: 原板で個別助走済みの値だけを確認し、未知0を成功数へ混ぜない。
        引数: actual/expected/mask(dict)、label(str)は保存値/独立値/独立既知性。
        返り値: None。
        """
        self.need(set(actual) == set(expected), label+':snapshot集合')
        for k in expected:
            if k != 'chart':
                self.tree(actual[k], expected[k], label+'.'+k)
        a, e = actual['chart'], expected['chart']
        self.need(set(a) == set(e) and set(a['Technical']) == set(e['Technical']), label+':Chart集合')
        for k, v in e['Technical'].items():
            if k in mask and not mask[k]:
                self.need(type(a['Technical'][k]) in (int, float) and math.isfinite(a['Technical'][k]), label+'.未知表現有限')
                self.unknown += 1
                continue
            self.tree(a['Technical'][k], v, label+'.Technical.'+k, k in mask)
        for k in e:
            if k == 'Technical':
                continue
            if k in ('PreviousClose3', 'PreviousEMA8_3') and not e['Previous3Known']:
                self.need(type(a[k]) in (int, float) and math.isfinite(a[k]), label+'.前足未知表現有限')
                self.unknown += 1
                continue
            self.tree(a[k], e[k], label+'.'+k, k in ('PreviousClose3', 'PreviousEMA8_3'))
        self.predicates(a, e, mask, label)

    def predicates(self, actual: dict, expected: dict, mask: dict, label: str) -> None:
        """
        機能: 採否で使うstrict不等式は数値許容誤差で丸めず照合する。
        引数: actual/expected/mask(dict)、label(str)はChartViewと個別既知性。
        返り値: None。新しい金融採否は行わない。
        """
        a, e = actual['Technical'], expected['Technical']
        operations = []
        for side in (-1, 1):
            for left, right in [('ema8_3', 'ema21_3'), ('ema8_15', 'ema21_15'), ('histogram3', 'previous_histogram3'), ('close3', 'ema8_3')]:
                if mask.get(left) and mask.get(right):
                    operations.append((f'{side}:{left}>{right}', side*(a[left]-a[right]) > 0, side*(e[left]-e[right]) > 0))
            if expected['Previous3Known'] and mask['close3']:
                operations.append((f'{side}:前Close進行', side*(a['close3']-actual['PreviousClose3']) > 0, side*(e['close3']-expected['PreviousClose3']) > 0))
        if all(mask[k] for k in ('tr3', 'previous_atr3', 'rsi3', 'previous_rsi3')):
            operations.append(('同時spike', a['tr3'] > 2*a['previous_atr3'] and abs(a['rsi3']-a['previous_rsi3']) > 15,
                e['tr3'] > 2*e['previous_atr3'] and abs(e['rsi3']-e['previous_rsi3']) > 15))
        for name, av, ev in operations:
            self.strict += 1
            self.need(av == ev, label+':strict境界差:'+name)

    def result(self) -> dict:
        """
        機能: 原値全転記なしの小型集計を返す。
        引数: なし。
        返り値: dictは照合件数/誤差/未知/strict数。
        """
        return dict(照合数=self.checks, 既知数値照合数=self.numeric, 未知値確認skip=self.unknown,
                    strict境界照合数=self.strict, 最大絶対誤差=self.max_error, 最大誤差箇所=self.worst, 不一致数=0)

    def recent_predicates(self, actual: list, expected: list, label: str) -> None:
        """
        機能: Bの固定L/奪還/維持/再進行を許容誤差なしで照合する。
        引数: actual(list[Snapshot])、expected(list[Publication])、label(str)は最新公開3足。
        返り値: None。候補の現在BBO/量は他監査へ分担する。
        """
        if len(expected) != 3 or not all(p['snapshot']['three']['data_known'] for p in expected):
            return
        masks = [p['mask'] for p in expected]
        if not masks[0]['ema8_3'] or not all(m['close3'] for m in masks) or not all(m['rsi3'] for m in masks[1:]):
            return
        a = [s['chart']['Technical'] for s in actual]
        e = [p['snapshot']['chart']['Technical'] for p in expected]
        for side in (-1, 1):
            for name, av, ev in [
                ('a固定線反対側',side*(a[0]['close3']-a[0]['ema8_3'])<=0,side*(e[0]['close3']-e[0]['ema8_3'])<=0),
                ('b固定線奪還',side*(a[1]['close3']-a[0]['ema8_3'])>0,side*(e[1]['close3']-e[0]['ema8_3'])>0),
                ('c固定線維持',side*(a[2]['close3']-a[0]['ema8_3'])>0,side*(e[2]['close3']-e[0]['ema8_3'])>0),
                ('c価格再進行',side*(a[2]['close3']-a[1]['close3'])>0,side*(e[2]['close3']-e[1]['close3'])>0),
                ('cRSI再進行',side*(a[2]['rsi3']-a[1]['rsi3'])>0,side*(e[2]['rsi3']-e[1]['rsi3'])>0)]:
                self.strict += 1
                self.need(av==ev,f'{label}:strictB:{side}:{name}')


def walk_raw(path: Path, scene: str, reference: str, quality: dict, base):
    """
    機能: 固定loaderの採用規則でLast0も含め全受理原行を返す。
    引数: path(Path)、scene/reference(str)、quality(dict)、base(module)は入力/品質/固定reader。
    返り値: iterator[dict]は再時刻化しない板行。
    """
    clock = base.session_clock(scene)
    previous, index = clock['start'], 0
    quality.update(lines=0, clock_missing=0, outside=0, backward=0, accepted=0, bad_last=0, bad_quote=0)
    codes = set()
    with gzip.open(path, 'rt', encoding='utf-8') as stream:
        for line, text in enumerate(stream, 1):
            quality['lines'] = line
            raw = json.loads(text, object_pairs_hook=unique, parse_constant=base.bad_constant)
            if type(raw) is not dict or type(raw.get('Symbol')) is not str:
                raise ValueError('原板Symbol不正')
            codes.add(raw['Symbol'])
            if raw.get('CurrentPriceTime') is not None and type(raw['CurrentPriceTime']) is not str:
                raise ValueError('原板価格時計の型不正')
            at = base.parse_clock(raw.get('CurrentPriceTime'))
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
            last = base.number(raw, 'CurrentPrice')
            prices = {}
            for side in ('Buy', 'Sell'):
                for depth in range(1, 11):
                    level = raw[side+str(depth)] or {}
                    if type(level) is not dict:
                        raise ValueError('原板段型不正')
                    price, _ = base.number(level, 'Price'), base.number(level, 'Qty')
                    if depth == 1:
                        prices[side] = price
            quality['bad_last'] += int(last <= 0)
            quality['bad_quote'] += int(not 0 < prices['Buy'] < prices['Sell'])
            quality['accepted'] += 1
            yield dict(reference=reference, time=at, index=index, line=line, last=last, bid=prices['Buy'], ask=prices['Sell'], valid=last > 0)
            index += 1
    quality['contracts'] = sorted(codes)


def merge_raw(streams: dict):
    """
    機能: stableなTOPIX先行/同市場物理順で時刻列をmergeする。
    引数: streams(dict[str,iterator])は2市場の採用行。
    返り値: iterator[dict]は元価格時計の統合列。
    """
    heap = []
    for rank, ref in enumerate(('TOPIX', 'NK225')):
        one = next(streams[ref], None)
        if one is not None:
            heapq.heappush(heap, (one['time'], rank, one['line'], one))
    while heap:
        _, rank, _, one = heapq.heappop(heap)
        yield one
        following = next(streams[one['reference']], None)
        if following is not None:
            heapq.heappush(heap, (following['time'], rank, following['line'], following))


def inspect_scene(input_scene: dict, source_root: Path, saved: dict, seed: dict | None, base, audit: Comparison) -> tuple:
    """
    機能: 全原板と5分時計からチャートだけを因果再生し保存値へ結ぶ。
    引数: input_scene/saved(dict)、source_root(Path)、seed(dict|None)、base(module)、audit(Comparison)。
    返り値: tupleは次場数値種と小型検査結果。
    """
    name = input_scene['id']
    clock = base.session_clock(name)
    bank = Bank(dict(id=name, contract=input_scene['contract'], start=clock['start']), seed)
    quality, streams = {}, {}
    for ref in ('TOPIX', 'NK225'):
        quality[ref] = {}
        streams[ref] = walk_raw(source_root/input_scene['files'][ref+'_book']['path'], name, ref, quality[ref], base)
    pending = [300*math.ceil(clock['start']/300)+300*n for n in range(math.ceil((clock['end']-clock['start'])/300))]
    pending = [t for t in pending if t < clock['end']]
    saved_grids = saved['chart_grids']
    grid_index, pointer, history, publications = 0, 0, [], 0
    last = None
    for row in merge_raw(streams):
        last = row
        times = []
        while pointer < len(pending) and pending[pointer] <= row['time']:
            times.append(pending[pointer])
            pointer += 1
        batch = bank.advance(row['time'], times)
        pi = 0
        for gi, at in enumerate(times):
            while pi < len(batch['publications']) and batch['publications'][pi]['at'] <= at:
                history.append(batch['publications'][pi])
                history = history[-3:]
                pi += 1
            audit.need(grid_index < len(saved_grids), name+':保存grid不足')
            current = saved_grids[grid_index]
            audit.tree(current['at'], at, name+':grid時計')
            audit.tree(current['snapshot_id'], f'{name}-G{grid_index+1:04d}', name+':gridID')
            audit.tree(current['kind'], name.split('_')[1], name+':場種')
            audit.snapshot(current['chart'], batch['grids'][gi], batch['grid_masks'][gi], f'{name}.grid{grid_index+1}')
            audit.need(len(current['recent3']) == len(history), name+':最新3公開足数')
            for i, record in enumerate(history):
                audit.snapshot(current['recent3'][i], record['snapshot'], record['mask'], f'{name}.grid{grid_index+1}.recent{i}')
            audit.recent_predicates(current['recent3'],history,f'{name}.grid{grid_index+1}')
            grid_index += 1
        while pi < len(batch['publications']):
            history.append(batch['publications'][pi])
            history = history[-3:]
            pi += 1
        publications += len(batch['publications'])
        if row['reference'] == 'NK225':
            q = {k: row[k] for k in ('time', 'index', 'line', 'last', 'bid', 'ask', 'valid')}
            added = bank.step(q, [])
            audit.need(not added['publications'] and not added['grids'], name+':同時計で公開再生成0')
    audit.need(last is not None, name+':原板欠測')
    final_mask = bank.numeric_mask()
    new_seed, end = bank.seal()
    audit.snapshot(saved['chart_end'], end, final_mask, name+'.chart_end')
    audit.need(grid_index == len(saved_grids), name+':保存余剰grid')
    for ref in quality:
        audit.need(len(quality[ref]['contracts']) == 1, name+':原板Symbol単一')
    audit.need(quality['NK225']['contracts'] == [input_scene['contract']], name+':NK限月')
    audit.need(end['observed_clock'] == last['time'] and end['at'] == last['time'], name+':EOF先締め0')
    audit.need(end['chart']['Technical']['bar3_end'] <= last['time'] and end['chart']['Technical']['bar15_end'] <= last['time'], name+':未来確定足0')
    return new_seed, dict(session=name, grids=grid_index, publications=publications, quality=quality,
        carried_numeric_seed=end['carried_numeric_seed'], end_at=end['at'], last_reference=last['reference'])


def select_sessions(manifest: dict, limit: int) -> list:
    """
    機能: 固定日付範囲の54場を先に抽出し、許可された先頭件数だけを選ぶ。
    引数: manifest(dict)、limit(int)は固定80台帳と2又は54。
    返り値: listは順番を変えない対象場。重複/欠落/対象混入はValueError。
    """
    if type(limit) is not int or limit not in (2, 54):
        raise ValueError('limitは2又は54だけ')
    selected = []
    for scene in manifest['sessions']:
        name = scene.get('id')
        if type(name) is not str or re.fullmatch(r'\d{4}-\d{2}-\d{2}_(Day|Night)', name) is None:
            raise ValueError('場IDの型/形式が不正')
        day = name.split('_')[0]
        dt.date.fromisoformat(day)
        if '2026-09-21' <= day <= '2026-10-27':
            selected.append(scene)
    names = [s['id'] for s in selected]
    if len(names) != 54 or len(set(names)) != 54 or names != sorted(names) or names[:2] != ALLOWED or names[-2:] != ['2026-10-27_Day','2026-10-27_Night']:
        raise ValueError('固定54場の範囲/件数/重複/順序が不一致')
    return selected[:limit]


def bind_completion(results: Path, selected: list, limit: int) -> dict:
    """
    機能: Native完了証拠と全対象の名前/本文SHAを照合する。
    引数: results(Path)、selected(list)、limit(int)はNative先と確定した対象。
    返り値: dictは完了JSONの識別情報。欠落/不完了/55場混入はValueError。
    """
    if limit not in (2,54) or len(selected) != limit or (results/'不完了.json').exists():
        raise ValueError('対象件数又はNative不完了')
    path = results/'完了.json'
    completed = load(path)
    if type(completed.get('場数')) is not int or completed['場数'] != limit or type(completed.get('Actor数')) is not int or completed['Actor数'] != 16:
        raise ValueError('Native完了の場数/Actor数が不一致')
    for key in ('G0対95全文一致','Shadow93全文一致','助走対本再生の場末公開値一致'):
        if completed.get(key) is not True:
            raise ValueError('Native完了の保証不足:'+key)
    if completed.get('試行') != 96 or completed.get('台帳SHA256') != MANIFEST_SHA:
        raise ValueError('Native完了の試行/台帳SHAが不一致')
    names = {s['id']+'.json' for s in selected}
    saved = completed.get('結果SHA256')
    if type(saved) is not dict or set(saved) != names:
        raise ValueError('Native完了の結果名集合が不一致')
    actual_names = {p.name for p in results.glob('*.json') if re.fullmatch(r'\d{4}-\d{2}-\d{2}_(Day|Night)\.json', p.name)}
    if actual_names != names:
        raise ValueError('Native結果の欠落/対象外場混入')
    for name in sorted(names):
        if type(saved[name]) is not str or re.fullmatch(r'[0-9a-f]{64}',saved[name]) is None or digest(results/name) != saved[name]:
            raise ValueError('Native結果の本文SHA差:'+name)
    return dict(path=str(path.resolve()), sha256=digest(path), 場数=limit, Actor数=16, Native結果SHA256=saved)


def main() -> int:
    """
    機能: Native完了へ結合した対象を照合し、指紋と数を新規JSONへ残す。
    引数: CLI --results/--manifest/--out は必須Path、--limitは2又は54（既定2）。
    返り値: intは成功0又は失敗1。
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--results', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--limit', type=int, choices=(2,54), default=2)
    args = parser.parse_args()
    if args.out.exists():
        raise ValueError('出力は既存上書禁止')
    if digest(args.manifest) != MANIFEST_SHA:
        raise ValueError('固定80台帳SHA差')
    manifest = load(args.manifest)
    selected = select_sessions(manifest, args.limit)
    completion = bind_completion(args.results, selected, args.limit)
    root = Path(manifest['source_root'])
    paths = [args.manifest, args.results/'完了.json'] + [ROOT/p for p in CORE] + [READER_PATH, Path(__file__), Path(__file__).with_name('chart_numeric.py')]
    for s in selected:
        paths.append(args.results/(s['id']+'.json'))
        for ref in ('TOPIX', 'NK225'):
            p = root/s['files'][ref+'_book']['path']
            if digest(p) != s['files'][ref+'_book']['sha256'] or p.stat().st_size != s['files'][ref+'_book']['size']:
                raise ValueError('原板固定台帳差:'+str(p))
            paths.append(p)
    before = {str(p.resolve()): digest(p) for p in paths}
    if before[str((args.results/'完了.json').resolve())] != completion['sha256']:
        raise ValueError('Native完了が結合後に変化')
    for name, expected in completion['Native結果SHA256'].items():
        if before[str((args.results/name).resolve())] != expected:
            raise ValueError('Native結果が結合後に変化:'+name)
    for p, expected in CORE.items():
        if before[str((ROOT/p).resolve())] != expected:
            raise ValueError('固定GoコードSHA差:'+p)
    audit, details, seed = Comparison(), [], None
    try:
        base = reader()
        for scene in selected:
            # ----------------------------------------
            # Actors/Source/損益のfieldへはアクセスせず、許可された共有チャートだけを使います。
            raw = load(args.results/(scene['id']+'.json'))
            saved = {k: raw[k] for k in ('chart_grids', 'chart_end')}
            del raw
            seed, detail = inspect_scene(scene, root, saved, seed, base, audit)
            details.append(detail)
        failure = None
    except Exception as exc:
        failure = str(exc)
    after = {str(p.resolve()): digest(p) for p in paths}
    result = dict(成功=failure is None and before == after, 完了時刻=dt.datetime.now().astimezone().isoformat(),
        対象=f'固定54内の先頭{args.limit}場のchart_grids/chart_endのみ・損益/Current/Actor未参照', 場数=len(details), 予定場数=args.limit,
        場別=details, 集計=audit.result(), 誤差={'abs':ABS_TOL,'rel':REL_TOL,'strict境界':'許容誤差を使用しない'},
        失敗=failure, 入力前SHA256=before, 入力後SHA256=after, 入力不変=before == after,
        原板本文=f'対象{args.limit}場のNK225/TOPIX計{args.limit*2}ファイルだけ・CSV未読', 指標計算='独立Python・Go金融/Source呼出0',
        限界=f'対象{args.limit}場だけ。数量Current・金融・Source生成の検査は別担当。unknown数値の0は数値一致へ数えない。',
        Native完了結合=completion)
    if failure is not None:
        result['集計']['不一致数'] = 1
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    print(json.dumps({k:result[k] for k in ('成功','場数','集計','失敗','入力不変')},ensure_ascii=False))
    return 0 if result['成功'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
