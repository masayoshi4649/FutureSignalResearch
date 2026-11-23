"""未採番99の公開Tapeを12金融独立器へ配送する。98完了未固定の間は市場入力読取前に拒否する。"""

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import importlib.util
import json
from pathlib import Path
import re
import sys


ROOT = Path(__file__).resolve().parents[2]
OLD_PATH = ROOT / "scripts/FAR利益前ATR追尾の監査/市場Tapeを照合する.py"
OLD_SHA = "2c60e08261cc06df30a55f819ce096abb8e9dcb32fb0394e7ffacbb5c500c694"
COUPLED_PATH = ROOT / "scripts/FAR背景と勢いと数量の監査/E3と金融の照合.py"
COUPLED_SHA = "75dc5309c3e9c0b79d094df7941be4b2b5c206f0bb0d51740fd33a448cbcf834"
PROOF98 = ROOT / "study/00098_実建値からの利益前ATR追尾/完了記録.json"
# Rootが正式98完了後に結ぶ。空の間はmetadataを含む市場入力を一切読まない。
PROOF98_SHA = "2ee9417d0cd1f8bef107712789d26e3f72c0f95a933e60b31bb3f11784ca0dfe"
RUNTIME_STOP_SHA = "97a567aed620f8288305acc8fb6fb3753d8aa18caa29d3c714ef8975977d962c"


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


OLD = fixed("固定98市場guard99", OLD_PATH, OLD_SHA)
COUPLED = fixed("本名E3金融99市場配送", COUPLED_PATH, COUPLED_SHA)
BASE = COUPLED.BASE
need, digest, path_key, valid_sha, normalized_map = OLD.need, OLD.digest, OLD.path_key, OLD.valid_sha, OLD.normalized_map
PROOF97, PROOF97_SHA, PROOF96, PROOF96_SHA = OLD.PROOF97, OLD.PROOF97_SHA, OLD.PROOF96, OLD.PROOF96_SHA
MANIFEST, MANIFEST_SHA = OLD.MANIFEST, OLD.MANIFEST_SHA
CONTROLS = {key for key in COUPLED.KEYS if key.startswith("H0_B5Q_")}


def require_fixed98():
    """
    機能: 未固定98のまま市場入力を読む経路を閉じる。
    引数: なし。
    返り値: None。空又は不正な指紋ならファイル読取前にValueError。
    """
    need(valid_sha(PROOF98_SHA), "正式98完了SHAが未固定のため99市場照合は禁止です")


def selected_catalog():
    """
    機能: 固定98/97/96完了と80台帳の宣言から同じ許可54場を結ぶ。
    引数: なし。
    返り値: tupleは98/97/96のNative gzip指紋と既存stage index指紋。
    """
    require_fixed98()
    catalog97, catalog96, indexes = OLD.selected_catalog()
    need(digest(PROOF98) == PROOF98_SHA, "固定98完了SHA差")
    proof = BASE.load(PROOF98)
    need(proof.get("試行") == 98 and proof.get("比較保存完了") is True
         and type(proof.get("場数")) is int and proof["場数"] == 54, "正式98の54場保存完了")
    catalog = {}
    for name, value in proof["自己を除く正式指紋"].items():
        match = re.fullmatch(r"成果物/(\d{4}-\d{2}-\d{2}_(?:Day|Night))\.json\.gz", name.replace("\\", "/"))
        if match:
            need(match[1] not in catalog and valid_sha(value), "98 Native集合/指紋")
            catalog[match[1]] = value
    need(len(catalog) == 54 and set(catalog) == set(catalog97) == set(catalog96), "98/97/96/80の54集合差")
    for stage, name in (("first2", "接続2場Tape台帳.json"), ("full54", "正式54Tape台帳.json")):
        need(proof["自己を除く正式指紋"][name] == indexes[stage], "98で使った固定Tape台帳の差")
    return catalog, catalog97, catalog96, indexes


