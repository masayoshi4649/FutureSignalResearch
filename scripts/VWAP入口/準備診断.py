"""保存済みの価格足と価格Pから、VWAP共通準備・確認遅延による入口集合差を診断する。"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
import gzip
import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT/"study/00018_VWAPの位置と傾きで順行反転を比較"
WORK = ROOT/"work/VWAP入口/00018"
PERIODS = ("学習", "条件選択", "後続検査")
STATE_REASONS = {"同場四点未準備", "四点nativeまたはepoch不成立"}
DELAY_REASON = "価格足確認遅延30秒超"


def sha(path: Path) -> str:
    """保存ファイルの指紋を返す。

    引数: path (Path) は入力。
    返り値: str はSHA256。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(name: str, artifacts: dict) -> tuple[list[dict], str]:
    """正式展開SHAを検査して作業JSONLだけを読む。

    引数: name (str) はgzip名、artifacts (dict) は正式成果物台帳。
    返り値: tuple[list[dict],str] は保存行と展開SHA。原板や運用エンジンは読まない。
    """
    matches = [r for r in artifacts["ファイル"] if Path(r["パス"]).name == name]
    if len(matches) != 1:
        raise ValueError("正式展開指紋の対応が一意でない")
    digest, rows = hashlib.sha256(), []
    with gzip.open(WORK/name, "rb") as stream:
        for raw in stream:
            digest.update(raw)
            if raw.strip():
                rows.append(json.loads(raw))
    if digest.hexdigest() != matches[0]["展開内容SHA256"]:
        raise ValueError("正式展開SHA不一致: "+name)
    return rows, digest.hexdigest()


class Audit:
    """診断の集合対応と分母分解を確認する。"""

    def __init__(self) -> None:
        """比較件数と不一致を初期化する。

        引数: なし。
        返り値: None。
        """
        self.count, self.errors = 0, []

    def check(self, name: str, actual: Any, expected: Any) -> None:
        """一致を数え、不一致だけを保存する。

        引数: name (str) は項目、actual/expected (Any) は比較値。
        返り値: None。集合の不一致は全生データを保存せず先頭だけ残す。
        """
        self.count += 1
        if actual != expected:
            if isinstance(actual, set) and isinstance(expected, set):
                value = {"不足": sorted(expected-actual)[:10], "余分": sorted(actual-expected)[:10]}
            else:
                value = {"実際": actual, "期待": expected}
            self.errors.append({"項目": name, **value})


def reason_counts(reasons: list[str], target: Counter) -> None:
    """同一行の理由重複を除き、理由別の行件数を加える。

    引数: reasons (list[str]) は理由、target (Counter) は集計先。
    返り値: None。異なる理由間の重複は残す。
    """
    target.update(set(reasons))


def current_reasons(row: dict) -> list[str]:
    """N共通助走の状態理由を外し、現在足の不可理由だけを得る。

    引数: row (dict) は保存足または価格発動。
    返り値: list[str] は数値/時計/identity/公開・遅延等の理由。
    """
    return sorted(set(row["N除外理由"])-STATE_REASONS)


