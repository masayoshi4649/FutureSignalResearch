"""66の保存済み方向選択を、旧65参照木のまま再計算せず表示する。"""

import argparse
from collections import Counter
from copy import deepcopy
import importlib.util
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
STUDY = ROOT / "study/00066_複数手法の適格方向から優先側を選ぶ"
OLD = ROOT / "study/00065_方向に対応する現在の有効状態を先に分ける"
SHARED = ROOT / "scripts/現在状態と量価格/レポート.py"
SPEC = importlib.util.spec_from_file_location("適格選択66の固定65表示純補助", SHARED)
BASE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = BASE
SPEC.loader.exec_module(BASE)
R64, R56, R55, V5 = BASE.R64, BASE.R56, BASE.R55, BASE.V5
POLICIES, NEW = ("U0", "U1", "E0", "E1"), ("E0", "E1")
PERIODS, PERIOD_NAMES, PHASES = BASE.PERIODS, BASE.PERIOD_NAMES, BASE.PHASES
sha, read, fingerprint, table = BASE.sha, BASE.read, BASE.fingerprint, BASE.table
number, rate, qualification, link, money = BASE.number, BASE.rate, BASE.qualification, BASE.link, BASE.money
FORMULAS = BASE.FORMULAS
REFERENCE = {"元試行": 65, "新fit": False, "教師再生成": False, "特徴再計算": False, "モデル同一": True, "回収集計同一": True}
EXTERNAL = ROOT / "docs/議論/外部再調査/候補の成立と方向の優先順位を分ける.md"

# ----------------------------------------
# 表示と分母の共通算術だけを固定版から再用する。
def main_tables(result: dict) -> tuple[str, str]:
    """四候補の入口と一建玉の実運用を別表にする。

    引数: result(dict)は保存結果。
    返り値: tuple[str,str]は先着表と運用表。
    """
    entrance, cash = [], []
    for p in POLICIES:
        for t in PERIODS:
            e, o = result["候補"][p][t]["入口"], result["候補"][p][t]["運用"]
            entrance.append([p, PERIOD_NAMES[t], e["候補"], f'{e["250"]}/{e["約定"]}', rate(e["率"]),
                             f'{e["間引き250"]}/{e["間引き約定"]}', rate(e["間引き率"]), f'{e["日数"]}日/{e["場数"]}場',
                             qualification(e["支持"]), qualification(e["70目標"])])
            cash.append([p, PERIOD_NAMES[t], o["完結数"], money(o["完結観測額円"]["5"]), money(o["全体確定額円"]["5"]),
                         len(o["品質注意場"]), rate(o["主待ち率"]), rate(o["待ち率保守上限"]), qualification(o["活動適格"]),
                         f'{o["利益起動件数"]}/{o["起動後赤字件数5"]}', qualification(o["費用適格"]), qualification(result["候補"][p][t]["同時適格"])])
    return (table(["候補", "期間", "純採用", "250/仮約定", "主率", "非重複250/約定", "非重複率", "日/場", "入口支持", "70目標"], entrance),
            table(["候補", "期間", "実完結", "観測5円", "全体確定5円", "品質注意場数", "待ち", "保守上限", "活動", "利益旗/旗後赤字", "費用", "同時適格"], cash))

