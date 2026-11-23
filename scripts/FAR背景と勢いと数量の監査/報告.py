"""99成功証拠が全て結合した後だけ、実現成績と原計画bytesを報告する。"""

import argparse
import importlib.util
import json
from pathlib import Path
import re
import sys
import types


ROOT=Path(__file__).resolve().parents[2]
OLD_PATH=ROOT/"scripts/FAR利益前ATR追尾の監査/報告.py"
OLD_SHA="1577453454e1727b81fffdd8eca04d9cc2478708e613dfed2192975ad8fc05c7"
PROOF98=ROOT/"study/00098_実建値からの利益前ATR追尾/完了記録.json"
PROOF98_SHA="2ee9417d0cd1f8bef107712789d26e3f72c0f95a933e60b31bb3f11784ca0dfe"
CONDITION_SHA="ba95b8c7df74f3b6f2f0f3cc349210ff284bdc64ed2fe79311d702ebff2b0f71"
SAVED_PATH=Path(__file__).with_name("集計.py")
VIEWER_PATH=Path(__file__).with_name("表示監査.py")
# 金融54/独立648/保存/Viewer648の成功証拠通知まで実生成しない。
SAVED_SHA="f5d6635e17e0e7bb3be8d5941e0adf7568f75251ce1a505b8090372289d2a69c"
COMPLETION_SHA="d945e5daf823d95e17eb897115d7dcbd96a94a2ac112a028267fb7ed7e847dcc"
INDEPENDENT_SHA="592aff6b2a6b6eae4c3a10b4e5b7752e02972a7d489b04c73d92ab6654fedc2e"
VIEWER_SHA="07491a17cef0599ee7fdf2f17fa58ba48e258d7c84e494386ab0b2d14193dd95"
BEGIN=b"<!-- REPORT99 PLAN BEGIN -->\n"
END=b"<!-- REPORT99 PLAN END -->\n"
KEYS=tuple("H0_"+(gate+"_" if gate else "")+f"B5Q_P0_C{cost}_D{delay}" for gate in ("","E3","E3S") for cost in (0,5) for delay in (0,1))
CHECKS=("共通.現在価格時計","共通.確定3分","共通.確定15分","共通.EMA背景既知","共通.MACD増分","共通.現在量支持","A.3分EMA方向","A.15分EMA方向")


def fixed():
    """
    機能: 固定98報告器の指紋/数値表示/原bytes復元だけを再用する。
    引数: なし。
    返り値: moduleは書式部品。市場結果をimport時に読まない。
    """
    import hashlib
    if hashlib.sha256(OLD_PATH.read_bytes()).hexdigest()!=OLD_SHA:raise ValueError("固定98報告器SHA差")
    spec=importlib.util.spec_from_file_location("固定98報告書式99",OLD_PATH)
    value=importlib.util.module_from_spec(spec);sys.modules[spec.name]=value;spec.loader.exec_module(value)
    return value


OLD=fixed()
need,sha,load,money,ratio=OLD.need,OLD.sha,OLD.load,OLD.money,OLD.ratio


def require_fixed():
    """
    機能: 実金融/独立/保存/Viewerの未確定を7入力読取前に拒否する。
    引数: なし。
    返り値: None。placeholderならValueError。
    """
    need(all(type(h) is str and re.fullmatch(r"[0-9a-f]{64}",h) for h in (CONDITION_SHA,SAVED_SHA,COMPLETION_SHA,INDEPENDENT_SHA,VIEWER_SHA)),"99金融/独立/保存/Viewer停止SHAが未結合")


def original(body,expected):
    """
    機能: REPORT99原計画又は初回文書を固定SHAへ復元する。
    引数: body(bytes)、expected(str)は文書と計画指紋。
    返り値: bytesは原文。余分なmarker/欠落/改変は拒否する。
    """
    namespace=dict(OLD.__dict__,BEGIN=BEGIN,END=END)
    restore=types.FunctionType(OLD.original.__code__,namespace)
    return restore(body,expected)


