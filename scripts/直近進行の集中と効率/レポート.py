"""73の直近進行C/E/J追加を、正式成功後の保存JSONだけで表示する。"""

import argparse
from collections import Counter
from copy import deepcopy
from decimal import Decimal
import hashlib
import importlib.util
import json
import math
from fractions import Fraction
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
STUDY = ROOT / "study/00073_直近の集中と方向効率を組み合わせる"
OLD = ROOT / "study/00072_分割候補から約定支持を確保する"
SOURCE = ROOT / "study/00069_条件入口に合わせて技法群の教師を作る"
SHARED = HERE.parent / "支持を満たす技法分割/レポート.py"
SPEC = importlib.util.spec_from_file_location("集中効率73が参照する固定72表示", SHARED)
PREVIOUS = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PREVIOUS
SPEC.loader.exec_module(PREVIOUS)
R69 = PREVIOUS.R69
V5, R55 = PREVIOUS.V5, PREVIOUS.R55
sha, read, table = PREVIOUS.sha, PREVIOUS.read, PREVIOUS.table
money, rate, qualification, link, shown = PREVIOUS.money, PREVIOUS.rate, PREVIOUS.qualification, PREVIOUS.link, PREVIOUS.shown
fingerprint, FORMULAS, POSITION_META = PREVIOUS.fingerprint, PREVIOUS.FORMULAS, PREVIOUS.POSITION_META
POLICIES = ("S0", "S1", "B0", "B1", "Q0", "Q1")
CONTROLS, NEW, MODEL_POLICIES = POLICIES[:2], POLICIES[2:], ("B0", "Q0")
MODEL_COUNTS = {"B0": 61, "Q0": 64}
FINGERPRINT_FIELDS = ("input_rows_sha256", "used_rows_sha256", "row_ids_sha256", "target_rows_sha256", "period_sha256", "used_barrier_rows_sha256")
PERIODS, PERIOD_NAMES, PHASES, NONFILL = PREVIOUS.PERIODS, PREVIOUS.PERIOD_NAMES, PREVIOUS.PHASES, PREVIOUS.NONFILL
EXTERNAL = ROOT / "docs/議論/外部再調査/進行の連続性と一足への集中を分ける.md"


EXTRA_META = [
    {"id": "F62", "name": "直近一足集中率", "method": "P05", "family": "price", "scale": "m03"},
    {"id": "F63", "name": "直近方向効率", "method": "P05", "family": "price", "scale": "m03"},
    {"id": "F64", "name": "最大一足の方向", "method": "P05", "family": "price", "scale": "m03"},
]
FORMULAS = [*FORMULAS,
    "C=max(abs(d_i))/TV、TV=Σabs(d_i)、5差分/6公開3分終値。方向に依らず同値",
    "E=s*Σd_i/TV。候補方向に符号を付けた効率、絶対値はERと同じ",
    "J=s*sign(max(d_i)+min(d_i))。絶対最大の正負同値は0、候補方向へ正規化"]


def qualification(value: object) -> str:
    """保存された真偽と達成判定を混同しない中立表示を返す。

    引数: value(object)はbool又はNoneの保存値。
    返り値: strは真・偽・未知。偽を一律に目標未達とは呼ばない。
    """
    return "真" if value is True else "偽" if value is False else "未知"

# ----------------------------------------

def validate_result(result: dict) -> None:
    """元学習六木と派生六木・六政策の条件運用を検査する。

    引数: result(dict)は主の小型保存結果又は人工辞書。
    返り値: None。不一致はValueError。正式値を補完しない。
    """
    if result.get("試行") != 73 or result.get("全66場既使用") is not True or set(result["候補"]) != set(POLICIES):
        raise ValueError("73の旧S対照・新B/Q六政策が必要")
    expected = {"新分類器fit": 0, "新独立計測": 0, "新保存木数": 12, "新元学習木数": 6,
        "新派生木数": 6, "参照モデル数": 3, "新運用数": 184, "参照独立測定": 4092}
    if any(type(result[key]) is not int or result[key] != value for key, value in expected.items()):
        raise ValueError("元六木・派生六木・新計測0・184運用の差")
    if result["新sklearnfit"] != 0 or type(result["新独自回帰学習"]) is not int or not 0 <= result["新独自回帰学習"] <= 24:
        raise ValueError("六元木の最大24独自回帰群の差")
    if result["対照参照"].get("候補") != list(CONTROLS) or result["対照参照"].get("元試行") != 72 or result["対照参照"].get("市場再生") is not False:
        raise ValueError("旧72S保存対照の参照差")
    learning = {"元試行": 69, "モデル政策": "C0", "同じ可知集合": all(x["追加準備除外枠"] == 0 for x in result["共通教師"].values()), "両政策共通準備集合": True, "同じ条件教師": True,
        "旧61投影同値": True, "新独自学習": True, "sklearnfit": 0, "比較": "同じ共通準備集合で直近集中C・方向効率E・最大方向Jを追加", "無取引": "回収0・障壁対象外"}
    if result["学習参照"] != learning:
        raise ValueError("共通準備集合・同69条件教師・旧61投影の参照差")
    preparation = result["準備比較"]
    previous, common = preparation["旧準備済み枠"], preparation["共通準備済み枠"]
    if type(previous) is not int or type(common) is not int or not 0 <= common <= previous <= 2442 or any(type(n) is not int or n < 0 for n in preparation["追加準備除外"].values()) or sum(preparation["追加準備除外"].values()) != previous - common:
        raise ValueError("全66場の旧準備/共通準備/追加除外復元差")
    if len(set(result["評価場"])) != 46 or len(set(result["学習専用場"])) != 20 or set(result["評価場"]) & set(result["学習専用場"]):
        raise ValueError("初20専用・評価46場の差")
    for key in ("モデル", "元学習モデル", "回収集計"):
        entries = result[key]
        if len(entries) != 6 or len({e["id"] for e in entries}) != 6 or {(e["policy"], e["phase"]) for e in entries} != {(p, h) for p in MODEL_POLICIES for h in PHASES}:
            raise ValueError("B0/Q0三phaseずつの元・派生・回収metaが必要")
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