def detail_tables(result: dict) -> str:
    """費用感応・品質・DI役割・保存理由を表示する。

    引数: result(dict)は66結果。
    返り値: strは全四候補の詳細表。
    """
    costs, roles, reasons = [], [], []
    for p in POLICIES:
        for t in PERIODS:
            o = result["候補"][p][t]["運用"]
            costs.append([p, t, o["完結数"], *(money(o["完結観測額円"][str(f)]) for f in (0, 5, 10)),
                          *(money(o["全体確定額円"][str(f)]) for f in (0, 5, 10)), o["未解消"], o["品質注意場"]])
            for role in ("順行", "反転"):
                e, actual = result["役割別入口"][p][t][role], o["役割別完結"][role]
                roles.append([p, t, role, e["候補"], f'{e["250"]}/{e["約定"]}', rate(e["率"]), qualification(e["支持"]), actual["件数"], money(actual["観測純額5"])])
            if p in NEW:
                reasons.extend([p, t, why, n] for why, n in sorted(result["判断理由"][p][t].items()))
    return ("## 同約定の費用・品質\n\n品質注意時の期間全体確定はnull、観測額は別に残す。\n\n"
            + table(["候補", "期間", "完結", "観測0", "観測5", "観測10", "確定0", "確定5", "確定10", "未解消", "品質注意場"], costs)
            + "## DI役割別の入口と実完結\n\nDI同方向=順行、逆方向=反転という保存分類。転換の時系列確認や心理の直測ではない。役割別額も候補期間全体の品質に従う。\n\n"
            + table(["候補", "期間", "役割", "純採用", "250/仮約定", "主率", "入口支持", "実完結", "観測5円"], roles)
            + "## 新候補の保存判断理由\n\n同点・片側未知の旧WAITを保持した後、両側資格を先に検査し、適格な方向の中から障壁score最高側を選ぶ。他方向採用はその側自身の資格が必要。純採否と実待ちは異なる。\n\n"
            + table(["候補", "期間", "保存理由", "枠数"], reasons)
            + "## 再利用した独立測定の状態\n\n新たな独立計測は0。未準備・未約定・品質注意・未解消を確定0円へ写さない。\n\n"
            + table(["用途区間", "状態", "方向行数"], [[x["区間"], x["状態"], x["方向行数"]] for x in result["独立測定"]]))

def validate_documents(output: dict[str, str], generated: set[Path]) -> int:
    """版5全55×9、60特徴、内部リンクを検査する。

    引数: output(dict[str,str])は二つの本文、generated(set[Path])は同時生成又は人工仮想参照。
    返り値: intはリンク確認数。
    """
    text = output["設定と結果.md"]
    ids = {m["id"] for m in V5.load_catalog()["methods"]}
    rows = [r for r in text.splitlines() if r.startswith("| ") and r.split("|")[1].strip() in ids]
    if len(rows) != 55 or any(len(r.split("|")) != 13 for r in rows):
        raise ValueError("版5の55×9が不足")
    if any("| " + f"F{i:02d}" + " |" not in text for i in range(1, 61)):
        raise ValueError("60特徴の表示漏れ")
    return sum(R55.G.check_links(value, STUDY / name, generated) for name, value in output.items())

def render(check: bool = False) -> dict:
    """正式結果から2MDを一度生成するか同byteだけを検査する。

    引数: check(bool)は書込なしの一致検査。
    返り値: dictはSHA・リンク・表検査。fitや市場運用を呼ばない。
    """
    output = documents(context_for())
    count = validate_documents(output, {(STUDY / n).resolve() for n in output})
    reports = {}
    for name, text in output.items():
        path, content = STUDY / name, text.encode("utf-8")
        if check:
            if path.read_bytes() != content:
                raise ValueError("保存MDと同byteでない:" + name)
        else:
            path.write_bytes(content)
        reports[name] = {"SHA256": sha(path), "bytes": len(content)}
    return {"文書": reports, "内部リンク検査": count, "欠落": 0, "版": 5, "手法": 55, "尺度": 9,
            "表示中fit": 0, "再計測_再集計_市場再生": False, "同byte確認": check}


# ----------------------------------------
# 新しい木を要求せず、旧65の同じ木と回収の版を検査する。


