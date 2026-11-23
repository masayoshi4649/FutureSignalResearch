"""元の決済を固定し、新規方向および同じ週の別日の同時刻が損益に与える差を測る。"""
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
import runpy

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
ENGINE = runpy.run_path(str(next(HERE.parent.glob("00219_*/口座再生.py"))))
JST = timezone(timedelta(hours=9))
MODES = ["元","同秒最初","同原行の逆方向",*[f"同週内で{i}営業日ずらす" for i in range(1,5)]]


def observations() -> tuple:
    """
    機能：各元取得に同じ幅・期限を与え、日本時間の対応する原行で各対照の入口と出口を再計算する。
    引数：なし。試行216の元建玉と原板指紋を照合して読む。
    返り値：tuple。45日と、元取得ごとの方向別・日付移動別の対応記録。
    """
    source,finance = ENGINE["SOURCE"],ENGINE["FINANCE"]
    days,originals,_ = source["SUMMARY"]["sources"]("デイ")
    baseline = originals["216:日経199_02"]
    records = [{} for _ in baseline]
    indices,by_day,weeks = {},defaultdict(list),defaultdict(list)
    for _,_,_,manifest in source["parts"]():
        for scene in source["read"](manifest)["scenes"]:
            if scene["session"] in days:
                indices.setdefault(scene["session"],(manifest.parent,scene))
    for i,row in enumerate(baseline):
        by_day[row["scene"]].append((i,row))
    for day in days:
        weeks[date.fromisoformat(day[:10]).isocalendar()[:2]].append(day)
    assert len(baseline)==181 and len(weeks)==9 and all(len(w)==5 for w in weeks.values())
    # ----------------------------------------
    for week in weeks.values():
        for pos,day in enumerate(week):
            folder,scene = indices[day]
            index = finance["load_scene"](folder,scene)
            midnight = datetime.fromisoformat(day[:10]).replace(tzinfo=JST)
            cut = midnight.replace(hour=15,minute=30).timestamp()
            forced = finance["closing"](index,cut)
            for mode_i,mode in enumerate(MODES):
                offset = max(0,mode_i-2)
                original_day = week[(pos-offset)%5]
                for i,row in by_day[original_day]:
                    source_time = datetime.fromtimestamp(row["entry_time"],JST)
                    clock = datetime.combine(midnight.date(),source_time.timetz()).timestamp()
                    entry = row["entry_index"] if mode_i in (0,2) else index.first_normal(clock)
                    if indices[original_day][1]["contract"]!=scene["contract"]:
                        records[i][mode] = {"状態":"限月不一致","net":None}
                        continue
                    if entry<0 or not (clock<=index.times[entry]<=clock+30 and index.times[entry]<cut-60):
                        records[i][mode] = {"状態":"新規気配不足","net":None}
                        continue
                    side = 1-row["side"] if mode_i==2 else row["side"]
                    t = finance["settle"](index,entry,side,row["width"],row["horizon"],cut,forced,"NK225")
                    records[i][mode] = {"状態":"決済不明" if t["net"] is None else "確定",
                                        "net":t["net"], "先着":t["label"], "適用日":day}
                    if mode_i==0:
                        assert (t["net"],t["exit_line"])==(row["net"],row["exit_line"])
    return baseline,records


def main() -> None:
    """
    機能：対照ごと、および全対照が確定した共通集合で比較し、選抜に使わない診断表を作る。
    引数：なし。元取得の日本時間・方向に基づき期間別の数値も算出する。
    返り値：None。試行フォルダにMarkdown表、作業領域に対になった計算結果を出力する。
    """
    baseline,records = observations()
    common = [i for i,r in enumerate(records) if all(r[m]["net"] is not None for m in MODES)]
    lines = ["# 同じIFDで入口方向と日付を変えた場合","",
             "元の新規181件を個別に再生した。元と同原行の逆方向は買いAsk・売りBidも入れ替え、返済は逆側の正常気配。日付の対照は同じ暦週の5デイで循環し、元と同じJST時刻から30秒以内、同じ限月の最初の正常気配で建てた。方向・幅・期限・費用条件は元を継承した。週ごとの値動き、時間帯、選ばれた方向の偏りをある程度そろえている。","",
             f"全対照の新規・決済が確定した共通集合は{len(common)}／181件。円額は費用後のmini 1枚換算。「個別既知」は各対照で確定した分の合計。前後・買売は共通集合の元の取得日と元の売買方向による分類。","",
             "|適用|取得不可|決済不明|個別既知収支|共通集合の利益|共通集合の損失|共通集合の収支|前24日|後21日|元買い|元売り|",
             "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for mode in MODES:
        entries = [r[mode] for r in records]
        missing = sum(r["状態"] in ("新規気配不足","限月不一致") for r in entries)
        unknown = sum(r["状態"]=="決済不明" for r in entries)
        known = sum(r["net"] for r in entries if r["net"] is not None)
        net = [entries[i]["net"] for i in common]
        pre = sum(entries[i]["net"] for i in common if baseline[i]["scene"][:10]<="2026-10-22")
        buy = sum(entries[i]["net"] for i in common if baseline[i]["side"]==0)
        vals = [missing,unknown,known,sum(x for x in net if x>0),-sum(x for x in net if x<0),
                sum(net),pre,sum(net)-pre,buy,sum(net)-buy]
        lines.append("|"+mode+"|"+"|".join(f"{v:,.0f}" for v in vals)+"|")
    lines.extend(["","元の注文が取得できた時点を取り出した比較で、保有の重複や注文機会の入れ替わりを再生しない。移動先の技術条件が成立していることも要求しない。実売買候補や独立した未見期間の検定には使わない。"])
    (HERE/"入口方向と時刻の対照.md").write_text("\n".join(lines)+"\n",encoding="utf8")
    output = ROOT/"work"/"221集計"
    output.mkdir(parents=True,exist_ok=True)
    (output/"同時刻の対照.json").write_text(json.dumps(records,ensure_ascii=False,allow_nan=False),encoding="utf8")


if __name__=="__main__":
    main()
