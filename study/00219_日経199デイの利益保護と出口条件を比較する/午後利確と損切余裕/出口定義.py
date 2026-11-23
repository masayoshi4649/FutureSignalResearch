"""午後の利確、損切り幅の余裕、その組合せに追加する利益追尾を検証する。"""
import numpy as np

POLICIES = {"C01":"午後利確と1.10R損切", "C02":"同条件に利確幅75%から追尾", "C03":"同条件に利確幅90%から追尾",
            "C04":"75%追尾・初期損切上限400pt", "C05":"90%追尾・初期損切上限400pt","C06":"上限400pt・狭い追尾"}


def prepare(index, scene: dict) -> dict:
    """
    機能：午後を判定するため場の開始時刻を保存する。
    引数：indexは原板索引、scene（dict）は日中の場定義。
    返り値：dict。日本時間08:45のUnix秒。
    """
    return {"start":scene["start"]}


def decide(code: str, context: dict, index, entry: int, side: int, width: float, horizon: str, term: dict) -> dict:
    """
    機能：条件ごとの常設IFD・必須追尾・期限のうち最初に成立した実側返済を選ぶ。
    引数：code（str）は方策、context・term（dict）は時刻と期限、indexは価格索引、
    entry・side（int）は取得行と方向、width（float）は元幅、horizon（str）は元来の期限。
    返り値：dict。決済行と理由、事前の利確・損切幅、保護の起動・発動記録。
    """
    if code not in POLICIES:
        raise ValueError(code)
    sign = 1 if side==0 else -1
    price = float(index.rows["ask" if side==0 else "bid"][entry])
    mark = index.rows["bid" if side==0 else "ask"]
    target = (.90 if index.times[entry]-context["start"]>=225*60 else 1)*width
    risk = 1.10*width if code in ("C01","C02","C03") else min(1.10*width,400)
    lower, upper = sorted((price+sign*target,price-sign*risk))
    hit = index.first_outside(entry+1,term["touch_end"],lower,upper,side)
    end = hit if hit>=0 else term["exit"]
    status = (1 if sign*(mark[hit]-price)>0 else 2) if hit>=0 else term["status"]
    result = {"exit_index":int(end),"status":int(status),
              "reason":{1:"静的利確",2:"静的損切",3:"期限決済",4:"場末決済"}.get(status,"決済不明"),
              "target_points":target,"initial_risk_points":risk,"activated":False,"activation_time":None,
              "trigger_time":None,"floor_points":None}
    if code=="C01":
        return result
    # ----------------------------------------
    stop = min(term["touch_end"],end) if end>=0 else term["touch_end"]
    normal = index.normal
    ids = normal[np.searchsorted(normal,entry+1):np.searchsorted(normal,stop)]
    if not len(ids):
        return result
    move = sign*(mark[ids]-price)
    peak = np.maximum.accumulate(move)
    active = peak>=target*(.75 if code in ("C02","C04") else .90)
    if not np.any(active):
        return result
    result.update(activated=True,activation_time=float(index.times[ids[active.argmax()]]))
    floors = np.maximum(20,peak-(.40 if code=="C06" else .65)*width)
    touch = (move<=floors) & np.r_[False,active[:-1]]
    result["floor_points"] = float(floors[-1])
    if touch.any():
        event = int(touch.argmax())
        trigger = float(index.times[ids[event]])
        result.update(trigger_time=trigger,floor_points=float(floors[event]))
        fill = np.searchsorted(index.times[ids],trigger+1)
        if fill<len(ids):
            result.update(exit_index=int(ids[fill]),status=5,reason="利益保護")
    return result
