"""出来高による条件を元IFD・価格のみの対照と同じ入口で比較し、期間・口座の差を残す。"""
from collections import Counter
from datetime import datetime,timedelta,timezone
import json
from pathlib import Path
import runpy


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
REPORT = runpy.run_path(str(HERE.parent/"値幅による保護/差を調べる.py"))
JST = timezone(timedelta(hours=9))


def read(path: Path) -> dict:
    """
    機能：生成済みの比較口座や件数を読み取る。
    引数：path（Path）はJSONのパス。
    返り値：dict。元帳または出来高情報。
    """
    return json.loads(path.read_bytes())


def main() -> None:
    """
    機能：原静的戦略との完全一致確認、損益・損失・日付偏り、実出来高を加えた対応対照を計算する。
    引数：なし。45日のQ00〜Q13元帳と当時の出来高照合結果を使用。
    返り値：なし。「全条件の結果.md」と作業用の数値内訳を保存する。
    """
    base = read(ROOT/"work/222境界照合/口座元帳.json")
    books = read(ROOT/"work/223量/比較元帳.json")
    extra = read(ROOT/"work/223量追試/比較元帳.json")
    for mode,rows in extra.items():
        assert not set(rows).intersection(books[mode])
        books[mode].update(rows)
    structural = read(ROOT/"work/223構造/比較元帳.json")
    days = base["対象場"]
    refs = read(ROOT/"work/223量/出来高の利用可能範囲.json")
    results = {}
    lines = ["# 出来高を加えた利益保護の全比較","","2026-11-22。日経225mini 1枚換算の45デイ。金額はすべて費用後の円、損失・日末最大下落は絶対額。各待機の単純IFDと同じ原板・予約を利用し、口座損益と、元の133建玉だけを返した成績を分けた。","","## 取引に使えた出来高","","対象分数は開始待機後から15:30まで。参照足は取得後条件を適用する前の、当時利用できた1分足の数。長い空白を含む資料で、シグナルを出せない時間帯にも元の±1R注文と通常の利益保護は有効。","","|開始待機|全場の対象分数|参照足|出来高急増|逆足＋下抜け＋量（買／売）|高値拒否＋量（買／売）|二段確認＋量（買／売）|","|---|---:|---:|---:|---:|---:|---:|"]
    for wait in (20,30):
        counts = [r[str(wait)] for r in refs.values()]
        nums = [sum(c[name] for c in counts) for name in ("分数","参照足","出来高急増")]
        pair = ["／".join(f"{sum(c[s][k] for c in counts):,}" for s in ("買い","売り")) for k in ("逆足と下抜けと量","試し失敗と量","二段確認と量")]
        lines.append("|"+"|".join([str(wait),*[f"{n:,.0f}" for n in nums],*pair])+"|")
    # ----------------------------------------
    for wait in (20,30):
        original = base["口座再生"][f"I{wait}"]
        for mode in ("入口固定","口座再生"):
            control = structural[mode][f"S00_{wait}"]
            assert all((a["scene"],a["entry_line"],a["exit_line"],a["net"])==(b["scene"],b["entry_line"],b["exit_line"],b["net"]) for a,b in zip(control,books[mode][f"Q00_{wait}"],strict=True))
        lines.extend(["",f"## 開始{wait}分待機・口座の成績","","含み益後の損失は原板の清算側気配で一度でも費用後プラスを付け、その後マイナスで確定した建玉の損失額。前後差と上位3日除外差は同じ待機の単純IFDと比較した。","","|条件|取得／不明|利益|損失|収支|赤字日|日末最大下落|含み益後の損失|前24差|後21差|改善上位3日除外差|","|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"])
        records = {}
        for name in [f"I{wait}",*[f"Q{i:02d}_{wait}" for i in range(14)]]:
            fixed = books["入口固定"].get(name,original)
            rows = books["口座再生"].get(name,original)
            info = REPORT["details"](original,fixed,rows,days,wait)
            assert all(r["exit_time"] is not None and r["net"]==r["gross"]-1077 for r in rows+fixed)
            records[name] = results[name] = info
            p = info["期間"]
            a = p["全45"]["候補"]
            nums = [*[a[k] for k in ("利益","損失","収支","赤字場","場末DD既知","利益後赤字損失")],p["前24"]["金額差"]["収支"],p["後21"]["金額差"]["収支"],p["全45"]["改善上位3日除外差"]]
            lines.append("|"+"|".join([name,f"{a['取得']}/{a['未知']}",*[f"{n:,.0f}" for n in nums]])+"|")
        lines.extend(["","### 同一建玉の比較","","元IFDの利確と同じ原行で返せた件数、および元損切から費用後黒字へ移せた件数を示す。早期サインは返済までに1回以上発生した建玉件数で、通常の0.90R保護も含む追尾返済件数とは異なる。","","|条件|早期サイン|元IFD利確維持／母数|元損切の赤→黒／母数|元の利確群の収支差|元の損切群の収支差|元の場末群の収支差|全固定の収支差|","|---|---:|---:|---:|---:|---:|---:|---:|"])
        for name,info in records.items():
            if name.startswith("I"):
                continue
            group = info["元の理由別"]
            changes = [group[i]["同一取得の収支差"] for i in (1,2,4)]
            signals = sum(r["structure_at"] is not None for r in books["入口固定"][name])
            lines.append("|"+"|".join([name,str(signals),f"{group[1]['返済原行維持']}/{group[1]['母数']}",f"{group[2]['赤から黒']}/{group[2]['母数']}",*[f"{n:,.0f}" for n in changes+[sum(changes)]]])+"|")
        # ----------------------------------------
        lines.extend(["","### 条件を1段加えた場合","","差は行に示す2候補間。固定の改善・悪化・同じは返済額の比較で、口座収支差には枠が空いて入れ替わる後続の建玉も含む。","","|比較|固定で改善／悪化／同じ|固定収支差|口座収支差|口座総損失差|","|---|---:|---:|---:|---:|"])
        for previous,current in ((1,2),(8,3),(4,5),(6,10),(9,10),(10,12),(12,11),(10,13)):
            a,b = (f"Q{i:02d}_{wait}" for i in (previous,current))
            deltas = [v["net"]-u["net"] for u,v in zip(books["入口固定"][a],books["入口固定"][b],strict=True)]
            count = Counter((1 if x>0 else -1 if x<0 else 0) for x in deltas)
            aa,bb = (records[n]["期間"]["全45"]["候補"] for n in (a,b))
            lines.append(f"|{a}→{b}|{count[1]}/{count[-1]}/{count[0]}|{sum(deltas):,.0f}|{bb['収支']-aa['収支']:,.0f}|{bb['損失']-aa['損失']:,.0f}|")
    # ----------------------------------------
    lines.extend(["","## 二段確認で元IFDとの差が大きかった日・時刻","","Q10の20分待機で、同じ元建玉の決済額の差が大きい順に改善・悪化を各2件掲載。時刻は日本時間。", "","|日付・取得|方向|元1R|元の決済|Q10決済|早期サイン|元→Q10収支|差額|","|---|---|---:|---|---|---|---:|---:|"])
    changes = sorted([(b["net"]-a["net"],a,b) for a,b in zip(base["口座再生"]["I20"],books["入口固定"]["Q10_20"],strict=True) if a["net"]!=b["net"]],key=lambda item:item[0])
    for delta,a,b in list(reversed(changes[-2:]))+changes[:2]:
        reason = {1:"利確",2:"損切",4:"場末",5:"追尾"}
        entry,original,now = (datetime.fromtimestamp(t,JST) for t in (a["entry_time"],a["exit_time"],b["exit_time"]))
        signal = datetime.fromtimestamp(b["structure_at"],JST).strftime("%H:%M:%S") if b["structure_at"] is not None else "通常追尾"
        lines.append(f"|{entry:%m-%d %H:%M:%S}|{('買','売')[a['side']]}|{a['width']}|{original:%H:%M:%S} {reason[a['status']]}|{now:%H:%M:%S} {reason[b['status']]}|{signal}|{a['net']:,.0f}→{b['net']:,.0f}|{delta:,.0f}|")
    (HERE/"全条件の結果.md").write_text("\n".join(lines)+"\n",encoding="utf8")
    (ROOT/"work/223量/比較内訳.json").write_text(json.dumps(results,ensure_ascii=False,allow_nan=False),encoding="utf8")


if __name__=="__main__":
    main()
