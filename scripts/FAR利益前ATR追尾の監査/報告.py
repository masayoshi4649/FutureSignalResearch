"""98の成功済み保存証拠から実現額だけを報告し、元README/版5設定をbytes復元する。"""

import argparse
import importlib.util
import json
from pathlib import Path
import re
import sys


ROOT=Path(__file__).resolve().parents[2]
OLD_PATH=ROOT/"scripts/FAR初回利益確定の監査/報告.py"
OLD_SHA="0ddeae536cd7ac8db5aeb1e29baf4f9afe3c1334531fcb469b5119342619ae51"
CONDITION_SHA="719cee62e6c1be8bfccb81b87ae5f82412776433c00faa9272f16cb3302947cb"
PROOF97=ROOT/"study/00097_初回費用後利益の全量確定/完了記録.json"
PROOF97_SHA="0d7111c41c4c25140be69fe8b06d0118496ddd6de3bc9ac7467ec2f01f6aef79"
SAVED_PATH=Path(__file__).with_name("集計.py")
SAVED_SHA="c7bd815c4157ef28e4d52d352207c1543a6dad3fcf474cf21be096ecf0fba340"
BEGIN=b"<!-- REPORT98 PLAN BEGIN -->\n"
END=b"<!-- REPORT98 PLAN END -->\n"


def old_module():
    """
    機能: 固定97報告器のJSON/指紋/円表示だけを再用する。
    引数: なし。
    返り値: moduleは停止書式部品。旧97の条件/成績/金融は再計算しない。
    """
    import hashlib
    if hashlib.sha256(OLD_PATH.read_bytes()).hexdigest()!=OLD_SHA:raise ValueError("固定97報告器SHA差")
    spec=importlib.util.spec_from_file_location("固定97報告書式98",OLD_PATH)
    module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module;spec.loader.exec_module(module)
    return module


OLD=old_module()
need,sha,load,money,ratio=OLD.need,OLD.sha,OLD.load,OLD.money,OLD.ratio


def original(body,expected):
    """
    機能: 初回計画又はREPORT98 markerから原計画bytesを復元する。
    引数: body(bytes)、expected(str)は文書と固定SHA。
    返り値: bytesは原計画。欠落/多重/改変は拒否する。
    """
    if BEGIN not in body and END not in body:
        need(sha(body)==expected,"原計画SHA差又はREPORT98 marker欠落")
        return body
    need(body.count(BEGIN)==body.count(END)==1,"REPORT98 marker集合")
    start,end=body.index(BEGIN)+len(BEGIN),body.index(END)
    need(end>start and body[end-1:end]==b"\n","原計画separator")
    restored=body[start:end-1];need(sha(restored)==expected,"REPORT98内の原bytes差")
    return restored


def table_contract(body):
    """
    機能: 元版5の55×9/39設定/24評価から実Keyとの対応を取得する。
    引数: body(bytes)は復元済み設定計画。
    返り値: dictは評価ID→入口/初期risk/Key/C/D。閾値は変更しない。
    """
    lines=body.decode("utf-8").splitlines()
    rows=[line.split("|")[1:-1] for line in lines if re.match(r"^\| [ICPVBXME]\d{2} \|",line)]
    need(len(rows)==55 and all(len(row)==11 for row in rows),"版5の55×9")
    ids=[re.match(r"^\| ([SNT]\d{2}) \|",line).group(1) for line in lines if re.match(r"^\| [SNT]\d{2} \|",line)]
    expected={f"S{i:02}" for i in range(1,11)}|{f"N{i:02}" for i in range(1,9)}|{f"T{i:02}" for i in range(1,22)}
    need(len(ids)==39 and set(ids)==expected,"固定39設定")
    evaluations={}
    for line in lines:
        if re.match(r"^\| R\d{2} \|",line):
            c=[v.strip() for v in line.split("|")[1:-1]]
            need(c[0] not in evaluations and len(c)==11,"評価ID一意/列数")
            evaluations[c[0]]={"入口":c[1],"初期risk":"" if c[2]=="なし" else c[2],"key":c[3],"cost":int(c[4]),"delay":int(c[5])}
    need(set(evaluations)=={f"R{i:02}" for i in range(1,25)},"固定24評価")
    expected_keys={(risk+"_" if risk else "")+"H0_"+(gate+"_" if gate=="AB" else "")+f"B5Q_P0_C{cost}_D{delay}"
                   for risk in ("","R05","R10") for gate in ("G0","AB") for cost in (0,5) for delay in (0,1)}
    need({e["key"] for e in evaluations.values()}==expected_keys,"24Key設定集合")
    return evaluations


