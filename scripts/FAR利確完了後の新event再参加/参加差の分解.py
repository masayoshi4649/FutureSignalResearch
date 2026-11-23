"""同参照の複数実参加を落とさず、同実入口と残る参加差を分解する。"""

from collections import Counter, defaultdict


def fingerprint(row: dict) -> tuple:
    """
    機能: 実参加の経済的に同じ入口を識別する。
    引数: row (dict) はsession/lot/entry_orderを持つ取引診断。
    返り値: tuple は参照IDと要求/方向/実取得時計/価格/初期量。
    """
    lot = row["lot"]
    return (row["session"], lot["reference_id"], row["entry_order"]["request_time"],
            lot["side"], lot["entry_time"], lot["entry_price"], lot["initial_quantity"])


def decompose(left: list[dict], right: list[dict]) -> dict:
    """
    機能: 完全一致を多重集合で対応し、全額差を初期入口と参加差へ足し戻す。
    引数: left/right (list[dict]) は両会計の実取得済み玉診断。
    返り値: dict は同実出口差・同ref未一致・ref片側の数量と純額。
    """
    groups = []
    for rows in (left, right):
        identities = [(r["session"], r["lot"]["id"]) for r in rows]
        if len(set(identities)) != len(identities):
            raise ValueError("会計内の実玉IDが重複")
        group = defaultdict(list)
        for row in rows:
            if row["lot"]["initial_quantity"] <= 0:
                raise ValueError("実取得0の要求を実参加へ混入")
            group[fingerprint(row)].append(row)
        groups.append(group)
    a, b = groups
    refs = [{key[:2] for key in group} for group in groups]
    common_refs = refs[0] & refs[1]
    paired = []
    unmatched = [[], []]
    for key in sorted(set(a) | set(b)):
        first, second = a.get(key, []), b.get(key, [])
        count = min(len(first), len(second))
        paired.extend(zip(first[:count], second[:count], strict=True))
        unmatched[0].extend(first[count:])
        unmatched[1].extend(second[count:])
    same_ref = [[r for r in rows if (r["session"], r["lot"]["reference_id"]) in common_refs] for rows in unmatched]
    only_ref = [[r for r in rows if (r["session"], r["lot"]["reference_id"]) not in common_refs] for rows in unmatched]
    net = lambda rows: sum(r["lot"]["net_pnl"] for r in rows)
    same_a, same_b = net([a for a, _ in paired]), net([b for _, b in paired])
    output = {"同参照ID": len(common_refs), "同実新規": len(paired),
        "同実新規A損益円": same_a, "同実新規B損益円": same_b, "同実新規出口差円": same_b-same_a,
        "同実役割組合せ": dict(Counter(a["entry_role"]+"→"+b["entry_role"] for a, b in paired)),
        "同ref未一致A": len(same_ref[0]), "同ref未一致B": len(same_ref[1]),
        "同ref未一致A損益円": net(same_ref[0]), "同ref未一致B損益円": net(same_ref[1]),
        "ref片側A": len(only_ref[0]), "ref片側B": len(only_ref[1]),
        "ref片側A損益円": net(only_ref[0]), "ref片側B損益円": net(only_ref[1]),
        "同ref未一致A役割": dict(Counter(r["entry_role"] for r in same_ref[0])),
        "同ref未一致B役割": dict(Counter(r["entry_role"] for r in same_ref[1])),
        "全差円": net(right)-net(left)}
    reconstructed = same_b-same_a + net(same_ref[1])-net(same_ref[0])+net(only_ref[1])-net(only_ref[0])
    if output["全差円"] != reconstructed or len(left) != len(paired)+len(unmatched[0]) or len(right) != len(paired)+len(unmatched[1]):
        raise ValueError("実参加の数量又は全額差分解が一致しない")
    return output