def validate_result(result: dict) -> None:
    """新fitなしの来歴と、新旧四候補の分母・品質を検査する。

    引数: result(dict)は66の小型保存結果。
    返り値: None。未知回収や無取引の先着率を0補完しない。
    """
    if result.get("試行") != 66 or set(result["候補"]) != set(POLICIES):
        raise ValueError("66の旧U・新E四候補が必要")
    if (result["新回帰器fit"], result["新分類器fit"], result["新独立計測"], result["新運用数"],
            result["新保存木数"], result["参照モデル数"]) != (0, 0, 0, 92, 0, 3):
        raise ValueError("新fit・新木0、旧参照3・新運用92の契約差")
    if result["学習参照"] != REFERENCE:
        raise ValueError("旧65の木・回収・教師・特徴を変更しない")
    if result["対照参照"] != {"候補": ["U0", "U1"], "元試行": 65, "同じ評価46場": True, "市場再生": False}:
        raise ValueError("旧U0/U1は固定65の保存対照")
    # ----------------------------------------
    # 共通の数値・分母検査だけを旧65表示器へ射影する。来歴は上で別確認済み。
    projected = deepcopy(result)
    mapping = {"U0": "Q0", "U1": "Q1", "E0": "U0", "E1": "U1"}
    projected.update(試行=65, 検査=result["旧証明検査"],
        対照参照={"候補": ["Q0", "Q1"], "元試行": 64, "同じ評価46場": True, "市場再生": False})
    for key in ("候補", "役割別入口"):
        projected[key] = {mapping[p]: row for p, row in result[key].items()}
    projected["判断理由"] = {mapping[p]: result["判断理由"][p] for p in NEW}
    projected["採用"] = [mapping[p] for p in result["採用"]]
    BASE.validate_result(projected)
    if result["検査"]["旧65特徴保存一致"] != 3404 or result["検査"]["旧65純判断一致"] != 3404:
        raise ValueError("旧65全60・旧純判断3404方向の一致が必要")
    R64.validate_quantity_distribution(result["数量分布"], result["価格経路分布"])
    validate_selection(result)


def validate_selection(result: dict) -> None:
    """新旧純候補とE0/E1方向差の保存件数を復元する。

    引数: result(dict)は主の選択比較と候補集計。
    返り値: None。純候補包含を実運用包含へ拡張しない。
    """
    if set(result["選択比較"]) != set(NEW) or set(result["新候補方向差"]) != set(PERIODS):
        raise ValueError("選択比較の政策又は期間差")
    for policy, control in zip(NEW, ("U0", "U1")):
        if set(result["選択比較"][policy]) != set(PERIODS):
            raise ValueError("新旧比較の三期間差")
        for period in PERIODS:
            row = result["選択比較"][policy][period]
            n = result["準備比較"][period]["全予定枠"]
            if row["全予定枠"] != n or not 0 <= row["特徴準備枠"] <= n:
                raise ValueError("選択比較の全予定・準備分母差")
            if (row["旧純採用"], row["新純採用"]) != (result["候補"][control][period]["入口"]["候補"], result["候補"][policy][period]["入口"]["候補"]):
                raise ValueError("選択比較と入口純採用差")
            if (row["共通同方向"] + row["追加純候補"] + row["反対変更"] != row["新純採用"]
                    or row["共通同方向"] + row["除外純候補"] + row["反対変更"] != row["旧純採用"]):
                raise ValueError("共通・追加・除外・反対変更の復元差")
            if sum(row["追加時旧理由"].values()) != row["追加純候補"]:
                raise ValueError("追加時の旧理由分母差")
    for period, row in result["新候補方向差"].items():
        n = result["準備比較"][period]["全予定枠"]
        if row["全予定枠"] != n or any(type(v) is not int or v < 0 for v in row.values()):
            raise ValueError("E0/E1方向差の件数型又は分母差")
        common = row["両採用同方向"] + row["両採用逆方向"]
        if common + row["E0のみ採用"] != result["候補"]["E0"][period]["入口"]["候補"] or common + row["E1のみ採用"] != result["候補"]["E1"][period]["入口"]["候補"]:
            raise ValueError("E0/E1方向差と純採用の復元差")
        if common + row["E0のみ採用"] + row["E1のみ採用"] > n:
            raise ValueError("E0/E1の採用和集合が全枠を超過")


