"""原板価格から独立に3/15分の公開指標を計算する。Go・金融・Sourceを呼ばない。"""

import copy
import math


class Mean:
    """初期SMAの後にEMA又はWilder平均を進める。"""

    def __init__(self, period: int, wilder: bool = False):
        """
        機能: 平均の必要本数と未助走状態を作る。
        引数: period(int)、wilder(bool)は期間と更新式。
        返り値: None。
        """
        self.period, self.wilder = period, wilder
        self.count, self.total, self.value, self.known = 0, 0.0, 0.0, False

    def add(self, value: float) -> None:
        """
        機能: 一つの確定値で平均を進める。
        引数: value(float)は有限の観測値。
        返り値: None。助走不足では既知を立てない。
        """
        if not math.isfinite(value):
            raise ValueError('平均の非有限入力')
        if not self.known:
            self.count += 1
            self.total += value
            if self.count == self.period:
                self.value, self.known = self.total/self.period, True
        elif self.wilder:
            self.value = (self.value*(self.period-1)+value)/self.period
        else:
            self.value += 2/(self.period+1)*(value-self.value)


class Series:
    """一尺度の数値種と公開maskを分ける。"""

    def __init__(self):
        """
        機能: 指標を未助走にする。
        引数: なし。
        返り値: None。
        """
        self.ema = {n: Mean(n) for n in (8, 21, 12, 26)}
        self.signal = Mean(9)
        self.gain, self.loss, self.atr = Mean(14, True), Mean(14, True), Mean(14, True)
        self.previous_close, self.previous_close_known = 0.0, False
        self.close = self.rsi = self.previous_rsi = self.hist = self.previous_hist = 0.0
        self.tr = self.previous_atr = self.end = 0.0
        self.rsi_known = self.previous_rsi_known = self.hist_known = self.previous_hist_known = False
        self.previous_atr_known = self.published = False

    def invalidate(self, preserve_publication: bool) -> None:
        """
        機能: 欠足又は不良Lastで数値種を破棄する。
        引数: preserve_publication(bool)は不良原行で旧終端を保持する指定。
        返り値: None。
        """
        end, published = self.end, self.published
        self.__init__()
        if preserve_publication:
            self.end, self.published = end, published

    def close_bar(self, high: float, low: float, close: float, end: float) -> None:
        """
        機能: 確定OHLCだけからEMA/MACD/RSI/ATRを更新する。
        引数: high/low/close/end(float)は確定足。
        返り値: None。
        """
        self.previous_rsi, self.previous_rsi_known = self.rsi, self.rsi_known
        self.previous_hist, self.previous_hist_known = self.hist, self.hist_known
        self.previous_atr, self.previous_atr_known = self.atr.value, self.atr.known
        self.tr = high-low
        if self.previous_close_known:
            self.tr = max(self.tr, abs(high-self.previous_close), abs(low-self.previous_close))
            delta = close-self.previous_close
            self.gain.add(max(delta, 0))
            self.loss.add(max(-delta, 0))
        self.atr.add(self.tr)
        for mean in self.ema.values():
            mean.add(close)
        if self.gain.known and self.loss.known:
            self.rsi_known = True
            if self.gain.value == 0 and self.loss.value == 0:
                self.rsi = 50.0
            elif self.loss.value == 0:
                self.rsi = 100.0
            else:
                self.rsi = 100-100/(1+self.gain.value/self.loss.value)
        if self.ema[12].known and self.ema[26].known:
            macd = self.ema[12].value-self.ema[26].value
            self.signal.add(macd)
            if self.signal.known:
                self.hist, self.hist_known = macd-self.signal.value, True
        self.previous_close, self.previous_close_known = close, True
        self.close, self.end, self.published = close, end, True


