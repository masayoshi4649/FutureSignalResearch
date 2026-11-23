"""71の取得位置追加と支持剪定を、保存JSONだけから表示する。"""

import argparse
from collections import Counter
from copy import deepcopy
from decimal import Decimal
import importlib.util
import hashlib
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
STUDY = ROOT / "study/00071_技法の組み合わせへ取得位置を加える"
OLD = ROOT / "study/00070_約定支持を保つ粒度で技法を組み合わせる"
SOURCE = ROOT / "study/00069_条件入口に合わせて技法群の教師を作る"
SHARED = HERE.parent / "支持を保つ技法群/レポート.py"
SPEC = importlib.util.spec_from_file_location("取得表示71の固定70純表示", SHARED)
PREVIOUS = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PREVIOUS
SPEC.loader.exec_module(PREVIOUS)
R69 = PREVIOUS.PREVIOUS
V5, R55 = PREVIOUS.V5, PREVIOUS.R55
sha, read, table = PREVIOUS.sha, PREVIOUS.read, PREVIOUS.table
money, rate, qualification, link, shown = PREVIOUS.money, PREVIOUS.rate, PREVIOUS.qualification, PREVIOUS.link, PREVIOUS.shown
POLICIES = ("P0", "P1", "B0", "B1", "G0", "G1")
CONTROLS, NEW, MODEL_POLICIES = POLICIES[:2], POLICIES[2:], ("B0", "G0")
PERIODS, PERIOD_NAMES, PHASES = PREVIOUS.PERIODS, PREVIOUS.PERIOD_NAMES, PREVIOUS.PHASES
NONFILL = PREVIOUS.NONFILL
POSITION_META = {"id": "F61", "name": "取得位置と上位端", "method": "P01", "family": "price", "scale": "m15"}
FORMULAS = [*PREVIOUS.FORMULAS, "g=s*(M-E*)/D。買M=公開15分high・E*=当時ask、売M=low・E*=bid。Fraction(str)→float64、学習walkはfloat32。clip/mask/新符号gateなし"]
EXTERNAL = ROOT / "docs/議論/外部再調査/取得前の距離と取得後の保護を分ける.md"


# ----------------------------------------

def fingerprint(value: object) -> str:
    """既存と同じ有限JSONの保存内容指紋を得る。

    引数: value(object)はキー整列可能な有限JSON値。
    返り値: strは配列順を保ったUTF-8のSHA256。
    """
    content = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(content).hexdigest()


def validate_result(result: dict) -> None:
    """元学習六木と派生六木・六政策の条件運用を検査する。

    引数: result(dict)は主の小型保存結果又は人工辞書。
    返り値: None。不一致はValueError。正式値を補完しない。
    """
    if result.get("試行") != 71 or result.get("全66場既使用") is not True or set(result["候補"]) != set(POLICIES):
        raise ValueError("71の旧P対照・新B/G六政策が必要")
    expected = {"新分類器fit": 0, "新独立計測": 0, "新保存木数": 12, "新元学習木数": 6,
        "新派生木数": 6, "参照モデル数": 3, "新運用数": 184, "参照独立測定": 4092}
    if any(type(result[key]) is not int or result[key] != value for key, value in expected.items()):
        raise ValueError("元六木・派生六木・新計測0・184運用の差")
    if type(result["新回帰器fit"]) is not int or not 0 <= result["新回帰器fit"] <= 24:
        raise ValueError("六元木の最大24子回帰fitの差")
    learning = {"元試行": 69, "モデル政策": "C0", "同じ可知集合": True, "同じ条件教師": True,
        "基礎60投影同値": True, "新fit": True, "追加": POSITION_META, "無取引": "回収0・障壁対象外"}
    if result["学習参照"] != learning or result["対照参照"] != {"候補": list(CONTROLS), "元試行": 70, "市場再生": False}:
        raise ValueError("同69C教師・旧70保存対照の接続差")
    if len(set(result["評価場"])) != 46 or len(set(result["学習専用場"])) != 20 or set(result["評価場"]) & set(result["学習専用場"]):
        raise ValueError("初20専用・評価46場の差")
    for key in ("モデル", "元学習モデル", "回収集計"):
        entries = result[key]
        if len(entries) != 6 or len({e["id"] for e in entries}) != 6 or {(e["policy"], e["phase"]) for e in entries} != {(p, h) for p in MODEL_POLICIES for h in PHASES}:
            raise ValueError("B0/G0三phaseずつの元・派生・回収metaが必要")
    if set(result["剪定"]) != set(PHASES) or any(set(result["剪定"][h]) != set(MODEL_POLICIES) for h in PHASES) or set(result["条件段階"]) != set(NEW):
        raise ValueError("六剪定・新四政策の条件段階が必要")
    for period, scheduled in zip(PERIODS, (740, 888, 74)):
        for policy in POLICIES:
            item = result["候補"][policy][period]
            e, o = item["入口"], item["運用"]
            outcomes = e["結果別"]
            if not set(outcomes) <= set(NONFILL) | {"250", "125", "期限", "不足"} or any(type(n) is not int or n < 0 for n in outcomes.values()):
                raise ValueError("条件入口の非fill六群と約定後四群の差")
            if sum(outcomes.values()) != e["候補"] or e["候補"] - sum(outcomes.get(k, 0) for k in NONFILL) != e["約定"] or e["250"] != outcomes.get("250", 0):
                raise ValueError("純候補・仮約定・250の復元差")
            for wins, total, field in (("250", "約定", "率"), ("間引き250", "間引き約定", "間引き率")):
                if (e[field] is None) != (e[total] == 0) or e[total] and not math.isclose(e[field], e[wins] / e[total], rel_tol=0, abs_tol=1e-12):
                    raise ValueError("率の分母又は無約定null差")
            wait, invalid = o["判断別"].get("待ち", 0), o["判断別"].get("判定不能", 0)
            upper = wait + invalid + o["条件未約定"]
            if o["予定枠"] != scheduled or sum(o["判断別"].values()) != scheduled or (o["待ち数"], o["判定不能"]) != (wait, invalid):
                raise ValueError("全予定枠・実判断別の差")
            if not 0 <= upper <= scheduled or not math.isclose(o["主待ち率"], wait / scheduled, rel_tol=0, abs_tol=1e-12) or not math.isclose(o["待ち率保守上限"], upper / scheduled, rel_tol=0, abs_tol=1e-12) or o["活動適格"] != (upper * 2 <= scheduled):
                raise ValueError("登録未約定込みの保守活動分母差")
            for fee in (0, 5, 10):
                if o["完結観測額円"][str(fee)] != o["完結観測額円"]["0"] - 20 * fee * o["完結数"]:
                    raise ValueError("同約定の費用感応差")
                if (o["品質注意場"] or o["未解消"]) and o["全体確定額円"][str(fee)] is not None:
                    raise ValueError("品質注意・未解消は全体確定null")
            if sum(o["役割別完結"][role]["件数"] for role in ("順行", "反転")) != o["完結数"] or item["同時適格"] != (e["70目標"] and o["活動適格"] and o["費用適格"]):
                raise ValueError("実役割復元又は同時目標差")
            if policy in NEW:
                stage = result["条件段階"][policy][period]
                if stage["全予定枠"] != scheduled or stage["純候補"] != e["候補"] or sum(stage["条件結果別"].values()) != e["候補"] or stage["仮約定"] != e["約定"] or not 0 <= stage["仮約定"] <= stage["発動"] <= stage["純候補"] <= scheduled:
                    raise ValueError("新条件入口の候補・発動・仮約定段階差")
                if (stage["実条件登録"], stage["実登録未約定"]) != (o["条件登録数"], o["条件未約定"]) or stage["実新規"] + stage["実登録未約定"] != stage["実条件登録"] or not o["完結数"] <= stage["実新規"] <= stage["実条件登録"]:
                    raise ValueError("一枚占有の登録・新規・未約定段階差")
    if sum(result["候補"][p][h]["入口"]["候補"] for p in NEW for h in PERIODS) != result["新条件入口評価"]:
        raise ValueError("新条件入口評価数の復元差")
    if result["採用"] != [p for p in NEW if all(result["候補"][p][h]["同時適格"] for h in PERIODS[:2])]:
        raise ValueError("新四政策の採用差")