# ----------------------------------------

def context_for() -> dict:
    """成功監査後の保存物を、旧S参考と共通準備B/Qへ分けて結合する。

    引数: なし。
    返り値: dictは純表示文脈。詳細圧縮・原板・教師個票は開かない。
    """
    names = ("結果.json", "保存物確認.json", "固定.json", "条件.json", "検証計画.md", "入力台帳.json", "一覧.resources.json")
    required = [STUDY / name for name in names]
    if any(not p.is_file() for p in required):
        raise FileNotFoundError("73主と正式保存監査の成功後だけ生成できます")
    result, proof, fixed = (read(p) for p in required[:3])
    validate_result(result)
    if result["固定SHA256"] != sha(required[2]) or proof.get("全件一致") is not True or proof.get("不一致数") != 0 or proof.get("不一致") != [] or proof["結果SHA256"] != sha(required[0]):
        raise ValueError("成功監査・結果・固定のSHA結合差")
    old, teacher = read(OLD / "結果.json"), read(SOURCE / "結果.json")
    for folder in (OLD, SOURCE):
        q = read(folder / "保存物確認.json")
        if q.get("全件一致") is not True or q.get("不一致数") != 0 or q["結果SHA256"] != sha(folder / "結果.json"):
            raise ValueError("旧対照又は教師の成功証明差")
    R69.validate_common(teacher["共通教師"])
    for policy in CONTROLS:
        if any(result[key][policy] != old[key][policy] for key in ("候補", "役割別入口")):
            raise ValueError("旧72S保存対照の集計変更")
    sources = [*required, OLD / "結果.json", OLD / "保存物確認.json", OLD / "設定と結果.md", SOURCE / "結果.json", SOURCE / "保存物確認.json", SOURCE / "設定と結果.md", SHARED, EXTERNAL]
    raw_meta = {(e["policy"], e["phase"]): e for e in result["元学習モデル"]}
    cals = {e["id"]: e for e in result["回収集計"]}
    models, raws, commons, metadata = {}, {}, {}, None
    for entry in result["モデル"]:
        raw_entry = raw_meta[entry["policy"], entry["phase"]]
        raw_path, path = ROOT / raw_entry["path"], ROOT / entry["path"]
        cal_entry = cals[entry["id"]]; cal_path = ROOT / cal_entry["path"]
        if entry["元path"] != raw_entry["path"] or entry["元SHA256"] != raw_entry["SHA256"] or any(sha(p) != e["SHA256"] for p, e in ((raw_path, raw_entry), (path, entry), (cal_path, cal_entry))):
            raise ValueError("元・派生・回収metaと指紋差")
        source, model, cal = read(raw_path), read(path), read(cal_path)
        phase = entry["phase"]
        common = common_for_training(source["training"], teacher["共通教師"][phase])
        excluded = {x["slot_id"] for x in teacher["共通教師"][phase]["使用枠"]} - {x["slot_id"] for x in common["使用枠"]}
        if set(result["共通教師"][phase]["追加準備除外ID"]) != excluded:
            raise ValueError("共通準備除外IDと保存教師IDの差")
        if phase in commons and common != commons[phase]:
            raise ValueError("B/Qの共通準備教師ID差")
        commons[phase] = common
        validate_common_summary(result["共通教師"][phase], old["共通教師"][phase], common)
        validate_fitted_model(source, None, common)
        validate_split_search(source)
        validate_model(model, cal, source, common)
        count = MODEL_COUNTS[entry["policy"]]
        if source["model_id"] != raw_entry["id"] or model["model_id"] != entry["id"] or model["source_model_sha256"] != entry["元SHA256"] or model["policy"] != entry["policy"] or entry["特徴数"] != count or raw_entry["特徴数"] != count or result["剪定"][phase][entry["policy"]] != model["pruning"]:
            raise ValueError("政策・列数・元/派生ID・剪定接続差")
        if (cal_entry["phase"], cal_entry["policy"]) != (phase, entry["policy"]):
            raise ValueError("回収metaのphase又は政策差")
        if metadata is not None and model["feature_meta"][:61] != metadata[:61]:
            raise ValueError("全六木の旧61metadata差")
        if model["feature_meta"][60] != POSITION_META or count == 64 and model["feature_meta"][61:] != EXTRA_META:
            raise ValueError("取得位置又は追加3列metadata差")
        metadata = [*model["feature_meta"][:61], *deepcopy(EXTRA_META)]
        raws[raw_entry["id"]] = {"base": source, "calibration": None, "base_path": raw_path, "path": raw_path, "entry": raw_entry, "kind": "独自元学習"}
        models[entry["id"]] = {"base": model, "calibration": cal, "base_path": path, "path": cal_path, "entry": entry, "source": source, "source_path": raw_path, "kind": "支持統合後"}
        sources.extend((raw_path, path, cal_path))
    if sum(g["fit_performed"] for item in raws.values() for g in item["base"]["training"]["partition"].values()) != result["新独自回帰学習"]:
        raise ValueError("独自回帰群の件数差")
    for phase in PHASES:
        pair = [x["base"]["training"] for x in raws.values() if x["entry"]["phase"] == phase]
        if any(set(x["base61_fingerprints"]) != set(FINGERPRINT_FIELDS) for x in pair):
            raise ValueError("旧61射影には六指紋が必要")
        if pair[0]["row_ids"] != pair[1]["row_ids"] or pair[0]["base61_fingerprints"] != pair[1]["base61_fingerprints"]:
            raise ValueError("B/Q教師ID又は旧61六指紋差")
    if metadata != read(STUDY / "条件.json")["特徴"]:
        raise ValueError("固定条件と64metadataの差")
    resources = read(required[-1])["resources"]
    if len(resources) != 276 or Counter(r["method_id"] for r in resources) != {p: 46 for p in POLICIES} or any(not (ROOT / r["pnl_path"]).is_file() for r in resources):
        raise ValueError("旧92＋新184のViewer276差")
    sources.extend([*sorted(HERE.glob("*.py")), *sorted(HERE.glob("*.md"))])
    for p in sources:
        if not p.is_file(): raise FileNotFoundError(p)
        relative = p.relative_to(ROOT).as_posix()
        if relative in fixed["ファイルSHA256"] and sha(p) != fixed["ファイルSHA256"][relative]:
            raise ValueError("固定出典変更:" + relative)
    return {"result": result, "proof": proof, "fixed": fixed, "old": old, "teacher": teacher, "common": commons,
        "models": models, "raw_models": raws, "all_models": {**raws, **models}, "metadata": metadata, "sources": list(dict.fromkeys(sources))}

