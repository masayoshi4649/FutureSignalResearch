"""元IFDの利確・損切の組合せを変え、先着した静的価格または期限の実気配で返済する。"""
from math import inf

POLICIES = {"D00":(True,True), "D01":(False,True), "D02":(True,False), "D03":(False,False)}
REASONS = {1:"静的利確",2:"静的損切",3:"期限決済",4:"場末決済"}


def prepare(index: object, scene: dict) -> dict:
    """
    機能：固定IFDの再生には追加の指標を蓄積しない。
    引数：index（PriceIndex）は価格索引、scene（dict）は場定義。
    返り値：dict。空の当時状態。
    """
    return {}


def decide(code: str, context: dict, index: object, entry: int, side: int,
           width: float, horizon: str, term: dict) -> dict:
    """
    機能：元の期限・欠測の範囲で、有効とした利確・損切の最初の到達を求める。
    引数：code・horizon（str）は設定と保有期限、context・term（dict）は当時状態と期限情報、
    index（PriceIndex）は板、entry・side（int）は新規位置と方向、width（float）は元のR。
    返り値：dict。観測した返済原行、理由、残している静的注文の距離。
    """
    take,stop = POLICIES[code]
    opened = index.rows["ask" if side==0 else "bid"][entry]
    target,loss = (width if take else inf),(width if stop else inf)
    lower,upper = (opened-loss,opened+target) if side==0 else (opened-target,opened+loss)
    end,status = term["exit"],term["status"]
    if take or stop:
        hit = index.first_outside(entry+1,term["touch_end"],lower,upper,side)
        if hit>=0:
            end = hit
            price = index.rows["bid" if side==0 else "ask"][hit]
            status = 1 if (price-opened)*(1 if side==0 else -1)>0 else 2
    return {"exit_index":int(end),"status":int(status),"reason":REASONS.get(status,"決済不明"),
            "initial_stop_points":width if stop else None,"target_points":width if take else None}
