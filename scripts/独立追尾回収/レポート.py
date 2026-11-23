"""55の保存結果と過去の葉内回収だけを二つのMarkdownへ表示する。"""

import argparse
from collections import Counter
from copy import deepcopy
from decimal import Decimal
import importlib.util
import json
import math
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
STUDY = ROOT / "study/00055_先着候補へ独立追尾回収を加える"
OLD = ROOT / "study/00054_方向と局所帯を先に分岐"
SHARED = ROOT / "scripts/局所帯分岐/レポート.py"
SPEC = importlib.util.spec_from_file_location("独立追尾回収の固定53表示純補助", SHARED)
G = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = G
SPEC.loader.exec_module(G)
V5 = G.V5
POLICIES = ("D0", "C0", "R0")
PERIODS = ("学習", "条件選択", "後続検査")
PERIOD_NAMES = {"学習": "時系列検査20場", "条件選択": "条件選択24場", "後続検査": "既使用後続2場"}
PHASES = ("W20", "W30", "F40")
EVALUATIONS = {"D0": "R01", "C0": "R02", "R0": "R03"}
sha, read, fingerprint, table = G.sha, G.read, G.fingerprint, G.table
number, rate, qualification, link = G.number, G.rate, G.qualification, G.link


def money(value: float | None, empty: str = "null（品質注意）") -> str:
    """数値0とnullを別に表示する。

    引数: value(float|None)は保存額、empty(str)はnullの説明。
    返り値: strは円額又は明示的なnull。
    """
    return empty if value is None else number(value, 2)


def validate_result(result: dict) -> None:
    """保存集計の分母・活動・費用を表示前に検査する。

    引数: result(dict)は55の結果。市場系列を参照しない。
    返り値: None。不整合は拒否する。
    """
    if result.get("試行") != 55 or result.get("全66場既使用") is not True or set(result["候補"]) != set(POLICIES):
        raise ValueError("55の候補又は既使用契約が不正")
    if result["新分類器fit"] != 0 or result["新運用数"] != 92:
        raise ValueError("新fit0・新92運用が必要")
    if len(set(result["評価場"])) != 46 or len(set(result["学習専用場"])) != 20 or set(result["評価場"]) & set(result["学習専用場"]):
        raise ValueError("初20専用・後46場の区分差")
    if result["対照参照"] != {"候補": ["D0"], "元試行": 54, "同じ評価46場": True, "市場再生": False}:
        raise ValueError("対照は固定54D0の保存値のみ")
    if sum(r["方向行数"] for r in result["独立測定"]) != 4884:
        raise ValueError("全2442枠両側4884行の記録差")
    expected_teacher = {"input_rows_sha256", "used_rows_sha256", "row_ids_sha256", "period_sha256"}
    if set(result["旧教師一致"]) != set(PHASES) or any(set(x) != expected_teacher or any(v is not True for v in x.values()) for x in result["旧教師一致"].values()):
        raise ValueError("旧D0の入力/使用行/ID/期間4指紋一致が必要")
    if any(r["状態"] not in ("技法未準備", "確定完結", "品質注意完結", "未解消", "未約定") for r in result["独立測定"]):
        raise ValueError("独立測定の未知状態")
    for period, count in zip(PERIODS, (740, 888, 74)):
        if result["準備比較"][period]["全予定枠"] != count:
            raise ValueError("全予定枠の準備分母差")
        for policy in POLICIES:
            entry, op = result["候補"][policy][period]["入口"], result["候補"][policy][period]["運用"]
            if sum(entry["結果別"].values()) != entry["候補"] or entry["候補"] - entry["結果別"].get("未約定", 0) != entry["約定"]:
                raise ValueError("純採用と仮約定の分母差")
            for win, total, value in (("250", "約定", "率"), ("間引き250", "間引き約定", "間引き率")):
                if (entry[value] is None) != (entry[total] == 0) or entry[total] and not math.isclose(entry[value], entry[win] / entry[total], rel_tol=0, abs_tol=1e-12):
                    raise ValueError("主又は非重複先着率の分母差")
            wait, invalid = op["判断別"].get("待ち", 0), op["判断別"].get("判定不能", 0)
            if op["予定枠"] != count or sum(op["判断別"].values()) != count or op["待ち数"] != wait or op["判定不能"] != invalid:
                raise ValueError("実運用の全予定枠差")
            if not math.isclose(op["主待ち率"], wait / count, abs_tol=1e-12, rel_tol=0) or not math.isclose(op["待ち率保守上限"], (wait + invalid) / count, abs_tol=1e-12, rel_tol=0):
                raise ValueError("待ち又は保守上限の分母差")
            if op["活動適格"] != ((wait + invalid) * 2 <= count):
                raise ValueError("活動適格の判定差")
            for fee in (0, 5, 10):
                if op["完結観測額円"][str(fee)] != op["完結観測額円"]["0"] - 20 * fee * op["完結数"]:
                    raise ValueError("同約定の費用感応差")
                if op["品質注意場"] and op["全体確定額円"][str(fee)] is not None:
                    raise ValueError("品質注意の確定null差")
            if result["候補"][policy][period]["同時適格"] != (entry["70目標"] and op["活動適格"] and op["費用適格"]):
                raise ValueError("同時適格の判定差")
    if result["採用"] != [p for p in ("C0", "R0") if all(result["候補"][p][s]["同時適格"] for s in PERIODS[:2])]:
        raise ValueError("採用対象は新2候補の両期同時適格")