class Forming:
    """当場の半開区間のLastだけを集め、数値種と一緒に持ち越さない。"""

    def __init__(self, start: float, width: int):
        """
        機能: 形成足を空にする。
        引数: start(float)、width(int)は開始と秒幅。
        返り値: None。
        """
        self.start, self.width = start, width
        self.high = self.low = self.close = 0.0
        self.count, self.bad = 0, False

    def add(self, last: float) -> None:
        """
        機能: 一原行のLastを形成足へ足す。
        引数: last(float)は正の有限価格。
        返り値: None。
        """
        if self.count == 0:
            self.high = self.low = last
        self.high, self.low, self.close = max(self.high, last), min(self.low, last), last
        self.count += 1

    def advance(self, at: float, series: Series) -> None:
        """
        機能: 当時時計以下の足だけを閉じる。
        引数: at(float)、series(Series)は公開時計と数値種。
        返り値: None。欠足を横ばい足で補完しない。
        """
        end = self.start+self.width
        if end > at:
            return
        if self.count == 0 or self.bad:
            series.invalidate(False)
            series.end, series.published = end, True
        else:
            series.close_bar(self.high, self.low, self.close, end)
        self.__init__(end, self.width)
        if self.start+self.width <= at:
            steps = math.floor((at-self.start)/self.width)
            self.start += steps*self.width
            series.invalidate(False)
            series.end, series.published = self.start, True


def empty_stamp() -> dict:
    """
    機能: 原行未観測の表現を作る。
    引数: なし。
    返り値: dictは未知のSourceStamp。
    """
    return dict(time=0, index=0, line=0, last=0, valid=False)


def empty_evidence() -> dict:
    """
    機能: 未公開の足出典を作る。
    引数: なし。
    返り値: dictは値を補完しない初期表現。
    """
    return dict(bar_end=0, available_at=0, observed_clock=0, rows=0, data_known=False,
                has_last_source=False, last_source=empty_stamp(), reason='')


