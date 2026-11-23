"""入口だけの変更で元の建玉、直接判定、後続の取得、期間ごとの損益がどう変わるかを検算する。"""
import json
from pathlib import Path
import runpy

HERE = Path(__file__).resolve().parent
REPLAY = runpy.run_path(str(HERE/"順行入口を再生する.py"))
WORK = REPLAY["WORK"]
BASE = REPLAY["BASE"]
OLD = runpy.run_path(str(next(REPLAY["STUDY"].glob("00219_*/出口を集計する.py"))))
TARGET = "2026-10-08_Day"


def split(base: list, changed: list, hits: dict, code: str) -> dict:
    """
    機能：共通取得の損益一致、条件が直接当たった元の取得、後続の枠交代の寄与を分ける。
    引数：base・changed（list）は同期間の二口座、hits（dict）は日別変更判断行、code（str）は入口。
    返り値：dict。各群の実取得数・費用後利益／損失／収支。
    """
    original = {OLD["key"](t):t for t in base}
    new = {OLD["key"](t):t for t in changed}
    common = original.keys() & new.keys()
    assert all((original[k]["net"],original[k]["exit_line"])==(new[k]["net"],new[k]["exit_line"]) for k in common)
    groups = {"共通":[original[k] for k in common],"元直接":[],"元枠交代":[],"新反転":[],"新後続":[]}
    for k in original.keys()-new.keys():
        r = original[k]
        directly = r["request_line"] in hits[r["scene"]][code]
        groups["元直接" if directly else "元枠交代"].append(r)
    for k in new.keys()-original.keys():
        r = new[k]
        reversed_entry = code=="E4" and r["request_line"] in hits[r["scene"]][code]
        groups["新反転" if reversed_entry else "新後続"].append(r)
    return {key:OLD["money"](rows) for key,rows in groups.items()}


def main() -> None:
    """
    機能：全候補について期間・赤字日の質・上位改善日を外した差・取得の入れ替わりを計算する。
    引数：なし。入口再生の作業元帳を使用。返り値：None。Markdownの結果表と詳細JSON。
    """
    payload = json.loads((WORK/"口座元帳.json").read_bytes())
    hits = json.loads((WORK/"当時の変更判断原行.json").read_bytes())
    dates,books = payload["対象場"],payload["口座再生"]
    out = {}
    lines = ["# 入口だけを変更した結果","","日経225mini 1枚換算、手数料・想定滑り控除後の円。差は同じ待機と出口のE0比。"
             "全日は2026-09-21〜11-20の45デイ、損失は絶対額。「利益0赤字」は当日すべての建玉で正の実現利益が一度もなく日次が赤字。"
             "保有中の正の含み益とは異なる。最大改善日除外は当日だけ基準と候補の両方から除外した収支差。"]
    for wait in (20,30):
        for exit_ in ("RC","I"):
            ref = books[f"E0{exit_}{wait}"]
            before,base_sum = BASE["measures"](dates,ref,wait)
            lines += ["",f"## 開始{wait}分・"+("RC" if exit_=="RC" else "単純IFD"),"",
                      "|入口|建玉／参加日|総利益|総損失|収支|損失差|赤字日／利益0赤字|日末DD|保有率|建玉／日中央値|10/8収支|10/8除外収支差|前24／後21日収支差|最大改善日除外収支差|",
                      "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
            for c in REPLAY["CODES"]:
                name = f"{c}{exit_}{wait}"
                book = books[name]
                after,s = BASE["measures"](dates,book,wait)
                assert s["未知"]==0
                delta = {a["場"]:a["収支"]-b["収支"] for a,b in zip(after,before,strict=True)}
                red_only = [d["場"] for d in after if d["利益"]==0 and d["損失"]>0]
                p = sum(delta[d] for d in dates[:24])
                q = sum(delta[d] for d in dates[24:])
                change = sum(delta.values())
                assert change==s["収支"]-base_sum["収支"]
                pos = max(delta,key=delta.get)
                groups = split(ref,book,hits,c)
                assert groups["新後続"]["収支"]+groups["新反転"]["収支"]-groups["元直接"]["収支"]-groups["元枠交代"]["収支"]==change
                today = next(d for d in after if d["場"]==TARGET)
                out[name] = {"全日":s,"入替":groups,"利益ゼロ赤字日":red_only,"前24日収支差":p,"後21日収支差":q,
                             "改善最大":pos,"最大改善日除外差":change-delta[pos],"日別":after,
                             "日別収支差":delta,"10月8日":today,"10月8日除外差":change-delta[TARGET]}
                fields = [c,f"{s['取得']}／{s['参加場']}",*[f"{s[k]:,.0f}" for k in ("利益","損失","収支")],
                          f"{s['損失']-base_sum['損失']:+,.0f}",f"{s['赤字場']}／{len(red_only)}",
                          f"{s['場末DD既知']:,.0f}",f"{s['保有率']:.2%}",f"{s['建玉中央値下限']:,.0f}／{s['場中央値下限']:,.0f}",
                          f"{today['収支']:+,.0f}",f"{change-delta[TARGET]:+,.0f}",f"{p:+,.0f}／{q:+,.0f}",f"{change-delta[pos]:+,.0f}"]
                lines.append("|"+"|".join(fields)+"|")
    lines += ["","## 入口変更が損益に反映した経路（20分、RC）","",
              "元直接は変更条件が成立した・元口座にだけ存在する建玉。元枠交代は変更条件のない元建玉で、他の建玉・予約が先に成立したため外れたもの。"
              "新反転は実際に逆向きに入った新口座の実現損益。新後続は空いた後の要求から取得した建玉。"
              "各セルは件数・費用後収支。共通取得については全件でRCの返済行と収支の一致を検査した。","",
              "|入口|共通|元直接|元枠交代|新反転|新後続|","|---|---:|---:|---:|---:|---:|"]
    for code in REPLAY["CODES"]:
        groups = out[code+"RC20"]["入替"]
        lines.append("|"+code+"|"+"|".join(f"{v['件数']}件・{v['収支']:+,}円" for v in groups.values())+"|")
    (HERE/"全口座の比較.md").write_text("\n".join(lines)+"\n",encoding="utf8")
    (WORK/"入口比較.json").write_text(json.dumps(out,ensure_ascii=False,allow_nan=False),encoding="utf8")


if __name__=="__main__":
    main()
