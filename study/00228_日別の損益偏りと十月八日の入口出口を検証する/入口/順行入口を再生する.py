"""公表済みの短期・中期情報で分岐0の見送りと実側反転を比較し、予約から両出口を再生する。"""
from functools import partial
import json
from pathlib import Path
import runpy

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
STUDY = ROOT/"study"
WORK = ROOT/"work/228入口"
CONTROL = runpy.run_path(str(next(STUDY.glob("00224_*/再エントリーを再生する.py"))))
ENGINE = CONTROL["ENGINE"]
SOURCE = CONTROL["SOURCE"]
BASE = CONTROL["BASE"]
RC = runpy.run_path(str(next(STUDY.glob("00223_*/反対の入口シグナル/出口条件.py"))))
CODES = ("E0","E1","E2","E3","E4")


def vetoes(features: np.ndarray, columns: list) -> tuple:
    """
    機能：当時の買いまたは売りに対する完成足の価格・勢い・中期方向と急変を組み合わせる。
    引数：features（np.ndarray）は一方の売買側の特徴、columns（list[str]）は各列名。
    返り値：tuple[np.ndarray,...]。E0からE4の各行の条件成立。
    """
    x = dict(zip(columns,features.T,strict=True))
    short = ((x["m5_ema8_delta_to_side"]<0) & (x["m5_hist_delta_to_side"]<0)
             & (x["m5_price_ema8_atr_to_side"]<0))
    medium = (x["m15_ema21_delta_to_side"]<0) & (x["m15_di_difference_to_side"]<0)
    shock = (x["m5_tr_previous_atr_ratio"]>=2) & (x["m5_close_position_to_side"]<=.25)
    strong = short & (medium | shock)
    return np.zeros(len(features),dtype=bool),short,short & medium,strong,strong


def modified(stream: tuple, buy: np.ndarray, sell: np.ndarray, reverse: bool) -> tuple:
    """
    機能：実売買側の条件が成立した分岐0の主入口だけを抑止または反転し、元の予約時計を保つ。
    引数：stream（tuple）は全要求、buy・sell（np.ndarray）は原行別の見直し条件、reverse（bool）は反転。
    返り値：tuple。新規予約に渡す要求、変えた元の判断行のマスク。
    """
    keys,captures,arrays = stream
    core = arrays["core"]
    hit = (arrays["branches"]==0) & (arrays["mw"]>0) & (((core==1) & buy) | ((core==-1) & sell))
    new = dict(arrays,core=np.where(hit,-core if reverse else 0,core),
               branches=arrays["branches"] if reverse else np.where(hit,-1,arrays["branches"]),
               technical=np.where(hit,0,arrays["technical"]),
               added=arrays["added"] if reverse else arrays["added"] & ~hit)
    return (keys,captures,new),hit


def close_rc(dynamic: object, code: str, entry: int, side: int, width: float, horizon: str) -> dict:
    """
    機能：保有時間上限なしのRCを実際の売買側で計算し、元入口の属性を保存する。
    引数：dynamic（callable）は当日出口、code・horizon（str）は出口と旧属性、entry・side（int）は取得・側、
    width（float）は静的片幅。返り値：dict。実際の返済と発動記録。
    """
    t = dynamic(code,entry,side,width,"SESSION")
    assert t["status"]!=3
    return dict(t,horizon=horizon,exit_horizon="SESSION")


def exit_options(observations: dict, scene: dict, index: object) -> tuple:
    """
    機能：変更前の通知を読むRC出口・単純IFD出口・再開時計を作る。
    引数：observations・scene（dict）は変更前全要求と場、index（PriceIndex）は板。
    返り値：tuple。RC、IFD、再開時計の各計算関数。
    """
    original_signals = {k:observations[k] for k in ("index","line","time","core","branches","mw","fw")}
    context = RC["prepare_signals"](index,scene,original_signals)
    rc = ENGINE["exits"](index,scene,dict(RC,prepare=lambda _index,_scene:context))
    static = ENGINE["exits"](index,scene,BASE["POLICY"]["STATIC"])
    ifd = BASE["POLICY"]["ORIGINAL"]["extend"](static)

    def barrier(entry: int, side: int, width: float) -> dict:
        """
        機能：保護決済後に元の静的注文相当まで予約を待つための価格到達時計を得る。
        引数：entry・side（int）は取得原行と側、width（float）は片幅。返り値：dict。静的注文の到達。
        """
        return static("D00",entry,side,width,"SESSION")

    return rc,ifd,barrier