def validate_metadata(index, completion, condition, stage, catalog):
    """
    機能: 場集合、12口座、G0四対照、条件、完成、前後指紋を本文前に検査する。
    引数: index/completion/condition/catalog(dict)、stage(str)は保存metadata。
    返り値: set[str]は許可2又は54場。旧P0/AB/Riskの成功を新99へ代用しない。
    """
    require_fixed98()
    need(stage in ("first2", "full54") and type(index.get("version")) is int and index["version"] == 1
         and index.get("stage") == stage, "99 index版/stage")
    expected = {"2026-09-21_Day", "2026-09-21_Night"} if stage == "first2" else set(catalog)
    need(len(catalog) == 54 and expected <= set(catalog), "固定98の許可54集合")
    entries = index.get("entries")
    need(type(entries) is list and len(entries) == len(expected), "index場数")
    for row in entries:
        need(type(row) is dict and set(row) == {"session", "path", "sha256"}
             and type(row["session"]) is str and type(row["path"]) is str and bool(row["path"])
             and valid_sha(row["sha256"]), "index全tag/型")
    ids = [row["session"] for row in entries]
    need(len(ids) == len(set(ids)) and set(ids) == expected, "index重複/欠落/対象外")
    need(type(condition.get("試行")) is int and condition["試行"] == 99
         and condition.get("固定98完了SHA256") == PROOF98_SHA
         and condition.get("固定97完了SHA256") == PROOF97_SHA
         and condition.get("固定96完了SHA256") == PROOF96_SHA
         and condition.get("台帳SHA256") == MANIFEST_SHA
         and condition.get("市場損益を開く前の固定") is True, "99/98/97/96/80固定条件")
    code = condition.get("コードSHA256")
    need(type(code) is dict and bool(code) and all(type(k) is str and k and valid_sha(v) for k, v in code.items()), "99固定コード辞書")
    need(completion.get("成功") is True and completion.get("stage") == stage
         and type(completion.get("場数")) is int and completion["場数"] == len(expected), "99完成/stage/場数")
    need(type(completion.get("口座/場")) is int and completion["口座/場"] == 12
         and type(completion.get("空Gate対98H0全文比較/場")) is int
         and completion["空Gate対98H0全文比較/場"] == 4, "99全12/G0旧98H0四対照")
    need(completion.get("入力前後不変") is True and completion.get("コード前後不変") is True, "99完了前後flag")
    need(normalized_map(completion.get("入力前SHA256")) == normalized_map(completion.get("入力後SHA256")), "99入力前後集合差")
    need(normalized_map(completion.get("コード前SHA256")) == normalized_map(completion.get("コード後SHA256")), "99コード前後集合差")
    need(completion.get("Source再運転") is False and completion.get("チャート再計算") is False
         and type(completion.get("Raw/CSV読取")) is int and completion["Raw/CSV読取"] == 0, "99Tape配送scope")
    rows = completion.get("結果")
    need(type(rows) is list and len(rows) == len(expected), "99完了結果数")
    for row in rows:
        need(type(row) is dict and {"session", "path", "sha256"} <= set(row) <= {"session", "path", "sha256", "error"}, "99結果全tag")
        need(type(row["session"]) is str and type(row["path"]) is str and row["path"] and valid_sha(row["sha256"])
             and ("error" not in row or type(row["error"]) is str and row["error"] == ""), "99結果error/path/指紋")
    ids = [row["session"] for row in rows]
    need(len(ids) == len(set(ids)) and set(ids) == expected, "99完了結果集合差")
    return expected