def context_for() -> dict:
    """主と保存監査の成功後、旧65木の参照を保って小型保存物を読む。

    引数: なし。
    返り値: dictは表示文脈。新モデル生成・教師・詳細gzip・市場系列は開かない。
    """
    required = [STUDY / n for n in ("結果.json", "保存物確認.json", "固定.json", "条件.json", "検証計画.md", "入力台帳.json", "一覧.resources.json")]
    if any(not p.is_file() for p in required):
        raise FileNotFoundError("主実行と保存監査の完成後だけ生成できます")
    result, proof, fixed = (read(p) for p in required[:3])
    validate_result(result)
    if (result["固定SHA256"] != sha(required[2]) or proof.get("全件一致") is not True or proof.get("不一致数") != 0
            or proof.get("不一致") != [] or proof["結果SHA256"] != sha(required[0])):
        raise ValueError("固定・監査・結果SHAの結合差")
    old = read(OLD / "結果.json")
    for policy in ("U0", "U1"):
        if any(result[key][policy] != old[key][policy] for key in ("候補", "役割別入口")):
            raise ValueError("旧65保存対照の集計差")
    for key in ("評価場", "学習専用場", "準備比較", "独立測定", "独立測定参照", "旧教師一致", "教師集合一致",
            "経路支持", "状態分布", "局面分布", "数量分布", "価格経路分布", "モデル", "回収集計"):
        if result[key] != old[key]:
            raise ValueError("旧65からの継承差:" + key)
    if result["対照モデル"] != old["モデル"] or result["旧証明検査"] != old["検査"]:
        raise ValueError("旧65のモデル又は検査14項目の来歴差")
    if len(result["モデル"]) != 3 or len(result["回収集計"]) != 3:
        raise ValueError("旧参照の木・回収は各3")
    models, paths, metadata = {}, [], None
    calibrations = {e["phase"]: e for e in result["回収集計"]}
    for entry in result["モデル"]:
        phase = entry["phase"]
        if phase not in PHASES or phase in models or (entry["id"], entry["policy"]) != ("U0_" + phase, "U0"):
            raise ValueError("参照モデルは旧U0の三phase")
        cal_entry = calibrations[phase]
        path, cal_path = ((ROOT / e["path"]).resolve() for e in (entry, cal_entry))
        if any(not p.is_relative_to(OLD) for p in (path, cal_path)):
            raise ValueError("モデルを66へ複製せず旧65を直接参照する")
        if sha(path) != entry["SHA256"] or sha(cal_path) != cal_entry["SHA256"]:
            raise ValueError("参照モデル又は回収集計のSHA差")
        model, cal = read(path), read(cal_path)
        BASE.validate_model(model)
        R55.validate_calibration(cal, model)
        if (cal_entry["id"], cal_entry["policy"], model["model_id"], cal["policy"], cal["base_model_path"], cal["base_model_sha256"]) != (
                entry["id"], "U0", entry["id"], "U0", entry["path"], entry["SHA256"]):
            raise ValueError("旧モデルと回収payloadの結合差")
        if metadata is not None and model["feature_meta"] != metadata:
            raise ValueError("参照三木の全60metadata差")
        metadata = model["feature_meta"]
        models[phase] = {"entry": entry, "base": model, "calibration": cal, "base_path": path, "path": cal_path}
        paths.extend((path, cal_path))
    if set(models) != set(PHASES) or set(calibrations) != set(PHASES):
        raise ValueError("旧65W20/W30/F40の参照差")
    BASE.validate_episode_support(result["経路支持"], models)
    BASE.validate_state_distribution(result["状態分布"], models)
    resources = read(required[-1])["resources"]
    if len(resources) != 184 or Counter(x["method_id"] for x in resources) != {p: 46 for p in POLICIES}:
        raise ValueError("旧U92＋新E92のViewer184資源差")
    if any(not (ROOT / e["pnl_path"]).is_file() for e in resources):
        raise ValueError("Viewer約定参照欠落")
    sources = [*required, *paths, Path(__file__), HERE / "README.md", HERE / "レポートの人工検査.py", HERE / "検証.py",
        HERE / "選択.py", HERE / "選択仕様.md", HERE / "保存検証.py", SHARED, R64.SHARED,
        ROOT / "scripts/量と価格進行/特徴.py", ROOT / "scripts/量と価格進行/特徴仕様.md", V5.CATALOG, V5.MASTER,
        ROOT / "scripts/レポート/カタログ版5.py", ROOT / "scripts/レポート/設定結果レポート.py", EXTERNAL,
        OLD / "結果.json", OLD / "設定と結果.md", OLD / "保存物確認.json"]
    for path in sources:
        if not path.is_file():
            raise FileNotFoundError(path)
        name = path.relative_to(ROOT).as_posix()
        if name in fixed["ファイルSHA256"] and sha(path) != fixed["ファイルSHA256"][name]:
            raise ValueError("固定出典変更:" + name)
    return {"result": result, "proof": proof, "fixed": fixed, "models": models, "metadata": metadata,
        "sources": list(dict.fromkeys(sources))}


