"""固定index・97完了・条件を検査して、既存のTape金融監査へ並列配送する。"""

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import sys


ROOT = Path(__file__).resolve().parents[2]
PROOF96 = ROOT/"study/00096_5分枠の順行反転と現在数量/完了記録.json"
PROOF96_SHA = "33deeae84c68de0ecce21023e95732db22a658c9a832cb456d446e221276d483"
MANIFEST = ROOT/"study/00080_FAR後期三手法の15分移植と利益保護/入力台帳.json"
MANIFEST_SHA = "b939bc91b33fd86e933534c3b991d844b8a0200a5f14710e1bd5004edc1aab42"
COUPLED_PATH = Path(__file__).with_name("Tapeと金融の照合.py")
COUPLED_SHA = "31fdf1d566f3c117b2cb6c5ec64e3211e7c8ae33a9cab75d84c1e38af1f4dff7"


def need(condition: bool, message: str) -> None:
    """
    機能: 未完/集合差/指紋差を成功へ補完せず拒否する。
    引数: condition(bool)、message(str)は条件と説明。
    返り値: None。不成立はValueError。
    """
    if not condition:
        raise ValueError(message)


def digest(path: Path) -> str:
    """
    機能: 許可された保存値又はコードのSHA256を取得する。
    引数: path(Path)は対象ファイル。
    返り値: strはSHA256。原板/CSVの探索はしない。
    """
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def path_key(path: Path) -> str:
    """
    機能: Windowsの大小文字差を除いて絶対パスを比較する。
    引数: path(Path)は明示ファイル。
    返り値: strは比較用の正規パス。
    """
    return os.path.normcase(str(path.resolve()))