# ----------------------------------------

def common_for_training(training: dict, old: dict) -> dict:
    """保存教師IDから表示用の共通集合を得て、旧可知pair内に限定する。

    引数: training(dict)は一元木の学習証拠、old(dict)は旧69共通教師の小型正本。
    返り値: dictは今回使用pairへ限定した表示文脈。特徴・教師値は再計算しない。
    """
    ids = training["row_ids"]
    if len(ids) % 2: raise ValueError("両方向pairが必要")
    used = []
    allowed = {(r["session"], r["slot_id"]) for r in old["使用枠"]}
    for first, second in zip(ids[::2], ids[1::2]):
        if first["side"] != 1 or second["side"] != -1 or (first["session"], first["slot_id"]) != (second["session"], second["slot_id"]) or (first["session"], first["slot_id"]) not in allowed:
            raise ValueError("共通知識集合の両方向pair/旧集合差")
        used.append({k: first[k] for k in first if k != "side"})
    selected = {(x["session"], x["slot_id"]) for x in used}
    if len(selected) != len(used) or used != [x for x in old["使用枠"] if (x["session"], x["slot_id"]) in selected]:
        raise ValueError("今回使用pairは旧集合の一意な同順序部分集合が必要")
    current = deepcopy(old)
    current.update(使用枠=used, 共通可知枠=len(used), 共通方向行=len(ids))
    return current


def validate_common_summary(summary: dict, inherited: dict, current: dict) -> None:
    """主の共通準備除外を旧要約と保存教師IDへ結合する。

    引数: summary/inherited/current(dict)は73要約・旧72要約・保存IDから得た共通集合。
    返り値: None。追加除外の件数/理由/IDと教師方向数の不整合は例外。
    """
    removed = inherited["共通可知枠"] - current["共通可知枠"]
    if summary["旧72共通要約"] != inherited or summary["旧共通可知枠"] != inherited["共通可知枠"] or summary["追加準備除外枠"] != removed or summary["共通可知枠"] != current["共通可知枠"] or summary["共通方向行"] != current["共通方向行"]:
        raise ValueError("共通教師の旧要約/新準備集合件数差")
    if len(set(summary["追加準備除外ID"])) != removed or len(summary["追加準備除外ID"]) != removed or sum(summary["追加準備除外理由"].values()) != removed or summary["除外枠数"] != inherited["除外枠数"] + removed:
        raise ValueError("共通準備除外理由/ID復元差")
    if summary["共通ID同順序"] is not True or summary["同じ旧61特徴"] is not True or set(summary["使用分類"]) != {"B0", "Q0"} or summary["使用分類"]["B0"] != summary["使用分類"]["Q0"] or sum(summary["使用分類"]["B0"].values()) != current["共通方向行"]:
        raise ValueError("両政策の同じ教師分類/旧61投影差")


def common_table(context: dict) -> str:
    """旧教師集合と今回の共通準備集合を、ID転記せず分離表示する。

    引数: context(dict)は旧69教師・新共通要約・元六木を持つ表示文脈。
    返り値: strは集合/除外/指紋表。教師の再生成・再評価をしない。
    """
    rows, hashes = [], []
    for phase in PHASES:
        old = context["teacher"]["共通教師"][phase]
        current = context["common"][phase]
        summary = context["result"]["共通教師"][phase]
        compact = {k:v for k,v in summary.items() if k not in ("追加準備除外ID", "旧72共通要約")}
        compact.update(追加準備除外ID_SHA256=fingerprint(summary["追加準備除外ID"]), 旧72共通要約SHA256=fingerprint(summary["旧72共通要約"]))
        rows.append([phase, old["共通可知枠"], current["共通可知枠"], current["共通方向行"], old["共通可知枠"] - current["共通可知枠"], current["評価開始"], shown(compact)])
    for identity, item in context["raw_models"].items():
        t = item["base"]["training"]
        hashes.append([identity, t["row_ids_sha256"], t["input_rows_sha256"], t["target_rows_sha256"], shown(t["base61_fingerprints"])])
    return ("## 同条件教師と共通準備集合\n\n旧69の確定条件教師を再用するが、今回6終値窓・TV正の準備不足を両方向pairごと共通除外する。旧Sと同一の集合とはしない。B/Q間は同じ準備集合・同じ条件教師で、B61列とQ64列だけが異なる。無取引0は回帰へ入り、125敗北/障壁分母へ入らない。未知は0補完しない。\n\n"
        + table(["phase", "旧69可知枠", "今回共通枠", "方向行", "共通準備追加除外", "評価開始strict前", "主保存の共通集合要約"], rows)
        + table(["元木", "共通ID指紋", "入力行指紋", "目的指紋", "旧61六指紋"], hashes)
        + "全IDと元の可知集合除外理由は旧69正本、今回の共通準備除外は主保存要約を参照し、全件をMDへ転記しない。\n\n")