def replay_pair(allowed: tuple, scene: dict, index: object, options: tuple) -> tuple:
    """
    機能：同じ予約・保有限度でRCと単純IFDを再生して取得の完全一致を検査する。
    引数：allowed（tuple）は開始待機済み要求、scene（dict）は当場、indexは板、options（tuple）は出口関数。
    返り値：tuple。RCと単純IFDそれぞれの建玉元帳。
    """
    rc,ifd,barrier = options
    rc_book,_ = CONTROL["account"](allowed,scene,index,"R02",partial(close_rc,rc),barrier,"C")
    ifd_book,_ = ENGINE["replay"](allowed,scene,"D04",ifd)
    same = ("scene","side","width","request_time","request_line","entry_time","entry_price","entry_line")
    assert all(all(a[f]==b[f] for f in same) for a,b in zip(rc_book,ifd_book,strict=True))
    return rc_book,ifd_book


def day(arrays: dict, number: int, scene: dict, index: object, values: dict, columns: list) -> tuple:
    """
    機能：元の反対シグナルで出口を固定し、全入口変更×2出口×2開始待機を買売共用1枠で再生する。
    引数：arrays・scene・values（dict）は全要求、場、当時特徴、number（int）は場番号、
    index（PriceIndex）は板、columns（list）は特徴名。返り値：tuple。各条件の建玉と見送り判断行。
    """
    stream = ENGINE["orders"](arrays,number,scene,index)
    active = (arrays["scene"]==number) & (arrays["time"]<scene["end"]-960)
    observations = stream[2]
    assert np.array_equal(observations["line"],arrays["line"][active])
    flags = [vetoes(values[k][active],columns) for k in ("buy","sell")]
    options = exit_options(observations,scene,index)
    # ----------------------------------------
    books,hits = {},{}
    for pos,code in enumerate(CODES):
        changed,hit = modified(stream,flags[0][pos],flags[1][pos],code=="E4")
        hits[code] = [int(n) for n in observations["line"][hit]]
        for wait in (20,30):
            allowed = BASE["after_open"](changed,scene["start"]+60*wait)
            rc_book,ifd_book = replay_pair(allowed,scene,index,options)
            books[f"{code}RC{wait}"] = rc_book
            books[f"{code}I{wait}"] = ifd_book
    return books,hits


def main() -> None:
    """
    機能：既使用45デイを原資料から再生し、単純IFD・RCの固定口座との全項目一致を確認する。
    引数：なし。入力は試行222・224と同じ。返り値：None。候補元帳と条件成立行を作業領域に保存する。
    """
    base = json.loads((ROOT/"work/222境界照合/口座元帳.json").read_bytes())
    original = json.loads((ROOT/"work/224反対追試/口座元帳.json").read_bytes())
    dates = base["対象場"]
    assert dates==original["対象場"]
    books,hits = {},{}
    for folder,archive,member,manifest in SOURCE["parts"]():
        scenes,arrays,values,columns,_ = SOURCE["inputs"](folder,archive,member)
        pointers = {r["session"]:r for r in SOURCE["read"](manifest)["scenes"]}
        for i,scene in enumerate(scenes):
            name = scene["session"]
            if name in hits or name not in dates:
                continue
            index = ENGINE["FINANCE"]["load_scene"](manifest.parent,pointers[name])
            result,hits[name] = day(arrays,i,scene,index,values,columns)
            for code,rows in result.items():
                books.setdefault(code,[]).extend(rows)
    assert set(hits)==set(dates)
    for w in ("20","30"):
        assert books["E0I"+w]==base["口座再生"]["I"+w]
        assert books["E0RC"+w]==original["口座再生"]["RC"+w]
    WORK.mkdir(parents=True,exist_ok=True)
    for name,data in (("口座元帳",{"対象場":dates,"口座再生":books}),("当時の変更判断原行",hits)):
        (WORK/(name+".json")).write_text(json.dumps(data,ensure_ascii=False,allow_nan=False),encoding="utf8")


if __name__=="__main__":
    main()
