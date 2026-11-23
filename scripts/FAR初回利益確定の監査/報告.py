"""97の成功済み保存証拠から実現損益の報告を生成し、原計画をbytes復元する。"""

import argparse
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
CONDITION_SHA = "f7421f26a306eb0a49387b9dfa2104621350fac5c6ceba035a84bb3661d42c05"
SAVED_SHA = "09e93302080a740d3c2add85297f9530c32f6235dabe5f08e674551b556b3208"
BEGIN = b"<!-- REPORT97 PLAN BEGIN -->\n"
END = b"<!-- REPORT97 PLAN END -->\n"


def need(ok, message):
    """
    機能: 未完又は破損した保存証拠の生成を停止する。
    引数: ok(bool)、message(str)は検査結果と理由。
    返り値: None。不成立はValueError。
    """
    if not ok:
        raise ValueError(message)


def sha(body):
    """
    機能: 保存bytesの指紋を取得する。
    引数: body(bytes)は入力又は生成本文。
    返り値: strはSHA256。
    """
    return hashlib.sha256(body).hexdigest()


def load(body):
    """
    機能: 半円を丸めずJSONを読む。
    引数: body(bytes)は保存JSON。
    返り値: dictはDecimal小数を保持。非有限数は拒否する。
    """
    return json.loads(body.decode("utf-8-sig"),parse_float=Decimal,
                      parse_constant=lambda x:(_ for _ in ()).throw(ValueError("非有限数:"+x)))


def canonical(value):
    """
    機能: 文字列/整数だけの指紋辞書を安定bytes化する。
    引数: value(dict)は証拠の短い辞書。
    返り値: bytesはUTF-8 JSON。
    """
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",",":"),allow_nan=False).encode("utf-8")


def money(value):
    """
    機能: 円額を半円のまま読みやすく整形する。
    引数: value(int|Decimal|None)は既存結果の値。
    返り値: strはnull又は数値。新しい損益を推計しない。
    """
    if value is None:
        return "未定義"
    value = Decimal(value)
    return f"{value:,.0f}" if value==value.to_integral_value() else f"{value:,.1f}"


def ratio(value):
    """
    機能: PFを表示桁だけ丸める。
    引数: value(int|Decimal|None)は結果正本のPF。
    返り値: strは小数3桁又は分母0の説明。
    """
    return "未定義" if value is None else f"{Decimal(value):.3f}"


def original(body, expected):
    """
    機能: 初回計画又は実行後markerから原計画bytesを復元する。
    引数: body(bytes)、expected(str)は入力文書と市場前の固定SHA。
    返り値: bytesは原計画そのもの。marker欠落/多重/本文改変を拒否する。
    """
    if BEGIN not in body and END not in body:
        need(sha(body)==expected,"原計画SHA差又はmarker欠落")
        return body
    need(body.count(BEGIN)==body.count(END)==1,"REPORT97 PLAN marker集合")
    start = body.index(BEGIN)+len(BEGIN)
    end = body.index(END)
    need(end>start and body[end-1:end]==b"\n","原計画separator欠落")
    restored = body[start:end-1]
    need(sha(restored)==expected,"marker内の原計画SHA差")
    return restored


def table_contract(body):
    """
    機能: 原版5の55×9、36設定、16評価の集合を確認する。
    引数: body(bytes)は復元済み設定計画。
    返り値: dictはR番号から固定Key/入口/出口への対応。
    """
    lines = body.decode("utf-8").splitlines()
    rows = [line.split("|")[1:-1] for line in lines if re.match(r"^\| [ICPVBXME]\d{2} \|",line)]
    need(len(rows)==55 and all(len(row)==11 for row in rows),"版5の55手法×9尺度")
    ids = [re.match(r"^\| ([SNT]\d{2}) \|",line).group(1) for line in lines if re.match(r"^\| [SNT]\d{2} \|",line)]
    expected = {f"S{i:02}" for i in range(1,11)}|{f"N{i:02}" for i in range(1,9)}|{f"T{i:02}" for i in range(1,19)}
    need(len(ids)==36 and set(ids)==expected,"固定36設定")
    evaluations = {}
    for line in lines:
        if re.match(r"^\| R\d{2} \|",line):
            cells = [part.strip() for part in line.split("|")[1:-1]]
            need(cells[0] not in evaluations and len(cells)==11,"評価表の一意/列数")
            evaluations[cells[0]]={"入口":cells[1],"出口":cells[2],"key":cells[3],"cost":int(cells[4]),"delay":int(cells[5])}
    need(set(evaluations)=={f"R{i:02}" for i in range(1,17)},"固定16評価")
    return evaluations