# ----------------------------------------

def validate_documents(output: dict[str, str], generated: set[Path]) -> int:
    """全64特徴・版5全文と内部リンクを検査する。

    引数: output(dict[str,str])は二本文、generated(set[Path])は同時生成又は人工参照。
    返り値: intは照合したリンク数。
    """
    text = output["設定と結果.md"]
    ids = {m["id"] for m in V5.load_catalog()["methods"]}
    rows = [s for s in text.splitlines() if s.startswith("| ") and s.split("|")[1].strip() in ids]
    if len(rows) != 55 or any(len(s.split("|")) != 13 for s in rows):
        raise ValueError("55手法×9尺度不足")
    if any("| " + f"F{i:02d}" + " |" not in text for i in range(1, 65)):
        raise ValueError("旧61＋追加3の全64特徴不足")
    return sum(R55.G.check_links(s, STUDY / name, generated) for name, s in output.items())

# ----------------------------------------

def validate_fitted_model(model: dict, calibration: dict, common: dict) -> None:
    """61/64列の元学習木と派生木について、全回帰と約定支持を検査する。

    引数: model/calibration(dict|None)は同ID保存物、common(dict)は共通教師。
    返り値: None。木の走査・fit・教師再計算はしない。
    """
    structure, training = model["structure"], model["training"]
    count = MODEL_COUNTS[model["policy"]]
    if model["policy"] not in MODEL_POLICIES or len(model["feature_meta"]) != count or structure["kind"] != "fixed_direction_current_episode":
        raise ValueError("B0/Q0・61/64列・固定構造の差")
    fixed = [{"id": 0, "feature": "F01", "index": 0, "threshold": 0.0}, {"id": 1, "feature": "F26", "index": 25, "threshold": 0.5}, {"id": 2, "feature": "F20", "index": 19, "threshold": 0.5}]
    projection = {"D0": [i for i in range(count) if i not in (0, 25)], "D1": [i for i in range(count) if i not in (0, 19)]}
    if structure["fixed_nodes"] != fixed or structure["child_feature_indices"] != projection or (structure["max_depth"], structure["child_depth"], structure["child_features"]) != (4, 2, count - 2):
        raise ValueError("固定三nodeと枝別59/62列の差")
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

    引数: model/calibration(dict)はB0/Q0派生物、source(dict)は同政策の新元木、common(dict)は共通準備を通過した教師。
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
        + "training.partitionのroot/node数/fit_performedは当試行の独自元学習B0/Q0の証拠。新配置は上のpruning.partitionsだけを用いる。残存元ID昇順で新連番にし、各新nodeにsource_node_idを保存する。元学習の閾値・親の回収統計を再用し、統合時に教師再集計や子平均の平均で置き換えない。\n\n"
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
    return {"文書": reports, "内部リンク検査": links, "欠落": 0, "版": 5, "手法": 55, "尺度": 9, "全特徴": 64,
        "表示中fit": 0, "再計測_教師再生成_市場再生": False, "同byte確認": check}

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
    return ("## 元六木と支持統合後六木の全nodeと回収\n\nB61/Q64列・同じ共通準備集合と条件教師。両方同じ候補支持付き列挙を行う。固定DI/episode三node（2段）、子59/62列深さ2・全深さ4を維持する。元木の独自学習と、その後の70同規約による支持統合は別段階。1政策は各0派生木に正回収資格を追加する。\n\n"
        + table(["段階", "保存木", "政策", "phase", "全node数", "回帰目的", "過去場", "評価場"], meta)
        + table(["木", "固定群", "対応", "全方向行", "unique枠", "日", "場", "元子root", "元子node数", "元列挙実施"], parts)
        + "上の元子root/node数/列挙実施は各raw学習のtraining.partition証拠であり、派生配置はpruning.partitionsを用いる。新配置は剪定対応表を参照する。先着scoreは250/約定既知だけ、無取引0は回帰に含む。支持60枠・6日・10場も約定既知だけで、全回帰行のminleaf60とは異なる。固定trend+priceは従来技法資格を構造的に充足するが、独立証拠が増えたとはしない。\n\n"
        + table(["木", "node", "元node", "分岐・左<=右>", "左/右", "全path", "全回帰行", "filled行", "無取引行", "約定率", "条件付き先着score", "全unique/日/場", "filled unique/日/場", "filled葉支持", "path family", "技法資格"], nodes)
        + "回帰目的は無取引0込みpnl5のMSE。目的平均を先着確率とは呼ばず、方向順位は障壁score、両側資格を先に評価する固定66選択を維持する。同点・片側score未知はWAITで、0政策と正回収1政策は逆方向になり得る。\n\n"
        + table(["木", "node", "滑りpt", "回帰/障壁の状態", "全合計円", "全平均Decimal円", "filled合計円", "filled平均Decimal円", "元保存平均5円", "元保存MSE5円²", "元Decimal MSE5円²"], cash)
        + "全無取引葉は全平均0・MSE0が既知でもscoreとfilled平均はnull。空回帰葉は両平均・MSEともnull。raw欄の平均/MSEは今回の独自学習で保存した所属統計。派生欄は同じraw親の値を継承し、統合時の新学習値ではない。固定三nodeも保存所属統計で、sklearnの生予測を新しく作っていない。calのpositive=Falseは不適格であり空の平均0ではない。\n\n"
        + table(["木", "葉", "全行", "filled行", "filled unique/日/場", "約定率", "合計円0/5/10", "filled平均円0/5/10", "全平均円0/5/10", "回収支持", "主合計strict正"], calibrations))