# ----------------------------------------
# 同じ60入力・旧木の参照・選択順序だけを説明する。


def settings(context: dict) -> list[dict]:
    """既存60列と適格集合内選択を版5のセルへ対応させる。

    引数: context(dict)は全60metadataを持つ文脈。
    返り値: list[dict]は複合評価設定。新たな特徴や独立票を追加しない。
    """
    rows = BASE.settings(context)[:60]
    for row in rows:
        row.update(結果短記="R01/R02/R03/R04", 説明="旧65U・新66Eは同60入力と旧U0三木・回収を共有。入力追加・新fitなし。")
    extras = [(["M01"], ["m03", "m15", "m30"], "R01/R02", "旧65U0/U1保存対照", "最高score側が不適格なら他側へ移らない旧選択。旧92運用を再生しない。"),
        (["M01"], ["m03", "m15", "m30"], "R03/R04", "E0/E1:適格集合内のscore最高側", "同点・片側未知は先に旧WAIT。各側score>=1/3・葉技法・回収支持を先評価。次に適格内で障壁score順位。"),
        (["M01"], ["m03", "m15", "m30"], "R04", "E1:各側の主回収strict正も必要", "Decimal主合計>0を各側資格に含む。E1はE0の反対側を選び得るので同方向部分集合を要求しない。"),
        (["M01", "P10"], ["m03", "m15", "m30"], "R01/R02/R03/R04", "旧65DI→対応episode有効根を参照", "全深さ4/子58深さ2/固定trend+price。V1出生でr/k未確認を含む。木・支持・閾値・教師・回収を変更しない。"),
        (["B01", "E02"], ["tick"], "R03/R04", "旧55測定・旧65木/回収を再用", "新計測・新fit・教師再生成0、同時保有不能な独立回収合算を戦略利益と呼ばない。"),
        (["E01", "E02", "C06"], ["tick"], "R01/R02/R03/R04", "O49現在益122円strict正・固定250TPなし", "損失側も連続追尾、新規D5..125固定、名目床・非緩和・返済pending保護凍結。"),
        (["C07"], ["m15"], "R01/R02/R03/R04", "全25/49予定枠・保守待ち50%以下", "保有は非待ち、判定不能を含む全枠分母。純候補の追加と実参加の増加を混同しない。")]
    for methods, scales, evaluations, short, description in extras:
        rows.append({"設定ID": f"S{len(rows) + 1:02d}", "手法ID": methods, "尺度ID": scales,
            "短記": short, "結果短記": evaluations, "説明": description})
    return rows


def feature_table(context: dict) -> str:
    """変更しない全60特徴を省略せず表示する。

    引数: context(dict)は旧65保存metadata。
    返り値: strは全式・family・尺度と参照条件。
    """
    rows = [[m["id"], m["name"], m["method"], m["family"], m["scale"], FORMULAS[i]] for i, m in enumerate(context["metadata"])]
    return ("## 全60特徴・新情報も新fitもなし\n\n旧U・新Eの全入力は同じ。旧65U0の保存木を使い、DI非正→R現在有効F26(index25)、正→T現在有効F20(index19)で分ける。"
        "非正子はindex0/25、正子はindex0/19を除く58列・深さ2。V1はbからでr/k確認ではなく、V0は未登録・取消・TTL/reset等の混合。"
        "この構造は66で再学習しない。固定trend+priceによるpath資格は、現在のsetup／trigger成立を保証しない。\n\n"
        + table(["ID", "特徴", "手法", "family", "尺度", "固定式・範囲"], rows)
        + "量の同時刻基準、b/r一足進行の現在ATR正規化、未知両0＋共同mask、保持KとTTL、k後の取消・進行統計も旧65と同じ。"
        "量のみで方向を決めず、各側の特徴や過去回収へ未来ラベルを混ぜない。原典の価格triggerと葉のfamily分類は別の観測である。\n\n")


