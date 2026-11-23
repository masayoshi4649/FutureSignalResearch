"""利確延長の2群を、選抜期間・元の取得固定・口座入れ替えに分けて比較する。"""
import json
from pathlib import Path
import runpy

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
COMMON = runpy.run_path(str(HERE.parent/"出口を集計する.py"))


def selected(cases: dict) -> str | None:
    """
    機能：閾値.mdの前24日選抜に従い、元より損失と収支を共に改善する適格案を選ぶ。
    引数：cases（dict）は同一探索回の期間別評価。
    返り値：strまたはNone。選抜ID又は適格なし。
    """
    base = cases["IFD"]["期間"]["前24日"]
    rows = {k:v["期間"]["前24日"] for k,v in cases.items() if k != "IFD"}
    kept = [k for k,a in rows.items() if a["未知"]<=base["未知"] and a["参加場"]==base["参加場"]
            and a["保有率"]>=.2 and min(a["場中央値下限"],a["建玉中央値下限"])>0
            and a["損失"]<base["損失"] and a["収支"]>base["収支"]
            and a["場末DD既知"]<=base["場末DD既知"] and a["赤字場"]<=base["赤字場"]]
    return min(kept,key=lambda k:(rows[k]["損失"],rows[k]["場末DD既知"],-rows[k]["収支"],k),default=None)


def main() -> None:
    """
    機能：全15候補について共通評価を計算し、延長を選択した取得数を添えて保存する。
    引数：なし。両群の固定入口および口座再生元帳を使用する。
    返り値：None。群別の全評価を各作業領域へ保存し、報告用の小計・選抜結果を試行に残す。
    """
    summary = {}
    for stage in ("219延長", "219遅延長"):
        folder = ROOT/"work"/stage
        books = json.loads((folder/"比較元帳.json").read_bytes())
        base = books["口座再生"]["IFD"]
        dates = sorted({t["scene"] for t in base})
        cases, compact = {}, {}
        for code, records in books["口座再生"].items():
            fixed = books["入口固定"][code]
            case,_ = COMMON["evaluate"](dates,base,fixed,records)
            cases[code] = case
            periods = case["期間"]
            compact[code] = {
                "件数": len(records), "未知": periods["全45日"]["未知"],
                "延長件数": sum(t.get("target_multiple",1)>1 for t in records),
                "元181収支": case["入口固定"]["収支"],
                "総利益": periods["全45日"]["利益"], "総損失": periods["全45日"]["損失"],
                "口座収支": periods["全45日"]["収支"], "前24収支": periods["前24日"]["収支"],
                "後21収支": periods["後21日"]["収支"], "上位3除外収支": periods["自身の利益上位3日除外"]["収支"],
                "利益後赤字": case["口座の利益保護"]["利益後赤字"],
            }
        summary[stage] = {"前24選抜":selected(cases),"全候補":compact}
        (folder/"成績.json").write_text(json.dumps(cases,ensure_ascii=False,allow_nan=False),encoding="utf8")
    (HERE/"二群の比較.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2,allow_nan=False)+"\n",encoding="utf8")


if __name__ == "__main__":
    main()