# ----------------------------------------
def split_search_tables(context: dict) -> str:
    """元木の候補列挙数・不成立理由と選択した両子の支持を表示する。

    引数: context(dict)は元学習六木を持つ表示文脈。
    返り値: strは全探索node/停止葉の保存表。候補の再探索を行わない。
    """
    searches, selected = [], []
    for identity, item in context["raw_models"].items():
        for node in item["base"]["nodes"]:
            search = node.get("split_search")
            if search is None:
                continue
            searches.append([identity, node["id"], search["candidate_count"], search["row_eligible_count"], search["support_eligible_count"], search["selectable_count"], qualification(search["support_required"]), shown(search["stop_reason"], "停止せず分割")])
            chosen = search["selected"]
            if chosen is not None:
                gain = chosen["gain"]
                selected.append([identity, node["id"], chosen["feature_id"], shown(chosen["threshold"]), gain["numerator"] + "/" + gain["denominator"], shown(chosen["left"]), shown(chosen["right"])])
    return ("## 元学習時の分割候補と選択/停止\n\nB/Qとも同じ独自列挙器で、全行minleaf60と両子のfilled unique60枠・6日・10場を要求する。"
        "分割の目的は無取引0込みpnl5のMSE正改善。先着score・回収符号・評価成績は支持判定へ使わない。候補数は探索の数で、取引数・独立支持数ではない。\n\n"
        + table(["元木", "node", "候補数", "全行適格", "支持適格", "選択可能", "分割時支持必須", "元探索の選択/停止理由"], searches)
        + "選択閾値はfloat32特徴の候補境界。MSE改善は厳密Fractionで比較し、同値は事前固定のfeature index・閾値順。乱数を使わず、同じ候補支持付き列挙手順をB/Qに適用する。停止理由は保存文字列をそのまま示す。派生葉に残るsplit_searchはsource_node_idで対応する元学習時の候補選択の来歴であり、現在の左右分割ではない。上表は元六木だけの探索記録を示す。\n\n"
        + table(["元木", "node", "選択技法特徴", "閾値", "MSE改善・厳密分数", "左子全行/filled支持", "右子全行/filled支持"], selected))


def validate_split_search(model: dict) -> None:
    """元木の探索記録を検査し、両政策の候補支持と厳密正改善を確認する。

    引数: model(dict)はB0又はQ0の元学習木。
    返り値: None。候補の全列挙・最適性・fitは正式監査の責務とし再実行しない。
    """
    for node in model["nodes"]:
        search = node["split_search"]
        if node["id"] < 3:
            if search is not None:
                raise ValueError("固定三nodeは候補探索しない")
            continue
        keys = ("candidate_count", "row_eligible_count", "support_eligible_count", "selectable_count")
        if not isinstance(search, dict) or any(type(search[k]) is not int or search[k] < 0 for k in keys):
            raise ValueError("探索件数は既知の非負整数が必要")
        if not search["support_eligible_count"] <= search["row_eligible_count"] <= search["candidate_count"] or search["support_required"] is not True:
            raise ValueError("全行支持と約定支持を分離する")
        if search["selectable_count"] != search["support_eligible_count"]:
            raise ValueError("選択候補の共通支持制約差")
        chosen = search["selected"]
        if node["left"] == -1:
            if chosen is not None or not isinstance(search["stop_reason"], str) or not search["stop_reason"]:
                raise ValueError("停止葉は理由を保存し選択値を持たない")
            continue
        if not isinstance(chosen, dict) or search["selectable_count"] == 0 or (chosen["feature"], chosen["feature_id"], chosen["threshold"]) != (node["feature"], node["feature_id"], node["threshold"]):
            raise ValueError("分割と保存した選択候補の差")
        numerator, denominator = chosen["gain"]["numerator"], chosen["gain"]["denominator"]
        if not isinstance(numerator, str) or not isinstance(denominator, str) or int(numerator) <= 0 or int(denominator) <= 0:
            raise ValueError("正改善の分子と正分母は整数文字列で保存する")
        gain = Fraction(int(numerator), int(denominator))
        if gain <= 0:
            raise ValueError("正のMSE改善が必要")
        for side in ("left", "right"):
            child, counts = model["nodes"][node[side]], chosen[side]
            expected = {k: child[k] for k in ("direction_rows", "unique_slots", "days", "sessions")}
            expected["supported"] = child["unique_slots"] >= 60 and child["days"] >= 6 and child["sessions"] >= 10
            if counts != expected or counts["supported"] is not True:
                raise ValueError("選択した両子の約定支持記録の差")


def settings(context: dict) -> list[dict]:
    """基礎61と追加3の設定IDを分け、共通規約をS65以降へ並べる。

    引数: context(dict)は全64metadataを持つ表示文脈。
    返り値: list[dict]は版5の使用設定。3列はP05/priceの同じ価格加工で独立票にしない。
    """
    rows = deepcopy(PREVIOUS.settings(context)[:61])
    for row in rows:
        row.update(結果短記="R01/R02/R03/R04/R05/R06", 説明="旧SとB/Qの基礎61特徴。同窓準備でB/Qを比較し、旧Sとの準備集合差は分ける。")
    for meta, formula in zip(EXTRA_META, FORMULAS[61:]):
        rows.append({"設定ID": "S" + meta["id"][1:], "手法ID": ["P05"], "尺度ID": ["m03"],
            "短記": meta["id"] + " " + meta["name"], "結果短記": "R05/R06", "説明": formula + "。Qだけ追加、独立技法票ではない。"})
    extras = [(["M01", "P10"], ["m03", "m15", "m30"], "同候補支持付き列挙・同支持統合", "B61/Q64、子59/62深さ2・全深さ4、全行minleaf60、両子filled60枠6日10場。新sklearnfit0。"),
        (["M01"], ["m03", "m15", "tick"], "同66適格内score最高側", "score>=1/3・異種技法・filled/回収支持。1政策は主回収strict正。同点/未知WAIT。"),
        (["P02", "P09", "B01"], ["m03", "tick"], "同68条件発動・発動前否定", "未発動を除外せず当時気配と将来取得を分ける。"),
        (["E01", "E02", "C06"], ["tick"], "同O49・現在益122円strict正・連続保護", "損失側も非緩和、pendingでh/L/arm凍結。250TPなし。"),
        (["C07"], ["m15"], "全25/49予定枠・保守待ち50%以下", "保有継続非待ち、登録未約定を保守待ちに含める。")]
    for methods, scales, short, description in extras:
        rows.append({"設定ID": f"S{len(rows)+1:02d}", "手法ID": methods, "尺度ID": scales, "短記": short, "結果短記": "R03/R04/R05/R06", "説明": description})
    return rows


