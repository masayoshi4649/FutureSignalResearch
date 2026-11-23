"""日経199_02の両注文に対し、順行から利益を戻した経路と最終的な決済を板原行で照合する。"""
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import runpy
from statistics import median

import numpy as np


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
ORIGINAL = runpy.run_path(str(next((ROOT/"study").glob("00219_*/経路診断/元の保有経路を測る.py"))))
FEE = ORIGINAL["FEE"]
BASIS = (("費用後プラス",0.0),("費用後25pt",25.0),("費用後50pt",50.0),("費用後100pt",100.0),
         ("費用後150pt",150.0),("費用後200pt",200.0))
RATIOS = (.25,.50,.75,.90)
LABELS = {1:"利確",2:"損切",4:"場末"}


def sample(trade: dict, records: np.ndarray) -> dict:
    """
    機能：確定済みの建玉を原行で照合し、順行初達の速さと元決済前の押し戻しを測る。
    引数：trade（dict）は単純IFDの建玉、records（np.ndarray）は当日の時系列価格索引。
    返り値：dict。建玉・観測極値、段階別の初達時計・その後の同値割れ・最大の押しを格納する。
    """
    path = ORIGINAL["observe"](trade,records)
    assert path["観測最大損益円"]==trade["max_unrealized_net"] and path["観測最小損益円"]==trade["min_unrealized_net"]
    part = records[trade["entry_index"]:trade["exit_index"]+1]
    quotes = part[part["normal"]==1]
    side = trade["side"]
    signed = (quotes["bid" if side==0 else "ask"]-trade["entry_price"])*(1 if side==0 else -1)
    net_pt = signed-FEE/100
    assert trade["exit_horizon"]=="SESSION" and trade["status"] in LABELS and trade["net"] is not None
    assert int(round(net_pt[-1]*100))==trade["net"]
    width = trade["width"]
    result = {"場":trade["scene"],"方向":path["方向"],"建値":trade["entry_price"],"返済値":trade["exit_price"],"幅":width,
              "新規":path["新規日時"],"返済":path["返済時"],"新規原行":trade["entry_line"],"返済原行":trade["exit_line"],
              "最大":path["観測最大損益円"],"最大時":path["最大時"],"最大気配":path["最大時実側気配"],
              "決済":int(trade["net"]),"理由":LABELS[trade["status"]],"利益の変化":path["最大から返済まで円"],
              "最大から返済まで秒":path["最大から返済まで秒"],"到達":{}}
    levels = [(name,net_pt>0 if number==0 else net_pt>=number) for name,number in BASIS]
    levels.extend((f"順行{r:.2f}R",signed>=width*r) for r in RATIOS)
    for name,hit in levels:
        found = np.flatnonzero(hit)
        if not found.size:
            continue
        i = int(found[0])
        detail = {"初達秒":float(quotes["time"][i]-trade["entry_time"]),"元返済以前":i<len(quotes)-1}
        if i<len(quotes)-1:
            # ----------------------------------------
            # 終端の元注文を最優先し、その直前までの原行だけで動的な床への接触を調べる。
            pts = signed[i:-1]
            drawdown = np.maximum.accumulate(pts)-pts
            detail["最大押し比"] = float(drawdown.max()/width)
            detail["費用後同値付近まで後退"] = bool(np.any(net_pt[i+1:-1]<=0))
        result["到達"][name] = detail
    return result


def groups(book: list,dates: list) -> list:
    """
    機能：診断に使う方向・期間・入口幅の群を作る。
    引数：book（list）は元口座の建玉、dates（list）は全取引日。
    返り値：list。群名と対象建玉の組。群間で重なるため合算しない。
    """
    sub = [("全体",book),("買い",[r for r in book if r["方向"]=="買い"]),("売り",[r for r in book if r["方向"]=="売り"])]
    for name,period in (("前24日",dates[:24]),("後21日",dates[24:])):
        sub.append((name,[r for r in book if r["場"] in period]))
    for width in sorted({r["幅"] for r in book}):
        sub.append((f"R={width}pt",[r for r in book if r["幅"]==width]))
    return sub


def reasons(rows: list) -> str:
    """
    機能：選んだ経路について実際の利確・損切・場末決済件数をまとめる。
    引数：rows（list）は日経199_02の建玉記録。
    返り値：str。利確・損切・場末の順に表示する件数。
    """
    counts = Counter(r["理由"] for r in rows)
    return " / ".join(str(counts[k]) for k in ("利確","損切","場末"))