def table_contract(body):
    """
    機能: 固定版5の55×9/38設定/12評価と本名の対応を確認する。
    引数: body(bytes)は復元済み設定計画。
    返り値: dictは評価ID→入口/出口/Key/C/D。
    """
    lines=body.decode("utf-8").splitlines()
    rows=[line.split("|")[1:-1] for line in lines if re.match(r"^\| [ICPVBXME]\d{2} \|",line)]
    need(len(rows)==55 and all(len(row)==11 for row in rows),"版5の55×9")
    ids=[re.match(r"^\| ([SNT]\d{2}) \|",line).group(1) for line in lines if re.match(r"^\| [SNT]\d{2} \|",line)]
    expected={f"S{i:02}" for i in range(1,11)}|{f"N{i:02}" for i in range(1,9)}|{f"T{i:02}" for i in range(1,21)}
    need(len(ids)==38 and set(ids)==expected,"99固定38設定")
    output={}
    for line in lines:
        if re.match(r"^\| R\d{2} \|",line):
            row=[s.strip() for s in line.split("|")[1:-1]]
            need(len(row)==11 and row[0] not in output,"99評価ID/列数")
            output[row[0]]={"入口":row[1],"出口":row[2],"key":row[3],"cost":int(row[4]),"delay":int(row[5])}
    need(set(output)=={f"R{i:02}" for i in range(1,13)} and {r["key"] for r in output.values()}==set(KEYS),"99全12評価")
    for row in output.values():
        gate="" if row["入口"]=="G0" else row["入口"]
        need(row["入口"] in ("G0","E3","E3S") and row["出口"]=="H0"
             and row["key"]=="H0_"+(gate+"_" if gate else "")+f"B5Q_P0_C{row['cost']}_D{row['delay']}","99本名12Key対応")
    return output


def comparison_pairs():
    """
    機能: G0→E3/SとE3→E3Sの12比較を列挙する。
    引数: なし。
    返り値: list[tuple[str,str]]は実戦略A/BのKey。
    """
    output=[]
    for before,after in (("","E3"),("","E3S"),("E3","E3S")):
        for c in (0,5):
            for d in (0,1):
                keys=["H0_"+(g+"_" if g else "")+f"B5Q_P0_C{c}_D{d}" for g in (before,after)]
                output.append(tuple(keys))
    return output