def documents(context: dict) -> dict[str, str]:
    """旧保存参考・共通準備対照・直近3列追加の違いを二本文にまとめる。

    引数: context(dict)は正式成功後又は自己完結人工の文脈。
    返り値: dict[str,str]は二本文。書込・特徴計算・教師再生成・fitはしない。
    """
    r, proof = context["result"], context["proof"]
    brief, detail = STUDY / "README.md", STUDY / "設定と結果.md"
    entrance, operations = main_tables(r)
    status = "新候補の採用なし。支持付き先着70・費用・全予定保守待ち50%以下の同時目標は未達。" if not r["採用"] else "保存採用候補：" + "、".join(r["採用"]) + "。未見利益の保証ではない。"
    intro = ("全66場既使用。初20は学習専用、学習欄は後20時系列・条件選択24・既使用後続2を分ける。\n\n" + status
        + f'\n\n旧72S0/S1保存92運用、新B0/B1/Q0/Q1各46場184運用・Viewer276。B61/Q64特徴、元6木/派生6木。独自回帰群学習{r["新独自回帰学習"]}、sklearnfit0・分類fit0・新独立計測0。\n\n'
        + "旧S→Bには直近窓の共通準備による集合差と同方式の再実装があり、純粋な特徴追加効果とは呼ばない。B→Qが同準備・同教師・同容量規約で3列を追加した比較。各1政策は各0派生木へ主回収strict正を要求し、同方向包含を断定しない。\n\n")
    mechanics = ("## 技法の役割と固定条件\n\n15分DIを方向、3分FastKを短期勢い、ATR/ADX/BBを値幅・強弱、価格端と再試験経路を場所・状態、同時刻RVOLを量の補助として組み合わせる。QのC/E/Jは同じ3分終値列のP05/price加工で、独立した三票ではない。\n\n"
        + "直近5差分は6個の完全・当場・隣接公開3分終値から計算する。番号/end隣接・公開keystrict・end<=予定時刻/key<=実判断を要求し、TV=Σ|差分|が0、欠足、未公開ならB/Qとも未準備。未知を0補完しない。準備不足も全予定枠の分母に残す。\n\n"
        + "Cは最大絶対一足/TV、Eは実方向純変位/TV、Jはs*sign(max差分+min差分)。最大正負が同じ絶対値ならJ0。高Cを自動反転、低Cや高Eを自動継続とはしない。C/Eだけでは差分の発生順序は分からない。n5や閾値の利益は原典から保証されない。\n\n"
        + "固定DI/対応episode三node（2段）、B子59/Q子62列・深さ2/全深さ4。V1はbから有効でr/k完成とは別、V0は未登録・取消・期限等の混合。float32根の零化とraw DI0の最終WAITを区別する。固定trend+priceの技法資格は構造的に充足し独立証拠の増加ではない。\n\n"
        + "両政策とも両子の全回帰行minleaf60・filled unique60枠6日10場を要求する独自MSE厳密正改善列挙と、同じ支持統合を行う。乱数不使用。無取引0は回帰に含むが125敗北/障壁分母にしない。\n\n"
        + "デイ09:15〜15:15の25枠、ナイト17:30〜05:30の49枠。66適格方向選択はscore>=1/3・葉技法/回収支持を先に評価、適格内最高側。同点/片側未知はWAIT。定時最新公開3分高安で将来Laststrict突破を要求し、発動前の反対端同値否定とT+900取消を維持。正常BBO＋有限正Last、watch後gap>300秒は品質注意。発動後1価格時計秒・後行BBO・TTL30秒も次定時未満。保有へ否定条件を追加しない。\n\n"
        + "主待ち=WAIT/全予定、保守=(WAIT＋判定不能＋登録後entryなし)/全予定、保有継続は非待ち。micro10円/pt、片道11円＋滑り5ptで主往復122円。正常返済BBOの現在費用後益strict正で利益旗/最低名目新規床。損失も連続非緩和、Dは定時ATRの5pt切上げ5..125。返済pendingでh/L/arm凍結。強制15:35/05:50、終了15:40/05:55、250TPなし・残60停止なし。名目床は費用後同値/実損回避の保証でない。\n\n")
    links = ("## 正本と再表示\n\n" + " / ".join(link(STUDY / n, brief) for n in ("設定と結果.md", "検証計画.md", "条件.json", "結果.json", "保存物確認.json", "一覧.resources.json"))
        + " / " + link(OLD / "設定と結果.md", brief, "旧72S保存参考")
        + f'\n\n[Viewer](http://127.0.0.1:8092)：276資源。監査{proof["照合項目数"]}照合・差{proof["不一致数"]}。\n\n'
        + "~~~powershell\nwork/venvs/technical-tree/Scripts/python.exe -X utf8 scripts/直近進行の集中と効率/レポート.py\nwork/venvs/technical-tree/Scripts/python.exe -X utf8 scripts/直近進行の集中と効率/レポート.py --check\n~~~\n")
    matrix = V5.matrix(V5.load_catalog(), detail, settings(context)).replace("未使用", "未使用・未検証")
    features = table(["ID", "特徴", "手法", "family", "尺度", "式", "政策"], [[m["id"], m["name"], m["method"], m["family"], m["scale"], FORMULAS[i], "旧S/B/Q" if i < 61 else "Qのみ追加"] for i,m in enumerate(context["metadata"])])
    external = ("## 外部の記述と今回の独自規約\n\n" + link(EXTERNAL, detail, "進行の連続性と一足への集中")
        + "は米株の日次/月次と先物の秒尺度を区別した着想。心理は推論であり、NK125/250・n5・費用後回収の証明ではない。Eの絶対値はKaufman ERと同じ形でも、今回の窓/符号接続/共通準備/木の分岐は独自規約。平均回帰や注意不足を価格列から直接特定しない。\n\n")
    provenance = table(["保存出典", "SHA256"], [[link(q, detail),sha(q)] for q in context["sources"]])
    preparation = "## 全予定枠の準備比較\n\n" + shown(r["準備比較"]) + "。全66場のslot被覆と各phaseの教師pair除外は分母が異なる。\n\n"
    overview = "# 00073：直近の集中と方向効率を組み合わせる\n\n" + intro + "## 条件入口先着\n\n" + entrance + "## 実一枚回収\n\n" + operations + preparation + mechanics + links
    detailed = ("# 00073：設定と結果\n\n" + intro + "R01=旧S0、R02=旧S1、R03=B0、R04=B1、R05=Q0、R06=Q1。\n\n## 手法×尺度・版5全文\n\n55手法×9尺度を全文保持。S01..64は特徴、共通規約はS65以降。複合成績を単独指標の効果としない。\n\n" + matrix
        + "## 全64特徴と政策別61/64入力\n\n" + features + preparation + common_table(context) + split_search_tables(context) + pruning_tables(context, detail) + model_tables(context, detail)
        + "## 条件入口先着\n\n" + entrance + "## 実一枚回収\n\n" + operations + detail_tables(r) + mechanics + external
        + "## 検査と限界\n\n独立一枠の合算は同時実行戦略の利益ではない。品質注意/未解消は期間確定null、観測額を保持する。全66場既使用、11月5日Day未予約未読。入力検査：" + shown(r["入力検査"]) + "。今回検査：" + shown(r["検査"]) + "。\n\n## 保存出典\n\n" + provenance + links)
    return {"README.md": overview, "設定と結果.md": detailed}


