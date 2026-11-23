"""元利確後の増減と、保有時間が変わって入れ替わった建玉を別々に集計する。"""
from collections import Counter
import json
from pathlib import Path
import runpy

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
STATS = runpy.run_path(str(next((ROOT/"study").glob("00219_*/出口を集計する.py"))))


def main() -> None:
    """
    機能：両元帳の損益、元利確した建玉の内訳、実際の変更・保護の原行順を照合する。
    引数：なし。作業領域の221延伸を参照する。
    返り値：None。各比較条件の成績と支持件数を本試行のMarkdownに出力する。
    """
    data = json.loads((ROOT/"work/221延伸/比較元帳.json").read_bytes())
    books,fixed = data["口座再生"],data["入口固定"]
    base = books["IFD"]
    dates = sorted({r["scene"] for r in base})
    stats = {}
    results = ["# 利確延長9案の板再生結果","","全45デイの費用後円額。損失・日末最大下落は正額。どの案も未知0件で全45日で取得した。","",
               "|候補|取得|利益|損失|収支|日末最大下落|赤字日|前24日収支|後21日収支|末3日収支|固定181収支|固定181損失|",
               "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    details = ["","## 元181取得を固定して、元利確の勝ちを伸ばせたか","",
               "延長有効は変更が間に合った件数（H01のみ取得時から延長）。元利確は元IFDが利確した65件のうち延長が有効だった件数。増減は元と同じ取得の費用後収支差。","",
               "|候補|延長有効|元利確|収支増の件数と増額|収支減の件数と減額|同額|元利確以外の収支差|",
               "|---|---:|---:|---:|---:|---:|---:|"]
    changes = ["","## 1枠での収支差を取引の入れ替わりに分ける","",
               "|候補|共通の実取得数|共通の決済差|取得できなくなった旧建玉の収支|新たに取得した建玉の収支|元より改善した日／悪化した日|改善上位3日除外の元との差|",
               "|---|---:|---:|---:|---:|---:|---:|"]
    for code,rows in books.items():
        c,_ = STATS["evaluate"](dates,base,fixed[code],rows)
        stats[code] = c
        a,p,f = c["期間"]["全45日"],c["期間"],c["入口固定"]
        assert a["未知"]==f["未知"]==0 and a["参加場"]==45
        vals = [a[k] for k in ("取得","利益","損失","収支","場末DD既知","赤字場")]
        vals.extend([p[k]["収支"] for k in ("前24日","後21日","直近3日")]+[f["収支"],f["損失"]])
        results.append("|"+code+"|"+"|".join(f"{v:,.0f}" for v in vals)+"|")
        if code=="IFD":
            continue
        # ----------------------------------------
        deltas = []
        other = 0
        for old,new in zip(base,fixed[code],strict=True):
            changed = new["extension_live"]
            if not changed or old["status"]!=1:
                assert old["exit_index"]==new["exit_index"] and old["net"]==new["net"]
            if changed and code!="H01":
                assert new["entry_time"]<=new["switch_request_time"]<=new["switch_time"]-1
                assert new["switch_time"]<=old["exit_time"]
            if changed and old["status"]==1:
                deltas.append(new["net"]-old["net"])
            else:
                other += new["net"]-old["net"]
        signs = Counter((d>0)-(d<0) for d in deltas)
        details.append(f"|{code}|{sum(r['extension_live'] for r in fixed[code])}|{len(deltas)}|"
                       f"{signs[1]}件／＋{sum(v for v in deltas if v>0):,.0f}円|"
                       f"{signs[-1]}件／−{-sum(v for v in deltas if v<0):,.0f}円|{signs[0]}|{other:,.0f}|")
        pieces = c["入替え"]
        net = pieces["共通新"]["収支"]-pieces["共通旧"]["収支"]
        changes.append(f"|{code}|{pieces['共通新']['件数']}|{net:+,.0f}|{pieces['旧専有']['収支']:+,.0f}|"
                       f"{pieces['新専有']['収支']:+,.0f}|{c['改善日']}／{c['悪化日']}|{c['改善上位3日を除く差']:+,.0f}|")
    ident = ("scene","side","entry_index","entry_time","exit_index","exit_time","net","status")
    for mode,all_rows in data.items():
        for old,new in zip(all_rows["IFD"],all_rows["H00"],strict=True):
            assert all(old[key]==new[key] for key in ident)
    chosen = STATS["front_choice"](stats,[k for k in stats if k!="IFD"])
    results.extend(details+changes+["","前24日の適格順は"+"、".join(chosen["適格順位"])+"。",""])
    (HERE/"固定と口座の全成績.md").write_text("\n".join(results),encoding="utf8")


if __name__=="__main__":
    main()
