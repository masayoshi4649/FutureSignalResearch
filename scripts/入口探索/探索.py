"""順行250pt・逆行125ptの入口を、固定条件と学習期間限定のモデルで探索する。"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import itertools
import json
import os
from pathlib import Path
import shutil
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
LIBRARIES = ROOT / "work/入口探索/pythonlibs"
sys.path.insert(0, str(LIBRARIES))
os.environ.setdefault("OMP_NUM_THREADS", "4")
import joblib
import numpy as np
import sklearn
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.tree import DecisionTreeClassifier
from threadpoolctl import threadpool_limits

JST = timezone(timedelta(hours=9))
WORK = ROOT / "work/入口探索"


# ----------------------------------------
# 凍結入力と、未来を含まない特徴の読取

def read_csv(path: Path) -> list[dict[str, str]]:
    """小型の正式表または作業表をUTF-8で読み込む。

    引数: path (Path) はCSVの場所。
    返り値: list[dict[str, str]] は列名付きの全行。
    """
    with path.open(encoding="utf-8-sig", newline="") as source:
        return list(csv.DictReader(source))


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    """列構成が共通の表を保存する。

    引数: path (Path) は保存先、rows (list[dict[str, Any]]) は行。
    返り値: None。空表は空ファイルとする。
    """
    with path.open("w", encoding="utf-8", newline="") as target:
        if rows:
            writer = csv.DictWriter(target, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)


def write_json(path: Path, value: Any) -> None:
    """標準型だけからなる日本語JSONを保存する。

    引数: path (Path) は保存先、value (Any) はJSON化可能な値。
    返り値: None。非有限数は拒否する。
    """
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def sha(path: Path) -> str:
    """小型入力・コード・モデルの内容を識別する。

    引数: path (Path) は対象。
    返り値: str はSHA256。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_module(path: Path, name: str) -> Any:
    """隣の評価処理を独立した名前で読み込む。

    引数: path (Path) はコード、name (str) はモジュール名。
    返り値: Any は読み込んだモジュール。
    """
    specification = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(specification)
    sys.modules[name] = module
    specification.loader.exec_module(module)
    return module


def numeric(value: Any) -> float:
    """数値・真偽値・欠測を行列入力へ正規化する。

    引数: value (Any) はCSV等の値。
    返り値: float は有限数またはNaN。
    """
    if value in (None, "", "None"):
        return float("nan")
    if value in ("True", True):
        return 1.0
    if value in ("False", False):
        return 0.0
    result = float(value)
    return result if np.isfinite(result) else float("nan")


def load_data(study: Path) -> tuple:
    """ラベルと特徴をIDで結合し、日付境界を固定した行列を作る。

    引数: study (Path) は正式試行。
    返り値: tuple は結合行、特徴行列、列名、三分割、定義、設定。
    """
    config = json.loads((study / "条件.json").read_text(encoding="utf-8"))
    if (config.get("版"), config.get("対象"), config.get("順行pt"), config.get("逆行pt"), config.get("目標率")) != (1, "NK225", 250, 125, .7):
        raise ValueError("この版が対応するNK225の250/125・70%条件と異なる")
    labels = read_csv(WORK / "入口250_125.csv")
    features = read_csv(WORK / "特徴.csv")
    definition = json.loads((WORK / "特徴定義.json").read_text(encoding="utf-8"))
    columns = definition["model_columns"]
    if len(columns) != 84 or len(columns) != len(set(columns)):
        raise ValueError("モデルの許可列が空または重複")
    denied = ("ラベル", "新規", "判定", "最大順行", "最大逆行", "所要", "イベント", "原板行", "開始日", "日付")
    if any(any(term in column for term in denied) for column in columns):
        raise ValueError("未来・識別子を含む列をモデルへ渡そうとした")
    indexed = {row["イベントID"]: row for row in features}
    if len(indexed) != len(features) or {row["イベントID"] for row in labels} != set(indexed):
        raise ValueError("特徴とラベルのID集合が一致しない")
    rows = []
    for row in labels:
        other = indexed[row["イベントID"]]
        for key in set(row) & set(other) - {"イベントID"}:
            a, b = numeric(row[key]), numeric(other[key])
            if not ((np.isnan(a) and np.isnan(b)) or np.isclose(a, b, atol=1e-8)):
                raise ValueError(f"重複する特徴値が不一致: {key}")
        rows.append({**row, **other})
    if any(float(row["順行幅pt"]) != 250 or float(row["逆行幅pt"]) != 125 for row in rows):
        raise ValueError("到達幅が250/125と異なる")
    if any(row["ラベル"] not in ("順行先着", "逆行先着", "期限未達", "観測不足", "未約定") for row in rows):
        raise ValueError("未定義の到達ラベル")
    x = np.array([[numeric(row[column]) for column in columns] for row in rows], dtype=float)
    dates = np.array([row["場"][:10] for row in rows])
    boundaries = config["分割"]
    splits = {"学習": dates < boundaries["選択開始日"],
              "条件選択": (dates >= boundaries["選択開始日"]) & (dates < boundaries["後続開始日"]),
              "後続検査": dates >= boundaries["後続開始日"]}
    if any(not np.any(mask) for mask in splits.values()) or not np.all(sum(mask.astype(int) for mask in splits.values()) == 1):
        raise ValueError("日付の三分割が不正")
    return rows, x, columns, splits, definition, config


