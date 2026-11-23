"""R02の再予約を止める実口座で、最短返済遅延だけを1秒から3秒・5秒へ変える。"""
import json
from pathlib import Path
import runpy


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
REPLAY = runpy.run_path(str(HERE.parent/"再エントリーを再生する.py"))
SOURCE = REPLAY["SOURCE"]


def read(name: str) -> dict:
    """
    機能：前段の確定した研究元帳を読み込む。
    引数：name（str）は作業領域からの相対パス。
    返り値：dict。候補別の口座または入口固定の元帳。
    """
    return json.loads((ROOT/"work"/name).read_bytes())


def main() -> None:
    """
    機能：同一の反対主入口二度・同じ幅・同じ再開Cを両待機で原行再生し、223と照合して結果を保存する。
    引数：なし。224で使った45日および従来の1秒の場合を使用する。
    返り値：なし。遅延別・日別の損益と原行の照合結果を出力する。
    """
    stage = REPLAY["TRIAL"]/"反対の入口シグナル"
    policy = runpy.run_path(str(stage/"近傍と遅延.py"))
    families = {f"R{lag}":(f"R02L{lag}",policy,"223反対追試") for lag in (3,5)}
    baseline = read("222境界照合/口座元帳.json")
    one = read("224反対追試/口座元帳.json")["口座再生"]
    check = read("223反対追試/比較元帳.json")
    days = baseline["対象場"]
    books,seen = {},set()
    for folder,archive,member,manifest in SOURCE["parts"]():
        scenes,arrays,*_ = SOURCE["inputs"](folder,archive,member)
        refs = {s["session"]:s for s in SOURCE["read"](manifest)["scenes"]}
        for i,scene in enumerate(scenes):
            day = scene["session"]
            if day not in days or day in seen:
                continue
            seen.add(day)
            index = REPLAY["ENGINE"]["FINANCE"]["load_scene"](manifest.parent,refs[day])
            produced,_ = REPLAY["day"](arrays,i,scene,index,families,("A","C"))
            for key,rows in produced.items():
                books.setdefault(key,[]).extend(rows)
    assert set(days)==seen
    # ----------------------------------------
    fields = ("scene","request_line","entry_line","side","entry_time","entry_price","width","exit_line","exit_time","exit_price","net","status","activation_time","trigger_time")
    for wait in (20,30):
        for gate in ("A","C"):
            books[f"R1{gate}{wait}"] = one[f"R{gate}{wait}"]
        for lag in (3,5):
            ref = f"R02L{lag}_{wait}"
            assert books[f"R{lag}A{wait}"]==check["口座再生"][ref]
            assert all(all(a[k]==b[k] for k in fields) for a,b in zip(books[f"R{lag}C{wait}"],check["入口固定"][ref],strict=True))
    output = ROOT/"work/224執行遅延"
    output.mkdir(parents=True,exist_ok=True)
    (output/"口座元帳.json").write_text(json.dumps({"対象場":days,"口座再生":books},ensure_ascii=False,allow_nan=False),encoding="utf8")
    # ----------------------------------------
    measures = REPLAY["BASE"]["measures"]
    lines = ["# 反対シグナルで利益を守った後の返済遅延","","2026-11-22。R02の判断と幅を固定し、追尾発動から返済に使える最初の正常板までの最短遅延だけを1・3・5秒とした。静的な±1Rと場末返済は先着優先。Cは保護返済後に元の±1Rか場末が到来した後の次判断まで待つ。Aは保護返済後、通常どおり再予約可能。両方を224の全入口・予約から再生した。", "","金額は日経225mini 1枚換算の模擬約定。売買反対側の正常なラージ気配を使用し、往復費用1,077円を控除。損失・日末最大下落は絶対額。増減はいずれも同じ待機の単純IFDとの比較。", "","|待機|再開|最短遅延|取引／不明|利益|損失|収支|損失差|収支差|赤字日|日末最大下落|利益後赤字の損失|", "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    support,execution = [],[]
    for wait in (20,30):
        base = baseline["口座再生"][f"I{wait}"]
        base_days,base_tot = measures(days,base,wait)
        for gate in ("C","A"):
            for lag in (1,3,5):
                rows = books[f"R{lag}{gate}{wait}"]
                day_rows,t = measures(days,rows,wait)
                assert t["未知"]==0 and len(set(r["scene"] for r in rows))==len(days)
                nums = [*[t[k] for k in ("利益","損失","収支")],t["損失"]-base_tot["損失"],t["収支"]-base_tot["収支"],t["赤字場"],t["場末DD既知"],t["利益後赤字損失"]]
                identity = [f"{wait}分",gate,f"{lag}秒"]
                lines.append("|"+"|".join(identity+[f"{len(rows)}/{t['未知']}"]+[f"{n:,.0f}" for n in nums])+"|")
                delta = [b["確定収支"]-a["確定収支"] for a,b in zip(base_days,day_rows,strict=True)]
                improved = sorted((d for d in delta if d>0),reverse=True)
                names = [days[i][:10] for i,v in enumerate(delta) if v==max(delta)]
                nums = [sum(delta[:24]),sum(delta[24:]),sum(delta)-sum(improved[:1]),sum(delta)-sum(improved[:3])]
                support.append("|"+"|".join(identity+[f"{len(improved)}／{sum(d<0 for d in delta)}／{delta.count(0)}","・".join(names)]+[f"{n:,.0f}" for n in nums])+"|")
                if gate=="C" and lag>1:
                    original = one[f"RC{wait}"]
                    assert all(a["scene"]==b["scene"] and a["entry_line"]==b["entry_line"] for a,b in zip(original,rows,strict=True))
                    different = [(a,b) for a,b in zip(original,rows) if a["exit_line"]!=b["exit_line"]]
                    values = [(a,b) for a,b in different if a["net"]!=b["net"]]
                    by_day = sorted({a["scene"][:10] for a,_ in values})
                    signed = [b["net"]-a["net"] for a,b in values]
                    execution.append(f"|{wait}分|{lag}秒|{len(rows)}|{len(different)}|{len(values)}|{sum(signed):,.0f}|{'、'.join(by_day) or 'なし'}|")
    lines.extend(["","## 改善を支えた日数", "","45日すべてを分母に、元IFDから収支が増えた／減った／同じ日を数えた。上位日除外差は差が最も良い1日または3日を外して算出。", "","|待機|再開|最短遅延|改善／悪化／同額日|最大の改善日|前24日差|後21日差|上位1日除外差|上位3日除外差|", "|---|---|---:|---:|---|---:|---:|---:|---:|",*support,"","## 再開Cで1秒から変わった実決済", "","3・5秒のCが得た各133建玉を、223で同じ遅延を元取得に固定した建玉と照合。判断・取得・決済の原行、時刻、費用後損益、追尾発動時計が全件一致した。即再開Aも223の同じ遅延の1枚口座と全件一致。", "","|待機|遅延|同一取得|1秒と返済原行が異なる件数|うち損益も異なる件数|1秒からの収支差|損益の変わった日|","|---|---:|---:|---:|---:|---:|---|",*execution,"","## 再現", "","[224の再生条件](../反対信号保護の追試方針.md)と223の反対追試の元帳を準備し、リポジトリ直下で次を実行する。条件の探索や再選択を行わない。45日はすべて既使用。", "","```powershell","& 'work/複合テクニカル学習環境/Scripts/python.exe' -X utf8 (Get-Item 'study/00224*/執行遅延/反対信号の返済を遅らせる.py').FullName","```", ""])
    c1 = sum(t["net"] for t in books["R1C20"])
    c5 = sum(t["net"] for t in books["R5C20"])
    assert c5==sum(t["net"] for t in books["R3C20"])
    lines[2:2] = [f"20分待機で元の価格到達まで再予約を保留したCは、返済遅延1秒で＋{c1:,.0f}円、3秒・5秒で＋{c5:,.0f}円だった。実現額が変わったのは10月21日の1建玉。単純IFDより収支が増えたのは45日のうち4日で、最大の改善日を外すと収支差はマイナスになった。", ""]
    (HERE/"結果.md").write_text("\n".join(lines),encoding="utf8")


if __name__=="__main__":
    main()
