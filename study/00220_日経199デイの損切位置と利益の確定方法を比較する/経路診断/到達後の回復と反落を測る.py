"""元の181建玉で、特定の逆行・順行に初めて達した後の正常実側気配と決済を測る。"""
import json
from pathlib import Path
import runpy

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
BASE = runpy.run_path(str(next((ROOT/"study").glob("00219_*/経路診断/元の保有経路を測る.py"))))
WORK = ROOT/"work/220経路診断"
LEVELS = (25, 50, 65, 75, 85, 90, 95)


def cash(rows: list, field: str) -> dict:
    """
    機能：指定した損益系列の利益・損失・費用後収支と黒赤の件数を合計する。
    引数：rows（list）は建玉の集合、field（str）は損益金額のキー。
    返り値：dict。件数、元単位の円額、黒赤件数。
    """
    values = [r[field] for r in rows]
    return {"件数":len(values), "黒字":sum(v>0 for v in values), "赤字":sum(v<0 for v in values),
            "利益":sum(max(v,0) for v in values), "損失":sum(max(-v,0) for v in values), "収支":sum(values)}


def first_or_end(condition: np.ndarray) -> int:
    """
    機能：条件が初めて真となる配列内の位置を特定する。
    引数：condition（np.ndarray）は観測順の真偽配列。
    返り値：int。到達しなければ配列長。
    """
    positions = np.flatnonzero(condition)
    return int(positions[0]) if positions.size else len(condition)


def observe(trade: dict, records: np.ndarray) -> list:
    """
    機能：初回到達を確定してから、その後の回復・反落、元の決済までの狭い床の効き方を記録する。
    引数：trade（dict）は元IFD一建玉、records（np.ndarray）は価格原行の索引。
    返り値：list。到達した水準ごとの建玉記録。
    """
    raw = records[trade["entry_index"]+1:trade["exit_index"]+1]
    q = raw[raw["normal"]==1]
    assert len(q) and q[-1]["source_line"]==trade["exit_line"]
    sign = 1 if trade["side"]==0 else -1
    marks = q["bid" if sign==1 else "ask"]
    moves = (marks-trade["entry_price"])*sign
    nets = (moves*100-1077).astype("int64")
    assert nets[-1]==trade["net"]
    # ----------------------------------------
    results = []
    for level in LEVELS:
        threshold = level*trade["width"]/100
        for label, passing in (("逆行",moves<=-threshold),("順行",moves>=threshold)):
            index = first_or_end(passing)
            if index==len(q):
                continue
            stop = len(q)-1
            trigger = None
            if label=="逆行":
                # 取得時点で置いた狭い静的損切注文を、初回タッチ時の清算側気配で見積もる。
                stop = index
            else:
                # 20pt床は起動の次の原行から判定する。元IFD・期限は同一原行なら先に成立。
                following = moves[index+1:-1]
                offset = first_or_end(following<=20)
                if offset<len(following):
                    trigger = index+1+offset
                    fill = int(np.searchsorted(q["time"],q["time"][trigger]+1))
                    stop = min(fill,len(q)-1)
            results.append({"場":trade["scene"],"新規時刻":BASE["stamp"](trade["entry_time"]),
                            "方向":"買" if sign==1 else "売","幅":int(trade["width"]),
                            "到達種":label,"水準":level,"到達時刻":BASE["stamp"](q["time"][index]),
                            "到達時評価":int(nets[index]),"元決済後収支":int(nets[-1]),
                            "元決済時刻":BASE["stamp"](q["time"][-1]),"元判定":trade["status"],
                            "元決済前に到達":index<len(q)-1,
                            "到達後の費用後正":bool(np.any(nets[index+1:]>0)),
                            "変更後収支":int(nets[stop]),"先に返済":stop<len(q)-1,
                            "保護条件発動":trigger is not None,"変更後決済時刻":BASE["stamp"](q["time"][stop])})
    return results


def stats(rows: list) -> dict:
    """
    機能：元の初回到達を分母に、元の最終結果・20pt保護床又は損切短縮による固定建玉の差を出す。
    引数：rows（list）は同一方向水準の初回到達記録。
    返り値：dict。原順の回復件数、元と変更後の損益、勝敗反転、損益差。
    """
    old = cash(rows,"元決済後収支")
    new = cash(rows,"変更後収支")
    return {"到達":len(rows),"決済前に到達":sum(r["元決済前に到達"] for r in rows),
            "到達後に費用後正":sum(r["到達後の費用後正"] for r in rows),
            "元利確で決済":sum(r["元判定"]==1 for r in rows),"元結果":old,"変更後":new,
            "元より前に返済":sum(r["先に返済"] for r in rows),
            "赤字を黒字化":sum(r["元決済後収支"]<0<r["変更後収支"] for r in rows),
            "黒字を赤字化":sum(r["変更後収支"]<0<r["元決済後収支"] for r in rows),
            "黒字建玉で利益縮小":sum(0<r["元決済後収支"] and r["変更後収支"]<r["元決済後収支"] for r in rows),
            "差":new["収支"]-old["収支"],"損失減":old["損失"]-new["損失"]}


def main() -> None:
    """
    機能：元181件で各水準の到達後を集計し、固定入口のW31とW36の損切幅による差を照合する。
    引数：なし。219の元比較元帳と原板索引を参照する。
    返り値：None。具体例用の初回到達元帳と結果JSONを作業領域に作成する。
    """
    comparison = json.loads((ROOT/"work/219逆行/比較元帳.json").read_bytes())["入口固定"]
    source = comparison["IFD"]
    scenes = sorted({t["scene"] for t in source})
    assert len(source)==181 and len(scenes)==45 and sum(t["net"] for t in source)==1020063
    archives = BASE["archives"]()
    rows = []
    for scene in scenes:
        records = BASE["load_records"](*archives[scene])
        for trade in (t for t in source if t["scene"]==scene):
            rows.extend(observe(trade,records))
    groups = {"全体":rows, "買い":[r for r in rows if r["方向"]=="買"], "売り":[r for r in rows if r["方向"]=="売"],
              "前24日":[r for r in rows if r["場"] in scenes[:24]], "後21日":[r for r in rows if r["場"] in scenes[24:]]}
    report = {group:{kind:{level:stats([r for r in subset if r["到達種"]==kind and r["水準"]==level])
                          for level in LEVELS} for kind in ("逆行","順行")} for group,subset in groups.items()}
    # ----------------------------------------
    wider = []
    for old, w36, w31 in zip(source,comparison["W36"],comparison["W31"],strict=True):
        assert all(old[k]==w31[k]==w36[k] for k in ("entry_line","scene","side","entry_price"))
        if w31["initial_stop_multiple"]>1:
            wider.append({"場":old["scene"],"新規時刻":BASE["stamp"](old["entry_time"]),"元R":old["width"],
                          "方向":"買" if old["side"]==0 else "売","W31":w31["net"],"W36":w36["net"],
                          "W31決済":w31["exit_reason"],"W36決済":w36["exit_reason"]})
        else:
            assert (w31["exit_line"],w31["net"])==(w36["exit_line"],w36["net"])
    report["同一保護で損切1.10Rを許可した建玉"] = wider
    WORK.mkdir(parents=True,exist_ok=True)
    for name,payload in (("初回到達",rows),("集計",report)):
        (WORK/(name+".json")).write_text(json.dumps(payload,ensure_ascii=False,allow_nan=False),encoding="utf8")


if __name__=="__main__":
    main()