def foot_group(rows: list[dict], audit: Audit) -> dict:
    """価格足のnative原値と足遅延・四点助走を分けて数える。

    引数: rows (list[dict]) は同尺度同期間の保存足、audit (Audit) は比較先。
    返り値: dict は足数と理由別件数。native有効flagが遅延を含む点を明示する。
    """
    counts = Counter({k: 0 for k in ("足数", "公開足数", "非公開足数", "公開かつ確認遅延30秒超足数",
        "公開かつ確認遅延30秒以内足数", "native有効flag足数", "現在補助観測だけならnative条件成立足数",
        "確認遅延だけでnative有効flag不可の足数", "確認遅延と補助観測不可の重複足数",
        "現在補助観測にも不可理由がある足数", "内部比率の数値差が許容超の足数",
        "内部比率が未定義の足数", "N共通準備足数", "D共通準備足数", "native有効だがN助走未準備足数")})
    current, state, source, delayed = Counter(), Counter(), Counter(), Counter()
    for row in rows:
        counts["足数"] += 1
        published = bool(row["publish"])
        is_delayed = published and row["confirm"]-row["end"] > 30
        ref = row["補助参照"]
        source_reasons = ref["現在不可理由"] if ref is not None else []
        source_valid = ref is not None and not source_reasons
        counts["公開足数" if published else "非公開足数"] += 1
        counts["公開かつ確認遅延30秒超足数"] += int(is_delayed)
        counts["公開かつ確認遅延30秒以内足数"] += int(published and not is_delayed)
        counts["native有効flag足数"] += int(row["native有効"])
        counts["現在補助観測だけならnative条件成立足数"] += int(source_valid)
        counts["確認遅延だけでnative有効flag不可の足数"] += int(is_delayed and source_valid and not row["native有効"])
        counts["確認遅延と補助観測不可の重複足数"] += int(is_delayed and ref is not None and bool(source_reasons))
        counts["現在補助観測にも不可理由がある足数"] += int(ref is not None and bool(source_reasons))
        if ref is not None:
            error = ref["内部絶対差pt"]
            counts["内部比率の数値差が許容超の足数"] += int(error is not None and error > .00010001)
            counts["内部比率が未定義の足数"] += int(error is None)
        counts["N共通準備足数"] += int(row["N共通準備"])
        counts["D共通準備足数"] += int(row["D共通準備"])
        counts["native有効だがN助走未準備足数"] += int(row["native有効"] and not row["N共通準備"])
        reason_counts(current_reasons(row), current)
        reason_counts([r for r in row["N除外理由"] if r in STATE_REASONS], state)
        reason_counts(source_reasons, source)
        reason_counts([r for r in current_reasons(row) if r == DELAY_REASON], delayed)
        audit.check(str((row["場"], row["時間足分"], row["index"]))+":Nは現在nativeを要求",
                    not row["N共通準備"] or row["native有効"], True)
        audit.check(str((row["場"], row["時間足分"], row["index"]))+":DはNを要求",
                    not row["D共通準備"] or row["N共通準備"], True)
    audit.check("足分母分解", counts["足数"], counts["公開足数"]+counts["非公開足数"])
    audit.check("公開足遅延分解", counts["公開足数"],
                counts["公開かつ確認遅延30秒超足数"]+counts["公開かつ確認遅延30秒以内足数"])
    return {**dict(counts), "現在native不可理由": dict(current), "N履歴準備理由": dict(state),
            "現在補助観測の不可理由": dict(source), "足の確認遅延理由": dict(delayed)}