def context_for() -> dict:
    """成功監査後に元六木・派生六木・旧教師参照を結合する。

    引数: なし。
    返り値: dictは純表示文脈。詳細圧縮・原板・教師個票は開かない。
    """
    names = ("結果.json", "保存物確認.json", "固定.json", "条件.json", "検証計画.md", "入力台帳.json", "一覧.resources.json")
    required = [STUDY / name for name in names]
    if any(not p.is_file() for p in required):
        raise FileNotFoundError("71主と正式保存監査の成功後だけ生成できます")
    result, proof, fixed = (read(p) for p in required[:3])
    validate_result(result)
    if result["固定SHA256"] != sha(required[2]) or proof.get("全件一致") is not True or proof.get("不一致数") != 0 or proof.get("不一致") != [] or proof["結果SHA256"] != sha(required[0]):
        raise ValueError("成功監査・結果・固定のSHA結合差")
    old, teacher = read(OLD / "結果.json"), read(SOURCE / "結果.json")
    for folder, payload in ((OLD, old), (SOURCE, teacher)):
        previous_proof = read(folder / "保存物確認.json")
        if previous_proof.get("全件一致") is not True or previous_proof.get("不一致数") != 0 or previous_proof["結果SHA256"] != sha(folder / "結果.json"):
            raise ValueError("旧保存対照又は教師の成功証明差")
    R69.validate_common(teacher["共通教師"])
    for phase in PHASES:
        common = teacher["共通教師"][phase]
        keys = ("全予定枠", "共通可知枠", "共通方向行", "除外枠数", "使用分類", "共通ID同順序", "方向重み")
        expected_common = {key: common[key] for key in keys}
        expected_common.update(旧69共通集合SHA256=fingerprint(common), 旧69結果path=(SOURCE / "結果.json").relative_to(ROOT).as_posix())
        if result["共通教師"][phase] != expected_common:
            raise ValueError("旧69共通集合の要約・全内容指紋差")
    for policy in CONTROLS:
        if any(result[key][policy] != old[key][policy] for key in ("候補", "役割別入口")):
            raise ValueError("旧70P保存対照の集計変更")
    models, raw_models = {}, {}
    sources = [*required, OLD / "結果.json", OLD / "保存物確認.json", OLD / "設定と結果.md", SOURCE / "結果.json", SOURCE / "保存物確認.json", SOURCE / "設定と結果.md", SHARED, EXTERNAL]
    raw_meta = {(e["policy"], e["phase"]): e for e in result["元学習モデル"]}
    cals = {e["id"]: e for e in result["回収集計"]}
    metadata = None
    for entry in result["モデル"]:
        raw_entry = raw_meta[entry["policy"], entry["phase"]]
        raw_path, path = ROOT / raw_entry["path"], ROOT / entry["path"]
        cal_entry = cals[entry["id"]]
        cal_path = ROOT / cal_entry["path"]
        if entry["元path"] != raw_entry["path"] or entry["元SHA256"] != raw_entry["SHA256"] or any(sha(p) != e["SHA256"] for p, e in ((raw_path, raw_entry), (path, entry), (cal_path, cal_entry))):
            raise ValueError("raw・派生・回収metaと指紋の差")
        source, model, cal = read(raw_path), read(path), read(cal_path)
        common = teacher["共通教師"][entry["phase"]]
        validate_fitted_model(source, None, common)
        validate_model(model, cal, source, common)
        count = 61 if entry["policy"] == "G0" else 60
        if source["model_id"] != raw_entry["id"] or model["model_id"] != entry["id"] or model["source_model_sha256"] != entry["元SHA256"] or model["policy"] != entry["policy"] or entry["特徴数"] != count or raw_entry["特徴数"] != count or result["剪定"][entry["phase"]][entry["policy"]] != model["pruning"]:
            raise ValueError("政策・特徴数・元/派生ID・剪定の接続差")
        if cal_entry["phase"] != entry["phase"] or cal_entry["policy"] != entry["policy"]:
            raise ValueError("回収metaのphase又は政策差")
        if metadata is not None and model["feature_meta"][:60] != metadata[:60]:
            raise ValueError("全六木の旧60metadata差")
        if count == 61:
            if model["feature_meta"][60] != POSITION_META:
                raise ValueError("F61の既存P01/price metadata差")
            metadata = model["feature_meta"]
        elif metadata is None:
            metadata = [*model["feature_meta"], deepcopy(POSITION_META)]
        raw_models[raw_entry["id"]] = {"base": source, "calibration": None, "base_path": raw_path, "path": raw_path, "entry": raw_entry, "kind": "元学習"}
        models[entry["id"]] = {"base": model, "calibration": cal, "base_path": path, "path": cal_path, "entry": entry, "source": source, "source_path": raw_path, "kind": "支持剪定後"}
        sources.extend((raw_path, path, cal_path))
    if sum(part["fit_performed"] for item in raw_models.values() for part in item["base"]["training"]["partition"].values()) != result["新回帰器fit"]:
        raise ValueError("元六木の実子回帰fit件数差")
    for phase in PHASES:
        pair = [item["base"] for item in raw_models.values() if item["entry"]["phase"] == phase]
        if pair[0]["training"]["row_ids"] != pair[1]["training"]["row_ids"] or pair[0]["training"]["base60_fingerprints"] != pair[1]["training"]["base60_fingerprints"]:
            raise ValueError("B/Gの共通教師ID又は旧60六指紋の差")
    conditions = read(STUDY / "条件.json")
    if metadata != conditions["特徴"]:
        raise ValueError("固定条件とB60/G61 metadataの差")
    resources = read(required[-1])["resources"]
    if len(resources) != 276 or Counter(r["method_id"] for r in resources) != {p: 46 for p in POLICIES} or any(not (ROOT / r["pnl_path"]).is_file() for r in resources):
        raise ValueError("旧92＋新184のViewer276参照差")
    sources.extend([HERE / "README.md", *sorted(HERE.glob("*.py")), *sorted(HERE.glob("*仕様.md"))])
    for p in sources:
        if not p.is_file():
            raise FileNotFoundError(p)
        name = p.relative_to(ROOT).as_posix()
        if name in fixed["ファイルSHA256"] and sha(p) != fixed["ファイルSHA256"][name]:
            raise ValueError("固定出典変更:" + name)
    return {"result": result, "proof": proof, "fixed": fixed, "old": old, "teacher": teacher, "models": models,
        "raw_models": raw_models, "all_models": {**raw_models, **models}, "metadata": metadata, "sources": list(dict.fromkeys(sources))}


