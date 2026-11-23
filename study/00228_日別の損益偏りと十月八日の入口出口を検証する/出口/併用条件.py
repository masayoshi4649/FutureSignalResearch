"""逆向きの背景と小値幅を別々に監視し、重複する返済を一度だけ扱う。"""
from functools import partial
from pathlib import Path
import runpy

HERE = Path(__file__).resolve().parent
K = runpy.run_path(str(HERE/"出口条件.py"))
V = runpy.run_path(str(HERE/"小値幅で確認する.py"))
POLICIES = ("X1","X2","V06","V07")


def prepare_signals(index: object, scene: dict, signals: dict) -> dict:
    """
    機能：取得時の逆向き背景・小値幅判定を同じ当日の清算側気配に揃える。
    引数：index（PriceIndex）は原板、scene・signals（dict）は場と主シグナル。
    返り値：dict。RCと追加候補の日別入力。
    """
    context = K["prepare_signals"](index,scene,signals)
    context["prior_range"] = V["prepare_signals"](index,scene,signals)["prior_range"]
    return context


def range_signal(context, index, ids, entry, side, width, move, peak, *, ratio):
    """
    機能：V02の入口の値幅境界だけを変える。
    引数：context（dict）は値幅、index（PriceIndex）は板、ids・move・peak（np.ndarray）は行と順行値、
    entry・side（int）は取得と方向、width・ratio（float）は元幅と値幅閾値。
    返り値：np.ndarray。事前に指定した値幅倍率に収まる建玉が半分の利幅に到達したか。
    """
    return (context["prior_range"][context["bar"][entry]]<=ratio*width) & (move>=.50*width)


def decide(code: str, context: dict, index: object, entry: int, side: int, width: float, horizon: str, term: dict) -> dict:
    """
    機能：二つの出口モニターの先着決済を、元の価格注文と共に一建玉一回だけ返す。
    引数：code・horizon（str）は候補と期限、context・term（dict）は当時状態と終端、
    index（PriceIndex）は原板、entry・side（int）は取得と方向、width（float）は元注文幅。
    返り値：dict。先着した決済・要求と、すでに起動済みの追尾の時刻。
    """
    args = (context,index,entry,side,width,horizon,term)
    if code in ("V06","V07"):
        ratio = .40 if code=="V06" else .60
        return K["PREVIOUS"]["COMMON"]["overlay"](*args,partial(range_signal,ratio=ratio),"即時",min_peak=.50)
    assert code in ("X1","X2")
    reverse = "K07" if code=="X1" else "K08"
    orders = [(reverse,K["decide"](reverse,*args)),("V02",V["decide"]("V02",*args))]
    live = [(name,o) for name,o in orders if o["exit_index"]>=0]
    name,chosen = min(live,key=lambda x:x[1]["exit_index"]) if live else orders[0]
    boundary = chosen["trigger_index"] if chosen["trigger_index"]>=0 else chosen["exit_index"]
    arms = [o["activation_index"] for _,o in orders if 0<=o["activation_index"]<=boundary]
    result = dict(chosen,winning_policy=name if chosen["extra_fill"] else "RC")
    if arms:
        arm = min(arms)
        result.update(activated=True,activation_index=arm,activation_time=float(index.times[arm]))
    return result