def validate_calibration(cal: dict, base: dict) -> None:
    """全葉の保存支持・正額・nullと未来境界を照合する。

    引数: cal(dict)は回収集計、base(dict)は固定54木。教師系列を新たに作らない。
    返り値: None。平均表示の丸めを採否へ使わない。
    """
    if cal["model_id"] != base["model_id"] or cal["classifier_fit_count"] != 0:
        raise ValueError("旧D0と回収集計の対応差")
    identities = base["training"]["row_ids"]
    if cal["old_teacher_direction_rows"] != len(identities) or cal["old_teacher_ids_sha256"] != fingerprint(identities):
        raise ValueError("旧使用教師IDの結合差")
    if cal["used_pairs"] != cal["input_pairs"] - len(cal["excluded_pairs"]) or cal["used_direction_rows"] != 2 * cal["used_pairs"]:
        raise ValueError("回収確定pairの共通部分差")
    if set(cal["leaves"]) != {str(n["id"]) for n in base["nodes"] if n["left"] == n["right"] == -1}:
        raise ValueError("空葉を含めた全葉の保存差")
    if sum(v["direction_rows"] for v in cal["leaves"].values()) != cal["used_direction_rows"]:
        raise ValueError("全葉の方向行数復元差")
    if cal["evaluation_start"] != base["training"]["period"]["evaluation_start"]:
        raise ValueError("回収集計の評価開始差")
    for identity, leaf in cal["leaves"].items():
        n = leaf["direction_rows"]
        if leaf["leaf"] != int(identity) or n != len(leaf["rows"]):
            raise ValueError("回収葉ID又は方向行数差")
        sums = {f: Decimal(leaf["sum_yen"][f]) for f in ("0", "5", "10")}
        if sums["5"] != sums["0"] - 100 * n or sums["10"] != sums["0"] - 200 * n:
            raise ValueError("葉内の費用感応差")
        for fee in ("0", "5", "10"):
            expected = float(sums[fee] / n) if n else None
            if leaf["mean_yen"][fee] != expected:
                raise ValueError("空葉null又は保存平均差")
        if leaf["support"] != (leaf["unique_slots"] >= 60 and leaf["days"] >= 6 and leaf["sessions"] >= 10):
            raise ValueError("確定回収支持60/6/10の差")
        if leaf["positive"] != (n > 0 and sums["5"] > 0):
            raise ValueError("十進主純額strict正の差")
        if n and (leaf["max_teacher_end"] is None or leaf["max_teacher_end"] >= cal["evaluation_start"]):
            raise ValueError("回収又は障壁の未来終了")
        if not n and leaf["max_teacher_end"] is not None:
            raise ValueError("空葉の教師終了はnull")


