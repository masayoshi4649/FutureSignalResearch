"""75初回監査の旧55/69欠測契約二箇所だけを、新名前空間で補足する。"""

import argparse
import ast
from collections import Counter
from copy import deepcopy
import gzip
import hashlib
import io
import json
import math
from pathlib import Path
import types


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
STUDY = ROOT / "study/00075_事前帯の外保持と内回帰を判別"
ORIGINAL = HERE / "保存検証.py"
ORIGINAL_SHA = "69e4320e3fc0a5b9ceaa2cc41b3ebac23fdaf814c632273aea80c8e92ba37058"
INITIAL = STUDY / "保存物確認_初回.json"
INITIAL_SHA = "a5e239eacb3b35cb545b7195d95d2ac37da6b4cb8ef50d75a1dd1a84c4185ae9"
DESTINATION = STUDY / "保存物確認.json"
ORIGIN_WORK = ROOT / "work/状態と判断/00065/定時判断と運用.jsonl.gz"
ORIGIN_STUDY = ROOT / "study/00065_方向に対応する現在の有効状態を先に分ける"
M55 = ROOT / "study/00055_先着候補へ独立追尾回収を加える"
M69 = ROOT / "study/00069_条件入口に合わせて技法群の教師を作る"
PREFLIGHT69 = ROOT / "work/条件入口の教師/入力接続確認.json"
BINDING = ("session", "slot_id", "scheduled", "time", "line")
PATCHES = (
    ("audit.check('旧測定の全予定両方向:' + kind, set(bank), {(identity, side) for identity in identities for side in (1, -1)})",
     "supplement_context.check_bank(bank, quotes, kind, identities, source, audit)"),
    ("INPUT.canonical(R55.decision_event(slot, tape))",
     "INPUT.canonical(supplement_context.expected_quote(slot, tape, R55))"))


def sha(path: Path) -> str:
    """保存物の全byte指紋を得る。

    引数: path(Path)は固定コード又は保存証拠。
    返り値: strはSHA256。市場を起動しない。
    """
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def read(path: Path) -> dict:
    """小型JSONをUTF-8で読む。

    引数: path(Path)は旧成功証明又は固定。
    返り値: dictは保存値。
    """
    return json.loads(path.read_text(encoding="utf-8"))


def rows(path: Path):
    """旧65の保存判断から元準備だけを参照する。

    引数: path(Path)は成功SHAへ結合した旧保存gzip。
    返り値: Iterator[dict]は保存行。価格・指標・売買を再計算しない。
    """
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        for line in stream:
            yield json.loads(line)


def canonical(value: object) -> str:
    """表示型も保持した旧気配等の比較文字列を作る。

    引数: value(object)は人工又は保存値。
    返り値: strはkey順に依らないJSON。
    """
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=True)


def finite(value: object) -> bool:
    """bool以外の有限時計を判定する。

    引数: value(object)は比較対象。
    返り値: boolは有限int/floatなら真。
    """
    return type(value) in (int, float) and math.isfinite(value)


def corrected_text(source: str) -> str:
    """凍結Aの二つの正確な式だけを各一回置換する。

    引数: source(str)はSHA確認した旧A本文又は人工本文。
    返り値: strは新名前空間用本文。他の監査式を変更しない。
    """
    for original, replacement in PATCHES:
        if source.count(original) != 1 or replacement in source:
            raise ValueError("限定置換は各1回が必要")
        source = source.replace(original, replacement, 1)
    return source


