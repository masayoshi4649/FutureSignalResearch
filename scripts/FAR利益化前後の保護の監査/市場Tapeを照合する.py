"""100の固定TapeをP0/H0/HG独立金融へ渡す。未固定Runtime/条件は本文前に拒否する。"""

import argparse
from concurrent.futures import ProcessPoolExecutor,as_completed
import importlib.util
import json
from pathlib import Path
import re
import sys

ROOT=Path(__file__).resolve().parents[2]
OLD_PATH=ROOT/"scripts/FAR背景と勢いと数量の監査/市場Tapeを照合する.py"
OLD_SHA="55abf75a6d8b924ad22a96b57d2399e524005c004e4ee77944fdd43addadad81"
COUPLED_PATH=ROOT/"scripts/FAR利益化前後の保護の監査/費用前ガードと金融の照合.py"
COUPLED_SHA="d6b2eb4dc18c082f3acf39dbc2f74553b127e0e1491bd601671c7e50c17aa6e7"
PROOF99=ROOT/"study/00099_背景と現在の勢いと数量で順行を選ぶ/完了記録.json"
PROOF99_SHA="8c2a30e1073126038e2a6a9c370f945ac258164877be6a250afb1c683fbbf5c8"
FINANCIAL_STOP_PATH=ROOT/"study/00100_費用後利益化の前後で保護を分ける/金融prototypeの停止.json"
FINANCIAL_STOP_SHA="717db3c18a154c4b016611ffebf0d37b8db35e67217372a57cdc9f07899f103c"
# Rootの条件固定前にRuntime停止へ結合する。条件SHAは循環するためコードへ埋め込まない。
RUNTIME_STOP_SHA="56604d7fcf52c2d975d18f99557048779d46c8f63c8fa685ff4dade3d8ed8b6c"

def fixed(name, path, expected):
    """
    機能: 停止した配送guard又は独立金融器をSHA検査して読む。
    引数: name/expected(str)、path(Path)は識別名・固定指紋・コード先。
    返り値: moduleは読取監査部品。市場入力や原板をimport時に読まない。
    """
    import hashlib
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
        raise ValueError("固定コードSHA差:" + str(path))
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


OLD=fixed("固定99市場guard100",OLD_PATH,OLD_SHA)
COUPLED=fixed("100全金融と現在E3S",COUPLED_PATH,COUPLED_SHA)
BASE=COUPLED.BASE
need,digest,path_key,valid_sha,normalized_map=OLD.need,OLD.digest,OLD.path_key,OLD.valid_sha,OLD.normalized_map
PROOF98,PROOF98_SHA=OLD.PROOF98,OLD.PROOF98_SHA
PROOF97,PROOF97_SHA,PROOF96,PROOF96_SHA=OLD.PROOF97,OLD.PROOF97_SHA,OLD.PROOF96,OLD.PROOF96_SHA
MANIFEST,MANIFEST_SHA=OLD.MANIFEST,OLD.MANIFEST_SHA
CONTROLS={key for key in COUPLED.KEYS if key.startswith("H0_E3S_")}