def context_for() -> dict:
    """正式な小型保存物だけを読み、監査・版・Viewerへ接続する。

    引数: なし。
    返り値: dictは表示文脈。圧縮詳細、原板、特徴・計測・学習関数は呼ばない。
    """
    required = [STUDY / name for name in ("結果.json", "保存物確認.json", "固定.json", "条件.json", "検証計画.md", "入力台帳.json", "一覧.resources.json")]
    for path in required:
        if not path.is_file():
            raise FileNotFoundError("正式結果と保存監査の完成後だけ生成できます: " + str(path))
    result, proof, fixed = read(required[0]), read(required[1]), read(required[2])
    validate_result(result)
    if result["固定SHA256"] != sha(STUDY / "固定.json") or proof.get("全件一致") is not True or proof.get("不一致数") != 0 or proof.get("不一致") != []:
        raise ValueError("固定又は正式保存監査の不一致")
    if proof["結果SHA256"] != sha(STUDY / "結果.json"):
        raise ValueError("監査の結果SHAが旧版")
    old = read(OLD / "結果.json")
    if result["候補"]["D0"] != old["候補"]["D0"] or result["準備比較"] != old["準備比較"] or result["対照モデル"] != old["モデル"]:
        raise ValueError("固定54の対照又は準備差")
    for key in ("評価場", "学習専用場"):
        if result[key] != old[key]:
            raise ValueError("同じ初20/評価46場が必要")
    controls = {entry["id"]: entry for entry in result["対照モデル"]}
    if set(controls) != {"D0_" + phase for phase in PHASES}:
        raise ValueError("旧D0の3モデルが必要")
    models, metadata, model_paths = {}, None, []
    for entry in result["モデル"]:
        phase = entry["phase"]
        path = (ROOT / entry["path"]).resolve()
        if phase not in PHASES or phase in models or not path.is_relative_to(STUDY) or sha(path) != entry["SHA256"]:
            raise ValueError("新3回収集計のパス・版・重複差")
        cal = read(path)
        base_path = (ROOT / cal["base_model_path"]).resolve()
        prior = controls[entry["id"]]
        if not base_path.is_relative_to(OLD) or cal["base_model_path"] != prior["path"] or sha(base_path) != prior["SHA256"] or cal["base_model_sha256"] != prior["SHA256"]:
            raise ValueError("旧D0木の出典差")
        base = read(base_path)
        validate_calibration(cal, base)
        if cal["phase"] != phase or entry["id"] != "D0_" + phase:
            raise ValueError("回収集計のphase差")
        if metadata is None:
            metadata = base["feature_meta"]
        if base["feature_meta"] != metadata or len(metadata) != 18:
            raise ValueError("固定18特徴の順序差")
        models[phase] = {"entry": entry, "calibration": cal, "base": base, "path": path, "base_path": base_path}
        model_paths += [path, base_path]
    if set(models) != set(PHASES):
        raise ValueError("W20/W30/F40の回収集計が必要")
    resources = read(STUDY / "一覧.resources.json")["resources"]
    if len(resources) != 138 or Counter(r["method_id"] for r in resources) != {"D0": 46, "C0": 46, "R0": 46}:
        raise ValueError("旧46+新92のViewer資源差")
    for r in resources:
        if not (ROOT / r["pnl_path"]).is_file():
            raise ValueError("Viewer約定参照欠落")
    sources = [*required, *model_paths, Path(__file__), HERE / "README.md", HERE / "検証.py", HERE / "回収集計.py",
               HERE / "計測.py", HERE / "保存物確認.py", SHARED, ROOT / "scripts/レポート/カタログ版5.py",
               ROOT / "scripts/レポート/設定結果レポート.py", V5.CATALOG, V5.MASTER,
               OLD / "結果.json", OLD / "設定と結果.md", ROOT / "scripts/局所帯分岐/特徴仕様.md",
               ROOT / "docs/議論/次の比較を価格経路と回収から設計する.md",
               ROOT / "docs/議論/入口の先着と追尾退出の順序を分ける.md",
               ROOT / "docs/議論/外部再調査/追尾の距離と入口の押戻余地を分ける.md"]
    for path in sources:
        if not path.is_file():
            raise FileNotFoundError(path)
        name = path.relative_to(ROOT).as_posix()
        if name in fixed["ファイルSHA256"] and sha(path) != fixed["ファイルSHA256"][name]:
            raise ValueError("固定出典変更:" + name)
    return {"result": result, "proof": proof, "fixed": fixed, "config": read(STUDY / "条件.json"),
            "models": models, "metadata": metadata, "sources": list(dict.fromkeys(sources))}


def settings(context: dict) -> list[dict]:
    """全18入力と独立回収・実執行を版5のセルへ対応させる。

    引数: context(dict)は保存文脈。
    返り値: list[dict]は設定。新しい指標や時間足を追加しない。
    """
    result = []
    for index, meta in enumerate(context["metadata"]):
        result.append({"設定ID": f"S{index + 1:02d}", "手法ID": [meta["method"]], "尺度ID": meta["scale"].split("+"),
                       "短記": meta["id"] + "=" + G.FORMULAS[index] + "・54固定", "結果短記": "R01/R02/R03",
                       "説明": "全18特徴は54から不変。実際の全分岐閾値は54設定と旧3モデル参照。未分岐入力の単独効果は未評価"})
    extras = [(["M01"], ["m03", "m15", "m30"], ["R01", "R02", "R03"], "固定D0木3・新fit0", "Z→float32 DI非正/正→17列d2。price+trendで技法資格は構造上充足。"),
              (["B01", "E02"], ["tick"], ["R02", "R03"], "全2442枠×両側の独立測定4884記録", "readyだけ単独O49。未約定/品質注意/未解消を損益0へ補完しない。D0実完結との一致も検査するが、独立合算はstrategy利益ではない。"),
              (["M01"], ["tick", "m03", "m15", "m30"], ["R02", "R03"], "C0過去回収支持60枠6日10場", "旧training.row_idsと両側回収確定pairの共通部分。旧最高側不適格の次点救済なし。"),
              (["M01"], ["tick", "m03", "m15", "m30"], ["R03"], "R0:C0＋過去平均5>0strict", "十進sum_yen5>0で判定。空平均null、0非採用。確率1/3とは別の円条件。"),
              (["E02", "C06"], ["tick"], ["R01", "R02", "R03"], "固定49O・現在益122円strict", "損失/利益連続追尾、名目床・非緩和・pending保護凍結。Dは新規時ATR由来固定。"),
              (["E01"], ["tick"], ["R01", "R02", "R03"], "同時計B±125/250/期限", "固定250TPなし。仮先着と実回収/売買黒字率は別。"),
              (["C07"], ["m15"], ["R01", "R02", "R03"], "当時3分/15分公開と鮮度", "15分は判断頻度と上位DMI。m30は3分10本OR集計であり30分OHLC追加なし。")]
    for methods, scales, applies, short, detail in extras:
        result.append({"設定ID": f"S{len(result) + 1:02d}", "手法ID": methods, "尺度ID": scales,
                       "短記": short, "結果短記": "/".join(applies), "説明": detail})
    return result