class Bank:
    """公開timer・原行・Seedの順を独立実装する。"""

    def __init__(self, scene: dict, seed: dict | None = None):
        """
        機能: 当場を開始し、同限月の数値種だけを値copyする。
        引数: scene(dict)、seed(dict|None)は当場と前場のsealed種。
        返り値: None。
        """
        self.scene = copy.deepcopy(scene)
        if not scene['id'] or not scene['contract'] or not math.isfinite(scene['start']) or scene['start'] <= 0:
            raise ValueError('場識別/時計不正')
        carried = False
        if seed is not None:
            if not seed['sealed'] or scene['start'] <= seed['start'] or scene['start'] < seed['observed']:
                raise ValueError('種の未来/未sealed')
            carried = scene['contract'] == seed['contract']
        self.s3, self.s15 = copy.deepcopy(seed['numeric']) if carried else (Series(), Series())
        self.s3.published = self.s15.published = False
        self.f3, self.f15 = Forming(scene['start'], 180), Forming(scene['start'], 900)
        self.next3, self.next15 = scene['start']+180, scene['start']+900
        self.frontier, self.last_raw, self.last_grid, self.sealed = scene['start'], None, None, False
        self.previous = dict(PreviousClose3=0.0, PreviousEMA8_3=0.0, PreviousBar3End=0.0, Previous3Known=False)
        self.form3, self.form15 = [], []
        self.view = dict(scene=copy.deepcopy(scene), at=scene['start'], has_observed_clock=False, observed_clock=0,
                         has_last_input=False, last_input=empty_stamp(), invalidated_at=0,
                         chart=self.chart(), three=empty_evidence(), fifteen=empty_evidence(),
                         carried_numeric_seed=carried, sealed=False)

    def technical(self) -> dict:
        """
        機能: 公開maskに従った固定型の現在数値を作る。
        引数: なし。
        返り値: dictはGoを呼ばず独立計算したTechnicalView。
        """
        v = {k: False for k in ('trend_known', 'reversal_known', 'spike_known', 'exit_known', 'atr_known')}
        v.update({k: 0.0 for k in ('ema8_3 ema21_3 ema8_15 ema21_15 rsi3 previous_rsi3 histogram3 previous_histogram3 '
                                   'close3 tr3 atr3 previous_atr3 bar3_end bar15_end').split()})
        a, z = self.s3, self.s15
        if a.published:
            v.update(bar3_end=a.end, close3=a.close, tr3=a.tr, ema8_3=a.ema[8].value, ema21_3=a.ema[21].value,
                     rsi3=a.rsi, previous_rsi3=a.previous_rsi, histogram3=a.hist, previous_histogram3=a.previous_hist,
                     atr3=a.atr.value, previous_atr3=a.previous_atr,
                     reversal_known=a.ema[8].known and a.rsi_known and a.previous_rsi_known and a.hist_known and a.previous_hist_known,
                     exit_known=a.ema[8].known and a.hist_known and a.previous_hist_known,
                     spike_known=a.rsi_known and a.previous_rsi_known and a.previous_atr_known, atr_known=a.atr.known)
        if z.published:
            v.update(bar15_end=z.end, ema8_15=z.ema[8].value, ema21_15=z.ema[21].value)
        v['trend_known'] = a.published and z.published and all(s.ema[n].known for s in (a, z) for n in (8, 21))
        return v

    def chart(self) -> dict:
        """
        機能: 現確定足と前3分を値copyする。
        引数: なし。
        返り値: dictはChartView。
        """
        return dict(Technical=self.technical(), **copy.deepcopy(self.previous))

    def numeric_mask(self) -> dict:
        """
        機能: 原板から得た個別指標の助走状態を比較用に返す。
        引数: なし。
        返り値: dictは未知0を数値一致件数へ混ぜないmask。
        """
        a, z = self.s3, self.s15
        return dict(ema8_3=a.published and a.ema[8].known, ema21_3=a.published and a.ema[21].known,
                    ema8_15=z.published and z.ema[8].known, ema21_15=z.published and z.ema[21].known,
                    rsi3=a.published and a.rsi_known, previous_rsi3=a.published and a.previous_rsi_known,
                    histogram3=a.published and a.hist_known, previous_histogram3=a.published and a.previous_hist_known,
                    close3=a.published and a.previous_close_known, tr3=a.published and a.previous_close_known,
                    atr3=a.published and a.atr.known, previous_atr3=a.published and a.previous_atr_known)

    def capture(self, before: dict) -> None:
        """
        機能: 更新前後の公開値を結び前確定3分を追跡する。
        引数: before(dict)は更新前TechnicalView。
        返り値: None。
        """
        after = self.technical()
        if after['bar3_end'] != before['bar3_end']:
            self.previous = dict(PreviousClose3=before['close3'], PreviousEMA8_3=before['ema8_3'], PreviousBar3End=before['bar3_end'],
                Previous3Known=all((before['exit_known'], before['spike_known'], after['exit_known'], after['spike_known'],
                    before['bar3_end'] > 0, after['bar3_end']-before['bar3_end'] == 180,
                    before['histogram3'] == after['previous_histogram3'], before['rsi3'] == after['previous_rsi3'])))
        if not after['exit_known'] or not after['spike_known'] or after['bar3_end'] == 0:
            self.previous['Previous3Known'] = False
        self.view['chart'] = self.chart()

    def numeric_advance(self, at: float) -> None:
        """
        機能: 両尺度を当時時計までだけ進める。
        引数: at(float)は原行又はtimer時計。
        返り値: None。
        """
        if at < self.frontier:
            raise ValueError('数値器時計後退')
        before = self.technical()
        self.f3.advance(at, self.s3)
        self.f15.advance(at, self.s15)
        self.frontier = at
        self.capture(before)

    def publish(self, at: float, observed: float) -> dict:
        """
        機能: 3分timerを公開し、5回に1回15分も公開する。
        引数: at/observed(float)は論理公開と観測上限。
        返り値: dictは独立したPublicationと私有比較mask。
        """
        self.numeric_advance(at)
        for name, form in [('three', self.form3)] + ([('fifteen', self.form15)] if at == self.next15 else []):
            bad = any(not s['valid'] for s in form)
            reason = '空足・価格の横ばい補完なし' if not form else '形成足に不良Last・数値履歴は未知' if bad else '公開済み形成足の入力出典'
            self.view[name] = dict(bar_end=at, available_at=at, observed_clock=observed, rows=len(form),
                data_known=bool(form) and not bad, has_last_source=bool(form), last_source=copy.deepcopy(form[-1]) if form else empty_stamp(), reason=reason)
            form.clear()
        changed15 = at == self.next15
        if changed15:
            self.next15 += 900
        self.next3 += 180
        self.view['at'], self.view['invalidated_at'] = at, 0
        return dict(at=at, three=True, fifteen=changed15, snapshot=copy.deepcopy(self.view), mask=self.numeric_mask())

    def advance(self, at: float, grids: list) -> dict:
        """
        機能: 同時計timer→gridの順で公開し、価格を足へ入れない。
        引数: at(float)、grids(list[float])は観測上限と未処理判断時刻。
        返り値: dictはPublications/Grids/After及び比較mask。
        """
        if self.sealed or not math.isfinite(at) or at < self.scene['start'] or self.view['has_observed_clock'] and at < self.view['observed_clock']:
            raise ValueError('bank時計後退/未開始/sealed')
        previous = self.last_grid
        for g in grids:
            if not math.isfinite(g) or not self.scene['start'] <= g <= at or g < self.view['at'] or self.last_raw and g <= self.last_raw['time'] or previous is not None and g <= previous:
                raise ValueError('未来/重複/原行後のgrid')
            previous = g
        out = dict(publications=[], grids=[], after=None, grid_masks=[])
        self.view['has_observed_clock'], self.view['observed_clock'] = True, at
        for g in grids:
            while self.next3 <= g:
                out['publications'].append(self.publish(self.next3, at))
            self.view['at'] = g
            out['grids'].append(copy.deepcopy(self.view))
            out['grid_masks'].append(self.numeric_mask())
            self.last_grid = g
        while self.next3 <= at:
            out['publications'].append(self.publish(self.next3, at))
        self.view['at'], out['after'] = at, None
        out['after'] = copy.deepcopy(self.view)
        return out

    def step(self, q: dict, grids: list) -> dict:
        """
        機能: timer/gridの後で当NK原行を形成足へ足す。
        引数: q(dict)、grids(list)はall受理NK連番と判断時刻。
        返り値: dictは公開結果。Last0も原行出典へ記録する。
        """
        if any(not math.isfinite(q[k]) for k in ('time', 'last', 'bid', 'ask')) or q['index'] < 0 or q['line'] <= 0:
            raise ValueError('原行有限性/識別不正')
        if self.last_raw and (q['index'] <= self.last_raw['index'] or q['line'] <= self.last_raw['line'] or q['time'] < self.last_raw['time']):
            raise ValueError('原行の順序不正')
        out = self.advance(q['time'], grids)
        self.numeric_advance(q['time'])
        before = self.technical()
        valid = q['valid'] and q['last'] > 0
        if valid:
            self.f3.add(q['last'])
            self.f15.add(q['last'])
        else:
            self.f3.bad = self.f15.bad = True
            self.s3.invalidate(True)
            self.s15.invalidate(True)
        self.capture(before)
        stamp = {k: q[k] for k in ('time', 'index', 'line', 'last')}
        stamp['valid'] = valid
        self.form3.append(copy.deepcopy(stamp))
        self.form15.append(copy.deepcopy(stamp))
        self.view['has_last_input'], self.view['last_input'] = True, stamp
        if not valid:
            self.view['invalidated_at'] = q['time']
        self.last_raw = copy.deepcopy(q)
        out['after'] = copy.deepcopy(self.view)
        return out

    def seal(self) -> tuple:
        """
        機能: 架空の場末timerを足さず数値種だけを確定する。
        引数: なし。
        返り値: tuple[dict,dict]は独立Seedと最終公開snapshot。
        """
        if self.sealed:
            raise ValueError('重複seal')
        self.sealed, self.view['sealed'] = True, True
        seed = dict(sealed=True, contract=self.scene['contract'], start=self.scene['start'],
                    observed=self.view['observed_clock'], numeric=copy.deepcopy((self.s3, self.s15)))
        return seed, copy.deepcopy(self.view)
