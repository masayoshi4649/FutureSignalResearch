"""TOPIX既存2入口の全注文要求について、同じ5分足で日経R1の必要符号を照合する。"""
import gzip
import hashlib
import json
import math
from pathlib import Path
import statistics


def read(path: Path) -> object:
    """
    機能: 圧縮または通常のUTF-8 JSONを読む。
    引数: path(Path)は既存の正式入力。
    返り値: objectは復号されたデータ。
    """
    payload=path.read_bytes()
    return json.loads(gzip.decompress(payload) if path.suffix=='.gz' else payload)


# ----------------------------------------
def key(row: dict) -> tuple:
    """
    機能: 方向を計算した時点の場・時刻・物理行を特定する。
    引数: row(dict)は純特徴または純入口の一行。
    返り値: tupleは同じ公表行を識別する三つ組。
    """
    return row['session'],row['time'],row['line']


# ----------------------------------------
def main() -> None:
    """
    機能: 技法210の二つのデイ入口と、同じ足の反対側方向指標を照合する。
    引数: なし。作業ディレクトリをリポジトリのルートとする。
    返り値: None。結果は標準出力に日本語JSONで出す。
    """
    root=Path.cwd()
    directory=next((root/'inputs').glob('00210_*'))
    manifest=read(directory/'入力台帳.json')
    pure=manifest['純出生']
    pinned={pure['path']:pure['sha256']}
    pinned.update({p:d for p,d in manifest['入力SHA'].items() if p.endswith('/純特徴184直接.json.gz')})
    assert len(pinned)==3
    for name,digest in pinned.items():
        assert hashlib.sha256((root/name).read_bytes()).hexdigest()==digest
    signals=read(root/pure['path'])
    features={}
    for name in pinned:
        if name==pure['path']:
            continue
        for row in read(root/name):
            assert key(row) not in features
            features[key(row)]=row
    assert len(signals)==len({key(row) for row in signals})==35361
    assert set(features)<={key(row) for row in signals}
    day=[r for r in signals if r['band']=='DAY']
    sessions=sorted({r['session'] for r in day})
    assert len(sessions)==42
    result={}
    for label,index in [('D4',0),('210主3',3)]:
        values=[]
        counts={s:0 for s in sessions}
        for decision in day:
            side=decision['signals'][index]
            if not side:
                continue
            assert side in (-1,1)
            value=side*features[key(decision)]['m5']['di']
            assert math.isfinite(value)
            values.append(value)
            counts[decision['session']]+=1
        result[label]={'非零の純入口':len(values),'要求成立場':sum(c>0 for c in counts.values()),
                       '実側5分DI差最小':min(values),'実側5分DI差中央値':statistics.median(values),
                       '実側5分DI差最大':max(values),'反対側5分DI差が正':sum(-v>0 for v in values),
                       '場別純入口':counts}
        assert result[label]['反対側5分DI差が正']==0
    assert all(r['signals'][3] in (0,r['signals'][0]) for r in day)
    print(json.dumps({'参照':pinned,'場数':len(sessions),'全帯判断数':len(signals),'デイ判断数':len(day),
                      'デイで直接特徴が無い判断':sum(key(row) not in features for row in day),
                      'デイ照合':result,'範囲':'210が用いたTOPIX184直接形成の同一5分足で、反対方向のDI差が正という日経R1必要条件を検査。別の足形成のR1は対象外。'},ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