def main_tables(result: dict) -> tuple[str, str]:
    """主先着と混合一建玉運用を分けて表にする。

    引数: result(dict)は55結果。
    返り値: tuple[str,str]は入口表と運用表。
    """
    entrance, cash = [], []
    for policy in POLICIES:
        for period in PERIODS:
            r = result["候補"][policy][period]
            e, o = r["入口"], r["運用"]
            entrance.append([policy, PERIOD_NAMES[period], e["候補"], f'{e["250"]}/{e["約定"]}', rate(e["率"]),
                             f'{e["間引き250"]}/{e["間引き約定"]}', rate(e["間引き率"]),
                             f'{e["日数"]}日/{e["場数"]}場', qualification(e["支持"]), qualification(e["70目標"])])
            cash.append([policy, PERIOD_NAMES[period], o["完結数"], money(o["完結観測額円"]["5"]),
                         money(o["全体確定額円"]["5"]), len(o["品質注意場"]), rate(o["主待ち率"]),
                         rate(o["待ち率保守上限"]), qualification(o["活動適格"]),
                         f'{o["利益起動件数"]}/{o["起動後赤字件数5"]}', qualification(o["費用適格"]), qualification(r["同時適格"])])
    return (table(["候補", "期間", "純採用", "250/仮約定", "主率", "非重複250/約定", "非重複率", "日/場", "入口支持", "70目標"], entrance),
            table(["候補", "期間", "実完結", "観測5円", "全体確定5円", "品質注意場数", "待ち", "保守上限", "活動", "利益旗/旗後赤字", "費用", "同時適格"], cash))


def feature_table(context: dict) -> str:
    """旧15に局所帯3を加えた18特徴を全て明示する。

    引数: context(dict)は固定metadata。
    返り値: strは全18列。木の全nodeは再転記しない。
    """
    rows = [[meta["id"], meta["name"], meta["method"], meta["family"], meta["scale"], G.FORMULAS[index]]
            for index, meta in enumerate(context["metadata"])]
    return "## 固定18特徴\n\n" + table(["ID", "特徴", "手法", "family", "尺度", "方向正規化式"], rows)


def recovery_tables(context: dict, output: Path) -> str:
    """全phaseの回収支持と全葉平均をnull込みで表示する。

    引数: context(dict)は保存3回収集計、output(Path)は詳細MD。
    返り値: strはphase表・除外表・全葉表。独立教師純額をstrategy損益としない。
    """
    phases, leaves, excluded = [], [], []
    for phase in PHASES:
        item = context["models"][phase]
        cal, entry = item["calibration"], item["entry"]
        phases.append([phase, link(item["base_path"], output, cal["model_id"]), link(item["path"], output, "回収集計"),
                       f'{len(entry["学習場"])}/{len(entry["評価場"])}', cal["old_teacher_direction_rows"],
                       cal["input_pairs"], cal["used_pairs"], len(cal["excluded_pairs"]), cal["used_direction_rows"], cal["evaluation_start"]])
        combinations = Counter(json.dumps(x["states"], ensure_ascii=False, sort_keys=True) for x in cal["excluded_pairs"])
        for status, count in sorted(combinations.items()):
            excluded.append([phase, status, count])
        for identity, leaf in sorted(cal["leaves"].items(), key=lambda x: int(x[0])):
            sums = " / ".join(f"{fee}:{leaf['sum_yen'][fee]}" for fee in ("0", "5", "10"))
            means = " / ".join(f"{fee}:" + money(leaf["mean_yen"][fee], "null（空葉）") for fee in ("0", "5", "10"))
            leaves.append([phase, identity, leaf["direction_rows"], leaf["unique_slots"], f'{leaf["days"]}日/{leaf["sessions"]}場',
                           sums, means, qualification(leaf["support"]), qualification(leaf["positive"]),
                           "null" if leaf["max_teacher_end"] is None else leaf["max_teacher_end"]])
    return ("## 過去の回収集計3つと全葉\n\n新しい分類器fitは0。旧先着木の全過去教師と両側回収確定pairの共通部分だけを使う。"
            "各方向の重み0.5は共通なので、葉平均は純額合計/方向行数。両方向行や重複保有は独立標本ではなく、この合計は同時実行可能な戦略利益ではない。"
            "平均表示を丸めても、正額採否は十進主純額のstrict>0で固定する。\n\n"
            + table(["phase", "旧木", "保存回収", "過去/評価場数", "旧方向教師", "入力pair", "使用pair", "除外pair", "使用方向行", "評価開始秒"], phases)
            + "全葉を載せ、空葉の平均はnullのままにする。日数は場名の日付、場数はセッション数。0/5/10は追加片道滑りptの費用感応。\n\n"
            + table(["phase", "leaf", "方向行", "unique枠", "日/場", "合計円0/5/10", "平均円0/5/10", "回収支持", "主合計>0", "最大教師終了秒"], leaves)
            + "片側不明ならpair全体を除外する。空の除外表は除外0であり、未知を損益0へ写した意味ではない。\n\n"
            + table(["phase", "除外pairの両方向状態", "pair数"], excluded))