class Context:
    """旧入力準備に基づく追加照合と、元の誤期待の再現件数を保持する。"""

    def __init__(self, origins: dict) -> None:
        """元65の準備・時計・ATR/Dだけを保存する。

        引数: origins(dict)はslot_idから原入力小型値への辞書。
        返り値: None。旧moduleのglobalを変更しない。
        """
        self.origins, self.immediate, self.quotes = deepcopy(origins), None, None
        self.count, self.original_differences = 0, Counter()

    def require(self, actual: object, expected: object, name: str) -> None:
        """補足専用の一致を確認し、不一致なら最終証明の前に停止する。

        引数: actual/expected(object)は値、name(str)は照合範囲。
        返り値: None。原Aの照合件数へ混ぜず別に数える。
        """
        self.count += 1
        if actual != expected:
            raise ValueError("監査補足不一致:" + name)

    def binding(self, binding: dict, origin: dict, side: int) -> None:
        """原入力と測定行の識別・時計・準備・ATR/Dを検査する。

        引数: binding/origin(dict)は保存測定/元65、side(int)は方向。
        返り値: None。時計は有限数値同値、識別と準備は型も検査する。
        """
        for key in ("session", "slot_id", "line"):
            self.require((type(binding[key]), binding[key]), (type(origin[key]), origin[key]), "元入力:" + key)
        for key in ("scheduled", "time"):
            self.require(finite(binding[key]) and finite(origin[key]) and binding[key] == origin[key], True, "元入力:" + key)
        self.require((type(binding["side"]), binding["side"]), (int, side), "方向")
        self.require((type(binding["ready"]), binding["ready"]), (bool, origin["ready"]), "原準備")
        for key in ("atr", "D"):
            self.require(canonical(binding[key]), canonical(origin[key]), "原入力:" + key)

    def check_bank(self, bank: dict, quotes: dict, kind: str, identities: set, source, audit) -> None:
        """旧69を原ready方向全集合へ直し、元Aの集合比較も一件として維持する。

        引数: bank/quotes(dict)は元Aが縮約した保存値、kind(str)は即時/条件、identitiesは対象、source/auditは固定補助。
        返り値: None。条件集合の検査を削除せず、欠落・余分・方向違いを拒否する。
        """
        self.require(set(self.origins), identities, "原入力1702集合")
        all_keys = {(identity, side) for identity in identities for side in (1, -1)}
        expected = all_keys if kind == "即時" else {(identity, side) for identity in identities if self.origins[identity]["ready"] for side in (1, -1)}
        if set(bank) != all_keys:
            self.original_differences["旧測定の全予定両方向:" + kind] += 1
        audit.check("旧測定の全予定両方向:" + kind, set(bank), expected)
        self.require(set(bank), expected, "正しい保存対象全集合:" + kind)
        for (identity, side), value in bank.items():
            self.binding(value["binding"], self.origins[identity], side)
            if kind == "即時" and not self.origins[identity]["ready"]:
                self.require(value["closed"], None, "55未準備は未計測")
                self.require(quotes[identity], None, "55未準備の気配は必ずNone")
            if kind == "即時" and self.origins[identity]["ready"]:
                self.require(quotes[identity] is not None, True, "55準備済みの偽None拒否")
            if kind == "条件":
                self.require(value["binding"]["ready"], True, "69保存対象は準備済み")
        if kind == "即時":
            self.immediate, self.quotes = bank, quotes

    def expected_quote(self, slot: dict, tape: dict, oracle) -> dict | None:
        """55原readyFalseだけNoneとし、readyTrueの原行6項目を変更せず返す。

        引数: slot/tape(dict)は元判断/原配列、oracleは固定55の原行射影補助。
        返り値: dict|Noneは55保存契約の期待。原行を計測・再生しない。
        """
        identity = slot["slot_id"]
        if self.immediate is None or identity not in self.origins:
            raise ValueError("原準備銀行の先行検査なし")
        raw = oracle.decision_event(slot, tape)
        if canonical(self.quotes[identity]) != canonical(raw):
            self.original_differences["55判断気配は原行同値"] += 1
        ready = self.origins[identity]["ready"]
        self.require(self.immediate[identity, 1]["binding"]["ready"], ready, "55原準備の一致")
        self.require(self.immediate[identity, -1]["binding"]["ready"], ready, "55両側原準備")
        if not ready:
            self.require(self.quotes[identity], None, "未準備のNone規約")
            return None
        self.require(raw is not None, True, "準備済みの原行なしを拒否")
        self.require(canonical(self.quotes[identity]), canonical(raw), "準備済みは原行6項目厳密同値")
        return raw


