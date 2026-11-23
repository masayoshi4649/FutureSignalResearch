"""固定97H0と同じTapeを、98の24金融独立器へ渡す読取ラッパー。実行許可は別に限定する。"""

import argparse
from concurrent.futures import ProcessPoolExecutor,as_completed
import importlib.util
import json
from pathlib import Path
import re
import sys


ROOT=Path(__file__).resolve().parents[2]
OLD_PATH=ROOT/"scripts/FAR初回利益確定の監査/市場Tapeを照合する.py"
OLD_SHA="640ee4a3d38c552ef146ec7325bd094a998c92a1ef839fd8cc5dfbc404f649a1"
RISK_PATH=Path(__file__).with_name("初期ATR追尾の金融照合.py")
RISK_SHA="ab8d6fd7245f6fe1d9528a4f81b1eeb532820bd80ea514d36c624d2c41839161"
PROOF97=ROOT/"study/00097_初回費用後利益の全量確定/完了記録.json"
PROOF97_SHA="0d7111c41c4c25140be69fe8b06d0118496ddd6de3bc9ac7467ec2f01f6aef79"


def fixed(name,path,expected):
    """
    機能: 停止済みの配送guard又は全金融独立器をSHA確認して再用する。
    引数: name/expected(str)、path(Path)は識別名・指紋・保存先。
    返り値: moduleは保存読取部品。原板/Go/Sourceを実行しない。
    """
    import hashlib
    if hashlib.sha256(path.read_bytes()).hexdigest()!=expected:raise ValueError("固定監査SHA差:"+str(path))
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec);sys.modules[name]=module;spec.loader.exec_module(module)
    return module


OLD=fixed("固定97市場guard98",OLD_PATH,OLD_SHA)
RISK=fixed("固定98全金融の市場配送",RISK_PATH,RISK_SHA)
BASE=RISK.BASE
need,digest,path_key,valid_sha,normalized_map=OLD.need,OLD.digest,OLD.path_key,OLD.valid_sha,OLD.normalized_map
PROOF96,PROOF96_SHA,MANIFEST,MANIFEST_SHA=OLD.PROOF96,OLD.PROOF96_SHA,OLD.MANIFEST,OLD.MANIFEST_SHA


def selected_catalog():
    """
    機能: 固定97/96完了と80台帳の宣言だけから共通許可54場を抽出する。
    引数: なし。
    返り値: tuple[dict,dict,dict]は97/96のNative gzip指紋と固定stage index指紋。
    """
    catalog96=OLD.selected_catalog()
    need(digest(PROOF97)==PROOF97_SHA,"固定97完了SHA差")
    proof=BASE.load(PROOF97)
    need(proof["試行"]==97 and proof["比較保存完了"] is True and proof["場数"]==54,"正式97の54場完了")
    catalog={}
    for name,sha in proof["自己を除く正式指紋"].items():
        m=re.fullmatch(r"成果物/(\d{4}-\d{2}-\d{2}_(?:Day|Night))\.json\.gz",name.replace("\\","/"))
        if m:
            need(m[1] not in catalog and valid_sha(sha),"97 Nativeの一意/指紋")
            catalog[m[1]]=sha
    need(len(catalog)==54 and set(catalog)==set(catalog96),"固定97/96/80の54集合差")
    indexes={stage:proof["自己を除く正式指紋"][name] for stage,name in (("first2","接続2場Tape台帳.json"),("full54","正式54Tape台帳.json"))}
    need(all(valid_sha(h) for h in indexes.values()),"固定97で使ったindex指紋")
    return catalog,catalog96,indexes


