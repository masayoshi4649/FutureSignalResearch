"""51の保存結果と6本のJSON木を、小型概要と詳細設定へ分けて表示する。"""

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
STUDY = ROOT / "study/00051_技法特徴の浅い分岐学習"
OLD = ROOT / "study/00050_15分定時の局所再開"
POLICIES = ("P0", "Q0", "Q1")
NEW = ("Q0", "Q1")
PERIODS = ("学習", "条件選択", "後続検査")
PERIOD_NAMES = {"学習": "時系列検査20場", "条件選択": "条件選択24場", "後続検査": "既使用後続2場"}
PHASES = {"W20": (20, 10, ("学習",)), "W30": (30, 10, ("学習",)), "F40": (40, 26, ("条件選択", "後続検査"))}
EVALUATIONS = {"P0": "R01", "Q0": "R02", "Q1": "R03"}
FORMULAS = ("s×(DI+−DI−)/100", "s×(K−50)/50", "s×ΔK/100", "ATR/125", "(OR高−OR低)/ATR",
    "s×(C−OR中央)/ATR", "s×(C−前C)/ATR", "s×(C−O)/ATR", "(H−L)/ATR", "s×CLV3・零幅0",
    "買(H−前H)/ATR・売−(L−前L)/ATR", "買(L−前L)/ATR・売−(H−前H)/ATR",
    "s×上位(C−O)/現3分ATR", "上位(H−L)/現3分ATR", "s×上位CLV・零幅0")
SPEC = importlib.util.spec_from_file_location("技法分岐帳票の固定版5", ROOT / "scripts/レポート/カタログ版5.py")
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
    if result.get("試行") != 51 or result.get("全66場既使用") is not True or set(result["候補"]) != set(POLICIES):
        raise ValueError("51の候補/既使用表示に差")
    if len(result["評価場"]) != 46 or len(set(result["評価場"])) != 46 or len(result["学習専用場"]) != 20 or set(result["評価場"]) & set(result["学習専用場"]):
        raise ValueError("学習専用20場と評価46場が不整合")
    if result["対照参照"] != {"候補": "P0", "元試行": 50, "同じ評価46場に保存値を再集計": True, "市場再生": False}:
        raise ValueError("対照は同46場の固定50P0保存再集計")
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
        raise ValueError("新Q候補だけを両期資格で採用する")


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
        if (entry["学習場"], entry["評価場"]) != expected_phases[phase] or model["parameters"]["max_depth"] != (2 if policy == "Q0" else 4):
            raise ValueError("モデルの時系列範囲/深さが不整合")
        if model["training"]["period"]["evaluation_start"] != entry["評価開始"] or model["training"]["period"]["max_input_label_end_key"][0] >= entry["評価開始"]:
            raise ValueError("学習教師が評価開始より過去でない")
        if model["feature_meta_sha256"] != fingerprint(model["feature_meta"]) or [m["id"] for m in model["feature_meta"]] != [f"F{i:02d}" for i in range(1, 16)]:
            raise ValueError("特徴metadataが不整合")
        models[identity] = {"entry": entry, "model": model, "path": path}
        model_paths.append(path)
    if set(models) != {p + "_" + phase for p in NEW for phase in PHASES}:
        raise ValueError("政策2×phase3の全6モデルが必要")
    metadata = next(iter(models.values()))["model"]["feature_meta"]
    if any(item["model"]["feature_meta"] != metadata for item in models.values()):
        raise ValueError("全木の特徴順が不一致")
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
    # 旧P0の同46場と新92場のViewerは参照だけで確認する。
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
    sources += [p for p in (study / "入力台帳.json", study / "人工確認.json", HERE / "検証.py", HERE / "特徴.py", HERE / "特徴仕様.md", HERE / "学習.py", HERE / "学習仕様.md", HERE / "保存物確認.py", HERE / "README.md", HERE / "requirements.txt") if p.is_file()]
    for path in sources:
        rel = path.relative_to(ROOT).as_posix()
        if rel in fixed["ファイルSHA256"] and sha(path) != fixed["ファイルSHA256"][rel]:
            raise ValueError("帳票が使用する固定出典の変更: " + rel)
    return {"study": study, "result": result, "proof": proof, "config": read(study / "条件.json"),
        "models": models, "metadata": metadata, "sources": list(dict.fromkeys(sources))}


