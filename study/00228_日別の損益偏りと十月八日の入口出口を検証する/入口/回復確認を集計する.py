"""旧BOへの局所化・回復確認の損益と、反対売買の実側照合を集計する。"""
from collections import Counter
from pathlib import Path
import runpy

HERE = Path(__file__).resolve().parent
K = runpy.run_path(str(HERE/"旧BOの回復を待つ.py"))
R = K["R"]


def main() -> None:
    """
    機能：全45日・10月8日以外・前後で費用後の損失と日次収支を比較し、回復まで待った取得を特定する。
    引数：なし。228入口と228回復入口の再生済み元帳を読む。
    返り値：None。全候補の比較をMarkdownに保存する。
    """
    read,work = R["SOURCE"]["read"],K["WORK"]
    original = read(R["WORK"]/"口座元帳.json")
    books = read(work/"口座元帳.json")["口座再生"]
    range_rows = read(work/"回復判断.json")
    audit = read(work/"反転照合.json")
    dates = original["対象場"]
    target = "2026-10-08_Day"
    lines = ["# 旧BOの実側回復を確認する追試","","日経225mini 1枚換算。円は往復費用控除後。損失は正の大きさ。"
             "純益差・損失差は同じ出口・待機の変更前比。日末DDは日次の累積収支で計算。"
             "45日全てが既使用で、前24日・後21日は同じ期間内の安定性をみる分割。"]
    for wait in (20,30):
        for exit_ in ("RC","I"):
            key = f"{exit_}{wait}"
            ref = original["口座再生"]["E0"+key]
            before,base = R["BASE"]["measures"](dates,ref,wait)
            lines += ["","## "+("RC" if exit_=="RC" else "単純IFD")+f"・開始{wait}分待機","",
                      "|入口|建玉／参加日|利益|損失|収支|損失差|赤字日／利益0赤字日|日末DD|保有率|建玉／日中央値|10/8収支|10/8除外収支差|前24／後21日収支差|最大改善日除外差|新判断の取得|",
                      "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
            for name in ("E0","K1","K2","K3"):
                trades = ref if name=="E0" else books[name+key]
                after,s = R["BASE"]["measures"](dates,trades,wait)
                assert s["未知"]==0
                delta = {a["場"]:a["収支"]-b["収支"] for a,b in zip(after,before,strict=True)}
                change = sum(delta.values())
                extra = sum(str(t["request_line"]) in range_rows[t["scene"]]["K2_"+str(wait)]["新判断"] for t in trades) if name=="K2" else 0
                today = next(r["収支"] for r in after if r["場"]==target)
                row = [name,f"{s['取得']}／{s['参加場']}",*[f"{s[k]:,.0f}" for k in ("利益","損失","収支")],
                       f"{s['損失']-base['損失']:+,.0f}",f"{s['赤字場']}／{sum(d['利益']==0 and d['損失']>0 for d in after)}",
                       f"{s['場末DD既知']:,.0f}",f"{s['保有率']:.2%}",f"{s['建玉中央値下限']:,.0f}／{s['場中央値下限']:,.0f}",
                       f"{today:+,.0f}",f"{change-delta[target]:+,.0f}",f"{sum(delta[d] for d in dates[:24]):+,.0f}／{sum(delta[d] for d in dates[24:]):+,.0f}",
                       f"{change-max(delta.values()):+,.0f}",str(extra)]
                lines.append("|"+"|".join(row)+"|")
    # ----------------------------------------
    lines += ["","## E4の反転が使った板","",
              "研究の予約対応は買売で共通のq0・q1を持つ。q1はq0から1秒以上後の別原行に到着した最初の正常BBOで、"
              "未取得・失効も共通。各反転取得のq1が板索引を独立に検索した最初の正常行と一致し、30秒の失効までに成立したことを確認した。"
              "新規買いAsk・決済Bid、新規売りBid・決済Askを元の生の板で照合し、倍率100と往復費用1,077円から元帳の収支を再計算した。","",
              "|口座|反転して買い|反転して売り|実反転の収支|","|---|---:|---:|---:|"]
    for key in ("E4RC20","E4I20","E4RC30","E4I30"):
        actual = [r for a in audit["実反転"].values() for r in a[key]]
        counts = Counter(r[1] for r in actual)
        lines.append(f"|{key}|{counts[0]}|{counts[1]}|{sum(r[-1] for r in actual):+,.0f}|")
    lines.append("")
    detail = "、".join(f"{k}{n}件" for k,n in audit["元E3該当の取得"].items())
    lines.append(f"元RC20でE3が直接該当した取得は{detail}だった。")
    (HERE/"回復確認の全口座比較.md").write_text("\n".join(lines)+"\n",encoding="utf8")


if __name__=="__main__":
    main()