def artificial_context() -> dict:
    """固定71の架空辞書だけからB61/Q64の表示用保存物を作る。

    引数: なし。
    返り値: dictは元/派生六木と共通集合を持つ人工文脈。本物入力・fitは呼ばない。
    """
    legacy = PREVIOUS.PREVIOUS
    spec = importlib.util.spec_from_file_location("集中効率73の固定71人工辞書", legacy.HERE / "レポートの人工検査.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    old = module.artificial_context(legacy)
    r = deepcopy(old["result"])
    for key in ("候補", "役割別入口"):
        r[key] = {policy: deepcopy(old["result"][key]["G" + policy[-1]]) for policy in POLICIES}
    r["条件段階"] = {policy: deepcopy(old["result"]["条件段階"]["G" + policy[-1]]) for policy in NEW}
    r["判断理由"] = {policy: deepcopy(old["result"]["判断理由"]["G" + policy[-1]]) for policy in NEW}
    r.pop("新回帰器fit", None)
    r.update(試行=73, 新独自回帰学習=0, 新sklearnfit=0, モデル=[], 元学習モデル=[], 回収集計=[], 剪定={h:{} for h in PHASES},
        対照参照={"候補":list(CONTROLS),"元試行":72,"市場再生":False})
    r["学習参照"] = {"元試行":69,"モデル政策":"C0","同じ可知集合":True,"両政策共通準備集合":True,"同じ条件教師":True,
        "旧61投影同値":True,"新独自学習":True,"sklearnfit":0,"比較":"同じ共通準備集合で直近集中C・方向効率E・最大方向Jを追加","無取引":"回収0・障壁対象外"}
    r["準備比較"] = {"旧準備済み枠":2,"共通準備済み枠":2,"追加準備除外":{}}
    models, raws, commons = {}, {}, {}
    for phase in PHASES:
        inherited = deepcopy(old["result"]["共通教師"][phase])
        common = deepcopy(old["teacher"]["共通教師"][phase])
        for policy, count in MODEL_COUNTS.items():
            template = old["models"]["G0_" + phase]
            source = deepcopy(template["base"])
            for key in ("source_model_id", "source_model_sha256", "pruning"):
                source.pop(key, None)
            raw_id, identity = policy + "_" + phase + "_学習", policy + "_" + phase
            source.update(policy=policy, model_id=raw_id)
            source["feature_meta"] = [*deepcopy(old["metadata"][:61]), *(deepcopy(EXTRA_META) if count == 64 else [])]
            source["feature_meta_sha256"] = fingerprint(source["feature_meta"])
            projection = {"D0":[i for i in range(count) if i not in (0,25)],"D1":[i for i in range(count) if i not in (0,19)]}
            source["structure"].update(child_features=count-2, child_feature_indices=projection, feature_count=count)
            source["training"]["base61_fingerprints"] = deepcopy(source["training"]["base60_fingerprints"])
            for index, (key, group) in enumerate(source["training"]["partition"].items()):
                group.update(policy=policy, root=3+index, node_count=1, child_feature_indices=projection[key[:2]])
            for node in source["nodes"]:
                node.pop("source_node_id", None)
                node["split_search"] = None if node["id"] < 3 else {"candidate_count":0,"row_eligible_count":0,"support_eligible_count":0,"selectable_count":0,"support_required":True,"stop_reason":"支持適格候補なし","selected":None}
            common = common_for_training(source["training"], old["teacher"]["共通教師"][phase])
            model = deepcopy(source)
            model.update(model_id=identity, source_model_id=raw_id, source_model_sha256="人工元byte指紋")
            for node in model["nodes"]: node["source_node_id"] = node["id"]
            trace = deepcopy(template["base"]["pruning"])
            trace.update(source_model_id=raw_id,source_model_sha256="人工元byte指紋",source_node_count=len(source["nodes"]),new_node_count=len(model["nodes"]),
                source_to_new={str(i):i for i in range(len(model["nodes"]))},new_to_source={str(i):i for i in range(len(model["nodes"]))},decisions=[],
                partitions={key:{"source_root":g["root"],"source_node_count":1,"new_root":g["root"],"new_node_count":1} for key,g in source["training"]["partition"].items()})
            model["pruning"] = trace
            cal = deepcopy(template["calibration"]);cal.update(policy=policy,model_id=identity)
            raw_path, path = STUDY / "models" / (raw_id+".json"), STUDY / "models" / (identity+".json")
            cal_path = STUDY / "models" / ("回収_"+identity+".json")
            raw_meta = {**deepcopy(template["entry"]),"id":raw_id,"policy":policy,"特徴数":count,"path":raw_path.relative_to(ROOT).as_posix()}
            meta = {**raw_meta,"id":identity,"path":path.relative_to(ROOT).as_posix(),"元path":raw_meta["path"],"元SHA256":"人工"}
            r["元学習モデル"].append(raw_meta);r["モデル"].append(meta)
            r["回収集計"].append({"id":identity,"policy":policy,"phase":phase,"path":cal_path.relative_to(ROOT).as_posix(),"SHA256":"人工"})
            r["剪定"][phase][policy] = trace
            raws[raw_id] = {"base":source,"calibration":None,"base_path":raw_path,"path":raw_path,"entry":raw_meta,"kind":"独自元学習"}
            models[identity] = {"base":model,"calibration":cal,"base_path":path,"path":cal_path,"entry":meta,"source":source,"source_path":raw_path,"kind":"支持統合後"}
            r["新独自回帰学習"] += sum(g["fit_performed"] for g in source["training"]["partition"].values())
        commons[phase] = common
        r["共通教師"][phase] = {**inherited,"旧72共通要約":inherited,"旧共通可知枠":inherited["共通可知枠"],"共通可知枠":common["共通可知枠"],"共通方向行":common["共通方向行"],
            "追加準備除外枠":0,"追加準備除外理由":{},"追加準備除外ID":[],"使用分類":{policy:deepcopy(common["使用分類"]["C0"]) for policy in MODEL_POLICIES},"同じ旧61特徴":True}
    r["新条件入口評価"] = sum(r["候補"][policy][period]["入口"]["候補"] for policy in NEW for period in PERIODS)
    return {**old,"result":r,"models":models,"raw_models":raws,"all_models":{**raws,**models},"common":commons,"metadata":[*deepcopy(old["metadata"][:61]),*deepcopy(EXTRA_META)],"sources":[Path(__file__)]}


def self_test() -> dict:
    """架空保存物で列数・準備集合・探索来歴と純表示を検査する。

    引数: なし。
    返り値: dictは成功・テスト件数・リンク数。本物入力/fit/正式生成は0。
    """
    c = artificial_context();r=c["result"]
    validate_result(r)
    output = documents(c)
    generated = {(STUDY/name).resolve() for name in ("README.md","設定と結果.md","検証計画.md","条件.json","結果.json","保存物確認.json","一覧.resources.json")}
    generated.update(p.resolve() for item in c["all_models"].values() for p in (item["base_path"],item["path"]))
    links = validate_documents(output,generated)
    assert output == documents(c)
    text=output["設定と結果.md"]
    assert len(settings(c)) == 69 and [x["設定ID"] for x in settings(c)] == [f"S{i:02d}" for i in range(1,70)]
    assert all(x in text for x in ("S62","S63","S64","S65","共通準備","B61/Q64","元学習時の候補選択の来歴"))
    assert qualification(False)=="偽" and qualification(None)=="未知" and qualification(True)=="真"
    assert "元69の証拠" not in text and "固定三段" not in text
    for identity,item in c["models"].items():
        common=c["common"][item["entry"]["phase"]]
        validate_fitted_model(item["source"],None,common)
        validate_split_search(item["source"])
        validate_model(item["base"],item["calibration"],item["source"],common)
        assert len(item["base"]["feature_meta"])==MODEL_COUNTS[item["base"]["policy"]]
        assert identity in text
    phase=PHASES[0];sample=deepcopy(c["raw_models"]["B0_"+phase+"_学習"]["base"]["training"])
    sample["row_ids"]=sample["row_ids"][2:]
    smaller=common_for_training(sample,c["teacher"]["共通教師"][phase])
    assert smaller["共通可知枠"]==c["common"][phase]["共通可知枠"]-1
    removed = deepcopy(r)
    removed["共通教師"][phase]["追加準備除外枠"] = 1
    removed["学習参照"]["同じ可知集合"] = False
    removed["準備比較"] = {"旧準備済み枠":2,"共通準備済み枠":1,"追加準備除外":{"人工TV0":1}}
    validate_result(removed)
    try:
        bad=deepcopy(r);bad["新sklearnfit"]=1;validate_result(bad)
    except ValueError: pass
    else: raise AssertionError("sklearnfitを受理")
    return {"成功":True,"テスト件数":8,"内部リンク":links,"本物入力読取":False,"fit":0,"正式生成":False}



if __name__ == "__main__":
    main()