def common_table(context: dict) -> str:
    """同69C教師の件数と六指紋を参照表示し、ID全件を複製しない。

    引数: context(dict)は旧教師と各元学習木を持つ表示文脈。
    返り値: strは共通集合・除外数・各入力指紋の表。
    """
    rows, hashes = [], []
    for phase in PHASES:
        group = context["teacher"]["共通教師"][phase]
        rows.append([phase, group["全予定枠"], group["共通可知枠"], group["共通方向行"], group["除外枠数"], shown(group["評価開始"]), shown(group["使用分類"]["C0"]), context["result"]["共通教師"][phase]["旧69共通集合SHA256"]])
    for identity, item in context["raw_models"].items():
        t = item["base"]["training"]
        hashes.append([identity, t["row_ids_sha256"], t["input_rows_sha256"], t["target_rows_sha256"], shown(t["base60_fingerprints"])])
    return ("## 旧69C条件教師と同じ共通可知集合\n\n今回も旧69の確定可知pair・条件入口回収を使い、新独立計測は0。確定無取引0は回帰に含めるが、125敗北又は障壁分母にしない。未知は0補完せず、旧のpair全体除外をそのまま保持する。g欠落は接続失敗であり、追加の教師除外・新mask・片側救済を行わない。\n\n"
        + table(["phase", "旧全予定枠", "共通可知枠", "方向行", "旧除外枠", "評価開始・strict前", "C使用分類", "旧69共通集合SHA256"], rows)
        + table(["元木", "共通ID指紋", "全入力行指紋", "回収目的指紋", "旧60の六指紋"], hashes)
        + "全使用IDと除外理由は旧69正本だけに保存し、今回MDへ転記しない。B60とG61のfull入力指紋は列差があり、base60指紋・教師ID・目的・期間の同一性と分ける。\n\n"
        + link(SOURCE / "結果.json", STUDY / "設定と結果.md", "旧共通集合の小型正本") + " / " + link(SOURCE / "設定と結果.md", STUDY / "設定と結果.md", "旧教師と全除外の説明") + "\n\n")


def settings(context: dict) -> list[dict]:
    """旧60共通セルとG専用の取得位置セルを版5へ表示する。

    引数: context(dict)は60＋F61のmetadataを持つ文脈。
    返り値: list[dict]は設定IDと複合評価ID。
    """
    rows = deepcopy(PREVIOUS.settings({**context, "metadata": context["metadata"][:60]})[:60])
    for row in rows:
        row.update(結果短記="R01/R02/R03/R04/R05/R06", 説明="旧Pと新B/Gで共通の旧60特徴。複合成績を単独指標の効果としない。")
    rows.append({"設定ID": "S61", "手法ID": ["P01"], "尺度ID": ["m15"], "短記": "G専用g=s*(M-E*)/D", "結果短記": "R05/R06", "説明": "Bは60列、Gだけ61列。公開15分端と当時正常BBO。既存価格加工の重複を含み、新独立票でない。"})
    extras = [(["M01", "P10"], ["m03", "m15", "m30"], "同69C教師・同固定容量でB60/G61を別fit", "元6木最大24子fit、同70支持剪定後の派生6木。剪定ではfitしない。"),
        (["M01"], ["m03", "m15", "tick"], "filled支持・score・異種技法と回収資格", "scoreは250/約定、支持60枠6日10場。1政策だけ主回収総額strict正。同点/片側未知WAIT。"),
        (["P02", "P09", "B01"], ["m03", "tick"], "同68条件突破・発動前反対端否定", "気配E*と将来実約定は別。未発動を全分母から消さない。"),
        (["E01", "E02", "C06"], ["tick"], "固定O49・現在益122円strict正・連続保護", "D・床を広げず、pendingでh/L/arm凍結。250TPなし。"),
        (["C07"], ["m15"], "全25/49予定枠・保守待ち50%以下", "保有継続非待ち。登録未約定は保守待ちへ。")]
    for methods, scales, short, description in extras:
        rows.append({"設定ID": f"S{len(rows) + 1:02d}", "手法ID": methods, "尺度ID": scales, "短記": short, "結果短記": "R03/R04/R05/R06", "説明": description})
    return rows