def ground_inputs(fixed: dict) -> tuple:
    """原65保存準備を、55/65/69の旧成功証拠と75固定指紋へ結合する。

    引数: fixed(dict)は凍結75固定。
    返り値: tupleは原準備辞書/追加入力指紋/追加照合数。特徴・予測を再計算しない。
    """
    pins, checks = {}, 0
    paths = [ORIGIN_WORK, PREFLIGHT69, M69 / "入力台帳.json", M69 / "固定.json"]
    for study in (M55, ORIGIN_STUDY, M69):
        paths += [study / "結果.json", study / "保存物確認.json"]
    for path in paths:
        relative = path.relative_to(ROOT).as_posix()
        if sha(path) != fixed["ファイルSHA256"][relative]:
            raise ValueError("原準備参照の固定差:" + relative)
        pins[relative] = sha(path)
        checks += 1
    for study in (M55, ORIGIN_STUDY, M69):
        proof = read(study / "保存物確認.json")
        if not (proof["全件一致"] is True and proof["不一致数"] == 0 and proof["不一致"] == [] and proof["結果SHA256"] == sha(study / "結果.json")):
            raise ValueError("旧成功証明の結合差")
        checks += 1
    proof65, proof69 = read(ORIGIN_STUDY / "保存物確認.json"), read(M69 / "保存物確認.json")
    rel = ORIGIN_WORK.relative_to(ROOT).as_posix()
    if proof65["参照SHA256"][rel] != sha(ORIGIN_WORK) or read(M69 / "固定.json")["ファイルSHA256"][rel] != sha(ORIGIN_WORK):
        raise ValueError("65保存準備と69原入力の連鎖差")
    ready = read(PREFLIGHT69)
    if not (ready["接続成功"] is True and ready["全予定枠"] == 2442 and ready["準備済み枠"] == 2046
            and ready["新独立測定予定方向"] == 4092 and proof69["独立教師数"] == 4092
            and read(M69 / "入力台帳.json")["入力接続確認"] == ready):
        raise ValueError("69全ready計測の入力接続証明差")
    checks += 2
    origins = {}
    for block in rows(ORIGIN_WORK):
        if block["policy"] != "U0":
            continue
        for slot in block["slots"]:
            identity, feature = slot["slot_id"], slot["feature"]
            if identity in origins or type(feature["ready"]) is not bool or slot["ready"] is not feature["ready"]:
                raise ValueError("65元準備の型又は重複")
            if slot["atr"] != feature["atr"] or slot["D"] != feature["D"]:
                raise ValueError("65元準備のATR/D差")
            origins[identity] = {key: deepcopy(slot[key]) for key in (*BINDING, "ready", "atr", "D")}
            checks += 3
    if len(origins) != 1702:
        raise ValueError("65元入力1702枠が必要")
    return origins, pins, checks + 1


class MemoryFile(io.StringIO):
    """旧Aが作るproofを外部ファイルへ書く前に受け取るメモリ出力。"""

    def __exit__(self, exc_type, exc_value, traceback) -> bool:
        """内容を閉じず、例外だけ呼出側へ返す。

        引数: exc_type/exc_value/tracebackはcontext例外情報。
        返り値: boolはFalse。例外を隠さない。
        """
        return False


class MemoryDestination:
    """通常proofの既存拒否と排他的メモリ書込を表す。"""

    def __init__(self, physical: Path | None = DESTINATION) -> None:
        """まだ書かれていない出力を作る。

        引数: physical(Path|None)は実出力。人工ではNoneとして実ファイルに依存しない。
        返り値: None。
        """
        self.physical, self.stream = physical, None

    def exists(self) -> bool:
        """実proofの既存又は既に受けた書込を確認する。

        引数: なし。
        返り値: boolは上書き不能か。
        """
        return (self.physical is not None and self.physical.exists()) or self.stream is not None

    def open(self, mode: str, encoding: str = "utf-8") -> MemoryFile:
        """旧Aのx書込だけをメモリへ受け取る。

        引数: mode/encoding(str)は旧Aの保存指定。
        返り値: MemoryFileは一度だけの出力。
        """
        if mode != "x" or encoding != "utf-8" or self.exists():
            raise FileExistsError("補足proofは一度だけ")
        self.stream = MemoryFile()
        return self.stream