def validate(result,audit,viewer,condition,evaluations,result_sha,audit_sha,saved_sha):
    """
    機能: 成功54/1296保存と独立/Viewer・uW損失・注文種別・16実現比較を結ぶ。
    引数: result/audit/viewer/condition/evaluations(dict)、result_sha/audit_sha/saved_sha(str)は正本と指紋。
    返り値: dictは16比較の集約。新金融・市場価格・未参加損益を計算しない。
    """
    need(result["試行"]==98 and result["成功"] is True and result["scope"]=="正式"
         and result["場数"]==54 and result["Actor数"]==24 and result["会計数"]==1296,"98保存54/1296成功")
    keys={e["key"] for e in evaluations.values()}
    need(len(keys)==24 and set(result["集計"])==set(result["実現診断"])==set(result["Actor設定"])==set(result["注文別"])==keys,"全24成績集合")
    need(saved_sha==SAVED_SHA and result["集計コードSHA256"]==saved_sha and result["条件SHA256"]==CONDITION_SHA
         and result["独立Tape金融監査SHA256"]==audit_sha,"停止保存/条件/独立証拠の結合")
    need(condition["試行"]==98 and condition["市場損益を開く前の固定"] is True and condition["汎用表版"]==5
         and condition["固定97完了SHA256"]==PROOF97_SHA,"98/固定97条件")
    need(audit["成功"] is True and audit["stage"]=="full54" and audit["場数"]==54 and audit["会計数"]==1296
         and audit["空Risk対97H0全文会計"]==432 and audit["不一致数"]==0
         and type(audit["照合項目数"]) is int and audit["照合項目数"]>0 and audit["入力コード前後不変"] is True,"独立54/1296/空Risk432成功")
    need(audit["Source/チャート再生成"] is False and audit["原板/CSV/Go金融再生"]==0
         and result["未実施"]["原板/CSV/Go再生"]==0 and result["未実施"]["未参加/決済後仮想利益"]==0,"再生成/仮想評価なし")
    need(viewer["試行"]==98 and viewer["成功"] is True and viewer["予定資源"]==viewer["完了資源"]==1296
         and viewer["全資源検証完了"] is True and viewer["不一致数"]==0 and not viewer["APIエラー"]
         and viewer["入力不変"] is True and viewer["入力SHA256前"]==viewer["入力SHA256後"]
         and viewer["結果SHA256"]==result_sha and result_sha in viewer["入力SHA256前"].values(),"Viewer全1296と同じ結果本文")
    controls=result["空Risk旧97H0全文対照"]
    need(len(controls)==54 and len({r["session"] for r in controls})==54
         and all(r["対照会計"]==8 and r["除外"]==[] for r in controls),"NoRisk対97H0全432/除外0")
    sessions={r["session"] for r in controls};audit_rows={r["session"]:r for r in audit["details"]}
    need(len(audit["details"])==54 and set(audit_rows)==sessions,"全54監査場")
    need(len(result["場別"])==1296 and {(r["session"],r["key"]) for r in result["場別"]}=={(s,k) for s in sessions for k in keys},"場別54×24")
    for session in sessions:
        native={p:h for p,h in result["入力依存SHA256前後"].items() if Path(p).name==session+".json"}
        a=audit_rows[session]
        need(len(native)==1 and a["成功"] is True and a["会計数"]==24 and a["不一致数"]==0
             and a["入力前後不変"] is True and a["空Risk対97H0全文"]["対照会計"]==8
             and a["空Risk対97H0全文"]["除外"]==[],"場別新24/旧H0八成功")
        path,h=next(iter(native.items()));need(a["入力SHA256前後"].get(path)==h,"NativeFingerprintの同本文")
    for e in evaluations.values():
        key=e["key"];r,d,c,o=(result[name][key] for name in ("集計","実現診断","Actor設定","注文別"))
        need(c["入口"]==e["入口"] and c["出口"]=="H0" and c["初期risk"]==e["初期risk"]
             and c["slip_pts"]==e["cost"] and c["delay_seconds"]==e["delay"],"評価IDと24設定")
        need(r["net_yen"]==r["gross_yen"]-r["fee_yen"]-r["slip_yen"]==d["純額円"]==d["正額円"]+d["負額円"],"実現粗純額/正負/費用")
        need(r["positions"]==d["玉数"] and r["entry_quantity"]==r["close_quantity"]==d["新規枚数"],"回数/枚数分母")
        need(all(r[n]==0 for n in ("open_buy","open_sell","pending_buy","pending_sell","open_entry_costs_yen")),"場内完結")
        for prefix,name in (("unit","u"),("whole","W")):
            need(r[prefix+"_positive_positions"]==d[name+"正益玉"]
                 and r[prefix+"_positive_closed_negative"]==d[name+"正益後最終赤字玉"],"u/W分母")
            need(d[name+"正益後最終赤字額円"]+d[name+"正益未観測赤字額円"]==d["負額円"],"u/W前後実損失")
        for name in ("positions","entry_quantity","gross_yen","fee_yen","slip_yen","net_yen"):
            section="counts" if name=="positions" else "totals"
            need(sum(row[section][name] for row in result["場別"] if row["key"]==key)==r[name],"場別合計:"+name)
        need(set(o)=={"Source","H","Risk"} and all(set(v)=={"要求回数","要求枚数","約定回数","約定枚数"} for v in o.values()),"Source/H/Riskの全4欄")
        need(o["Source"]["要求回数"]==r["source_exit_requests"] and o["H"]["要求回数"]==r["protection_exit_requests"]
             and o["Risk"]["要求回数"]==r.get("initial_risk_exit_requests",0),"point別要求counter")
        need(sum(v["約定回数"] for v in o.values())==r["exit_fills"] and sum(v["約定枚数"] for v in o.values())==r["close_quantity"]
             and o["H"]["約定回数"]==r["protection_exit_fills"],"point別実約定/枚数")
    comparisons={};source=result["初期Riskと空Riskの同実入口と実参加差"]
    need(len(source)==16,"Risk16比較")
    for risk in ("R05","R10"):
        for gate in ("","AB_"):
            for cost in (0,5):
                for delay in (0,1):
                    old="H0_"+gate+f"B5Q_P0_C{cost}_D{delay}";new=risk+"_"+old;name=new+"対"+old
                    rows=source[name];need(len(rows)==54 and {r["session"] for r in rows}==sessions,"16比較の各54場")
                    c={n:sum(r[n] for r in rows) for n in rows[0] if n not in ("session","限定")}
                    need(c["同Source出生"]==c["同実入口"]+c["取得変更"],"同出生/取得変更分解")
                    need(c["同Source出生"]+c["Aのみ"]==result["集計"][old]["positions"]
                         and c["同Source出生"]+c["Bのみ"]==result["集計"][new]["positions"],"実在Source分母")
                    need(c["全差円"]==c["同実入口差円"]+c["取得変更差円"]-c["Aのみ円"]+c["Bのみ円"]
                         ==result["集計"][new]["net_yen"]-result["集計"][old]["net_yen"],"同実入口退出差と実参加差")
                    comparisons[name]=c
    return comparisons