def reference_tables(context: dict, output: Path) -> str:
    """旧65三木と三回収表を参照先と来歴を保って全表示する。

    引数: context(dict)は旧木文脈、output(Path)は出力MD。
    返り値: strは保存閾値・支持・score・平均。複製保存や再fitなし。
    """
    models = BASE.model_tables(context, output)
    models = models.replace("新回帰木3つの全分岐", "参照する旧65三木の全分岐")
    models = models.replace("回帰fitは最大12（3phase×4子）、空子はfitしない。新分類器fit0。",
        "旧65で学習済みの三木を直接参照し、66の回帰fit0・分類fit0・新保存木0。")
    models = models.replace("子の探索目的は", "旧65子の探索目的は")
    models = models.replace("旧64から固定段がtrend+priceへ変わるが", "旧65参照木の固定段はtrend+priceだが")
    models = models.replace("対応V0も残し、最高score側の資格不足を次点で救済しない。",
        "対応V0も旧木内へ残す。66の方向選択は両側資格先行へ変更する。")
    recovery = BASE.recovery_tables(context, output).replace("U1は主合計strict>0", "E1は同じ参照集計の主合計strict>0")
    recovery = recovery.replace("旧D0使用教師ID・新木使用ID・旧55校正IDの同集合を確認する。",
        "旧65が確認した教師・回収集合と保存集計をそのまま参照する。66で再集計しない。")
    return ("## 変更しない学習・回収の参照\n\nモデル名/policyは旧U0のまま、pathは旧65のmodels配下。新E0/E1という木を作らず、同じ閾値・葉支持・回収平均を使う。"
        "下表の教師・目的値・回収は旧65時点の値で、66の新fit・新測定結果ではない。\n\n" + models + recovery)


def selection_table(result: dict) -> str:
    """選択比較と保存判断理由を、実運用の活動分母と分けて表示する。

    引数: result(dict)は主の選択比較。
    返り値: strは政策・期間別の全保存比較値。欠けた値を補完しない。
    """
    rows = []
    for policy, periods in result["選択比較"].items():
        for period, fields in periods.items():
            for name, value in fields.items():
                rows.append([policy, PERIOD_NAMES.get(period, period), name,
                    json.dumps(value, ensure_ascii=False, sort_keys=True) if isinstance(value, (dict, list)) else value])
    cross = [[PERIOD_NAMES[t], *(row[k] for k in ("全予定枠", "両採用同方向", "両採用逆方向", "E0のみ採用", "E1のみ採用")),
        row["全予定枠"] - sum(row[k] for k in ("両採用同方向", "両採用逆方向", "E0のみ採用", "E1のみ採用"))] for t, row in result["新候補方向差"].items()]
    return ("## 適格先行による方向選択の比較\n\n同点又は片側未知なら順位比較を遮断して旧WAIT。両側既知で差があるときだけ、各側のscore>=1/3・葉支持・技法資格・回収支持を先に評価する。"
        "E1は各側の回収主合計strict正も資格へ含む。適格集合から最高score側を選び、回帰平均順位へ変更しない。"
        "他側採用はその側自身が適格な場合に限り、元仮説の否定だけで反対注文を成立させない。\n\n"
        + table(["政策", "期間", "保存項目", "保存値"], rows)
        + "### 新E0/E1同士の純方向差\n\n" + table(["期間", "全予定枠", "両同方向", "両逆方向", "E0のみ", "E1のみ", "両不採用"], cross)
        + "両側資格がE1で狭くなっても、E0が買い・E1が売りになることがある。E1の同方向純部分集合や実参加包含を断定しない。"
        "予測救済はraw DI同値等の後段拒否より前の予測フラグで、純追加や実新規とは別の件数。"
        "純候補と、先の保有・pendingによって変わる実新規/完結は別である。追加候補だけを独立再運用した利益ではない。\n\n")


