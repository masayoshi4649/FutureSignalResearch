"""同じ133の実取引で方向対照、時刻対照、広幅のみの実現損益と保護の寄与を比べる。"""
import argparse
import json
from pathlib import Path
import runpy

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PREV = runpy.run_path(str(next(HERE.parent.glob("00224_*/集計と閲覧入力を作る.py"))))
POLICY = runpy.run_path(str(HERE/"出口条件.py"))
LABELS = POLICY["LABELS"]
OLD = PREV["OLD"]
WORK = ROOT/"work/226方向時刻"


def contributions(base: list, book: list) -> dict:
    """
    機能：元の利確・損切・場末ごとに、変更した返済原行と実現差を同じ建玉どうしで集計する。
    引数：base・book（list）は単純IFDと候補の133取得。順序・原行・売買側は再生段で照合済み。
    返り値：dict。保護床が起動した建玉数、実際に保護決済した数、元理由別の差と該当日。
    """
    report = {}
    for name,status in (("利確",1),("損切",2),("場末",4)):
        pairs = [(a,b) for a,b in zip(base,book,strict=True) if a["status"]==status]
        changes = [(a,b) for a,b in pairs if (a["exit_line"],a["net"])!=(b["exit_line"],b["net"])]
        report[name] = {"元取得":len(pairs),"変化建玉":len(changes),"収支差":sum(b["net"]-a["net"] for a,b in changes),
                        "変化日":[a["scene"][:10] for a,_ in changes]}
    assert sum(r["元取得"] for r in report.values())==len(book)
    return {"保護起動":sum(t["activated"] for t in book),"狭幅該当":sum(t["narrow_source_line"] is not None for t in book),
            "保護決済":sum(t["status"]==5 for t in book),"元決済別":report}


def csv_rows(tables: dict, name: str, book: list, daily: list, periods: dict) -> None:
    """
    機能：全45日の費用後損益、建玉と含み益・返済の時計、各期間の比較を候補別CSVへ渡す。
    引数：tables・periods（dict）は表と期間集計、name（str）は候補名、book・daily（list）は元帳・日計。
    返り値：None。建玉の損益を建値と返済値から再検算する。
    """
    for t in book:
        tables["建玉明細"]["rows"].append(PREV["CSV"]["trade_row"](name,t))
    for d in daily:
        tables["デイ"]["rows"].append([name,*[d[k] for k in OLD["DAY"]],d["対象秒"],d["保有秒"]])
    for key,r in periods.items():
        tables["候補比較"]["rows"].append([name,key,*[r[k] for k in OLD["COLS"]],r["利益後赤字件数"],
                                       r["利益後赤字損失"],r["収支差"],r["損失差"]])


def main() -> None:
    """
    機能：10口座を同じ待機の単純IFD・広い追尾・原R02と比較し、公開表を元帳と突き合わせる。
    引数：CLI --照合（Path、任意）は既存の公開CSVの親ディレクトリ。
    返り値：None。MarkdownとCSV用の表と寄与を保存する。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--照合",type=Path)
    args = parser.parse_args()
    base = json.loads((ROOT/"work/222境界照合/口座元帳.json").read_bytes())
    ledger = json.loads((WORK/"口座元帳.json").read_bytes())
    dates = base["対象場"]
    accounts = ledger["口座再生"]
    assert dates==ledger["対象場"]
    tables = {"候補比較":{"headers":["候補","期間",*OLD["COLS"].values(),"含み益後赤字件数","含み益後赤字の損失円",
                                "対単純IFD収支差円","対単純IFD損失差円"],"rows":[]},
              "デイ":{"headers":["候補",*OLD["DAY"].values(),"対象秒数","既知保有秒数"],"rows":[]},
              "建玉明細":{"headers":PREV["DETAIL"],"rows":[]}}
    lines = ["# 方向と公表時刻を変えた実口座","",
             "日経225mini1枚・費用後の円。開始待機別に同じ45日・133取得。金額差は単純IFD比、総損失は赤字の絶対値。"
             "広幅差・反対差は収支について各待機のX5・X1を引く。保護起動は狭い・広いのどちらかが起動した建玉。"
             "元の価格注文が先に約定した建玉も起動数に含めた。","","## 口座の比較","",
             "|条件|総利益|総損失|収支|損失差|収支差|広幅差|反対差|赤字日|日末DD|保有率|保護起動／うち狭幅該当／実保護決済|前24日収支差|後21日収支差|改善・悪化日|改善上位3日除外収支差|",
             "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    diagnostics = {}
    by_origin = []
    for code,book in sorted(accounts.items(),key=lambda x:(x[0][-2:],x[0])):
        w = int(code[-2:])
        original = base["口座再生"]["I"+str(w)]
        periods,daily,diag = PREV["compare"](dates,book,original,w)
        contribution = contributions(original,book)
        diagnostics[code] = dict(**diag,**contribution,期間=periods)
        full = periods["全45日"]
        assert full["取得"]==133 and full["未知"]==0 and full["参加場"]==45
        net = full["収支"]
        wide = sum(t["net"] for t in accounts["X5C"+str(w)])
        opp = sum(t["net"] for t in accounts["X1C"+str(w)])
        basic = [full["利益"],full["損失"],net,full["損失差"],full["収支差"],net-wide,net-opp,full["赤字場"],full["場末DD既知"]]
        row = [code,*[f"{v:,.0f}" for v in basic],f"{full['保有率']:.2%}",
               f"{contribution['保護起動']}/{contribution['狭幅該当']}/{contribution['保護決済']}",f"{periods['前24日']['収支差']:,.0f}",
               f"{periods['後21日']['収支差']:,.0f}",f"{len(diag['改善日'])}/{len(diag['悪化日'])}",f"{diag['改善上位3日除外収支差']:,.0f}"]
        lines.append("|"+"|".join(row)+"|")
        cells = [f"{r['変化建玉']}/{r['元取得']}、{r['収支差']:+,.0f}円" for r in contribution["元決済別"].values()]
        by_origin.append("|"+"|".join([code,*cells])+"|")
        if code[:2] in ("X2","X3","X4"):
            csv_rows(tables,"226:"+code+"_"+LABELS[code[:2]],book,daily,periods)
    lines.extend(["","## 元の返済理由別に何が変わったか","",
                  "各セルは「決済が変わった取得数／元の件数、実現収支差」。損益が変わらなくても決済原行が変われば数える。","",
                  "|条件|元の利確|元の損切|元の場末|","|---|---:|---:|---:|",*by_origin])
    (HERE/"全条件の比較.md").write_text("\n".join(lines)+"\n",encoding="utf8")
    (WORK/"詳細.json").write_text(json.dumps(diagnostics,ensure_ascii=False,allow_nan=False),encoding="utf8")
    payload = {"tableNames":PREV["FILES"],"tables":tables}
    (WORK/"閲覧入力.json").write_text(json.dumps(payload,ensure_ascii=False,allow_nan=False),encoding="utf8")
    if args.照合:
        PREV["verify"](tables,args.照合)


if __name__=="__main__":
    main()