def validate(result, audit, viewer, condition, evaluations, result_sha, audit_sha):
    """
    機能: 成功54場/864会計/Viewerと実現分解の算術を保存正本へ結ぶ。
    引数: result/audit/viewer/condition/evaluations(dict)、result_sha/audit_sha(str)は明示入力。
    返り値: dictは8比較の合計。金融や純技法の再計算はしない。
    """
    need(result["試行"]==97 and result["成功"] is True and result["scope"]=="正式"
         and result["場数"]==54 and result["Actor数"]==16 and result["会計数"]==864,"保存54/864の成功が必要")
    keys = {r["key"] for r in evaluations.values()}
    need(len(keys)==16 and set(result["集計"])==set(result["実現診断"])==set(result["Actor設定"])==keys,"全16結果集合")
    need(result["集計コードSHA256"]==SAVED_SHA and result["条件SHA256"]==CONDITION_SHA,"停止保存器/条件の結合")
    need(result["独立Tape金融監査SHA256"]==audit_sha,"保存会計と全経路監査の結合")
    need(audit["成功"] is True and audit["stage"]=="full54" and audit["場数"]==54 and audit["会計数"]==864
         and audit["照合項目数"]==2436210498 and audit["不一致数"]==0 and audit["入力コード前後不変"] is True,"独立全54/2,436,210,498の成功が必要")
    need(viewer["試行"]==97 and viewer["成功"] is True and viewer["予定資源"]==viewer["完了資源"]==864
         and viewer["全資源検証完了"] is True and viewer["不一致数"]==0 and not viewer["APIエラー"]
         and viewer["入力不変"] is True,"Viewer864資源の完了が必要")
    need(viewer["入力SHA256前"]==viewer["入力SHA256後"] and viewer["結果SHA256"]==result_sha,"Viewer結果本文と入力前後の結合")
    need(any(h==result_sha for h in viewer["入力SHA256前"].values()),"Viewer入力に同じ結果SHA")
    controls = result["P0旧96全文対照"]
    need(len(controls)==54 and len({r["session"] for r in controls})==54
         and all(r["対照会計"]==8 and r["除外"]==[] for r in controls),"P0対96全432/除外0")
    need(result["未実施"]["原板/CSV/Go再生"]==0 and result["未実施"]["未参加/決済後仮想利益"]==0,"再生成/仮想評価なし")
    need(condition["試行"]==97 and condition["汎用表版"]==5 and condition["市場損益を開く前の固定"] is True,"97固定条件")
    sessions = {r["session"] for r in controls}
    audit_rows={r["session"]:r for r in audit["details"]}
    need(len(audit["details"])==54 and set(audit_rows)==sessions,"独立監査54場集合")
    for session in sessions:
        native={p:h for p,h in result["入力依存SHA256前後"].items() if Path(p).name==session+".json"}
        row=audit_rows[session]
        need(len(native)==1 and row["成功"] is True and row["不一致数"]==0 and row["入力前後不変"] is True,"Native/独立監査の場別完了")
        p,h=next(iter(native.items()))
        need(row["入力SHA256前後"].get(p)==h,"NativeFingerprintと独立監査の同じ本文")
    need(len(result["場別"])==864 and {(r["session"],r["key"]) for r in result["場別"]}=={(s,k) for s in sessions for k in keys},"場別864集合")
    for row in evaluations.values():
        key = row["key"]; r,d,c = result["集計"][key],result["実現診断"][key],result["Actor設定"][key]
        need(c["入口"]==row["入口"] and c["出口"]==row["出口"] and c["slip_pts"]==row["cost"] and c["delay_seconds"]==row["delay"],"設定IDとActor対応")
        need(r["net_yen"]==r["gross_yen"]-r["fee_yen"]-r["slip_yen"]==d["純額円"]==d["正額円"]+d["負額円"],"実現額/正負/費用")
        need(r["positions"]==d["玉数"] and r["entry_quantity"]==r["close_quantity"]==d["新規枚数"],"実玉と数量分母")
        need(all(r[n]==0 for n in ("open_buy","open_sell","pending_buy","pending_sell","open_entry_costs_yen")),"場内完結")
        for prefix,name in (("unit","u"),("whole","W")):
            need(r[prefix+"_positive_positions"]==d[name+"正益玉"] and r[prefix+"_positive_closed_negative"]==d[name+"正益後最終赤字玉"],"u/W分母")
            need(d[name+"正益後最終赤字額円"]+d[name+"正益未観測赤字額円"]==d["負額円"],"正益前後の実損失分解")
        for name in ("positions","entry_quantity","gross_yen","fee_yen","slip_yen","net_yen"):
            section = "counts" if name=="positions" else "totals"
            need(sum(rw[section][name] for rw in result["場別"] if rw["key"]==key)==r[name],"54場と集計合計:"+name)
    comparisons = {}
    for gate in ("", "AB_"):
        for cost in (0,5):
            for delay in (0,1):
                old = gate+f"B5Q_P0_C{cost}_D{delay}"; new="H0_"+old; name=new+"対"+old
                rows = result["P0とH0の同実入口と実参加差"][name]
                need(len(rows)==54 and {r["session"] for r in rows}==sessions,"同Source比較54場")
                numeric = [n for n in rows[0] if n not in ("session","限定")]
                c = {n:sum(r[n] for r in rows) for n in numeric}
                need(c["同Source出生"]==c["同実入口"]+c["取得変更"],"同出生の分解")
                need(c["全差円"]==c["同実入口差円"]+c["取得変更差円"]-c["Aのみ円"]+c["Bのみ円"]
                     ==result["集計"][new]["net_yen"]-result["集計"][old]["net_yen"],"同実入口/参加差の全実現額")
                need(c["同Source出生"]+c["Aのみ"]==result["集計"][old]["positions"]
                     and c["同Source出生"]+c["Bのみ"]==result["集計"][new]["positions"],"実在出生の分母")
                comparisons[name]=c
    need(len(result["P0とH0の同実入口と実参加差"])==8,"8実現比較だけ")
    return comparisons