def documents(context: dict) -> dict[str, str]:
    """再学習と支持剪定と旧70対照を分離して二本文を組み立てる。

    引数: context(dict)は正式又は人工表示文脈。
    返り値: dict[str,str]は二MD。書込・fit・再生・予測をしない。
    """
    r, proof = context["result"], context["proof"]
    brief, detail = STUDY / "README.md", STUDY / "設定と結果.md"
    entrance, operations = main_tables(r)
    status = "新候補の採用なし。支持付き先着70・費用・全予定保守待ち50%以下の同時目標は未達。" if not r["採用"] else "保存採用候補：" + "、".join(r["採用"]) + "。未見利益の保証ではない。"
    intro = ("全66場既使用。初20は学習専用、結果学習欄は後20時系列、選択24、既使用後続2を分ける。\n\n" + status
        + f'\n\n旧70P0/P1保存92運用、新B0/B1/G0/G1各46場184運用、Viewer276。元学習6木＋支持剪定後派生6木＝保存12木。実子回帰fit{r["新回帰器fit"]}（予定最大24）、新分類fit0、新独立計測0。参照独立方向4092は旧69保存測定。\n\n'
        "Bは旧60列、GだけF61取得位置を追加。B→Gが同69C教師・同容量・同剪定規約の情報追加比較であり、旧70Pとの差をg単独効果としない。1政策は各0と同じ派生木に主回収strict正を加える。元学習と支持剪定を別段階として表示する。\n\n")
    mechanics = ("## 取得位置と固定した判断・条件入口・保護\n\nF61はg=s*(M−E*)/D。買いM=当時公開15分high・E*=ask、売りM=low・E*=bid。原判断session/slot_id/scheduled/time/lineの5keyで正常BBOを結び、Lastの追加gateは設けない。Fraction(str)で差と除算→有限float64、学習walkはfloat32。clip・符号条件・新mask・0補完はしない。旧readyの欠落や不整合は接続失敗で止める。\n\n"
        "Mは実証された支持抵抗ではなく既知足端、E*は将来の条件発動後の実約定ではない。gは旧上位幅・終値位置と、上位終値対気配の差をDへ変換した組合せであり、独立した前方余地の証拠とはしない。主要な追加は気配差と表現の組合せで、既存P01/priceの価格構造。新しい独立技法票・反転確認・残り250ptの保証にせず、後方の構造否定線までの距離とも分ける。\n\n"
        "デイ09:15〜15:15の25枠、ナイト17:30〜05:30の49枠。両方向同じ関数、同点・片側score未知はWAIT。66選択によりscore>=1/3・filled60枠6日10場・異種技法・回収支持を満たす側内でscore最高側。B1/G1だけ主回収総額strict正を加え、0政策との同方向部分集合を断定しない。raw DI0は最終WAIT、float32根の零化とは別。V1はbから有効でr/k成立を保証しない。\n\n"
        "定時に最新公開完全3分high/lowを凍結し、買Last>high／売Last<lowで要求。設定既超過を拒否、買Last<=low／売Last>=highは発動前否定。設定否定は未登録WAIT、監視否定は登録未約定で品質注意にしない。normal BBO＋有限正Last、watch後gap>300秒観測不足は品質。次定時T+900でwatch/新規pending取消、発動後1価格時計秒・後行BBO・TTL30秒も次定時未満。発動後へ新否定を足さず、足内順序を推測しない。\n\n"
        "主待ち=WAIT/全予定、保守=(WAIT＋判定不能＋登録後entryなし)/全予定、保有継続非待ち。micro10円/pt・片道11円＋滑り5ptで主往復122円。現在返済BBOの粗益−122円strict正で利益旗と最低名目新規床、損失側も連続非緩和。Dは定時ATR5pt切上げ・5..125固定、返済pendingでh/L/arm凍結。強制15:35/05:50、終了15:40/05:55、残60停止なし・250TPなし。費用0/10感応は同約定・起動122円維持。名目床は実損又は費用後同値の保証ではない。\n\n")
    links = ("## 正本・再表示\n\n" + " / ".join(link(STUDY / name, brief) for name in ("設定と結果.md", "検証計画.md", "条件.json", "結果.json", "保存物確認.json", "一覧.resources.json")) + " / " + link(HERE / "README.md", brief, "コードと再現") + " / " + link(OLD / "設定と結果.md", brief, "旧70P保存対照")
        + f'\n\n[Viewer](http://127.0.0.1:8092)：276資源。監査{proof["照合項目数"]}照合・差{proof["不一致数"]}。範囲は監査JSONを正本とする。\n\n'
        "~~~powershell\nwork/venvs/technical-tree/Scripts/python.exe -X utf8 scripts/取得位置と支持/レポート.py\nwork/venvs/technical-tree/Scripts/python.exe -X utf8 scripts/取得位置と支持/レポート.py --check\n~~~\n")
    uses = settings(context)
    matrix = V5.matrix(V5.load_catalog(), detail, uses).replace("未使用", "未使用・未検証")
    features = table(["ID", "特徴", "対象", "手法", "family", "尺度", "式・範囲"], [[m["id"], m["name"], "G専用追加" if i == 60 else "旧P/B/G共通60", m["method"], m["family"], m["scale"], FORMULAS[i]] for i, m in enumerate(context["metadata"])])
    setting_rows = table(["設定ID", "手法/尺度", "設定内容", "限定"], [[x["設定ID"], "/".join(x["手法ID"]) + "・" + "/".join(x["尺度ID"]), x["短記"], x["説明"]] for x in uses])
    sources = table(["出典", "SHA256"], [[link(p, detail), sha(p)] for p in context["sources"]])
    external = ("## 原典と独自の取得位置\n\nAlphatrendsの取得前の二問は、来た距離と前方の理論余地を保護の管理と分ける。Grimesの未到達利益の読者事例は、入口足の往復と後日の不進行、事前規則と結果後の感情的変更を分ける。" + link(EXTERNAL, detail, "71前の本人・運営組織2本文と適用限界") + "。商用教育説明で全件の費用後検定ではなく、心理は推論。当時gは将来取得や構造否定距離ではない。部分返済・数量調整・裁量退出をO49へ移植せず、7割又は最適な保護幅の根拠としない。\n\n")
    overview = "# 00071：技法の組み合わせへ取得位置を加える\n\n" + intro + "## 条件入口先着\n\n" + entrance + "## 実一枚の回収\n\n" + operations + mechanics + links
    detailed = ("# 00071：設定と結果\n\n" + intro + "R01=旧P0、R02=旧P1、R03=B0、R04=B1、R05=G0、R06=G1。\n\n## 手法×尺度・版5全文\n\n55手法×9尺度を全文保持。旧60と追加G専用F61の使用セルを分け、複合評価を単独技法の効果としない。\n\n" + matrix
        + "## 旧60特徴とG専用F61\n\n" + features + "## 設定明細\n\n" + setting_rows + common_table(context) + pruning_tables(context, detail) + model_tables(context, detail)
        + "## 条件入口先着\n\n" + entrance + "## 実一枚の回収\n\n" + operations + detail_tables(r) + mechanics + external
        + "## 検査と限界\n\n独立一枠回収の重複建玉合算は同時実行戦略の利益ではない。先着250/125・無取引0・filled支持・実一枚回収を別分母とし、品質注意時の確定nullを0補完しない。全66場既使用・11月5日Day未予約未読、今回も未見検証ではない。\n\n入力検査：" + shown(r["入力検査"]) + "。今回検査：" + shown(r["検査"]) + "。\n\n## 保存出典\n\n" + sources + "## 再表示\n\n" + link(brief, detail, "概要と表示コマンド") + "\n")
    return {"README.md": overview, "設定と結果.md": detailed}


