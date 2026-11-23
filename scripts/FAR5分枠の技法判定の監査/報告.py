"""96の全完了証拠から事前本文を保持する報告案を生成する。市場再生はしない。"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from decimal import Decimal
import gzip
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import types


ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT / "study/00096_5分枠の順行反転と現在数量"
FIXED = ROOT / "scripts/FAR5分判断と出生一回の監査/報告.py"
FIXED_SHA = "c39b8db431edd1ee448b277c273ea1c995d2b8a478b80ce4e16202830eb61c39"
if hashlib.sha256(FIXED.read_bytes()).hexdigest() != FIXED_SHA:
    raise ValueError("固定95報告部品のSHA差")
SPEC = importlib.util.spec_from_file_location("96の固定95報告復元",FIXED)
OLD = importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(OLD)
need,sha,load,fmt = OLD.need,OLD.sha,OLD.load,OLD.fmt
AGG_SHA = "32f7931f75f4b6241ced26e1f4b4014c332711c0948de104093762d01c73d750"
GATE_SHA = "b5d1af7fb85d4446a47573a4389abfa433177189cb01d901bdd53a8a38b8d5e6"
VIEW_SHA = "4e2f937ee25267ae9ce39df35444f50a5aca7edb5faf7c7f45155539b127ce30"
RAW_SHA = "7f673b29f27bc8f79e2c0c2e6106dc457a4697f283fdb64a7cddafa4e3210658"
CHART_SHA = "3aa0cfa58b8efd130c95b2fcfddfd8cec4cab26b2f7226123d234f17a30c9c72"
CONDITION_SHA = "24e1d04d51f0204d2bfb76728411abac2188d4a3f1097d9d25a3f0d83b4e65c9"
README_SHA = "c1cc97f058d7884122b86f24b82e57e0bb8b0f7115ee54057d7faac1be16fd6a"
SETTINGS_SHA = "d8c8a56b62d193a0b750962239a87ec9e118cbd91c841160541959b663e28b4d"
PLAN_SHA = "b8de17e7dd01599ec661699f687086dc32fea83b63975f1f13e4810c7b90d965"
PROOF95 = "b7df0d9f793fca1ee9fbb489e045b927f8cf4b46e0e81a6c199920f128e4d943"
AMENDMENT_SHA = "1acdaa3f33b8c8930137a71a83679c7535758116cadafc35cc81f82f7c8a6ca0"
KEYS = tuple(("" if p=="G0" else p+"_")+f"B5Q_P0_C{c}_D{d}"
             for p in ("G0","A","B","AB") for c in (0,5) for d in (0,1))
INPUT_NAMES = ("result","raw","chart","viewer","inputs_before","inputs","condition","readme","settings","amendment")
MARKERS = {name:getattr(OLD,name).replace("REPORT95","REPORT96") for name in
           ("PLAN_BEGIN","PLAN_END","STATE_BEGIN","STATE_END","RESULT_BEGIN","RESULT_END")}
globals().update(MARKERS)
namespace = dict(vars(OLD.OLD));namespace.update(MARKERS)
original = types.FunctionType(OLD.OLD.original.__code__,namespace,"96原計画の不変復元")


def label(key: str) -> str:
    """
    機能: 16keyの表示政策を返す。
    引数: key(str)。
    返り値: str。
    """
    need(key in KEYS,"96報告Actor")
    return "G0" if key.startswith("B5Q_") else key.split("_")[0]


def link(path: Path) -> str:
    """
    機能: 正式基準相対リンク。
    引数: path(Path)。
    返り値: str。
    """
    return os.path.relpath(path.resolve(),STUDY).replace("\\","/")


def plans(readme: Path, settings: Path) -> dict:
    """
    機能: 事前全文/35設定/55×9セル/16評価を固定SHAで検査する。
    引数: readme/settings(Path)は原文又はmarker付き生成文書。
    返り値: dict[str,str]は原文。元の未実行記述は変更しない。
    """
    result={name:original(path.read_text(encoding="utf-8"),expected) for name,path,expected in
            (("readme",readme,README_SHA),("settings",settings,SETTINGS_SHA))}
    text=result["settings"]
    cells=[s for s in text.splitlines() if re.match(r"^\| [ICPVXBME]\d{2} \|",s)]
    need(len(cells)==55 and all(len(s.split("|"))==13 for s in cells),"55×9の固定原表")
    need(len(re.findall(r"^\| (?:S|N|T)\d{2} \|",text,re.M))==35,"35固定設定")
    rows=re.findall(r"^\| (R\d{2}) \|[^\n]+",text,re.M)
    need(rows==[f"R{i:02}" for i in range(1,17)],"事前16評価")
    actor_rows=[s.split("|")[3].strip() for s in text.splitlines() if re.match(r"^\| R\d{2} \|",s)]
    need(actor_rows==list(KEYS),"原16評価と口座の順序")
    return result


def valid_pf(value, positive, negative) -> bool:
    """
    機能: PFの未定義と保存JSON比率を金額の厳密比較から分けて確認する。
    引数: value(number|None)、positive/negative(number)は保存比率/実玉正額/負額。
    返り値: boolはDecimal比を保存floatへ丸めた表現と一致するか。
    """
    if not negative:return value is None
    return type(value) in (int,float,Decimal) and float(value)==float(positive/-negative)


def mapped_name(mapping: dict, name: str, expected: str) -> None:
    """
    機能: 証拠の指紋辞書へ指定codeが一意に結ばれているか確認する。
    引数: mapping(dict)、name/expected(str)はbasenameと固定SHA。
    返り値: None。異版や同名混入なら停止する。
    """
    found=[value for path,value in mapping.items() if Path(path).name==name]
    need(found==[expected],"正本codeの指紋結合:"+name)


def validate_amendment(amendment: dict) -> None:
    """
    機能: 表記だけの正式補足と再接続証拠を検査する。
    引数: amendment(dict)はRootが固定した補足JSON。
    返り値: None。金融core/条件の変更や再接続未完了を受け付けない。
    """
    need(amendment["試行"]==96 and amendment["成功"] is True and amendment["金融core26/固定条件不変"] is True and
         amendment["固定条件SHA256"]==CONDITION_SHA and amendment["新市場再生"]==0 and amendment["原板追加読取"]==0,"表記補足の固定条件")
    changes=amendment["変更"]
    for name,new_sha in (("技法の保存照合.py",GATE_SHA),("表示監査.py",VIEW_SHA),("出生枠と金融の照合.py",RAW_SHA),("原板から照合する.py",CHART_SHA)):
        need(changes[name]["新SHA256"]==new_sha,"補足の新版:"+name)
    need(changes["技法の保存照合.py"]["旧SHA256"]=="71363cfa968beb634e44eaa0851cedbcda0a9b985d3f34dcef31a275b0e49588" and
         changes["表示監査.py"]["旧SHA256"]=="35e2791b38aa6849e52690eb37f202794bfd8186cdba0909323d790c858c28b4","旧接続当時版を保持")
    for name in ("技法の保存照合.py","人工と破損を確認する.py"):
        need(changes[name]["関数説明を除くAST同体"] is True,"説明以外のAST不変")
    for name in ("Go人工の再接続.json","表示人工の再接続.json"):
        need(amendment[name]["成功"] is True and re.fullmatch(r"[0-9a-f]{64}",amendment[name]["SHA256"]) is not None,"補足の人工再接続")


def validate_result(result: dict) -> set[str]:
    """
    機能: 正式54/864保存結果と実績分母を検査する。
    引数: result(dict)は固定32fの保存結果。
    返り値: set[str]は54場。接続/人工は正式報告へ渡さない。
    """
    need(result["試行"]==96 and result["成功"] is True and result["scope"]=="正式" and
         result["場数"]==54 and result["Actor数"]==16 and result["会計数"]==864,"正式96保存864会計")
    need(result["集計コードSHA256"]==AGG_SHA and result["技法照合コードSHA256"]==GATE_SHA and
         result["基準95完了SHA256"]==PROOF95 and result["入力前後不変"] is True and
         result["入力SHA256前"]==result["入力SHA256後"]==result["入力SHA256"],"保存停止/入力指紋")
    need(set(result["集計"])==set(result["実現診断"])==set(result["Actor設定"])==set(KEYS),"16口座集合")
    identities={(r["session"],r["key"]) for r in result["場別"]};sessions={s for s,_ in identities}
    need(len(sessions)==54 and len(identities)==len(result["場別"])==864 and identities=={(s,k) for s in sessions for k in KEYS},"全場全口座一意")
    need(set(result["入力SHA256"])=={s+".json" for s in sessions},"Native54保存集合")
    dates={s[:10] for s in sessions}
    need(len(dates)==27 and all({d+"_Day",d+"_Night"}<=sessions for d in dates) and
         all("2026-09-21"<=d<="2026-10-27" for d in dates),"既使用27日54場")
    matches=result["G0四会計の固定95対照"]
    need(len(matches)==54 and {r["session"] for r in matches}==sessions and all(
        r["基準完了SHA256"]==PROOF95 and r["G0除外field"]==[] and set(r["一致口座"])=={k for k in KEYS if label(k)=="G0"} for r in matches),"G0全216の旧95全文")
    for key in KEYS:
        a,d=result["集計"][key],result["実現診断"][key]
        for ours,theirs in (("玉数","positions"),("新規枚数","entry_quantity"),("粗額円","gross_yen"),("指定手数料円","fee_yen"),
                           ("仮定滑り円","slip_yen"),("純額円","net_yen"),("u正益玉","unit_positive_positions"),("W正益玉","whole_positive_positions")):
            need(d[ours]==a[theirs],"保存/実現診断:"+key+"/"+ours)
        need(d["正額円"]+d["負額円"]==d["純額円"] and d["黒字玉"]+d["赤字玉"]+d["同額玉"]==d["玉数"],"全実玉分母")
        need(valid_pf(d["PF"],d["正額円"],d["負額円"]),"PFの分母/保存JSON表現")
        for p in ("u","W"):
            need(d[p+"正益後最終赤字玉"]+d[p+"正益未観測赤字玉"]==d["赤字玉"] and
                 d[p+"正益後最終赤字額円"]+d[p+"正益未観測赤字額円"]==d["負額円"],"実損失の正益観測分解")
    return sessions


def native_groups(folder: Path, result: dict) -> dict:
    """
    機能: 保存Nativeから元kindと当時受理roleを実取得へ結ぶ。
    引数: folder(Path)は96圧縮保存、result(dict)は固定保存集計。
    返り値: dictは実玉/受理の小型群とSHA。Rawや未参加の将来を読まない。
    """
    kinds,roles=defaultdict(lambda:defaultdict(Decimal)),defaultdict(lambda:defaultdict(Decimal))
    hashes={};slot_roles=Counter();scene_stats={}
    for name,expected in sorted(result["入力SHA256"].items()):
        path=(folder/(name+".gz")).resolve();need(path.is_relative_to(folder.resolve()),"Native保存境界")
        body=path.read_bytes();hashes[str(path)]=hashlib.sha256(body).hexdigest();plain=gzip.decompress(body)
        need(hashlib.sha256(plain).hexdigest()==expected,"圧縮Native内容と集計指紋")
        value=json.loads(plain,parse_float=Decimal,parse_constant=lambda x:(_ for _ in ()).throw(ValueError(x)))
        need(value["session"]+".json"==name and set(value["books"])==set(KEYS),"Native場/16口座")
        for key,book in value["books"].items():
            by_order={p["entry_order_id"]:p for p in book["entry_opportunities"] if p["status"]=="accepted"}
            need(len(by_order)==sum(p["status"]=="accepted" for p in book["entry_opportunities"]),"受理OrderID一意")
            for opportunity in by_order.values():
                gate=opportunity.get("gate");role=gate["role"] if gate else "G0・技法採否なし"
                need((gate is None) == (label(key)=="G0"),"G0/新技法の受理gate有無")
                if gate:need(gate["known"] is True and gate["allowed"] is True and role in ("順行","反転"),"受理時の成立role")
                slot_roles[key+"/"+role]+=1
            total=Decimal(0)
            for p in book["positions"]:
                need(p["quantity"]==p["reserved"]==0 and p["entry_order_id"] in by_order,"完結実玉と受理出典")
                opportunity=by_order[p["entry_order_id"]]
                need(opportunity["source"]==p["source"] and opportunity["side"]==p["side"],"元出生と実玉")
                role=opportunity["gate"]["role"] if "gate" in opportunity else "G0・技法採否なし"
                for target in (kinds[key+"/"+p["source"]["method"]+"/"+p["source"]["kind"]],roles[key+"/"+role]):
                    target["玉数"]+=1;target["新規枚数"]+=p["initial_quantity"];target["純額円"]+=p["realized_net"]
                total+=p["realized_net"]
            equal_row=next(r for r in result["場別"] if r["session"]==value["session"] and r["key"]==key)
            need(total==equal_row["totals"]["net_yen"] and len(book["positions"])==equal_row["counts"]["positions"],"群と保存実現額")
            scene_stats[(value["session"],key)]={"純額円":total,"玉数":len(book["positions"])}
    need(all(sha(Path(p))==v for p,v in hashes.items()),"Native群の前後不変")
    return {"元手法と元kind":{k:dict(v) for k,v in kinds.items()},"成立role実取得":{k:dict(v) for k,v in roles.items()},
            "成立role受理要求":dict(slot_roles),"入力SHA256":hashes,"入力前後不変":True,
            "場統計":{key:{"取引あり場":sum(v["玉数"]>0 for (s,k),v in scene_stats.items() if k==key),
                           "黒字場":sum(v["純額円"]>0 for (s,k),v in scene_stats.items() if k==key),
                           "赤字場":sum(v["純額円"]<0 for (s,k),v in scene_stats.items() if k==key)} for key in KEYS}}


def prepare(args) -> dict:
    """
    機能: 全54/864・金融Raw・chart numeric・Viewer・入力前後が完了した正本だけを受け取る。
    引数: args(Namespace)は10明示Path/Native dir/任意flow証拠。
    返り値: dictは生成context。欠落や接続2場では正式生成しない。
    """
    paths={name:getattr(args,name).resolve() for name in INPUT_NAMES};physical={name:sha(path) for name,path in paths.items()}
    need(physical["amendment"]==AMENDMENT_SHA,"正式表記訂正JSONのSHA")
    validate_amendment(load(paths["amendment"]))
    need(physical["condition"]==CONDITION_SHA,"96事前固定条件SHA")
    condition=load(paths["condition"])
    need(condition["README計画SHA256"]==README_SHA and condition["設定表計画SHA256"]==SETTINGS_SHA and condition["計画SHA256"]==PLAN_SHA,"条件の元計画SHA")
    plan=plans(paths["readme"],paths["settings"])
    result,raw,chart,viewer,before,after=(load(paths[n]) for n in INPUT_NAMES[:6])
    sessions=validate_result(result)
    need(raw["成功"] is True and raw["セッション数"]==54 and raw["会計数"]==864 and raw["G0基準会計数"]==216 and
         raw["不一致数"]==0 and raw["入力前後不変"] is True and len(raw["details"])==54 and {r["session"] for r in raw["details"]}==sessions,"全54の金融Raw/出生境界")
    for row in raw["details"]:
        need(row["成功"] is True and row["会計数"]==16 and row["G0基準会計数"]==4 and row["不一致数"]==0 and row["入力前後不変"] is True,"金融Raw各場")
        found=[v for p,v in row["入力SHA256"].items() if Path(p).name==row["session"]+".json"]
        need(len(found)==1 and found[0]==result["入力SHA256"][row["session"]+".json"],"Raw/Native同値")
    mapped_name(raw["コード入力SHA256"],"出生枠と金融の照合.py",RAW_SHA)
    mapped_name(raw["コード入力SHA256"],"技法の保存照合.py",GATE_SHA)
    need(chart["成功"] is True and chart["場数"]==chart["予定場数"]==54 and chart["入力不変"] is True and
         chart["入力前SHA256"]==chart["入力後SHA256"] and chart["集計"]["不一致数"]==0 and
         len(chart["場別"])==54 and {r["session"] for r in chart["場別"]}==sessions,"全54chart numeric")
    mapped_name(chart["入力前SHA256"],"原板から照合する.py",CHART_SHA)
    for session in sessions:
        found=[v for p,v in chart["入力前SHA256"].items() if Path(p).name==session+".json"]
        need(len(found)==1 and found[0]==result["入力SHA256"][session+".json"],"chart/Native指紋")
    need(viewer["試行"]==96 and viewer["成功"] is True and viewer["scope"]=="正式" and viewer["予定資源"]==viewer["完了資源"]==864 and
         viewer["全資源検証完了"] is True and viewer["不一致数"]==0 and not viewer["APIエラー"] and viewer["入力不変"] is True and
         viewer["結果SHA256"]==physical["result"] and viewer["監査コードSHA256"]==VIEW_SHA,"864Viewer保存会計")
    need(before==after and after["試行"]==96 and after["場数"]==54 and after["固定95完了SHA256"]==PROOF95 and after["コード"]==condition["コードSHA256"],"入力前後の全文辞書")
    for name,count in {"原入力":324,"純戦略":43,"固定93コード":11,"固定94コード":13,"固定95コード":15,"固定93正本":313,"固定94正本":726,"固定95正本":728,"コード":26}.items():
        need(len(after[name])==count,"固定依存分母:"+name)
    native=native_groups(args.native.resolve(),result)
    flow={"状態":"未検証","説明":"板量支持Currentの原板独立再計算を示す別証拠は未入力。保存技法式と時刻BBOの照合から全面再計算済とはしない。"}
    if getattr(args,"flow",None) is not None:
        paths["flow"]=args.flow.resolve();physical["flow"]=sha(paths["flow"])
        extra=load(paths["flow"])
        flow={"状態":"別証拠を参照","説明":"提供されたflowの検証範囲と限界を参照。この報告器自身はflow値を原板から再計算しない。","成功":extra.get("成功"),"path":str(paths["flow"])}
    normalized={str(path):physical[name] for name,path in paths.items()}
    normalized[str(paths["readme"])]=README_SHA;normalized[str(paths["settings"])]=SETTINGS_SHA
    return {"paths":paths,"physical":physical,"normalized":normalized,"plans":plan,"result":result,"raw":raw,"chart":chart,
            "viewer":viewer,"inputs":after,"native":native,"flow":flow,"fixture":False}


def outcome(context: dict) -> str:
    """
    機能: 黒字/赤字/同額/無取引/PF未定義を別に数える。
    引数: context(dict)は保存実現診断を含む。
    返り値: strは口座分類。0やPF未定義を安定利益と呼ばない。
    """
    rows=context["result"]["実現診断"].values()
    positive=sum(d["純額円"]>0 for d in rows);negative=sum(d["純額円"]<0 for d in rows)
    zero=sum(d["純額円"]==0 for d in rows);empty=sum(d["玉数"]==0 for d in rows);undefined=sum(d["PF"] is None for d in rows)
    need(positive+negative+zero==16,"全16口座の符号分母")
    return f"16口座の費用後実現額は黒字{positive}・赤字{negative}・同額{zero}。うち無取引{empty}、PF未定義{undefined}。0取引やPF未定義を安定利益と扱わず、未知期間の安定性は未証明。"


def tables(context: dict, short: bool) -> str:
    """
    機能: 実現額/利益後赤字/回数枚数と現在技法の分母を表示する。
    引数: context(dict)、short(bool)はREADME用の短縮指定。
    返り値: strは実取得中心のMarkdown。未参加の仮想利益を計算しない。
    """
    result,native=context["result"],context["native"]
    lines=["## 実行後の比較", "", "**"+outcome(context)+"**", "",
           "全16はB5Q/P0。G0は追加採否なし、Aは順行、Bは反転確認、ABは三値OR。Sourceの元方向は変更しない。C0は指定手数料のみ、C5は片道5pt仮定を保護起動にも用いる別運転で、同じ取引への後付け費用ではない。", "",
           "| 評価/Actor | 実玉/枚 | gross円 | 指定fee円 | 仮定slip円 | net円 | 正額/負額円 | PF |",
           "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for i,key in enumerate(KEYS,1):
        d=result["実現診断"][key]
        lines.append(f"| R{i:02}/{key} | {fmt(d['玉数'])}/{fmt(d['新規枚数'])} | {fmt(d['粗額円'])} | {fmt(d['指定手数料円'])} | {fmt(d['仮定滑り円'])} | {fmt(d['純額円'])} | {fmt(d['正額円'])}/{fmt(d['負額円'])} | {fmt(d['PF'],3)} |")
    lines += ["", "PF=完結実玉の正純額÷負純額絶対値、負純額0なら未定義。正負は各玉の最終netで分け、指標単独効果へ帰属しない。", "",
              "| Actor | u後赤字/正益玉 | u後赤字額円 | u未観測赤字玉/額円 | W後赤字/正益玉 | W後赤字額円 | W未観測赤字玉/額円 | 保存極値連結DD円 |",
              "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for key in KEYS:
        d=result["実現診断"][key]
        lines.append(f"| {key} | {fmt(d['u正益後最終赤字玉'])}/{fmt(d['u正益玉'])} | {fmt(d['u正益後最終赤字額円'])} | {fmt(d['u正益未観測赤字玉'])}/{fmt(d['u正益未観測赤字額円'])} | {fmt(d['W正益後最終赤字玉'])}/{fmt(d['W正益玉'])} | {fmt(d['W正益後最終赤字額円'])} | {fmt(d['W正益未観測赤字玉'])}/{fmt(d['W正益未観測赤字額円'])} | {fmt(d['保存極値を連結した最大DD円'])} |")
    lines += ["", "uは費用後の残玉1枚現在益、Wは実現純額＋残玉評価。正益後最終赤字額は該当玉の最終net合計で、正益からの減少額ではない。未観測は観測間欠も含み得る。DDは保存場内極値/DDをflat場境界で連結した値で、保存集計だけを全面原板再計算と呼ばない。名目建値床は次正常原行の費用後約定額を保証しない。", "",
              "### 当枠での技法採否と実取得", "",
              "| Actor | 技法成立/既知拒否/必要未知 | 技法前金融判定・EOF | 成立A/Bの受理要求 | 成立A/Bの実取得玉 | 取引あり/黒字/赤字場 |",
              "| --- | ---: | ---: | ---: | ---: | ---: |"]
    calls=result["Gate呼出分母"]
    for key in KEYS:
        c=[calls.get(key+"/"+n,0) for n in ("成立","既知不成立","未知")]
        accepted=[native["成立role受理要求"].get(key+"/"+n,0) for n in ("順行","反転")]
        filled=[native["成立role実取得"].get(key+"/"+n,{}).get("玉数",0) for n in ("順行","反転")]
        stats=native["場統計"][key]
        prior=fmt(calls.get(key+'/技法前の金融判定又はEOF',0)) if label(key)!='G0' else '対象外'
        lines.append(f"| {key} | {'/'.join(fmt(v) for v in c) if label(key)!='G0' else '対象外'} | {prior} | {'/'.join(fmt(v) for v in accepted) if label(key)!='G0' else '対象外'} | {'/'.join(fmt(v) for v in filled) if label(key)!='G0' else '対象外'} | {stats['取引あり場']}/{stats['黒字場']}/{stats['赤字場']} |")
    lines += ["", "技法は旧quiet・取得済Source・返済予約なし・正常気配・余力の後だけを評価する。成立した受理要求と実取得は別の分母で、後のSource取消を成功約定へ変えない。G0は技法を使わないため、技法成立0を実新規0と読まない。G0のgateなしcounterを金融拒否件数とも扱わず、この列も対象外とする。各費用/遅延のcallback回数は重複する局面を含み、独立市場例数ではない。", ""]
    if not short:
        lines += ["### 主C0D0の個別check", "", "| Actor/check | 成立 | 既知不成立 | 未知 |", "| --- | ---: | ---: | ---: |"]
        for name,row in result["Gate条件採否"].items():
            if "_C0_D0/" not in name:continue
            lines.append(f"| {name} | {fmt(row.get('成立',0))} | {fmt(row.get('既知不成立',0))} | {fmt(row.get('未知',0))} |")
        lines += ["", "個別checkの否定/未知は重なり得る。ANDは既知否定優先、ABは既知成立優先ORで、全checkの未知数をそのまま判定不能数へ加算しない。他費用/遅延の全checkは結果JSONを参照する。", "",
                  "### 元手法・元kindで成立した実玉", "", "| Actor/元手法/元kind | 玉/枚 | 最終net円 |", "| --- | ---: | ---: |"]
        for name,row in native["元手法と元kind"].items():
            lines.append(f"| {name.replace('|','/')} | {fmt(row['玉数'])}/{fmt(row['新規枚数'])} | {fmt(row['純額円'])} |")
        lines += ["", "Source.kindは元出生の初回/追加等の段階であり、実口座の初参加を意味しない。成立A/Bは当時受理Opportunityと実EntryOrderIDから結び、最終保有状態から推測しない。", "",
                  "### 実現額差の分解", "", "| B対G0 | 同実入口/取得変更 | G0のみ/Bのみ | 全差円 | 同実差/取得変更差円 |", "| --- | ---: | ---: | ---: | ---: |"]
        for name,parts in result["同実入口と実現額差"].items():
            columns={n:sum(p[n] for p in parts) for n in ("同実入口","取得変更","Aのみ","Bのみ","全差円","同実入口差円","取得変更差円","Aのみ円","Bのみ円")}
            need(columns["全差円"]==columns["同実入口差円"]+columns["取得変更差円"]-columns["Aのみ円"]+columns["Bのみ円"],"比較の全差帰属")
            lines.append(f"| {name} | {columns['同実入口']}/{columns['取得変更']} | {columns['Aのみ']}/{columns['Bのみ']} | {fmt(columns['全差円'])} | {fmt(columns['同実入口差円'])}/{fmt(columns['取得変更差円'])} |")
        lines += ["", "実取得・容量・参加が変わった差を同じ出口だけの効果と呼ばない。未参加側の仮想利益や退出後の仮想利益は計算しない。", ""]
    lines += ["量支持の追加検査：**"+context["flow"]["状態"]+"**。"+context["flow"]["説明"], ""]
    return "\n".join(lines)


def render(context: dict, name: str) -> str:
    """
    機能: 元計画を一字不変のmarker内へ置き、状態/結果を別段へ追加する。
    引数: context(dict)、name(str)はreadme/settings。
    返り値: strは新規本文。元の未実行は作成時点の記述と明記する。
    """
    fixture=context.get("fixture",False)
    status="人工表示fixture・正式生成未実施" if fixture else "実行済み"
    header=f"# 00096：5分枠の順行反転と現在数量{'・設定と結果' if name=='settings' else ''}（{status}）\n\n"
    header += "**"+outcome(context)+"**\n\n"
    header += ("人工の型・表示・原文復元だけを検査しており、正式54場の完了を主張しない。\n\n" if fixture else
               "54既使用場・16口座/864会計の保存、金融/出生Raw、独立チャートnumeric、Viewerの照合を正本に結んだ。量支持Currentの追加独立再計算は下の別項目で範囲を分ける。\n\n")
    header += "下の事前全文内の『未実行』は作成時点の記録。35設定・55×9セル・R01〜R16を変更せず、現在の実績を末尾に記録する。共通保護・Source方向・数量・費用は固定し、未参加/決済後の仮想利益は評価しない。元FAR全面同値=falseを維持する。\n\n"
    body=tables(context,name=="readme")
    if not fixture:
        p=context["paths"];raw=context["raw"];chart=context["chart"];viewer=context["viewer"]
        body += ("\n### 正本と検査範囲\n\n"
                 f"- [保存会計]({link(p['result'])})・[Viewer一覧]({link(p['result'].with_name('一覧.resources.json'))})。G0全216は旧95B5Qへ除外0で全文一致。\n"
                 f"- [金融/出生Raw]({link(p['raw'])})：54場/864会計、{fmt(raw['照合項目数'])}項目差0。旧金融全正常原行MTM・Source通知・出生一枠・当時Current時刻/BBOとgate採否の結合。\n"
                 f"- [独立チャートnumeric]({link(p['chart'])})：54場、{fmt(chart['集計']['照合数'])}項目差0。公開値・未知mask・場間numeric種/roll・欠足/足公開・同時計順を検査。未知の0を既知数値一致へ加えない。\n"
                 f"- [Viewer]({link(p['viewer'])})：864資源、{fmt(viewer['照合項目数'])}項目差0。保存全約定/半円/最終所有0。\n"
                 f"- [入力前]({link(p['inputs_before'])})・[入力後]({link(p['inputs'])})：324入力/純43/旧95正本728/旧コード等と新core26の辞書全文一致。\n"
                 f"- [監査コードの補足と表記訂正]({link(p['amendment'])})：関数説明以外のASTと金融core26/条件を固定。正式54は新gate/Viewer指紋、既済み接続2場は当時713/35等の指紋を保持し、過去証拠を新指紋へ書き替えない。\n"
                 "- [条件](条件.json)・[検証計画](検証計画.md)・[再現](再現手順.md)・[設定と結果](設定と結果.md)。\n\n"
                 "CurrentPriceTimeは価格項目の時計で、独立した受信時刻ではない。同時刻TOPIX先行は再生規則で、真の両市場到着順は検証不能。ラージBBOをmini約定代理にし、実mini流動性と片道5ptの実測は未確認。54場は既使用で探索外ではない。\n")
    return STATE_BEGIN+header+STATE_END+"\n<details>\n<summary>固定した事前計画・35設定（作成時点の未実行記述）</summary>\n\n"+PLAN_BEGIN+context["plans"][name]+PLAN_END+"\n</details>\n\n"+RESULT_BEGIN+body+RESULT_END


def serial(value):
    """
    機能: 半円とPathを証拠JSONへ保存。
    引数: value(object)。
    返り値: 数値/str。
    """
    if isinstance(value,Decimal) and value.is_finite():
        return int(value) if value==value.to_integral_value() else float(value)
    if isinstance(value,Path):return str(value)
    raise TypeError(type(value).__name__)


def self_test() -> dict:
    """
    機能: 架空表示contextと実事前計画でmarker・ゼロ分母・欠落拒否を検査する。
    引数: なし。正式54/Raw/Viewer/原板/金融は読み込まない。
    返り値: dictは表示型の人工証拠。架空の金融監査成功を作らない。
    """
    plan=plans(STUDY/"README.md",STUDY/"設定と結果.md")
    diagnostics={};groups={};stats={}
    count_fields=("u正益玉","W正益玉","u正益後最終赤字玉","W正益後最終赤字玉","u正益後最終赤字額円","W正益後最終赤字額円",
                  "u正益未観測赤字玉","W正益未観測赤字玉","u正益未観測赤字額円","W正益未観測赤字額円")
    for i,key in enumerate(KEYS):
        d={name:Decimal(0) for name in count_fields}
        net=Decimal(100 if i==0 else -100 if i==1 else 0);qty=4 if i==0 else 2 if i==1 else 1 if i==2 else 0
        positions=2 if i==0 else 1 if i in (1,2) else 0;slip=int(key.split("_")[-2][1:])
        pos,neg=(Decimal(150),Decimal(-50)) if i==0 else (Decimal(0),net)
        d.update({"玉数":positions,"新規枚数":qty,"粗額円":net+77*qty+200*slip*qty,"指定手数料円":77*qty,"仮定滑り円":200*slip*qty,
                  "純額円":net,"正額円":pos,"負額円":neg,"PF":pos/-neg if neg else None,"保存極値を連結した最大DD円":Decimal(125) if i<2 else Decimal(0)})
        if i==0:
            for p in ("u","W"):d.update({p+"正益玉":2,p+"正益後最終赤字玉":1,p+"正益後最終赤字額円":-50})
        if i==1:
            for p in ("u","W"):d.update({p+"正益未観測赤字玉":1,p+"正益未観測赤字額円":-100})
        diagnostics[key]=d
        groups[key]={"positions":positions,"entry_quantity":qty,"net_yen":net}
        stats[key]={"取引あり場":int(positions>0),"黒字場":int(net>0),"赤字場":int(net<0)}
    context={"fixture":True,"plans":plan,"result":{"実現診断":diagnostics,"集計":groups,"Gate呼出分母":{},"Gate条件採否":{},"同実入口と実現額差":{}},
             "native":{"成立role受理要求":{},"成立role実取得":{},"元手法と元kind":{},"場統計":stats},
             "flow":{"状態":"未検証","説明":"人工表示fixture。独立flow証拠を与えていない。"}}
    expected="黒字1・赤字1・同額14。うち無取引13、PF未定義14"
    need(expected in outcome(context),"黒字/赤字/0/無取引/PFの別分母")
    outputs={name:render(context,name) for name in ("readme","settings")}
    for name,body in outputs.items():
        original(body,README_SHA if name=="readme" else SETTINGS_SHA)
        need("人工表示fixture・正式生成未実施" in body and "未定義" in body and "未検証" in body,"人工/未定義/未検証の明示")
    checks=["55×9/35設定/16評価の原文SHA復元","黒字1/赤字1/同額14/無取引13/PF未定義14","flow未検証を全面成功としない"]
    need(valid_pf(Decimal(str(float(Decimal(1)/3))),Decimal(1),Decimal(-3)) and valid_pf(None,0,0) and
         not valid_pf(0,0,0) and not valid_pf(True,1,-1),"PF保存float/未定義/数値型")
    checks.append("PF1/3の保存JSON丸めと分母0/偽boolの区別")
    for name,change in (("marker重複",lambda text:text+PLAN_BEGIN),("marker欠落",lambda text:text.replace(PLAN_END,"",1)),
                        ("事前T01の変更",lambda text:text.replace("T01","T99",1))):
        try:original(change(outputs["settings"]),SETTINGS_SHA)
        except ValueError:checks.append(name+"拒否")
        else:raise AssertionError(name+"を受理")
    # ----------------------------------------
    # 既読接続の結果だけで、54完了条件の拒否を確認します。
    connection=ROOT/"work/96保存監査/実2場_停止版/結果.json"
    before={str(STUDY/"README.md"):sha(STUDY/"README.md"),str(STUDY/"設定と結果.md"):sha(STUDY/"設定と結果.md"),str(Path(__file__)):sha(Path(__file__))}
    amendment_path=STUDY/"監査コードの補足と表記訂正.json"
    need(sha(amendment_path)==AMENDMENT_SHA,"人工で使う正式補足のSHA")
    before[str(amendment_path)]=AMENDMENT_SHA
    amendment=load(amendment_path);validate_amendment(amendment)
    amendment["金融core26/固定条件不変"]=False
    try:validate_amendment(amendment)
    except ValueError:checks.append("金融core不変falseの補足を拒否")
    else:raise AssertionError("補足破損を受理")
    if connection.is_file():
        before[str(connection)]=sha(connection)
        try:validate_result(load(connection))
        except ValueError:checks.append("接続32を正式864として生成しない")
        else:raise AssertionError("接続を正式と誤認")
        need(load(connection)["技法照合コードSHA256"]=="71363cfa968beb634e44eaa0851cedbcda0a9b985d3f34dcef31a275b0e49588" and
             GATE_SHA!="71363cfa968beb634e44eaa0851cedbcda0a9b985d3f34dcef31a275b0e49588","旧接続を新指紋へ置換しない")
        checks.append("旧接続713と正式新版b5を別管理")
    need(all(sha(Path(p))==v for p,v in before.items()),"人工/原計画/code前後不変")
    return {"成功":True,"scope":"表示contextと既読接続の型/原文復元。正式54生成未実施","検査":checks,"原文SHA256":{"README.md":README_SHA,"設定と結果.md":SETTINGS_SHA},
            "marker本文SHA256":{name:hashlib.sha256(body.encode()).hexdigest() for name,body in outputs.items()},"入力SHA256":before,"入力前後不変":True,
            "原板/金融/API":0,"正式文書編集":0,"コードSHA256":sha(Path(__file__))}


def main() -> None:
    """
    機能: 人工確認又は全証拠完了後の2文書/証拠を新規生成する。
    引数: --self-test又は10必須入力Path/--native(dir)/任意--flow/--out/--check。
    返り値: None。正式文書を上書きせず、生成はRootが全完了後に実行する。
    """
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test",action="store_true")
    for name in INPUT_NAMES:parser.add_argument("--"+name.replace("_","-"),dest=name,type=Path)
    parser.add_argument("--native",type=Path);parser.add_argument("--flow",type=Path)
    parser.add_argument("--out",type=Path,required=True);parser.add_argument("--check",action="store_true")
    args=parser.parse_args()
    if args.self_test:
        need(not args.check and all(getattr(args,n) is None for n in INPUT_NAMES) and args.native is None and args.flow is None,"人工へ実入力を渡さない")
        need(not args.out.exists(),"新規人工証拠先")
        proof=self_test();args.out.parent.mkdir(parents=True,exist_ok=True)
        args.out.write_text(json.dumps(proof,ensure_ascii=False,indent=2,default=serial)+"\n",encoding="utf-8")
        print(json.dumps({"成功":True,"scope":"人工表示のみ","検査":len(proof["検査"])},ensure_ascii=False));return
    need(all(getattr(args,n) is not None for n in INPUT_NAMES) and args.native is not None,"全正式証拠とNative保存dirを明示")
    need(args.out.exists() if args.check else not args.out.exists(),"新規生成先/check既存だけ")
    ctx=prepare(args)
    outputs={"README.md":render(ctx,"readme"),"設定と結果.md":render(ctx,"settings")}
    for name,expected in (("README.md",README_SHA),("設定と結果.md",SETTINGS_SHA)):original(outputs[name],expected)
    proof={"試行":96,"成功":True,"生成対象":list(outputs),"正規化入力SHA256":ctx["normalized"],"原計画SHA256":{"README.md":README_SHA,"設定と結果.md":SETTINGS_SHA},
           "出力SHA256":{name:hashlib.sha256(body.encode()).hexdigest() for name,body in outputs.items()},"生成コードSHA256":sha(Path(__file__)),"固定95報告部品SHA256":FIXED_SHA,
           "全495セルと35設定と16評価":"固定原計画SHA復元で不変","実結果":outcome(ctx),"元kindと当時成立role":ctx["native"],"flow検査範囲":ctx["flow"],
           "金融/原板/APIの再実行":0,"機会損失/退出後仮想利益":0,"元FAR全面同値":False,"未知安定性":"未証明"}
    if args.check:
        for name,text in outputs.items():need((args.out/name).read_bytes()==text.encode("utf-8"),"再生成文書差:"+name)
        need(load(args.out/"生成証拠.json")==proof,"再生成証拠差")
        for name in ("readme","settings"):
            text=ctx["paths"][name].read_text(encoding="utf-8")
            if PLAN_BEGIN in text:need(text==outputs["README.md" if name=="readme" else "設定と結果.md"],"生成済み入力の手修正差")
    else:
        args.out.mkdir(parents=True)
        for name,text in outputs.items():(args.out/name).write_bytes(text.encode("utf-8"))
        (args.out/"生成証拠.json").write_text(json.dumps(proof,ensure_ascii=False,indent=2,default=serial)+"\n",encoding="utf-8")
    need(all(sha(ctx["paths"][name])==expected for name,expected in ctx["physical"].items()),"生成入力前後差")
    print(json.dumps({"成功":True,"check":args.check,"事前全文復元":True,"出力SHA256":proof["出力SHA256"]},ensure_ascii=False))


if __name__=="__main__":main()