def comparison(books: dict,dates: list) -> list:
    """
    機能：固定IFDがどの順行を失い、どの勝ちに押し戻しへの耐性が必要だったかを一覧化する。
    引数：books（dict）はI20・I30の経路記録、dates（list）は対象デイ。
    返り値：list。診断資料のMarkdown各行。
    """
    out = ["# 順行してから赤字になった取引と、押し戻しを経て利確した取引","",
           "2026-11-22。日経199_02の開始20分待機（I20）と30分待機（I30）の固定利確・固定損切を用いた。"
           "45デイで各133建玉。最長は15:30までで、建玉ごとの時間上限なし。"
           "新規から決済まで、買いはBid・売りはAskでその場で清算できる金額を再評価した。"
           "mini換算1枚、1pt＝100円、往復1,077円を新規時から控除。"
           "同じ入口の両口座に共通する建玉もあるため、件数を足して標本数を増やさない。","",
           "## 最大含み益と実際の決済","",
           "「すべての初達」は元の決済原行で初めて到達した場合も含む。"
           "「決済前初達」はそれ以前の原行で到達し、保護注文を出す時間順の余地があった件数。"
           "費用後ptは評価円額÷100。R比の行は固定両注文と同じ費用前の順行幅÷R。"
           "閾値ごとの母数は重なる。赤字件数と確定損失額はすべての初達に対して集計した。","",
           "|待機|到達した水準|すべての初達|決済前初達|最終利確 / 損切 / 場末|最終赤字|その確定損失（円）|",
           "|---|---|---:|---:|---:|---:|---:|"]
    thresholds = [name for name,_ in BASIS]+[f"順行{r:.2f}R" for r in RATIOS]
    for code,book in books.items():
        for name in thresholds:
            reached = [r for r in book if name in r["到達"]]
            before = sum(r["到達"][name]["元返済以前"] for r in reached)
            lost = [r for r in reached if r["決済"]<0]
            out.append(f"|{code}|{name}|{len(reached)}|{before}|{reasons(reached)}|{len(lost)}|{-sum(r['決済'] for r in lost):,}|")
    # ----------------------------------------
    out += ["","## 早い順行は、そのまま元利確に達したか","",
            "元決済前に0.50Rに達した建玉だけを用い、その時点までの所要時間を分ける。"
            "件数は元IFDでの最終結果。将来の完走・時間切れ・利確が分かる時点には使えない。","",
            "|待機|初達の時期|建玉|利確 / 損切 / 場末|赤字|赤字額（円）|","|---|---|---:|---:|---:|---:|"]
    for code,book in books.items():
        hits = [(r,r["到達"]["順行0.50R"]["初達秒"]) for r in book if r["到達"].get("順行0.50R",{}).get("元返済以前")]
        for band,a,b in (("5分以内",-1,300),("5分超15分以内",300,900),("15分超",900,np.inf)):
            chosen = [r for r,s in hits if a<s<=b]
            lost = [r for r in chosen if r["決済"]<0]
            out.append(f"|{code}|{band}|{len(chosen)}|{reasons(chosen)}|{len(lost)}|{-sum(r['決済'] for r in lost):,}|")
    # ----------------------------------------
    out += ["","## 保護床に触れたあとで元利確まで戻れた件数","",
            "元の決済行より先に水準へ到達した建玉から、そこまでの評価益を後で大きく戻した建玉を数えた。"
            "「費用後同値」は順行側に往復費用10.77ptを上乗せした実質の建値。"
            "「ピークからの押し」は水準への初達後に観測した順行ピークからの逆行で測り、少なくとも次の原行以降で判定。"
            "元の決済行は接触判定から除く。各床を単独の条件として比べ、その床での損益・約定・枠解放はこの表には含めない。","",
            "|待機|初達した水準|初達後の後退|戻した建玉|のちに利確 / 損切 / 場末|最終黒字|最終赤字|",
            "|---|---|---|---:|---:|---:|---:|"]
    for code,book in books.items():
        for ratio in (.25,.50,.75):
            name = f"順行{ratio:.2f}R"
            reached = [(r,r["到達"][name]) for r in book if r["到達"].get(name,{}).get("元返済以前")]
            for desc,ret in (("費用後同値まで",None),("ピークから0.25R以上",.25),("ピークから0.50R以上",.5)):
                chosen = [r for r,o in reached if (o["費用後同値付近まで後退"] if ret is None else o["最大押し比"]>=ret)]
                out.append(f"|{code}|{name}|{desc}|{len(chosen)}|{reasons(chosen)}|"
                           f"{sum(r['決済']>0 for r in chosen)}|{sum(r['決済']<0 for r in chosen)}|")
    # ----------------------------------------
    out += ["","## 利益後赤字はどこに集中したか","",
            "『利益後赤字』は費用後の含み益を一度でも観測し、最終的に赤字だった建玉。"
            "その確定損失は決済時の赤字額。最大評価益からの下落は別の量。方向・期間・幅はそれぞれ全体の別集計。","",
            "|待機|範囲|全建玉|利益後赤字|損切 / 場末|確定損失（円）|ピークから決済への下落（円）|赤字例のピーク中央値（円）|",
            "|---|---|---:|---:|---:|---:|---:|---:|"]
    for code,book in books.items():
        for group,subset in groups(book,dates):
            losses = [r for r in subset if r["最大"]>0 and r["決済"]<0]
            counts = Counter(r["理由"] for r in losses)
            center = f"{median(r['最大'] for r in losses):,.0f}" if losses else "―"
            out.append(f"|{code}|{group}|{len(subset)}|{len(losses)}|{counts['損切']} / {counts['場末']}|"
                       f"{-sum(r['決済'] for r in losses):,}|{sum(r['利益の変化'] for r in losses):,}|{center}|")
    # ----------------------------------------
    out += ["","## 利益を大きく返した日時","",
            "各口座の『利益後赤字』を最大評価益から元決済までの下落額順に先頭3件表示する。日時は日本時間。","",
            "|待機|取得|方向・建値|R|ピーク時刻と返済側気配|費用後ピーク（円）|元決済時刻と価格|元決済（円）|下落額（円）|",
            "|---|---|---|---:|---|---:|---|---:|---:|"]
    for code,book in books.items():
        losses = sorted((r for r in book if r["最大"]>0 and r["決済"]<0),key=lambda r:-r["利益の変化"])
        for r in losses[:3]:
            out.append(f"|{code}|{r['新規'][:19]}|{r['方向']} {r['建値']:,.0f}|{r['幅']}|"
                       f"{r['最大時'][11:19]} {r['最大気配']:,.0f}|{r['最大']:,}|{r['返済'][11:19]} {r['返済値']:,.0f}（{r['理由']}）|"
                       f"{r['決済']:,}|{r['利益の変化']:,}|")
    out += ["","利益後赤字の確定損失が大きかった日は次の通り。",""]
    for code,book in books.items():
        daily = Counter()
        for r in book:
            if r["最大"]>0 and r["決済"]<0:
                daily[r["場"][:10]] += -r["決済"]
        tops = daily.most_common(3)
        out.append(f"- {code}では{len(daily)}日に発生。上位3日（"+ "、".join(f"{d} {v:,}円" for d,v in tops)
                   +f"）が全額の{sum(v for _,v in tops)/daily.total():.1%}。")
    return out