def validate_documents(output: dict[str, str], generated: set[Path]) -> int:
    """全61特徴・版5全文と内部リンクを検査する。

    引数: output(dict[str,str])は二本文、generated(set[Path])は同時生成又は人工参照。
    返り値: intは照合したリンク数。
    """
    text = output["設定と結果.md"]
    ids = {m["id"] for m in V5.load_catalog()["methods"]}
    rows = [s for s in text.splitlines() if s.startswith("| ") and s.split("|")[1].strip() in ids]
    if len(rows) != 55 or any(len(s.split("|")) != 13 for s in rows):
        raise ValueError("55手法×9尺度不足")
    if any("| " + f"F{i:02d}" + " |" not in text for i in range(1, 62)):
        raise ValueError("旧60＋F61の全特徴不足")
    return sum(R55.G.check_links(s, STUDY / name, generated) for name, s in output.items())


# ----------------------------------------

def validate_fitted_model(model: dict, calibration: dict, common: dict) -> None:
    """60/61列の元学習木と派生木について、全回帰と約定支持を検査する。

    引数: model/calibration(dict|None)は同ID保存物、common(dict)は共通教師。
    返り値: None。木の走査・fit・教師再計算はしない。
    """
    structure, training = model["structure"], model["training"]
    count = 61 if model["policy"] == "G0" else 60
    if model["policy"] not in MODEL_POLICIES or len(model["feature_meta"]) != count or structure["kind"] != "fixed_direction_current_episode":
        raise ValueError("B0/G0・60/61列・固定構造の差")
    fixed = [{"id": 0, "feature": "F01", "index": 0, "threshold": 0.0}, {"id": 1, "feature": "F26", "index": 25, "threshold": 0.5}, {"id": 2, "feature": "F20", "index": 19, "threshold": 0.5}]
    projection = {"D0": [i for i in range(count) if i not in (0, 25)], "D1": [i for i in range(count) if i not in (0, 19)]}
    if structure["fixed_nodes"] != fixed or structure["child_feature_indices"] != projection or (structure["max_depth"], structure["child_depth"], structure["child_features"]) != (4, 2, count - 2):
        raise ValueError("固定三nodeと枝別58/59列の差")
    ids = [{**r, "side": side} for r in common["使用枠"] for side in (1, -1)]
    if training["row_ids"] != ids or training["direction_rows"] != len(ids) or training["input_pairs"] != len(common["使用枠"]) or training["evaluation_start"] != common["評価開始"]:
        raise ValueError("新木と共通教師ID・方向数・評価時計の差")
    period = training["period"]
    if period["same_second_allowed"] is not False or period["evaluation_start"] != common["評価開始"] or any(not math.isfinite(period[k]) or period[k] >= common["評価開始"] for k in ("max_label_end_time", "max_recovery_end_time")):
        raise ValueError("新木の障壁・回収終端は評価開始よりstrict前")
    if set(training["partition"]) != {f"D{d}_V{v}" for d in (0, 1) for v in (0, 1)}:
        raise ValueError("DI×現在有効の四子が必要")
    if sum(x["direction_rows"] for x in training["partition"].values()) != len(ids):
        raise ValueError("四子の方向行復元差")
    if calibration is not None and (calibration["model_id"] != model["model_id"] or calibration["policy"] != model["policy"] or calibration["evaluation_start"] != common["評価開始"]):
        raise ValueError("回収集計と新木のID・政策・時点差")
    leaves = set()
    for n in model["nodes"]:
        total, filled = n["direction_rows"], n["filled_direction_rows"]
        if not 0 <= filled <= total or n["unfilled_direction_rows"] != total - filled or n["total_weight"] != total * 0.5 or n["barrier_total_weight"] != filled * 0.5:
            raise ValueError("全回帰行と約定先着分母の差")
        if n["data_absent"] != (total == 0) or n["barrier_data_absent"] != (filled == 0):
            raise ValueError("空回帰葉と全無取引葉の区別差")
        if (n["score"] is None) != (filled == 0) or filled and not math.isclose(n["score"], n["success_weight"] / (filled * 0.5), rel_tol=0, abs_tol=1e-12):
            raise ValueError("障壁scoreは約定既知だけが分母")
        if (n["fill_rate"] is None) != (total == 0) or total and not math.isclose(n["fill_rate"], filled / total, rel_tol=0, abs_tol=1e-12):
            raise ValueError("約定率の全方向分母差")
        if (n["recovery_mse_decimal"] is None) != (total == 0):
            raise ValueError("全無取引MSE0と空MSE未知の区別差")
        expected_support = n["unique_slots"] >= 60 and n["days"] >= 6 and n["sessions"] >= 10
        if n["leaf_support"] != expected_support:
            raise ValueError("約定既知の60枠6日10場と葉支持の差")
        expected_positive = Decimal(n["recovery"]["pnl5"]["sum"]) > 0 if total else None
        if n["recovery_positive"] is not expected_positive:
            raise ValueError("主回収総額の符号と木の正額資格の差")
        for cost in (0, 5, 10):
            all_cash, fill_cash = n["recovery"]["pnl" + str(cost)], n["recovery_filled"]["pnl" + str(cost)]
            if Decimal(all_cash["sum"]) != Decimal(fill_cash["sum"]) or (all_cash["mean"] is None) != (total == 0) or (fill_cash["mean"] is None) != (filled == 0):
                raise ValueError("全回収とfilled回収の合計・null差")
        if n["left"] != -1:
            continue
        leaves.add(str(n["id"]))
        if calibration is None:
            continue
        cal = calibration["leaves"][str(n["id"])]
        if cal["positive"] is not bool(expected_positive):
            raise ValueError("主回収総額の符号と回収正額資格の差")
        if (cal["all_direction_rows"], cal["direction_rows"], cal["support"], cal["fill_rate"]) != (total, filled, n["leaf_support"], n["fill_rate"]):
            raise ValueError("回収資格は約定支持・全平均は別欄")
        for cost in (0, 5, 10):
            if (cal["sum_yen"][str(cost)], cal["mean_yen"][str(cost)], cal["mean_all_yen"][str(cost)]) != (n["recovery_filled"]["pnl" + str(cost)]["sum"], n["recovery_filled"]["pnl" + str(cost)]["mean"], n["recovery"]["pnl" + str(cost)]["mean"]):
                raise ValueError("calのfilled平均と全平均の転記差")
    if calibration is not None and set(calibration["leaves"]) != leaves:
        raise ValueError("回収集計の全葉不足")