def documents(context: dict) -> dict[str, str]:
    """新しい木を作らず、保存結果と旧参照から二本文を構成する。

    引数: context(dict)は正式又は人工の表示文脈。
    返り値: dict[str,str]は概要と全設定。原板・教師系列を開かない。
    """
    r, proof = context["result"], context["proof"]
    brief_path, detail_path = STUDY / "README.md", STUDY / "設定と結果.md"
    entrance, operation = main_tables(r)
    status = "新候補の採用なし。両期の支持付き先着70・費用・活動の同時目標は未達。" if not r["採用"] else "保存採用候補：" + "、".join(r["採用"]) + "。未見の利益保証ではない。"
    intro = ("全66場は既使用。初20場は学習専用、学習欄は後20時系列。選択24場・既使用後続2場はF40を使用する。\n\n"
        + status + "\n\n旧65U0/U1は保存対照、新E0/E1は同60入力・同U0三木・同回収集計・同教師・同出口を参照する。"
        "新fit0・新木0・参照モデル3・新独立計測0、新92運用。旧モデルのpath/policyU0を保ち、コピーした新木を保存しない。\n\n"
        "旧Uは全方向score最高側を選んでから資格を課し、不適格なら他側を救済しない。新Eは同点・片側未知の旧WAITを先に保持した後、"
        "両側のscore>=1/3・葉支持・技法・回収支持60枠6日10場を先に検査し、適格な側だけの中で障壁score最高側を選ぶ。"
        "E1は各側にDecimal主回収合計strict正も要求する。回帰平均順位へ変更しない。E1はE0と逆側になる場合があり、同方向部分集合ではない。\n\n"
        "DI同値WAIT、入力不準備、同点、片側未知を低い側の選択で救わない。葉の技法資格は過去pathの分類で、現在の価格setupや再開triggerの成立と同一ではない。"
        "V1出生≠r/k、V0混合という旧65の状態も変えず、今回の比較で取消経路の現在性まで解決したとはしない。\n\n")
    mechanics = ("## 判断・執行と費用\n\n定時はデイ09:15〜15:15の25枠、ナイト17:30〜05:30の49枠。全予定枠分母で待ち＋判定不能の保守上限50%以下、保有継続は非待ち。"
        "純採用の増減や反対変更が実新規の増減と一致するとは限らない。一建玉・pendingの占有を保つ。\n\n"
        "固定49O、現在正常BBOから1価格時計秒後の最初の正常気配へ新規、TTL30秒。過去のb/r/k価格へ約定を戻さない。残り60分停止なし。"
        "強制15:35/05:50、終了15:40/05:55。micro1枚10円/pt、片道11円＋滑り5ptの往復122円。"
        "現ATRの5pt切上げをD5..125へ制限して新規時固定、損失側も連続追尾。現在返済気配の粗益−122円strict正で利益旗と最低名目新規床、非緩和、返済pendingのh/L/arm保護凍結。\n\n"
        "固定250TPなし。費用0/10pt感応は同約定・利益起動122円不変、名目床は費用後同値保証ではない。"
        "先着125/250、参照木の過去平均・回帰円予測、実運用の回収を別にする。旧55独立回収の重複保有合計は実行可能な一戦略の利益でない。"
        "品質注意の全体確定nullを維持し、観測・役割別額を無条件確定へ変えない。\n\n")
    links = ("## 正本・閲覧・再表示\n\n" + " / ".join(link(STUDY / n, brief_path) for n in (
        "設定と結果.md", "検証計画.md", "条件.json", "結果.json", "保存物確認.json", "一覧.resources.json"))
        + " / " + link(HERE / "README.md", brief_path, "コードと再現") + "\n\n"
        "[Viewer（ローカル起動時）](http://127.0.0.1:8092)。旧U0/U1各46＋新E0/E1各46＝184資源。\n\n"
        + link(OLD / "設定と結果.md", brief_path, "旧65全60特徴・木と回収") + " / " + link(EXTERNAL, brief_path, "候補成立と方向順位の外部参考")
        + f'\n\n保存監査：{number(proof["照合項目数"])}照合・差{number(proof["不一致数"])}。Viewer範囲は監査JSONを正本とする。\n\n'
        "再表示はfit・予測walk・回収集計・市場運用を再実行しない。\n\n~~~powershell\n"
        "C:/Python314/python.exe -X utf8 scripts/適格方向の選択/レポート.py\n"
        "C:/Python314/python.exe -X utf8 scripts/適格方向の選択/レポート.py --check\n~~~\n")
    uses = settings(context)
    matrix = V5.matrix(V5.load_catalog(), detail_path, uses).replace("未使用", "未使用・未検証")
    settings_table = table(["設定ID", "手法/尺度", "設定内容", "限定"], [[x["設定ID"], "/".join(x["手法ID"]) + "・" + "/".join(x["尺度ID"]), x["短記"], x["説明"]] for x in uses])
    sources = table(["出典", "SHA256"], [[link(p, detail_path), sha(p)] for p in context["sources"]])
    inherited = ("## 再計算しない教師・状態・量の参照\n\n以下の価格経路、数量、状態四群、葉episode支持、上位局面は旧65正本をそのまま継承した参照表示。"
        "66の純採用や実完結の群別集計ではなく、新しく特徴・教師を再計算した値でもない。\n\n"
        + BASE.coverage_table(r) + BASE.quantity_table(r) + BASE.state_distribution_table(context)
        + BASE.episode_support_table(context) + BASE.regime_distribution_table(r))
    external = ("## 原典と葉資格の違い\n\n確認日2026-11-06。Tharp本人研究所のsystem構成、SMB Garrett Drinonの2023年setup/trigger説明、"
        "Raschke本人保管の1997年AIQインタビューを再読した。新発見ではなく、候補成立と発動・管理の役割を分ける参考である。"
        "3資料は同一先物の二方向scoreから適格集合内で選ぶ算法や、その利益を実証していない。"
        "実setup/trigger、心理仮説、過去path family・支持/平均を区別し、裁量退出・swing stop・買増しをO49へ移植しない。"
        + link(EXTERNAL, detail_path, "書誌・読取範囲・心理/観測の限定") + "を参照する。\n\n")
    brief = "# 00066：複数手法の適格方向から優先側を選ぶ\n\n" + intro + "## 入口先着\n\n" + entrance + "## 混合一建玉の実運用\n\n" + operation + mechanics + links
    detail = ("# 00066：設定と結果\n\n" + intro + "R01=旧U0、R02=旧U1、R03=E0、R04=E1。\n\n"
        "## 手法×尺度・版5全文\n\n55手法×9尺度を全件保持し、未使用・未検証とデータ不足・対象外を分ける。複合成績を個別手法の効果にしない。\n\n"
        + matrix + feature_table(context) + "## 設定明細\n\n" + settings_table + reference_tables(context, detail_path)
        + selection_table(r) + inherited + "## 全候補の入口先着\n\n" + entrance + "## 全候補の混合運用\n\n" + operation
        + detail_tables(r) + mechanics + external + "## 検査と来歴\n\n学習参照：" + json.dumps(r["学習参照"], ensure_ascii=False)
        + "。新実施検査：" + json.dumps(r["検査"], ensure_ascii=False) + "。旧65証明検査：" + json.dumps(r["旧証明検査"], ensure_ascii=False)
        + "。旧教師一致：" + json.dumps(r["旧教師一致"], ensure_ascii=False) + "。教師集合一致：" + json.dumps(r["教師集合一致"], ensure_ascii=False)
        + "。base60六指紋・既存18/30/38/46/54は旧65モデル内の同じ値を参照する。66で新しく再生成・再fitした証明ではない。\n\n"
        + "## 保存出典\n\n" + sources + "## 再表示\n\n" + link(brief_path, detail_path, "概要とコマンド") + "\n")
    return {"README.md": brief, "設定と結果.md": detail}


def self_test() -> dict:
    """別ファイルの人工表示検査を呼び、成功と件数を返す。

    引数: なし。
    返り値: dictは正式人工記録用。実入力なし、失敗時終了1。
    """
    spec = importlib.util.spec_from_file_location("適格選択66表示の人工", HERE / "レポートの人工検査.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.run(sys.modules[__name__])


def main() -> None:
    """正式表示又は人工検査のCLIを選ぶ。

    引数: なし。--checkと--self-testは排他的。
    返り値: None。正式生成は主・監査成功後の通知時だけ行う。
    """
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--check", action="store_true")
    group.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    print(json.dumps(self_test() if args.self_test else render(args.check), ensure_ascii=False))


if __name__ == "__main__":
    main()