def settings(context: dict) -> list[dict]:
    """15特徴の入力と実分岐、対照/モデル/運用の設定を分ける。

    引数: context(dict)は保存文脈。
    返り値: list[dict]は版5へ明示する設定。特徴単独の効果を主張しない。
    """
    output = []
    for i, meta in enumerate(context["metadata"]):
        output.append({"設定ID": f"S{i + 1:02d}", "手法ID": [meta["method"]], "尺度ID": meta["scale"].split("+"),
            "短記": meta["id"] + "=" + FORMULAS[i] + "・閾値は木表", "結果短記": "R02/R03", "適用評価": ["R02", "R03"],
            "説明": "15列の候補入力。分岐で使われた位置は下表。未分岐入力の効果は未評価"})
    extra = [(["P03", "P04", "P06", "P07", "P09", "I07", "I09"], ["m03"], ["R01"], "固定50P0同46場・新T/旧R対照", "保存値を同46場へ再集計。木の入力や学習教師へ旧採否を渡さない"),
        (["I08", "C07"], ["m15"], ["R01"], "固定50P0の上位DI背景", "新QのDIは特徴及び説明roleに使い、旧OR外ANDを新Qへ追加しない"),
        (["M01"], ["m03", "m15", "m30"], ["R02", "R03"], "浅い共通木・全6JSON/葉表", "入力尺度の表記。深さ2/4・score>=1/3・winner支持/family条件。定時15分を15分足だけの学習としない"),
        (["B01"], ["tick"], list(EVALUATIONS.values()), "全定時枠/正常BBO/+1秒TTL30", "25/49枠。保有非待ち、判定不能込み上限50%。受信時計やmicro自身の板の実測ではない"),
        (["E02"], ["tick"], list(EVALUATIONS.values()), "固定49O・現在益122円strict", "連続損失/利益追尾・名目床・非緩和・pending凍結。実要求時最新3分ATRのD固定"),
        (["E01"], ["tick"], list(EVALUATIONS.values()), "同時計B±の125/250/期限", "主分母は全仮約定、未約定別。force最初正常行inclusive・群内非重複、固定250TPなし"),
        (["C07"], ["m15"], ["R02", "R03"], "当時3/15分公開/隣接/鮮度", "30分ORは3分10本の起算帯であり、新しい30分OHLCを作らない。出典準備と値による分岐を分ける")]
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
    models, leaves, evaluation = [], [], []
    for identity, item in context["models"].items():
        m, e = item["model"], item["entry"]
        training, ready = m["training"], e["特徴準備"]
        models.append([link(item["path"], output, identity), e["phase"], m["parameters"]["max_depth"], len(e["学習場"]), len(e["評価場"]),
            ready["特徴準備枠"], ready["特徴未準備枠"], training["used_pairs"], training["excluded_pair_count"], training["period"]["max_label_end_key"], e["評価開始"]])
        for node in m["nodes"]:
            if node["left"] != -1 or node["right"] != -1:
                continue
            path = " ∧ ".join(p["feature_id"] + " " + p["comparison"] + " " + format(p["threshold"], ".17g") for p in node["path"]) or "根のみ（分岐なし）"
            leaves.append([identity, node["id"], path, node["direction_rows"], number(node["success_weight"], 1) + "/" + number(node["total_weight"], 1), rate(node["score"]),
                f"{node['unique_slots']}/{node['days']}/{node['sessions']}", qualification(node["leaf_support"]), "/".join(node["families"]), qualification(node["method_support"])])
    for row in context["result"]["葉別評価"]:
        e = row["入口"]
        evaluation.append([row["model_id"], row["phase"], row["leaf"], row["period"], e["候補"], f"{e['250']}/{e['約定']}", rate(e["率"]),
            f"{e['間引き250']}/{e['間引き約定']}", rate(e["間引き率"]), row["実完結"], number(row["実観測純額5"]), row["品質注意場"]])
    return ("## 学習6モデルと時間境界\n\n特徴未準備除外と、両方向先着の未約定/不足によるpair除外を別にする。初期20場は運用評価へ含めない。全教師の終了秒は評価開始よりstrict過去で、同秒は不可。全入力/使用ID・期間指紋と除外方向結果は各JSONへ保存した。\n\n"
        + table(["モデルJSON", "phase", "深さ", "fit場", "評価場", "特徴準備枠", "特徴未準備枠", "使用pair", "先着不明pair", "使用教師最大終了key", "評価開始秒"], models)
        + "## 全葉の学習経路・率・支持\n\n全nodeの枝/閾値はJSONを正本とし、以下に全葉の根からのpathを表示する。入力をfloat32へ写した後で左<=/右>を判定する。学習葉率は0.5重みの教師内率。葉支持は方向行数60ではなく、ユニーク枠60/6日/10場である。pathは異種family2以上かつtrend又はoscを含むことを別条件とする。\n\n"
        + table(["モデル", "葉", "全path・閾値", "方向行", "成功重み/全重み", "学習葉率", "枠/日/場", "葉支持", "path family", "技法条件"], leaves)
        + "## 全葉の対応評価\n\nこの評価はその葉から選ばれた純入口だけ。全方向scoreの校正表でも、葉へ到達した全定時枠の勝率でもない。最高側の資格・同点・DI役割WAIT等で選ばれない方向は含まない。空群も全leaf×phase内期間へ残し、率は分母0。葉ごとの間引きは全候補間引きの分割とは限らない。実額は元運用の事後帰属で、その葉だけの独立運用額ではない。品質注意場は同じモデル評価期間全体であり、葉への帰属ではない。重複する注意場を行間で足さず、実未解消も運用期間の正本を参照する。\n\n"
        + table(["モデル", "phase", "葉", "評価期間", "選択純入口", "仮250/仮約定", "主率", "仮250/非重複", "非重複率", "実完結", "実観測5円", "品質注意場"], evaluation))