def family_mask(rows: list[dict[str, str]], specification: dict[str, Any], cache: dict | None = None) -> np.ndarray:
    """固定したチャート仮説と入口時点の補助条件だけで許可を判定する。

    引数: rows (list[dict[str, str]]) は特徴付き候補、specification (dict[str, Any]) は条件、
    cache (dict | None) は同一行列内だけで共用する数値列。
    返り値: np.ndarray はラベルを使わない真偽列。
    """
    cache = {} if cache is None else cache
    def col(name: str) -> np.ndarray:
        """同じ名前の特徴を数値列にする。

        引数: name (str) は列名。
        返り値: np.ndarray は欠測をNaNにした列。
        """
        if rows and name not in rows[0]:
            raise ValueError(f"固定条件が参照する特徴がない: {name}")
        if name not in cache:
            cache[name] = np.array([numeric(row.get(name)) for row in rows])
        return cache[name]

    family = specification["family"]
    if family.startswith("旧群:"):
        group = family.split(":", 1)[1]
        return np.array([group in row["条件群"].split("|") for row in rows])
    support = (col("反対端距離pt_6本") > 0) & (col("反対端距離pt_6本") <= 125)
    upper = col("上位足整合") == 1
    if family == "追随復帰と構造":
        mask = (col("押し戻り復帰") == 1) & support
    elif family == "構造内位置追随":
        mask = upper & support & (col("方向変化pt_1本") > 0)
    elif family == "レンジ端復帰":
        mask = ((col("上位足相互整合") == 0) & (col("反対端復帰_12本") == 1)
                & (col("反対端距離pt_12本") > 0) & (col("反対端距離pt_12本") <= 125)
                & (col("順方向端距離pt_12本") >= 250))
    elif family == "突破再テスト":
        mask = upper & (col("再テスト_6本") == 1) & (col("再テスト水準距離pt") >= 0) & (col("再テスト水準距離pt") <= 125)
    elif family == "収縮突破":
        mask = upper & (col("前足収縮") == 1) & (col("当足拡大") == 1) & (col("方向端突破_6本") == 1)
    elif family == "強い足継続":
        mask = upper & (col("方向実体比_5分") >= .6) & (col("方向終値位置_5分") >= .8) & (col("方向変化pt_1本") > 0)
    else:
        raise ValueError(f"未知の仮説family: {family}")
    direction = specification["direction"]
    if direction != "両方向":
        mask &= np.array([row["方向"] == direction for row in rows])
    mask &= col("残り分_判断時") >= specification["remaining"]
    lo, hi = specification["atr_range"]
    mask &= (col("ATR5") > lo) & (col("ATR5") <= hi)
    if specification["volume"] is not None:
        mask &= col("観測数量比") >= specification["volume"]
    if specification["rsi_range"] is not None:
        lo, hi = specification["rsi_range"]
        mask &= (col("方向RSI_5分") >= lo) & (col("方向RSI_5分") < hi)
    return mask