def price_group(rows: list[dict], cases: list[dict], audit: Audit, name: str) -> dict:
    """価格P全数から遅延とN/D共通準備、保存対照ケースへの対応を数える。

    引数: rows/cases (list[dict]) は同尺度系統期間の価格発動/保存入口、audit (Audit) は比較先、name (str) は識別名。
    返り値: dict は位置条件の前で生じた集合差。先着ラベルや損益を集計しない。
    """
    counts = Counter({k: 0 for k in ("価格P全数", "P確認遅延30秒超数", "P確認遅延30秒以内数",
        "全PからN通過数", "全PからN除外数", "全PからD通過数", "全PからD除外数",
        "遅延以内PからN通過数", "遅延以内PからN除外数", "遅延以内PからD通過数", "遅延以内PからD除外数",
        "現在native有効P数", "現在native有効だがN助走未準備P数", "遅延のみでnative有効flag不可のP数",
        "現在補助観測にも不可理由があるP数", "内部比率の数値差が許容超のP数", "内部比率が未定義のP数")})
    n_reasons, d_reasons, n_state, n_current = Counter(), Counter(), Counter(), Counter()
    within_n_reasons, within_d_reasons = Counter(), Counter()
    expected = {"N_A": set(), "D_A": set()}
    for row in rows:
        price = row["元価格信号"]
        is_delayed = price["確認遅延秒"] > 30
        counts["価格P全数"] += 1
        counts["P確認遅延30秒超数" if is_delayed else "P確認遅延30秒以内数"] += 1
        for mask, setting in (("N", "N_A"), ("D", "D_A")):
            passed = bool(row[mask+"共通準備"])
            counts[f"全Pから{mask}通過数" if passed else f"全Pから{mask}除外数"] += 1
            if not is_delayed:
                counts[f"遅延以内Pから{mask}通過数" if passed else f"遅延以内Pから{mask}除外数"] += 1
            if passed:
                expected[setting].add(row["価格イベントID"])
            audit.check(name+row["価格イベントID"]+":"+setting, row["通過設定"][setting], passed)
            if is_delayed:
                audit.check(name+row["価格イベントID"]+":遅延超は"+mask+"不可", passed, False)
        counts["現在native有効P数"] += int(row["native有効"])
        counts["現在native有効だがN助走未準備P数"] += int(row["native有効"] and not row["N共通準備"])
        ref = row["補助参照"]
        source_reasons = ref["現在不可理由"] if ref is not None else []
        source_valid = ref is not None and not source_reasons
        counts["遅延のみでnative有効flag不可のP数"] += int(is_delayed and source_valid and not row["native有効"])
        counts["現在補助観測にも不可理由があるP数"] += int(ref is not None and bool(source_reasons))
        if ref is not None:
            error = ref["内部絶対差pt"]
            counts["内部比率の数値差が許容超のP数"] += int(error is not None and error > .00010001)
            counts["内部比率が未定義のP数"] += int(error is None)
        if not row["N共通準備"]:
            reason_counts(row["N除外理由"], n_reasons)
            reason_counts([r for r in row["N除外理由"] if r in STATE_REASONS], n_state)
            reason_counts(current_reasons(row), n_current)
            if not is_delayed:
                reason_counts(row["N除外理由"], within_n_reasons)
        if not row["D共通準備"]:
            reason_counts(row["D除外理由"], d_reasons)
            if not is_delayed:
                reason_counts(row["D除外理由"], within_d_reasons)
    actual_counts = {}
    for setting in ("N_A", "D_A"):
        selected = [r for r in cases if r["補助"] == setting]
        actual = {r["価格イベントID"] for r in selected}
        audit.check(name+":"+setting+"保存case一意", len(actual), len(selected))
        audit.check(name+":"+setting+"全Pとの集合対応", actual, expected[setting])
        actual_counts[setting+"保存case数"] = len(selected)
    audit.check(name+":全P遅延分母", counts["価格P全数"], counts["P確認遅延30秒超数"]+counts["P確認遅延30秒以内数"])
    for mask in ("N", "D"):
        audit.check(name+":"+mask+"全P分母", counts["価格P全数"], counts[f"全Pから{mask}通過数"]+counts[f"全Pから{mask}除外数"])
        audit.check(name+":"+mask+"遅延以内分母", counts["P確認遅延30秒以内数"],
                    counts[f"遅延以内Pから{mask}通過数"]+counts[f"遅延以内Pから{mask}除外数"])
    return {**dict(counts), **actual_counts, "N除外理由_全P": dict(n_reasons),
            "D除外理由_全P": dict(d_reasons), "N除外の現在理由": dict(n_current),
            "N除外の履歴状態理由": dict(n_state), "N除外理由_遅延以内P": dict(within_n_reasons),
            "D除外理由_遅延以内P": dict(within_d_reasons)}


def totals(rows: list[dict]) -> dict:
    """診断群の件数と理由別件数だけを合計する。

    引数: rows (list[dict]) は同じschemaの集計。
    返り値: dict は期間/尺度/系統の識別列を除く合計。
    """
    counts, reasons = Counter(), defaultdict(Counter)
    for row in rows:
        for key, value in row.items():
            if key in ("時間足分", "期間", "系統"):
                continue
            if isinstance(value, int):
                counts[key] += value
            elif isinstance(value, dict):
                reasons[key].update(value)
    return {**dict(counts), **{k: dict(v) for k, v in reasons.items()}}


# ----------------------------------------
# 保存足/P/caseの指紋と集合を照合し、数値再生をせず診断を正式保存する。