class StudyView:
    """証明出力一つ以外は同じ実保存先を返す新module専用の射影。"""

    def __init__(self, destination: MemoryDestination) -> None:
        """新名前空間の出力先だけを受け取る。

        引数: destination(MemoryDestination)はproof受取。
        返り値: None。
        """
        self.destination = destination

    def __truediv__(self, name: str):
        """proof名以外の全入力・Viewer参照を元のPathへ返す。

        引数: name(str)は旧Aの相対名。
        返り値: Path|MemoryDestinationは元入力又はproof出力だけ。
        """
        return self.destination if name == "保存物確認.json" else STUDY / name


def run(viewer_url: str | None = None) -> dict:
    """root許可後だけ、二契約を補足した同じA照合を行い最終proofをx保存する。

    引数: viewer_url(str|None)は従来のViewer URL。
    返り値: dictは初回証明を保全した補足proof。売買/label/fit再実行は0。
    """
    if DESTINATION.exists() or not INITIAL.is_file() or sha(INITIAL) != INITIAL_SHA:
        raise FileExistsError("初回proofのbyte保全後、通常proof未存在で実行する")
    if sha(ORIGINAL) != ORIGINAL_SHA:
        raise ValueError("凍結Aの変更")
    initial, fixed = read(INITIAL), read(STUDY / "固定.json")
    if (initial["全件一致"] is not False or initial["不一致数"] != 89 or initial["照合項目数"] != 146093
            or initial["結果SHA256"] != sha(STUDY / "結果.json")
            or any(r["項目"] not in ("旧測定の全予定両方向:条件", "55判断気配は原行同値") for r in initial["不一致"])):
        raise ValueError("初回89差の保存証拠と範囲が違う")
    originals = {name: sha(ROOT / name) for name in initial["参照SHA256"]}
    if originals != initial["参照SHA256"]:
        raise ValueError("初回参照が変更されている")
    origins, extra_pins, extra_count = ground_inputs(fixed)
    context = Context(origins)
    text = corrected_text(ORIGINAL.read_bytes().decode("utf-8"))
    ast.parse(text)
    pins = {p.relative_to(ROOT).as_posix(): sha(p) for p in (Path(__file__), HERE / "監査補足.md", INITIAL)}
    pins.update(extra_pins)
    lock = STUDY / "補足固定.json"
    if lock.exists():
        value = read(lock)
        for name, digest in value["ファイルSHA256"].items():
            if sha(ROOT / name) != digest:
                raise ValueError("補足固定後の変更")
        for key, expected in (("結果SHA256", sha(STUDY / "結果.json")), ("初回証明SHA256", INITIAL_SHA), ("元固定SHA256", sha(STUDY / "固定.json"))):
            if value[key] != expected:
                raise ValueError("補足固定の結合差:" + key)
        pins[lock.relative_to(ROOT).as_posix()] = sha(lock)
    module = types.ModuleType("事前帯75の欠測契約を補足した新名前空間")
    module.__file__ = str(ORIGINAL)
    module.__dict__["supplement_context"] = context
    exec(compile(text, str(ORIGINAL), "exec"), module.__dict__)
    memory = MemoryDestination()
    module.__dict__["STUDY"] = StudyView(memory)
    payload = module.run(viewer_url)
    if memory.stream is None or json.loads(memory.stream.getvalue()) != payload:
        raise ValueError("原Aの出力と返却の差")
    if payload["全件一致"] is not True or payload["不一致数"] != 0 or payload["不一致"] != [] or payload["照合項目数"] != 146093:
        raise ValueError("二契約以外に未解消差又は照合範囲の変化")
    expected_differences = {"旧測定の全予定両方向:条件": 1, "55判断気配は原行同値": 88}
    context.require(dict(context.original_differences), expected_differences, "初回89差の全件分類再現")
    context.require(sum(context.original_differences.values()), 89, "初回のその他差0")
    for name, digest in {**originals, **pins}.items():
        if sha(ROOT / name) != digest:
            raise ValueError("補足監査中の変更:" + name)
    payload["原監査照合項目数"] = payload["照合項目数"]
    payload["追加接続照合項目数"] = context.count + extra_count
    payload["照合項目数"] += payload["追加接続照合項目数"]
    payload["参照SHA256"].update(pins)
    payload["監査補足"] = {"初回証明パス": INITIAL.relative_to(ROOT).as_posix(), "初回証明SHA256": INITIAL_SHA,
        "原監査コードSHA256": ORIGINAL_SHA, "補足コードSHA256": sha(Path(__file__)),
        "置換後ソースSHA256": hashlib.sha256(text.encode("utf-8")).hexdigest(), "置換数": [1, 1],
        "初回終了コード": 1, "初回不一致数": 89, "初回不一致分類の再現": dict(context.original_differences),
        "初回のその他不一致": 0, "原監査再照合全件一致": True, "初回成功項目数": 146004,
        "初回参照SHA256不変": True, "補足参照SHA256前": pins, "補足参照SHA256後": {name: sha(ROOT / name) for name in pins},
        "旧条件の対象方向数": len({(identity, side) for identity in origins if origins[identity]["ready"] for side in (1, -1)}),
        "原準備枠": sum(r["ready"] for r in origins.values()), "未準備枠": sum(not r["ready"] for r in origins.values()),
        "限定": "旧55readyFalseだけNoneを要求、readyTrue原行6項目同値を維持。旧69は成功固定された原65ready方向全集合。原A/主/結果/初回proof無変更。新売買/label計測/fit0。"}
    with DESTINATION.open("x", encoding="utf-8") as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    return payload