def validate_metadata(index,completion,condition,stage,catalog):
    """
    機能: 本文を開く前にstage/集合/24口座/旧H0八対照/前後指紋を厳密検査する。
    引数: index/completion/condition/catalog(dict)、stage(str)は明示保存metadata。
    返り値: set[str]は許可場。未知期間・未完・旧P0への偽装は拒否する。
    """
    need(stage in ("first2","full54") and type(index.get("version")) is int and index["version"]==1
         and index.get("stage")==stage,"index版/stage")
    expected={"2026-09-21_Day","2026-09-21_Night"} if stage=="first2" else set(catalog)
    need(len(catalog)==54 and expected<=set(catalog),"許可54集合")
    entries=index.get("entries")
    need(type(entries) is list and len(entries)==len(expected),"index場数")
    for row in entries:
        need(type(row) is dict and set(row)=={"session","path","sha256"} and type(row["session"]) is str
             and type(row["path"]) is str and bool(row["path"]) and valid_sha(row["sha256"]),"index entry型/全tag")
    ids=[r["session"] for r in entries]
    need(len(ids)==len(set(ids)) and set(ids)==expected,"index重複/欠落/対象外")
    need(condition.get("試行")==98 and condition.get("固定97完了SHA256")==PROOF97_SHA
         and condition.get("固定96完了SHA256")==PROOF96_SHA and condition.get("台帳SHA256")==MANIFEST_SHA
         and condition.get("市場損益を開く前の固定") is True,"98/97/96/80固定条件")
    code=condition.get("コードSHA256")
    need(type(code) is dict and bool(code) and all(type(n) is str and n and valid_sha(h) for n,h in code.items()),"固定98コード辞書")
    need(completion.get("成功") is True and completion.get("stage")==stage and completion.get("場数")==len(expected),"98完了/stage/場数")
    need(completion.get("口座/場")==24 and completion.get("空Risk対97H0全文比較/場")==8,"98全24/旧97H0八対照")
    need(completion.get("入力前後不変") is True and completion.get("コード前後不変") is True,"完了前後flag")
    need(normalized_map(completion.get("入力前SHA256"))==normalized_map(completion.get("入力後SHA256")),"完了入力前後集合")
    need(normalized_map(completion.get("コード前SHA256"))==normalized_map(completion.get("コード後SHA256")),"完了コード前後集合")
    need(completion.get("Source再運転") is False and completion.get("チャート再計算") is False
         and type(completion.get("Raw/CSV読取")) is int and completion["Raw/CSV読取"]==0,"固定Tape運転範囲")
    results=completion.get("結果")
    need(type(results) is list and len(results)==len(expected),"完了結果数")
    for row in results:
        need(type(row) is dict and {"session","path","sha256"}<=set(row)<={"session","path","sha256","error"},"結果全tag")
        need(type(row["session"]) is str and type(row["path"]) is str and row["path"] and valid_sha(row["sha256"])
             and ("error" not in row or type(row["error"]) is str and row["error"]==""),"結果error/path/指紋")
    ids=[r["session"] for r in results]
    need(len(ids)==len(set(ids)) and set(ids)==expected,"完了結果集合")
    return expected


def validate_envelope(tape,value,old97,task):
    """
    機能: 98新envelopeの出典と空Risk対97H0を、固定97本文とTapeへ結ぶ。
    引数: tape/value/old97/task(dict)は保存入力と明示path/SHA。
    返り値: None。旧P0対96欄を新98の対照成功へ読み替えない。
    """
    fields={"version","session","contract","books","chart_grids","gate_assessments","shadows","feature_config","source_rows",
            "chart_end","quality","input96_provenance","input97_provenance","tape_provenance","source_reexecuted",
            "charts_recomputed","empty_risk_97_match","actual_run_complete"}
    need(set(value)==fields and value["version"]==1 and value["actual_run_complete"] is True,"98 envelope全tag/完了")
    need(value["source_reexecuted"] is False and value["charts_recomputed"] is False,"新Source/チャート生成なし")
    need(value["session"]==old97["session"]==tape["session"]["id"]==task["session"],"index/Tape/98/97の場")
    need(old97["version"]==1 and old97["actual_run_complete"] is True and old97["source_reexecuted"] is False
         and old97["charts_recomputed"] is False and set(old97["books"])==set(RISK.FIN.KEYS),"固定97旧16完了")
    need(set(value["books"])==set(RISK.KEYS),"新24金融集合")
    controls={k for k in RISK.KEYS if k.startswith("H0_")}
    matched=value["empty_risk_97_match"]
    need(set(matched)=={"all","books","keys","excluded","scope"} and matched["all"] is True and matched["books"]==8
         and len(matched["keys"])==8 and set(matched["keys"])==controls and matched["excluded"]==[],"空Riskの旧H0八対照/除外0")
    for name in ("contract","chart_grids","shadows","feature_config","source_rows","chart_end","quality","input96_provenance"):
        need(RISK.TAPE.canonical(value[name])==RISK.TAPE.canonical(old97[name]),"固定97からの全文継承:"+name)
    p=value["input97_provenance"]
    need(set(p)=={"native_path","native_gzip_sha256","completion_sha256","old_P0_96_match","old_actual_run_complete","scope"},"input97全tag")
    need(path_key(Path(p["native_path"]))==path_key(Path(task["native97"])) and p["native_gzip_sha256"]==task["native97_sha256"]
         and p["completion_sha256"]==PROOF97_SHA and p["old_actual_run_complete"] is True
         and p["old_P0_96_match"]==old97["P0_96_match"],"固定97gzip/旧対照の出典")
    p=value["input96_provenance"]
    need(path_key(Path(p["native_path"]))==path_key(Path(task["native96"])) and p["native_gzip_sha256"]==task["native96_sha256"]
         and p["completion_sha256"]==PROOF96_SHA and p["tape_sha256"]==task["tape_sha256"],"固定96由来/旧97と同じTape")
    need(path_key(Path(p["tape_path"]))==path_key(Path(task["tape"])),"継承Tape配置")
    p=value["tape_provenance"]
    need(set(p)=={"path","sha256","capabilities","scope","source_input_provenance"},"新Tape出典全tag")
    need(path_key(Path(p["path"]))==path_key(Path(task["tape"])) and p["sha256"]==task["tape_sha256"]
         and p["capabilities"]==tape["capabilities"] and p["scope"]==tape["scope"],"新Tape出典")
    provenance=normalized_map(tape["provenance"])
    need(provenance.get(path_key(Path(task["native96"])))==task["native96_sha256"]
         and provenance.get(path_key(PROOF96))==PROOF96_SHA,"Tapeの固定96入力出典")


