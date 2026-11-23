"""監査済みTOPIXだけから、固定29の中心化MACDと限定出典を構成する。"""

from copy import deepcopy
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("TOPIX補助の固定29数値", ROOT/"scripts/OBV反転/指標.py")
NUMERIC = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = NUMERIC
SPEC.loader.exec_module(NUMERIC)
W, SOURCE_FIELDS, finite = NUMERIC.W, NUMERIC.SOURCE_FIELDS, NUMERIC.finite
AUX_FIELDS = ("場", *SOURCE_FIELDS, "価格数値入力可", "macd_hist", "MACD原点", "MACD原点出典")


def sha(path: Path) -> str:
    """予約済みファイルの内容指紋を分割読取で求める。

    引数: path(Path)はコード又は予約済みcache。
    返り値: strはSHA256。原板の複製や列挙をしない。
    """
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024*1024), b""): digest.update(block)
    return digest.hexdigest()


def canonical_sha(value: object) -> str:
    """限定数値と公開出典を厳密JSONの指紋へ写す。

    引数: value(object)はJSON互換値。
    返り値: strは並びと全末端値を保持するSHA256。
    """
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def aux_projection(row: dict | None) -> dict | None:
    """TOPIXの3分価格出典と中心化ヒストだけを取り出す。

    引数: row(dict|None)は数値足又は未公開参照なし。
    返り値: dict|Noneは17列。数量/OBV/ATR/BBO正常フラグを含まない。
    """
    if row is None: return None
    if row["minutes"] != 3: raise ValueError("TOPIX補助は3分だけです")
    return {key: deepcopy(row[key]) for key in AUX_FIELDS}


class AuxiliaryBank:
    """TOPIX自身の同限月だけで固定29の中心化MACDをcarryする。"""

    def __init__(self) -> None:
        """NKとは共有しない空のTOPIX銀行を用意する。

        引数: なし。
        返り値: None。場内OLSや公開現前参照は入口側で毎場初期化する。
        """
        self.bank = NUMERIC.NumericBank()

    def build(self, frames: list[dict], session: str, contract: tuple,
              tail_missing: int = 0) -> tuple[list[dict], dict]:
        """完全幅のTOPIX足を固定銀行へ投入し、価格系列だけを射影する。

        引数: frames(list[dict])は3分OHLC、session(str)は場、contract(tuple)はTPI限月、
        tail_missing(int)は完全尾部欠枠数。
        返り値: tuple[list[dict],dict]は限定数値/価格品質。数量を計算gateにしない。
        """
        if len(contract) != 1 or any(row["minutes"] != 3 or row["end"]-row["start"] != 180 for row in frames):
            raise ValueError("一意のTOPIX限月と完全180秒足だけです")
        rows, info = self.bank.build(frames, session, contract, tail_missing, quantities=None)
        projected = [aux_projection(row) for row in rows]
        quality = {key: deepcopy(info[key]) for key in ("場", "時間足分", "入力足数", "価格数値入力足数",
            "MACD準備足数", "数値clear数", "尾部完全欠枠", "非公開価格数値更新数", "場末MACD原点")}
        quality["全足SHA256"] = canonical_sha(projected)
        return projected, quality


def build_aux(manifest: dict, quality_sink: dict | None = None) -> dict[str, list[dict]]:
    """監査済み台帳の順にTOPIXを読み、全場の限定足だけを返す。

    引数: manifest(dict)はsource_root/cache_base/entries、quality_sink(dict|None)は任意の品質格納先。
    返り値: dict[str,list[dict]]は場別限定数値。実市場での起動はroot担当だけが行う。
    """
    entries = manifest["entries"]
    sessions = [row["session"] for row in entries]
    if sessions != sorted(sessions) or len(set(sessions)) != len(sessions):
        raise ValueError("監査済みTOPIX台帳は場の昇順で一意だけです")
    source_root = Path(manifest["source_root"]).resolve()
    cache_base = (ROOT/manifest.get("cache_base", "work/複合検証")).resolve()
    if not cache_base.is_relative_to((ROOT/"work").resolve()): raise ValueError("cache基底がwork外です")
    bank, output = AuxiliaryBank(), {}
    for entry in entries:
        if entry["symbol"] != "TOPIX" or Path(entry["source_path"]).parts[0] != "TOPIX":
            raise ValueError("監査済みTOPIXだけです")
        source, cache = (source_root/entry["source_path"]).resolve(), (cache_base/entry["cache_path"]).resolve()
        if not source.is_relative_to(source_root) or not cache.is_relative_to((ROOT/"work").resolve()):
            raise ValueError("予約入力の解決先が基底外です")
        stat = source.stat()
        if (stat.st_size, stat.st_mtime_ns) != (entry["source_size"], entry["source_mtime_ns"]) or sha(cache) != entry["sha256_cache"]:
            raise ValueError("予約TOPIX原板/cacheの指紋に差")
        contract = tuple(entry["in_session_contract_codes"])
        if len(contract) != 1: raise ValueError("TOPIX場内限月は一意だけです")
        if entry.get("場内限月年月") != [entry["限月年月"]]: raise ValueError("監査済みTOPIX限月年月に差")
        session = entry["session"]
        begin, finish, _, _ = W.OLD.shared.legacy.session_times(session)
        start, end, events, previous_now = begin.timestamp(), finish.timestamp(), [], -math.inf
        for event in W.PREP.read_events(cache):
            if math.isfinite(event.now) and start <= event.now <= end and event.now >= previous_now:
                events.append(event); previous_now = event.now
        formed = W.bars_from_events(events, start, end, 3)
        tail = max(0, int((end-start)//180)-1-(formed[-1]["index"] if formed else -1))
        output[session], quality = bank.build(formed, session, contract, tail)
        after = source.stat()
        if (after.st_size, after.st_mtime_ns) != (stat.st_size, stat.st_mtime_ns):
            raise ValueError("TOPIX読取中に原板が変化")
        if quality_sink is not None:
            quality_sink[session] = {**quality, "商品": "TOPIX", "限月年月": entry["限月年月"],
                "原板相対パス": entry["source_path"], "cache相対パス": entry["cache_path"],
                "cacheSHA256": entry["sha256_cache"], "原板展開SHA256": entry["sha256_uncompressed"]}
    return output