def validate_metadata(index, completion, condition, stage, catalog):
    """
    機能: 場集合、12口座、G0四対照、条件、完成、前後指紋を本文前に検査する。
    引数: index/completion/condition/catalog(dict)、stage(str)は保存metadata。
    返り値: set[str]は許可2又は54場。旧P0/AB/Riskの成功を新100へ代用しない。
    """
    require_fixed100()
    need(stage in ("first2", "full54") and type(index.get("version")) is int and index["version"] == 1
         and index.get("stage") == stage, "100 index版/stage")
    expected = {"2026-09-21_Day", "2026-09-21_Night"} if stage == "first2" else set(catalog)
    need(len(catalog) == 54 and expected <= set(catalog), "固定99の許可54集合")
    entries = index.get("entries")
    need(type(entries) is list and len(entries) == len(expected), "index場数")
    for row in entries:
        need(type(row) is dict and set(row) == {"session", "path", "sha256"}
             and type(row["session"]) is str and type(row["path"]) is str and bool(row["path"])
             and valid_sha(row["sha256"]), "index全tag/型")
    ids = [row["session"] for row in entries]
    need(len(ids) == len(set(ids)) and set(ids) == expected, "index重複/欠落/対象外")
    validate_condition(condition)
    code = condition.get("コードSHA256")
    need(type(code) is dict and bool(code) and all(type(k) is str and k and valid_sha(v) for k, v in code.items()), "100固定コード辞書")
    need(completion.get("成功") is True and completion.get("stage") == stage
         and type(completion.get("場数")) is int and completion["場数"] == len(expected), "100完成/stage/場数")
    need(type(completion.get("口座/場")) is int and completion["口座/場"] == 12
         and type(completion.get("H0対99E3S全文比較/場")) is int
         and completion["H0対99E3S全文比較/場"] == 4, "100全12/H0旧99E3S四対照")
    need(completion.get("入力前後不変") is True and completion.get("コード前後不変") is True, "100完了前後flag")
    need(normalized_map(completion.get("入力前SHA256")) == normalized_map(completion.get("入力後SHA256")), "100入力前後集合差")
    need(normalized_map(completion.get("コード前SHA256")) == normalized_map(completion.get("コード後SHA256")), "100コード前後集合差")
    need(completion.get("Source再運転") is False and completion.get("チャート再計算") is False
         and type(completion.get("Raw/CSV読取")) is int and completion["Raw/CSV読取"] == 0, "100Tape配送scope")
    rows = completion.get("結果")
    need(type(rows) is list and len(rows) == len(expected), "100完了結果数")
    for row in rows:
        need(type(row) is dict and {"session", "path", "sha256"} <= set(row) <= {"session", "path", "sha256", "error"}, "100結果全tag")
        need(type(row["session"]) is str and type(row["path"]) is str and row["path"] and valid_sha(row["sha256"])
             and ("error" not in row or type(row["error"]) is str and row["error"] == ""), "100結果error/path/指紋")
    ids = [row["session"] for row in rows]
    need(len(ids) == len(set(ids)) and set(ids) == expected, "100完了結果集合差")
    return expected


def inspect_values(tape, value, old99):
    """
    機能: 全Tape12金融とH0旧99E3S/H0四金融の全文をそれぞれ検査する。
    引数: tape/value/old99(dict)は許可された保存値。人工scopeも保持する。
    返り値: dictは12会計と四対照。現在E3/E3Sは全check独立計算。
    """
    result = COUPLED.inspect_tape(tape, value)
    controls = COUPLED.compare_h0_99(value, old99)
    result["金融照合項目数"] = result["照合項目数"]
    result["照合項目数"] += controls["照合項目数"]
    result["H0対99E3S全文"] = controls
    return result


def inspect_task(task):
    """
    機能: 明示一場の全path/SHA/由来を検査し、停止12金融器へ配送する。
    引数: task(dict)はTape/100Native/旧99/98/97/96NativeのpathとSHA。
    返り値: dictは一場の照合と入力前後指紋。原板やGoは動かさない。
    """
    require_fixed100()
    paths = {name: Path(task[name]).resolve() for name in ("tape", "result", "native99", "native98", "native97", "native96")}
    before = {str(path): digest(path) for path in paths.values()}
    for name, path in paths.items():
        need(before[str(path)] == task[name + "_sha256"], task["session"] + ":" + name + " SHA差")
    tape, value, old99 = (BASE.load(paths[name]) for name in ("tape", "result", "native99"))
    need(tape.get("provenance") and not tape["scope"].startswith(("固定96Go型人工", "固定98Go型人工", "固定99Go型人工", "固定100Go型人工")), "市場Tapeには固定構築出典が必要")
    validate_envelope(tape, value, old99, task)
    result = inspect_values(tape, value, old99)
    need(all(digest(Path(path)) == expected for path, expected in before.items()), task["session"] + ":入力前後差")
    return {"session": task["session"], **result, "入力SHA256前後": before, "入力前後不変": True}


def require_fixed100():
    """
    機能: 99完了/金融停止/Runtime停止が未固定のまま本文を読む経路を閉じる。
    引数: なし。
    返り値: None。条件SHAは循環を避け、完了入力の実SHAで結ぶ。
    """
    need(all(valid_sha(value) for value in (PROOF99_SHA,FINANCIAL_STOP_SHA,RUNTIME_STOP_SHA)),"100固定proof/金融停止/Runtime停止が未結合")


