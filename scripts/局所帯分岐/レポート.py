"""53の局所帯準備と自由木/固定rootの保存学習を、概要と詳細へ分けて表示する。"""

import argparse
from collections import Counter
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import sys
from urllib.parse import unquote


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
STUDY = ROOT / "study/00053_局所帯の反応で先に分岐"
OLD = ROOT / "study/00052_定時判断へ価格履歴を追加"
POLICIES = ("H0", "B0", "F0")
NEW = ("B0", "F0")
FEATURE_COUNTS = {"B0": 17, "F0": 18}
PERIODS = ("学習", "条件選択", "後続検査")
PERIOD_NAMES = {"学習": "時系列検査20場", "条件選択": "条件選択24場", "後続検査": "既使用後続2場"}
PHASES = {"W20": (20, 10, ("学習",)), "W30": (30, 10, ("学習",)), "F40": (40, 26, ("条件選択", "後続検査"))}
EVALUATIONS = {"H0": "R01", "B0": "R02", "F0": "R03"}
FORMULAS = ("s×(DI+−DI−)/100", "s×(K−50)/50", "s×ΔK/100", "ATR/125", "(OR高−OR低)/ATR",
    "s×(C−OR中央)/ATR", "s×(C−前C)/ATR", "s×(C−O)/ATR", "(H−L)/ATR", "s×CLV3・零幅0",
    "買(H−前H)/ATR・売−(L−前L)/ATR", "買(L−前L)/ATR・売−(H−前H)/ATR",
    "s×上位(C−O)/現3分ATR", "上位(H−L)/現3分ATR", "s×上位CLV・零幅0",
    "参照10本の局所帯幅/ATR", "s×(C−局所帯中央)/ATR", "Z=自端の外切替後外 OR 逆端の内切替後内・0/1")
SPEC = importlib.util.spec_from_file_location("局所帯分岐帳票の固定版5", ROOT / "scripts/レポート/カタログ版5.py")
V5 = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = V5
SPEC.loader.exec_module(V5)