# ----------------------------------------

def validate_model(model: dict, calibration: dict, source: dict, common: dict) -> None:
    """元親統計と剪定後配置を混同せず、保存由来と回収分母を検査する。

    引数: model/calibration(dict)はB0/G0派生物、source(dict)は同政策の新元木、common(dict)は旧69共通教師の正本。
    返り値: None。再剪定・fit・教師生成・予測walkは行わない。
    """
    pruning = model["pruning"]
    if model["policy"] != source["policy"] or source["policy"] not in MODEL_POLICIES or model["source_model_id"] != source["model_id"] or pruning["source_model_id"] != source["model_id"] or pruning["fit_count"] != 0:
        raise ValueError("派生木の元学習出所又は新fit0の差")
    if model["source_model_sha256"] != pruning["source_model_sha256"]:
        raise ValueError("派生木と剪定の元byte指紋差")
    for key, value in source.items():
        if key not in ("model_id", "policy", "nodes") and model.get(key) != value:
            raise ValueError("元の学習証拠・metadata・規約変更:" + key)
    old_nodes, nodes = source["nodes"], model["nodes"]
    mapping, reverse = pruning["source_to_new"], pruning["new_to_source"]
    retained = [i for i in range(len(old_nodes)) if mapping.get(str(i)) is not None]
    if pruning["source_node_count"] != len(old_nodes) or pruning["new_node_count"] != len(nodes) or set(mapping) != {str(i) for i in range(len(old_nodes))} or reverse != {str(i): old for i, old in enumerate(retained)} or any(mapping[str(old)] != i for i, old in enumerate(retained)):
        raise ValueError("元ID昇順の圧縮と全旧新対応の差")
    if retained[:3] != [0, 1, 2] or len(nodes) != len(retained):
        raise ValueError("固定三節点は維持する")
    decisions = {d["source_node_id"]: d for d in pruning["decisions"]}
    expected_decisions = {n["id"] for n in old_nodes if n["id"] >= 3 and n["left"] != -1}
    if set(decisions) != expected_decisions or len(decisions) != len(pruning["decisions"]):
        raise ValueError("元の学習分割の全剪定判断が必要")
    for old_id, decision in decisions.items():
        details = [{"source_node_id": i, "unique_slots": old_nodes[i]["unique_slots"], "days": old_nodes[i]["days"], "sessions": old_nodes[i]["sessions"], "supported": old_nodes[i]["unique_slots"] >= 60 and old_nodes[i]["days"] >= 6 and old_nodes[i]["sessions"] >= 10} for i in decision["terminal_source_ids"]]
        keep = all(d["supported"] for d in details)
        if decision["terminal_support"] != details or decision["action"] != ("保持" if keep else "両側統合") or decision["result_terminal_source_ids"] != (decision["terminal_source_ids"] if keep else [old_id]):
            raise ValueError("剪定は終端の約定支持だけで判定する")
        if decision["retained_in_final"] != (old_id in retained) or decision["split_retained_in_final"] != (old_id in retained and keep):
            raise ValueError("途中の剪定判断と最終残存を分離する")
    topology = {"id", "feature", "feature_id", "family", "threshold", "left", "right", "path"}
    reached = {0}
    for new_id, old_id in enumerate(retained):
        current, original = nodes[new_id], old_nodes[old_id]
        if current["id"] != new_id or current["source_node_id"] != old_id or new_id not in reached:
            raise ValueError("新ID又は元ID・到達性の差")
        if {k: v for k, v in current.items() if k not in topology | {"source_node_id"}} != {k: v for k, v in original.items() if k not in topology}:
            raise ValueError("元親の保存統計を変更している")
        expected_path = [{**p, "node": mapping[str(p["node"])]} for p in original["path"]]
        if current["path"] != expected_path:
            raise ValueError("pathは元閾値を保持しnode IDだけ圧縮する")
        collapsed = old_id in decisions and decisions[old_id]["action"] == "両側統合"
        if original["left"] == -1 or collapsed:
            if (current["feature"], current["feature_id"], current["family"], current["threshold"], current["left"], current["right"]) != (-2, None, None, -2.0, -1, -1):
                raise ValueError("統合葉のsentinel差")
        else:
            if any(current[k] != original[k] for k in ("feature", "feature_id", "family", "threshold")) or (current["left"], current["right"]) != (mapping[str(original["left"])], mapping[str(original["right"])]) or not new_id < current["left"] < len(nodes) or not new_id < current["right"] < len(nodes):
                raise ValueError("保持分割又は子対応の差")
            reached.update((current["left"], current["right"]))
    if reached != set(range(len(nodes))):
        raise ValueError("孤立nodeがある")
    for key, old_group in source["training"]["partition"].items():
        item = pruning["partitions"][key]
        stack, members = [old_group["root"]], []
        while stack:
            i = stack.pop()
            members.append(i)
            if old_nodes[i]["left"] != -1:
                stack.extend((old_nodes[i]["left"], old_nodes[i]["right"]))
        expected = {"source_root": old_group["root"], "source_node_count": old_group["node_count"], "new_root": mapping[str(old_group["root"])], "new_node_count": sum(i in retained for i in members)}
        if item != expected:
            raise ValueError("元training配置と新pruning配置の差")
    validate_fitted_model(model, calibration, common)

# ----------------------------------------

def main_tables(result: dict) -> tuple[str, str]:
    """六政策の条件入口先着と一枚実回収を異なる分母で表示する。

    引数: result(dict)は小型結果。
    返り値: tuple[str,str]は入口と実運用の二表。
    """
    entrances, operations = [], []
    for p in POLICIES:
        for h in PERIODS:
            e, o = result["候補"][p][h]["入口"], result["候補"][p][h]["運用"]
            entrances.append([p, PERIOD_NAMES[h], e["候補"], f'{e["250"]}/{e["約定"]}', rate(e["率"]), f'{e["間引き250"]}/{e["間引き約定"]}', rate(e["間引き率"]), f'{e["日数"]}日/{e["場数"]}場', qualification(e["支持"]), qualification(e["70目標"])])
            operations.append([p, PERIOD_NAMES[h], o["完結数"], money(o["完結観測額円"]["5"]), money(o["全体確定額円"]["5"]), len(o["品質注意場"]), rate(o["主待ち率"]), rate(o["待ち率保守上限"]), qualification(o["活動適格"]), f'{o["利益起動件数"]}/{o["起動後赤字件数5"]}', qualification(o["費用適格"]), qualification(result["候補"][p][h]["同時適格"])])
    return table(["候補", "期間", "純候補", "250/仮約定", "主率", "非重複250/約定", "非重複率", "日/場", "入口支持", "70目標"], entrances), table(["候補", "期間", "実完結", "観測5円", "全体確定5円", "品質注意場", "主待ち", "保守上限", "活動", "利益旗/旗後赤字", "費用", "同時適格"], operations)