def validate_condition(condition):
    """
    機能: 新100条件の固定宣言/本名12/四段由来を本文前に検査する。
    引数: condition(dict)は明示条件metadata。
    返り値: None。旧試行の成功や旧Keyを新12成功へ転用しない。
    """
    need(type(condition.get("試行")) is int and condition["試行"]==100
         and condition.get("市場損益を開く前の固定") is True
         and condition.get("固定99完了SHA256")==PROOF99_SHA and condition.get("固定98完了SHA256")==PROOF98_SHA
         and condition.get("固定97完了SHA256")==PROOF97_SHA and condition.get("固定96完了SHA256")==PROOF96_SHA
         and condition.get("金融停止SHA256")==FINANCIAL_STOP_SHA and condition.get("台帳SHA256")==MANIFEST_SHA,"100固定条件/proof/金融停止")
    keys=condition.get("全12Key")
    need(type(keys) is list and len(keys)==12 and all(type(key) is str for key in keys)
         and set(keys)==set(COUPLED.KEYS),"100本名P0/H0/HG全12Key")
    code=condition.get("コードSHA256")
    need(type(code) is dict and bool(code) and all(type(path) is str and path and valid_sha(h) for path,h in code.items()),"100固定code辞書")


def selected_catalog():
    """
    機能: 固定99/98/97/96/80の宣言から同じ既使用54集合を取得する。
    引数: なし。
    返り値: tupleは四段Native gzip指紋とstage index指紋。本文は展開しない。
    """
    require_fixed100()
    catalog98,catalog97,catalog96,indexes=OLD.selected_catalog()
    need(digest(PROOF99)==PROOF99_SHA,"固定99完了SHA差")
    proof=BASE.load(PROOF99)
    need(proof.get("試行")==99 and proof.get("比較保存完了") is True and proof.get("場数")==54,"正式99の54保存完了")
    catalog={}
    for name,value in proof["自己を除く正式指紋"].items():
        match=re.fullmatch(r"成果物/(\d{4}-\d{2}-\d{2}_(?:Day|Night))\.json\.gz",name.replace("\\","/"))
        if match:
            need(match[1] not in catalog and valid_sha(value),"99Native一意/指紋");catalog[match[1]]=value
    need(len(catalog)==54 and set(catalog)==set(catalog98)==set(catalog97)==set(catalog96),"99/98/97/96/80許可54集合差")
    for stage,name in (("first2","接続2場Tape台帳.json"),("full54","正式54Tape台帳.json")):
        need(proof["自己を除く正式指紋"][name]==indexes[stage],"旧99で使った固定Tape台帳差")
    return catalog,catalog98,catalog97,catalog96,indexes


def validate_envelope(tape,value,old99,task):
    """
    機能: 新100全field/全12/H0四対照と四段Native/Tapeの由来を検査する。
    引数: tape/value/old99/task(dict)は保存値と明示path/SHA。
    返り値: None。旧99G0対照や旧入力生成を新金融成功とはしない。
    """
    fields={"trial","version","session","contract","books","chart_grids","gate_assessments","shadows","feature_config","source_rows",
            "chart_end","quality","input96_provenance","input97_provenance","input98_provenance","input99_provenance",
            "tape_provenance","source_reexecuted","charts_recomputed","h0_99_match","actual_run_complete"}
    need(set(value)==fields and type(value["trial"]) is int and value["trial"]==100
         and type(value["version"]) is int and value["version"]==1 and value["actual_run_complete"] is True,"100全envelope/完成")
    need(value["source_reexecuted"] is False and value["charts_recomputed"] is False,"100Source/チャート新生成なし")
    need(value["session"]==old99["session"]==tape["session"]["id"]==task["session"],"index/Tape/100/99の場")
    need(old99["trial"]==99 and old99["version"]==1 and old99["actual_run_complete"] is True
         and old99["source_reexecuted"] is False and old99["charts_recomputed"] is False
         and set(old99["books"])==set(COUPLED.ENTRY.KEYS),"固定99の旧12完成")
    need(set(value["books"])==set(COUPLED.KEYS),"100本名12金融集合")
    match=value["h0_99_match"]
    need(set(match)=={"all","books","keys","excluded","scope"} and match["all"] is True
         and type(match["books"]) is int and match["books"]==4 and len(match["keys"])==4
         and set(match["keys"])==CONTROLS and match["excluded"]==[] and type(match["scope"]) is str,"H0旧99E3S四対照/除外0")
    for name in ("contract","chart_grids","shadows","feature_config","source_rows","chart_end","quality","input96_provenance","input97_provenance","input98_provenance"):
        need(COUPLED.TAPE.canonical(value[name])==COUPLED.TAPE.canonical(old99[name]),"固定99全文継承:"+name)
    p=value["input99_provenance"]
    need(set(p)=={"native_path","native_gzip_sha256","completion_sha256","old_empty_gate_98_match","old_actual_run_complete","scope"},"input99全tag")
    need(path_key(Path(p["native_path"]))==path_key(Path(task["native99"])) and p["native_gzip_sha256"]==task["native99_sha256"]
         and p["completion_sha256"]==PROOF99_SHA and p["old_empty_gate_98_match"]==old99["empty_gate_98_match"]
         and p["old_actual_run_complete"] is True,"固定99gzipと旧対照の由来")
    for number,proof_sha in ((98,PROOF98_SHA),(97,PROOF97_SHA),(96,PROOF96_SHA)):
        p=value[f"input{number}_provenance"]
        need(path_key(Path(p["native_path"]))==path_key(Path(task[f"native{number}"]))
             and p["native_gzip_sha256"]==task[f"native{number}_sha256"] and p["completion_sha256"]==proof_sha,f"固定{number}追加出典")
    p=value["input96_provenance"]
    need(p["tape_sha256"]==task["tape_sha256"] and path_key(Path(p["tape_path"]))==path_key(Path(task["tape"])),"固定96と同じTape")
    p=value["tape_provenance"]
    need(set(p)=={"path","sha256","capabilities","scope","source_input_provenance"},"100Tape出典全tag")
    need(path_key(Path(p["path"]))==path_key(Path(task["tape"])) and p["sha256"]==task["tape_sha256"]
         and p["capabilities"]==tape["capabilities"] and p["scope"]==tape["scope"]
         and old99["tape_provenance"]["sha256"]==task["tape_sha256"],"新100と旧99の同じTape")
    provenance=normalized_map(tape["provenance"])
    need(provenance.get(path_key(Path(task["native96"])))==task["native96_sha256"]
         and provenance.get(path_key(PROOF96))==PROOF96_SHA,"Tapeの固定96構築出典")


