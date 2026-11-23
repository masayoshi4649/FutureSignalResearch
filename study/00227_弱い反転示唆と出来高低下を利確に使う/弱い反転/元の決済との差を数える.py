"""反転示唆で実際に早く返済した取引を、同一時刻に建てたRCと一組ずつ照合する。"""
from collections import defaultdict
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
JST = timezone(timedelta(hours=9))


def summarize(ref: list, trial: list, dates: list) -> dict:
    """
    機能：同じ133取得における損失減と利益減を分け、元の利確と損切への作用を算出する。
    引数：ref・trial（list[dict]）は同じ開始待機のRCと追加利確の時系列、dates（list[str]）は対象日。
    返り値：dict。既知の金額・件数、前後期間の差、実返済が早まった代表例。
    """
    days = {day:0 for day in dates}
    totals = defaultdict(int)
    altered = []
    for old,new in zip(ref,trial,strict=True):
        assert all(old[key]==new[key] for key in ("scene","entry_time","entry_line","side","width","entry_price"))
        assert new["exit_index"]<=old["exit_index"] and new["extra_fill"]==(new["exit_index"]<old["exit_index"])
        previous,current = int(old["net"]),int(new["net"])
        delta = current-previous
        totals["収支"] += current
        totals["総損失"] += max(-current,0)
        totals["総利益"] += max(current,0)
        totals["利益差"] += max(current,0)-max(previous,0)
        totals["損失差"] += max(-current,0)-max(-previous,0)
        totals["示唆"] += new["extra_signal"]>=0
        days[old["scene"]] += delta
        if not new["extra_fill"]:
            assert delta==0
            continue
        totals["早期返済"] += 1
        totals["うち実赤字"] += current<0
        totals["救った赤字"] += previous<0<=current
        totals["新たな赤字"] += current<0<=previous
        reason = {1:"静的利確",2:"静的損切",4:"場末",5:"既存追尾"}[old["status"]]
        totals[reason+"数"] += 1
        totals[reason+"差"] += delta
        altered.append((delta,old,new))
    # ----------------------------------------
    totals["収支差"] = sum(days.values())
    assert totals["収支差"]==totals["利益差"]-totals["損失差"]
    totals["前差"] = sum(days[d] for d in dates[:24])
    totals["後差"] = sum(days[d] for d in dates[24:])
    totals["改善日"] = sum(v>0 for v in days.values())
    totals["悪化日"] = sum(v<0 for v in days.values())
    totals["改善上位3日除外"] = totals["収支差"]-sum(sorted(days.values(),reverse=True)[:3])
    if altered:
        totals["最小差"] = min(altered,key=lambda p:p[0])
        totals["最大差"] = max(altered,key=lambda p:p[0])
    return totals


def main() -> None:
    """
    機能：各候補の判定根拠の強さ・即時または追尾の違いを、元の決済理由と期間別に比較する。
    引数：なし。作業領域の試行224と227の候補元帳を読む。
    返り値：None。弱い反転群の成績表を同じフォルダのMarkdownに出力する。
    """
    previous = json.loads((ROOT/"work/224反対追試/口座元帳.json").read_bytes())
    test = json.loads((ROOT/"work/227弱反転/口座元帳.json").read_bytes())
    second = json.loads((ROOT/"work/227確定足転換/口座元帳.json").read_bytes())
    assert previous["対象場"]==test["対象場"]==second["対象場"]
    assert test["口座再生"].keys().isdisjoint(second["口座再生"])
    accounts = test["口座再生"] | second["口座再生"]
    report = ["# 弱い逆方向の示唆で何件の元利確を手放したか","",
              "各候補は開始20・30分待機の日経デイ45日、RCと同じ133取得。金額はmini1枚費用後の円。"
              "損失は赤字額の絶対値、各差は同じ待機のRCを引いたもの。「示唆」は利益条件を満たした上で追加判定が出た件数。"
              "追加追尾が起動しても先に元注文が決済する場合がある。","",
              "|待機・候補|示唆／早期返済|うち実赤字|元赤字を非負にした数|総利益|総損失|収支|利益差|損失差|収支差|前24日差|後21日差|改善／悪化日|改善上位3日除外差|",
              "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    results = {}
    for wait in (20,30):
        for n in range(1,15):
            code = f"W{n:02d}C{wait}"
            r = summarize(previous["口座再生"][f"RC{wait}"],accounts[code],test["対象場"])
            results[code] = r
            values = [code,f'{r["示唆"]}/{r["早期返済"]}',r["うち実赤字"],r["救った赤字"],
                      *[f"{r[key]:,}" for key in ("総利益","総損失","収支")],
                      *[f"{r[key]:+,}" for key in ("利益差","損失差","収支差","前差","後差")],
                      f'{r["改善日"]}/{r["悪化日"]}',f'{r["改善上位3日除外"]:+,}']
            report.append("|"+"|".join(str(x) for x in values)+"|")
    # ----------------------------------------
    report += ["","## 20分待機で元のRCのどの決済が変わったか","",
               "件数は早く決済した数、円はその取得における収支の差。","",
               "|候補|元の静的利確|元の静的損切|元の場末返済|元の既存追尾|","|---|---:|---:|---:|---:|"]
    for code,r in results.items():
        if code.endswith("20"):
            cells = [f'{r[k+"数"]}件／{r[k+"差"]:+,}' for k in ("静的利確","静的損切","場末","既存追尾")]
            report.append("|"+"|".join([code,*cells])+"|")
    report += ["","## 最大の改善と悪化を同じ取得で比較","",
               "|20分・候補|収支差|方向|新規日時|元の返済・損益|新しい返済・損益|",
               "|---|---:|---|---|---|---|"]
    for code in ("W01C20","W05C20","W07C20","W08C20","W09C20","W10C20","W11C20","W12C20"):
        for name in ("最大差","最小差"):
            if name not in results[code]:
                continue
            delta,old,new = results[code][name]
            stamp = datetime.fromtimestamp(old["entry_time"],JST).strftime("%m-%d %H:%M:%S")
            old_exit = datetime.fromtimestamp(old["exit_time"],JST).strftime("%H:%M:%S")
            new_exit = datetime.fromtimestamp(new["exit_time"],JST).strftime("%H:%M:%S")
            side = ("買い","売り")[old["side"]]
            report.append(f'|{code}|{delta:+,}|{side}|{stamp}|{old_exit}、{old["net"]:+,.0f}|{new_exit}、{new["net"]:+,.0f}|')
    (HERE/"決済の内訳.md").write_text("\n".join(report)+"\n",encoding="utf8")


if __name__=="__main__":
    main()