def valid_sha(value) -> bool:
    """
    機能: 固定指紋の型と小文字16進64桁を検査する。
    引数: value(any)は指紋候補。
    返り値: boolは妥当性。
    """
    return type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def fixed_module():
    """
    機能: 変更しない金融/純技法の結合監査を固定SHAで読み込む。
    引数: なし。
    返り値: moduleは停止済みinspect_tapeを公開する。
    """
    need(digest(COUPLED_PATH) == COUPLED_SHA, "固定Tape金融監査SHA差")
    spec = importlib.util.spec_from_file_location("固定97Tape金融の市場配送", COUPLED_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


COUPLED = fixed_module()
BASE = COUPLED.BASE


# ----------------------------------------
def selected_catalog() -> dict:
    """
    機能: 固定96完了と固定80台帳のmetadataだけで許可54場を結ぶ。
    引数: なし。
    返り値: dict[str,str]は許可場と正式Native gzip指紋。本文は読まない。
    """
    need(digest(PROOF96) == PROOF96_SHA and digest(MANIFEST) == MANIFEST_SHA, "固定96/80指紋差")
    proof, manifest = BASE.load(PROOF96), BASE.load(MANIFEST)
    need(proof["比較保存完了"] is True and proof["場数"] == 54, "96の54場完了")
    out = {}
    for name, value in proof["自己を除く正式指紋"].items():
        match = re.fullmatch(r"成果物/(\d{4}-\d{2}-\d{2}_(?:Day|Night))\.json\.gz", name.replace("\\", "/"))
        if match:
            need(match[1] not in out and valid_sha(value), "固定96 Native集合/指紋")
            out[match[1]] = value
    allowed = {s["id"] for s in manifest["sessions"] if "2026-09-21" <= s["id"][:10] <= "2026-10-27"}
    need(len(out) == len(allowed) == 54 and set(out) == allowed, "96許可54と固定台帳集合差")
    return out


def normalized_map(value: dict) -> dict:
    """
    機能: 完了証拠の絶対path→SHAを衝突なく比較形式へ変換する。
    引数: value(dict)は完了時の指紋集合。
    返り値: dict[str,str]は正規パスと指紋。
    """
    need(type(value) is dict and bool(value), "空の指紋集合")
    out = {}
    for name, sha in value.items():
        need(type(name) is str and Path(name).is_absolute() and valid_sha(sha), "完了指紋のpath/SHA")
        key = path_key(Path(name))
        need(key not in out, "指紋pathの重複")
        out[key] = sha
    return out


def validate_metadata(index: dict, completion: dict, condition: dict, stage: str, catalog: dict) -> set:
    """
    機能: ファイル本文を開く前に、stage集合と97完了/固定条件を厳密検査する。
    引数: index/completion/condition/catalog(dict)、stage(str)は指定保存metadata。
    返り値: set[str]はfirst2又はfull54の場。架空の成功を作らない。
    """
    need(stage in ("first2", "full54") and type(index.get("version")) is int
         and index.get("version") == 1 and index.get("stage") == stage, "index版/stage")
    expected = {"2026-09-21_Day", "2026-09-21_Night"} if stage == "first2" else set(catalog)
    need(len(catalog) == 54 and expected <= set(catalog), "固定96の許可集合")
    rows = index.get("entries")
    need(type(rows) is list and len(rows) == len(expected), "index場数")
    ids = []
    for row in rows:
        need(type(row) is dict and set(row) == {"session", "path", "sha256"}, "index entry全字段")
        need(type(row["session"]) is str, "index場名型")
        need(type(row["path"]) is str and bool(row["path"]) and valid_sha(row["sha256"]), "Tape path/指紋")
        ids.append(row["session"])
    need(len(set(ids)) == len(ids) and set(ids) == expected, "index欠落/重複/対象外")
    need(condition.get("試行") == 97 and condition.get("固定96完了SHA256") == PROOF96_SHA
         and condition.get("台帳SHA256") == MANIFEST_SHA and condition.get("市場損益を開く前の固定") is True, "97固定条件")
    code = condition.get("コードSHA256")
    need(type(code) is dict and bool(code) and all(type(k) is str and k and valid_sha(v) for k,v in code.items()), "固定コード集合")
    need(completion.get("成功") is True and completion.get("stage") == stage and completion.get("場数") == len(expected), "97運転完了/stage/場数")
    need(completion.get("口座/場") == 16 and completion.get("P0対96全文比較/場") == 8, "97全16/P0対照8")
    need(completion.get("入力前後不変") is True and completion.get("コード前後不変") is True, "97入力/コード不変flag")
    need(normalized_map(completion.get("入力前SHA256")) == normalized_map(completion.get("入力後SHA256")), "97入力前後集合差")
    need(normalized_map(completion.get("コード前SHA256")) == normalized_map(completion.get("コード後SHA256")), "97コード前後集合差")
    need(completion.get("Source再運転") is False and completion.get("チャート再計算") is False
         and type(completion.get("Raw/CSV読取")) is int and completion.get("Raw/CSV読取") == 0, "固定Tape運転scope")
    outcomes = completion.get("結果")
    need(type(outcomes) is list and len(outcomes) == len(expected), "完了結果場数")
    seen = []
    for row in outcomes:
        need(type(row) is dict and {"session", "path", "sha256"} <= set(row) <= {"session", "path", "sha256", "error"}, "完了結果schema")
        need(type(row["session"]) is str and ("error" not in row or type(row["error"]) is str and row["error"] == "")
             and type(row["path"]) is str and bool(row["path"]) and valid_sha(row["sha256"]), "完了結果のerror/path/指紋")
        seen.append(row["session"])
    need(len(set(seen)) == len(seen) and set(seen) == expected, "完了結果集合差")
    return expected


def inspect_values(tape: dict, new97: dict) -> dict:
    """
    機能: 既存の停止監査へ値をそのまま渡す単場接続口。
    引数: tape/new97(dict)は完成Tapeと金融保存。
    返り値: dictはinspect_tapeの全結果。金融/純技法の式を追加しない。
    """
    return COUPLED.inspect_tape(tape, new97)


def validate_fixed_code(condition: dict, completion: dict) -> dict:
    """
    機能: 条件で列挙した全codeを、完了前後集合と現在bytesへ結ぶ。
    引数: condition/completion(dict)は固定条件と運転完了metadata。
    返り値: dictは正規pathから実Path/SHAへの対応。長さをliteralに固定しない。
    """
    code = {path_key((ROOT/name).resolve()):((ROOT/name).resolve(),sha) for name,sha in condition["コードSHA256"].items()}
    need(len(code) == len(condition["コードSHA256"]), "固定code path衝突")
    expected = {k:v[1] for k,v in code.items()}
    need(normalized_map(completion["コード前SHA256"]) == normalized_map(completion["コード後SHA256"]) == expected,
         "完了と条件のコード集合差")
    for path,sha in code.values():
        need(digest(path) == sha, "固定code実SHA差:"+str(path))
    return code


def inspect_task(task: dict) -> dict:
    """
    機能: 指定一場の保存完了/出典を確認し、全16金融を独立監査へ渡す。
    引数: task(dict)はsession/Tape/resultの絶対path・期待SHA・固定96 Native指紋。
    返り値: dictは単場結果と入力前後指紋。Source/原板は再運転しない。
    """
    session = task["session"]
    tape_path, result_path = Path(task["tape"]).resolve(), Path(task["result"]).resolve()
    before = {str(p.resolve()):digest(p) for p in (tape_path,result_path)}
    need(before[str(tape_path)] == task["tape_sha256"] and before[str(result_path)] == task["result_sha256"], session+":入力SHA差")
    tape, value = BASE.load(tape_path), BASE.load(result_path)
    need(tape["session"]["id"] == value["session"] == session, "index/Tape/金融の場差")
    need(tape.get("provenance") and not tape["scope"].startswith("固定96Go型人工"), "市場Tapeの出典が必要")
    need(value.get("version") == 1 and value.get("actual_run_complete") is True, "金融Envelope完了")
    need(value.get("source_reexecuted") is False and value.get("charts_recomputed") is False, "保存Source/チャート継承scope")
    matched = value.get("P0_96_match", {})
    expected_keys = {k for k in COUPLED.FIN.KEYS if not k.startswith("H0_")}
    need(matched.get("all") is True and matched.get("books") == 8 and set(matched.get("keys", [])) == expected_keys
         and len(matched["keys"]) == 8 and matched.get("excluded") == [], "旧96の8全文対照/除外0")
    p = value.get("input96_provenance", {})
    native = (PROOF96.parent/"成果物"/(session+".json.gz")).resolve()
    need(path_key(Path(p["native_path"])) == path_key(native) and p["native_gzip_sha256"] == task["native96_sha256"]
         and p["completion_sha256"] == PROOF96_SHA, "固定96 Native出典")
    need(path_key(Path(p["tape_path"])) == path_key(tape_path) and p["tape_sha256"] == task["tape_sha256"], "Envelope Tape出典")
    provenance = normalized_map(tape["provenance"])
    need(provenance.get(path_key(native)) == task["native96_sha256"]
         and provenance.get(path_key(PROOF96)) == PROOF96_SHA, "Tapeの固定96出典")
    result = inspect_values(tape, value)
    need(all(digest(Path(k)) == v for k,v in before.items()), session+":入力前後差")
    return {"session":session, **result, "入力SHA256前後":before, "入力前後不変":True}


# ----------------------------------------
def prepare(index_path: Path, run97: Path, condition_path: Path, stage: str) -> tuple:
    """
    機能: 97完了と固定index/コードを現物SHAまで確認してから単場taskを作る。
    引数: index_path/run97/condition_path(Path)、stage(str)は明示保存先。
    返り値: tuple[list,dict]は配送taskと全入力/コードの開始指紋。
    """
    catalog = selected_catalog()
    completion_path = (run97/"完了.json").resolve()
    index, condition, completion = BASE.load(index_path), BASE.load(condition_path), BASE.load(completion_path)
    expected = validate_metadata(index, completion, condition, stage, catalog)
    files = {p.stem for p in run97.glob("*.json") if re.fullmatch(r"\d{4}-\d{2}-\d{2}_(Day|Night)", p.stem)}
    need(files == expected, "実97保存の場集合")
    inputs = {path_key(p):p.resolve() for p in (index_path,condition_path,PROOF96,MANIFEST)}
    tasks, outcomes = [], {r["session"]:r for r in completion["結果"]}
    for row in index["entries"]:
        session = row["session"]
        tape_path = Path(row["path"])
        tape_path = (tape_path if tape_path.is_absolute() else index_path.parent/tape_path).resolve()
        result_path = (run97/(session+".json")).resolve()
        declared_result = Path(outcomes[session]["path"])
        declared_result = (declared_result if declared_result.is_absolute() else ROOT/declared_result).resolve()
        need(path_key(result_path) == path_key(declared_result), "完了結果の配置差")
        need(digest(tape_path) == row["sha256"] and digest(result_path) == outcomes[session]["sha256"], session+":Tape/result SHA差")
        native = (PROOF96.parent/"成果物"/(session+".json.gz")).resolve()
        need(digest(native) == catalog[session], "固定96 gzip指紋差")
        for path in (tape_path,result_path,native):
            inputs[path_key(path)] = path
        tasks.append({"session":session, "tape":str(tape_path), "result":str(result_path),
                      "tape_sha256":row["sha256"], "result_sha256":outcomes[session]["sha256"], "native96_sha256":catalog[session]})
    recorded_input = normalized_map(completion["入力前SHA256"])
    go_inputs = set(inputs)-{path_key(Path(t["result"])) for t in tasks}
    need(set(recorded_input) == go_inputs, "97完了入力の完全集合差")
    for key in go_inputs:
        need(digest(inputs[key]) == recorded_input[key], "97完了入力の実SHA差:"+str(inputs[key]))
    code = validate_fixed_code(condition, completion)
    for path,sha in code.values():
        inputs[path_key(path)] = path
    for path in (completion_path,Path(__file__).resolve(),COUPLED_PATH,COUPLED.FIN_PATH,
                 COUPLED.FIN.OLD_PATH,COUPLED.FIN.TECH_PATH,COUPLED.FIN.OLD.OLD_PATH,
                 COUPLED.FIN.OLD.OLD.BASE_PATH,COUPLED.BASE.BASE_PATH):
        inputs[path_key(path)] = path
    return sorted(tasks,key=lambda t:t["session"]), {str(p):digest(p) for p in inputs.values()}


def main() -> int:
    """
    機能: 明示された完了97保存を既存監査へProcessPoolで配送する。
    引数: --index/--run97/--condition/--out(Path)、--stage(str)、--workers(int,1..8)は指定保存と並列数。
    返り値: intは全成功0/未完又は差1。金融/純技法の式を追加変更せず、Sourceを再生成しない。
    """
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("index", "run97", "condition", "out"):
        parser.add_argument("--"+name, type=Path, required=True)
    parser.add_argument("--stage", choices=("first2","full54"), required=True)
    parser.add_argument("--workers", type=int, choices=range(1,9), default=1)
    args = parser.parse_args()
    need(not args.out.exists(), "新規監査出力先")
    before, rows, errors = {}, [], []
    try:
        tasks, before = prepare(args.index.resolve(), args.run97.resolve(), args.condition.resolve(), args.stage)
        with ProcessPoolExecutor(max_workers=args.workers) as executor:
            futures = {executor.submit(inspect_task,task):task["session"] for task in tasks}
            for future in as_completed(futures):
                session = futures[future]
                try:
                    rows.append(future.result())
                    print("Tape金融照合 "+session+" 差0", flush=True)
                except Exception as error:
                    errors.append({"session":session, "error":str(error)})
        need(not errors and len(rows) == len(tasks), "単場監査の未完/不一致")
        need(all(digest(Path(p)) == h for p,h in before.items()), "監査の入力/コード前後差")
        result = {"成功":True, "stage":args.stage, "場数":len(rows), "会計数":sum(r["会計数"] for r in rows),
                  "照合項目数":sum(r["照合項目数"] for r in rows), "新callback":sum(r["技法"]["新callback"] for r in rows),
                  "不一致数":0, "details":sorted(rows,key=lambda r:r["session"]), "入力コードSHA256前後":before,
                  "入力コード前後不変":True, "workers":args.workers, "原板/CSV/Go金融再生":0,
                  "限定":"全金融を固定TapeからPythonで再構成。原板・Source・チャート生成は固定96/Tape構築の証拠へ依存。P0旧96全文の再比較は完了/Envelope証拠と固定gzip指紋へ結ぶ。"}
    except Exception as error:
        result = {"成功":False, "stage":args.stage, "不整合":str(error), "単場エラー":errors,
                  "完了場数":len(rows), "入力コードSHA256開始":before, "原板/CSV/Go金融再生":0}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2)+"\n", encoding="utf-8", newline="\n")
    print(json.dumps({k:result[k] for k in ("成功","場数","会計数","照合項目数","不整合") if k in result}, ensure_ascii=False))
    return 0 if result["成功"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