def main() -> None:
    """全三尺度・三期間・二系統の準備差を正式JSONへ保存する。

    引数: なし。固定00018の保存成果物だけを読む。
    返り値: None。損益・先着の再計算とcore/結果の変更は行わない。
    """
    artifacts = json.loads((STUDY/"作業成果物.json").read_text(encoding="utf-8"))
    feet, feet_sha = load("全足参照.jsonl.gz", artifacts)
    prices, price_sha = load("価格発動.jsonl.gz", artifacts)
    cases, cases_sha = load("入口事例.jsonl.gz", artifacts)
    audit = Audit()
    indexed = {(r["場"], r["時間足分"], r["index"]): r for r in feet}
    audit.check("保存足の場尺度番号一意", len(indexed), len(feet))
    audit.check("全価格イベント一意", len({r["価格イベントID"] for r in prices}), len(prices))
    for row in prices:
        p = row["元価格信号"]
        foot = indexed[(row["場"], row["時間足分"], p["index"])]
        for field in ("native有効", "N共通準備", "D共通準備", "N除外理由", "D除外理由", "補助参照"):
            audit.check(row["価格イベントID"]+":足P属性:"+field, row[field], foot[field])
        audit.check(row["価格イベントID"]+":確認遅延", p["確認遅延秒"], foot["confirm"]-foot["end"])
    foot_rows, price_rows = [], []
    for size in (1, 3, 5):
        for period in PERIODS:
            own = [r for r in feet if r["時間足分"] == size and r["期間"] == period]
            foot_rows.append({"時間足分": size, "期間": period, **foot_group(own, audit)})
            for family in ("T1", "R2"):
                own_p = [r for r in prices if r["時間足分"] == size and r["期間"] == period and r["元価格信号"]["入口系統"] == family]
                own_c = [r for r in cases if r["時間足分"] == size and r["期間"] == period and r["入口系統"] == family]
                price_rows.append({"時間足分": size, "期間": period, "系統": family,
                                   **price_group(own_p, own_c, audit, f"{size}分:{period}:{family}")})
    locked = json.loads((STUDY/"固定.json").read_text(encoding="utf-8"))
    for name, expected in locked["ファイルSHA256"].items():
        audit.check("固定後SHA:"+name, sha(ROOT/name), expected)
    result = {"全件一致": not audit.errors, "照合項目数": audit.count, "不一致数": len(audit.errors), "不一致": audit.errors,
              "確認日時": datetime.now(timezone(timedelta(hours=9))).isoformat(),
              "コードSHA256": sha(Path(__file__)), "結果SHA256": sha(STUDY/"結果.json"),
              "全足参照展開SHA256": feet_sha, "価格発動展開SHA256": price_sha, "入口事例展開SHA256": cases_sha,
              "保存足数": len(feet), "保存価格P数": len(prices), "足別群数": len(foot_rows), "価格P群数": len(price_rows),
              "全体足集計": totals(foot_rows), "全体価格P集計": totals(price_rows),
              "尺度期間別の足": foot_rows, "尺度期間系統別の価格P": price_rows,
              "分母の定義": "価格Pは旧11価格発動の全数。N_A/D_Aは位置条件を加える前に共通準備だけで選別された部分集合。遅延超Pと遅延以内PのN/D除外を分ける。",
              "native有効flagの定義": "公開判断時点の補助観測条件に加えて、価格足の確認遅延30秒以内を含む。flag不可は配信VWAPの数値不整合とは同義でない。補助参照内の現在不可理由と内部絶対差を別集計。",
              "理由の数え方": "各行内は理由重複を除くが、異なる理由間の重複は許す。理由別件数の和を除外行数としない。Nの二つの四点準備理由は現在値の理由から分けた。",
              "限界": "保存足/P/caseの集計と集合対応の診断。原市場データ・入口・先着・運用損益は再生しない。位置・傾き条件の収益効果を証明せず、共通助走と遅延で母集団が変わることを示す。"}
    (STUDY/"準備診断.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False)+"\n", encoding="utf-8")
    print(json.dumps({"全件一致": not audit.errors, "照合項目数": audit.count,
                      "不一致数": len(audit.errors), "足数": len(feet), "P数": len(prices),
                      "P全体": result["全体価格P集計"]}, ensure_ascii=False))
    if audit.errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
