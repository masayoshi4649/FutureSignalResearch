"""元決済理由ごとに部品を外した同一建玉の損益差と、保有枠の入れ替わりを記録する。"""
import json
from pathlib import Path
import runpy

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
LIB = runpy.run_path(str(next((ROOT/"study").glob("00219_*/出口を集計する.py"))))


def change(pairs: list) -> dict:
    """
    機能：同じ取得の両決済が確定した組の改善・悪化額、件数、色の変化をまとめる。
    引数：pairs（list）は旧建玉・新建玉の組のリスト。
    返り値：dict。片側不明と同時に確定した建玉集合での負・正の変化を区別した集計。
    """
    known = [(a,b) for a,b in pairs if a["net"] is not None and b["net"] is not None]
    deltas = [round(b["net"]-a["net"]) for a,b in known]
    return {"総件数":len(pairs),"不明":len(pairs)-len(known),"改善数":sum(d>0 for d in deltas),
            "悪化数":sum(d<0 for d in deltas),"改善額":sum(max(d,0) for d in deltas),
            "悪化額":sum(min(d,0) for d in deltas),"差":sum(deltas),
            "黒字から赤字":sum(a["net"]>0>b["net"] for a,b in known),
            "赤字から黒字":sum(a["net"]<0<b["net"] for a,b in known)}


def markdown(rows: list, headers: list) -> list:
    """
    機能：日本語の表頭・行からMarkdown表を作る。
    引数：rows（list）は文字と整数の行、headers（list）は同じ列数の見出し。
    返り値：list。Markdownの行。
    """
    out = ["|"+"|".join(headers)+"|","|"+"|".join("---" for _ in headers)+"|"]
    for row in rows:
        assert len(row)==len(headers)
        out.append("|"+"|".join(f"{c:,}" if isinstance(c,int) else str(c) for c in row)+"|")
    return out


def main() -> None:
    """
    機能：元IFD注文の役割、元決済理由の影響、1枠口座と入口固定の違いを元帳から集計する。
    引数：なし。workの元IFD診断と分期限比較元帳を読む。
    返り値：None。正式な診断表を試行に、詳細診断を作業フォルダに保存する。
    """
    work = ROOT/"work/221元IFD"
    data = json.loads((work/"比較元帳.json").read_bytes())
    later = json.loads((ROOT/"work/221期限寄与/比較元帳.json").read_bytes())
    for mode in data:
        assert data[mode]["IFD"]==later[mode]["IFD"]
        data[mode]["D04"] = later[mode]["D04"]
    account,fixed = data["口座再生"],data["入口固定"]
    base = account["IFD"]
    dates = sorted({r["scene"] for r in base})
    reasons = list(dict.fromkeys(r["exit_reason"] for r in sorted(base,key=lambda t:t["status"])))
    cols = ("scene","entry_line","exit_line","entry_time","exit_time","width","net","status")
    for mode in (account,fixed):
        assert all(all(a[k]==b[k] for k in cols) for a,b in zip(base,mode["D00"],strict=True))
    # ----------------------------------------
    base_rows = []
    for reason in reasons:
        group = [r for r in base if r["exit_reason"]==reason]
        m = LIB["money"](group)
        base_rows.append([reason,len(group),sum(r["net"]>0 for r in group),sum(r["net"]<0 for r in group),
                          m["利益"],m["損失"],m["収支"]])
    assert sum(row[6] for row in base_rows)==1020063
    texts = ["# 元IFDの各注文を外した診断表","","2026-11-22。日経225mini 1枚、往復1,077円控除後の円。","",
             "## 元の181建玉の決済理由","",*markdown(base_rows,["決済理由","建玉","黒字","赤字","利益","損失","収支"])]
    # ----------------------------------------
    book_rows,attr_rows,flow_rows,period_rows,extremes = [],[],[],[],[]
    comparisons = {}
    for code in ("D00","D01","D02","D03","D04"):
        c,_ = LIB["evaluate"](dates,base,fixed[code],account[code])
        a = c["期間"]["全45日"]
        f = c["入口固定"]
        losses = sorted(t["net"] for t in account[code] if t["net"] is not None and t["net"]<0)
        book_rows.append([code,int(a["取得"]),int(a["未知"]),int(a["利益"]),int(a["損失"]),int(a["収支"]),
                          int(a["赤字場"]),int(a["場末DD既知"]),-int(losses[0]),-int(sum(losses[:5])),f["未知"],f["収支"]])
        period_rows.append([code,*[int(c["期間"][p][s]) for p in ("前24日","後21日","直近3日")
                                   for s in ("未知","損失","収支")]])
        pair = list(zip(base,fixed[code],strict=True))
        assert all(LIB["key"](a)==LIB["key"](b) for a,b in pair)
        for reason in reasons:
            g = [(a,b) for a,b in pair if a["exit_reason"]==reason]
            d = change(g)
            attr_rows.append([code,reason,*d.values()])
        c["元理由別変化"] = {reason:change([(a,b) for a,b in pair if a["exit_reason"]==reason]) for reason in reasons}
        proper = [(a,b) for a,b in pair if b["net"] is not None]
        proper.sort(key=lambda couple:couple[1]["net"]-couple[0]["net"])
        if code!="D00":
            for label,(a,b) in (("最大悪化",proper[0]),("最大改善",proper[-1])):
                extremes.append([code,label,LIB["stamp"](a["entry_time"]),"買" if a["side"]==0 else "売",
                                 a["width"],a["exit_reason"],int(a["net"]),b["exit_reason"],int(b["net"]),
                                 int(b["net"]-a["net"])])
        p = c["入替え"]
        flow_rows.append([code,p["共通旧"]["件数"],p["共通新"]["未知"],
                          p["共通新"]["収支"]-p["共通旧"]["収支"],p["旧専有"]["件数"],p["旧専有"]["収支"],
                          p["新専有"]["件数"],p["新専有"]["未知"],p["新専有"]["収支"],
                          int(c["期間"]["全45日"]["収支"]-1020063)])
        comparisons[code] = c
    texts += ["","## 各設定を1枚口座で再生した結果","",
              *markdown(book_rows,["設定","建玉","不明","既知利益","既知損失","既知収支","確定赤字日","既知日末最大下落","最大1件損失","損失大5件計","固定181の不明","固定181の既知収支"]),
              "","## 同じ取得に固定した場合の変化","",
              "確定同士を比較。改善・悪化は金額の大小、黒字→赤字・赤字→黒字は符号の変化。悪化額は負額。","",
              *markdown(attr_rows,["設定","元の理由","件数","不明","改善件数","悪化件数","改善額","悪化額","差額","黒字→赤字","赤字→黒字"]),
              "","## 期間別の1枚口座","",
              *markdown(period_rows,["設定","前24不明","前24既知損失","前24既知収支","後21不明","後21既知損失","後21既知収支","直近3不明","直近3既知損失","直近3既知収支"]),
              "","## 元と共通の新規と、入れ替わった新規","",
              *markdown(flow_rows,["設定","共通取得","共通の新不明","共通の既知収支差","元のみ件数","元のみ収支","新のみ件数","新のみ不明","新のみ既知収支","口座の既知収支差"]),
              "","## 元の同じ建玉で決済差が最も大きかった例","",
              *markdown(extremes,["設定","区分","取得日時JST","側","R","元の理由","元収支","新理由","新収支","差額"])]
    (HERE/"部品別の照合表.md").write_text("\n".join(texts)+"\n",encoding="utf8")
    (work/"寄与.json").write_text(json.dumps(comparisons,ensure_ascii=False,allow_nan=False),encoding="utf8")


if __name__=="__main__":
    main()