def sha(path: Path) -> str:
    """小型保存出典のバイト指紋を得る。

    引数: path(Path)はファイル。
    返り値: strはSHA256。市場系列や原板を開かない。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path) -> dict:
    """保存JSON正本を読む。

    引数: path(Path)は結果・モデル・条件等。
    返り値: dictは有限JSONの内容。
    """
    def invalid(value: str) -> None:
        """非標準の非有限JSONを拒否する。

        引数: value(str)は不正値。
        返り値: None。必ずValueError。
        """
        raise ValueError("非有限JSON: " + value)
    result = json.loads(path.read_text(encoding="utf-8-sig"), parse_constant=invalid)
    if not isinstance(result, dict):
        raise ValueError("JSON正本は辞書が必要")
    return result


def fingerprint(value: object) -> str:
    """JSON metadataを内容指紋にする。

    引数: value(object)はJSON安全な値。
    返り値: strはキー整列・配列順保持のSHA256。
    """
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def cell(value: object) -> str:
    """保存値を表セルに表示する。

    引数: value(object)は保存値。
    返り値: strは縦棒・改行を処理した表示。
    """
    text = json.dumps(value, ensure_ascii=False, separators=(",", ":")) if isinstance(value, (list, dict)) else str(value)
    return text.replace("|", "&#124;").replace("\r", "").replace("\n", "<br>")


def table(headers: list[str], rows: list[list]) -> str:
    """列数を検査しMarkdown表を作る。

    引数: headers(list[str])は見出し、rows(list[list])は表示値。
    返り値: strは表。
    """
    if any(len(row) != len(headers) for row in rows):
        raise ValueError("帳票列数が不一致")
    return "| " + " | ".join(headers) + " |\n| " + " | ".join("---" for _ in headers) + " |\n" + "".join("| " + " | ".join(cell(v) for v in row) + " |\n" for row in rows) + "\n"


def number(value: int | float | None, digits: int = 0) -> str:
    """未保存を0にせず数値を表示する。

    引数: value(int|float|None)は保存値、digits(int)は小数桁。
    返り値: strは数値又は対象なし。
    """
    return "対象なし" if value is None else f"{value:,.{digits}f}"


def rate(value: float | None) -> str:
    """分母0の率を未実行と区別する。

    引数: value(float|None)は保存率。
    返り値: strは百分率又は対象なし。
    """
    return "対象なし（分母0）" if value is None else f"{100 * value:.2f}%"


def qualification(value: bool) -> str:
    """保存された資格を表示する。

    引数: value(bool)は資格。
    返り値: strは充足又は未達。
    """
    if type(value) is not bool:
        raise ValueError("資格のboolが必要")
    return "充足" if value else "未達"


def confirmed(value: float | None) -> str:
    """品質nullの確定額を未実行と混同せず表示する。

    引数: value(float|None)は全体確定対象額。
    返り値: strは円又は確定不能。
    """
    return "確定不能（品質注意）" if value is None else number(value)


def link(path: Path, output: Path, label: str | None = None) -> str:
    """出力先から保存正本への相対リンクを作る。

    引数: path(Path)は参照先、output(Path)は文書、label(str|None)は表示名。
    返り値: strはMarkdownリンク。
    """
    return "[" + (label or path.name) + "](" + os.path.relpath(path, output.parent).replace("\\", "/") + ")"


def validate_result(result: dict) -> None:
    """評価範囲・支持分母・費用・活動を保存集計内で結ぶ。

    引数: result(dict)は正式結果。
    返り値: None。不整合を拒否し、先着や運用を再計算しない。
    """
    if result.get("試行") != 53 or result.get("全66場既使用") is not True or set(result["候補"]) != set(POLICIES):
        raise ValueError("53の候補/既使用表示に差")
    if len(result["評価場"]) != 46 or len(set(result["評価場"])) != 46 or len(result["学習専用場"]) != 20 or set(result["評価場"]) & set(result["学習専用場"]):
        raise ValueError("学習専用20場と評価46場が不整合")
    if result["対照参照"] != {"候補": "H0", "元試行": 52, "同じ評価46場に保存値を再集計": True, "市場再生": False}:
        raise ValueError("対照は同46場の固定52H0保存再集計")
    for period, count in zip(PERIODS, (740, 888, 74)):
        ready = result["準備比較"][period]
        if ready["全予定枠"] != count or not 0 <= ready["共通履歴準備"] <= ready["旧特徴準備"] <= count:
            raise ValueError("共通履歴準備の全枠分母差")
        if ready["旧特徴準備"] - ready["共通履歴準備"] != ready["履歴追加で未準備"] or sum(ready["追加未準備理由"].values()) != ready["履歴追加で未準備"]:
            raise ValueError("履歴追加の未準備分割差")
        if set(ready["買売Z分布"]) - {"00", "01", "10", "11"} or sum(ready["買売Z分布"].values()) != ready["共通履歴準備"]:
            raise ValueError("準備済み全枠の買売Z分布が不整合")
    for policy in POLICIES:
        for period, expected_slots in zip(PERIODS, (740, 888, 74)):
            group = result["候補"][policy][period]
            e, o = group["入口"], group["運用"]
            if sum(e["結果別"].values()) != e["候補"] or e["候補"] - e["結果別"].get("未約定", 0) != e["約定"]:
                raise ValueError("先着の全候補/仮約定分母差")
            if (e["率"] is None) != (e["約定"] == 0) or e["約定"] and not math.isclose(e["率"], e["250"] / e["約定"], abs_tol=1e-12, rel_tol=0):
                raise ValueError("先着主率の分母差")
            if o["予定枠"] != expected_slots or sum(o["判断別"].values()) != expected_slots:
                raise ValueError("評価全予定枠が不一致")
            wait, invalid = o["判断別"].get("待ち", 0), o["判断別"].get("判定不能", 0)
            if (o["待ち数"], o["判定不能"], o["活動適格"], o["全枠判定可能"]) != (wait, invalid, (wait + invalid) * 2 <= expected_slots, invalid == 0):
                raise ValueError("待ち/判定不能の活動条件差")
            if not math.isclose(o["待ち率保守上限"], (wait + invalid) / expected_slots, abs_tol=1e-12, rel_tol=0):
                raise ValueError("保守待ち率の分母差")
            for fee in (0, 5, 10):
                if o["完結観測額円"][str(fee)] != o["完結観測額円"]["0"] - 20 * fee * o["完結数"]:
                    raise ValueError("同約定費用差")
                if o["品質注意場"] and o["全体確定額円"][str(fee)] is not None:
                    raise ValueError("品質注意の全体確定null差")
            if group["同時適格"] != (e["70目標"] and o["活動適格"] and o["費用適格"]):
                raise ValueError("総合資格差")
    if result["採用"] != [p for p in NEW if all(result["候補"][p][s]["同時適格"] for s in PERIODS[:2])]:
        raise ValueError("新B0/F0候補だけを両期資格で採用する")


def context_for(study: Path) -> dict:
    """結果・監査・6モデルを同版へ結合する。

    引数: study(Path)は正式先。
    返り値: dictは小型保存値だけの文脈。市場/特徴/学習コードをimportしない。
    """
    required = [study / name for name in ("結果.json", "保存物確認.json", "固定.json", "検証計画.md", "条件.json", "一覧.resources.json")]
    for path in required:
        if not path.is_file():
            raise FileNotFoundError("正式結果と監査の完成後だけ表示可能: " + str(path))
    result, proof, fixed = read(required[0]), read(required[1]), read(required[2])
    validate_result(result)
    old = read(OLD / "結果.json")
    if result["候補"]["H0"] != old["候補"]["H0"] or result["役割別入口"]["H0"] != old["役割別入口"]["H0"] or result["評価場"] != old["評価場"]:
        raise ValueError("固定52H0の同46場保存対照差")
    if result["固定SHA256"] != sha(study / "固定.json") or proof.get("全件一致") is not True or proof.get("不一致数") != 0:
        raise ValueError("結果の固定版又は保存監査が不整合")
    models, model_paths = {}, []
    all_sessions = result["学習専用場"] + result["評価場"]
    expected_phases = {"W20": (all_sessions[:20], all_sessions[20:30]), "W30": (all_sessions[:30], all_sessions[30:40]), "F40": (all_sessions[:40], all_sessions[40:])}
    for entry in result["モデル"]:
        path = (ROOT / entry["path"]).resolve()
        if not path.is_relative_to(study) or not path.is_file() or sha(path) != entry["SHA256"]:
            raise ValueError("保存モデルのパス又はSHAが不整合")
        model = read(path)
        identity, policy, phase = entry["id"], entry["policy"], entry["phase"]
        if identity in models or policy not in NEW or phase not in PHASES or identity != policy + "_" + phase or (model["model_id"], model["policy"]) != (identity, policy):
            raise ValueError("保存モデル識別子が不整合")
        if (entry["学習場"], entry["評価場"]) != expected_phases[phase] or model["parameters"]["max_depth"] != 4:
            raise ValueError("モデルの時系列範囲/深さが不整合")
        if model["training"]["period"]["evaluation_start"] != entry["評価開始"] or model["training"]["period"]["max_input_label_end_key"][0] >= entry["評価開始"]:
            raise ValueError("学習教師が評価開始より過去でない")
        count = FEATURE_COUNTS[policy]
        if entry["特徴数"] != count or model["feature_meta_sha256"] != fingerprint(model["feature_meta"]) or [m["id"] for m in model["feature_meta"]] != [f"F{i:02d}" for i in range(1, count + 1)]:
            raise ValueError("特徴metadataが不整合")
        nodes = model["nodes"]
        if [n["id"] for n in nodes] != list(range(len(nodes))) or max(len(n["path"]) for n in nodes) > 4:
            raise ValueError("全体nodeID/深さが不整合")
        if policy == "B0":
            if model["structure"] != {"kind": "free", "max_depth": 4, "features": 17} or model["training"]["partition"] is not None or model["subtree_parameters"] is not None:
                raise ValueError("B0は17列の自由木")
        else:
            if model["structure"] != {"kind": "fixed_root", "feature": "F18", "index": 17, "threshold": 0.5, "child_depth": 3, "child_features": 17, "max_depth": 4, "root_gini_optimized": False}:
                raise ValueError("F0の固定root定義が不整合")
            if (nodes[0]["feature"], nodes[0]["threshold"]) != (17, 0.5) or any(n["feature"] >= 17 for n in nodes[1:]) or model["subtree_parameters"]["max_depth"] != 3:
                raise ValueError("F0は固定rootと17列の深さ3子木")
            parts = model["training"]["partition"]
            if set(parts) != {"0", "1"} or sum(p["direction_rows"] for p in parts.values()) != model["training"]["direction_rows"]:
                raise ValueError("Z別方向行分割差")
            for z, branch in (("0", "left"), ("1", "right")):
                p = parts[z]
                if p["root"] != nodes[0][branch] or p["fit_performed"] != (p["direction_rows"] > 0) or p["fit_parameters"] != model["subtree_parameters"]:
                    raise ValueError("Z別子木の出典差")
        for node in nodes:
            if node["data_absent"]:
                if node["left"] != -1 or node["right"] != -1 or node["direction_rows"] != 0 or node["score"] is not None or node["impurity"] is not None:
                    raise ValueError("未知枝を0点又は学習済みとして表示できない")
            elif not isinstance(node["score"], (int, float)) or not 0 <= node["score"] <= 1:
                raise ValueError("学習済みnode率が不整合")
        models[identity] = {"entry": entry, "model": model, "path": path}
        model_paths.append(path)
    if set(models) != {p + "_" + phase for p in NEW for phase in PHASES}:
        raise ValueError("政策2×phase3の全6モデルが必要")
    metadata = models["F0_W20"]["model"]["feature_meta"]
    if any(item["model"]["feature_meta"] != metadata[:FEATURE_COUNTS[item["entry"]["policy"]]] for item in models.values()):
        raise ValueError("全木の特徴順が不一致")
    for phase in PHASES:
        control, history = (models[p + "_" + phase]["model"]["training"] for p in NEW)
        for key in ("row_ids_sha256", "period_sha256", "input_pairs", "used_pairs", "excluded_pair_count", "excluded_pairs"):
            if control[key] != history[key]:
                raise ValueError("同準備B0/F0の教師pair/期間差: " + key)
    if set(result["価格SOURCE"]) != set(all_sessions) or any(type(v["足数"]) is not int or v["足数"] < 0 or not re.fullmatch(r"[0-9a-f]{64}", v["SHA256"]) for v in result["価格SOURCE"].values()):
        raise ValueError("共有価格SOURCEの66場指紋が不整合")
    # ----------------------------------------
    # 葉別評価は採用された純入口だけ。空群を含む全leaf×phase内期間を検査する。
    expected, observed = set(), set()
    for identity, item in models.items():
        for node in item["model"]["nodes"]:
            if node["left"] == -1 and node["right"] == -1:
                expected.update((identity, node["id"], period) for period in PHASES[item["entry"]["phase"]][2])
    for row in result["葉別評価"]:
        identity = row["model_id"]
        key = identity, row["leaf"], row["period"]
        if identity not in models or key in observed or key not in expected or row["policy"] != models[identity]["entry"]["policy"] or row["phase"] != models[identity]["entry"]["phase"]:
            raise ValueError("葉別評価の識別子/重複が不整合")
        if row["品質注意の範囲"] != "同じモデル評価期間全体。葉への帰属ではない":
            raise ValueError("葉別評価の品質注意は同モデル評価期間全体が必要")
        observed.add(key)
    if observed != expected:
        raise ValueError("空群を含む全leaf×期間の評価が不足")
    for policy in NEW:
        for period in PERIODS:
            selected = [r for r in result["葉別評価"] if r["policy"] == policy and r["period"] == period]
            e, o = result["候補"][policy][period]["入口"], result["候補"][policy][period]["運用"]
            for key in ("候補", "約定", "250"):
                if sum(r["入口"][key] for r in selected) != e[key]:
                    raise ValueError("葉別評価と純入口の合計差")
            if sum(r["実完結"] for r in selected) != o["完結数"] or sum(r["実観測純額5"] for r in selected) != o["完結観測額円"]["5"]:
                raise ValueError("葉別評価と実完結/観測額の合計差")
    # ----------------------------------------
    # 局面は採用方向の帰属。Z別に再運用せず、全12行と元入口/完結の合計を確認する。
    contexts, expected_contexts = result["局面別評価"], {(p, s, z) for p in NEW for s in PERIODS for z in (0, 1)}
    if len(contexts) != 12 or {(r["policy"], r["period"], r["z"]) for r in contexts} != expected_contexts:
        raise ValueError("空群を含む局面12行が必要")
    for policy in NEW:
        for period in PERIODS:
            selected = [r for r in contexts if r["policy"] == policy and r["period"] == period]
            group = result["候補"][policy][period]
            for key in ("候補", "約定", "250"):
                if sum(r["入口"][key] for r in selected) != group["入口"][key]:
                    raise ValueError("局面別と純入口の合計差")
            if sum(r["実完結"] for r in selected) != group["運用"]["完結数"] or sum(r["実観測純額5"] for r in selected) != group["運用"]["完結観測額円"]["5"]:
                raise ValueError("局面別と元運用帰属の合計差")
            if any(r["品質注意場"] != group["運用"]["品質注意場"] or r["品質注意の範囲"] != "同じ候補の期間全体。局面への帰属ではない" for r in selected):
                raise ValueError("局面の品質範囲差")
    # ----------------------------------------
    # 旧H0の同46場と新92場のViewerは参照だけで確認する。
    viewer = read(study / "一覧.resources.json")
    resources = viewer["resources"]
    if viewer.get("path_base") not in (None, "") or len(resources) != 138 or len({r["id"] for r in resources}) != 138:
        raise ValueError("Viewerはresource_root相対の138資源")
    for policy in POLICIES:
        if {r["session"] for r in resources if r["method_id"] == policy} != set(result["評価場"]):
            raise ValueError("Viewerは各候補同46場")
    for row in resources:
        path = (ROOT / row["pnl_path"]).resolve()
        if not path.is_relative_to(ROOT) or not path.is_file():
            raise ValueError("Viewer約定参照の欠落")
    sources = [*required, *model_paths, Path(__file__), V5.CATALOG, V5.MASTER, ROOT / "scripts/レポート/カタログ版5.py",
        OLD / "結果.json", OLD / "固定.json", OLD / "保存物確認.json",
        ROOT / "scripts/定時帯反応/運用.py"]
    sources += [p for p in (study / "入力台帳.json", study / "人工確認.json", HERE / "検証.py", HERE / "特徴.py", HERE / "特徴仕様.md", HERE / "学習.py", HERE / "学習仕様.md", HERE / "保存物確認.py", HERE / "README.md", HERE / "requirements.txt", ROOT / "scripts/技法分岐学習/特徴.py", ROOT / "scripts/定時履歴/学習.py", OLD / "設定と結果.md") if p.is_file()]
    for path in sources:
        rel = path.relative_to(ROOT).as_posix()
        if rel in fixed["ファイルSHA256"] and sha(path) != fixed["ファイルSHA256"][rel]:
            raise ValueError("帳票が使用する固定出典の変更: " + rel)
    return {"study": study, "result": result, "proof": proof, "config": read(study / "条件.json"),
        "models": models, "metadata": metadata, "sources": list(dict.fromkeys(sources))}


def settings(context: dict) -> list[dict]:
    """基礎15/局所3の入力と自由分岐/固定root、対照/運用の設定を分ける。

    引数: context(dict)は保存文脈。
    返り値: list[dict]は版5へ明示する設定。特徴単独の効果を主張しない。
    """
    output = []
    for i, meta in enumerate(context["metadata"]):
        applies = list(EVALUATIONS.values()) if i < 15 else ["R02", "R03"] if i < 17 else ["R03"]
        output.append({"設定ID": f"S{i + 1:02d}", "手法ID": [meta["method"]], "尺度ID": meta["scale"].split("+"),
            "短記": meta["id"] + "=" + FORMULAS[i] + "・閾値は木表", "結果短記": "/".join(applies), "適用評価": applies,
            "説明": "基礎15はH0/B0/F0。局所F16/17はB0/F0共通、F18はF0固定root。旧H0の履歴10列とは別で、入力や固定分岐を単独効果としない"})
    extra = [(["M01"], ["m03", "m15", "m30"], ["R01"], "固定52H0深さ4・同46場保存対照", "旧3木と結果を参照し、市場/fitを再実行しない。旧の準備を新局所準備へ遡及置換しない"),
        (["M01"], ["m03", "m15", "m30"], ["R02", "R03"], "B0自由17列d4/F0固定root+17列d3", "同準備/同教師pair。F18固定分岐はgini最適ではない。未知leafはscore未定で両方向WAIT"),
        (["B01"], ["tick"], list(EVALUATIONS.values()), "全定時枠/正常BBO/+1秒TTL30", "25/49枠。保有非待ち、判定不能込み上限50%。受信時計やmicro自身の板の実測ではない"),
        (["E02"], ["tick"], list(EVALUATIONS.values()), "固定49O・現在益122円strict", "連続損失/利益追尾・名目床・非緩和・pending凍結。実要求時最新3分ATRのD固定"),
        (["E01"], ["tick"], list(EVALUATIONS.values()), "同時計B±の125/250/期限", "主分母は全仮約定、未約定別。force最初正常行inclusive・群内非重複、固定250TPなし"),
        (["C07"], ["m15"], list(EVALUATIONS.values()), "当時3/15分公開/隣接/鮮度", "30分ORは3分10本の起算帯であり、新しい30分OHLCを作らない"),
        (["P03", "P10"], ["m03"], ["R02", "R03"], "固定参照10足＋反応5足の共通準備", "反応なしZ0は有効。未知は未準備。両方向Z1可。B0もF0と同じreadyへ揃える"),
        (["P06", "P03", "P09", "P10"], ["m03", "m30"], ["R01"], "旧52H0の履歴10列は保存対照のみ", "旧の自端/逆端の状態・切替数・符号・古さは旧52設定を参照。新F16..18と同一の値ではない")]
    for methods, scales, applies, short, detail in extra:
        output.append({"設定ID": f"S{len(output) + 1:02d}", "手法ID": methods, "尺度ID": scales, "短記": short,
            "結果短記": "/".join(applies), "適用評価": applies, "説明": detail})
    return output


def main_tables(result: dict) -> tuple[str, str]:
    """主要な先着と活動/費用だけを小型の表にする。

    引数: result(dict)は保存結果。
    返り値: tuple[str,str]は入口表と実運用表。
    """
    entry, cash = [], []
    for policy in POLICIES:
        for period in PERIODS:
            current = result["候補"][policy][period]
            e, o = current["入口"], current["運用"]
            entry.append([policy, PERIOD_NAMES[period], e["候補"], f"{e['250']}/{e['約定']}", rate(e["率"]), rate(e["間引き率"]), qualification(e["支持"]), qualification(e["70目標"])])
            cash.append([policy, PERIOD_NAMES[period], o["予定枠"], o["完結数"], number(o["台帳観測額円"]["5"]), confirmed(o["全体確定額円"]["5"]), rate(o["待ち率保守上限"]),
                len(o["品質注意場"]), o["未解消"], qualification(current["同時適格"])])
    return (table(["候補", "評価範囲", "純候補", "仮250/全仮約定", "主率", "非重複率", "入口支持", "70目標"], entry),
        table(["候補", "評価範囲", "全予定枠", "実完結", "台帳観測5円", "全体確定5円", "保守待ち率", "注意場", "未解消", "全条件"], cash))


def detailed_results(result: dict) -> str:
    """費用感応・判定不能・役割・回収を詳細設定へ集約する。

    引数: result(dict)は保存結果。
    返り値: strは全期間の小型表。
    """
    fees, activity, roles, protection = [], [], [], []
    for policy in POLICIES:
        for period in PERIODS:
            o = result["候補"][policy][period]["運用"]
            fees.append([policy, period, *[number(o["台帳観測額円"][str(f)]) for f in (0, 5, 10)], *[confirmed(o["全体確定額円"][str(f)]) for f in (0, 5, 10)], qualification(o["費用支持"]), qualification(o["費用適格"])])
            activity.append([policy, period, o["待ち数"], rate(o["主待ち率"]), o["判定不能"], rate(o["待ち率保守上限"]), qualification(o["活動適格"]), o["判断別"]])
            protection.append([policy, period, o["利益起動件数"], o["起動後赤字件数5"], o["実250到達件数"], o["定時外返済件数"], o["返済理由"], o["品質注意場"]])
            for role in ("順行", "反転"):
                e, actual = result["役割別入口"][policy][period][role], o["役割別完結"][role]
                roles.append([policy, period, role, e["候補"], f"{e['250']}/{e['約定']}", rate(e["率"]), qualification(e["支持"]), actual["件数"], number(actual["観測純額5"])])
    return ("## 費用・活動・役割の詳細\n\n0/5/10は同じ実約定へ追加片道ptの費用だけを加える。起動参照122円を感応ごとに変えない。未解消の新規片道費用を台帳観測へ含め、品質注意時は全体確定nullを観測額で埋めない。\n\n"
        + table(["候補", "期間", "台帳0", "台帳5", "台帳10", "確定0", "確定5", "確定10", "費用支持", "費用適格"], fees)
        + table(["候補", "期間", "待ち", "主待ち率", "判定不能", "保守上限", "活動適格", "実判断"], activity)
        + "順行/反転は当時の上位DI方向と選択sideの関係という説明ラベル。心理の正解教師ではない。DI同値は役割未確定WAIT。混合入口支持を片役割へ代用しない。\n\n"
        + table(["候補", "期間", "実役割", "純候補", "仮250/仮約定", "率", "役割支持", "実完結", "実観測5円"], roles)
        + "起動後赤字5は追加5pt費用後の実完結。現在益起動件数や仮250とは別で、実MFE250も固定250利確ではない。\n\n"
        + table(["候補", "期間", "現在益起動", "起動後赤字5", "実MFE250", "定時外返済", "返済理由", "品質注意場"], protection))


def model_tables(context: dict, output: Path) -> str:
    """全6木の全葉経路と、選ばれた純入口だけの葉別評価を表示する。

    引数: context(dict)は保存木、output(Path)は設定文書。
    返り値: strはモデル概要/全葉学習表/葉別評価。閾値は17桁で保存精度を示す。
    """
    models, leaves, evaluation, partitions = [], [], [], []
    for identity, item in context["models"].items():
        m, e = item["model"], item["entry"]
        training, ready = m["training"], e["特徴準備"]
        models.append([link(item["path"], output, identity), e["phase"], "自由d4" if m["policy"] == "B0" else "F18固定root＋17列d3", e["特徴数"], len(e["学習場"]), len(e["評価場"]),
            ready["特徴準備枠"], ready["特徴未準備枠"], training["used_pairs"], training["excluded_pair_count"], training["period"]["max_label_end_key"], e["評価開始"]])
        if training["partition"] is not None:
            for z, p in training["partition"].items():
                partitions.append([identity, z, p["root"], p["node_count"], p["direction_rows"],
                    f"{p['pair_unique']}/{p['days']}/{p['sessions']}", "fit済み" if p["fit_performed"] else "空枝・未学習", p["row_ids_sha256"]])
        for node in m["nodes"]:
            if node["left"] != -1 or node["right"] != -1:
                continue
            path = " ∧ ".join(p["feature_id"] + ("（固定）" if m["policy"] == "F0" and p["node"] == 0 else "") + " " + p["comparison"] + " " + format(p["threshold"], ".17g") for p in node["path"]) or "根のみ（分岐なし）"
            leaves.append([identity, node["id"], path, "未学習" if node["data_absent"] else "学習済み", node["direction_rows"], number(node["success_weight"], 1) + "/" + number(node["total_weight"], 1), "未学習（score未定）" if node["data_absent"] else rate(node["score"]),
                f"{node['unique_slots']}/{node['days']}/{node['sessions']}", qualification(node["leaf_support"]), "/".join(node["families"]), qualification(node["method_support"])])
    for row in context["result"]["葉別評価"]:
        e = row["入口"]
        evaluation.append([row["model_id"], row["phase"], row["leaf"], row["period"], e["候補"], f"{e['250']}/{e['約定']}", rate(e["率"]),
            f"{e['間引き250']}/{e['間引き約定']}", rate(e["間引き率"]), row["実完結"], number(row["実観測純額5"]), row["品質注意場"]])
    return ("## 学習6モデルと時間境界\n\n特徴未準備除外と、両方向先着の未約定/不足によるpair除外を別にする。初期20場は運用評価へ含めない。全教師の終了秒は評価開始よりstrict過去で、同秒は不可。全入力/使用ID・期間指紋と除外方向結果は各JSONへ保存した。\n\n"
        + table(["モデルJSON", "phase", "構造/深さ", "特徴数", "fit場", "評価場", "共通準備枠", "特徴未準備枠", "使用pair", "先着不明pair", "使用教師最大終了key", "評価開始秒"], models)
        + "### F0の固定rootとZ別教師\n\n全pairの検査・未約定/不足pair除外の後に方向行をZで分ける。枝内で両方向を要求しない。同じ枠が両枝へ入る場合があるため枝のユニーク枠は非加算。固定rootはF18<=0.5/ >0.5、各子は先頭17列だけで深さ3。強制partitionをgini最適分割と呼ばず、全体gini/支持は使用教師から再計数した。空枝はfitせず、0点補完しない。\n\n"
        + table(["モデル", "Z", "全体子root", "node数", "方向行", "枠/日/場", "子fit", "使用方向ID指紋"], partitions)
        + "## 全葉の学習経路・率・支持\n\n全nodeの枝/閾値はJSONを正本とし、以下に全葉の根からのpathを表示する。入力をfloat32へ写した後で左<=/右>を判定する。学習葉率は0.5重みの教師内率。葉支持は方向行数60ではなく、ユニーク枠60/6日/10場である。pathは異種family2以上かつtrend又はoscを含むことを別条件とする。\n\n"
        + "未知leafのscore=nullは成功率0%ではない。どちらか方向が未知leafに到達すれば既知側を含め未学習枝WAITとし、低い側へ救済しない。F18固定rootはprice familyに数えるが、それだけでは技法条件を満たさない。\n\n"
        + table(["モデル", "葉", "全path・閾値", "状態", "方向行", "成功重み/全重み", "学習葉率", "枠/日/場", "葉支持", "path family", "技法条件"], leaves)
        + "## 全葉の対応評価\n\nこの評価はその葉から選ばれた純入口だけ。全方向scoreの校正表でも、葉へ到達した全定時枠の勝率でもない。最高側の資格・同点・DI役割WAIT等で選ばれない方向は含まない。空群も全leaf×phase内期間へ残し、率は分母0。葉ごとの間引きは全候補間引きの分割とは限らない。実額は元運用の事後帰属で、その葉だけの独立運用額ではない。品質注意場は同じモデル評価期間全体であり、葉への帰属ではない。重複する注意場を行間で足さず、実未解消も運用期間の正本を参照する。\n\n"
        + table(["モデル", "phase", "葉", "評価期間", "選択純入口", "仮250/仮約定", "主率", "仮250/非重複", "非重複率", "実完結", "実観測5円", "品質注意場"], evaluation))


def feature_table(context: dict) -> str:
    """入力18列がどの学習分岐又は固定rootへ使われたかを対応する。

    引数: context(dict)はモデルとmetadata。
    返り値: strは入力式/分岐位置/単独未評価の表。
    """
    locations = {i: [] for i in range(18)}
    for identity, item in context["models"].items():
        for node in item["model"]["nodes"]:
            if node["feature"] >= 0:
                locations[node["feature"]].append(identity + (":固定root" if item["model"]["policy"] == "F0" and node["id"] == 0 else ":学習node" + str(node["id"])))
    rows = [[f"S{i + 1:02d}", m["id"], m["name"], m["method"] + "/" + m["family"], m["scale"], FORMULAS[i], "、".join(locations[i]) or "入力候補・全6木で分岐未使用", "単独未評価"]
        for i, m in enumerate(context["metadata"])]
    return "## 基礎15・局所3と新6木の分岐\n\n基礎15列は旧51の式を保持する。sは候補方向、A=現3分ATR、K=保存FastK14、ΔKは保存現前差。売ではF11/F12の高安役割を交換する。CLV零幅0は明示定義で欠測補完ではない。ORのm30は3分10本の序盤帯で、新しい30分OHLCではない。\n\n局所参照はj−14..j−5の10本で帯を固定し、j−4..jの5終値だけで反応を数える。参照末は内state−1を種とし、端方向qに対してq×(C−端)>=5で外、<=−5で内、中間帯は保持。Zは自方向端が一度外切替後いま外、又は反対端が一度内切替後いま内、のBoolean OR。両方向Z1も可能、Z0は未知ではない。新3列は全てprice family。\n\nF16/17はB0/F0の学習候補、F18はF0の事前固定rootで学習選択された列ではない。分岐位置は新6木だけ。旧H0の履歴10列と全pathは旧52の設定表を参照する。入力・未分岐・固定分岐のどれも単独の効果実証にしない。\n\n" + table(["設定", "特徴", "名前", "技法/family", "尺度", "式", "新6木の分岐位置", "効果範囲"], rows)


def readiness_table(result: dict) -> str:
    """旧特徴準備と局所帯準備、全ready枠の買売Z分布を表示する。

    引数: result(dict)は準備比較正本。
    返り値: strは期間別の準備表。履歴の未発生を除外としない。
    """
    rows, distribution = [], []
    for period in PERIODS:
        r = result["準備比較"][period]
        rows.append([PERIOD_NAMES[period], r["全予定枠"], r["旧特徴準備"], r["共通履歴準備"], r["履歴追加で未準備"], r["追加未準備理由"]])
        distribution.append([PERIOD_NAMES[period], r["共通履歴準備"], *[r["買売Z分布"].get(z, 0) for z in ("00", "01", "10", "11")]])
    return (table(["範囲", "全枠", "旧15列準備", "B0/F0共通準備", "追加未準備", "追加理由"], rows)
        + "買売Z分布は全ready枠を分母とし、文字列は買Z・売Zの順。採用方向だけの局面表とは異なる。\n\n"
        + table(["範囲", "全ready枠", "00", "01", "10", "11"], distribution))


def context_table(result: dict) -> str:
    """採用方向Zの12群へ帰属した入口と完結損益を表示する。

    引数: result(dict)は局面別評価を含む結果。
    返り値: strは空群を含む12行。局面別の再運用額とは呼ばない。
    """
    rows = []
    for r in result["局面別評価"]:
        e = r["入口"]
        rows.append([r["policy"], r["period"], r["z"], e["候補"], e["結果別"].get("未約定", 0),
            f"{e['250']}/{e['約定']}", rate(e["率"]), f"{e['間引き250']}/{e['間引き約定']}", rate(e["間引き率"]),
            r["実完結"], number(r["実観測純額5"]), r["品質注意場"]])
    return ("## 採用方向の局面別評価\n\n新2候補×3期間×Z0/1の12行で、採用方向のZに純入口と元運用の実完結を帰属する。準備済み全枠・全方向の校正表ではない。Zで絞って戦略を再運用した損益でもない。群別非重複間引きは群内の診断で、行間で足して全体間引きへ照合しない。品質注意場は同じ候補/期間全体で、局面への帰属ではなく、重複加算しない。未解消は元運用正本を参照する。\n\n"
        + table(["候補", "期間", "採用Z", "純入口", "未約定", "仮250/全仮約定", "主率", "仮250/非重複", "非重複率", "実完結", "実観測5円", "期間品質注意場"], rows))


def documents(context: dict) -> dict[str, str]:
    """同じ保存値から、小型READMEと詳細設定の文字列を作る。

    引数: context(dict)は読取文脈。
    返り値: dict[str,str]は二文書。ファイルへはまだ書かない。
    """
    study, result, proof = context["study"], context["result"], context["proof"]
    readme, detail = study / "README.md", study / "設定と結果.md"
    entry, cash = main_tables(result)
    classifier_fits = sum(1 if item["model"]["policy"] == "B0" else sum(p["fit_performed"] for p in item["model"]["training"]["partition"].values()) for item in context["models"].values())
    intro = ("保存実行日時：" + result["実行日時"] + "。全66場は研究に既使用。初期20場はfit専用、運用評価は後半20場/条件選択24場/後続2場の46場である。表の『学習』は後半20場の時系列検査で、fitした40場への当てはめ成績ではない。\n\n"
        "H0は固定52の基礎15＋履歴10列・深さ4を同46場へ保存再集計した対照。B0は新しい局所帯準備の基礎15＋幅/距離2列で深さ4の自由木。F0は同じ準備/教師の17列にZを加え、根をZで事前固定し、各子は17列・深さ3を過去教師だけで学習した。保存モデルは合成木を含む6本で、分類器の実fit回数は" + str(classifier_fits) + "回。\n\n"
        + ("両期の入口70・活動・品質付き費用を同時達成した新候補：" + "、".join(result["採用"]) + "。\n\n" if result["採用"] else "**両期同時適格は0/2。** 先着・支持・活動・費用の未達を下表で分ける。\n\n"))
    limits = ("## 読み方と限界\n\n"
        "- 主率は仮250/全仮約定。125・期限・不足も仮約定分母へ含め、未約定は別。実黒字率や固定250利確率ではない。非重複間引きは30分間引きではない。\n"
        "- 保有継続は非待ち。判定不能を全て待ちとする保守上限=(待ち+判定不能)/全予定枠が50%以下で活動適格。評価の全枠は740/888/74で、初期20場を加えたり欠測を除いたりしない。\n"
        "- 葉率は0.5重みの学習標本内比率で、将来確率ではない。葉別評価は選ばれた入口だけであり、全方向scoreの校正ではない。基礎・価格履歴を独立した心理の票と数えない。\n"
        "- H0→B0は準備/入力と再fitを含む方針差。B0→F0は同ready/同教師pairに対してZの固定根と子探索を変える比較で、Z単独の因果効果ではない。F18固定rootはgini最適分岐でなく、空枝はscore未定。片側でも未知leaf到達なら両方向WAITで、0点補完や救済をしない。\n"
        "- 共通木の最高score側だけに1/3以上、枠60/6日/10場、path異種family2以上かつtrend又はoscを要求する。同点/最高側不適格はWAITで、次点へ救済しない。\n"
        "- 運用は固定49。定時最新3分ATRからDを固定し、現在正常返済BBOの粗益−122円>0strictで利益旗、最低名目entry床。損失側も定時外に追尾し、返済pending中の保護は凍結する。0/5/10ptは同じ実約定の費用感応。品質注意時の確定nullを観測額で埋めない。\n"
        "- 木の探索・期間設計まで含めて既使用66場の開発。未予約11/5Day両商品は使わず、未見利益や心理的因果の実証とはしない。貪欲最適分岐の別算法再学習や全tick戦略の独立実装まで監査したとは述べない。\n\n")
    links = ("## 詳細・再表示\n\n" + " / ".join(link(study / p, readme) for p in ("設定と結果.md", "検証計画.md", "条件.json", "結果.json", "保存物確認.json", "一覧.resources.json"))
        + "。保存監査は" + number(proof["照合項目数"]) + "項目・不一致0。Viewerは旧H0同46＋新92の138資源。新しい2gzipや原板を帳票で展開しない。\n\n"
        + link(HERE / "学習仕様.md", readme) + " / " + link(HERE / "特徴仕様.md", readme) + " / " + link(OLD / "設定と結果.md", readme, "旧H0の分岐と評価") + "。新6保存モデル（合成木含む）のJSON・全葉経路・局面12行・特徴使用状況・出典SHAは設定と結果へ集約。\n\n"
        "```powershell\nC:/Python314/python.exe -X utf8 scripts/局所帯分岐/レポート.py\nC:/Python314/python.exe -X utf8 scripts/局所帯分岐/レポート.py --check\n```\n\n結果と保存監査の完成後だけ表示する。fit・特徴・先着・運用を再計算しない。\n")
    brief = "# 00053：局所帯の反応で先に分岐\n\n" + intro + "## 共通準備\n\n" + readiness_table(result) + "## 入口先着\n\n" + entry + "## 実運用・活動\n\n追加5ptは片道。台帳観測額は未解消新規の片道費用を含む。\n\n" + cash + limits + links
    # ----------------------------------------
    # 詳細だけへ55×9/全葉を置き、READMEへの全文重複を避ける。
    groups = settings(context)
    details = ("# 設定と結果：局所帯の反応で先に分岐\n\n" + intro
        + "## 手法×尺度・版5\n\n55手法×9尺度。S01..15は基礎入力、S16/17は新B0/F0共通の局所幅/距離、S18はF0固定rootのZ。R01=固定52H0同46場対照、R02=B0自由17列d4、R03=F0固定root＋17列d3子木。旧H0の履歴10列は新F16..18と別で旧52設定を参照。短記の式を学習済み閾値とせず、固定root0.5と学習した子の閾値は全葉表で分ける。\n\n"
        + V5.matrix(V5.load_catalog(), detail, groups) + feature_table(context)
        + "## 共通設定\n\n" + table(["設定", "手法/尺度", "短記", "役割・限定", "複合評価"], [[g["設定ID"], "/".join(g["手法ID"]) + "・" + "/".join(g["尺度ID"]), g["短記"], g["説明"], "/".join(g["適用評価"])] for g in groups[18:]])
        + "## 準備差と同教師の比較\n\n" + readiness_table(result)
        + "B0/F0は全phaseで使用pair ID・期間・除外pairが一致する。旧H0の準備を遡及変更しない。共有3分価格SOURCEは66場の足数/内容SHAだけを結果JSONで参照し、指標銀行や原板を再計算・転記しない。\n\n"
        + model_tables(context, detail) + "## 複合評価\n\n"
        + table(["評価", "候補", "構成", "状態"], [[EVALUATIONS[p], p, {"H0": "固定52同46場・25列深さ4保存対照", "B0": "同準備・17列自由木深さ4・3phase", "F0": "同準備/同pair・F18固定root＋17列深さ3子木・3phase"}[p], "採用対象外の対照" if p == "H0" else "採用" if p in result["採用"] else "未達"] for p in POLICIES])
        + "## 主結果\n\n" + entry + cash + detailed_results(result) + context_table(result)
        + "## 判断理由\n\n" + table(["候補", "期間", "保存理由別枠数"], [[p, s, result["判断理由"][p][s]] for p in NEW for s in PERIODS])
        + "## 全固定条件\n\n" + table(["項目", "値"], [[k, v] for k, v in context["config"].items()]) + limits
        + "## 保存出典\n\n" + table(["出典", "SHA256"], [[link(p, detail), "`" + sha(p) + "`"] for p in context["sources"]])
        + "## 再表示\n\n" + link(readme, detail, "概要・再表示CLI") + "。詳細値は保存結果・モデルJSONを参照し、帳票から本物fitや市場運用を起動しない。\n")
    return {"README.md": brief.rstrip() + "\n", "設定と結果.md": details.rstrip() + "\n"}


def check_links(text: str, output: Path, generated: set[Path]) -> int:
    """生成文書のローカルリンクの存在を検査する。

    引数: text(str)は本文、output(Path)は出力先、generated(set[Path])は同時生成二MD。
    返り値: intはローカルリンク数。外部サイトへ接続しない。
    """
    count = 0
    for target in re.findall(r"\]\(([^)]+)\)", text):
        if target.startswith(("http:", "https:", "#", "mailto:")):
            continue
        count += 1
        path = (output.parent / unquote(target.split("#", 1)[0])).resolve()
        if path not in generated and not path.exists():
            raise FileNotFoundError("帳票リンク欠落: " + target)
    return count


def render(study: Path = STUDY, check: bool = False) -> dict:
    """保存結果を二MDへ表示するか、保存版との同byteだけを検査する。

    引数: study(Path)は正式先、check(bool)は書込なし照合か。
    返り値: dictはbytes/SHAと表・リンク件数。市場/学習再計算はしない。
    """
    study = study.resolve()
    context = context_for(study)
    output = documents(context)
    generated, report, links = {(study / name).resolve() for name in output}, {}, 0
    for name, text in output.items():
        path, data = study / name, text.encode("utf-8")
        links += check_links(text, path, generated)
        if check:
            if not path.is_file() or path.read_bytes() != data:
                raise ValueError("保存帳票と再表示が不一致: " + name)
        else:
            path.write_bytes(data)
        report[name] = {"bytes": len(data), "SHA256": hashlib.sha256(data).hexdigest()}
    return {"文書": report, "リンク検査件数": links, "欠落リンク": [], "カタログ手法数": 55, "尺度数": 9,
        "特徴設定数": 18, "政策特徴数": FEATURE_COUNTS, "共通設定数": len(settings(context)) - 18, "保存モデル数": len(context["models"]),
        "分類器fit回数": sum(1 if item["model"]["policy"] == "B0" else sum(p["fit_performed"] for p in item["model"]["training"]["partition"].values()) for item in context["models"].values()),
        "葉別評価行数": len(context["result"]["葉別評価"]), "局面別評価行数": len(context["result"]["局面別評価"]),
        "市場再計算": False, "学習再実行": False}


def main() -> None:
    """正式完成後の生成又は同byte確認をCLIへ公開する。

    引数: --study(Path)/--check(bool)をargparseから取得。
    返り値: None。
    """
    parser = argparse.ArgumentParser(description="53局所帯分岐の保存帳票")
    parser.add_argument("--study", type=Path, default=STUDY)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    print(json.dumps(render(args.study, args.check), ensure_ascii=False))


if __name__ == "__main__":
    main()
