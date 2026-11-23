"""再生エンジンから独立し、Viewer約定とCSVの会計・帰属・時刻を照合する。"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
import hashlib
import json
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
JST = timezone(timedelta(hours=9))
ZERO = Decimal(0)
ONE = Decimal(1)


# ----------------------------------------
# 数値・時刻・参照台帳を独立に読み取る

def 数値(value: Any) -> Decimal:
    """JSONとCSVの数値を二進浮動小数点の計算を経ずDecimalへ変換する。

    引数: value (Any) は整数・Decimal・数値文字列等。
    返り値: Decimal は有限の十進数。不正値はValueErrorにする。
    """
    if isinstance(value, bool):
        raise ValueError("真偽値は数値として採用しない")
    result = Decimal(str(value))
    if not result.is_finite():
        raise ValueError(f"有限でない数値: {value}")
    return result


def 時刻(value: str) -> datetime:
    """時差付きISO日時を読み、JSTへ正規化する。

    引数: value (str) はRFC3339互換の日時文字列。
    返り値: datetime は時差付きJST日時。時差のない値はValueErrorにする。
    """
    result = datetime.fromisoformat(value)
    if result.utcoffset() is None:
        raise ValueError(f"時差なし日時: {value}")
    return result.astimezone(JST)


def 秒数(value: datetime) -> Decimal:
    """日時をマイクロ秒精度の十進Unix秒へ変換する。

    引数: value (datetime) は時差付き日時。
    返り値: Decimal はUnix秒。
    """
    delta = value - datetime(1970, 1, 1, tzinfo=timezone.utc)
    return Decimal(delta.days * 86400 + delta.seconds) + Decimal(delta.microseconds) / Decimal(1000000)


def ハッシュ(path: Path) -> str:
    """ファイルを小さな塊で読みSHA256を求める。

    引数: path (Path) は対象。
    返り値: str はSHA256の16進表記。
    """
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def JSONを読む(path: Path) -> Any:
    """JSONの小数をDecimalとして読み込む。

    引数: path (Path) はUTF-8のJSON。
    返り値: Any は解析した値。
    """
    return json.loads(path.read_text(encoding="utf-8-sig"), parse_float=Decimal)


def CSVを読む(path: Path) -> list[dict[str, str]]:
    """小集計CSVを文字列のまま読み込む。

    引数: path (Path) はUTF-8のCSV。
    返り値: list[dict[str, str]] は行一覧。空ファイルは空配列。
    """
    with path.open(encoding="utf-8-sig", newline="") as source:
        return list(csv.DictReader(source))


def 設定を探す(study: Path, explicit: Path | None) -> Path:
    """明示設定または成果物の親階層にある条件JSONを探す。

    引数: study (Path) は成果物、explicit (Path | None) は指定された条件JSON。
    返り値: Path は実在する条件ファイル。不明ならFileNotFoundErrorにする。
    """
    if explicit is not None:
        return explicit.resolve(strict=True)
    for folder in (study, *study.parents):
        candidate = folder / "条件.json"
        if candidate.is_file():
            return candidate
    raise FileNotFoundError("成果物または親に条件.jsonがありません")


def 台帳を読む(path: Path, visited: set[Path] | None = None) -> tuple[dict[str, Any], Path]:
    """SHA256付きの小参照JSONを解決し、共有する入力台帳を読む。

    引数: path (Path) は台帳または参照JSON、visited (set[Path] | None) は循環検出用。
    返り値: tuple[dict[str, Any], Path] は実体と、そのファイルの絶対パス。
    """
    path = path.resolve(strict=True)
    seen = set() if visited is None else visited
    if path in seen:
        raise ValueError(f"入力台帳の循環参照: {path}")
    seen.add(path)
    result = JSONを読む(path)
    if "参照" in result:
        target = (path.parent / result["参照"]).resolve(strict=True)
        if ハッシュ(target) != result["SHA256"]:
            raise ValueError(f"参照台帳のハッシュ不一致: {target}")
        return 台帳を読む(target, seen)
    if not isinstance(result.get("entries"), list):
        raise ValueError(f"入力台帳にentriesがありません: {path}")
    return result, path


def 場の時刻(session: str, config: dict[str, Any]) -> tuple[datetime, datetime, datetime, datetime]:
    """注文エンジンを呼ばずに開始・ザラバ終了・新規停止・返済要求を求める。

    引数: session (str) は開始日基準の場名、config (dict[str, Any]) は条件。
    返り値: tuple[datetime, datetime, datetime, datetime] はJSTの四時刻。
    """
    date_text, part = session.split("_")
    date = datetime.fromisoformat(date_text).replace(tzinfo=JST)
    if part not in ("Day", "Night"):
        raise ValueError(f"未知の場名: {session}")
    following = date + timedelta(days=part == "Night")
    start = date.replace(hour=8, minute=45) if part == "Day" else date.replace(hour=17)
    end = date.replace(hour=15, minute=40) if part == "Day" else following.replace(hour=5, minute=55)
    cutoff_hour, cutoff_minute = map(int, config["新規停止"][part].split(":"))
    force_hour, force_minute = map(int, config["全返済要求"][part].split(":"))
    return (start, end, following.replace(hour=cutoff_hour, minute=cutoff_minute),
            following.replace(hour=force_hour, minute=force_minute))


# ----------------------------------------
# 混在台帳の帰属と、Decimalの独立会計

class 独立監査:
    """約定の新規帰属を保持し、各資源の一建玉と会計を照合する。"""

    def __init__(self) -> None:
        """エラーと照合件数を初期化する。

        引数: なし。
        返り値: None。
        """
        self.errors: list[str] = []
        self.checks = 0
        self.fills = 0
        self.closed = 0
        self.cache_checks = 0

    def 確認(self, condition: bool, message: str) -> None:
        """不一致を蓄積し、後続の独立照合を続ける。

        引数: condition (bool) は成立すべき条件、message (str) は不一致の説明。
        返り値: None。
        """
        self.checks += 1
        if not condition:
            self.errors.append(message)

    def 同値(self, observed: Any, expected: Any, message: str) -> None:
        """有限数値をDecimalで比較する。

        引数: observed/expected (Any) は照合値、message (str) は検査対象。
        返り値: None。
        """
        left, right = 数値(observed), 数値(expected)
        self.確認(left == right, f"{message}: {left} / 期待 {right}")

    def ファイルを監査(self, path: Path, resources: list[dict[str, Any]], config: dict[str, Any],
                  input_entry: dict[str, Any], trade_rows: dict[tuple, dict[str, str]],
                  cache_root: Path | None) -> tuple[dict[str, dict[str, Any]], set[tuple]]:
        """混在約定ファイルを一度読み、新規method_idによる帰属で会計を作る。

        引数: path (Path) は約定、resources (list[dict[str, Any]]) は同じファイルを使う資源、
        config/input_entry (dict[str, Any]) は条件と入力台帳、trade_rows (dict[tuple, dict[str, str]]) は取引CSV、
        cache_root (Path | None) は追加照合するキャッシュ親。
        返り値: tuple[dict[str, dict[str, Any]], set[tuple]] は手法別会計と照合済み取引キー。
        """
        first = resources[0]
        symbol, session = first["symbol"], first["session"]
        product = config["商品"][symbol]
        point, tick, fee = (数値(product[key]) for key in ("point_value", "tick", "fee_yen"))
        self.確認(point > ZERO and tick > ZERO and fee >= ZERO, f"{symbol}: 商品条件が不正")
        start, end, cutoff, force = 場の時刻(session, config)
        methods = {resource.get("entry_method_id", resource["method_id"]) for resource in resources}
        accounts = {method: {"cash": ZERO, "gross": ZERO, "fees": ZERO, "count": 0,
                             "open": 0, "fills": 0} for method in methods}
        for resource in resources:
            prefix = f"{resource['id']}: "
            self.確認((resource["symbol"], resource["session"]) == (symbol, session), prefix + "同ファイルの指数・場が不一致")
            self.確認(resource["product"] == product["product"], prefix + "実行商品が条件と不一致")
            self.同値(resource["point_value"], point, prefix + "倍率")
            self.確認(resource.get("pnl_format") == "trades" and resource.get("pnl_basis") == "net", prefix + "損益形式")
            self.確認(resource.get("market_path") == input_entry["source_path"], prefix + "原板の参照先")
        records = [json.loads(line, parse_float=Decimal) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        cache = self.キャッシュを読む(cache_root, input_entry, records) if cache_root is not None else None
        ids, positions, active, matched = set(), {}, {}, set()
        previous_key = None
        rules = {rule["名前"]: rule for rule in config["候補"]}
        for index, fill in enumerate(records, 1):
            label = f"{path.name}:{index}"
            stamp, line = 時刻(fill["timestamp"]), int(fill["source_line"])
            key = (stamp, line)
            self.確認(previous_key is None or key >= previous_key, label + "約定の時刻・原行が非減少でない")
            previous_key = key
            self.確認(start <= stamp < end, label + "ザラバの場内時刻でない")
            self.確認(isinstance(fill["source_line"], int) and not isinstance(fill["source_line"], bool)
                    and 1 <= line <= int(input_entry["raw_lines"]), label + "原行が範囲外")
            self.確認(isinstance(fill["id"], str) and bool(fill["id"]), label + "空または非文字列の約定ID")
            self.確認(fill["id"] not in ids, label + "約定IDの重複")
            ids.add(fill["id"])
            self.同値(fill["qty"], ONE, label + "枚数")
            price, actual_fee = 数値(fill["price"]), 数値(fill.get("fee_yen", 0))
            self.確認(price > ZERO and price % tick == ZERO, label + "価格が正の呼値刻みでない")
            self.同値(actual_fee, fee, label + "片道手数料")
            kind = fill["type"]
            if kind not in ("LongN", "ShortN", "LongR", "ShortR"):
                self.確認(False, label + "未知の約定型")
                continue
            side, is_entry = (1 if kind.startswith("Long") else -1), kind.endswith("N")
            position_id = fill["position_id"]
            self.確認(isinstance(position_id, str) and bool(position_id), label + "空または非文字列の建玉ID")
            if cache is not None:
                self.板を照合(fill, cache, side, is_entry, label)
            if is_entry:
                method = fill.get("method_id")
                self.確認(method in methods, label + "新規手法に対応するViewer資源がない")
                if method not in methods:
                    continue
                self.確認(position_id not in positions, label + "建玉IDの再使用")
                self.確認(method not in active, label + "同一候補に複数建玉")
                self.確認(stamp < cutoff, label + "新規停止時刻以後の新規")
                positions[position_id] = {"method": method, "side": side, "price": price,
                                          "fee": actual_fee, "time": stamp, "line": line, "closed": False}
                active[method] = position_id
                accounts[method]["cash"] -= actual_fee
            else:
                self.確認(position_id in positions, label + "対応する新規がない返済")
                if position_id not in positions:
                    continue
                pos = positions[position_id]
                method = pos["method"]
                self.確認(not pos["closed"], label + "同じ建玉の二重返済")
                self.確認(pos["side"] == side, label + "新規・返済の方向不一致")
                self.確認(fill.get("method_id", method) == method, label + "返済method_idと新規帰属が不一致")
                self.確認(stamp > pos["time"] and line > pos["line"], label + "新規より後の返済でない")
                gross = Decimal(side) * (price - pos["price"]) * point
                total_fee = pos["fee"] + actual_fee
                net = gross - total_fee
                accounts[method]["cash"] += gross - actual_fee
                accounts[method]["gross"] += gross
                accounts[method]["count"] += 1
                trade_key = (symbol, session, method, position_id)
                self.確認(trade_key in trade_rows, label + "取引集計CSVに対応行がない")
                if trade_key in trade_rows:
                    row = trade_rows[trade_key]
                    self.取引を照合(row, pos, fill, gross, total_fee, net, tick, rules[method], force, label)
                    matched.add(trade_key)
                pos["closed"] = True
                active.pop(method, None)
                self.closed += 1
            accounts[method]["fees"] += actual_fee
            accounts[method]["fills"] += 1
            self.fills += 1
        for method, account in accounts.items():
            account["open"] = sum(not pos["closed"] and pos["method"] == method for pos in positions.values())
            self.確認(account["open"] == 0, f"{symbol}/{session}/{method}: 終了建玉が残る")
        return accounts, matched

    def 取引を照合(self, row: dict[str, str], pos: dict[str, Any], fill: dict[str, Any],
               gross: Decimal, fee: Decimal, net: Decimal, tick: Decimal,
               rule: dict[str, Any], force: datetime, label: str) -> None:
        """完結取引とCSVの価格・費用・損益・原行・記録遅延を照合する。

        引数: row (dict[str, str]) は取引CSV、pos/fill (dict[str, Any]) は新規と返済、
        gross/fee/net/tick (Decimal) は会計値と呼値、rule (dict[str, Any]) は候補、
        force (datetime) は返済要求時刻、label (str) は検査対象。
        返り値: None。
        """
        self.確認(row["方向"] == ("買い" if pos["side"] == 1 else "売り"), label + "CSV方向")
        self.確認(時刻(row["新規時刻"]) == pos["time"], label + "CSV新規時刻")
        self.確認(時刻(row["返済時刻"]) == 時刻(fill["timestamp"]), label + "CSV返済時刻")
        expected = {"数量": ONE, "新規価格": pos["price"], "返済価格": fill["price"],
                    "値幅損益円": gross, "手数料円": fee, "純損益円": net,
                    "新規原板行": pos["line"], "返済原板行": fill["source_line"],
                    "保有秒": 秒数(時刻(fill["timestamp"])) - 秒数(pos["time"])}
        for key, value in expected.items():
            self.同値(row[key], value, label + "CSV " + key)
        entry_delay, exit_delay = 数値(row["判断から新規秒"]), 数値(row["要求から返済秒"])
        self.確認(ONE <= entry_delay <= Decimal(30), label + "記録された新規待ちが1～30秒でない")
        self.確認(exit_delay >= ONE, label + "記録された返済待ちが1秒未満")
        if 時刻(fill["timestamp"]) >= force:
            self.確認(row["返済理由"] == "期限返済", label + "期限後の返済理由")
        stop = pos["price"] - Decimal(pos["side"]) * 数値(rule.get("保護ATR倍", 2)) * 数値(row["入口ATR"])
        rounding = ROUND_FLOOR if pos["side"] == 1 else ROUND_CEILING
        stop = (stop / tick).to_integral_value(rounding=rounding) * tick
        if rule.get("追尾ATR倍"):
            final_stop = 数値(row["保護価格"])
            self.確認(final_stop % tick == ZERO, label + "最終追尾価格の呼値")
            self.確認(Decimal(pos["side"]) * (final_stop - stop) >= ZERO, label + "追尾が初期保護より不利側")
        else:
            self.同値(row["保護価格"], stop, label + "入口固定の保護価格")

    def キャッシュを読む(self, cache_root: Path, entry: dict[str, Any], fills: list[dict[str, Any]]) -> dict[int, tuple]:
        """必要な原行だけをキャッシュから取り、内容ハッシュも検証する。

        引数: cache_root (Path) はキャッシュ親、entry (dict[str, Any]) は入力台帳、
        fills (list[dict[str, Any]]) は照合対象。
        返り値: dict[int, tuple] は原行から価格時計・両気配・正常フラグへの対応。
        """
        import numpy as np

        path = cache_root / entry["cache_path"]
        self.確認(ハッシュ(path) == entry["sha256_cache"], f"{path}: キャッシュSHA256")
        wanted = {int(fill["source_line"]) for fill in fills}
        result = {}
        with np.load(path, allow_pickle=False) as data:
            for index, line in enumerate(data["line"]):
                if int(line) in wanted:
                    self.確認(int(line) not in result, f"{path}: 原行の重複")
                    result[int(line)] = (float(data["now"][index]), float(data["bid"][index]),
                                         float(data["ask"][index]), bool(data["valid"][index]))
        return result

    def 板を照合(self, fill: dict[str, Any], cache: dict[int, tuple], side: int,
             is_entry: bool, label: str) -> None:
        """約定の原行・時計・売買方向別の正常BBO価格を検証する。

        引数: fill (dict[str, Any]) は約定、cache (dict[int, tuple]) は独立に読んだ板、
        side (int) は方向、is_entry (bool) は新規か、label (str) は検査対象。
        返り値: None。
        """
        line = int(fill["source_line"])
        self.確認(line in cache, label + "キャッシュに原行がない")
        if line not in cache:
            return
        now, bid, ask, valid = cache[line]
        self.確認(valid and 数値(bid) > ZERO and 数値(ask) > 数値(bid), label + "約定した原行の板が不正")
        self.確認(abs(秒数(時刻(fill["timestamp"])) - 数値(now)) <= Decimal("0.000001"), label + "原行の価格時計不一致")
        expected = ask if (side == 1) == is_entry else bid
        self.同値(fill["price"], expected, label + "原行のBBO約定価格")
        self.cache_checks += 1


# ----------------------------------------
# 成果物全体の一致と小さな監査結果

def 実行(study: Path, conditions: Path | None = None, cache_check: bool = False) -> dict[str, Any]:
    """全Viewer資源・CSVを独立会計で監査し、照合結果JSONを保存する。

    引数: study (Path) は成果物、conditions (Path | None) は条件JSON、cache_check (bool) は原行BBOも照合するか。
    返り値: dict[str, Any] は監査状態・件数・不一致。含み損益DDや戦略シグナルの正否は再計算しない。
    """
    study = study.resolve(strict=True)
    auditor = 独立監査()
    try:
        condition_path = 設定を探す(study, conditions)
        config = JSONを読む(condition_path)
        manifest_candidate = study / "入力台帳.json"
        if not manifest_candidate.is_file():
            manifest_candidate = condition_path.parent / "入力台帳.json"
        manifest, manifest_path = 台帳を読む(manifest_candidate)
        inputs = {(entry["symbol"], entry["session"]): entry for entry in manifest["entries"]}
        resources = JSONを読む(study / "一覧.resources.json")
        auditor.確認(resources.get("schema_version") == 1 and resources.get("path_base") == "catalog", "資源一覧の形式")
        session_rows = CSVを読む(study / "セッション集計.csv")
        trade_rows = CSVを読む(study / "取引集計.csv")
        sessions = {(row["銘柄"], row["場"], row["手法"]): row for row in session_rows}
        trades = {(row["銘柄"], row["場"], row["手法"], row["建玉ID"]): row for row in trade_rows}
        auditor.確認(len(sessions) == len(session_rows), "セッション集計の重複キー")
        auditor.確認(len(trades) == len(trade_rows), "取引集計の重複キー")
        grouped, resource_keys, resource_ids = {}, set(), set()
        for resource in resources["resources"]:
            method = resource.get("entry_method_id", resource["method_id"])
            key = (resource["symbol"], resource["session"], method)
            auditor.確認(key not in resource_keys, f"{key}: 資源の重複")
            auditor.確認(resource["id"] not in resource_ids, "資源IDの重複")
            resource_keys.add(key)
            resource_ids.add(resource["id"])
            grouped.setdefault((study / resource["pnl_path"]).resolve(), []).append(resource)
        auditor.確認(resource_keys == set(sessions), "Viewer資源とセッション集計の対象が一致しない")
        matched = set()
        cache_root = Path(config["キャッシュルート"])
        if not cache_root.is_absolute():
            cache_root = ROOT / cache_root
        for path, group in grouped.items():
            entry = inputs[group[0]["symbol"], group[0]["session"]]
            accounts, checked = auditor.ファイルを監査(path, group, config, entry, trades,
                                                   cache_root if cache_check else None)
            matched.update(checked)
            for method, account in accounts.items():
                key = (group[0]["symbol"], group[0]["session"], method)
                if key not in sessions:
                    continue
                row = sessions[key]
                for column, expected in (("取引数", account["count"]), ("純損益円", account["cash"]),
                                         ("終了建玉", account["open"]), ("終了未約定", ZERO)):
                    auditor.同値(row[column], expected, f"{key}: セッション {column}")
        auditor.確認(matched == set(trades), "取引集計に未照合行または約定のない取引がある")
        result = {"監査状態": "成功" if not auditor.errors else "失敗", "資源数": len(resource_keys),
                  "約定ファイル数": len(grouped), "約定数": auditor.fills, "完結取引数": auditor.closed,
                  "取引CSV行数": len(trade_rows), "キャッシュBBO照合約定数": auditor.cache_checks,
                  "条件SHA256": ハッシュ(condition_path), "入力台帳SHA256": ハッシュ(manifest_path)}
    except Exception as error:
        auditor.errors.append(f"監査を継続できない入力: {type(error).__name__}: {error}")
        result = {"監査状態": "失敗"}
    result.update({"確認日時": datetime.now(JST).isoformat(), "照合条件数": auditor.checks,
                   "不一致数": len(auditor.errors), "不一致": auditor.errors[:300],
                   "監査コードSHA256": ハッシュ(Path(__file__)),
                   "範囲": "再生.pyをimportせず、新規method_id帰属、Decimal会計、CSV、枚数・一建玉、原行・時刻・場末ゼロを検査。任意でキャッシュの正常BBO価格を検査。",
                   "限界": "未約定要求の独立記録はないため要求時刻そのものは再現しない。待ち1秒は取引CSV記録値を照合。含み損益DD、入口シグナル、追尾・利確の最初の発動時点、原板全イベントの完全性は別監査。"})
    (study / "台帳照合結果.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> None:
    """指定成果物を監査し、不一致があれば終了コード1にする。

    引数: なし。argparseからstudy・conditions・cache-checkを受け取る。
    返り値: None。
    """
    parser = argparse.ArgumentParser(description="混在Viewer約定の帰属・会計を独立に照合する")
    parser.add_argument("--study", required=True, type=Path)
    parser.add_argument("--conditions", type=Path)
    parser.add_argument("--cache-check", action="store_true")
    args = parser.parse_args()
    result = 実行(args.study, args.conditions, args.cache_check)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result["監査状態"] != "成功":
        sys.exit(1)


if __name__ == "__main__":
    main()
