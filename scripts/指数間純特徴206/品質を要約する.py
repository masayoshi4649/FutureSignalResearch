"""全8returnの共通品質と時計感度を金融なしで集計する。"""
from collections import Counter,defaultdict
from pathlib import Path
import hashlib
import json
import numpy as np

ROOT=Path(__file__).resolve().parents[2]
DEST=ROOT/'inputs/00206_両指数の固定端点相対変化'


# ----------------------------------------
def main() -> None:
    """
    機能: 全q0の自己相手×4窓の可用性を商品・帯・遅延で要約する。
    引数: なし。
    返り値: None。金融母体、採否、成績は参照しない。
    """
    done=json.loads((DEST/'完了.json').read_text(encoding='utf-8'));counts=defaultdict(Counter)
    for row in done['files']:
        with np.load(ROOT/row['file']['path'],allow_pickle=False) as z:
            for band,index in (('DAY',0),('PRE',1),('POST',2)):
                mask=z['q0_band']==index
                if not np.any(mask):continue
                for di,delay in enumerate((1,5,30,60)):
                    c=counts[f'{row["symbol"]}/{band}/d{delay}']
                    known=z['return_known'][:,di].all(axis=(1,2));quality=z['quality_known'][:,di].all(axis=(1,2))
                    first=z['quality_known'][:,0].all(axis=(1,2))
                    c['q0']+=int(mask.sum());c['全8return端点既知']+=int(np.sum(known&mask));c['全8return品質既知']+=int(np.sum(quality&mask))
                    c['d1と共通の全8品質既知']+=int(np.sum(quality&first&mask))
                    c['d1から全8品質旗が変化']+=int(np.sum((quality!=first)&mask))
    source=Path(__file__)
    value={'試行':206,'金融参照':False,'成功':True,'集計対象':'純q0全件。入口採否による選択なし。','全8return':'自己/相手×1/5/15/30分の全て',
        'Source':{'path':source.relative_to(ROOT).as_posix(),'sha256':hashlib.sha256(source.read_bytes()).hexdigest()},
        '共通品質':dict(counts),'窓ごとの感度正本':'完了.json/遅延感度と可用性'}
    p=DEST/'共通品質の遅延感度.json';body=json.dumps(value,ensure_ascii=False,indent=2)+'\n'
    if p.exists():assert p.read_text(encoding='utf-8')==body
    else:p.write_text(body,encoding='utf-8')
    print(json.dumps(dict(counts),ensure_ascii=False,indent=2),flush=True)


# ----------------------------------------
if __name__=='__main__':main()