def rule_specs(config: dict[str, Any]) -> list[dict[str, Any]]:
    """事前に固定した仮説と格子の全組み合わせを作る。

    引数: config (dict[str, Any]) は探索条件。
    返り値: list[dict[str, Any]] は順序と件数が固定された条件。
    """
    grid = config["固定条件探索"]
    specs = [{"family": "旧群:" + name} for name in grid["対照群"]]
    for family, direction, remaining, atr, volume, rsi in itertools.product(grid["families"], grid["directions"],
                  grid["remaining"], grid["atr_ranges"], grid["volumes"], grid["rsi_ranges"]):
        specs.append({"family": family, "direction": direction, "remaining": remaining,
                      "atr_range": atr, "volume": volume, "rsi_range": rsi})
    return specs


# ----------------------------------------
# 学習期間だけで作るモデルと、候補の共通評価

def train_preprocessing(x: np.ndarray, train: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """学習行だけの中央値で決定木用の欠測を補完する。

    引数: x (np.ndarray) は全特徴、train (np.ndarray) は学習約定行。
    返り値: tuple[np.ndarray, np.ndarray] は変換済み行列と学習中央値。
    """
    medians = []
    for index in range(x.shape[1]):
        values = x[train, index]
        values = values[np.isfinite(values)]
        medians.append(float(np.median(values)) if len(values) else 0.0)
    medians = np.array(medians)
    return np.where(np.isfinite(x), x, medians), medians


def support_ok(train: dict[str, Any], validation: dict[str, Any], config: dict[str, Any]) -> bool:
    """70%という率とは別に、探索候補の最低支持件数を確認する。

    引数: train/validation (dict[str, Any]) は分割集計、config (dict[str, Any]) は基準。
    返り値: bool は両方の最低件数・日数・場数を満たすか。
    """
    for result, prefix in ((train, "学習"), (validation, "条件選択")):
        needed = config["支持条件"][prefix]
        if any(result[key] < needed[key] for key in needed):
            return False
    return True


def target_ok(train: dict[str, Any], validation: dict[str, Any], config: dict[str, Any]) -> bool:
    """探索時点で70%と間引き感度の最低条件をともに満たすか確認する。

    引数: train/validation (dict[str, Any]) は集計、config (dict[str, Any]) は基準。
    返り値: bool は探索上の70%候補であるか。
    """
    return (support_ok(train, validation, config)
            and all(result["確認率"] is not None and result["確認率"] >= config["目標率"] for result in (train, validation))
            and train["30分間引き_約定候補数"] >= 20
            and validation["30分間引き_約定候補数"] >= 10
            and all(result["30分間引き_確認率"] is not None and result["30分間引き_確認率"] >= config["目標率"] for result in (train, validation)))


def tree_path(model: Any, leaf: int, columns: list[str]) -> list[dict[str, Any]]:
    """選択した決定木の葉へ至る価格特徴条件を取り出す。

    引数: model (Any) は学習済み木、leaf (int) は葉ID、columns (list[str]) は許可特徴。
    返り値: list[dict[str, Any]] は葉へ至る不等式。
    """
    tree = model.tree_
    stack = [(0, [])]
    while stack:
        node, conditions = stack.pop()
        if node == leaf:
            return conditions
        if tree.children_left[node] >= 0:
            feature, threshold = columns[tree.feature[node]], float(tree.threshold[node])
            stack.append((int(tree.children_right[node]), conditions + [{"特徴": feature, "比較": ">", "閾値": threshold}]))
            stack.append((int(tree.children_left[node]), conditions + [{"特徴": feature, "比較": "<=", "閾値": threshold}]))
    raise ValueError("葉が見つからない")


# ----------------------------------------
# 後続評価後の選び直し・再評価を、数値入力を読む前に禁止する。

def require_unconfirmed(study: Path, operation: str) -> None:
    """後続結果が存在する試行で、再探索または後続結果の上書きを拒否する。

    引数: study (Path) は試行フォルダ、operation (str) は実行しようとする段階の表示名。
    返り値: None。後続結果.jsonがあればValueErrorにし、新しい試行を要求する。
    """
    if (study / "後続結果.json").exists():
        raise ValueError(f"後続結果.jsonが既に存在するため{operation}は実行できません。条件を変える場合は新しい試行を作成してください。")


# ----------------------------------------
# 学習・条件選択だけによる探索と一候補の固定。

def search(study: Path) -> None:
    """学習・条件選択だけで全候補を比較し、一候補を内容ハッシュ付きで固定する。

    引数: study (Path) は試行フォルダ。
    返り値: None。後続期間のラベル集計や候補選び直しは行わない。
    """
    require_unconfirmed(study, "再探索")
    rows, x, columns, splits, definition, config = load_data(study)
    metrics = load_module(Path(__file__).with_name("評価.py"), "入口探索の評価")
    fill = np.array([row["ラベル"] != "未約定" for row in rows])
    y = np.array([row["ラベル"] == "順行先着" for row in rows], dtype=int)
    train = splits["学習"] & fill
    search_mask = splits["学習"] | splits["条件選択"]
    search_indices = np.flatnonzero(search_mask)
    x_tree, medians = train_preprocessing(x, train)
    dates = np.array([row["場"][:10] for row in rows])
    unique, counts = np.unique(dates[train], return_counts=True)
    day_count = dict(zip(unique, counts))
    weights = np.array([1 / day_count[day] for day in dates[train]])
    weights *= len(weights) / weights.sum()
    parts = {name: [row for row, allowed in zip(rows, mask) if allowed] for name, mask in splits.items() if name != "後続検査"}
    models = WORK / "モデル"
    models.mkdir(exist_ok=True)
    reports, candidates, fitted = [], {}, {}

    def register(identifier: str, specification: dict[str, Any], mask: np.ndarray, complexity: int) -> None:
        """二分割だけの共通評価を追加し、後続ラベルは参照しない。

        引数: identifier (str) は候補ID、specification (dict[str, Any]) は仕様、
        mask (np.ndarray) は許可列、complexity (int) は同率時の複雑さ。
        返り値: None。
        """
        result = {name: metrics.evaluate(parts[name], mask[splits[name]], name) for name in parts}
        supported = support_ok(result["学習"], result["条件選択"], config)
        reached = target_ok(result["学習"], result["条件選択"], config)
        record = {"候補ID": identifier, "種類": specification["kind"], "仕様": json.dumps(specification, ensure_ascii=False),
                  "支持条件": supported, "探索70条件": reached, "複雑さ": complexity}
        for name, values in result.items():
            record.update({name + "_" + key: value for key, value in values.items() if key != "分割"})
        reports.append(record)
        candidates[identifier] = {"specification": specification, "result": result, "mask": mask, "complexity": complexity}

    rule_cache = {}
    for number, rule in enumerate(rule_specs(config)):
        register(f"規則{number:05d}", {"kind": "固定条件", "rule": rule}, family_mask(rows, rule, rule_cache) & search_mask, 6)
        if number % 500 == 0:
            print(f"固定条件 {number}件", flush=True)
    for depth, leaf_size in itertools.product(config["決定木"]["depths"], config["決定木"]["min_samples_leaf"]):
        name = f"木_d{depth}_n{leaf_size}"
        model = DecisionTreeClassifier(max_depth=depth, min_samples_leaf=leaf_size, criterion="log_loss", random_state=config["乱数種"])
        model.fit(x_tree[train], y[train], sample_weight=weights)
        fitted[name] = {"model": model, "medians": medians, "columns": columns, "kind": "決定木"}
        joblib.dump(fitted[name], models / (name + ".joblib"))
        leaves = model.apply(x_tree[search_mask])
        scores = model.predict_proba(x_tree[search_mask])[:, 1]
        for leaf in np.unique(model.apply(x_tree[train])):
            mask = np.zeros(len(rows), dtype=bool)
            mask[search_indices] = leaves == leaf
            register(name + f"_葉{leaf}", {"kind": "決定木の葉", "model": name, "leaf": int(leaf),
                     "conditions": tree_path(model, int(leaf), columns)}, mask, depth)
        for threshold in config["モデル閾値"]:
            mask = np.zeros(len(rows), dtype=bool)
            mask[search_indices] = scores >= threshold
            register(name + f"_率{threshold}", {"kind": "決定木スコア", "model": name, "threshold": threshold}, mask, depth)
        print(name + " 完了", flush=True)
    for leaves, rate in itertools.product(config["勾配木"]["max_leaf_nodes"], config["勾配木"]["learning_rates"]):
        name = f"勾配木_l{leaves}_r{rate}"
        model = HistGradientBoostingClassifier(max_leaf_nodes=leaves, max_depth=3, min_samples_leaf=80,
                    learning_rate=rate, max_iter=150, l2_regularization=1, max_bins=64,
                    early_stopping=False, random_state=config["乱数種"])
        with threadpool_limits(limits=4):
            model.fit(x[train], y[train], sample_weight=weights)
            scores = model.predict_proba(x[search_mask])[:, 1]
            train_scores = model.predict_proba(x[train])[:, 1]
        fitted[name] = {"model": model, "medians": None, "columns": columns, "kind": "勾配木"}
        joblib.dump(fitted[name], models / (name + ".joblib"))
        thresholds = list(config["モデル閾値"]) + [float(np.quantile(train_scores, quantile)) for quantile in config["学習スコア分位点"]]
        for index, threshold in enumerate(thresholds):
            mask = np.zeros(len(rows), dtype=bool)
            mask[search_indices] = scores >= threshold
            register(name + f"_閾値{index}", {"kind": "勾配木スコア", "model": name, "threshold": threshold}, mask, 3)
        print(name + " 完了", flush=True)
    write_csv(study / "全候補_探索.csv", reports)
    supported = [record for record in reports if record["支持条件"]]
    if not supported:
        raise ValueError("最低支持を満たす比較候補がない")
    def order(record: dict[str, Any]) -> tuple:
        """探索の最弱期間、間引き、件数、簡潔さの固定順で順位を作る。

        引数: record (dict[str, Any]) は二分割の集計。
        返り値: tuple は降順順位。
        """
        rate = min(record["学習_確認率"], record["条件選択_確認率"])
        thin = min(record["学習_30分間引き_確認率"] or 0, record["条件選択_30分間引き_確認率"] or 0)
        return (int(record["探索70条件"]), rate, thin, record["条件選択_約定候補数"], -record["複雑さ"])
    supported.sort(key=order, reverse=True)
    chosen = supported[0]
    identifier = chosen["候補ID"]
    candidate = candidates[identifier]
    specification = candidate["specification"]
    if "model" in specification:
        shutil.copyfile(models / (specification["model"] + ".joblib"), study / "選択モデル.joblib")
    write_csv(study / "上位候補_探索.csv", supported[:50])
    selected_rows = [row for row, allowed in zip(rows, candidate["mask"]) if allowed]
    keep = ("イベントID", "場", "方向", "要求時計JST", "新規時計JST", "新規価格", "ラベル", "理由", "逆行線", "順行線", "最大順行pt", "最大逆行pt")
    write_csv(study / "選択事例_探索.csv", [{key: row[key] for key in keep} for row in selected_rows])
    write_json(study / "特徴定義.json", definition)
    for filename in ("ラベル準備メタ.json", "独立照合結果.json", "特徴照合結果.json", "生成照合結果.json", "合成検証結果.json"):
        if (WORK / filename).exists():
            shutil.copyfile(WORK / filename, study / filename)
    lock_files = [Path(__file__), Path(__file__).with_name("評価.py"), Path(__file__).with_name("特徴生成.py"),
                  Path(__file__).with_name("ラベル準備.py"), study / "条件.json", study / "計画.md",
                  WORK / "入口250_125.csv", WORK / "特徴.csv", WORK / "特徴定義.json"]
    if (study / "選択モデル.joblib").exists():
        lock_files.append(study / "選択モデル.joblib")
    selected = {"固定日時": datetime.now(JST).isoformat(), "候補ID": identifier, "仕様": specification,
                "探索結果": candidate["result"], "探索候補数": len(reports), "支持候補数": len(supported),
                "探索70候補数": sum(record["探索70条件"] for record in reports),
                "選択理由": "探索70条件を優先し、学習/選択の低い確認率、間引き確認率、選択件数、簡潔さの順。未達時は診断用に一候補を固定。",
                "後続状態": "未評価。全期間は既使用だが、この探索では後続結果を選択に使わない。",
                "Python": sys.version.split()[0], "NumPy": np.__version__, "scikit-learn": sklearn.__version__,
                "ファイルSHA256": {path.relative_to(ROOT).as_posix(): sha(path) for path in lock_files}}
    write_json(study / "選択固定.json", selected)
    write_json(study / "探索結果.json", {key: value for key, value in selected.items() if key != "ファイルSHA256"})
    print(json.dumps({"選択": identifier, "探索候補数": len(reports), "支持候補数": len(supported),
                      "70候補数": selected["探索70候補数"], "仕様": specification,
                      "学習": candidate["result"]["学習"], "条件選択": candidate["result"]["条件選択"]}, ensure_ascii=False), flush=True)


# ----------------------------------------
# 一候補を固定した後だけ開く、既使用データ内の後続検査

def confirm(study: Path) -> None:
    """固定内容を検査し、選んだ一候補だけの後続期間を集計する。

    引数: study (Path) は探索を終えた試行。
    返り値: None。後続結果で候補や閾値を選び直さない。
    """
    require_unconfirmed(study, "後続評価の再実行")
    lock = json.loads((study / "選択固定.json").read_text(encoding="utf-8"))
    for relative, expected in lock["ファイルSHA256"].items():
        if sha(ROOT / relative) != expected:
            raise ValueError(f"固定後に変更された: {relative}")
    rows, x, columns, splits, _, config = load_data(study)
    metrics = load_module(Path(__file__).with_name("評価.py"), "後続の入口評価")
    specification = lock["仕様"]
    if specification["kind"] == "固定条件":
        allowed = family_mask(rows, specification["rule"])
    else:
        bundle = joblib.load(study / "選択モデル.joblib")
        if bundle["columns"] != columns:
            raise ValueError("選択モデルの特徴列不一致")
        model = bundle["model"]
        values = x if bundle["medians"] is None else np.where(np.isfinite(x), x, bundle["medians"])
        if "leaf" in specification:
            allowed = model.apply(values) == specification["leaf"]
        else:
            with threadpool_limits(limits=4):
                allowed = model.predict_proba(values)[:, 1] >= specification["threshold"]
    reports, dates = {}, []
    for name, mask in splits.items():
        part = [row for row, included in zip(rows, mask) if included]
        part_allowed = allowed[mask]
        reports[name] = metrics.evaluate(part, part_allowed, name)
        dates.extend({"分割": name, **row} for row in metrics.group_by_day(part, part_allowed))
    check = reports["後続検査"]
    support = all(check[key] >= value for key, value in config["支持条件"]["後続検査"].items())
    target = (lock["探索70候補数"] > 0 and support and check["確認率"] is not None and check["確認率"] >= config["目標率"]
              and check["30分間引き_約定候補数"] >= 10 and check["30分間引き_確認率"] is not None and check["30分間引き_確認率"] >= config["目標率"])
    bootstrap_rows = [row for row, included in zip(rows, splits["後続検査"]) if included]
    bootstrap = metrics.date_bootstrap(bootstrap_rows, allowed[splits["後続検査"]], seed=config["乱数種"], draws=2000)
    write_json(study / "後続結果.json", {"候補ID": lock["候補ID"], "評価日時": datetime.now(JST).isoformat(),
               "結果": reports, "後続支持条件": support, "探索と後続の70条件": target,
               "日別再標本": bootstrap, "解釈": "全期間が既使用。探索条件を満たしても将来勝率70%の保証ではない。",
               "選択固定SHA256": sha(study / "選択固定.json")})
    write_csv(study / "選択候補_期間比較.csv", [{"候補ID": lock["候補ID"], **report} for report in reports.values()])
    write_csv(study / "日別結果.csv", dates)
    kept = ("イベントID", "場", "方向", "要求時計JST", "新規時計JST", "新規価格", "ラベル", "理由", "逆行線", "順行線", "最大順行pt", "最大逆行pt")
    write_csv(study / "後続事例.csv", [{key: row[key] for key in kept} for row, permitted in zip(rows, allowed & splits["後続検査"]) if permitted])
    print(json.dumps({"候補ID": lock["候補ID"], "後続": check, "70条件": target}, ensure_ascii=False), flush=True)


def main() -> None:
    """実行段階を分離し、確認前の一候補固定を必須にする。

    引数: なし。argparseでstudy/phaseを取得する。
    返り値: None。
    """
    parser = argparse.ArgumentParser(description="NK225の250/125で70%を探索する")
    parser.add_argument("--study", required=True, type=Path)
    parser.add_argument("--phase", choices=("探索", "後続"), default="探索")
    args = parser.parse_args()
    study = args.study.resolve()
    search(study) if args.phase == "探索" else confirm(study)


if __name__ == "__main__":
    main()