def main() -> None:
    """
    機能：両待機の元帳から該当する板を再読し、極値・日付等を照合して診断結果を作成する。
    引数：なし。試行222の口座元帳と指紋付き正常気配索引を使う。
    返り値：None。試行へ診断表、作業領域へ個別経路の要約と入力の指紋を保存する。
    """
    source = ROOT/"work/222境界照合/口座元帳.json"
    payload = json.loads(source.read_bytes())
    dates = payload["対象場"]
    files = ORIGINAL["archives"]()
    samples = {"I20":[],"I30":[]}
    for day in dates:
        rows = ORIGINAL["load_records"](*files[day])
        cache = {}
        for code,book in samples.items():
            for t in (r for r in payload["口座再生"][code] if r["scene"]==day):
                key = (t["entry_line"],t["exit_line"],t["side"],t["entry_price"],t["exit_price"],t["width"])
                if key not in cache:
                    cache[key] = sample(t,rows)
                book.append(cache[key])
    assert len(dates)==45 and all(len(book)==133 for book in samples.values())
    assert [sum(r["決済"] for r in b) for b in samples.values()]==[968759,917759]
    out = ROOT/"work/223建玉診断"
    out.mkdir(parents=True,exist_ok=True)
    data = {"元帳SHA256":sha256(source.read_bytes()).hexdigest(),"原行索引SHA256":{day:files[day][1] for day in dates},"建玉":samples}
    (out/"経路診断.json").write_text(json.dumps(data,ensure_ascii=False,allow_nan=False),encoding="utf8")
    (HERE/"診断結果.md").write_text("\n".join(comparison(samples,dates))+"\n",encoding="utf8")


if __name__=="__main__":
    main()