def render(result,evaluations,comparisons,audit,viewer):
    """
    機能: 全24の実現成績と実注文種別を日本語表へ整形する。
    引数: result/evaluations/comparisons/audit/viewer(dict)は成功済み保存値。
    返り値: strは実行後本文。未参加/退出後利益/回収率は生成しない。
    """
    stats=result["集計"]
    lines=["全54既使用場の保存会計・独立Tape金融・Viewer照合を完了。下部の原計画内の『未実行』は市場前に固定した当時の記述で、現在結果は本欄を正とする。",""]
    for gate in ("G0","AB"):
        key="H0_"+("AB_" if gate=="AB" else "")+"B5Q_P0_C0_D0"
        values=[("なし",key),("R05","R05_"+key),("R10","R10_"+key)]
        cells=[f"{risk} {money(stats[k]['net_yen'])}円（{stats[k]['positions']}玉/{stats[k]['entry_quantity']}枚）" for risk,k in values]
        lines.append("主C0/D0の"+gate+"："+"、".join(cells)+"。")
    lines += ["", "C0は指定手数料38.5円/枚片道のみ。C5は未実測の追加5pt/片道感度、D1は追加1価格秒の別動的運転。BBOのspreadは実粗額へ含み二重加算しない。費用/遅延による悪化も以下へ全件表示し、主条件の順位を他条件へ一般化しない。", "",
              "## 全24評価の実現額", "", "|ID・入口/risk/C/D|玉/枚|粗額円|fee円|slip円|純額円|正額/負額円|PF|取引あり場/赤字場|", "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for rid,e in evaluations.items():
        r,d=stats[e["key"]],result["実現診断"][e["key"]];risk=e["初期risk"] or "なし"
        lines.append(f"|{rid} {e['入口']}/{risk}/C{e['cost']}/D{e['delay']}|{r['positions']}/{r['entry_quantity']}|{money(r['gross_yen'])}|{money(r['fee_yen'])}|{money(r['slip_yen'])}|{money(r['net_yen'])}|{money(d['正額円'])}/{money(d['負額円'])}|{ratio(d['PF'])}|{r['active_sessions']}/54・{r['negative_sessions']}/54|")
    lines += ["", "PF＝実玉の正額÷負額の絶対値。無取引場を赤字場へ含めない。全出口の利益後はH0固定で、初期riskなしを旧P0出口と呼ばない。", "",
              "## 正益前後の実損失とDD", "", "|ID|u後赤字玉/u正益玉・損失円|u未観測赤字玉・損失円|W後赤字玉/W正益玉・損失円|W未観測赤字玉・損失円|場内最大DD円|連結DD円|", "|---|---:|---:|---:|---:|---:|---:|"]
    for rid,e in evaluations.items():
        d=result["実現診断"][e["key"]]
        lines.append(f"|{rid}|{d['u正益後最終赤字玉']}/{d['u正益玉']}・{money(d['u正益後最終赤字額円'])}|{d['u正益未観測赤字玉']}・{money(d['u正益未観測赤字額円'])}|{d['W正益後最終赤字玉']}/{d['W正益玉']}・{money(d['W正益後最終赤字額円'])}|{d['W正益未観測赤字玉']}・{money(d['W正益未観測赤字額円'])}|{money(d['場内最大DD円'])}|{money(d['保存極値を連結した最大DD円'])}|")
    lines += ["", "uは残玉単価の往復費用後評価、Wは同じ実玉の確定額＋残玉評価。損失額は旗後の値幅でなく、各分類に属する実玉の最終赤字額。H移行はstrict u>0であり、Wだけ正/u=0では移行しない。DDは独立全金融監査で検証した口座MTM保存極値を使用し、連結DDは場順の極値/終値を連結した値。", "",
              "## 実注文のSource/H/Risk分類", "", "|ID|Source 要求回/枚→約定回/枚|H 要求回/枚→約定回/枚|Risk 要求回/枚→約定回/枚|", "|---|---:|---:|---:|"]
    for rid,e in evaluations.items():
        o=result["注文別"][e["key"]]
        cells=[f"{o[n]['要求回数']}/{o[n]['要求枚数']}→{o[n]['約定回数']}/{o[n]['約定枚数']}" for n in ("Source","H","Risk")]
        lines.append("|"+rid+"|"+"|".join(cells)+"|")
    lines += ["", "分類は実注文のinitial_risk_point/protection_pointと理由に結ぶ。初期risk予約後のpre_fillでuが正になっても、既予約注文を撤回・Hへ付け替えない。H起動玉＝H理由の決済玉とは限らず、初hit＝新返済要求とも限らない。Source全予約ならrisk初hitがあっても追加要求0が正しい。", "",
              "## 同実入口の出口差と実参加差", "", "実Sourceのmethod＋signal_idを先に結び、要求時刻/方向、実取得時刻・Index・物理行、取得価格、初期量が全一致したものだけを同実入口とする。回数/枚数が等しいだけでは同入口と断定しない。", "",
              "|risk・入口/C/D|同実入口/取得変更/空riskのみ/新riskのみ|同実入口差円|取得変更差円|空riskのみ実現額円|新riskのみ実現額円|全差円|", "|---|---:|---:|---:|---:|---:|---:|"]
    for name,c in comparisons.items():
        new=name.split("対",1)[0];e=next(v for v in evaluations.values() if v["key"]==new)
        lines.append(f"|{e['初期risk']}・{e['入口']}/C{e['cost']}/D{e['delay']}|{c['同実入口']}/{c['取得変更']}/{c['Aのみ']}/{c['Bのみ']}|{money(c['同実入口差円'])}|{money(c['取得変更差円'])}|{money(c['Aのみ円'])}|{money(c['Bのみ円'])}|{money(c['全差円'])}|")
    lines += ["", "全差＝同実入口差＋取得変更差−空riskのみの実現額＋新riskのみの実現額。片側欄も両戦略で実際に成立した取引の実現額であり、未参加の仮想利益ではない。早期返済で余力が変わると実参加も変わり得るため、全差を指標単独や同一入口の出口効果へ一括帰属しない。", "",
              "## 証拠と限界", "",
              f"空Riskの8×54＝432会計は正式97H0へ除外0全文一致。全24×54＝1296会計の独立Python照合{money(audit['照合項目数'])}項目、Viewer1296資源{money(viewer['照合項目数'])}項目は差0。保存算術・全金融経路・表示一致を互いの代用にしない。", "",
              "固定96/97由来の完成Tape（Scalar11/公開Source/確定3・15分文脈）を再用し、新しいSource/チャート/ATRの原板生成はfalse。ABは当時の現在候補から純式を再計算する。新しい原板数値生成の全面証明ではない。", "",
              "2026-09-21〜10-27、日中27/夜間27の全既使用54場。未使用期間の安定性、実mini板の流動性、5pt滑りの実測、真の両市場受信順序は未確認。同時刻TOPIX先行は再生規則で、CurrentPriceTimeは独立した到着時計ではない。", "",
              "0.5/1倍、20/125ptは比較仮定で最適値ではない。ATRは値幅尺度で方向予測ではなく、125ptも後続気配・費用込みの実損失上限ではない。売買は符号反転した同一条件。少数例や同じ市場出生の運転反復を独立標本へ水増しせず、安定収益を未証明とする。", "",
              "評価は実現粗純額/費用/正負/PF/uW損失/DD/回数枚数。未参加/退出後仮想利益/理想ピーク/回収率は未算出（処理0回）、資本金ROIも未算出。Source残量を現在出来高や攻撃側約定量へ読み替えない。", "",
              "[結果正本](成果物/結果.json)・[保存成績](成果物/結果.md)・[Viewer一覧](成果物/一覧.resources.json)・[金融完了](金融完了.json)・[独立照合](独立照合.json)・[Viewer照合](Viewer照合.json)・[条件](条件.json)・[検証計画](検証計画.md)・[再現手順](再現手順.md)。", ""]
    return "\n".join(lines)


def prepare(paths):
    """
    機能: 成功済み7入力と固定コードを読み、原計画を保つ2文書のbytesを作る。
    引数: paths(dict[str,Path])は明示入力。保存器は同folderの停止コード。
    返り値: tupleは生成2文書・安定内容指紋・入力開始指紋。ここでは書き込まない。
    """
    raw={n:p.read_bytes() for n,p in paths.items()};before={str(paths[n].resolve()):sha(b) for n,b in raw.items()}
    condition=load(raw["condition"])
    need(sha(raw["condition"])==CONDITION_SHA,"固定98条件SHA")
    need(sha(raw["plan"])==condition["計画SHA256"],"98検証計画SHA")
    need(sha(PROOF97.read_bytes())==PROOF97_SHA,"正式97完了SHA")
    readme=original(raw["readme"],condition["README計画SHA256"])
    settings=original(raw["settings"],condition["設定表計画SHA256"]);evaluations=table_contract(settings)
    dependencies={str((ROOT/n).resolve()):h for n,h in condition["コードSHA256"].items()}
    need(bool(dependencies) and len(dependencies)==len(condition["コードSHA256"])
         and all(sha(Path(p).read_bytes())==h for p,h in dependencies.items()),"固定金融コード前後同一")
    result,audit,viewer=(load(raw[n]) for n in ("result","audit","viewer"))
    saved_sha=sha(SAVED_PATH.read_bytes())
    comparisons=validate(result,audit,viewer,condition,evaluations,sha(raw["result"]),sha(raw["audit"]),saved_sha)
    body=render(result,evaluations,comparisons,audit,viewer).encode("utf-8")
    generated={"README.md":("# 00098：実建値からの利益前ATR追尾・実行結果\n\n").encode("utf-8")+body+("\n## 固定した原計画\n\n").encode("utf-8")+BEGIN+readme+b"\n"+END,
               "設定と結果.md":("# 98：設定と結果（全54場実行後）\n\n").encode("utf-8")+body+("\n## 固定した設定計画・版5\n\n").encode("utf-8")+BEGIN+settings+b"\n"+END}
    content={n:sha(raw[n]) for n in ("result","audit","viewer","condition","plan")}
    content.update(readme_plan=sha(readme),settings_plan=sha(settings),保存器=saved_sha,報告コード=sha(Path(__file__).read_bytes()),固定97完了=PROOF97_SHA)
    for name,expected in (("README.md",condition["README計画SHA256"]),("設定と結果.md",condition["設定表計画SHA256"])):
        need(sha(original(generated[name],expected))==expected,"生成後の原bytes復元")
    before.update(dependencies);before.update(result["入力依存SHA256前後"])
    for path in (SAVED_PATH,OLD_PATH,PROOF97,Path(__file__)):before[str(path.resolve())]=sha(path.read_bytes())
    need(all(sha(Path(p).read_bytes())==h for p,h in before.items()),"生成前後の全入力差")
    return generated,content,before


def main():
    """
    機能: 成功済み保存から新規報告を生成又は同出力を再照合する。
    引数: --result/--audit/--viewer/--condition/--plan/--readme/--settings/--out(Path)、--run又は--check。
    返り値: None。未完/差/既存生成先は非0。金融/原板/API/Sourceを実行しない。
    """
    parser=argparse.ArgumentParser(description=__doc__);mode=parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--run",action="store_true");mode.add_argument("--check",action="store_true")
    names=("result","audit","viewer","condition","plan","readme","settings")
    for name in names+("out",):parser.add_argument("--"+name,type=Path,required=True)
    args=parser.parse_args();generated,content,before=prepare({n:getattr(args,n) for n in names})
    outputs={n:sha(b) for n,b in generated.items()}
    if args.run:
        need(not args.out.exists(),"新規報告dirだけ");args.out.mkdir(parents=True)
        for name,body in generated.items():(args.out/name).write_bytes(body)
        proof={"試行":98,"成功":True,"入力内容SHA256":content,"観測入力SHA256前後":before,"出力SHA256":outputs,"原計画復元":True,
               "版5":{"手法":55,"尺度":9,"設定":39,"評価":24},"金融/Source/チャート再生成":False,"原板/API/Go金融再生":0,
               "未参加/退出後仮想利益/回収率":"未算出・処理0回"}
        (args.out/"報告生成.json").write_text(json.dumps(proof,ensure_ascii=False,indent=2,allow_nan=False)+"\n",encoding="utf-8",newline="\n")
    else:
        proof=load((args.out/"報告生成.json").read_bytes())
        need(proof["成功"] is True and proof["入力内容SHA256"]==content and proof["出力SHA256"]==outputs,"報告証拠内容差")
        for name,body in generated.items():need((args.out/name).read_bytes()==body,"報告生成差:"+name)
    need(all(sha(Path(p).read_bytes())==h for p,h in before.items()),"報告後の入力差")
    print(json.dumps({"成功":True,"mode":"run" if args.run else "check","原計画復元":True,"出力SHA256":outputs},ensure_ascii=False))


if __name__=="__main__":main()