def feature_table(context: dict) -> str:
    """入力15列が実際のどの分岐で使われたかを対応する。

    引数: context(dict)はモデルとmetadata。
    返り値: strは入力式/分岐位置/単独未評価の表。
    """
    locations = {i: [] for i in range(15)}
    for identity, item in context["models"].items():
        for node in item["model"]["nodes"]:
            if node["feature"] >= 0:
                locations[node["feature"]].append(identity + ":node" + str(node["id"]))
    rows = [[f"S{i + 1:02d}", m["id"], m["name"], m["method"] + "/" + m["family"], m["scale"], FORMULAS[i], "、".join(locations[i]) or "入力候補・全6木で分岐未使用", "単独未評価"]
        for i, m in enumerate(context["metadata"])]
    return "## 15特徴と実分岐の対応\n\nsは候補方向。A=現3分ATR、K=保存FastK14、ΔKは保存現前差、CLV=(2C−H−L)/(H−L)。売では高安の役割を交換するF11/F12を単なる買列の負値としない。零幅CLVの0は有効足の明示定義で欠測補完ではない。ORのm30は3分10本から作る序盤30分帯で、取引所30分OHLCを新計算したものではない。入力として渡しただけの列や、木が選んだ変換を指標単独の効果実証にしない。\n\n" + table(["設定", "特徴", "名前", "技法/family", "尺度", "式", "全分岐位置", "効果範囲"], rows)