def detail_tables(result: dict) -> str:
    """実費用感応、役割、判断理由、独立測定の状態を表示する。

    引数: result(dict)は保存結果。
    返り値: strは詳細表。roleと品質の範囲を混同しない。
    """
    costs, roles, reasons = [], [], []
    for policy in POLICIES:
        for period in PERIODS:
            o = result["候補"][policy][period]["運用"]
            costs.append([policy, period, o["完結数"], *(money(o["完結観測額円"][str(f)]) for f in (0, 5, 10)),
                          *(money(o["全体確定額円"][str(f)]) for f in (0, 5, 10)), o["未解消"], o["品質注意場"]])
            for role in ("順行", "反転"):
                e = result["役割別入口"][policy][period][role]
                actual = o["役割別完結"][role]
                roles.append([policy, period, role, e["候補"], f'{e["250"]}/{e["約定"]}', rate(e["率"]),
                              qualification(e["支持"]), actual["件数"], money(actual["観測純額5"])])
            if policy != "D0":
                reasons.extend([policy, period, text, n] for text, n in sorted(result["判断理由"][policy][period].items()))
    measured = [[x["区間"], x["状態"], x["方向行数"]] for x in result["独立測定"]]
    return ("## 独立測定の状態\n\n全2442枠×両側4884記録。準備不足・未約定・品質注意完結・未解消を確定回収0へ補完しない。"
            "DI同値の測定roleは便宜上順行だが、記録説明は上位同値、評価候補はDI同値WAITのままである。\n\n"
            + table(["用途区間", "状態", "方向行数"], measured)
            + "## 実運用の費用・品質\n\n未解消新規の費用を含む台帳観測/確定は結果JSONを参照。ここは実完結の観測額と期間全体確定額を並べる。\n\n"
            + table(["候補", "期間", "完結", "観測0", "観測5", "観測10", "確定0", "確定5", "確定10", "未解消", "品質注意場"], costs)
            + "## DI役割別の入口と実完結\n\n同方向=順行/逆方向=反転という保存分類。心理や価格の転換進行を実測した意味ではない。役割別観測額も候補期間全体の品質に従い、群だけ無条件確定とはしない。\n\n"
            + table(["候補", "期間", "役割", "純採用", "250/仮約定", "率", "入口支持", "実完結", "観測5円"], roles)
            + "## 新候補の純判断理由\n\n純採否と、保有・注文占有を反映した実待ちは異なる。回収支持と正額条件の除外を分ける。\n\n"
            + table(["候補", "期間", "保存理由", "枠数"], reasons))


