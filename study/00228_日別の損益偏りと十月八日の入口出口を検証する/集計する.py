"""全日の口座を同条件の対照に突合し、日別・売買別の収支と試行の比較表を作る。"""
from argparse import ArgumentParser
import json
from pathlib import Path
import runpy

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PREV = runpy.run_path(str(next(HERE.parent.glob("00224_*/集計と閲覧入力を作る.py"))))
OLD = PREV["OLD"]
DAY = "2026-10-08_Day"
GROUPS = ("入口","回復入口","出口","小値幅","併用1","両方")
PUBLISH = {"E0RC":"元の入口と出口","E0I":"元の単純IFD","E2RC":"中期矛盾を見送り","E4RC":"実側反転",
           "K2RC":"回復まで監視","K08C":"逆向き背景で追尾","V02C":"直前の小値幅で利確",
           "X1C":"背景別即時と小幅利確","X2C":"背景別追尾と小幅利確","E2X2C":"入口と出口を変更"}


def ledger(folder: str) -> dict:
    """
    機能：実際の約定順の全場元帳を作業先から読む。
    引数：folder（str）はworkの子ディレクトリ名。
    返り値：dict。対象場・候補別建玉を含む元帳。
    """
    return json.loads((ROOT/"work"/folder/"口座元帳.json").read_bytes())


def fills(name: str, book: list, daily: list, periods: dict, tables: dict) -> None:
    """
    機能：一つの候補について建玉明細・日次・期間集計を各表へ出す。
    引数：name（str）は候補表示名、book・daily（list）は建玉と日計、periods・tables（dict）は期間計と出力。
    返り値：None。決済値から費用後損益を再計算する既存の明細関数を使用する。
    """
    for trade in book:
        row = PREV["CSV"]["trade_row"](name,trade)
        row.extend([OLD["stamp"](trade.get("extra_signal_time")),OLD["stamp"](trade.get("extra_trigger_time"))])
        tables["建玉明細"]["rows"].append(row)
    for day in daily:
        tables["デイ"]["rows"].append([name,*[day[k] for k in OLD["DAY"]],day["対象秒"],day["保有秒"]])
    for period,summary in periods.items():
        tables["候補比較"]["rows"].append([name,period,*[summary[k] for k in OLD["COLS"]],summary["利益後赤字件数"],
                                     summary["利益後赤字損失"],summary["収支差"],summary["損失差"]])


def main() -> None:
    """
    機能：全候補の損益経路を再集計し、10月8日除外・前後期間・同遅延感度も保存する。
    引数：CLI --照合（Path）は既に生成した候補別CSVの親。--全候補CSVは全条件を明細化する。
    返り値：None。比較表、CSV用データ、検算用の集計を生成する。
    """
    parser = ArgumentParser()
    parser.add_argument("--照合",type=Path)
    parser.add_argument("--全候補CSV",action="store_true")
    args = parser.parse_args()
    ref = ledger("228入口")
    dates,books = ref["対象場"],ref["口座再生"]
    columns = {"候補比較":["候補","期間",*OLD["COLS"].values(),"含み益後赤字件数","含み益後の損失円",
                            "同じ待機と対照出口との収支差円","同じ待機と対照出口との損失差円"],
               "デイ":["候補",*OLD["DAY"].values(),"対象秒数","既知保有秒数"],
               "建玉明細":[*PREV["DETAIL"][:-1],"動的返済要求時刻JST","追加条件成立時刻JST","追加返済要求時刻JST"]}
    tables = {k:{"headers":v,"rows":[]} for k,v in columns.items()}
    details = {}
    text = ["# 変更箇所と口座の比較","","日経225mini 1枚相当・費用控除後の円。"
            "差の基準は同じ待機時間のRC。末尾がI20・I30の入口テストだけは同じ待機時間の単純IFDが基準。"
            "損失・日末最大ドローダウン（DD）は絶対額。建玉中の含み損は日末DDに含まれない。"
            "前24日は9月21日〜10月22日、後21日は10月23日〜11月20日。"
            "利益ゼロ日は建玉があって費用後の黒字決済がなかった日。"]
    # ----------------------------------------
    for group in GROUPS:
        data = ledger("228"+group)
        assert data["対象場"]==dates
        text.extend(["","## "+group,"",
               "|条件|建玉|総利益|総損失|収支|赤字日／利益ゼロ日|日末DD|10/8収支|他44日収支差|前24日／後21日収支差|改善日／悪化日|改善上位3日を除く差|",
               "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"])
        for code,book in sorted(data["口座再生"].items(),key=lambda p:(p[0][-2:],p[0])):
            wait = int(code[-2:])
            target = "E0"+("I" if code[:-2].endswith("I") else "RC")+str(wait)
            base = books[target]
            periods,daily,diag = PREV["compare"](dates,book,base,wait)
            full = periods["全45日"]
            assert len(daily)==45 and full["未知"]==0
            single = next(d for d in daily if d["場"]==DAY)
            change = single["収支"]-sum(t["net"] for t in base if t["scene"]==DAY)
            excl = full["収支差"]-change
            zero = sum(d["利益"]==0 and d["損失"]>0 for d in daily)
            details[code] = {"対照":target,"期間":periods,"利益ゼロ日":zero,"十月八日":single,
                             "他44日収支差":excl,**diag}
            money = [full[k] for k in ("利益","損失","収支")]
            pair = f"{periods['前24日']['収支差']:+,.0f}／{periods['後21日']['収支差']:+,.0f}"
            line = [code,full["取得"],*[f"{v:,.0f}" for v in money],f"{full['赤字場']}／{zero}",
                    f"{full['場末DD既知']:,.0f}",f"{single['収支']:+,.0f}",f"{excl:+,.0f}",pair,
                    f"{len(diag['改善日'])}／{len(diag['悪化日'])}",f"{diag['改善上位3日除外収支差']:+,.0f}"]
            text.append("|"+"|".join(map(str,line))+"|")
            if code[:-2] in PUBLISH or args.全候補CSV:
                fills(f"228:{code}_{PUBLISH.get(code[:-2],'比較条件')}",book,daily,periods,tables)
    # ----------------------------------------
    delayed = json.loads((ROOT/"work/223反対追試/比較元帳.json").read_bytes())["入口固定"]
    text.extend(["","## X2の追加返済と元のRCを同じ秒数だけ遅らせた場合","",
                 "|待機分|最短遅延秒|対RC収支差|対RC損失差|赤字日|日末DD|",
                 "|---:|---:|---:|---:|---:|---:|"])
    for seconds in (1,3,5):
        group = ledger("228併用"+str(seconds))
        for wait in (20,30):
            base = books[f"E0RC{wait}"] if seconds==1 else delayed[f"R02L{seconds}_{wait}"]
            periods,_,_ = PREV["compare"](dates,group["口座再生"][f"X2C{wait}"],base,wait)
            d = periods["全45日"]
            text.append(f"|{wait}|{seconds}|{d['収支差']:+,.0f}|{d['損失差']:+,.0f}|{d['赤字場']}|{d['場末DD既知']:,.0f}|")
    out = ROOT/"work/228集計"
    out.mkdir(parents=True,exist_ok=True)
    (HERE/"全条件の比較.md").write_text("\n".join(text)+"\n",encoding="utf8")
    for filename,data in (("結果",details),("閲覧入力",{"tableNames":PREV["FILES"],"tables":tables})):
        (out/(filename+".json")).write_text(json.dumps(data,ensure_ascii=False,allow_nan=False),encoding="utf8")
    if args.照合:
        PREV["verify"](tables,args.照合)


if __name__=="__main__":
    main()
