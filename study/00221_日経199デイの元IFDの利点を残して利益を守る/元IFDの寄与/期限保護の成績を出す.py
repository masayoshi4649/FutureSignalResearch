"""延長の有無と保護手法を分け、候補ごとの利益喪失・収支・執行遅延を集計する。"""
import json
from pathlib import Path
import runpy

HERE = Path(__file__).resolve().parent
DIAG = runpy.run_path(str(HERE/"寄与を集計する.py"))
ROOT, LIB, table = DIAG["ROOT"], DIAG["LIB"], DIAG["markdown"]


def main() -> None:
    """
    機能：両モードを比較して元IFDとの差、元期限延長による変化と追随時の遅延感度を保存する。
    引数：なし。D04とT群の確認済み取引、および3遅延の再生元帳を使う。
    返り値：None。再現可能な集計表を試行へ、詳細集計を作業領域へ出力する。
    """
    work = ROOT/"work/221期限保護"
    books = json.loads((work/"比較元帳.json").read_bytes())
    delays = json.loads((work/"遅延比較元帳.json").read_bytes())
    all_static = json.loads((ROOT/"work/221期限寄与/比較元帳.json").read_bytes())
    for mode,group in books.items():
        group["D04"] = all_static[mode]["D04"]
    base = books["口座再生"]["IFD"]
    dates = sorted({t["scene"] for t in base})
    main_rows,period_rows,fixed_rows,delay_rows,extension_rows = [],[],[],[],[]
    results = {}
    for code in ("IFD","D04","T01","T02","T03","T04","T05","T06"):
        fixed,account = books["入口固定"][code],books["口座再生"][code]
        summary,_ = LIB["evaluate"](dates,base,fixed,account)
        results[code] = summary
        a = summary["期間"]["全45日"]
        guard = summary["口座の利益保護"]
        main_rows.append([code,*[int(a[k]) for k in ("取得","利益","損失","収支","赤字場","場末DD既知")],
                          guard["利益後赤字"],guard["利益後の損失"],sum(t["status"]==5 for t in account)])
        period_rows.append([code,*[int(summary["期間"][p]["収支"]) for p in ("前24日","後21日","直近3日")],
                            summary["改善日"],summary["悪化日"],int(summary["改善上位3日を除く差"]),
                            int(summary["方向"]["口座再生"]["買い"]["収支"]),int(summary["方向"]["口座再生"]["売り"]["収支"])])
        fixed_rows.append([code,*[summary["入口固定"][k] for k in ("利益","損失","収支")],
                           summary["固定の利益保護"]["利益後赤字"],summary["固定の利益保護"]["利益後の損失"],
                           int(a["建玉中央値下限"]),int(a["場中央値下限"]),f'{a["保有率"]:.1%}'])
        if code in ("T03","T04","T05","T06"):
            for name,items in (("固定181",fixed),("1枚口座",account)):
                eligible = [t for t in items if t.get("eligible_for_extension")]
                extended = [t for t in eligible if t["extended"]]
                extension_rows.append([code,name,len(eligible),len(extended),sum(t.get("activated",False) for t in extended),
                                      sum(t["status"]==5 for t in extended),sum(t["status"]==1 for t in extended),
                                      sum(t["status"]==2 for t in extended),sum(t["status"]==4 for t in extended)])
        assert a["未知"]==summary["入口固定"]["未知"]==0 and a["参加場"]==45
    # ----------------------------------------
    for code in ("T01","T02","T03","T04","T05","T06"):
        for wait in (1,3,5):
            key = code+"_"+str(wait)
            summary,_ = LIB["evaluate"](dates,base,delays["入口固定"][key],delays["口座再生"][key])
            a = summary["期間"]["全45日"]
            delay_rows.append([code,wait,*[int(a[k]) for k in ("取得","利益","損失","収支","赤字場","場末DD既知")],
                               summary["入口固定"]["収支"]])
            assert a["未知"]==summary["入口固定"]["未知"]==0
    rows = ["# 元の±1Rに期限延長と追尾を重ねた成績","","2026-11-22。既使用45デイ、日経225mini 1枚換算、往復1,077円控除後。全案45日参加・不明0件。金額は円。",
            "","## 1枚口座の利益・損失と含み益の保護","",
            *table(main_rows,["設定","建玉","利益","損失","収支","赤字日","日末最大下落","利益後赤字件数","利益後赤字の損失","追尾で返済"]),
            "","利益後赤字は保有中の実側気配で費用後含み益が一度でも正となり、決済で費用後赤字となった件数。",
            "","## 時期・方向・改善の集中","",
            *table(period_rows,["設定","前24日収支","後21日収支","直近3日収支","元比改善日","元比悪化日","改善上位3日除外の差","買い収支","売り収支"]),
            "","## 元の181建玉の出口効果と1枚口座の参加","",
            *table(fixed_rows,["設定","固定利益","固定損失","固定収支","固定の利益後赤字","固定の利益後損失",
                              "1枚口座の建玉中央値","1枚口座の日次中央値","1枚口座の保有率"]),
            "","## 60分で延長する玉の選択","",
            *table(extension_rows,["設定","対象","元H60を迎えた玉","延長","追尾起動","追尾で返済","元利確","元損切","場末"]),
            "","## 追尾要求から返済までの遅延感度","",
            *table(delay_rows,["設定","最短秒","取得","利益","損失","収支","赤字日","日末最大下落","固定181収支"])]
    (HERE/"期限と保護の照合表.md").write_text("\n".join(rows)+"\n",encoding="utf8")
    (work/"統計.json").write_text(json.dumps(results,ensure_ascii=False,allow_nan=False),encoding="utf8")


if __name__=="__main__":
    main()