def inspect_values(tape,value,old97):
    """
    機能: 同じ値を停止98全金融/純技法と空Risk旧97H0全文の2検査へ渡す。
    引数: tape/value/old97(dict)は人工又は別途許可済みの保存値。
    返り値: dictは24会計と旧H0八対照。手製baselineのscopeを保持する。
    """
    result=RISK.inspect_tape(tape,value)
    controls=RISK.compare_no_risk97(value,old97)
    result["金融照合項目数"]=result["照合項目数"]
    result["照合項目数"]+=controls["照合項目数"]
    result["空Risk対97H0全文"]=controls
    return result


def inspect_task(task):
    """
    機能: 明示一場の全path/SHA/envelopeを検査し、全24と旧H0八へ配送する。
    引数: task(dict)はsession/Tape/新Native/旧97/96のpathと期待SHA。
    返り値: dictは単場監査と入力前後指紋。原板/Source/Goは動かさない。
    """
    paths={n:Path(task[n]).resolve() for n in ("tape","result","native97","native96")}
    before={str(p):digest(p) for p in paths.values()}
    for name,p in paths.items():need(before[str(p)]==task[name+"_sha256"],task["session"]+":"+name+" SHA差")
    tape,value,old97=(BASE.load(paths[n]) for n in ("tape","result","native97"))
    need(tape.get("provenance") and not tape["scope"].startswith(("固定96Go型人工","固定98Go型人工")),"市場Tapeの固定出典が必要")
    validate_envelope(tape,value,old97,task)
    result=inspect_values(tape,value,old97)
    need(all(digest(Path(p))==h for p,h in before.items()),task["session"]+":入力前後差")
    return {"session":task["session"],**result,"入力SHA256前後":before,"入力前後不変":True}