def validate(result,audit,viewer,condition,evaluations,result_sha,audit_sha,saved_sha):
    """
    機能: 全54/648保存・独立・Viewerと実現額/判断分母/12比較を厳密結合する。
    引数: result/audit/viewer/condition/evaluations(dict)、result_sha/audit_sha/saved_sha(str)は正本とSHA。
    返り値: dictは実入口比較。未参加/退出後の仮想利益は計算しない。
    """
    need(result["試行"]==99 and result["成功"] is True and result["scope"]=="正式" and result["場数"]==54
         and result["Actor数"]==12 and result["会計数"]==648,"99保存全54/648")
    keys={row["key"] for row in evaluations.values()}
    need(keys==set(KEYS) and all(set(result[name])==keys for name in ("集計","実現診断","Actor設定","注文別","判断分類")),"99全12成績集合")
    need(saved_sha==SAVED_SHA and result["集計コードSHA256"]==saved_sha and result["条件SHA256"]==CONDITION_SHA
         and result["完了SHA256"]==COMPLETION_SHA and audit_sha==INDEPENDENT_SHA
         and result["独立Tape金融監査SHA256"]==audit_sha,"99保存/条件/実金融/独立停止結合")
    need(condition["試行"]==99 and condition["市場損益を開く前の固定"] is True
         and condition["汎用表版"]==5 and condition["固定98完了SHA256"]==PROOF98_SHA,"99/固定98条件")
    need(audit["成功"] is True and audit["stage"]=="full54" and audit["場数"]==54 and audit["会計数"]==648
         and audit["空Gate対98H0全文会計"]==216 and audit["不一致数"]==0
         and type(audit["照合項目数"]) is int and audit["照合項目数"]>0 and audit["入力コード前後不変"] is True,"99独立全648/G0四×54")
    need(audit["Source/チャート再生成"] is False and audit["原板/CSV/Go金融再生"]==0
         and result["未実施"]["原板/CSV/Go再生"]==0 and result["未実施"]["未参加/決済後仮想利益"]==0,"再生成/仮想評価なし")
    need(viewer["試行"]==99 and viewer["成功"] is True and viewer["予定資源"]==viewer["完了資源"]==648
         and viewer["全資源検証完了"] is True and viewer["不一致数"]==0 and not viewer["APIエラー"]
         and viewer["監査コードSHA256"]==VIEWER_SHA and viewer["入力不変"] is True
         and viewer["入力SHA256前"]==viewer["入力SHA256後"] and viewer["結果SHA256"]==result_sha
         and result_sha in viewer["入力SHA256前"].values(),"99Viewer全648と同結果/停止コード")
    controls=result["空Gate旧98H0全文対照"]
    need(len(controls)==54 and len({row["session"] for row in controls})==54
         and all(row["対照会計"]==4 and row["除外"]==[] and re.fullmatch(r"[0-9a-f]{64}",row["固定98保存SHA256"]) for row in controls),"99G0旧98H0全216/除外0")
    sessions={row["session"] for row in controls};audit_rows={row["session"]:row for row in audit["details"]}
    need(len(audit["details"])==54 and set(audit_rows)==sessions,"99監査54集合")
    need(len(result["場別"])==648 and {(row["session"],row["key"]) for row in result["場別"]}=={(s,k) for s in sessions for k in keys},"99場別54×12")
    for control in controls:
        session=control["session"];row=audit_rows[session]
        native={p:h for p,h in result["入力依存SHA256前後"].items() if Path(p).name==session+".json"}
        need(len(native)==1 and row["成功"] is True and row["会計数"]==12 and row["不一致数"]==0
             and row["入力前後不変"] is True and row["空Gate対98H0全文"]["対照会計"]==4
             and row["空Gate対98H0全文"]["除外"]==[],"99場別新12/旧G0四成功")
        path,value=next(iter(native.items()));need(row["入力SHA256前後"].get(path)==value,"99Native同本文")
        old={p:h for p,h in row["入力SHA256前後"].items() if Path(p).name==session+".json.gz" and Path(p).resolve().is_relative_to(PROOF98.parent)}
        need(len(old)==1 and next(iter(old.values()))==control["固定98保存SHA256"],"旧98対照gzipの指紋結合")
    pure=result["純判定と共有枠"]
    need(len(pure)==54 and {row["session"] for row in pure}==sessions,"99共有枠54集合")
    for e in evaluations.values():
        key=e["key"];r,d,c,o,j=(result[name][key] for name in ("集計","実現診断","Actor設定","注文別","判断分類"))
        need(c=={"入口":e["入口"],"出口":"H0","初期risk":"","共通基本保護":"P0","slip_pts":e["cost"],"delay_seconds":e["delay"]},"99評価と本名金融設定")
        need(r["net_yen"]==r["gross_yen"]-r["fee_yen"]-r["slip_yen"]==d["純額円"]==d["正額円"]+d["負額円"],"実現粗純/正負/費用")
        need(r["positions"]==d["玉数"] and r["entry_quantity"]==r["close_quantity"]==d["新規枚数"],"実回数/枚数分母")
        need(all(r[name]==0 for name in ("open_buy","open_sell","pending_buy","pending_sell","open_entry_costs_yen")),"99全場完結")
        for prefix,name in (("unit","u"),("whole","W")):
            need(r[prefix+"_positive_positions"]==d[name+"正益玉"] and r[prefix+"_positive_closed_negative"]==d[name+"正益後最終赤字玉"],"u/W分母")
            need(d[name+"正益後最終赤字額円"]+d[name+"正益未観測赤字額円"]==d["負額円"],"u/W前後実損失")
        for name in ("positions","entry_quantity","gross_yen","fee_yen","slip_yen","net_yen"):
            section="counts" if name=="positions" else "totals"
            need(sum(row[section][name] for row in result["場別"] if row["key"]==key)==r[name],"場別合計:"+name)
        need(set(o)=={"Source","H"} and all(set(v)=={"要求回数","要求枚数","約定回数","約定枚数"} for v in o.values()),"Source/H全注文欄")
        need(o["Source"]["要求回数"]==r["source_exit_requests"] and o["H"]["要求回数"]==r["protection_exit_requests"]
             and sum(v["約定回数"] for v in o.values())==r["exit_fills"] and sum(v["約定枚数"] for v in o.values())==r["close_quantity"]
             and o["H"]["約定回数"]==r["protection_exit_fills"],"Source/H要求と約定counter")
        mapping={"新規":"new_grids","保有":"holding_grids","待機":"waiting_grids","判定不能":"unknown_grids"}
        need(set(j["枠"])==set(mapping) and all(j["枠"][label]==r["grid_"+field] for label,field in mapping.items())
             and sum(j["枠"].values())==r["grid_grid_calls"],"判断4分類と全枠分母")
        n=sum(j["技法機会"].values())
        need(set(j["技法機会"])=={"成立","既知拒否","必要未知"} and n==sum(row["口座別"][key] for row in pure)
             and j["技法未使用"]==(e["入口"]=="G0"),"技法三値と適格出生分母")
        checks=set(CHECKS)|({"共通.同時スパイク警戒"} if e["入口"]=="E3S" else set())
        need(set(j["check"])==(checks if n else set()) and all(set(v)=={"既知成立","既知不成立","未知"} and sum(v.values())==n for v in j["check"].values()),"E3/S必要8/9check集合と分母")
        stages=j["Source段階"]
        need(sum(v["出生"] for v in stages.values())==r["grid_births"] and sum(v["受理"] for v in stages.values())==r["grid_accepted"]
             and sum(v["実取得"] for v in stages.values())==r["positions"] and sum(v["枚数"] for v in stages.values())==r["entry_quantity"],"Source出生/受理/実取得/枚数を分離")
    comparisons={};source=result["入口間の同実入口と実参加差"]
    need(len(source)==12,"99全12実入口比較")
    for before,after in comparison_pairs():
        name=after+"対"+before;rows=source[name]
        need(len(rows)==54 and {row["session"] for row in rows}==sessions,"12比較の各54場")
        c={name:sum(row[name] for row in rows) for name in rows[0] if name not in ("session","限定")}
        need(c["同Source出生"]==c["同実入口"]+c["取得変更"] and c["同Source出生"]+c["Aのみ"]==result["集計"][before]["positions"]
             and c["同Source出生"]+c["Bのみ"]==result["集計"][after]["positions"],"Source/同実入口/実参加分母")
        need(c["全差円"]==c["同実入口差円"]+c["取得変更差円"]-c["Aのみ円"]+c["Bのみ円"]
             ==result["集計"][after]["net_yen"]-result["集計"][before]["net_yen"],"12比較の実現額分解")
        comparisons[name]=c
    return comparisons


