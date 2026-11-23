"""原行順だけで更新する201の純板特徴。価格方向と実際の売買側を分離する。"""
from collections import deque
import math

NAMES = ('QI1', 'QI3', 'QI10', 'OFI16', 'OFI64', 'BLOCK4_OFI', 'BLOCK4_MID_CHANGE')


# ----------------------------------------
def finite(value):
    """
    機能: 真偽値を除いた有限数値を判定する。
    引数: value(any)は入力値。
    返り値: boolは有限数値。
    """
    return type(value) in (int, float) and math.isfinite(value)


# ----------------------------------------
def missing(reason, line):
    """
    機能: 未知を零と区別する共通形式を作る。
    引数: reason(str)は理由、line(int)は判断原行。
    返り値: dictは値nullと既知falseを持つ記録。
    """
    return dict(value=None, known=False, reason=reason, start_line=0, end_line=0,
                available_line=line, events=0, clock_span=None, max_clock_gap=None)


# ----------------------------------------
def known(value, start, end, available, events, span, gap):
    """
    機能: 過去の入力端と公表原行を分けて既知値を作る。
    引数: value(float)、start/end/available/events(int)、span/gap(float)は値と原順出典。
    返り値: dictは既知の特徴。全ての入力端が公表原行以下であることを検査する。
    """
    assert finite(value) and 0 < start <= end <= available
    return dict(value=float(value), known=True, reason='', start_line=start, end_line=end,
                available_line=available, events=events, clock_span=float(span), max_clock_gap=float(gap))


# ----------------------------------------
def ofi(previous, current):
    """
    機能: 最良板の符号付き差分を前後の両側総深さの平均で正規化する。
    引数: previous/current(dict)はb/a/bq/aqを持つ正常板。
    返り値: floatは買い側正の差分。数量の共通倍率に不変。
    """
    p, q = previous, current
    e = (q['bq'] if q['b'] >= p['b'] else 0) - (p['bq'] if q['b'] <= p['b'] else 0)
    e -= (q['aq'] if q['a'] <= p['a'] else 0) - (p['aq'] if q['a'] >= p['a'] else 0)
    depth = (p['bq'] + p['aq'] + q['bq'] + q['aq']) / 2
    return e / depth


