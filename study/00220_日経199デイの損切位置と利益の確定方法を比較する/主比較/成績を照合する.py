"""主比較の40口座を集計し、旧IFD・W31・M34の実現取引と利確上限の有無を照合する。"""
from collections import Counter
import json
from pathlib import Path
import runpy

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OLD = next((ROOT/"study").glob("00219_*"))
STATS = runpy.run_path(str(OLD/"出口を集計する.py"))
NAV = ("scene","entry_line","side","request_line","entry_time","entry_price","width","horizon",
       "exit_line","exit_price","exit_time","status","net","origin")


def verify(data: dict) -> None:
    """
    機能：同じ条件の過去3元帳に新規・決済・価格・費用後損益・予約起源を一件ずつ照合する。
    引数：data（dict）は入口固定と口座の全取引。
    返り値：None。不一致なら実行を停止する。
    """
    references = {"S1P0":("219出口","IFD"),"S3P7":("219逆行","W31"),"S1P3":("219期限前保護","M34")}
    for new,(folder,ref) in references.items():
        old = json.loads((ROOT/"work"/folder/"比較元帳.json").read_bytes())
        for mode in ("入口固定","口座再生"):
            for a,b in zip(data[mode][new],old[mode][ref],strict=True):
                assert all(a[k]==b[k] for k in NAV)
                if new!="S1P0":
                    assert all(a.get(k)==b.get(k) for k in ("activation_time","trigger_time","floor_points"))


def test_delays(data: dict, dates: list) -> list:
    """
    機能：3つの利確案で動的返済の最短遅延を3・5秒に変え、元の口座・181件固定も含め再生する。
    引数：data（dict）は1秒基準の元帳、dates（list）は対象場名。
    返り値：list。各候補・秒数の固定収支と実口座の成績行。
    """
    engine = runpy.run_path(str(OLD/"口座再生.py"))
    policy = runpy.run_path(str(HERE/"出口条件.py"))
    codes = ["S3P3","S3P4","S3P6"]
    table = []
    for delay in (1,3,5):
        def decide(code: str, context: dict, index: object, entry: int, side: int,
                   width: float, horizon: str, term: dict) -> dict:
            """
            機能：同一の損切と利確を保ち、比較対象の最短待ち秒だけを変更する。
            引数：code（str）、context・term（dict）、index（PriceIndex）、entry・side（int）、
            width（float）、horizon（str）は元の決済と共通。
            返り値：dict。実現損益計算に用いる決済行と時計。
            """
            points = policy["stop_size"](code[:2],context,float(index.times[entry]),width)
            return policy["settle"](code[2:],points,context,index,entry,side,width,horizon,term,delay)

        book = data if delay==1 else engine["calculate"](dict(policy,decide=decide),codes)[0]
        for name in codes:
            rows = book["口座再生"][name]
            fixed = STATS["money"](book["入口固定"][name])
            _,a = STATS["calculate"](dates,rows,"全体")
            negative = sum(t["activated"] and t["net"] is not None and t["net"]<0 for t in rows)
            table.append([name,delay,a["取得"],a["未知"],a["赤字場"],a["損失"],a["収支"],
                          a["場末DD既知"],negative,fixed["損失"],fixed["収支"]])
    return table