def validate_envelope(tape, value, old98, task):
    """
    機能: 99全field、G0旧98対照、継承共有値と三段Native出典を検査する。
    引数: tape/value/old98/task(dict)は保存値と明示したpath/SHA。
    返り値: None。旧対照のflagを新E3採否/金融の期待値へ使わない。
    """
    fields = {"trial", "version", "session", "contract", "books", "chart_grids", "gate_assessments", "shadows", "feature_config",
              "source_rows", "chart_end", "quality", "input96_provenance", "input97_provenance", "input98_provenance",
              "tape_provenance", "source_reexecuted", "charts_recomputed", "empty_gate_98_match", "actual_run_complete"}
    need(set(value) == fields and type(value["trial"]) is int and value["trial"] == 99
         and type(value["version"]) is int and value["version"] == 1 and value["actual_run_complete"] is True, "99全envelope/完成")
    need(value["source_reexecuted"] is False and value["charts_recomputed"] is False, "99Source/チャート再生成なし")
    need(value["session"] == old98["session"] == tape["session"]["id"] == task["session"], "index/Tape/99/98の場")
    need(old98["version"] == 1 and old98["actual_run_complete"] is True and old98["source_reexecuted"] is False
         and old98["charts_recomputed"] is False and set(old98["books"]) == set(COUPLED.RISK.KEYS), "固定98の24金融完成")
    need(set(value["books"]) == set(COUPLED.KEYS), "99の本名12金融集合")
    matched = value["empty_gate_98_match"]
    need(set(matched) == {"all", "books", "keys", "excluded", "scope"} and matched["all"] is True
         and type(matched["books"]) is int and matched["books"] == 4 and len(matched["keys"]) == 4
         and set(matched["keys"]) == CONTROLS and matched["excluded"] == [] and type(matched["scope"]) is str,
         "空Gate旧98H0四対照/除外0")
    for name in ("contract", "chart_grids", "shadows", "feature_config", "source_rows", "chart_end", "quality", "input96_provenance", "input97_provenance"):
        need(COUPLED.TAPE.canonical(value[name]) == COUPLED.TAPE.canonical(old98[name]), "固定98の全文継承:" + name)
    provenance = value["input98_provenance"]
    need(set(provenance) == {"native_path", "native_gzip_sha256", "completion_sha256", "old_empty_risk_97_match", "old_actual_run_complete", "scope"}, "input98全tag")
    need(path_key(Path(provenance["native_path"])) == path_key(Path(task["native98"]))
         and provenance["native_gzip_sha256"] == task["native98_sha256"] and provenance["completion_sha256"] == PROOF98_SHA
         and provenance["old_empty_risk_97_match"] == old98["empty_risk_97_match"]
         and provenance["old_actual_run_complete"] is True, "固定98gzip/旧対照の由来")
    for number, proof_sha in ((97, PROOF97_SHA), (96, PROOF96_SHA)):
        provenance = value[f"input{number}_provenance"]
        need(path_key(Path(provenance["native_path"])) == path_key(Path(task[f"native{number}"]))
             and provenance["native_gzip_sha256"] == task[f"native{number}_sha256"]
             and provenance["completion_sha256"] == proof_sha, f"固定{number}の追加出典")
    provenance = value["input96_provenance"]
    need(provenance["tape_sha256"] == task["tape_sha256"] and path_key(Path(provenance["tape_path"])) == path_key(Path(task["tape"])), "固定96と同じTape")
    provenance = value["tape_provenance"]
    need(set(provenance) == {"path", "sha256", "capabilities", "scope", "source_input_provenance"}, "99Tape出典全tag")
    need(path_key(Path(provenance["path"])) == path_key(Path(task["tape"])) and provenance["sha256"] == task["tape_sha256"]
         and provenance["capabilities"] == tape["capabilities"] and provenance["scope"] == tape["scope"], "99Tape出典")
    need(old98["tape_provenance"]["sha256"] == task["tape_sha256"], "旧98も同じTape")
    source = normalized_map(tape["provenance"])
    need(source.get(path_key(Path(task["native96"]))) == task["native96_sha256"]
         and source.get(path_key(PROOF96)) == PROOF96_SHA, "Tapeの固定96構築出典")


def inspect_values(tape, value, old98):
    """
    機能: 全Tape12金融とG0旧98H0四金融の全文をそれぞれ検査する。
    引数: tape/value/old98(dict)は許可された保存値。人工scopeも保持する。
    返り値: dictは12会計と四対照。現在E3/E3Sは全check独立計算。
    """
    result = COUPLED.inspect_tape(tape, value)
    controls = COUPLED.compare_empty_gate98(value, old98)
    result["金融照合項目数"] = result["照合項目数"]
    result["照合項目数"] += controls["照合項目数"]
    result["空Gate対98H0全文"] = controls
    return result