def self_test() -> dict:
    """欠測契約・全集合・原準備bindと限定置換を人工だけで検査する。

    引数: なし。
    返り値: dictは成功/人工件数/照合数。本物入力や原配列は読まない。
    """
    checks, tests = 0, 0

    def equal(actual: object, expected: object) -> None:
        """人工期待を型を含むJSON又は値で比較する。

        引数: actual/expected(object)は人工値。
        返り値: None。
        """
        nonlocal checks
        checks += 1
        if actual != expected:
            raise AssertionError((actual, expected))

    def reject(callback) -> None:
        """不正契約の拒否を確認する。

        引数: callback(Callable)は人工処理。
        返り値: None。必ずValueErrorを要求する。
        """
        try:
            callback()
        except ValueError:
            equal(True, True)
        else:
            raise AssertionError("不正な欠測/集合を受け入れた")

    class FakeAudit:
        """旧Aの集合一照合だけを模擬する。"""

        def check(self, name: str, actual: object, expected: object) -> None:
            """元監査へ渡す正しい集合を確認する。

            引数: name(str)は範囲、actual/expectedは集合。
            返り値: None。
            """
            equal(actual, expected)

    class FakeOracle:
        """人工の判断原行を返し、売買を行わない。"""

        @staticmethod
        def decision_event(slot: dict, tape: dict) -> dict | None:
            """人工slot_idに対応する6項目を返す。

            引数: slot/tape(dict)は人工判断/人工行。
            返り値: dict|Noneは原行。
            """
            return deepcopy(tape[slot["slot_id"]])

    origins = {key: {"session": "人工Day", "slot_id": key, "scheduled": 180, "time": 181,
        "line": 10 if key == "A" else 11, "ready": key == "A", "atr": 100.0, "D": 100.0}
        for key in ("A", "B")}
    bank = {(key, side): {"binding": {**origin, "side": side}, "closed": [] if origin["ready"] else None}
        for key, origin in origins.items() for side in (1, -1)}
    quote = {"now": 181.0, "line": 10, "bid": 99.0, "ask": 101.0, "last": 100.0, "valid": True}
    quotes = {"A": quote, "B": None}
    conditional = {key: value for key, value in bank.items() if key[0] == "A"}
    context = Context(origins)
    context.check_bank(bank, quotes, "即時", set(origins), None, FakeAudit())
    context.check_bank(conditional, quotes, "条件", set(origins), None, FakeAudit())
    equal(len(conditional), 2)
    equal(context.original_differences, Counter({"旧測定の全予定両方向:条件": 1}))
    tests += 1
    raw = {"A": quote, "B": {**quote, "line": 11}}
    equal(context.expected_quote(origins["A"], raw, FakeOracle), quote)
    equal(context.expected_quote(origins["B"], raw, FakeOracle), None)
    equal(context.original_differences["55判断気配は原行同値"], 1)
    tests += 1
    raw["B"] = None
    equal(context.expected_quote(origins["B"], raw, FakeOracle), None)
    tests += 1
    for identity in ("A", "B"):
        bad_quotes = deepcopy(quotes)
        bad_quotes[identity] = None if identity == "A" else quote
        reject(lambda: Context(origins).check_bank(bank, bad_quotes, "即時", set(origins), None, FakeAudit()))
        tests += 1
    for mutation in ("欠方向", "余分方向", "未準備を条件へ追加", "time", "atr", "D", "ready型"):
        bad = deepcopy(conditional)
        if mutation == "欠方向":
            bad.pop(("A", -1))
        elif mutation == "余分方向":
            bad["A", 2] = deepcopy(bad["A", 1])
        elif mutation == "未準備を条件へ追加":
            bad["B", 1] = deepcopy(bank["B", 1])
        elif mutation == "ready型":
            bad["A", 1]["binding"]["ready"] = 1
        else:
            bad["A", 1]["binding"][mutation] += 1
        # 集合の誤りは旧auditの前でも後でも追加requireが必ず拒否する。
        class LooseAudit:
            """追加requireの拒否だけを見る人工監査。"""

            def check(self, name: str, actual: object, expected: object) -> None:
                """意図的な集合差を補足専用検査へ渡す。

                引数: name/actual/expectedは人工の比較。
                返り値: None。
                """
                return None
        reject(lambda: Context(origins).check_bank(bad, quotes, "条件", set(origins), None, LooseAudit()))
        tests += 1
    context = Context(origins)
    context.check_bank(bank, quotes, "即時", set(origins), None, FakeAudit())
    reject(lambda: context.expected_quote(origins["A"], {"A": {**quote, "ask": 102}}, FakeOracle))
    tests += 1
    source = ORIGINAL.read_bytes()
    equal(hashlib.sha256(source).hexdigest(), ORIGINAL_SHA)
    transformed = corrected_text(source.decode("utf-8"))
    ast.parse(transformed)
    restored = transformed
    for original, replacement in reversed(PATCHES):
        equal(restored.count(replacement), 1)
        restored = restored.replace(replacement, original, 1)
    equal(restored.encode("utf-8"), source)
    reject(lambda: corrected_text(source.decode("utf-8").replace(PATCHES[0][0], "別の式")))
    tests += 1
    memory = MemoryDestination(None)
    view = StudyView(memory)
    equal(view / "結果.json", STUDY / "結果.json")
    with (view / "保存物確認.json").open("x", encoding="utf-8") as stream:
        stream.write('{"人工": true}')
    equal(json.loads(memory.stream.getvalue()), {"人工": True})
    equal(memory.exists(), True)
    tests += 1
    return {"成功": True, "人工成功": True, "テスト件数": tests, "照合項目数": checks,
        "不一致数": 0, "本物入力読取": False, "売買再生": False, "label計測": False, "fit": 0}


def main() -> None:
    """人工又はroot許可後の補足監査だけを排他的に公開する。

    引数: CLIのself-test/runとviewer-urlは工程・Viewer URL。
    返り値: None。正式は既存proofを拒否して新規保存する。
    """
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--self-test", action="store_true")
    group.add_argument("--run", action="store_true")
    parser.add_argument("--viewer-url")
    args = parser.parse_args()
    payload = self_test() if args.self_test else run(args.viewer_url)
    keys = ("成功", "人工成功", "全件一致", "照合項目数", "テスト件数", "不一致数", "結果SHA256", "原監査照合項目数", "追加接続照合項目数", "監査補足")
    print(json.dumps({k: payload[k] for k in keys if k in payload}, ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
