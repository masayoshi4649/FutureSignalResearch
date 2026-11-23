"""固定した四つの出口を原板で再生し、動的返済の遅延だけを比較する。"""
from hashlib import sha256
import json
from pathlib import Path
import runpy


HERE = Path(__file__).resolve().parent
WORK = HERE.parents[1] / "work/219返済遅延"
HASHES = {
    "口座再生.py": "cb1b0769c78dcbd9887ef0d99489479e39cfe09b302eff47ef856997e0e9dfd7",
    "逆行時の出口.py": "ceb4fc2057ed5c078b73859b2b7772fa00af8e49ab1c14d48d87c22b4af8e175",
    "期限前保護の切り分け.py": "ebc868ad2bf0f8621cccace251e3c96d88e38d2184880d8f49cfb1d9609fe5d5",
    "成熟時の出口.py": "c55ed476333cea40d59f0fab65f9acd9e3e1017ff631e61166ec11acdc84d113",
    "出口候補.py": "dfb5e609100d74086ac15aaa5b62ca6b59a1d76bb606ff18385453f0247864e1",
}
TARGETS = {"W": ("逆行時の出口.py", b"times[trigger]+1"),
           "M": ("期限前保護の切り分け.py", b"time[trigger]+1")}
CODES = ("W31", "W36", "M34", "M28")
DELAYS = (1, 3, 5)
BASELINES = {
    "口座再生": {
        "IFD": "2b03410c0a4d342958f597ab7e26f5999d2af246a7a604be1ddccb3f31ce53e7",
        "W31": "5b213f6a60261568049802baa1c99d01f1995c28f137ae3099655d5667fbb527",
        "W36": "447180dd5a701cee861ecbf3bb77fff03e74f9ff10fbe31c772cf648f4879463",
        "M34": "0e83ef8924993d6e320a8b894086b0c05b7ed2ec504ca4021e0a46a2e7546ed5",
        "M28": "88bad39fa0964f90b797608b607e0baca90212a6e55925da7bd8b68a7503ea77",
    },
    "入口固定": {
        "IFD": "2b03410c0a4d342958f597ab7e26f5999d2af246a7a604be1ddccb3f31ce53e7",
        "W31": "6feabe07d06ea76c47643f08d828887a2911784f15b8857354d966ea30e4f25d",
        "W36": "b9dbcc575da74ee5f558c51f4509e8f83c2a3f902b368d08ecdcaa7148c12bf8",
        "M34": "4316da6abc10893156e3995ea0b5c9f99606876c2ef39f192a29009ade6d4c81",
        "M28": "0115c397645135c31c6db8c596b07d74f56159f0ab0904c19fd52faa0ff17c96",
    },
}


def sensitivity() -> dict:
    """
    機能：正本の指紋を照合し、作業用複製の動的返済待ちだけを変えて統合する。
    引数：なし。入力は同じ試行内の口座再生器と出口定義。
    返り値：dict。各遅延の候補を同じ場で同時に再生するインターフェース。
    """
    sources = {name: (HERE/name).read_bytes() for name in HASHES}
    assert {name: sha256(body).hexdigest() for name, body in sources.items()} == HASHES
    modules = {}
    for seconds in DELAYS:
        dest = WORK / f"{seconds}秒"
        dest.mkdir(parents=True, exist_ok=True)
        for helper in ("成熟時の出口.py", "出口候補.py"):
            (dest/helper).write_bytes(sources[helper])
        for group, (name, expression) in TARGETS.items():
            body = sources[name]
            assert body.count(expression) == 1
            (dest/name).write_bytes(body.replace(expression, expression[:-1]+str(seconds).encode("ascii")))
            modules[group, seconds] = runpy.run_path(str(dest/name))
    # ----------------------------------------
    def prepare(index, scene: dict) -> dict:
        """
        機能：同じ場の完成足をW群とM群それぞれで一度だけ準備する。
        引数：index（PriceIndex）は原板索引、scene（dict）は場の情報。
        返り値：dict。群ごとの形成済み特徴量。
        """
        return {group: modules[group, 1]["prepare"](index, scene) for group in TARGETS}

    def decide(code: str, context: dict, *args) -> dict:
        """
        機能：同じ取得を指定の出口と遅延で決済する。
        引数：code（str）は候補と秒数、context（dict）は両群の特徴、args（tuple）は原行・期限等。
        返り値：dict。競合・欠測を含めた決済行と事由。
        """
        policy, delay = code.split("_")
        return modules[policy[0], int(delay)]["decide"](policy, context[policy[0]], *args)

    return {"prepare": prepare, "decide": decide}


def main() -> None:
    """
    機能：45日を通常の口座と取得固定で再生し、各建玉の元帳と再現情報を保存する。
    引数：なし。入力は研究219の元IFDと4出口×3遅延。
    返り値：None。元帳・場別取得数を作業領域へ書き出す。
    """
    interface = sensitivity()
    codes = [f"{code}_{seconds}" for code in CODES for seconds in DELAYS]
    engine = runpy.run_path(str(HERE/"口座再生.py"))
    books, audit = engine["calculate"](interface, codes)
    audit["入力SHA256"] = HASHES
    for mode, ledger in books.items():
        for code, fingerprint in BASELINES[mode].items():
            rows = ledger[code if code == "IFD" else f"{code}_1"]
            normal = [dict(row, exit_strategy=code) for row in rows]
            body = json.dumps(normal, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf8")
            assert sha256(body).hexdigest() == fingerprint
        for code in CODES:
            for seconds in DELAYS:
                run = ledger[f"{code}_{seconds}"]
                assert all(t["exit_time"]-t["trigger_time"] >= seconds for t in run if t["status"] == 5)
            print(mode, code, len(ledger[f"{code}_1"]), flush=True)
    for name, data in (("比較元帳", books), ("再生照合", audit)):
        (WORK/(name+".json")).write_text(json.dumps(data, ensure_ascii=False, allow_nan=False), encoding="utf8")


if __name__ == "__main__":
    main()