# ----------------------------------------

def detail_tables(result: dict) -> str:
    """全期間・実役割・費用・判断理由と条件段階を保存値で表示する。

    引数: result(dict)は六政策の結果。
    返り値: strは純と実を加算せずに示す詳細表。
    """
    costs, roles, stages, reasons = [], [], [], []
    for p in POLICIES:
        for h in PERIODS:
            o = result["候補"][p][h]["運用"]
            costs.append([p, PERIOD_NAMES[h], o["予定枠"], shown(o["判断別"]), o["条件登録数"], o["条件未約定"], o["完結数"], *(money(o["完結観測額円"][str(f)]) for f in (0, 5, 10)), *(money(o["全体確定額円"][str(f)]) for f in (0, 5, 10)), o["未解消"], shown(o["品質注意場"])])
            for role in ("順行", "反転"):
                e, actual = result["役割別入口"][p][h][role], o["役割別完結"][role]
                roles.append([p, PERIOD_NAMES[h], role, e["候補"], f'{e["250"]}/{e["約定"]}', rate(e["率"]), qualification(e["支持"]), actual["件数"], money(actual["観測純額5"])])
            if p in NEW:
                stages.extend([p, PERIOD_NAMES[h], k, shown(v)] for k, v in result["条件段階"][p][h].items())
                reasons.extend([p, PERIOD_NAMES[h], k, n] for k, n in result["判断理由"][p][h].items())
    return ("## 予定枠・費用と品質\n\n品質注意又は未解消は期間全体確定null。観測額・役割別観測額を無条件確定としない。\n\n"
        + table(["政策", "期間", "全予定", "実判断別", "登録", "登録未約定", "完結", "観測0", "観測5", "観測10", "確定0", "確定5", "確定10", "未解消", "品質注意場"], costs)
        + "## DI役割別の純入口と実回収\n\n価格T/Rの名称、現在episode有効、raw DIに対する実役割は別。薄化・仮先着と実一枚を加算しない。\n\n"
        + table(["政策", "期間", "実役割", "純候補", "250/仮約定", "主率", "入口支持", "実完結", "観測5円"], roles)
        + "## 条件段階と当時の保存判断理由\n\n条件登録actionは当時の指示、発動・未約定等はその後の結果。保有又はpendingの占有と独立仮入口を混同しない。\n\n"
        + table(["政策", "期間", "段階", "保存値"], stages) + table(["政策", "期間", "保存判断理由", "枠数"], reasons))

# ----------------------------------------

def pruning_tables(context: dict, output: Path) -> str:
    """全元ID対応・途中判断・四子の新配置を保存値で表示する。

    引数: context(dict)は派生三木、output(Path)は詳細MD。
    返り値: strは全剪定判断と配置。学習統計を再算しない。
    """
    summary, mappings, decisions, partitions = [], [], [], []
    for identity, item in context["models"].items():
        model, p = item["base"], item["base"]["pruning"]
        summary.append([identity, link(item["source_path"], output, p["source_model_id"]), p["source_model_sha256"], p["source_node_count"], p["new_node_count"], p["fit_count"]])
        mappings.extend([identity, old_id, shown(new_id, "削除"), "固定段" if int(old_id) < 3 else "元の学習子"] for old_id, new_id in p["source_to_new"].items())
        for d in p["decisions"]:
            decisions.append([identity, d["source_node_id"], d["action"], shown(d["terminal_source_ids"]), shown(d["terminal_support"]), shown(d["result_terminal_source_ids"]), qualification(d["retained_in_final"]), qualification(d["split_retained_in_final"]), d["reason"]])
        for group, part in p["partitions"].items():
            partitions.append([identity, group, part["source_root"], part["source_node_count"], part["new_root"], part["new_node_count"]])
    return ("## 支持だけによる剪定と旧新ID\n\n固定node0/1/2とDI×現在有効の四群を保持する。各学習子を下から確認し、その時点の終端に一つでもfilled60枠・6日・10場未達があれば両側を親へ統合する。score・回収・MSE・技法資格や評価成績を剪定基準にしない。四群の親も支持不足なら固定段を越えずWAITを残す。両側統合は文脈を混ぜ得るので改善を保証しない。\n\n"
        + table(["派生木", "元保存木", "元byte SHA256", "元node数", "残存node数", "新fit"], summary)
        + table(["派生木", "元群", "元root", "元node数", "新root", "新node数"], partitions)
        + "training.partitionのroot/node数/fitは元69の証拠。新配置は上のpruning.partitionsだけを用いる。残存元ID昇順で新連番にし、各新nodeにsource_node_idを保存する。元学習の閾値・親の回収統計を再用し、新たな教師再集計や子平均の平均で置き換えない。\n\n"
        + table(["派生木", "元ID", "新ID", "種別"], mappings)
        + "以下は元の全学習分割の判断。途中で保持した分割も、後で祖先が統合されれば最終木から除かれる。途中判断と最終残存を分ける。\n\n"
        + table(["木", "判断元ID", "判断", "判断時の終端元ID", "終端filled支持", "判断後終端元ID", "最終残存", "最終分割保持", "理由"], decisions))

# ----------------------------------------

def render(check: bool = False) -> dict:
    """正式結果の二文書を生成するか保存同byteを検査する。

    引数: check(bool)は書込なしの同byte照合。
    返り値: dictは成果物SHA・サイズ・表・リンク。
    """
    output = documents(context_for())
    links = validate_documents(output, {(STUDY / n).resolve() for n in output})
    reports = {}
    for name, text in output.items():
        path, content = STUDY / name, text.encode("utf-8")
        if check:
            if path.read_bytes() != content:
                raise ValueError("保存文書と同byteでない:" + name)
        else:
            path.write_bytes(content)
        reports[name] = {"SHA256": sha(path), "bytes": len(content)}
    return {"文書": reports, "内部リンク検査": links, "欠落": 0, "版": 5, "手法": 55, "尺度": 9, "全特徴": 61,
        "表示中fit": 0, "再計測_教師再生成_市場再生": False, "同byte確認": check}

