"""固定96金融規範を継承し、H0床だけを独立再構成する人工用監査。"""

import argparse
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
OLD_PATH = ROOT/"scripts/FAR5分枠の技法判定の監査/出生枠と金融の照合.py"
OLD_SHA = "7f673b29f27bc8f79e2c0c2e6106dc457a4697f283fdb64a7cddafa4e3210658"
TECH_PATH = ROOT/"scripts/FAR5分枠の技法判定の監査/技法の保存照合.py"
TECH_SHA = "b5d1af7fb85d4446a47573a4389abfa433177189cb01d901bdd53a8a38b8d5e6"
HARVEST_REASON = "初回費用後残玉正益の全量確定"
KEYS = tuple(("H0_" if harvest else "")+(gate+"_" if gate else "")+f"B5Q_P0_C{cost}_D{delay}"
             for gate in ("", "AB") for harvest in (False, True) for cost in (0, 5) for delay in (0, 1))


def digest(path: Path) -> str:
    """
    機能: 明示されたコード又は人工入力を指紋化する。
    引数: path(Path)は読取先。
    返り値: strはSHA256。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fixed_module(name: str, path: Path, expected: str):
    """
    機能: 停止版のPythonだけをSHA確認して読み込む。
    引数: name/expected(str)、path(Path)はmodule名・指紋・保存先。
    返り値: moduleは固定部品。市場/Go/原板の実行はしない。
    """
    if digest(path) != expected:
        raise ValueError("固定監査SHA差:"+str(path))
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


OLD = fixed_module("固定96全原行金融97", OLD_PATH, OLD_SHA)
TECH = OLD.TECH
if digest(TECH_PATH) != TECH_SHA:
    raise ValueError("固定96技法SHA差")
BASE, Audit = OLD.BASE, OLD.Audit


# ----------------------------------------
class ArtificialAllowGates:
    """Go型人工で宣言された常時AB許可だけを独立の定数から返す。"""

    def __init__(self, books: dict, audit: Audit):
        """
        機能: 人工のcallback適用記録を空から作る。
        引数: books(dict)、audit(Audit)は16口座と比較器。
        返り値: None。保存Gateを期待判断へ読み戻さない。
        """
        self.books, self.audit, self.claimed = books, audit, set()

    def claim(self, key: str, opportunity: dict) -> dict:
        """
        機能: 金融前資格を通った人工候補へ一度だけAB許可を返す。
        引数: key(str)、opportunity(dict)は独立に再構成した口座と候補。
        返り値: dictは手製callbackの固定判断。純技法の成立証拠ではない。
        """
        marker = key, opportunity["ordinal"]
        self.audit.need(marker not in self.claimed, "人工gate重複")
        self.audit.need(self.books[key]["config"].get("gate_policy", "") == "AB", "人工gateはABだけ")
        self.audit.need(opportunity["consumed"] is True and opportunity["available"] > 0
                        and opportunity["quote"] is not None, "人工gate前の金融資格")
        self.claimed.add(marker)
        return dict(policy="AB", snapshot_id="人工枠", known=True, allowed=True, role="順行", reason="人工許可")

    def finish(self) -> dict:
        """
        機能: 再構成したcallback集合を保存された一回判定へ照合する。
        引数: なし。
        返り値: dictは人工callback数。3/15数値又は自然採否の検査数は0。
        """
        expected = {(key, p["ordinal"]) for key, book in self.books.items()
                    for p in book["entry_opportunities"] if p.get("gate") is not None}
        self.audit.equal(self.claimed, expected, "人工gate適用集合")
        return {"手製allow判定": len(self.claimed), "自然3/15技法成立の検査": 0}


# ----------------------------------------
class HarvestPath(OLD.GatePath):
    """Source/入口/約定/費用を固定96へ委ね、H0のmarkだけを追加する。"""

    def __init__(self, actual: dict, audit: Audit, gate_provider):
        """
        機能: H0設定と外Keyを明示し、旧規範の初期化へだけ型投影する。
        引数: actual(dict)、audit(Audit)、gate_providerはGo保存口座・比較器・採否供給器。
        返り値: None。受理/注文/約定/Sourceを改時刻又は偽装しない。
        """
        audit.need(actual["key"] in KEYS, "97人工の16key")
        cfg = actual["config"]
        harvest = cfg.get("harvest_policy", "")
        audit.need(harvest in ("", "H0"), "97のHarvest設定")
        audit.need(("harvest_policy" in cfg) == (harvest == "H0"), "空Harvestはomitempty")
        expected_config = {"policy", "slip_pts", "delay_seconds", "entry_timing", "us_open"}
        if cfg.get("gate_policy", ""):
            expected_config.add("gate_policy")
        if harvest:
            expected_config.add("harvest_policy")
        audit.equal(set(cfg), expected_config, "97設定の全tag集合")
        audit.equal(set(actual), {"session", "key", "config", "orders", "fills", "positions", "source_events",
                                 "metrics", "totals", "account", "finished", "complete", "failure", "stream_scope",
                                 "entry_opportunities", "grid_traces", "grid_metrics"}, "97金融top全tag集合")
        audit.equal(actual["stream_scope"], "固定93と同じLast>0のSource受理行。Last0未供給数は共有qualityを参照。", "固定観測scope")
        audit.need(cfg.get("gate_policy", "") in ("", "AB") and cfg["entry_timing"] == "B5Q"
                   and cfg["policy"] == "P0", "97の固定入口と保護")
        old = copy.deepcopy(actual)
        old["config"].pop("harvest_policy", None)
        expected = (cfg.get("gate_policy", "")+"_" if cfg.get("gate_policy", "") else "")
        expected += f"B5Q_P0_C{cfg['slip_pts']:g}_D{cfg['delay_seconds']}"
        audit.equal(actual["key"], ("H0_" if harvest else "")+expected, "97外keyと設定")
        old["key"] = expected
        super().__init__(old, audit, gate_provider)
        # 初期化ラベルだけを射影し、期待IDの採番は実際の97Keyをそのまま使う。
        self.key, self.extra_actual = actual["key"], actual
        self.harvest = harvest == "H0"

    def mark(self, q: dict, phase: str, atr: dict) -> None:
        """
        機能: H0だけ初回strict u正益の返済側を最低床にし、全正常行を評価する。
        引数: q/atr(dict)、phase(str)は当原行・公開幅・pre_fill/after_source。
        返り値: None。新規要求はSource後の未予約量だけ。空Harvestは旧実装を直再用する。
        """
        if not self.harvest:
            return super().mark(q, phase, atr)
        for p in self.positions.values():
            if p["quantity"] == 0:
                continue
            point = BASE.mtm_point(p, q, phase, self.cost)
            p["marks"].observe(point)
            gain = point["gain_points"]
            if not p["has_mark"] or gain > p["peak_gain"]:
                p["peak_gain"] = gain
            p["has_mark"] = True
            self.lock_atr(p, q, atr)
            if not p["protection_active"] and point["unit_net"] > 0:
                p["protection_active"], p["activation"] = True, point
            if not p["protection_active"]:
                continue
            first = p["activation"]
            self.audit.need(first is not None and all(BASE.finite(first[n]) for n in ("gain_points", "unit_net"))
                            and first["unit_net"] > 0, "H0初回strict u正益の根拠")
            floor = max(0.0, first["gain_points"])
            if p["atr"] is not None:
                floor = max(floor, p["peak_gain"]-p["atr"]["width"])
            if p["floor_gain"] is not None:
                floor = max(floor, p["floor_gain"])
            if p["floor_gain"] is None or floor > p["floor_gain"]:
                p["floor_gain"], p["floor_updated"] = floor, point
            if gain <= floor:
                if p["first_floor_hit"] is None:
                    p["first_floor_hit"] = point
                free = p["quantity"]-p["reserved"]
                if phase == "after_source" and free > 0:
                    self.request("exit", -p["side"], free, p["source"], q["time"], q,
                                 HARVEST_REASON, p, point=point)
        self.account.observe(q, phase, self.cash, self.positions, self.side_cost)
        whole = sum(p["realized_net"]+p["quantity"]*(p["side"]*((q["bid"] if p["side"] == 1 else q["ask"])
                    -p["entry_price"])*100-self.cost) for p in self.positions.values())
        self.audit.need(abs(whole-self.account.value["last"]["equity"]) <= 1e-7, "H0全HoldWと現金の独立一致")


# ----------------------------------------
def inspect_fixture(value: dict) -> dict:
    """
    機能: 停止Go型人工16口座の全経路を元calls順に独立再構成する。
    引数: value(dict)は手製Source/公開ATR/常時allowのGo Marshal。
    返り値: dictは64会計へ集約可能な一場結果。自然Source/技法/原板は未検査。
    """
    audit = Audit()
    audit.need(type(value.get("scope")) is str and "人工" in value["scope"], "人工scopeの明示")
    audit.need("chart_grids" not in value and "gate_assessments" not in value, "手製allowだけの専用scope")
    books = value.get("actors")
    audit.need(type(books) is dict, "Go型actors")
    audit.equal(set(books), set(KEYS), "97人工16口座")
    for key, book in books.items():
        audit.equal(book["key"], key, "Actor mapと本体key")
        BASE.compare_tree(book["session"], value["session"], audit, key+"/人工の共通場")
    gates = ArtificialAllowGates(books, audit)
    models = [HarvestPath(books[key], audit, gates) for key in KEYS]
    for call in OLD.OLD.fixture_calls(value):
        if call["kind"] == "quote":
            q, atr = BASE.observation_quote(call["observation"], call["source_line"])
            for model in models:
                model.step(q, call["batches"], atr)
        elif call["kind"] == "timer":
            for model in models:
                model.timer(call["at"], call["batches"])
        elif call["kind"] == "grid":
            for model in models:
                model.grid(call["at"])
        else:
            raise ValueError("未知の人工呼出")
    details = [model.finish() for model in models]
    gate_counts = gates.finish()
    return {"成功": True, "scope": "Go型API人工の全金融経路。Source/ATRは手製、ABは定数allow。自然3/15成立/原板/市場損益は対象外。",
            "会計数": len(details), "非0会計数": sum(d["positions"] > 0 for d in details),
            "照合項目数": audit.checks, "不一致数": 0, "人工gate": gate_counts, "details": details}


def main() -> int:
    """
    機能: 明示された停止Go人工4場面だけを新規証拠へ照合する。
    引数: --fixtures/--out(Path)は人工根と新規結果。市場又は原板Pathは受け付けない。
    返り値: intは全成功0。途中差は例外で非0にする。
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixtures", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        raise ValueError("新規証拠先だけ")
    paths = sorted(args.fixtures.glob("*.json"))
    expected = {"-1_通常.json", "1_通常.json", "1_同原行Source部分.json", "-1_次気配悪化.json"}
    if {p.name for p in paths} != expected:
        raise ValueError("停止人工4場面だけ")
    all_paths = [Path(__file__), OLD_PATH, TECH_PATH, OLD.OLD_PATH, OLD.OLD.BASE_PATH,
                 BASE.BASE_PATH]+paths
    before = {str(p.resolve()): digest(p) for p in all_paths}
    rows = [{"fixture": p.name, **inspect_fixture(BASE.load(p))} for p in paths]
    if any(digest(Path(p)) != h for p, h in before.items()):
        raise ValueError("人工/コード前後差")
    result = {"成功": True, "人工場面": 4, "会計数": sum(r["会計数"] for r in rows),
              "非0会計数": sum(r["非0会計数"] for r in rows), "照合項目数": sum(r["照合項目数"] for r in rows),
              "不一致数": 0, "details": rows, "入力コードSHA256前後": before, "前後不変": True,
              "市場/原板/Go再生": 0, "自然3/15技法成立の主張": False}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2)+"\n", encoding="utf-8", newline="\n")
    print(json.dumps({k:result[k] for k in ("成功", "会計数", "非0会計数", "照合項目数", "不一致数")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
