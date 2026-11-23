"""量の異常を利用できた分数・判断可能な建玉と、条件ごとの利確維持・金額を集計する。"""
from collections import Counter
import json
from pathlib import Path
import runpy

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
STUDIES = ROOT/"study"
FIRST = runpy.run_path(str(HERE/"出口条件.py"))
BASE = runpy.run_path(str(next(STUDIES.glob("00222_*/建玉制限を再生する.py"))))


def coverage(days: list, reference: dict) -> tuple:
    """
    機能：当時の各正常原行で直近・時刻別基準が揃った分数と、価格の前提を満たす元建玉を数える。
    引数：days（list[str]）は対象日、reference（dict）は開始待機別のRC元帳。
    返り値：tuple[dict,dict,dict]。日別の可用性、費用後の結果と元利確の母数、入力指紋。
    """
    source,engine = BASE["SOURCE"],BASE["ENGINE"]
    by_day,members,inputs = {},{wait:Counter() for wait in (20,30)},{}
    for folder,_,_,manifest in source["parts"]():
        scenes = source["read"](folder/"固定取得入力.json.gz")["scenes"]
        meta = {r["session"]:r for r in source["read"](manifest)["scenes"]}
        for scene in scenes:
            day = scene["session"]
            if day in by_day or day not in days:
                continue
            cut = scene["end"]-900
            index = engine["FINANCE"]["load_scene"](manifest.parent,meta[day])
            f = FIRST["volume_flags"](index,day,scene["contract"],str(folder),cut)
            by_day[day],inputs[day] = {},f["csv_sha"]
            for wait in (20,30):
                opened = scene["start"]+wait*60
                active = (f["stamp"]>=opened) & (index.times<cut)
                joint = f["local_known"] & f["season_known"]
                by_day[day][wait] = {"対象分":(cut-opened)//60,"有効":int(active.sum()),
                    "局所基準":int((active & f["local_known"]).sum()),"時分基準":int((active & f["season_known"]).sum()),
                    "両基準":int((active & joint).sum()),"両方で低下":int((active & f["local"] & f["season"]).sum())}
                # ----------------------------------------
                for r in reference["RC"+str(wait)]:
                    if day!=r["scene"]:
                        continue
                    touch = r["trigger_index"]
                    end = min(r["exit_index"],touch) if touch>=0 else r["exit_index"]
                    start,stop = index.normal.searchsorted([r["entry_index"]+1,end])
                    ids = index.normal[start:stop]
                    if not len(ids):
                        continue
                    px = index.rows["bid" if r["side"]==0 else "ask"][ids]
                    move = (px-r["entry_price"])*(1 if r["side"]==0 else -1)
                    eligible = (f["stamp"][ids]>=r["entry_time"]) & joint[ids] & (move>=.25*r["width"])
                    if np.any(eligible & (np.maximum.accumulate(move)>=.5*r["width"])):
                        members[wait]["建玉"] += 1
                        members[wait]["元価格利確"] += r["status"]==1
                        members[wait]["元黒字"] += r["net"]>0
    assert set(by_day)==set(days)
    return by_day,members,inputs


def main() -> None:
    """
    機能：同じ133件の元取得で費用後損益を再計算し、元利確を変更した件数や期間差・可用性を出力する。
    引数：なし。試行227の初回・追試と試行224のRC口座を読む。
    返り値：None。診断表と出来高確認・期間別計数を保存する。
    """
    ref = json.loads((ROOT/"work/224反対追試/口座元帳.json").read_bytes())
    days,reference = ref["対象場"],ref["口座再生"]
    by_day,members,inputs = coverage(days,reference)
    records = {}
    for group in ("227出来高","227量回復"):
        records.update(json.loads((ROOT/"work"/group/"口座元帳.json").read_bytes())["口座再生"])
    report = ["# 出来高の可用性と実現損益","",
              "日経225mini換算1枚、9月21日〜11月20日の既使用45デイ。各金額は円、差は同じ開始条件のRC比。"
              "元利確は、RCの元の1R指値が先に約定した件数。","",
              "|待機|対象分|直近3本基準|過去同時分基準|両基準|うち両方で60%以下|両基準で価格前提に達した元建玉|うち元価格利確／元黒字|",
              "|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for w in (20,30):
        counts = [sum(by_day[d][w][field] for d in days) for field in ("対象分","局所基準","時分基準","両基準","両方で低下")]
        m = members[w]
        cells = [str(w),*[f"{int(v):,}" for v in counts],str(m["建玉"]),f'{m["元価格利確"]}／{m["元黒字"]}']
        report.append("|"+"|".join(cells)+"|")
    report += ["","価格前提は保有中に0.50R順行、かつ当時0.25R以上の順行があり、当該建玉の取得後に始まった完成足を観測したこと。"
               "この行の母数には先行薄商い・価格突破の条件を課していない。最初の5デイは同時分基準の支持が不足する。",
               "","|待機|条件|印成立／追加約定|総利益|総損失|収支|損失差|収支差|元利確早退／元利確|元利確群の収支差|前24日差|後21日差|改善／悪化日|",
               "|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for key,book in sorted(records.items(),key=lambda it:(it[0][-2:],it[0][:3])):
        wait,id_ = int(key[-2:]),key[:3]
        original = reference["RC"+str(wait)]
        deltas,daydiff = [],Counter()
        missed,targets,target_diff = 0,0,0
        for t,o in zip(book,original,strict=True):
            assert (t["scene"],t["entry_line"],t["side"])==(o["scene"],o["entry_line"],o["side"])
            delta = t["net"]-o["net"]
            deltas.append(delta)
            daydiff[t["scene"]] += delta
            if o["status"]==1:
                targets += 1
                missed += t["extra_fill"]
                target_diff += delta
        dif = sum(deltas)
        pre = sum(daydiff[d] for d in days[:24])
        gross = sum(max(0,t["net"]) for t in book)
        loss = sum(max(0,-t["net"]) for t in book)
        diff_loss = loss-sum(max(0,-t["net"]) for t in original)
        signals = sum(t["extra_signal"]>=0 for t in book)
        fills = sum(t["extra_fill"] for t in book)
        money = [f"{v:,.0f}" for v in (gross,loss,gross-loss)]
        ends = [f"{v:+,.0f}" for v in (target_diff,pre,dif-pre)]
        sign = f"{sum(v>0 for v in daydiff.values())}／{sum(v<0 for v in daydiff.values())}"
        cells = [str(wait),id_,f"{signals}／{fills}",*money,f"{diff_loss:+,.0f}",f"{dif:+,.0f}",f"{missed}／{targets}",*ends,sign]
        report.append("|"+"|".join(cells)+"|")
    report += ["","","額はすべて実現した建玉の費用後損益。追加判断が成立しても、元価格注文の先着・追加追尾の未接触で元の決済が残る場合がある。"
               "両待機には同じ取得が多く、別市場や未使用期間の再現数には換算できない。"]
    (HERE/"全条件の効果.md").write_text("\n".join(report)+"\n",encoding="utf8")
    details = {"日別の可用性":by_day,"価格前提を満たす元建玉":members,"当日CSVのSHA256":inputs}
    (ROOT/"work/227出来高/量の照合.json").write_text(json.dumps(details,ensure_ascii=False,allow_nan=False),encoding="utf8")


if __name__=="__main__":
    main()