def inspect_task(task):
    """
    機能: 明示一場の全path/SHA/由来を検査し、停止12金融器へ配送する。
    引数: task(dict)はTape/99Native/旧98/97/96NativeのpathとSHA。
    返り値: dictは一場の照合と入力前後指紋。原板やGoは動かさない。
    """
    require_fixed98()
    paths = {name: Path(task[name]).resolve() for name in ("tape", "result", "native98", "native97", "native96")}
    before = {str(path): digest(path) for path in paths.values()}
    for name, path in paths.items():
        need(before[str(path)] == task[name + "_sha256"], task["session"] + ":" + name + " SHA差")
    tape, value, old98 = (BASE.load(paths[name]) for name in ("tape", "result", "native98"))
    need(tape.get("provenance") and not tape["scope"].startswith(("固定96Go型人工", "固定98Go型人工", "固定99Go型人工")), "市場Tapeには固定構築出典が必要")
    validate_envelope(tape, value, old98, task)
    result = inspect_values(tape, value, old98)
    need(all(digest(Path(path)) == expected for path, expected in before.items()), task["session"] + ":入力前後差")
    return {"session": task["session"], **result, "入力SHA256前後": before, "入力前後不変": True}


def prepare(index_path, run99, condition_path, stage):
    """
    機能: 固定98未設定を先に拒否し、99運転入力と独立追加入力を分離して閉じる。
    引数: index_path/run99/condition_path(Path)、stage(str)は明示先。
    返り値: tuple[list,dict,dict]は単場task、開始指紋、入力分類。
    """
    require_fixed98()
    need(stage in ("first2", "full54"), "99 stage")
    catalog98, catalog97, catalog96, indexes = selected_catalog()
    need(digest(index_path) == indexes[stage], "固定98で使ったindex bytes")
    completion_path = (run99 / "完了.json").resolve()
    index, condition, completion = (BASE.load(path) for path in (index_path, condition_path, completion_path))
    expected = validate_metadata(index, completion, condition, stage, catalog98)
    files = {path.stem for path in run99.glob("*.json") if re.fullmatch(r"\d{4}-\d{2}-\d{2}_(Day|Night)", path.stem)}
    need(files == expected, "99Nativeの場集合")
    runtime_inputs = {path_key(path): path.resolve() for path in (index_path, condition_path, PROOF98, PROOF97, PROOF96, MANIFEST)}
    extras = {}
    tasks = []
    outcomes = {row["session"]: row for row in completion["結果"]}
    for row in index["entries"]:
        session = row["session"]
        tape = Path(row["path"])
        tape = (tape if tape.is_absolute() else index_path.parent / tape).resolve()
        result = (run99 / (session + ".json")).resolve()
        declared = Path(outcomes[session]["path"])
        declared = (declared if declared.is_absolute() else ROOT / declared).resolve()
        need(path_key(result) == path_key(declared), "99完了結果の配置")
        task = {"session": session, "tape": str(tape), "result": str(result),
                "tape_sha256": row["sha256"], "result_sha256": outcomes[session]["sha256"]}
        for number, proof, catalog in ((98, PROOF98, catalog98), (97, PROOF97, catalog97), (96, PROOF96, catalog96)):
            native = (proof.parent / "成果物" / (session + ".json.gz")).resolve()
            task[f"native{number}"] = str(native)
            task[f"native{number}_sha256"] = catalog[session]
            (runtime_inputs if number == 98 else extras)[path_key(native)] = native
        runtime_inputs[path_key(tape)] = tape
        extras[path_key(result)] = result
        for name in ("tape", "result", "native98", "native97", "native96"):
            need(digest(Path(task[name])) == task[name + "_sha256"], session + ":保存SHA差:" + name)
        tasks.append(task)
    recorded = normalized_map(completion["入力前SHA256"])
    need(set(recorded) == set(runtime_inputs), "99運転が読んだ六固定+Tape+98Nativeの完全集合")
    for key, path in runtime_inputs.items():
        need(digest(path) == recorded[key], "99運転入力の現在SHA差:" + str(path))
    codes = {key: path for key, (path, _) in OLD.OLD.validate_fixed_code(condition, completion).items()}
    imports = [Path(__file__).resolve(), OLD_PATH, OLD.OLD_PATH, COUPLED_PATH, COUPLED.PURE_PATH, COUPLED.PURE.TECH_PATH,
               COUPLED.FIN_PATH, COUPLED.TAPE_PATH, COUPLED.RISK_PATH, COUPLED.FIN.OLD_PATH,
               COUPLED.FIN.OLD.OLD_PATH, COUPLED.FIN.OLD.OLD.BASE_PATH, COUPLED.BASE.BASE_PATH]
    for path in [completion_path] + imports:
        extras[path_key(path)] = path
    all_inputs = {**runtime_inputs, **extras, **codes}
    groups = {"99運転入力SHA256": {str(path): digest(path) for path in runtime_inputs.values()},
              "独立監査追加入力SHA256": {str(path): digest(path) for path in extras.values()},
              "条件固定コードSHA256": {str(path): digest(path) for path in codes.values()}}
    return sorted(tasks, key=lambda task: task["session"]), {str(path): digest(path) for path in all_inputs.values()}, groups