def main() -> None:
    """
    機能：確認済み元帳で全損切×利確の相互比較表・固定利確の寄与と最短遅延への感度を作る。
    引数：なし。work/220主比較/比較元帳.json を読む。
    返り値：None。主要指標の比較を本試行のMarkdownに保存する。
    """
    data = json.loads((ROOT/"work/220主比較/比較元帳.json").read_bytes())
    dates = sorted({r["scene"] for r in data["口座再生"]["IFD"]})
    assert len(dates)==45
    verify(data)
    cases = {}
    for code,rows in data["口座再生"].items():
        case,_ = STATS["evaluate"](dates,data["口座再生"]["IFD"],data["入口固定"][code],rows)
        cases[code] = case
    selection = STATS["front_choice"](cases,[k for k in cases if k!="IFD"])
    assert selection["選抜"]=="S1P3"
    lines = ["# 同じ損切り幅で利確方法を変えた結果","",
             "45デイ、日経225mini換算1枚、往復費用1,077円、保有・予約共通1枠。単位は円。損失と日末最大下落は絶対額を表示する。[全条件の定義](条件.md)","",
             "|初期損切・利確|取得|未知|利益|損失|収支|日末最大下落|赤字日|前24日収支|後21日収支|直近3日収支|固定181損失|固定181収支|",
             "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for code,c in cases.items():
        a = c["期間"]["全45日"]
        fix = c["入口固定"]
        col = [a[k] for k in ("取得","未知","利益","損失","収支","場末DD既知","赤字場")]
        col.extend(c["期間"][k]["収支"] for k in ("前24日","後21日","直近3日"))
        col.extend([fix["損失"],fix["収支"]])
        lines.append("|"+code+"|"+"|".join(f"{v:,.0f}" for v in col)+"|")
    # ----------------------------------------
    lines.extend(["","## 同じ追尾から固定利確だけを取り外す","",
                  "元181建玉を固定して、利確指値がある側が実際に指値決済した建玉を抽出。利益額が増えたか減ったかを、上限を取り外した結果で比較する。右3列は独立の単一口座で、共通の実取得の決済差と旧専有・新専有の寄与を区別した。","",
                  "|指値あり→指値なし|固定の指値決済|同じ取得で増／減／同額／未知|固定の収支差|共通の取得 収支差|消えた取得の収支|新たな取得の収支|口座収支差|",
                  "|---|---:|---:|---:|---:|---:|---:|---:|"])
    for s in ("S1","S3"):
        for old,new in [("P3","P4"),("P7","P8"),("P6","P5")]:
            x,y = s+old,s+new
            vals = [(a["net"],b["net"]) for a,b in zip(data["入口固定"][x],data["入口固定"][y],strict=True)
                    if a["exit_reason"]=="静的利確"]
            counts = Counter("未知" if v is None else "増" if v>u else "減" if v<u else "同額" for u,v in vals)
            delta = sum(v-u for u,v in vals if v is not None)
            if not counts["未知"]:
                assert delta==cases[y]["入口固定"]["収支"]-cases[x]["入口固定"]["収支"]
            diff = STATS["contrast"](data["口座再生"][x],data["口座再生"][y])
            components = [diff["共通新"]["収支"]-diff["共通旧"]["収支"],diff["旧専有"]["収支"],diff["新専有"]["収支"]]
            lines.append(f"|{x}→{y}|{len(vals)}|"+"／".join(str(counts[label]) for label in ("増","減","同額","未知"))+
                         "|"+"|".join(f"{v:+,.0f}" for v in [delta,*components,components[0]-components[1]+components[2]])+"|")
    lines.extend(["","## 保護要求から初めて約定できるまでの秒数","",
                  "静的注文・期限と新規は共通条件、動的な保護要求から正常気配までの最短遅延だけを変える。起動後赤字はその口座で保護を起動した全建玉のうち、費用後損失で実決済した件数。","",
                  "|条件|秒|取得|未知|赤字日|口座損失|口座収支|日末最大下落|起動後赤字|固定181損失|固定181収支|",
                  "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"])
    for code,*counts in test_delays(data,dates):
        lines.append("|"+code+"|"+"|".join(f"{v:,.0f}" for v in counts)+"|")
    lines.extend(["","前24日規則での適格順は "+ "、".join(selection["適格順位"])+"。S1P3はM34と同一で、W31の初期幅を加えるS3群は第1位にならなかった。選択後の追加21日も以前から研究に利用済み。",""])
    (HERE/"全組合せの結果.md").write_text("\n".join(lines),encoding="utf8")


if __name__=="__main__":
    main()
