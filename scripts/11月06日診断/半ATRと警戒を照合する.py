"""実保有中の保存公表列で、利益額と警戒の同時成立だけを照合する。"""

import collections
import gzip
import json
from pathlib import Path

from 診断する import OUT, ROOT, TRIAL, point, read_json, ref, when


def main() -> None:
    """
    機能: ナイト02:45売り玉の保有中観測で、半ATR金額とC/M警戒の同時成立を調べる。
    引数: なし。
    返り値: None。
    """
    native_path = TRIAL / "成果物_金融/Native/2026-11-06_Night.Native.json.gz"
    native = read_json(native_path)
    position = next(p for p in native["books"]["B0_C0_D0"]["positions"] if p["id"].endswith("P000018"))
    start, end = position["entry_quote"]["time"], position["closed_quote"]["time"]
    threshold = 100 * max(10, .5 * position["atr"]["value"])
    source_path = ROOT / "work/106市場/全70場/2026-11-06_Night.public.records.jsonl.gz"
    index = read_json(TRIAL / "成果物_金融/Native参照台帳.json")
    source_ref = next(x for x in index["Native"] if x["session"] == "2026-11-06_Night")["公開sidecar"]["sidecar_records"]
    source_fingerprint = ref(source_path)
    assert source_fingerprint["sha256"] == source_ref["sha256"]
    latest, reached, publications = None, [], []
    maximum_unit_net = -float("inf")
    observations = collections.Counter()
    with gzip.open(source_path, "rt", encoding="utf-8") as stream:
        for line in stream:
            record = json.loads(line)
            if record["at"] > end:
                break
            if record["kind"] == "publication":
                latest = record["delivery"]["sell"]
                if start <= record["at"] <= end:
                    publications.append({"日時": when(record["at"]), "公表ID": latest["publication_id"],
                                         "C": latest["c"], "M": latest["m"]})
            elif record["kind"] == "quote" and start <= record["at"] <= end:
                scalar = record["scalar"]
                if not scalar["quote_ok"]:
                    continue
                unit_net = 100 * (position["entry_price"] - scalar["ask"]) - 77
                maximum_unit_net = max(maximum_unit_net, unit_net)
                if unit_net < threshold:
                    continue
                assert latest and latest["available_at"] <= scalar["time"]
                c, m = latest["c"], latest["m"]
                label = f"C={c['passed']},M={m['passed']}"
                observations[label] += 1
                reached.append({"日時": when(scalar["time"]), "参照行": scalar["source_line"],
                                "費用後単位円": unit_net, "参照公表ID": latest["publication_id"], "C": c, "M": m})
    assert maximum_unit_net == position["marks"]["unit_max"]["unit_net"]
    assert reached and all(not (x["C"]["known"] and x["C"]["passed"] and x["M"]["known"] and x["M"]["passed"]) for x in reached)
    result = {"対象建玉": position["id"], "金融再実行": False,
              "対象範囲": [when(start), when(end)], "半ATR起動額円毎枚": threshold,
              "保存単位最大と照合一致": True, "半ATR額到達観測数": len(reached),
              "半ATR額到達時の警戒組合せ": dict(observations), "初回到達観測": reached[0], "最終到達観測": reached[-1],
              "保有中公表": publications, "出典": [ref(native_path), source_fingerprint],
              "結論": "半ATR利益とC/M警戒が同時に成立しなかった。起動額未満の時刻に警戒しても、この政策の利益起動にはならない。",
              "限界": "既存の実保有と価格列で条件の同時性を記述した。新しい退出・約定や利益額は推計していない。"}
    (OUT / "半ATRと警戒の同時性.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("半ATR額到達観測数", "半ATR額到達時の警戒組合せ", "初回到達観測", "最終到達観測", "結論")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
