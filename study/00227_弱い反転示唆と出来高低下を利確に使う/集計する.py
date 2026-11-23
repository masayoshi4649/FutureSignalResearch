"""同じ133建玉の利確変更をRCと単純IFDに対応させ、日次と建玉の損益表を作成する。"""
from argparse import ArgumentParser
import json
from pathlib import Path
import runpy

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PREV = runpy.run_path(str(next(HERE.parent.glob("00224_*/集計と閲覧入力を作る.py"))))
OLD = PREV["OLD"]
GROUPS = ("弱反転","確定足転換","出来高","量回復","停滞")
PUBLISH = {"W01":"単発反対即時","W08":"単発と失速追尾","W12":"大幅順行後の転換追尾",
           "D01":"直近出来高低下","D05":"薄商い逆足追尾","D09":"出来高回復と逆足","Z05":"場末の停滞失速"}


def diagnose(base: list, book: list) -> dict:
    """
    機能：追加の利確で実際に変わった建玉だけを対応させ、救った損失と早期決済した利益を分ける。
    引数：base・book（list[dict]）は同じ取得順のRCと候補。
    返り値：dict。元の利確・損切・場末・追尾の内訳、改善／悪化した建玉、追加の成立・救済数。
    """
    groups = {k:[0,0] for k in (1,2,4,5)}
    changed = []
    for a,b in zip(base,book,strict=True):
        assert (a["scene"],a["side"],a["entry_line"])==(b["scene"],b["side"],b["entry_line"])
        if b["extra_fill"]:
            groups[a["status"]][0] += 1
            delta = b["net"]-a["net"]
            groups[a["status"]][1] += delta
            changed.append((a,b,delta))
    return {"理由別":groups,"追加成立":sum(t["extra_signal"]>=0 for t in book),"追加返済":len(changed),
            "元赤字から非赤字":sum(a["net"]<0<=b["net"] for a,b,_ in changed),
            "元黒字から非黒字":sum(b["net"]<=0<a["net"] for a,b,_ in changed),
            "建玉改善":sum(v>0 for _,_,v in changed),"建玉悪化":sum(v<0 for _,_,v in changed),
            "買い差":sum(v for a,_,v in changed if a["side"]==0),"売り差":sum(v for a,_,v in changed if a["side"]==1)}