def documents(context: dict) -> dict[str, str]:
    """同じ保存値から、小型READMEと詳細設定の文字列を作る。

    引数: context(dict)は読取文脈。
    返り値: dict[str,str]は二文書。ファイルへはまだ書かない。
    """
    study, result, proof = context["study"], context["result"], context["proof"]
    readme, detail = study / "README.md", study / "設定と結果.md"
    entry, cash = main_tables(result)
    intro = ("保存実行日時：" + result["実行日時"] + "。全66場は研究に既使用。初期20場はfit専用、運用評価は後半20場/条件選択24場/後続2場の46場である。表の『学習』は後半20場の時系列検査で、fitした40場への当てはめ成績ではない。\n\n"
        "P0は固定50を同46場へ保存再集計した対照。Q0/Q1は深さ2/4の共通木を各3回、過去教師だけでfitして対応する次期間へ適用した。\n\n"
        + ("両期の入口70・活動・品質付き費用を同時達成した新候補：" + "、".join(result["採用"]) + "。\n\n" if result["採用"] else "**両期同時適格は0/2。** 先着・支持・活動・費用の未達を下表で分ける。\n\n"))
    limits = ("## 読み方と限界\n\n"
        "- 主率は仮250/全仮約定。125・期限・不足も仮約定分母へ含め、未約定は別。実黒字率や固定250利確率ではない。非重複間引きは30分間引きではない。\n"
        "- 保有継続は非待ち。判定不能を全て待ちとする保守上限=(待ち+判定不能)/全予定枠が50%以下で活動適格。評価の全枠は740/888/74で、初期20場を加えたり欠測を除いたりしない。\n"
        "- 葉率は0.5重みの学習標本内比率で、将来確率ではない。葉別評価は選ばれた入口だけであり、全方向scoreの校正ではない。価格からの15変換を独立した心理の票と数えない。\n"
        "- 共通木の最高score側だけに1/3以上、枠60/6日/10場、path異種family2以上かつtrend又はoscを要求する。同点/最高側不適格はWAITで、次点へ救済しない。\n"
        "- 運用は固定49。定時最新3分ATRからDを固定し、現在正常返済BBOの粗益−122円>0strictで利益旗、最低名目entry床。損失側も定時外に追尾し、返済pending中の保護は凍結する。0/5/10ptは同じ実約定の費用感応。品質注意時の確定nullを観測額で埋めない。\n"
        "- 木の探索・期間設計まで含めて既使用66場の開発。未予約11/5Day両商品は使わず、未見利益や心理的因果の実証とはしない。貪欲最適分岐の別算法再学習や全tick戦略の独立実装まで監査したとは述べない。\n\n")
    links = ("## 詳細・再表示\n\n" + " / ".join(link(study / p, readme) for p in ("設定と結果.md", "検証計画.md", "条件.json", "結果.json", "保存物確認.json", "一覧.resources.json"))
        + "。保存監査は" + number(proof["照合項目数"]) + "項目・不一致0。Viewerは旧P0同46＋新92の138資源。新しい2gzipや原板を帳票で展開しない。\n\n"
        + link(HERE / "学習仕様.md", readme) + " / " + link(HERE / "特徴仕様.md", readme) + "。全6木のJSON・全葉経路・特徴使用状況・出典SHAは設定と結果へ集約。\n\n"
        "```powershell\nC:/Python314/python.exe -X utf8 scripts/技法分岐学習/レポート.py\nC:/Python314/python.exe -X utf8 scripts/技法分岐学習/レポート.py --check\n```\n\n結果と保存監査の完成後だけ表示する。fit・特徴・先着・運用を再計算しない。\n")
    brief = "# 00051：技法特徴の浅い分岐学習\n\n" + intro + "## 入口先着\n\n" + entry + "## 実運用・活動\n\n追加5ptは片道。台帳観測額は未解消新規の片道費用を含む。\n\n" + cash + limits + links
    # ----------------------------------------
    # 詳細だけへ55×9/全葉を置き、READMEへの全文重複を避ける。
    groups = settings(context)
    details = ("# 設定と結果：技法特徴の浅い分岐学習\n\n" + intro
        + "## 手法×尺度・版5\n\n55手法×9尺度。S01..15は候補入力で、実分岐と単独効果の有無は下段を参照する。R01=P0同46場対照、R02=Q0深さ2、R03=Q1深さ4。短記の式を固定の採用閾値とせず、学習した閾値は全葉表とJSONを正本にする。\n\n"
        + V5.matrix(V5.load_catalog(), detail, groups) + feature_table(context)
        + "## 共通設定\n\n" + table(["設定", "手法/尺度", "短記", "役割・限定", "複合評価"], [[g["設定ID"], "/".join(g["手法ID"]) + "・" + "/".join(g["尺度ID"]), g["短記"], g["説明"], "/".join(g["適用評価"])] for g in groups[15:]])
        + model_tables(context, detail) + "## 複合評価\n\n"
        + table(["評価", "候補", "構成", "状態"], [[EVALUATIONS[p], p, {"P0": "固定50同46場保存対照", "Q0": "深さ2共通木・3phase", "Q1": "深さ4共通木・3phase"}[p], "採用対象外の対照" if p == "P0" else "採用" if p in result["採用"] else "未達"] for p in POLICIES])
        + "## 主結果\n\n" + entry + cash + detailed_results(result)
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
        "特徴設定数": 15, "共通設定数": len(settings(context)) - 15, "保存モデル数": len(context["models"]), "葉別評価行数": len(context["result"]["葉別評価"]),
        "市場再計算": False, "学習再実行": False}


def main() -> None:
    """正式完成後の生成又は同byte確認をCLIへ公開する。

    引数: --study(Path)/--check(bool)をargparseから取得。
    返り値: None。
    """
    parser = argparse.ArgumentParser(description="51浅い共通木の保存帳票")
    parser.add_argument("--study", type=Path, default=STUDY)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    print(json.dumps(render(args.study, args.check), ensure_ascii=False))


if __name__ == "__main__":
    main()