def prepare(index_path,run98,condition_path,stage):
    """
    機能: 固定index/98完了/条件と実code指紋を閉じてProcessPool taskを作る。
    引数: index_path/run98/condition_path(Path)、stage(str)は明示保存先。
    返り値: tuple[list,dict]はtaskと開始指紋。市場実行の許可は別に要する。
    """
    catalog97,catalog96,index_shas=selected_catalog()
    need(digest(index_path)==index_shas[stage],"固定97で使ったindex bytes")
    completion_path=(run98/"完了.json").resolve()
    index,condition,completion=(BASE.load(p) for p in (index_path,condition_path,completion_path))
    expected=validate_metadata(index,completion,condition,stage,catalog97)
    files={p.stem for p in run98.glob("*.json") if re.fullmatch(r"\d{4}-\d{2}-\d{2}_(Day|Night)",p.stem)}
    need(files==expected,"実98 Nativeの場集合")
    inputs={path_key(p):p.resolve() for p in (index_path,condition_path,PROOF97,PROOF96,MANIFEST)}
    tasks=[];outcomes={r["session"]:r for r in completion["結果"]}
    for row in index["entries"]:
        session=row["session"];tp=Path(row["path"])
        tp=(tp if tp.is_absolute() else index_path.parent/tp).resolve()
        result=(run98/(session+".json")).resolve()
        declared=Path(outcomes[session]["path"]);declared=(declared if declared.is_absolute() else ROOT/declared).resolve()
        need(path_key(result)==path_key(declared),"完了98結果の配置")
        native97=(PROOF97.parent/"成果物"/(session+".json.gz")).resolve()
        native96=(PROOF96.parent/"成果物"/(session+".json.gz")).resolve()
        for path,sha in ((tp,row["sha256"]),(result,outcomes[session]["sha256"]),(native97,catalog97[session])):
            need(digest(path)==sha,session+":保存入力SHA差")
        for path in (tp,native97):inputs[path_key(path)]=path
        tasks.append({"session":session,"tape":str(tp),"result":str(result),"native97":str(native97),"native96":str(native96),
                      "tape_sha256":row["sha256"],"result_sha256":outcomes[session]["sha256"],"native97_sha256":catalog97[session],"native96_sha256":catalog96[session]})
    recorded=normalized_map(completion["入力前SHA256"])
    need(set(recorded)==set(inputs),"98運転が読んだ入力の完全集合")
    for key,path in inputs.items():need(digest(path)==recorded[key],"運転入力の現在SHA差:"+str(path))
    for task in tasks:
        for name in ("result","native96"):
            path=Path(task[name]);need(digest(path)==task[name+"_sha256"],"監査追加入力SHA差")
            inputs[path_key(path)]=path
    for path,sha in OLD.validate_fixed_code(condition,completion).values():inputs[path_key(path)]=path
    for path in (completion_path,Path(__file__).resolve(),OLD_PATH,RISK_PATH,RISK.FIN_PATH,RISK.TAPE_PATH,
                 RISK.FIN.OLD_PATH,RISK.FIN.TECH_PATH,RISK.FIN.OLD.OLD_PATH,RISK.FIN.OLD.OLD.BASE_PATH,RISK.BASE.BASE_PATH):
        inputs[path_key(path)]=path
    return sorted(tasks,key=lambda t:t["session"]),{str(p):digest(p) for p in inputs.values()}


def main():
    """
    機能: 完了98 Nativeを全24独立金融と旧97H0へProcessPoolで配送する。
    引数: --index/--run98/--condition/--out(Path)、--stage(first2/full54)、--workers(int,1..8)。
    返り値: None。成功以外は非0。金融/純技法/Source/原板を追加生成しない。
    """
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ("index","run98","condition","out"):parser.add_argument("--"+name,type=Path,required=True)
    parser.add_argument("--stage",choices=("first2","full54"),required=True)
    parser.add_argument("--workers",type=int,choices=range(1,9),default=1)
    args=parser.parse_args();need(not args.out.exists(),"新規監査先だけ")
    before,rows,errors={},[],[]
    try:
        tasks,before=prepare(args.index.resolve(),args.run98.resolve(),args.condition.resolve(),args.stage)
        with ProcessPoolExecutor(max_workers=args.workers) as pool:
            futures={pool.submit(inspect_task,t):t["session"] for t in tasks}
            for future in as_completed(futures):
                session=futures[future]
                try:
                    rows.append(future.result());print("98 Tape独立照合 "+session+" 差0",flush=True)
                except Exception as error:errors.append({"session":session,"error":str(error)})
        need(not errors and len(rows)==len(tasks),"単場監査の未完/差")
        need(all(digest(Path(p))==h for p,h in before.items()),"全入力/コードの前後差")
        result={"成功":True,"stage":args.stage,"場数":len(rows),"会計数":sum(r["会計数"] for r in rows),
                "空Risk対97H0全文会計":sum(r["空Risk対97H0全文"]["対照会計"] for r in rows),
                "照合項目数":sum(r["照合項目数"] for r in rows),"新callback":sum(r["技法"]["新callback"] for r in rows),
                "不一致数":0,"details":sorted(rows,key=lambda r:r["session"]),"入力コードSHA256前後":before,"入力コード前後不変":True,
                "workers":args.workers,"原板/CSV/Go金融再生":0,"Source/チャート再生成":False,
                "限定":"24金融は固定Tapeから独立再構成。空risk8は旧97H0の正式gzipへ除外0比較し、旧P0と呼ばない。原板/Source/指標形成は固定96/97の構築証拠へ依存。"}
    except Exception as error:
        result={"成功":False,"stage":args.stage,"不整合":str(error),"単場エラー":errors,"完了場数":len(rows),"入力コードSHA256開始":before,"原板/CSV/Go金融再生":0}
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8",newline="\n")
    print(json.dumps({n:result[n] for n in ("成功","場数","会計数","照合項目数","不整合") if n in result},ensure_ascii=False))
    if not result["成功"]:raise SystemExit(1)


if __name__=="__main__":main()