# ----------------------------------------

def self_test() -> dict:
    """実入力なしの人工表示検査を呼ぶ。

    引数: なし。
    返り値: dictは成功とテスト件数。失敗時は終了1。
    """
    spec = importlib.util.spec_from_file_location("取得位置71表示の人工", HERE / "レポートの人工検査.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.run(sys.modules[__name__])

# ----------------------------------------

def main() -> None:
    """正式生成・同byte・人工だけのCLIを選択する。

    引数: なし。--checkと--self-testは排他的。
    返り値: None。正式生成はrootの主・監査成功通知後だけ行う。
    """
    parser = argparse.ArgumentParser()
    options = parser.add_mutually_exclusive_group()
    options.add_argument("--check", action="store_true")
    options.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    print(json.dumps(self_test() if args.self_test else render(args.check), ensure_ascii=False))

# ----------------------------------------

def model_tables(context: dict, output: Path) -> str:
    """元六木と派生六木の全node・全path・支持・二種類の回収平均を表示する。

    引数: context(dict)は新モデル、output(Path)は詳細MD。
    返り値: strは閾値を省略しない表。円予測を先着率に読み替えない。
    """
    meta, parts, nodes, cash, calibrations = [], [], [], [], []
    for identity, item in context["all_models"].items():
        m, cal = item["base"], item["calibration"]
        meta.append([item["kind"], link(item["base_path"], output, identity), m["policy"], item["entry"]["phase"], len(m["nodes"]), "pnl5・squared_error", len(item["entry"]["学習場"]), len(item["entry"]["評価場"])])
        for key, group in m["training"]["partition"].items():
            parts.append([identity, key, group["route"], group["direction_rows"], group["pair_unique"], group["days"], group["sessions"], group["root"], group["node_count"], qualification(group["fit_performed"])])
        for n in m["nodes"]:
            split = "葉" if n["left"] == -1 else m["feature_meta"][n["feature"]]["id"] + " <= " + shown(n["threshold"]) + ("（固定）" if n["id"] < 3 else "")
            path = " ∧ ".join(p["feature_id"] + p["comparison"] + shown(p["threshold"]) for p in n["path"]) or "根"
            nodes.append([identity, n["id"], shown(n.get("source_node_id"), "元木自身"), split, f'{n["left"]}/{n["right"]}', path, n["direction_rows"], n["filled_direction_rows"], n["unfilled_direction_rows"], shown(n["fill_rate"]), shown(n["score"]), f'{n["all_unique_slots"]}/{n["all_days"]}/{n["all_sessions"]}', f'{n["unique_slots"]}/{n["days"]}/{n["sessions"]}', qualification(n["leaf_support"]), "/".join(n["families"]) or "なし", qualification(n["method_support"])])
            state = "空回帰・先着未知" if n["data_absent"] else "全無取引・回帰0既知/先着未知" if n["barrier_data_absent"] else "約定既知あり"
            for fee in (0, 5, 10):
                a, f = n["recovery"]["pnl" + str(fee)], n["recovery_filled"]["pnl" + str(fee)]
                cash.append([identity, n["id"], fee, state, a["sum"], shown(a["mean_decimal"]), f["sum"], shown(f["mean_decimal"]), shown(n.get("regression_value"), "対象外又は空"), shown(n.get("impurity"), "対象外又は空"), shown(n["recovery_mse_decimal"])])
            if n["left"] == -1 and cal is not None:
                q = cal["leaves"][str(n["id"]) ]
                calibrations.append([identity, n["id"], q["all_direction_rows"], q["direction_rows"], f'{q["unique_slots"]}/{q["days"]}/{q["sessions"]}', shown(q["fill_rate"]), shown(q["sum_yen"]), shown(q["mean_yen"]), shown(q["mean_all_yen"]), qualification(q["support"]), qualification(q["positive"])])
    return ("## 元六木と派生六木の全node・全回収葉\n\nB0は旧60列、G0だけ61列。各三phaseの元木を同69C条件教師・同じ固定三段/子深さ2/全深さ4で別fitし、各元木を同70の約定支持規約で剪定する。B1/G1は各0の同派生木。固定根はfloat32 F01<=0、低側R F26<=0.5／高側T F20<=0.5。D0はindex0/25、D1はindex0/19を除く子58/59列。minleaf60・seed51・方向重み0.5を維持。V1はbから有効でr/k成立ではなく、raw DI0は最終WAIT。\n\n"
        + table(["段階", "保存木", "政策", "phase", "全node数", "回帰目的", "過去場", "評価場"], meta)
        + table(["木", "固定群", "対応", "全方向行", "unique枠", "日", "場", "元子root", "元子node数", "元fit"], parts)
        + "上の元子root/node数/fitは各raw学習のtraining.partition証拠であり、派生配置はpruning.partitionsを用いる。新配置は剪定対応表を参照する。先着scoreは250/約定既知だけ、無取引0は回帰に含む。支持60枠・6日・10場も約定既知だけで、全回帰行のminleaf60とは異なる。固定trend+priceは従来技法資格を構造的に充足するが、独立証拠が増えたとはしない。\n\n"
        + table(["木", "node", "元node", "分岐・左<=右>", "左/右", "全path", "全回帰行", "filled行", "無取引行", "約定率", "条件付き先着score", "全unique/日/場", "filled unique/日/場", "filled葉支持", "path family", "技法資格"], nodes)
        + "回帰目的は無取引0込みpnl5のMSE。目的平均を先着確率とは呼ばず、方向順位は障壁score、両側資格を先に評価する固定66選択を維持する。同点・片側score未知はWAITで、0政策と正回収1政策は逆方向になり得る。\n\n"
        + table(["木", "node", "滑りpt", "回帰/障壁の状態", "全合計円", "全平均Decimal円", "filled合計円", "filled平均Decimal円", "元保存予測5円", "元保存MSE5円²", "元Decimal MSE5円²"], cash)
        + "全無取引葉は全平均0・MSE0が既知でもscoreとfilled平均はnull。空回帰葉は両平均・MSEともnull。raw欄の平均/MSEは今回学習した保存値。派生欄は同じraw親の値を継承し、剪定時の新fit値ではない。固定三nodeは元学習器の生予測対象外で、所属からの統計と区別する。calのpositive=Falseは不適格であり空の平均0ではない。\n\n"
        + table(["木", "葉", "全行", "filled行", "filled unique/日/場", "約定率", "合計円0/5/10", "filled平均円0/5/10", "全平均円0/5/10", "回収支持", "主合計strict正"], calibrations))


if __name__ == "__main__":
    main()