def main() -> None:
    """
    機能：全候補の前後期間、損失と日次安定性、元利確の維持を一覧化し、代表候補別にCSVを用意する。
    引数：CLIの --全候補CSV（bool）は全定義を出力、--照合（Path）は公開済みCSVの親フォルダ。
    返り値：None。集計表Markdown、元帳照合用JSON、候補別のCSV作成入力を保存する。
    """
    parser = ArgumentParser()
    parser.add_argument("--全候補CSV",action="store_true")
    parser.add_argument("--照合",type=Path)
    args = parser.parse_args()
    ref = json.loads((ROOT/"work/224反対追試/口座元帳.json").read_bytes())
    ifd = json.loads((ROOT/"work/222境界照合/口座元帳.json").read_bytes())["口座再生"]
    dates = ref["対象場"]
    columns = {"候補比較":["候補","期間",*OLD["COLS"].values(),"含み益後赤字件数","含み益後赤字の損失円",
                            "対RC収支差円","対RC損失差円","対単純IFD収支差円","対単純IFD損失差円"],
               "デイ":["候補",*OLD["DAY"].values(),"対象秒数","既知保有秒数"],
               "建玉明細":[*PREV["DETAIL"][:-1],"動的返済要求時刻JST","追加利確の条件成立時刻JST",
                         "追加利確の返済要求時刻JST","追加で返済","対RC収支差円"]}
    tables = {k:{"headers":v,"rows":[]} for k,v in columns.items()}
    overview = ["# 技術的な利確を追加した全候補","","金額はmini 1枚の手数料と想定滑り控除後の円。"
                "損失は赤字建玉の損失の絶対額。全候補が開始待機別のRCと同じ133取得・45デイ、決済未知0件。"
                "差は同じ待機時間のRCからの増減。元利確はRCの固定指値で終わった建玉のうち先に返済した件数。"
                "改善／悪化は45日の日次収支差の符号、上位3除外は日次収支の改善が大きい日を最大3日除いた差。",
                "","|候補|待機|追加成立／追加返済|総利益|総損失|収支|損失差|収支差|IFDとの差（収支）|赤字日|日末DD|"
                "元利確の早期返済|前24日／後21日収支差|改善／悪化日|上位3除外|",
                "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    result = {}
    for group in GROUPS:
        data = json.loads((ROOT/"work"/("227"+group)/"口座元帳.json").read_bytes())
        assert data["対象場"]==dates and data.get("執行秒",1)==1
        for code,book in sorted(data["口座再生"].items(),key=lambda v:(v[0][-2:],v[0])):
            kind,wait = code[:-3],int(code[-2:])
            base = ref["口座再生"][f"RC{wait}"]
            periods,daily,diag = PREV["compare"](dates,book,base,wait)
            old_periods,_,_ = PREV["compare"](dates,book,ifd[f"I{wait}"],wait)
            why = diagnose(base,book)
            full = periods["全45日"]
            assert (full["取得"],full["未知"],full["参加場"])==(133,0,45)
            assert sum(q[1] for q in why["理由別"].values())==full["収支差"]
            result[code] = {**why,**diag,"期間":periods,"IFD比":old_periods["全45日"]["収支差"]}
            money = [full[k] for k in ("利益","損失","収支","損失差","収支差")]
            pair = f"{periods['前24日']['収支差']:+,.0f}／{periods['後21日']['収支差']:+,.0f}"
            row = [kind,str(wait),f"{why['追加成立']}/{why['追加返済']}",*[f"{v:,.0f}" for v in money],
                   f"{old_periods['全45日']['収支差']:+,.0f}",str(full["赤字場"]),f"{full['場末DD既知']:,.0f}",
                   str(why["理由別"][1][0]),pair,f"{len(diag['改善日'])}/{len(diag['悪化日'])}",
                   f"{diag['改善上位3日除外収支差']:+,.0f}"]
            overview.append("|"+"|".join(row)+"|")
            if not args.全候補CSV and kind not in PUBLISH:
                continue
            name = f"227:{code}_{PUBLISH.get(kind,'追加利確')}"
            for a,b in zip(base,book,strict=True):
                line = PREV["CSV"]["trade_row"](name,b)
                line.extend([OLD["stamp"](b["extra_signal_time"]),OLD["stamp"](b["extra_trigger_time"]),
                             int(b["extra_fill"]),b["net"]-a["net"]])
                tables["建玉明細"]["rows"].append(line)
            for d in daily:
                tables["デイ"]["rows"].append([name,*[d[k] for k in OLD["DAY"]],d["対象秒"],d["保有秒"]])
            for key,s in periods.items():
                tables["候補比較"]["rows"].append([name,key,*[s[k] for k in OLD["COLS"]],s["利益後赤字件数"],
                        s["利益後赤字損失"],s["収支差"],s["損失差"],old_periods[key]["収支差"],old_periods[key]["損失差"]])
    # ----------------------------------------
    work = ROOT/"work/227集計"
    work.mkdir(parents=True,exist_ok=True)
    (HERE/"全条件の比較.md").write_text("\n".join(overview)+"\n",encoding="utf8")
    (work/"詳細.json").write_text(json.dumps(result,ensure_ascii=False,allow_nan=False),encoding="utf8")
    (work/"閲覧入力.json").write_text(json.dumps({"tableNames":PREV["FILES"],"tables":tables},allow_nan=False,
                                           ensure_ascii=False),encoding="utf8")
    if args.照合:
        PREV["verify"](tables,args.照合)


if __name__=="__main__":
    main()