def documents(context: dict) -> dict[str, str]:
    """保存文脈から概要と設定詳細を生成する。

    引数: context(dict)は正式又は人工schema文脈。
    返り値: dict[str,str]はREADME.md/設定と結果.md。ここでは書き込まない。
    """
    result, proof = context["result"], context["proof"]
    readme, detail = STUDY / "README.md", STUDY / "設定と結果.md"
    entry, operation = main_tables(result)
    status = "新候補の採用なし。先着・支持・費用・活動の両期同時適格は未達。" if not result["採用"] else "保存された採用候補：" + "、".join(result["採用"]) + "。既使用データ外の利益保証ではない。"
    intro = ("全66場は既使用。初期20場は学習専用、学習欄は後半20場の時系列検査、選択24/後続2場は40場までの過去集計を固定して評価した。\n\n"
             + status + "\n\n"
             "旧54D0の3分類木は再fitせず、同じ18特徴と最高先着得点側を使う。"
             "C0は葉の過去確定回収60unique枠・6日・10場を要求、R0はC0へ主費用後平均strict正を追加する。"
             "未知・未約定・品質不明を回収0に補完せず、次点方向へ救済しない。\n\n")
    mechanics = ("## 判断・執行と限界\n\n"
                 "デイ09:15〜15:15の25枠、ナイト17:30〜05:30の49枠、初回を除く15分判断。"
                 "保有継続は非待ち、判定不能を含む保守上限も全予定枠で50%以下を要求する。新規の残り60分条件は追加しない。"
                 "新規/返済は後行1価格時計秒、正常BBO、新規TTL30秒。強制15:35/05:50、連続終了15:40/05:55。\n\n"
                 "固定49Oで利益前も損失を連続追尾する。Dは新規時3分ATRの5pt切上げを5〜125へ制限し、建玉中は固定。"
                 "現在正常返済BBOの粗含み益−122円がstrict正なら利益旗、最低名目新規価格床、非緩和、返済pending後の保護凍結を維持する。"
                 "固定250TPはなく、仮125/250先着は別評価。名目同値床は費用後同値の保証ではない。\n\n"
                 "micro1枚・10円/pt・片道11円＋想定片道5ptで主往復122円。0/10ptは同約定への費用感応で、起動費用122円は変えない。"
                 "ラージBBOの代理であり、microの実板や受信遅延を測った利益ではない。\n\n"
                 "独立測定は全定時の両方向を別々の一建玉として測る。その重複する純額合計・葉平均は、単一建玉の戦略損益ではない。"
                 "評価時の未来回収は採否へ渡さず、過去の旧training.row_idsと両側回収確定pairの共通部分だけを使う。"
                 "回収平均は未来確率の校正ではなく、1/3という先着得点閾値を円平均へ流用しない。\n\n"
                 "量・注文フロー・新しい価格発動は追加していない。DI逆向きは転換の時系列確認ではなく、心理も直測していない。"
                 "C0/R0純入口の包含と実参加の包含は別で、群内の非重複集計も加算できない。\n\n")
    links = ("## 正本・閲覧・再表示\n\n" + " / ".join(link(STUDY / n, readme) for n in
             ("設定と結果.md", "検証計画.md", "条件.json", "結果.json", "保存物確認.json", "一覧.resources.json"))
             + " / " + link(HERE / "README.md", readme, "コードと再現") + "\n\n"
             + "[Viewer（ローカル起動時）](http://127.0.0.1:8092)。旧D0保存46資源＋新C0/R0各46＝138資源。"
             "独立測定の合算曲線は作らない。\n\n"
             + link(OLD / "設定と結果.md", readme, "旧D0の全閾値・全葉")
             + " / " + link(ROOT / "docs/議論/次の比較を価格経路と回収から設計する.md", readme, "先着と回収の問い")
             + " / " + link(ROOT / "docs/議論/入口の先着と追尾退出の順序を分ける.md", readme, "54の回収経路診断")
             + " / " + link(ROOT / "docs/議論/外部再調査/上位方向との逆向きと反転確認を分ける.md", readme, "方向配置と反転確認")
             + "\n\n保存監査：" + number(proof["照合項目数"]) + "照合・不一致" + number(proof["不一致数"]) + "。"
             "検算範囲・Viewer確認の実行有無は監査JSONを正本とする。\n\n"
             "再表示は次の2行のみで、独立測定・回収集計・市場運用を再実行しない。\n\n"
             "~~~powershell\nC:/Python314/python.exe -X utf8 scripts/独立追尾回収/レポート.py\n"
             "C:/Python314/python.exe -X utf8 scripts/独立追尾回収/レポート.py --check\n~~~\n\n")
    brief = "# 00055：先着候補へ独立追尾回収を加える\n\n" + intro + "## 入口先着\n\n" + entry + "## 混合一建玉の実運用\n\n" + operation + mechanics + links
    entries = settings(context)
    matrix = V5.matrix(V5.load_catalog(), detail, entries).replace("未使用", "未使用・未検証")
    extra = table(["設定ID", "手法/尺度", "設定内容", "解釈と限定"],
                  [[r["設定ID"], "/".join(r["手法ID"]) + "・" + "/".join(r["尺度ID"]), r["短記"], r["説明"]] for r in entries])
    provenance = table(["出典", "SHA256"], [[link(p, detail), sha(p)] for p in context["sources"]])
    detailed = ("# 00055：設定と結果\n\n" + intro
                + "R01=旧D0、R02=C0、R03=R0。全18入力・旧木・執行は不変で、回収支持と回収正額を段階的に比較する。\n\n"
                + "## 手法×尺度・版5全文\n\n55手法×9尺度＝495セルを保持する。使用セルは設定IDと複合評価IDを示す。"
                "未使用・未検証をデータ不足や対象外と取り替えず、複合成績を指標単独効果とはしない。"
                "m30はOR集計、tickは執行・回収の観測であり新しいtick技法の入力を追加した意味ではない。\n\n"
                + matrix + feature_table(context) + "## 設定明細\n\n" + extra
                + "## 旧分類木の再利用\n\n"
                + link(OLD / "設定と結果.md", detail, "固定54の全分岐閾値・葉支持") + " / "
                + link(ROOT / "scripts/局所帯分岐/特徴仕様.md", detail, "固定18特徴と公開規約") + "。"
                "Z固定段priceとDI符号固定段trendが全pathへ入るため、既存の異種family資格は構造上充足する。"
                "新たに異種技法の有効性を発見したことにはしない。\n\n"
                + recovery_tables(context, detail) + "## 全候補の入口先着\n\n" + entry
                + "## 全候補の混合運用\n\n" + operation + detail_tables(result) + mechanics
                + "## 検査と版\n\n独立測定の検査件数：" + json.dumps(result["検査"], ensure_ascii=False)
                + "。旧D0との教師4指紋一致：" + json.dumps(result["旧教師一致"], ensure_ascii=False)
                + "。正式保存監査は" + link(STUDY / "保存物確認.json", detail) + "。"
                "全日単独比較・旧D0実完結一致・先着新規一致と、後続の混合運用の実績を別に記録する。\n\n"
                + "## 保存出典\n\n" + provenance + "## 再表示\n\n" + link(readme, detail, "概要・再表示コマンド") + "\n")
    return {"README.md": brief, "設定と結果.md": detailed}


def validate_documents(output: dict[str, str], generated: set[Path]) -> int:
    """2MDの全行・内部リンク・18特徴を検査する。

    引数: output(dict[str,str])は文書、generated(set[Path])は同時生成又は人工の仮想参照。
    返り値: intは確認したリンク数。
    """
    text = output["設定と結果.md"]
    catalog = V5.load_catalog()
    rows = [line for line in text.splitlines() if line.startswith("| ") and line.split("|")[1].strip() in {m["id"] for m in catalog["methods"]}]
    if len(rows) != 55 or any(len(row.split("|")) != 13 for row in rows):
        raise ValueError("版5の55行×9尺度を保持していない")
    if any("| " + f"F{i:02d}" + " |" not in text for i in range(1, 19)):
        raise ValueError("18特徴の表示漏れ")
    return sum(G.check_links(value, STUDY / name, generated) for name, value in output.items())