# ----------------------------------------
class State:
    """場ごとの原順状態。時計で並べ替えず、現ブロックを未来まで閉じない。"""

    def __init__(self, start, end):
        """
        機能: 一場の空の純履歴を作る。
        引数: start/end(float)は原板の価格時計による場端。
        返り値: None。
        """
        self.start, self.end = start, end
        self.highwater = None
        self.contract = None
        self.last_line = 0
        self.reset('履歴不足')

    def reset(self, reason):
        """
        機能: 不連続後の特徴履歴を破棄する。価格時計の高水位は保持する。
        引数: reason(str)は今回の不連続理由。
        返り値: None。
        """
        self.previous, self.block = None, None
        self.event_base, self.pending_gap = None, 0.0
        self.events = deque(maxlen=64)
        self.completed = deque(maxlen=4)
        self.reason = reason

    def add(self, q):
        """
        機能: 一原行だけを追加し、旧ブロックの公表と新イベントを原順に処理する。
        引数: q(dict)はline/time/contract/last/b/a/bq/aq。
        返り値: None。未知行は履歴を切り、後退後は高水位以上で復帰する。
        """
        assert q['line'] > self.last_line
        self.last_line = q['line']
        t = q['time']
        reason = ''
        if not finite(t):
            reason = '価格時計欠測'
        elif not self.start <= t < self.end:
            reason = '価格時計場外'
        elif self.highwater is not None and t < self.highwater:
            reason = '価格時計後退から未復帰'
        elif not all(finite(q[k]) and q[k] > 0 for k in ('last', 'b', 'a', 'bq', 'aq')):
            reason = '価格又は最良量不正'
        elif q['b'] >= q['a']:
            reason = '不正常BBO'
        elif not isinstance(q['contract'], str) or not q['contract']:
            reason = '限月不明'
        if finite(t) and self.start <= t < self.end:
            self.highwater = t if self.highwater is None else max(t, self.highwater)
        if reason:
            self.reset(reason)
            return
        if self.contract is not None and self.contract != q['contract']:
            self.reset('限月変更')
        self.contract = q['contract']
        p = self.previous
        mid = (q['b'] + q['a']) / 2
        if self.block is None or t > self.block['label']:
            if self.block is not None:
                self.block['available'] = q['line']
                self.completed.append(self.block)
            base = p if p is not None else q
            self.block = dict(label=t, start=base['line'], end=q['line'], time0=base['time'],
                              base_mid=(base['b'] + base['a']) / 2, last_mid=mid,
                              total=0.0, count=0, gap=0.0, available=0)
        changed = p is not None and any(q[k] != p[k] for k in ('b', 'a', 'bq', 'aq'))
        gap = t - p['time'] if p is not None else 0
        self.pending_gap = max(self.pending_gap, gap)
        if self.event_base is None:
            self.event_base = q.copy()
        if changed:
            value = ofi(p, q)
            assert finite(value)
            self.events.append(dict(value=value, start=self.event_base['line'], end=q['line'],
                                    time0=self.event_base['time'], time=t, gap=self.pending_gap))
            self.event_base, self.pending_gap = q.copy(), 0.0
            self.block['total'] += value
            self.block['count'] += 1
        self.block.update(end=q['line'], last_mid=mid, gap=max(self.block['gap'], gap))
        self.previous = q.copy()
        self.reason = ''

    def snapshot(self, q, levels):
        """
        機能: 現在原行までに公表済みの7列を取り出す。
        引数: q(dict)は最後に追加した原行、levels(tuple[list,list])は買い/売り10段。
        返り値: dict[str,dict]は市場方向の純特徴。未知とその理由を全件保持する。
        """
        line = q['line']
        assert line == self.last_line
        result = {name: missing(self.reason or '履歴不足', line) for name in NAMES}
        if self.previous is None:
            return result
        for depth in (1, 3, 10):
            buy, sell = levels[0][:depth], levels[1][:depth]
            valid = len(buy) == len(sell) == depth and all(finite(p) and p > 0 and finite(v) and v > 0 for p, v in buy + sell)
            valid = valid and all(buy[i][0] > buy[i+1][0] for i in range(depth-1)) and all(sell[i][0] < sell[i+1][0] for i in range(depth-1))
            if valid:
                bsum, asum = sum(v for _, v in buy), sum(v for _, v in sell)
                result[f'QI{depth}'] = known((bsum-asum)/(bsum+asum), line, line, line, 1, 0, 0)
            else:
                result[f'QI{depth}'] = missing('段価格順又は数量不正', line)
        events = list(self.events)
        for size in (16, 64):
            selected = events[-size:]
            if len(selected) == size:
                a, b = selected[0], selected[-1]
                result[f'OFI{size}'] = known(sum(x['value'] for x in selected)/size,
                    a['start'], b['end'], line, size, b['time']-a['time0'], max(x['gap'] for x in selected))
            else:
                result[f'OFI{size}'] = missing(f'L1変化{size}回不足', line)
        blocks = list(self.completed)
        if len(blocks) == 4:
            a, b = blocks[0], blocks[-1]
            count = sum(x['count'] for x in blocks)
            meta = (a['start'], b['end'], b['available'], count, b['label']-a['time0'], max(x['gap'] for x in blocks))
            result['BLOCK4_MID_CHANGE'] = known(b['last_mid']-a['base_mid'], *meta)
            result['BLOCK4_OFI'] = known(sum(x['total'] for x in blocks)/count, *meta) if count else missing('完了4ブロック内L1変化なし', line)
        else:
            result['BLOCK4_OFI'] = missing('完了4ブロック不足', line)
            result['BLOCK4_MID_CHANGE'] = missing('完了4ブロック不足', line)
        for value in result.values():
            assert value['end_line'] <= value['available_line'] <= line
        return result
