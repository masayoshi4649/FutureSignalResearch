"""95の一回出生slot・quiet・現在Source・旧金融不変を独立照合する。"""

import argparse
import concurrent.futures
import copy
import gzip
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
BASE_PATH = ROOT/'scripts/FAR個別利益追尾の監査/原板と保護の照合.py'
BASE_SHA = '1437804124be71ba5254b57b583c8cc4db247f3bbb8749f89a6ac07c55caf5a6'
NEW_TOP = {'entry_opportunities','grid_traces','grid_metrics'}
GRID_METRICS = set(('births grid_calls quiet_grids unknown_us_grids accepted expired '
    'required_unknown eof_expired new_grids holding_grids waiting_grids unknown_grids').split())


def digest(path: Path) -> str:
    """
    機能: 読取対象のSHA256を計算する。
    引数: path(Path)は固定コード又は明示入力。
    返り値: strはSHA256。
    """
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for data in iter(lambda:stream.read(1048576),b''):
            h.update(data)
    return h.hexdigest()


def load_base():
    """
    機能: 停止94の監査式と全原行状態器だけを固定再用する。
    引数: なし。
    返り値: moduleは固定94監査。金融Goを実行しない。
    """
    if digest(BASE_PATH) != BASE_SHA:
        raise ValueError('固定94監査のSHA差')
    spec = importlib.util.spec_from_file_location('固定94Raw部品95',BASE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


BASE = load_base()
Audit = BASE.Audit


def assigned_slot(birth: float) -> float:
    """
    機能: 出生と同時計を除いた最初の5分格子を計算する。
    引数: birth(float)は実際の元出生価格時計。
    返り値: floatはstrict次slot。不正値はValueError。
    """
    if not BASE.finite(birth) or birth <= 0:
        raise ValueError('出生時計不正')
    return 300 * (math.floor(birth/300)+1)


def legacy_projection(actual: dict) -> dict:
    """
    機能: Root指定の新top3とConfig2だけを旧94比較から除く。
    引数: actual(dict)は95Actor公開結果。
    返り値: dictは共有子を変更しない旧型射影。除外を増やさない。
    """
    if not NEW_TOP <= set(actual) or not {'entry_timing','us_open'} <= set(actual['config']):
        raise ValueError('95新公開fieldが欠落')
    out = {k:v for k,v in actual.items() if k not in NEW_TOP}
    out['config'] = {k:v for k,v in actual['config'].items() if k not in ('entry_timing','us_open')}
    return out


class GridPath(BASE.ActorPath):
    """源通知・旧利益保護は94を再用し、新規受付と新診断だけを別実装する。"""

    def __init__(self, actual: dict, audit: Audit):
        """
        機能: 95の新境界と旧金融状態を初期化する。
        引数: actual(dict)、audit(Audit)は実型保存値と検査器。
        返り値: None。出生gateや金融式を新たに推定しない。
        """
        self.timing, self.us = actual['config']['entry_timing'], actual['config']['us_open']
        audit.need(self.timing in ('N','B5','B5Q') and BASE.finite(self.us) and self.us >= 0,'95設定型')
        audit.need(self.timing == 'N' or actual['config']['policy'] == 'P0','B系はP0固定')
        session = actual['session']
        if session['kind'] == 'Night':
            audit.need(self.us == 0 and self.timing == 'N' or session['start'] < self.us < session['end'],'Night米国時計')
        old = legacy_projection(actual)
        old_key = f"{old['config']['policy']}_C{old['config']['slip_pts']:g}_D{old['config']['delay_seconds']}"
        expected_key = old_key if self.timing == 'N' else self.timing+'_'+old_key
        audit.equal(actual['key'],expected_key,'95金融key')
        init = dict(old,key=old_key)
        super().__init__(init,audit)
        self.actual, self.key = old, expected_key
        self.extra_actual = actual
        self.opportunities, self.grids, self.op_by_source = [], [], {}
        audit.equal(set(actual['grid_metrics']),GRID_METRICS,'GridMetrics集合')
        self.gm = {k:0 for k in GRID_METRICS}
        self.last_grid = None

    def capacity(self, side: int) -> int:
        """
        機能: 実所有と未取得newを片側10から引く。
        引数: side(int)は元出生方向。
        返り値: intは空き。返済予約では空きを増やさない。
        """
        used = sum(p['quantity'] for p in self.positions.values() if p['side'] == side)
        used += sum(o['quantity'] for o in self.orders if o['side'] == side and o['kind'] == 'entry' and o['status'] == 'pending')
        self.audit.need(0 <= used <= 10,'95予約込み片側上限')
        return 10-used

    def append_opportunity(self, key: tuple, batch_index: int, signal_index: int) -> dict:
        """
        機能: 全出生を元の登録順で一回だけ保存する。
        引数: key(tuple)、batch_index/signal_index(int)は元出典と順番。
        返り値: dictは未消費機会。まだHold IDを創作しない。
        """
        self.audit.need(key not in self.op_by_source,'出生機会重複')
        source = self.sources[key]
        p = dict(ordinal=len(self.opportunities)+1,source=copy.deepcopy(source['identity']),
            side=source['signal']['side'],batch_index=batch_index,signal_index=signal_index,
            assigned_at=assigned_slot(source['signal']['time']),consumed=False,evaluated_at=None,
            status='scheduled',required_unknown=False,reason='',source_state='',source_hold_id='',
            source_quantity=None,source_reserved=None,quote=None,quote_age_seconds=None,
            available=0,requested=0,entry_order_id='')
        self.op_by_source[key] = len(self.opportunities)
        self.opportunities.append(p)
        self.gm['births'] += 1
        return p

    def accept_sources(self, at: float, prepared: list) -> None:
        """
        機能: Nは旧受理を保ち、Bは全出生を新slot機会へ登録する。
        引数: at(float)、prepared(list)は当原行の保存源通知。
        返り値: None。Source new自体を落としたり時刻を変えたりしない。
        """
        before = len(self.events)
        if self.timing == 'N':
            super().accept_sources(at,prepared)
        n_events = {(e['method'],e['signal_id']):e for e in self.events[before:] if e['kind'] == 'new_signal'}
        for bi,(method,delta) in enumerate(prepared):
            for si,record in enumerate(delta['signals']):
                signal = record['signal']
                if signal['action'] != 'new':
                    continue
                key = method,signal['id']
                p = self.append_opportunity(key,bi,si)
                source = self.sources[key]
                if self.timing == 'N':
                    event = n_events[key]
                    qty = event['actual_accepted']
                    p.update(consumed=True,evaluated_at=at,available=event['available'],requested=qty,
                        entry_order_id=event['order_id'],status='accepted' if qty else 'expired',
                        reason=event['reason'],source_state=source['state'],quote=copy.deepcopy(p['source']['birth_quote']),
                        quote_age_seconds=0.0)
                    self.gm['accepted' if qty else 'expired'] += 1
                else:
                    self.events.append(BASE.empty_event(at,method,'native_new','new_signal',record['quote'],
                        signal_id=signal['id'],side=signal['side'],quantity=signal['quantity'],
                        available=self.capacity(signal['side']),reason='出生を最初の次5分枠へ割当'))

    def quiet(self, at: float) -> tuple:
        """
        機能: slot時点の開始/米国30分区間を半開で判定する。
        引数: at(float)は5分時計。
        返り値: tuple[bool,str,bool又はNone]はquietと根拠。
        """
        quiet = self.session['start'] <= at < self.session['start']+1800
        reason = 'セッション開始30分' if quiet else ''
        us_quiet = None
        if self.session['kind'] == 'Night' and self.us > 0:
            us_quiet = self.us <= at < self.us+1800
            if us_quiet:
                quiet,reason = True,'米国開始30分'
        return quiet,reason,us_quiet

    def evaluate(self, p: dict, at: float, quiet: bool, trace: dict) -> None:
        """
        機能: 一機会を当枠だけの源現在状態/既Quote/capで判定する。
        引数: p/trace(dict)、at(float)、quiet(bool)は機会と当時状態。
        返り値: None。遅着・quiet・未知を後の枠へ戻さない。
        """
        key = p['source']['method'],p['source']['signal_id']
        source = self.sources[key]
        p.update(consumed=True,evaluated_at=at,status='expired',source_state=source['state'],available=self.capacity(p['side']))
        if self.last is not None:
            p.update(quote=copy.deepcopy(self.last),quote_age_seconds=at-self.last['time'])
        hold = self.holds.get((key[0],source['hold'])) if source['hold'] else None
        if hold is not None:
            p.update(source_hold_id=source['hold'],source_quantity=hold['quantity'],source_reserved=hold['reserved'])
        deadline = self.session['force_close']
        if key[0] == 'NK225_P164_06':
            deadline = min(deadline,self.us-900)
        reason = ''
        if p['assigned_at'] != at:
            reason = '割当枠を通過・後の枠へ復活しない'
        elif at >= deadline:
            reason = '元手法Force境界以降'
        elif quiet and self.timing == 'B5Q':
            reason = '割当枠が開始30分見送り'
        elif source['state'] == 'cancelled':
            reason = 'Native取消済みの出生'
        elif source['state'] == 'pending':
            reason = '割当枠でSource未取得'
        elif source['state'] != 'filled' or hold is None:
            raise ValueError('取得済みSource Hold出典なし')
        elif hold['quantity'] == 0:
            reason = '割当枠でSource完結済み'
        elif hold['reserved'] > 0:
            reason = '割当枠でSource返済予約あり'
        elif not trace['quote_known']:
            reason = '割当枠の最新原行の正常気配が必要未知'
            p['required_unknown'] = True
        elif p['available'] == 0:
            reason = '片側上限に空きなし'
            self.count('cap_rejected_entries')
        else:
            quantity = min(source['signal']['quantity'],hold['quantity'],p['available'])
            self.audit.need(quantity > 0,'slot正の要求量')
            if p['available'] < min(source['signal']['quantity'],hold['quantity']):
                self.count('cap_clipped_entries')
            order = self.request('entry',p['side'],quantity,source['identity'],at,self.last,source['signal']['reason'])
            order['source_hold_id'] = source['hold']
            self.entry_sources[key] = len(self.orders)-1
            p.update(requested=quantity,entry_order_id=order['id'],status='accepted')
            reason = '出生量・Source現在残量・片側余力のminを一度受理'
            trace['accepted_count'] += 1
            trace['accepted_quantity'] += quantity
            self.gm['accepted'] += 1
        p['reason'] = reason
        if p['status'] != 'accepted':
            self.entry_sources[key] = None
            trace['expired_count'] += 1
            self.gm['expired'] += 1
        if p['required_unknown']:
            trace['unknown_count'] += 1
            self.gm['required_unknown'] += 1

    def grid(self, at: float) -> None:
        """
        機能: 価格・MTM・ATRを更新せず一枠だけ実新規受付する。
        引数: at(float)は増加する場内5分時計。
        返り値: None。既Quoteは再時刻化しない。
        """
        self.audit.need(BASE.finite(at) and at % 300 == 0 and self.session['start'] <= at < self.session['end']
            and at >= self.last_event and (self.last_grid is None or at > self.last_grid),'grid時計/端/順序')
        quiet,reason,us_quiet = self.quiet(at)
        trace = dict(at=at,timing=self.timing,quote=copy.deepcopy(self.last),quote_known=self.last is not None and BASE.quote_ok(self.last),
            quote_age_seconds=None if self.last is None else at-self.last['time'],
            us_clock_known=self.session['kind']=='Day' or self.us>0,us_quiet=us_quiet,
            quiet=quiet,quiet_applied=quiet and self.timing=='B5Q',quiet_reason=reason,
            candidate_count=0,accepted_count=0,accepted_quantity=0,expired_count=0,unknown_count=0,
            open_buy=0,open_sell=0,pending_buy=0,pending_sell=0,action='',reason='',ordinals=[])
        if self.last is not None:
            self.audit.need(self.last['time'] <= at,'grid未来Quote拒否')
        if self.timing != 'N':
            for p in self.opportunities:
                if p['consumed'] or p['assigned_at'] > at:
                    continue
                trace['candidate_count'] += 1
                trace['ordinals'].append(p['ordinal'])
                self.evaluate(p,at,quiet,trace)
        for p in self.positions.values():
            trace['open_buy' if p['side']==1 else 'open_sell'] += p['quantity']
        for order in self.orders:
            if order['kind']=='entry' and order['status']=='pending':
                trace['pending_buy' if order['side']==1 else 'pending_sell'] += order['quantity']
        if trace['accepted_count']:
            trace.update(action='新規',reason='当5分枠で実新規要求を受理')
            self.gm['new_grids'] += 1
        elif trace['open_buy']+trace['open_sell']:
            trace.update(action='保有',reason='実保有の継続')
            self.gm['holding_grids'] += 1
        elif trace['unknown_count']:
            trace.update(action='判定不能',reason='候補の必須情報が未知')
            self.gm['unknown_grids'] += 1
        else:
            trace.update(action='待機',reason='実新規約定待ち' if trace['pending_buy']+trace['pending_sell'] else '当枠に受理できる候補なし')
            self.gm['waiting_grids'] += 1
        self.gm['grid_calls'] += 1
        self.gm['quiet_grids'] += int(quiet)
        self.gm['unknown_us_grids'] += int(not trace['us_clock_known'])
        self.grids.append(trace)
        self.last_grid,self.last_event = at,at

    def expire_eof(self) -> None:
        """
        機能: 未消費機会だけを現在のSource/最終Quote出典でEOF失効する。
        引数: なし。
        返り値: None。新grid/実要求/MTM/価格を作らない。
        """
        for p in self.opportunities:
            if p['consumed']:
                continue
            key = p['source']['method'],p['source']['signal_id']
            p.update(consumed=True,evaluated_at=self.last_event,status='expired',reason='EOFで未消費出生機会を失効')
            source = self.sources[key]
            p.update(source_state=source['state'],source_hold_id=source['hold'],available=self.capacity(p['side']))
            hold = self.holds.get((key[0],source['hold']))
            if hold is not None:
                p.update(source_quantity=hold['quantity'],source_reserved=hold['reserved'])
            if self.last is not None:
                p.update(quote=copy.deepcopy(self.last),quote_age_seconds=self.last_event-self.last['time'])
            self.entry_sources[key] = None
            self.gm['expired'] += 1
            self.gm['eof_expired'] += 1

    def finish(self) -> dict:
        """
        機能: EOF失効と旧金融/新診断をそれぞれ全fieldで検査する。
        引数: なし。
        返り値: dictは監査済みの一口座scope。
        """
        if self.extra_actual['finished']:
            self.expire_eof()
        result = super().finish()
        BASE.compare_tree(self.extra_actual['entry_opportunities'],self.opportunities,self.audit,self.key+'/機会')
        BASE.compare_tree(self.extra_actual['grid_traces'],self.grids,self.audit,self.key+'/全grid')
        BASE.compare_tree(self.extra_actual['grid_metrics'],self.gm,self.audit,self.key+'/grid計数')
        return dict(result,entry_timing=self.timing,opportunities=len(self.opportunities),grids=len(self.grids))


def fixture_calls(value: dict) -> list:
    """
    機能: API人工の明示呼出順を取り出す。
    引数: value(dict)はGoMarshal人工。
    返り値: listはquote/timer/gridの実順。
    """
    if 'calls' in value:
        return value['calls']
    if 'events' not in value:
        raise ValueError('95人工は同秒の順序を明示するcalls/eventsが必要')
    calls,used = [],{'quote':set(),'timer':set(),'grid':set()}
    groups = {'quote':value['steps'],'timer':value['timers'],'grid':value['grids']}
    for event in value['events']:
        kind,index = event['kind'],event['index']
        if kind not in groups or type(index) is not int or not 0 <= index < len(groups[kind]) or index in used[kind]:
            raise ValueError('人工eventsの種別/索引/重複')
        used[kind].add(index)
        item = groups[kind][index]
        calls.append(dict(kind='grid',at=item) if kind=='grid' else dict(item,kind=kind))
    if any(used[k] != set(range(len(v))) for k,v in groups.items()):
        raise ValueError('eventsへ結合しない人工呼出')
    return calls


def inspect_fixture(value: dict) -> dict:
    """
    機能: Go実型人工の全金融と新grid境界を独立再構築する。
    引数: value(dict)はcallsとactorsを持つ非0人工。
    返り値: dictは範囲と照合件数。原板/Source自然発生は証明しない。
    """
    audit = Audit()
    books = value.get('actors',value.get('books'))
    audit.need(type(books) is dict and bool(books),'人工Actor集合')
    models = [GridPath(book,audit) for book in books.values()]
    for call in fixture_calls(value):
        if call['kind']=='quote':
            q,atr = BASE.observation_quote(call['observation'],call['source_line'])
            for model in models:
                model.step(q,call['batches'],atr)
        elif call['kind']=='timer':
            for model in models:
                model.timer(call['at'],call['batches'])
        elif call['kind']=='grid':
            for model in models:
                model.grid(call['at'])
        else:
            raise ValueError('人工呼出種別不正')
    details = [model.finish() for model in models]
    baselines = value.get('baseline94',value.get('legacy_n',{}))
    baseline_count = 0
    for book in books.values():
        if book['config']['entry_timing']=='N' and baselines:
            audit.need(book['key'] in baselines,'N旧94 baseline欠落')
            BASE.compare_tree(legacy_projection(book),baselines[book['key']],audit,'N対94の5field除外全文')
            baseline_count += 1
    return dict(成功=True,scope='Go手製API人工の全金融/一回slot境界。自然Source/全原板/公式時計driverは未計測',
        会計数=len(details),照合項目数=audit.checks,不一致数=0,N基準会計数=baseline_count,details=details)


# ----------------------------------------
def scan_board_clock(path: Path, session: str) -> tuple:
    """
    機能: Last0を含む受理boardの最終価格時計を独立復元する。
    引数: path(Path)、session(str)は明示された固定市場原板と場。
    返り値: tuple[float又はNone,dict]はEOF時計上限と時計品質。BBO/Sourceを再生しない。
    """
    clock = BASE.BASE.session_clock(session)
    previous,last,codes = clock['start'],None,set()
    quality = dict(lines=0,clock_missing=0,outside=0,backward=0,accepted=0,contracts=[])
    with gzip.open(path,'rt',encoding='utf-8') as stream:
        for line,text in enumerate(stream,1):
            quality['lines'] = line
            raw = json.loads(text,parse_constant=BASE.BASE.bad_constant,object_pairs_hook=BASE.unique_pairs)
            if type(raw) is not dict or type(raw.get('Symbol')) is not str:
                raise ValueError('時計原板Symbol型')
            codes.add(raw['Symbol'])
            at = BASE.BASE.parse_clock(raw.get('CurrentPriceTime'))
            if at is None:
                quality['clock_missing'] += 1
            elif not clock['start'] <= at < clock['end']:
                quality['outside'] += 1
            elif at < previous:
                quality['backward'] += 1
            else:
                previous,last = at,at
                quality['accepted'] += 1
    quality['contracts'] = sorted(codes)
    return last,quality


def grid_schedule(session: str, clock_end: float | None) -> list:
    """
    機能: 両市場受理時計までの場内5分格子だけを列挙する。
    引数: session(str)、clock_end(float又はNone)は場と実観測上限。
    返り値: list[float]は開始含む・終了除外・EOF後なしの全予定grid。
    """
    clock = BASE.BASE.session_clock(session)
    if clock_end is None:
        return []
    start = 300*math.ceil(clock['start']/300)
    return [float(at) for at in range(start,int(clock['end']),300) if at <= clock_end]


def inspect_one(task: tuple) -> dict:
    """
    機能: 許可された一場を原板両時計/Source保存通知/全旧金融/gridへ結合する。
    引数: task(tuple)は95Path、InputSession、source_root、94固定保存先。
    返り値: dictは全12Actor/旧N4の独立読取結果。新売買は再生しない。
    """
    result_path,input_session,source_root,baseline_folder = task
    result_path,source_root,baseline_folder = Path(result_path),Path(source_root),Path(baseline_folder)
    session = input_session['id']
    if not '2026-09-21' <= session[:10] <= '2026-10-27':
        raise ValueError('既使用54場の期間外は読まない')
    files = input_session['files']
    inputs = {k:source_root/files[k]['path'] for k in ('NK225_book','TOPIX_book','NK225_candle_300')}
    baseline_path = baseline_folder/(session+'.json.gz')
    if not baseline_path.is_file():
        baseline_path = baseline_folder/(session+'.json')
    paths = [result_path,baseline_path,Path(__file__),BASE_PATH,BASE.BASE_PATH]+list(inputs.values())
    before = {str(p.resolve()):digest(p) for p in paths}
    audit = Audit()
    for key,p in inputs.items():
        audit.need(before[str(p.resolve())]==files[key]['sha256'] and p.stat().st_size==files[key]['size'],'固定原入力:'+key)
    value,old = BASE.load(result_path),BASE.load(baseline_path)
    audit.equal((value['session'],old['session']),(session,session),'新旧場')
    audit.need(value['shadow_match']['all'] is True and value['neutral_match']['all'] is True,'Native旧比較の保存証拠')
    audit.equal(value['neutral_match']['baseline_sha256'],before[str(baseline_path.resolve())],'94基準指紋')
    clock = BASE.BASE.session_clock(session)
    expected_keys = {prefix+f'P0_C{c}_D{d}' for prefix in ('','B5_','B5Q_') for c in (0,5) for d in (0,1)}
    audit.equal(set(value['books']),expected_keys,'95全12Actor')
    expected_session = dict(id=session,kind=session.split('_')[1],start=clock['start'],end=clock['end'],force_close=clock['force'],
        us_open=clock['us'],extra_at=clock['us']+1800 if clock['us'] else clock['start']+225*60)
    clocks = []
    for ref in ('NK225','TOPIX'):
        last,quality = scan_board_clock(inputs[ref+'_book'],session)
        if last is not None:
            clocks.append(last)
        for key,expected in quality.items():
            BASE.compare_tree(value['quality'][ref][key],expected,audit,ref+':時計品質/'+key)
    clock_end = max(clocks) if clocks else None
    grids = grid_schedule(session,clock_end)
    models = []
    baseline_count = 0
    for key,book in value['books'].items():
        audit.need(book['finished'] is True and book['complete'] is True and book['failure']=='','95金融完了')
        BASE.compare_tree(book['session'],expected_session,audit,key+':場時計')
        audit.equal(book['config']['us_open'],clock['us'],key+':正式NY時計')
        audit.equal([g['at'] for g in book['grid_traces']],grids,key+':全予定grid')
        if book['config']['entry_timing']=='N':
            BASE.compare_tree(legacy_projection(book),old['books'][key],audit,key+':94全金融')
            baseline_count += 1
        models.append(GridPath(book,audit))
    cfg = value['feature_config']
    audit.need(cfg['atr_period']==12 and cfg['atr_min_bars']==3 and cfg['candle_delay_seconds']==60,'固定ATR条件')
    native = BASE.NativeTape(value['shadows'],session,audit)
    atr = BASE.ATRSeries(BASE.candles_from_csv(inputs['NK225_candle_300'],session),clock['start'])
    force = [clock['force']] + ([clock['us']-900] if clock['us'] else [])
    events = sorted([(at,0) for at in force]+[(at,1) for at in grids])
    ei = 0
    def clock_event(at: float, kind: int) -> None:
        """
        機能: Forceをgridより先に配送し、価格を更新しない。
        引数: at(float)、kind(int)は明示時計とForce0/grid1。
        返り値: None。
        """
        if kind==0:
            batches = native.take(at)
            for model in models:
                model.timer(at,batches)
        else:
            for model in models:
                model.grid(at)
    quality = {}
    for q in BASE.walk_raw(inputs['NK225_book'],session,quality):
        while ei < len(events) and events[ei][0] <= q['time']:
            clock_event(*events[ei])
            ei += 1
        batches = native.take(q['time'],q['source_line'])
        width = atr.asof(q['time'])
        for model in models:
            model.step(q,batches,width)
    for event in events[ei:]:
        clock_event(*event)
    native.finish()
    BASE.compare_tree(value['source_rows'],native.source_rows,audit,'全Source行数')
    BASE.compare_tree(value['quality']['NK225'],quality,audit,'全NK品質')
    audit.equal(value['contract'],input_session['contract'],'限月')
    details = [model.finish() for model in models]
    audit.need(all(digest(Path(p))==h for p,h in before.items()),'入力/code前後不変')
    return dict(session=session,成功=True,会計数=12,N基準会計数=baseline_count,全grid数=len(grids),
        EOF受理時計上限=clock_end,照合項目数=audit.checks,不一致数=0,入力前後不変=True,
        入力SHA256=before,scope='既使用54内・両市場EOF時計/全NK旧金融/出生一枠/全Source/全MTM',details=details)


def self_test() -> dict:
    """
    機能: strict次slot・半開quiet・格子端の基礎を市場なしで確認する。
    引数: なし。
    返り値: dictは手計算人工の照合件数。
    """
    audit = Audit()
    base = 1800000000.0
    audit.equal(assigned_slot(base),base+300,'同時刻出生は次枠')
    audit.equal(assigned_slot(base-.5),base,'前原行出生は当格子')
    audit.equal(assigned_slot(base+.5),base+300,'後原行出生の前倒し禁止')
    for value in (0,-1,float('nan'),float('inf'),True):
        try:
            assigned_slot(value)
        except ValueError:
            audit.need(True,'不正出生拒否')
        else:
            raise AssertionError('不正出生通過')
    return dict(成功=True,scope='基礎slot算術のみ・Go型接続前',照合項目数=audit.checks)


def main() -> int:
    """
    機能: 明示人工又は別途許可後の既使用場を読取監査する。
    引数: --self-test/--run(bool)、--fixture/--input/--manifest/--baseline94/--out(Path)、--workers/--limit(int)。
    返り値: intは成功0、不一致1。
    """
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--self-test',action='store_true')
    mode.add_argument('--fixture',type=Path)
    mode.add_argument('--run',action='store_true')
    parser.add_argument('--input',type=Path)
    parser.add_argument('--manifest',type=Path)
    parser.add_argument('--baseline94',type=Path)
    parser.add_argument('--workers',type=int,default=1)
    parser.add_argument('--limit',type=int)
    parser.add_argument('--out',type=Path,required=True)
    args = parser.parse_args()
    if args.out.exists():
        parser.error('証拠上書き拒否')
    if not 1 <= args.workers <= 8:
        parser.error('workerは1..8')
    if args.run and any(p is None for p in (args.input,args.manifest,args.baseline94)):
        parser.error('実読取は--input --manifest --baseline94を明示')
    before = {str(BASE_PATH):digest(BASE_PATH),str(BASE.BASE_PATH):digest(BASE.BASE_PATH),str(Path(__file__)):digest(Path(__file__))}
    try:
        if args.self_test:
            result = self_test()
        elif args.fixture:
            before[str(args.fixture)] = digest(args.fixture)
            result = inspect_fixture(BASE.load(args.fixture))
        else:
            before[str(args.manifest)] = digest(args.manifest)
            if before[str(args.manifest)] != BASE.BASE.MANIFEST_SHA:
                raise ValueError('固定80台帳SHA差')
            manifest = BASE.load(args.manifest)
            selected = [s for s in manifest['sessions'] if '2026-09-21' <= s['id'][:10] <= '2026-10-27']
            if len(selected)!=54 or len({s['id'] for s in selected})!=54:
                raise ValueError('既使用54場の集合差')
            if args.limit is not None:
                if not 1 <= args.limit <= 54:
                    raise ValueError('limit範囲外')
                selected = selected[:args.limit]
            tasks = [(str(args.input/(s['id']+'.json')),s,manifest['source_root'],str(args.baseline94)) for s in selected]
            if args.workers==1:
                details = [inspect_one(task) for task in tasks]
            else:
                with concurrent.futures.ProcessPoolExecutor(max_workers=args.workers) as pool:
                    details = list(pool.map(inspect_one,tasks))
            result = dict(成功=all(d['成功'] for d in details),scope='既使用54内・両市場EOF/全grid/出生一枠/94旧金融/全原行MTMの独立読取',
                セッション数=len(details),会計数=sum(d['会計数'] for d in details),
                N基準会計数=sum(d['N基準会計数'] for d in details),照合項目数=sum(d['照合項目数'] for d in details),不一致数=0,details=details)
        result['入力前後不変'] = all(digest(Path(p))==h for p,h in before.items())
        result['コード入力SHA256'] = before
        result['成功'] = result['成功'] and result['入力前後不変']
    except Exception as error:
        result = dict(成功=False,不整合=str(error),コード入力SHA256=before)
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:result[k] for k in ('成功','不整合') if k in result},ensure_ascii=False))
    return 0 if result['成功'] else 1


if __name__=='__main__':
    raise SystemExit(main())