def render(check: bool = False) -> dict:
    """正式2MDを生成するか、保存済み同byteだけを確認する。

    引数: check(bool)は書込しない一致確認。
    返り値: dictは出力SHA・リンク・表検査結果。固定コードや市場を起動しない。
    """
    context = context_for()
    output = documents(context)
    generated = {(STUDY / name).resolve() for name in output}
    links = validate_documents(output, generated)
    reports = {}
    for name, text in output.items():
        path, content = STUDY / name, text.encode("utf-8")
        if check:
            if path.read_bytes() != content:
                raise ValueError("正式帳票と再表示が不一致:" + name)
        else:
            path.write_bytes(content)
        reports[name] = {"SHA256": sha(path), "bytes": len(content)}
    return {"文書": reports, "内部リンク検査": links, "欠落": 0, "版": 5, "手法": 55, "尺度": 9,
            "分類器fit": 0, "再計測_再集計_市場再生": False, "同byte確認": check}


def main() -> None:
    """正式表示又は人工schema検査を選ぶ。

    引数: なし。CLIの--check/--self-testは排他的。
    返り値: None。
    """
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--check", action="store_true")
    group.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        suite = unittest.defaultTestLoader.loadTestsFromTestCase(RenderTests)
        result = unittest.TextTestRunner(verbosity=2).run(suite)
        if not result.wasSuccessful():
            raise SystemExit(1)
    else:
        print(json.dumps(render(args.check), ensure_ascii=False))


# ----------------------------------------
# 人工の数値だけでnull・全葉・表を確認する。正式結果は開かず文書も保存しない。

