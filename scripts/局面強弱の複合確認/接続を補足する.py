"""凍結63監査の縮約枠と旧50完全枠の接続だけを新名前空間で補足する。"""

from collections import defaultdict
from copy import deepcopy
from datetime import datetime
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
from types import FunctionType


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
FROZEN_SHA = "f7dd0ec4a19f3debcc771f2f5b35d3061a0a82e147fa95ddfb78db8a0a397603"
INITIAL_LOG = ROOT / "work/局面強弱の複合確認/00063/保存検証_実行.log"


def load(path: Path, name: str):
    """凍結監査を別名で読み、元ファイル・大域値を変更しない。

    引数: path(Path)はコード、name(str)は固有名。
    返り値: ModuleTypeは読取結果。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


FROZEN = HERE / "保存検証.py"
A63 = load(FROZEN, "接続補足が固定参照する63監査")


# ----------------------------------------
# 入力接続は独立旧46からの出典と旧50正本を照合し、将来値を供給しない。

def strict_equal(actual: object, expected: object) -> bool:
    """JSONの型と値を再帰的に比較する。

    引数: actual/expected(object)はJSON値。
    返り値: boolは型・辞書キー・配列順・末端値が一致するか。
    """
    if type(actual) is not type(expected):
        return False
    if isinstance(actual, dict):
        return actual.keys() == expected.keys() and all(strict_equal(actual[k], expected[k]) for k in actual)
    if isinstance(actual, list):
        return len(actual) == len(expected) and all(strict_equal(a, b) for a, b in zip(actual, expected))
    return actual == expected


def bind_full_slots(thin: dict, full_rows: list[dict], prepared46: dict) -> dict:
    """旧50正本の完全枠を、縮約枠と独立旧46出典へ一対一で結ぶ。

    引数: thin(dict)はBINDING5項目、full_rows(list[dict])は旧50P0完全枠、
        prepared46(dict)は固定60独立算術で再構成した旧46。
    返り値: dictはID別完全枠の深い写し。欠落・重複・時計・上位改竄は拒否する。
    """
    if set(thin) != set(prepared46):
        raise ValueError("縮約枠と独立46の集合差")
    complete = {}
    for slot in full_rows:
        identity = slot.get("slot_id")
        if identity in complete or identity not in thin:
            raise ValueError("旧50P0枠の重複又は範囲外")
        if any(k not in slot for k in A63.BINDING):
            raise ValueError("旧50P0のBINDING項目欠落")
        binding = {k: slot[k] for k in A63.BINDING}
        if not strict_equal(binding, thin[identity]):
            raise ValueError("旧50P0と縮約枠の識別子・予定・実時計・原行差")
        feature = prepared46[identity]
        if feature["ready"]:
            base15 = feature["base"]["base"]
            upper = slot.get("upper")
            if not isinstance(upper, dict) or upper.get("ready") is not True:
                raise ValueError("準備済み旧46に対応する上位出典なし")
            source = upper.get("source")
            if A63.A.source_reason(source, slot["session"], 15, slot["scheduled"], (slot["time"], slot["line"])):
                raise ValueError("旧50上位が未可視又は不正")
            if not strict_equal(source, base15["sources"]["upper"]):
                raise ValueError("旧50上位SOURCEと独立旧46が不一致")
            for name in ("plus_di", "minus_di"):
                value = upper.get(name)
                if not A63.A.finite(value) or not strict_equal(value, base15["diagnostic"][name]):
                    raise ValueError("旧50上位DIと独立旧46が不一致")
        complete[identity] = deepcopy(slot)
    if set(complete) != set(thin):
        raise ValueError("旧50P0枠の欠落")
    return complete


def prepare_connected(old_slots: dict, features: dict, source, audit) -> tuple:
    """旧46縮約経路を保ち、追加8直前だけ完全枠を供給する。

    引数: old_slots/features(dict)は凍結監査の縮約予定/旧18、source(ModuleType)/audit(Audit)は純補助。
    返り値: tuple[dict,dict]は全54期待特徴と追加接続検査の件数・範囲。
    """
    previous = A63.R60.prepare_features(old_slots, features, source, audit)
    full_rows = [slot for block in source.json_rows(A63.SLOTS50) if block["policy"] == "P0" for slot in block["slots"]]
    complete = bind_full_slots(old_slots, full_rows, previous)
    start = audit.count
    audit.check("接続補足:全2442一意正本枠", len(complete), 2442)
    audit.check("接続補足:全ID同値", set(complete), set(old_slots))
    for identity, slot in complete.items():
        audit.check("接続補足:完全BINDING型値", strict_equal({k: slot[k] for k in A63.BINDING}, old_slots[identity]), True)
        if previous[identity]["ready"]:
            base15 = previous[identity]["base"]["base"]
            audit.check("接続補足:独立46とupperSOURCE型値", strict_equal(slot["upper"]["source"], base15["sources"]["upper"]), True)
            audit.check("接続補足:独立46とDI型値", [slot["upper"][k] for k in ("plus_di", "minus_di")],
                [base15["diagnostic"][k] for k in ("plus_di", "minus_di")])
    extra = audit.count - start
    frames = defaultdict(list)
    for row in source.json_rows(A63.FRAMES):
        if row["minutes"] == 15:
            frames[row["場"]].append({"session": row["場"], **{k: row[k] for k in A63.A.SOURCE if k != "session"}})
    sessions = []
    for entry in source.read(source.MANIFEST)["entries"]:
        session = entry["session"]
        begin, _, end, _ = source.calendar(session)
        sessions.append({"session": session, "contract": tuple(entry["in_session_contract_codes"]),
            "begin": begin, "end": end, "frames15": frames[session]})
    contexts = A63.numeric_context(sessions)
    prepared = {}
    for identity, feature in previous.items():
        slot = complete[identity]
        prepared[identity] = A63.expected_feature(feature, slot, contexts[slot["session"]])
        audit.check("旧46全辞書射影完全同値", A63.control_projection(prepared[identity]), feature)
    return prepared, {"追加接続照合項目数": extra, "正本完全枠数": len(complete),
        "準備済み上位出典照合枠数": sum(f["ready"] for f in previous.values()),
        "修正範囲": "旧46は縮約BINDING経路のまま。追加8の期待特徴へ渡すslotだけ旧50正本へ結合"}


def cloned_run(function, adapter):
    """関数の大域辞書を複写し、準備関数一つだけ局所差替えする。

    引数: function(function)は凍結run、adapter(callable)は新接続準備。
    返り値: functionは同一code object・新名前空間のrun。元の大域値は変更しない。
    """
    namespace = dict(function.__globals__)
    namespace["prepare_features"] = adapter
    return FunctionType(function.__code__, namespace, function.__name__, function.__defaults__, function.__closure__)


def run(viewer_url: str | None = None) -> dict:
    """初回失敗を保全し、固定監査の未完部分を接続補足で完了する。

    引数: viewer_url(str|None)はViewer API。
    返り値: dictは原A範囲と追加接続検査を区別した正本証明。市場/fitを再実行しない。
    """
    proof_path = A63.STUDY / "保存物確認.json"
    if proof_path.exists():
        raise FileExistsError("正本proofが既存です")
    if hashlib.sha256(FROZEN.read_bytes()).hexdigest() != FROZEN_SHA:
        raise ValueError("凍結63監査SHAが不一致")
    initial_text = INITIAL_LOG.read_text(encoding="utf-8-sig")
    if "KeyError: 'upper'" not in initial_text or 'expected = slot["upper"]["source"]' not in initial_text:
        raise ValueError("初回失敗ログの原因が想定と不一致")
    files = [INITIAL_LOG, FROZEN, HERE / "接続を補足する.py", HERE / "接続補足人工.py", HERE / "補足仕様.md", A63.SLOTS50]
    fixed = json.loads((A63.STUDY / "固定.json").read_text(encoding="utf-8"))
    slot_name = A63.SLOTS50.relative_to(ROOT).as_posix()
    if fixed["ファイルSHA256"].get(slot_name) != hashlib.sha256(A63.SLOTS50.read_bytes()).hexdigest():
        raise ValueError("旧50P0完全枠の固定pinが不成立")
    files += [ROOT / path for path in fixed["ファイルSHA256"]]
    files += [A63.STUDY / "結果.json", A63.STUDY / "条件.json", A63.STUDY / "入力台帳.json"]
    before = {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    connection = {}

    def adapter(old_slots: dict, features: dict, source, audit) -> dict:
        """固定runへ新接続準備の返り値だけを供給する。

        引数: old_slots/features(dict)は縮約入力、source(ModuleType)/audit(Audit)は固定補助。
        返り値: dictは独立54特徴。追加件数を今回の局所記録へ残す。
        """
        prepared, metadata = prepare_connected(old_slots, features, source, audit)
        connection.update(metadata)
        return prepared

    original_prepare = A63.prepare_features
    copied = cloned_run(A63.run, adapter)
    changed = [key for key in copied.__globals__ if copied.__globals__[key] is not A63.run.__globals__.get(key)]
    if changed != ["prepare_features"] or copied.__code__ is not A63.run.__code__:
        raise ValueError("局所差替えが準備関数以外へ波及")
    payload = copied(viewer_url)
    if A63.prepare_features is not original_prepare:
        raise ValueError("凍結モジュールの大域値を変更")
    for name, digest in before.items():
        if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != digest:
            raise ValueError("補足実行中の固定物又は入力変化:" + name)
    total = payload["照合項目数"]
    extra = connection["追加接続照合項目数"]
    payload.update({"初回監査": {"開始chunk": "83c301", "session": 73864, "終了chunk": "23c310", "terminal_exit": 1,
        "完了": False, "proof生成": False, "ログ": INITIAL_LOG.relative_to(ROOT).as_posix(),
        "ログSHA256": before[INITIAL_LOG.relative_to(ROOT).as_posix()], "例外": "KeyError: upper",
        "原因": "旧56Aの縮約BINDING枠を追加指標の期待値へ渡し、upperの接続が欠落"},
        "接続補足": {**connection, "補足日時": datetime.now().astimezone().isoformat(),
            "凍結A範囲の照合項目数": total-extra, "合計照合項目数": total,
            "凍結A変更": False, "凍結A大域値変更": False, "主結果変更": False,
            "市場再生": False, "fit": False, "初回ログ不変": True,
            "実行前proof未存在": True, "凍結run同一code_object": True,
            "補足コード": {"パス": Path(__file__).relative_to(ROOT).as_posix(), "SHA256": before[Path(__file__).relative_to(ROOT).as_posix()]},
            "上位出典入力正本": {"パス": A63.SLOTS50.relative_to(ROOT).as_posix(), "SHA256": before[A63.SLOTS50.relative_to(ROOT).as_posix()]},
            "実行前後SHA不変": before}})
    payload["参照SHA256"].update(before)
    proof_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False)+"\n", encoding="utf-8")
    return payload


def self_test() -> dict:
    """別人工ファイルの接続拒否境界だけを起動する。

    引数: なし。
    返り値: dictは人工成功と照合数。正式入力・モデルは読まない。
    """
    return load(HERE / "接続補足人工.py", "接続補足の独立人工").self_test()


def main() -> None:
    """人工又は許可済み補足監査をCLIから実行する。

    引数: CLIの--self-test/--run、任意--viewer-url。
    返り値: None。正式起動はrootの補足許可後だけ。
    """
    parser = argparse.ArgumentParser(description="凍結63監査の完全枠接続だけを補足")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--self-test", action="store_true")
    group.add_argument("--run", action="store_true")
    parser.add_argument("--viewer-url")
    args = parser.parse_args()
    payload = self_test() if args.self_test else run(args.viewer_url)
    print(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False))
    raise SystemExit(0 if payload.get("人工成功", payload.get("全件一致")) else 1)


if __name__ == "__main__":
    main()
