"""反対の公表時刻・方向だけを入れ替え、元のR02と同じ価格・約定条件で清算する。"""
from pathlib import Path
import runpy

import numpy as np

HERE = Path(__file__).resolve().parent
ORIGINAL = runpy.run_path(str(next(HERE.parent.glob("00223_*/反対の入口シグナル/出口条件.py"))))
POLICIES = ("X1","X2","X3","X4","X5")
LABELS = {"X1":"反対二回","X2":"同方向二回","X3":"方向を問わず二回","X4":"三分遅延","X5":"広い追尾のみ"}


def prepare_signals(index: object, scene: dict, signals: dict) -> dict:
    """
    機能：当時の元の主シグナルと、それぞれを3分遅く公表する場合の最初の原行を用意する。
    引数：index（PriceIndex）は場の時計、scene・signals（dict）は場の時間と入口側の当時情報。
    返り値：dict。元の時系列と遅延側の公表時刻・行。場末を超える行の索引は配列の終端になる。
    """
    context = ORIGINAL["prepare_signals"](index,scene,signals)
    delayed = context["signal_times"]+180
    rows = index.times.searchsorted(delayed,side="left")
    within = rows<len(index.times)
    assert np.all(index.times[rows[within]]>=delayed[within])
    earlier = within & (rows>0)
    assert np.all(index.times[rows[earlier]-1]<delayed[earlier])
    return dict(context,delayed_times=delayed,delayed_rows=rows)


def decide(code: str, context: dict, index: object, entry: int, side: int, width: float, horizon: str, term: dict) -> dict:
    """
    機能：主シグナルの方向と公表時点だけを入れ替えた入力を、元のR02価格注文・追尾・執行へ渡す。
    引数：code・horizon（str）は条件・場末の種別、context・term（dict）は主信号と観測終端、
    index（PriceIndex）は板、entry・side（int）は取得原行と売買、width（float）は元注文幅。
    返り値：dict。元の固定価格注文・利益保護または場末による決済原行と実現収支用の情報。
    """
    if code not in POLICIES:
        raise ValueError("未定義の候補 "+code)
    rule = "R00" if code=="X5" else "R02"
    signs = context["signal_sides"]
    if code=="X2":
        context = dict(context,signal_sides=-signs)
    elif code=="X3":
        # 元の反対2回の判定に、どの実方向の有効信号も通す。
        required = -1 if side==0 else 1
        context = dict(context,signal_sides=np.full_like(signs,required))
    elif code=="X4":
        # 建玉前に発生し取得後に届くものを除く。新しい公表時刻を経過するまで検出できない。
        start = context["signal_rows"].searchsorted(entry,side="right")
        context = dict(context,signal_rows=context["delayed_rows"][start:],
                       signal_times=context["delayed_times"][start:],signal_sides=signs[start:])
    result = ORIGINAL["decide"](rule,context,index,entry,side,width,horizon,term)
    # 実注文・返済から独立に、広い追尾と区別した追加保護の該当件数を数える。
    first = None
    if code!="X5":
        stop = result["exit_index"] if result["exit_index"]>=0 else term["touch_end"]
        at = result.get("trigger_index")
        if at is not None and at>=0:
            stop = min(stop,at+1)
        lo,hi = index.normal.searchsorted([entry+1,stop])
        observed = index.normal[lo:hi]
        first = first_narrow(context,index,entry,observed,side,width)
        if first is not None:
            assert result["activated"] and result["activation_index"]<=first
    return dict(result,narrow_source_line=int(index.rows["source_line"][first]) if first is not None else None)


def first_narrow(context: dict, index: object, entry: int, observed: np.ndarray, side: int, width: float) -> int | None:
    """
    機能：最初の発動・実返済で観測を止め、狭い追尾だけの初回成立原行を集計用に調べ直す。
    引数：context（dict）は各候補に調整した過去の信号、index（PriceIndex）は気配、entry・side（int）は
    建玉原行・実側、observed（np.ndarray）は実観測できた原行、width（float）は初期幅。
    返り値：intまたはNone。該当する最初の原行。実注文や次の新規には使わない。
    """
    rows = context["signal_rows"]
    if len(observed)==0 or len(rows)<2:
        return None
    positions = rows.searchsorted(observed,side="right")-1
    two = positions>=1
    last = positions.clip(0)
    prior = (positions-1).clip(0)
    times = index.times[observed]
    signs = context["signal_sides"]
    targets = context["signal_times"]
    side_sign = 1 if side==0 else -1
    two &= (rows[prior]>entry) & (signs[prior]==-side_sign) & (signs[last]==-side_sign)
    two &= (times-targets[last]<=90) & (times-targets[prior]<=180)
    price = index.rows["ask" if side==0 else "bid"][entry]
    change = side_sign*(index.rows["bid" if side==0 else "ask"][observed]-price)
    meets = np.flatnonzero(two & (change>=20) & (np.maximum.accumulate(change)>=.25*width))
    return int(observed[meets[0]]) if len(meets) else None