def render(result,evaluations,comparisons,audit,viewer):
    """
    機能: 全12の実現額/損失/判断/注文/入口比較と限界を日本語で記す。
    引数: result/evaluations/comparisons/audit/viewer(dict)は成功済み保存証拠。
    返り値: strは実行後本文。指標単独効果や仮想利益は作らない。
    """
    lines=["全54既使用場の保存会計・独立Tape金融・Viewerを照合済み。下部の固定原計画内の『未実行』は市場前の状態であり、現在結果は本欄を正とする。","",
           "C0は片道38.5円/枚の指定手数料のみ。C5は未実測の追加5pt/片道、D1は追加1価格秒の別動的運転。BBO spreadは実粗額に含み二重加算しない。","",
           "## 全12評価の実現額","","|ID・入口/C/D|玉/枚|粗額円|fee円|slip円|純額円|正額/負額円|PF|取引あり場/赤字場|","|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for rid,e in evaluations.items():
        r,d=result["集計"][e["key"]],result["実現診断"][e["key"]]
        lines.append(f"|{rid} {e['入口']}/C{e['cost']}/D{e['delay']}|{r['positions']}/{r['entry_quantity']}|{money(r['gross_yen'])}|{money(r['fee_yen'])}|{money(r['slip_yen'])}|{money(r['net_yen'])}|{money(d['正額円'])}/{money(d['負額円'])}|{ratio(d['PF'])}|{r['active_sessions']}/54・{r['negative_sessions']}/54|")
    lines += ["","PF＝実玉の正額÷負額絶対値。無取引は黒字や安定成功へ数えない。全口座の退出はH0、利益前Riskは空。G0の旧98H0対照を旧P0/AB成功と言い換えない。","",
              "## 正益前後の実損失とDD","","|ID|u後赤字/正益玉・損失円|u未観測赤字玉・損失円|W後赤字/正益玉・損失円|W未観測赤字玉・損失円|場内最大DD円|連結DD円|","|---|---:|---:|---:|---:|---:|---:|"]
    for rid,e in evaluations.items():
        d=result["実現診断"][e["key"]]
        lines.append(f"|{rid}|{d['u正益後最終赤字玉']}/{d['u正益玉']}・{money(d['u正益後最終赤字額円'])}|{d['u正益未観測赤字玉']}・{money(d['u正益未観測赤字額円'])}|{d['W正益後最終赤字玉']}/{d['W正益玉']}・{money(d['W正益後最終赤字額円'])}|{d['W正益未観測赤字玉']}・{money(d['W正益未観測赤字額円'])}|{money(d['場内最大DD円'])}|{money(d['保存極値を連結した最大DD円'])}|")
    lines += ["","uは残玉単価の往復費用後評価、Wは確定額＋残玉評価。表の損失額は分類した実玉の最終赤字額。DDは独立全金融監査へ結んだ口座MTM保存極値と場順連結であり、資本金ROIではない。","",
              "## Source/Hの実注文と判断分類","","|ID|Source要求回/枚→約定回/枚|H要求回/枚→約定回/枚|新規/保有/待機/不能の枠|技法成立/既知拒否/必要未知|Source種別：出生/受理/実取得/枚|","|---|---:|---:|---:|---:|---|"]
    for rid,e in evaluations.items():
        o,j=result["注文別"][e["key"]],result["判断分類"][e["key"]]
        cells=[f"{o[n]['要求回数']}/{o[n]['要求枚数']}→{o[n]['約定回数']}/{o[n]['約定枚数']}" for n in ("Source","H")]
        frames="/".join(str(j["枠"][n]) for n in ("新規","保有","待機","判定不能"))
        gates="未使用" if j["技法未使用"] else "/".join(str(j["技法機会"][n]) for n in ("成立","既知拒否","必要未知"))
        stages="、".join(kind+"："+"/".join(str(row[name]) for name in ("出生","受理","実取得","枚数")) for kind,row in j["Source段階"].items()) or "なし"
        lines.append("|"+rid+"|"+"|".join(cells)+"|"+frames+"|"+gates+"|"+stages+"|")
    lines += ["","技法分母は金融前資格を満たした出生のcallbackだけ。全枠や保有を技法の未知へ重ねない。Source出生・枠受理・実取得は別段階で、拒否/未知も同じ出生を一回消費する。HはSource処理後の未予約残だけを要求し、先行予約を撤回しない。","",
              "## 同実入口と実参加の12比較","","実Sourceのmethod＋signal_idを先に結び、要求時刻/方向、取得時刻・Index・物理行、価格、初期量が全一致したものだけを同実入口とする。数量や回数だけで同入口としない。","",
              "|実戦略B対A|同実/取得変更/Aのみ/Bのみ|同実差円|取得変更差円|Aのみ実現額円|Bのみ実現額円|全差円|","|---|---:|---:|---:|---:|---:|---:|"]
    for name,c in comparisons.items():
        lines.append(f"|{name}|{c['同実入口']}/{c['取得変更']}/{c['Aのみ']}/{c['Bのみ']}|{money(c['同実入口差円'])}|{money(c['取得変更差円'])}|{money(c['Aのみ円'])}|{money(c['Bのみ円'])}|{money(c['全差円'])}|")
    lines += ["","全差＝同実入口差＋取得変更差−Aのみ実現額＋Bのみ実現額。片側も実在取引の実現額で、未参加の仮想利益ではない。入口選別と保有余力の変化を含む全差を、指標単独や出口効果へ一括帰属しない。","",
              "## 証拠と限界","",f"G0四×54＝216会計は旧98空Risk/G0/H0へ除外0全文対照。新12×54＝648会計の独立照合{money(audit['照合項目数'])}項目、Viewer648資源{money(viewer['照合項目数'])}項目は差0。保存算術・全金融経路・表示一致を代用しない。","",
              "E3は現在価格時計・確定3/15分・EMA背景既知・MACD増分・現在量・3分/15分EMA方向の8条件。E3Sだけ同時スパイク警戒を加える。旧Close/EMA位置・Close進行・ATR距離・旧Bの反転条件は採否未使用だが、入力破損検査は維持する。", "",
              "固定96/97/98由来の完成Tapeと当時公開された文脈を再用し、Source/チャートの新生成はfalse。現在候補の本名E3/S全checkを純Pythonで再計算する。新しい原板数値生成の全面証明ではない。","",
              "2026-09-21〜10-27の既使用54場（日中27/夜間27）。未知期間の安定利益、実mini板流動性、5pt滑り実測、両市場の真の到着順は未確認。同秒TOPIX先行は再生規則で、CurrentPriceTimeは独立受信時計ではない。少数例や費用/遅延違いを独立市場例へ水増ししない。Source残量を現在出来高や攻撃側約定量へ呼び替えない。","",
              "評価は実現額/正負/PF/uW前後損失/DD/回数枚数。未参加/退出後仮想利益/理想ピーク/回収率は未算出・処理0回、資本金ROIも未算出。","",
              "[結果正本](成果物/結果.json)・[保存成績](成果物/結果.md)・[Viewer一覧](成果物/一覧.resources.json)・[金融完了](金融完了.json)・[独立照合](独立照合.json)・[Viewer照合](Viewer照合.json)・[条件](条件.json)・[検証計画](検証計画.md)・[再現手順](再現手順.md)。",""]
    return "\n".join(lines)


def prepare(paths):
    """
    機能: 成功7入力とコードを検査し、REPORT99原bytesを保つ2文書を作る。
    引数: paths(dict[str,Path])はresult/audit/viewer/condition/plan/readme/settings。
    返り値: tupleは生成bytes/内容指紋/入力前指紋。未確定時は読取前に拒否。
    """
    require_fixed()
    need(set(paths)=={"result","audit","viewer","condition","plan","readme","settings"},"99報告7Path集合")
    raw={name:path.read_bytes() for name,path in paths.items()};before={str(paths[name].resolve()):sha(body) for name,body in raw.items()}
    condition=load(raw["condition"]);need(sha(raw["condition"])==CONDITION_SHA,"99固定条件SHA")
    need(sha(raw["plan"])==condition["計画SHA256"] and sha(PROOF98.read_bytes())==PROOF98_SHA,"99計画/98完了SHA")
    readme=original(raw["readme"],condition["README計画SHA256"])
    settings=original(raw["settings"],condition["設定表計画SHA256"]);evaluations=table_contract(settings)
    dependencies={str((ROOT/name).resolve()):value for name,value in condition["コードSHA256"].items()}
    need(bool(dependencies) and len(dependencies)==len(condition["コードSHA256"])
         and all(sha(Path(path).read_bytes())==value for path,value in dependencies.items()),"99固定金融コード一致")
    need(sha(SAVED_PATH.read_bytes())==SAVED_SHA and sha(VIEWER_PATH.read_bytes())==VIEWER_SHA,"99保存/表示停止コード")
    result,audit,viewer=(load(raw[name]) for name in ("result","audit","viewer"))
    comparisons=validate(result,audit,viewer,condition,evaluations,sha(raw["result"]),sha(raw["audit"]),SAVED_SHA)
    body=render(result,evaluations,comparisons,audit,viewer).encode("utf-8")
    generated={"README.md":"# 00099：背景と現在の勢いと数量で順行を選ぶ・実行結果\n\n".encode()+body+"\n## 固定した原計画\n\n".encode()+BEGIN+readme+b"\n"+END,
               "設定と結果.md":"# 99：設定と結果（全54場実行後）\n\n".encode()+body+"\n## 固定した設定計画・版5\n\n".encode()+BEGIN+settings+b"\n"+END}
    content={name:sha(raw[name]) for name in ("result","audit","viewer","condition","plan")}
    content.update(readme_plan=sha(readme),settings_plan=sha(settings),保存器=SAVED_SHA,表示器=VIEWER_SHA,報告コード=sha(Path(__file__).read_bytes()),固定98完了=PROOF98_SHA)
    for name,expected in (("README.md",condition["README計画SHA256"]),("設定と結果.md",condition["設定表計画SHA256"])):
        need(sha(original(generated[name],expected))==expected,"REPORT99生成後原bytes復元")
    before.update(dependencies);before.update(result["入力依存SHA256前後"])
    for path in (SAVED_PATH,VIEWER_PATH,OLD_PATH,PROOF98,Path(__file__)):before[str(path.resolve())]=sha(path.read_bytes())
    need(all(sha(Path(path).read_bytes())==value for path,value in before.items()),"99生成前後全入力差")
    return generated,content,before


def main():
    """
    機能: 成功済み7Pathから新規2報告を生成又は同じbytesを再照合する。
    引数: --result/--audit/--viewer/--condition/--plan/--readme/--settings/--out(Path)、--run/--check。
    返り値: None。未完/未確定/差/既存生成先は非0。
    """
    parser=argparse.ArgumentParser(description=__doc__);mode=parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--run",action="store_true");mode.add_argument("--check",action="store_true")
    names=("result","audit","viewer","condition","plan","readme","settings")
    for name in names+("out",):parser.add_argument("--"+name,type=Path,required=True)
    args=parser.parse_args();generated,content,before=prepare({name:getattr(args,name) for name in names})
    outputs={name:sha(body) for name,body in generated.items()}
    if args.run:
        need(not args.out.exists(),"99新規報告dirのみ");args.out.mkdir(parents=True)
        for name,body in generated.items():(args.out/name).write_bytes(body)
        proof={"試行":99,"成功":True,"入力内容SHA256":content,"観測入力SHA256前後":before,"出力SHA256":outputs,"原計画復元":True,
               "版5":{"手法":55,"尺度":9,"設定":38,"評価":12},"金融/Source/チャート再生成":False,"原板/API/Go金融再生":0,
               "未参加/退出後仮想利益/回収率":"未算出・処理0回"}
        (args.out/"報告生成.json").write_text(json.dumps(proof,ensure_ascii=False,indent=2,allow_nan=False)+"\n",encoding="utf-8",newline="\n")
    else:
        proof=load((args.out/"報告生成.json").read_bytes())
        need(proof["成功"] is True and proof["入力内容SHA256"]==content and proof["出力SHA256"]==outputs,"99報告証拠内容差")
        for name,body in generated.items():need((args.out/name).read_bytes()==body,"99報告bytes差:"+name)
    need(all(sha(Path(path).read_bytes())==value for path,value in before.items()),"99報告後入力差")
    print(json.dumps({"成功":True,"mode":"run" if args.run else "check","原計画復元":True,"出力SHA256":outputs},ensure_ascii=False))


if __name__=="__main__":main()