def main():
    """
    機能: 完了99Nativeを12金融と旧98H0四対照へProcessPool配送する。
    引数: --index/--run99/--condition/--out(Path)、--stage(first2/full54)、--workers(int,1..8)。
    返り値: None。未固定/未完/差は非0。原板/CSV/Go金融/Source再生は0。
    """
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("index", "run99", "condition", "out"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--stage", choices=("first2", "full54"), required=True)
    parser.add_argument("--workers", type=int, choices=range(1, 9), default=1)
    args = parser.parse_args()
    before, rows, errors, groups = {}, [], [], {}
    try:
        require_fixed98()
        need(not args.out.exists(), "新規照合先だけ")
        tasks, before, groups = prepare(args.index.resolve(), args.run99.resolve(), args.condition.resolve(), args.stage)
        with ProcessPoolExecutor(max_workers=args.workers) as pool:
            futures = {pool.submit(inspect_task, task): task["session"] for task in tasks}
            for future in as_completed(futures):
                session = futures[future]
                try:
                    rows.append(future.result())
                    print("99 Tape独立照合 " + session + " 差0", flush=True)
                except Exception as error:
                    errors.append({"session": session, "error": str(error)})
        need(not errors and len(rows) == len(tasks), "99単場の未完/差")
        need(all(digest(Path(path)) == expected for path, expected in before.items()), "99全入力/コードの前後差")
        result = {"試行": 99, "成功": True, "stage": args.stage, "場数": len(rows), "会計数": sum(row["会計数"] for row in rows),
                  "空Gate対98H0全文会計": sum(row["空Gate対98H0全文"]["対照会計"] for row in rows),
                  "照合項目数": sum(row["照合項目数"] for row in rows), "新callback": sum(row["技法"]["新callback"] for row in rows),
                  "不一致数": 0, "details": sorted(rows, key=lambda row: row["session"]), "入力コードSHA256前後": before,
                  "入力コード前後不変": True, **groups, "監査コードSHA256": digest(Path(__file__)),
                  "固定98完了SHA256": PROOF98_SHA, "由来99再生接続の停止SHA256": RUNTIME_STOP_SHA,
                  "workers": args.workers, "原板/CSV/Go金融再生": 0, "Source/チャート再生成": False,
                  "限定": "12金融とE3/E3S現在checkは固定Tapeから独立再計算。G0四つは旧98空Risk/H0へ全文対照。旧P0/AB/Riskの成功を99へ代用しない。原板/Source/指標形成は固定96/97/98構築証拠へ依存。"}
    except Exception as error:
        result = {"試行": 99, "成功": False, "stage": args.stage, "不整合": str(error), "単場エラー": errors,
                  "完了場数": len(rows), "入力コードSHA256開始": before, "原板/CSV/Go金融再生": 0}
    need(not args.out.exists(), "既存照合証拠は上書き不可")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({name: result[name] for name in ("成功", "場数", "会計数", "照合項目数", "不整合") if name in result}, ensure_ascii=False))
    if not result["成功"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