def prepare(index_path,run100,condition_path,stage):
    """
    機能: 未固定/不正条件を本文前で拒否し、運転7固定と独立追加入力を分ける。
    引数: index_path/run100/condition_path(Path)、stage(str)は明示保存先。
    返り値: tupleはtasks/開始指紋/入力分類。条件SHAは完了入力と前後辞書で閉じる。
    """
    require_fixed100();need(stage in ("first2","full54"),"100 stage")
    condition=BASE.load(condition_path);validate_condition(condition)
    need(digest(FINANCIAL_STOP_PATH)==FINANCIAL_STOP_SHA,"固定100金融停止SHA差")
    catalog99,catalog98,catalog97,catalog96,indexes=selected_catalog()
    need(digest(index_path)==indexes[stage],"固定99で使ったindex bytes")
    completion_path=(run100/"完了.json").resolve()
    index,completion=(BASE.load(path) for path in (index_path,completion_path))
    expected=validate_metadata(index,completion,condition,stage,catalog99)
    files={path.stem for path in run100.glob("*.json") if re.fullmatch(r"\d{4}-\d{2}-\d{2}_(Day|Night)",path.stem)}
    need(files==expected,"100Nativeの場集合")
    runtime_inputs={path_key(path):path.resolve() for path in (index_path,condition_path,PROOF99,PROOF98,PROOF97,PROOF96,MANIFEST)}
    extras={};tasks=[];outcomes={row["session"]:row for row in completion["結果"]}
    for row in index["entries"]:
        session=row["session"];tape=Path(row["path"]);tape=(tape if tape.is_absolute() else index_path.parent/tape).resolve()
        result=(run100/(session+".json")).resolve();declared=Path(outcomes[session]["path"])
        declared=(declared if declared.is_absolute() else ROOT/declared).resolve();need(path_key(result)==path_key(declared),"100完了結果の配置")
        task={"session":session,"tape":str(tape),"result":str(result),"tape_sha256":row["sha256"],"result_sha256":outcomes[session]["sha256"]}
        for number,proof,catalog in ((99,PROOF99,catalog99),(98,PROOF98,catalog98),(97,PROOF97,catalog97),(96,PROOF96,catalog96)):
            native=(proof.parent/"成果物"/(session+".json.gz")).resolve()
            task[f"native{number}"]=str(native);task[f"native{number}_sha256"]=catalog[session]
            (runtime_inputs if number==99 else extras)[path_key(native)]=native
        runtime_inputs[path_key(tape)]=tape;extras[path_key(result)]=result
        for name in ("tape","result","native99","native98","native97","native96"):
            need(digest(Path(task[name]))==task[name+"_sha256"],session+":保存SHA差:"+name)
        tasks.append(task)
    recorded=normalized_map(completion["入力前SHA256"])
    need(set(recorded)==set(runtime_inputs),"100運転の7固定+Tape+99Nativeの完全集合")
    for key,path in runtime_inputs.items():need(digest(path)==recorded[key],"100運転入力の現在SHA差:"+str(path))
    codes={key:path for key,(path,_) in OLD.OLD.OLD.validate_fixed_code(condition,completion).items()}
    imports=[Path(__file__).resolve(),OLD_PATH,OLD.OLD_PATH,OLD.OLD.OLD_PATH,COUPLED_PATH,COUPLED.ENTRY_PATH,COUPLED.PURE_PATH,
             Path(COUPLED.FIN.__file__),Path(COUPLED.TAPE.__file__),COUPLED.ENTRY.RISK_PATH,COUPLED.FIN.TECH_PATH,
             COUPLED.FIN.OLD_PATH,COUPLED.FIN.OLD.OLD_PATH,COUPLED.FIN.OLD.OLD.BASE_PATH,COUPLED.BASE.BASE_PATH]
    for path in [completion_path,FINANCIAL_STOP_PATH]+imports:extras[path_key(path)]=path
    all_inputs={**runtime_inputs,**extras,**codes}
    groups={"100運転入力SHA256":{str(path):digest(path) for path in runtime_inputs.values()},
            "独立監査追加入力SHA256":{str(path):digest(path) for path in extras.values()},
            "条件固定コードSHA256":{str(path):digest(path) for path in codes.values()}}
    return sorted(tasks,key=lambda task:task["session"]),{str(path):digest(path) for path in all_inputs.values()},groups