def render(result, evaluations, comparisons, audit, viewer):
    """
    機能: 全16実現成績・uW損失・DD・同実入口差を日本語へ整形する。
    引数: result/evaluations/comparisons/audit/viewer(dict)は成功済み保存値。
    返り値: strは実行後本文。後知識の仮想利益や回収率を作らない。
    """
    rows = result["集計"]
    g0a,g0b = (rows[k]["net_yen"] for k in ("B5Q_P0_C0_D0","H0_B5Q_P0_C0_D0"))
    aba,abb = (rows[k]["net_yen"] for k in ("AB_B5Q_P0_C0_D0","H0_AB_B5Q_P0_C0_D0"))
    ab=rows["AB_B5Q_P0_C0_D0"]
    adverse=[]
    for label,old in (("G0 C0/D1","B5Q_P0_C0_D1"),("G0 C5/D0","B5Q_P0_C5_D0"),("G0 C5/D1","B5Q_P0_C5_D1"),
                      ("AB C5/D0","AB_B5Q_P0_C5_D0"),("AB C5/D1","AB_B5Q_P0_C5_D1")):
        a,b=rows[old]["net_yen"],rows["H0_"+old]["net_yen"]
        adverse.append(f"{label}は{money(a)}→{money(b)}円")
    lines = ["2026-11-08、既使用54場の市場再生・保存会計・独立Tape監査・Viewer照合を完了。下部の原計画内の『未実行』は固定当時の記述で、現在結果は本欄を正とする。", "",
             f"主C0/D0のG0はP0 {money(g0a)}円→H0 {money(g0b)}円（差{money(g0b-g0a)}円）で、両方赤字。複合ABは{money(aba)}円→{money(abb)}円（差{money(abb-aba)}円）。主ABは同じ{ab['positions']}市場出生・計{ab['entry_quantity']}枚であり、P0/H0・費用・遅延の反復を独立標本に数えず、安定性は未証明。", "",
             "、".join(adverse)+"。初回正益の確定が全条件の純額を改善するとの結論にはならない。", "",
             "主C0はmini1枚1片道38.5円税込のみ、C5は追加5pt/片道の未実測感度。各費用/遅延は出口と参加が変わり得る別動的運転。ラージBBOのspreadは実粗額に含み二重加算しない。", "",
             "## 全16評価の実現額", "", "|ID・入口/出口/C/D|玉/枚|粗額円|fee円|slip円|純額円|正額/負額円|PF|取引あり場/赤字場|", "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for rid,e in evaluations.items():
        r,d=rows[e["key"]],result["実現診断"][e["key"]]
        lines.append(f"|{rid} {e['入口']}/{e['出口']}/C{e['cost']}/D{e['delay']}|{r['positions']}/{r['entry_quantity']}|{money(r['gross_yen'])}|{money(r['fee_yen'])}|{money(r['slip_yen'])}|{money(r['net_yen'])}|{money(d['正額円'])}/{money(d['負額円'])}|{ratio(d['PF'])}|{r['active_sessions']}/54・{r['negative_sessions']}/54|")
    lines += ["", "PF＝正額÷負額の絶対値。正負は実在玉の最終費用後額。無取引場を赤字場へ数えない。", "",
              "## 正益前後の実損失とDD", "", "|ID|u後赤字玉/u正益玉・損失円|u未観測赤字玉・損失円|W後赤字玉/W正益玉・損失円|W未観測赤字玉・損失円|場内最大DD円|場を連結したDD円|", "|---|---:|---:|---:|---:|---:|---:|"]
    for rid,e in evaluations.items():
        d=result["実現診断"][e["key"]]
        lines.append(f"|{rid}|{d['u正益後最終赤字玉']}/{d['u正益玉']}・{money(d['u正益後最終赤字額円'])}|{d['u正益未観測赤字玉']}・{money(d['u正益未観測赤字額円'])}|{d['W正益後最終赤字玉']}/{d['W正益玉']}・{money(d['W正益後最終赤字額円'])}|{d['W正益未観測赤字玉']}・{money(d['W正益未観測赤字額円'])}|{money(d['場内最大DD円'])}|{money(d['保存極値を連結した最大DD円'])}|")
    lines += ["", "uは当時の残玉単価の往復費用後評価、Wはその玉の実確定額＋残玉評価。H0起動条件はstrict u>0であり、Wだけ正又はu=0では起動しない。損失額は旗以後の値幅でなく、その分類に属する実玉の最終赤字額。DDは固定Tapeの全金融独立監査で確かめた口座MTM極値を使い、連結DDは場順の保存極値/終値から算出。", "",
              "## 同実入口の出口差と実参加差", "",
              "実在Sourceのmethod＋signal_id（出生ID）を先に一致させ、その中で要求時刻、売買、実取得時刻・Index・物理行、取得価格、初期量が全て一致したものだけを同実入口とする。数量/回数が等しいだけでは同入口としない。", "",
              "|入口/C/D|同実入口/取得変更/P0のみ/H0のみ|同実入口の出口差円|取得変更差円|P0のみ実現額円|H0のみ実現額円|全差円|", "|---|---:|---:|---:|---:|---:|---:|"]
    for name,c in comparisons.items():
        old=name.split("対",1)[1]; key=next(e for e in evaluations.values() if e["key"]==old)
        lines.append(f"|{key['入口']}/C{key['cost']}/D{key['delay']}|{c['同実入口']}/{c['取得変更']}/{c['Aのみ']}/{c['Bのみ']}|{money(c['同実入口差円'])}|{money(c['取得変更差円'])}|{money(c['Aのみ円'])}|{money(c['Bのみ円'])}|{money(c['全差円'])}|")
    lines += ["", "全差＝同実入口差＋取得変更差−P0のみの実現額＋H0のみの実現額。この標本では全8比較で取得変更/片側参加0のため差は同実入口の出口差。G0とABの違いはSource選別も含むため指標単独や出口単独の効果へ帰属させない。", "",
              "## 証拠と限界", "",
              f"P0の8×54＝432会計は固定96へ除外0全文一致。独立Pythonは全16×54＝864会計、{money(audit['照合項目数'])}照合で差0。Viewerは864資源、{money(viewer['照合項目数'])}照合で差0。Source/Features/チャートの再生成はfalseで、固定96からのScalar11/公開通知/確定3・15分文脈を再用した。新しい原板数値生成の全面証明と混同しない。", "",
              "期間は2026-09-21〜10-27の日中27/夜間27、全て既使用。未使用期間の安定性、実mini板の流動性、5ptの実測滑り、真の両市場受信順序は未確認。CurrentPriceTimeは価格項目時計で、同時刻TOPIX先行は再生規則。Source残量は現在出来高でも攻撃側約定量でもない。", "",
              "未参加/決済後の仮想利益、理想ピーク、回収率は算出0回（値は未算出）。実現取引の費用後額/正負/PF/uW損失/DD/回数を評価する。H0は要求価格での利益保証ではなく、予約済み部分や後続気配悪化で赤字を残し得る。資本金ROIは算出しない。", "",
              "[結果正本](成果物/結果.json)・[保存成績](成果物/結果.md)・[Viewer一覧](成果物/一覧.resources.json)・[金融完了](金融完了.json)・[独立照合](独立照合.json)・[Viewer照合](Viewer照合.json)・[条件](条件.json)・[検証計画](検証計画.md)・[再現手順](再現手順.md)。", ""]
    return "\n".join(lines)


def prepare(paths):
    """
    機能: 成功証拠を明示Pathで読み、原計画と実行後2文書を生成可能にする。
    引数: paths(dict[str,Path])は7入力。
    返り値: tupleは2生成bytes、安定内容指紋、入力前指紋。出力を書き込まない。
    """
    raw={name:path.read_bytes() for name,path in paths.items()}
    before={str(paths[name].resolve()):sha(body) for name,body in raw.items()}
    condition=load(raw["condition"])
    need(sha(raw["condition"])==CONDITION_SHA,"固定97条件SHA")
    need(sha(raw["plan"])==condition["計画SHA256"],"検証計画の固定SHA")
    readme=original(raw["readme"],condition["README計画SHA256"])
    settings=original(raw["settings"],condition["設定表計画SHA256"])
    evaluations=table_contract(settings)
    dependencies={str((ROOT/n).resolve()):h for n,h in condition["コードSHA256"].items()}
    need(len(dependencies)==155 and all(sha(Path(p).read_bytes())==h for p,h in dependencies.items()),"固定155コード不変")
    result,audit,viewer=(load(raw[name]) for name in ("result","audit","viewer"))
    comparisons=validate(result,audit,viewer,condition,evaluations,sha(raw["result"]),sha(raw["audit"]))
    body=render(result,evaluations,comparisons,audit,viewer).encode("utf-8")
    generated={"README.md":("# 00097：初回費用後利益の全量確定・実行結果\n\n").encode("utf-8")+body+("\n## 固定した原計画\n\n").encode("utf-8")+BEGIN+readme+b"\n"+END,
               "設定と結果.md":("# 97：設定と結果（全54場実行後）\n\n").encode("utf-8")+body+("\n## 固定した設定計画・版5\n\n").encode("utf-8")+BEGIN+settings+b"\n"+END}
    content={name:sha(raw[name]) for name in ("result","audit","viewer","condition","plan")}
    content.update({"readme_plan":sha(readme),"settings_plan":sha(settings),"報告コード":sha(Path(__file__).read_bytes())})
    need(original(generated["README.md"],condition["README計画SHA256"])==readme
         and original(generated["設定と結果.md"],condition["設定表計画SHA256"])==settings,"生成後の原計画bytes復元")
    before.update(dependencies)
    before.update(result["入力依存SHA256前後"])
    before[str(Path(__file__).resolve())]=content["報告コード"]
    need(all(sha(Path(p).read_bytes())==h for p,h in before.items()),"報告生成前後の入力差")
    return generated,content,before


def main():
    """
    機能: 成功済み7保存証拠から新規報告を生成又は既生成を照合する。
    引数: --result/--audit/--viewer/--condition/--plan/--readme/--settings/--out(Path)、--run又は--check。
    返り値: None。未完Viewer・計画改変・出力差は非0。原板/API/金融を呼ばない。
    """
    parser=argparse.ArgumentParser(description=__doc__)
    mode=parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--run",action="store_true");mode.add_argument("--check",action="store_true")
    names=("result","audit","viewer","condition","plan","readme","settings")
    for name in names+("out",):parser.add_argument("--"+name,type=Path,required=True)
    args=parser.parse_args();paths={n:getattr(args,n) for n in names}
    generated,content,before=prepare(paths)
    outputs={n:sha(b) for n,b in generated.items()}
    if args.run:
        need(not args.out.exists(),"新規報告dirのみ")
        args.out.mkdir(parents=True)
        for name,body in generated.items():(args.out/name).write_bytes(body)
        proof={"試行":97,"成功":True,"入力内容SHA256":content,"観測入力SHA256前後":before,
               "出力SHA256":outputs,"原計画復元":True,"版5":{"手法":55,"尺度":9,"設定":36,"評価":16},
               "金融と純技法の再計算":False,"Source・チャート再生成":False,"原板/API/金融再生":0,
               "未参加/退出後仮想利益/回収率":"未算出・処理0回"}
        (args.out/"報告生成.json").write_text(json.dumps(proof,ensure_ascii=False,indent=2,allow_nan=False)+"\n",encoding="utf-8",newline="\n")
    else:
        proof=load((args.out/"報告生成.json").read_bytes())
        need(proof["成功"] is True and proof["入力内容SHA256"]==content and proof["出力SHA256"]==outputs,"報告証拠の内容差")
        for name,body in generated.items():need((args.out/name).read_bytes()==body,"生成文書差:"+name)
    need(all(sha(Path(p).read_bytes())==h for p,h in before.items()),"報告処理後の入力差")
    print(json.dumps({"成功":True,"mode":"run" if args.run else "check","原計画復元":True,"出力SHA256":outputs},ensure_ascii=False))


if __name__=="__main__":
    main()
