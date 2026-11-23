"""単一口座と同一取得の差、および元利確の消失と元損切の回避を集計する。"""
import json
from pathlib import Path
import runpy


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SUMMARY = runpy.run_path(str(next((ROOT/"study").glob("00222_*/建玉制限を再生する.py"))))
FOLDERS = ("223構造","223構造追試","223建値構造","223構造遅延")


def main() -> None:
    """
    機能：三巡と執行感度の各口座について、元の単純IFDの同じ建玉・同じ日付に照らして寄与を検算する。
    引数：なし。試行222の基準と各再生元帳を作業領域から読む。
    返り値：None。件数・確定損益・集中度・決済理由と時間帯別の比較をMarkdownに保存する。
    """
    baseline = json.loads((ROOT/"work/222境界照合/口座元帳.json").read_bytes())
    days = baseline["対象場"]
    output = ["# 価格構造による利益保護の全成績","",
              "各行の比較基準は同じ待機分の単純IFD（元の利確・損切、15:30全決済）。"
              "費用後の円。損失減は正ほど改善。「固定」は基準が取得した同じ133件。元利確・元損切・元場末は"
              "変更件数と固定収支差。動的返済で元の利確を小さな黒字に変えても、実現収支全体で評価する。","",
              "|ID・待機分|口座件数|不明|総利益|総損失|収支|基準比収支|基準比損失減|赤字日|日末DD|前24日差|後21日差|改善上位3日除外差|固定収支差|固定損失減|元利確|元損切|元場末|",
              "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for folder in FOLDERS:
        ledger = json.loads((ROOT/"work"/folder/"比較元帳.json").read_bytes())
        for tag in sorted(ledger["口座再生"]):
            wait = int(tag.split("_")[-1])
            book,fixed = ledger["口座再生"][tag],ledger["入口固定"][tag]
            base = baseline["口座再生"][f"I{wait}"]
            daily,current = SUMMARY["measures"](days,book,wait)
            old_daily,old = SUMMARY["measures"](days,base,wait)
            assert current["未知"]==0 and current["参加場"]==45
            # ----------------------------------------
            fixed_delta,fixed_loss = 0,0
            exits = {i:[0,0] for i in (1,2,4)}
            for before,after in zip(base,fixed,strict=True):
                assert all(before[k]==after[k] for k in ("scene","entry_index","side","width","request_line"))
                assert after["net"] is not None
                change = after["net"]-before["net"]
                fixed_delta += change
                fixed_loss += min(after["net"],0)-min(before["net"],0)
                t = exits[before["status"]]
                t[0] += after["exit_index"]!=before["exit_index"]
                t[1] += change
            assert fixed_delta==sum(t[1] for t in exits.values())
            diff = [a["収支"]-b["収支"] for a,b in zip(daily,old_daily,strict=True)]
            numbers = [current["取得"],current["未知"],current["利益"],current["損失"],current["収支"],
                       sum(diff),old["損失"]-current["損失"],current["赤字場"],current["場末DD既知"],
                       sum(diff[:24]),sum(diff[24:]),sum(sorted(diff,reverse=True)[3:]),fixed_delta,fixed_loss]
            output.append("|"+"|".join([tag,*[f"{v:,.0f}" for v in numbers],
                                        *[f"{n}件／{p:+,.0f}" for n,p in exits.values()]])+"|")
    (HERE/"全成績.md").write_text("\n".join(output)+"\n",encoding="utf8")


if __name__=="__main__":
    main()