def main():
    """
    機能: 完了100Nativeを12金融と旧99E3S/H0四対照へProcessPool配送する。
    引数: --index/--run100/--condition/--out(Path)、--stage(first2/full54)、--workers(int,1..8)。
    返り値: None。未固定/未完/差は非0。原板/CSV/Go金融/Source再生は0。
    """
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("index", "run100", "condition", "out"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--stage", choices=("first2", "full54"), required=True)
    parser.add_argument("--workers", type=int, choices=range(1, 9), default=1)
    args = parser.parse_args()
    before, rows, errors, groups = {}, [], [], {}
    try:
        require_fixed100()
        need(not args.out.exists(), "新規照合先だけ")
        tasks, before, groups = prepare(args.index.resolve(), args.run100.resolve(), args.condition.resolve(), args.stage)
        with ProcessPoolExecutor(max_workers=args.workers) as pool:
            futures = {pool.submit(inspect_task, task): task["session"] for task in tasks}
            for future in as_completed(futures):
                session = futures[future]
                try:
                    rows.append(future.result())
                    print("100 Tape独立照合 " + session + " 差0", flush=True)
                except Exception as error:
                    errors.append({"session": session, "error": str(error)})
        need(not errors and len(rows) == len(tasks), "100単場の未完/差")
        need(all(digest(Path(path)) == expected for path, expected in before.items()), "100全入力/コードの前後差")
        result = {"試行": 100, "成功": True, "stage": args.stage, "場数": len(rows), "会計数": sum(row["会計数"] for row in rows),
                  "H0対99E3S全文会計": sum(row["H0対99E3S全文"]["対照会計"] for row in rows),
                  "照合項目数": sum(row["照合項目数"] for row in rows), "新callback": sum(row["技法"]["新callback"] for row in rows),
                  "不一致数": 0, "details": sorted(rows, key=lambda row: row["session"]), "入力コードSHA256前後": before,
                  "入力コード前後不変": True, **groups, "監査コードSHA256": digest(Path(__file__)),
                  "固定99完了SHA256": PROOF99_SHA, "金融停止SHA256": FINANCIAL_STOP_SHA, "由来100再生接続の停止SHA256": RUNTIME_STOP_SHA,
                  "workers": args.workers, "原板/CSV/Go金融再生": 0, "Source/チャート再生成": False,
                  "限定": "P0/H0/HG全12と現在E3Sは固定Tapeから独立再計算。H0四つは旧99E3S/H0へ全文対照。旧G0/P0/AB/Riskの成功を100へ代用しない。Source/チャートは固定96/97/98/99構築証拠へ依存。"}
    except Exception as error:
        result = {"試行": 100, "成功": False, "stage": args.stage, "不整合": str(error), "単場エラー": errors,
                  "完了場数": len(rows), "入力コードSHA256開始": before, "原板/CSV/Go金融再生": 0}
    need(not args.out.exists(), "既存照合証拠は上書き不可")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({name: result[name] for name in ("成功", "場数", "会計数", "照合項目数", "不整合") if name in result}, ensure_ascii=False))
    if not result["成功"]:
        raise SystemExit(1)


if __name__=="__main__":main()

