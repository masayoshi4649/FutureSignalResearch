"""固定した96原板照合を場別processへ分け、計算式を変更せず集約する。"""

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import hashlib
import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
FIXED = Path(__file__).with_name("出生枠と金融の照合.py")
FIXED_SHA = "7f673b29f27bc8f79e2c0c2e6106dc457a4697f283fdb64a7cddafa4e3210658"
MANIFEST_SHA = "b939bc91b33fd86e933534c3b991d844b8a0200a5f14710e1bd5004edc1aab42"
WORKER_MODULE = None


def digest(path: Path) -> str:
    """
    機能: 読取入力とコードの内容指紋を取得する。
    引数: path(Path)は既存ファイル。
    返り値: strはSHA256。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path) -> dict:
    """
    機能: UTF-8の保存JSONを読み込む。
    引数: path(Path)は保存入力。
    返り値: dictは内容。
    """
    return json.loads(path.read_text(encoding="utf-8-sig"))


def initialize_worker() -> None:
    """
    機能: 独立process内へ固定指紋の原板計算器を読み込む。
    引数: なし。
    返り値: None。旧moduleのglobalを他processと共有しない。
    """
    global WORKER_MODULE
    if digest(FIXED) != FIXED_SHA:
        raise ValueError("固定96原板照合codeの指紋差")
    spec = importlib.util.spec_from_file_location("固定96の場別原板計算", FIXED)
    WORKER_MODULE = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(WORKER_MODULE)


def inspect_worker(task: tuple) -> dict:
    """
    機能: 既存inspect_oneへ一場だけ渡す。
    引数: task(tuple[Path,dict,str,Path])はNative/固定場/入力根/旧95成果物。
    返り値: dictは固定計算器の元の結果。値やイベントを変えない。
    """
    if WORKER_MODULE is None:
        initialize_worker()
    return WORKER_MODULE.inspect_one(task)


def select_inputs(input_dir: Path, manifest_path: Path, limit: int) -> tuple:
    """
    機能: 完了した2又は54場の名前とNative指紋を固定台帳へ結ぶ。
    引数: input_dir/manifest_path(Path)、limit(int)は明示された保存先と場数。
    返り値: tuple[dict,list[dict],dict,list[Path]]は台帳/選択場/完了/前後検査path。
    """
    if limit not in (2, 54) or digest(manifest_path) != MANIFEST_SHA:
        raise ValueError("場数又は固定80台帳の指紋差")
    manifest = load(manifest_path)
    selected = [s for s in manifest["sessions"] if "2026-09-21" <= s["id"][:10] <= "2026-10-27"]
    if len(selected) != 54 or len({s["id"] for s in selected}) != 54:
        raise ValueError("既使用54場集合差")
    selected = selected[:limit]
    completion_path = input_dir / "完了.json"
    completion = load(completion_path)
    if completion["試行"] != 96 or completion["場数"] != limit or completion["Actor数"] != 16:
        raise ValueError("Native完了scope差")
    if not all(completion[name] is True for name in ("G0対95全文一致", "Shadow93全文一致", "助走対本再生の場末公開値一致")):
        raise ValueError("Native完了の基準比較が未完")
    expected = {s["id"] + ".json" for s in selected}
    if set(completion["結果SHA256"]) != expected or completion["台帳SHA256"] != MANIFEST_SHA:
        raise ValueError("Native集合又は完了台帳差")
    paths = [manifest_path, completion_path, FIXED, Path(__file__)]
    for name, sha in completion["結果SHA256"].items():
        path = input_dir / name
        if digest(path) != sha:
            raise ValueError("Nativeの内容指紋差:" + name)
        paths.append(path)
    return manifest, selected, completion, paths


def main() -> int:
    """
    機能: 完了済み固定場だけを独立processで検査し、元順に集約する。
    引数: --input/--manifest/--out/--baseline95(Path)、--limit(int)、--workers(int)。
    返り値: intは成功0又は不一致1。計算式・金融・原板は変更しない。
    """
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("input", "manifest", "out"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--baseline95", type=Path, default=ROOT / "study/00095_5分判断と開始30分見送り/成果物")
    parser.add_argument("--limit", type=int, choices=(2, 54), default=54)
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()
    if args.out.exists() or not 1 <= args.workers <= 8:
        raise ValueError("新規証拠先とworker1..8を指定")
    manifest, selected, completion, paths = select_inputs(args.input, args.manifest, args.limit)
    initialize_worker()
    paths.extend([WORKER_MODULE.OLD_PATH, WORKER_MODULE.OLD.BASE_PATH, WORKER_MODULE.BASE.BASE_PATH, WORKER_MODULE.TECH_PATH])
    before = {str(p.resolve()): digest(p) for p in paths}
    tasks = [(args.input / (s["id"] + ".json"), s, manifest["source_root"], args.baseline95) for s in selected]
    try:
        with ProcessPoolExecutor(max_workers=args.workers, initializer=initialize_worker) as pool:
            futures = {pool.submit(inspect_worker, task): scene["id"] for task, scene in zip(tasks, selected)}
            found = {}
            for future in as_completed(futures):
                scene_id = futures[future]
                detail = future.result()
                if detail["session"] != scene_id or not detail["成功"] or not detail["入力前後不変"]:
                    raise ValueError("場別成功又は入力照合に不一致")
                found[scene_id] = detail
                print(f"原板照合 {len(found)}/{args.limit} {scene_id}", flush=True)
        details = [found[s["id"]] for s in selected]
        result = {"成功": True, "scope": "接続2場" if args.limit == 2 else "正式既使用54場",
                  "セッション数": len(details), "会計数": sum(d["会計数"] for d in details),
                  "G0基準会計数": sum(d["G0基準会計数"] for d in details),
                  "照合項目数": sum(d["照合項目数"] for d in details), "不一致数": 0, "details": details}
    except Exception as exc:
        result = {"成功": False, "不整合": str(exc), "不一致数": 1}
    after = {str(p.resolve()): digest(p) for p in paths}
    result.update(入力前後不変=before == after, コード入力SHA256=before,
                  入力SHA256前=before, 入力SHA256後=after, 並列数=args.workers,
                  場別計算器SHA256=FIXED_SHA, 金融式変更=False, 新市場売買再生=0)
    result["成功"] = result["成功"] and result["入力前後不変"]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps({k: result[k] for k in ("成功", "会計数", "照合項目数", "不一致数") if k in result}, ensure_ascii=False))
    return 0 if result["成功"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