class RenderTests(unittest.TestCase):
    """回収合計・空葉・正符号と版5表示を検査する。"""

    def test_calibration_null_and_decimal_sign(self) -> None:
        """空葉は平均null、非空平均の採否は十進合計strict正とする。

        引数: なし。
        返り値: None。
        """
        identities = [{"session": "人工", "slot_id": str(i // 2), "side": 1 if i % 2 else -1} for i in range(120)]
        base = {"model_id": "D0_人工", "training": {"row_ids": identities, "period": {"evaluation_start": 1000.}},
                "nodes": [{"id": 0, "left": 1, "right": 2}, {"id": 1, "left": -1, "right": -1}, {"id": 2, "left": -1, "right": -1}]}
        full = {"leaf": 1, "direction_rows": 120, "unique_slots": 60, "days": 6, "sessions": 10,
                "sum_yen": {"0": "12120", "5": "120", "10": "-11880"}, "mean_yen": {"0": 101., "5": 1., "10": -99.},
                "support": True, "positive": True, "rows": [{}] * 120, "max_teacher_end": 990.}
        empty = {"leaf": 2, "direction_rows": 0, "unique_slots": 0, "days": 0, "sessions": 0,
                 "sum_yen": {f: "0" for f in ("0", "5", "10")}, "mean_yen": {f: None for f in ("0", "5", "10")},
                 "support": False, "positive": False, "rows": [], "max_teacher_end": None}
        cal = {"model_id": "D0_人工", "classifier_fit_count": 0, "old_teacher_direction_rows": 120,
               "old_teacher_ids_sha256": fingerprint(identities), "input_pairs": 60, "used_pairs": 60,
               "excluded_pairs": [], "used_direction_rows": 120, "evaluation_start": 1000., "leaves": {"1": full, "2": empty}}
        validate_calibration(cal, base)
        bad = deepcopy(cal)
        bad["leaves"]["2"]["mean_yen"]["5"] = 0.
        with self.assertRaises(ValueError):
            validate_calibration(bad, base)
        bad = deepcopy(cal)
        bad["leaves"]["1"]["positive"] = False
        with self.assertRaises(ValueError):
            validate_calibration(bad, base)
        zero = deepcopy(cal)
        zero["leaves"]["1"].update(sum_yen={"0": "12000", "5": "0", "10": "-12000"},
                                  mean_yen={"0": 100., "5": 0., "10": -100.}, positive=False)
        validate_calibration(zero, base)
        self.assertTrue(zero["leaves"]["1"]["support"])
        self.assertFalse(zero["leaves"]["1"]["positive"])
        bad = deepcopy(cal)
        bad["leaves"]["1"]["max_teacher_end"] = 1000.
        with self.assertRaises(ValueError):
            validate_calibration(bad, base)
        self.assertEqual(money(None, "null（空葉）"), "null（空葉）")
        self.assertEqual(money(0.), "0.00")

    def test_matrix_and_all_eighteen_features(self) -> None:
        """全55×9セルと18入力を保持し、未使用を単独効果へ変えない。

        引数: なし。
        返り値: None。
        """
        methods = ("I08", "I07", "I07", "I09", "P03", "P06", "P05", "P01", "P01", "P01", "P02", "P02", "P01", "P01", "P01", "P03", "P06", "P10")
        metadata = [{"id": f"F{i + 1:02d}", "name": "人工特徴", "method": m, "family": "price", "scale": "m03"} for i, m in enumerate(methods)]
        context = {"metadata": metadata}
        text = V5.matrix(V5.load_catalog(), STUDY / "設定と結果.md", settings(context))
        self.assertEqual(sum(line.startswith("| ") and line.split("|")[1].strip() in {m["id"] for m in V5.load_catalog()["methods"]} for line in text.splitlines()), 55)
        self.assertEqual(feature_table(context).count("| F"), 18)
        self.assertEqual(len(settings(context)[:18]), 18)
        self.assertIn("R0:C0＋過去平均5&gt;0strict", text)

    def test_complete_artificial_documents(self) -> None:
        """人工schemaだけで2MD・null・全葉・全リンク・再表示同byteを検査する。

        引数: なし。
        返り値: None。正式結果・教師・市場を読まず、ファイルも生成しない。
        """
        methods = ("I08", "I07", "I07", "I09", "P03", "P06", "P05", "P01", "P01", "P01", "P02", "P02", "P01", "P01", "P01", "P03", "P06", "P10")
        metadata = [{"id": f"F{i + 1:02d}", "name": "人工特徴", "method": m, "family": "price", "scale": "m03"} for i, m in enumerate(methods)]
        result = {"試行": 55, "全66場既使用": True, "候補": {}, "新分類器fit": 0, "新運用数": 92,
                  "評価場": ["人工評価" + str(i) for i in range(46)], "学習専用場": ["人工専用" + str(i) for i in range(20)],
                  "対照参照": {"候補": ["D0"], "元試行": 54, "同じ評価46場": True, "市場再生": False},
                  "独立測定": [{"区間": "人工全66", "状態": "技法未準備", "方向行数": 4884}],
                  "準備比較": {p: {"全予定枠": n} for p, n in zip(PERIODS, (740, 888, 74))},
                  "役割別入口": {}, "判断理由": {"C0": {}, "R0": {}}, "採用": [], "検査": {},
                  "旧教師一致": {p: {k: True for k in ("input_rows_sha256", "used_rows_sha256", "row_ids_sha256", "period_sha256")} for p in PHASES}}
        for policy in POLICIES:
            result["候補"][policy], result["役割別入口"][policy] = {}, {}
            for period, n in zip(PERIODS, (740, 888, 74)):
                entry = {"候補": 0, "約定": 0, "250": 0, "結果別": {}, "率": None,
                         "間引き約定": 0, "間引き250": 0, "間引き率": None, "日数": 0, "場数": 0,
                         "支持": False, "70目標": False}
                caution = ["人工注意"] if policy == "D0" and period == "学習" else []
                op = {"予定枠": n, "判断別": {"待ち": n}, "待ち数": n, "判定不能": 0,
                      "主待ち率": 1., "待ち率保守上限": 1., "活動適格": False, "完結数": 0,
                      "完結観測額円": {str(f): 0. for f in (0, 5, 10)},
                      "全体確定額円": {str(f): None if caution else 0. for f in (0, 5, 10)},
                      "品質注意場": caution, "未解消": 0, "利益起動件数": 0, "起動後赤字件数5": 0,
                      "費用適格": False, "役割別完結": {r: {"件数": 0, "観測純額5": 0.} for r in ("順行", "反転")}}
                result["候補"][policy][period] = {"入口": entry, "運用": op, "同時適格": False}
                result["役割別入口"][policy][period] = {r: deepcopy(entry) for r in ("順行", "反転")}
                if policy != "D0":
                    result["判断理由"][policy][period] = {"人工WAIT": n}
        models, virtual = {}, {(STUDY / n).resolve() for n in ("README.md", "設定と結果.md", "条件.json", "結果.json", "保存物確認.json", "一覧.resources.json")}
        for phase, train, evaluated in (("W20", 20, 10), ("W30", 30, 10), ("F40", 40, 26)):
            path, base_path = STUDY / "models" / ("回収_" + phase + ".json"), OLD / "models" / ("D0_" + phase + ".json")
            cal = {"model_id": "D0_" + phase, "old_teacher_direction_rows": 2, "input_pairs": 1, "used_pairs": 0,
                   "excluded_pairs": [{"slot_id": "人工", "states": {"1": "未約定", "-1": "確定完結"}}],
                   "used_direction_rows": 0, "evaluation_start": 1000., "leaves": {
                       "1": {"leaf": 1, "direction_rows": 0, "unique_slots": 0, "days": 0, "sessions": 0,
                             "sum_yen": {f: "0" for f in ("0", "5", "10")}, "mean_yen": {f: None for f in ("0", "5", "10")},
                             "support": False, "positive": False, "max_teacher_end": None}}}
            models[phase] = {"path": path, "base_path": base_path, "calibration": cal,
                             "entry": {"学習場": ["人工"] * train, "評価場": ["人工"] * evaluated}}
            virtual.add(path.resolve())
        context = {"metadata": metadata, "result": result, "proof": {"照合項目数": 0, "不一致数": 0},
                   "models": models, "sources": [Path(__file__).resolve()]}
        validate_result(result)
        before = deepcopy(context)
        first, second = documents(context), documents(context)
        self.assertEqual(first, second)
        self.assertEqual(context, before)
        self.assertGreater(validate_documents(first, virtual), 55)
        self.assertIn("null（空葉）", first["設定と結果.md"])
        self.assertIn("null（品質注意）", first["README.md"])
        self.assertIn("未使用・未検証", first["設定と結果.md"])
        self.assertEqual(first["設定と結果.md"].count("| W20 | 1 |"), 1)


if __name__ == "__main__":
    main()
