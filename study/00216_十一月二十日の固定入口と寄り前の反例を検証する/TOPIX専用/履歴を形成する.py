"""212_06の旧83場を通った指標履歴を保持して、後続7場の純特徴を生成する。"""
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
import gzip
import hashlib
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
WORK = ROOT / 'work/216TOPIX専用'
sys.path[:0] = list(map(str,(ROOT/'work/194追加二場', ROOT/'scripts/複合検証')))
import TOPIX純接続194 as old
import データ準備 as reader
DATES = ('2026-11-17_Night','2026-11-18_Day','2026-11-18_Night','2026-11-19_Day','2026-11-19_Night','2026-11-20_Day','2026-11-20_Night')
NAMES = ('純特徴183.json.gz','純特徴184直接.json.gz')


# ----------------------------------------
def raw_path(scene: str) -> Path:
    """
    機能：TOPIXの物理原板を取得する。二形式あるときは非圧縮形を優先する。
    引数：scene（str）はセッション名。
    返り値：Pathは読取対象。
    """
    directory = ROOT.parent / 'JP_OSE_Data/future/TOPIX' / scene
    return next(p for p in (directory/'book.jsonl',directory/'book.jsonl.gz') if p.is_file())


# ----------------------------------------
def load_new(scene: str) -> dict:
    """
    機能：原板を8列の参照入力に変換し、展開後SHA256の一致を検査する。
    引数：scene（str）はセッション名。
    返り値：dictは8列入力・限月・原板指紋等。
    """
    raw = raw_path(scene)
    cache = WORK / '原順8列' / (scene+'.npz')
    audit = cache.with_suffix('.json')
    if audit.exists():
        entry = old.I.read(audit)
        with (gzip.open(raw,'rb') if raw.suffix=='.gz' else raw.open('rb')) as stream:
            assert entry['sha256_uncompressed'] == hashlib.file_digest(stream,'sha256').hexdigest()
        assert old.M.sha(cache)==entry['sha256_cache']
        return entry
    entry = reader.build_one(raw,cache,'TOPIX',scene,ROOT.parent/'JP_OSE_Data')
    entry['cache_absolute'] = str(cache)
    old.I.save(audit,entry)
    return entry


# ----------------------------------------
def form(formation: int) -> dict:
    """
    機能：83場の履歴を起点から形成し、旧最終2場の純特徴が全行一致する状態で7場を追加する。
    引数：formation（int）は0が1分合成、1が直接形成。
    返り値：dictは旧特徴一致数と追加特徴数。
    """
    history = old.entries()
    entries = history + [old.I.read(WORK/'原順8列'/(day+'.json')) for day in DATES]
    comparison = old.I.read(old.DEST / NAMES[formation])
    contract, channels, known, future = None, {}, [], []
    for i,entry in enumerate(entries):
        if entry['in_session_contract_codes'] != contract:
            contract=entry['in_session_contract_codes']
            channels={n:old.M.Channel() for n in (5,15,30)}
        data,_ = (old.M.bars_and_features(entry,channels) if formation==0
                  else old.D.direct_features(entry,channels,Counter()))
        if i>=81:
            for row in data:
                plus,minus = old.M.roles(row,1),old.M.roles(row,-1)
                row['signals']=[1 if a and not b else -1 if b and not a else 0 for a,b in zip(plus,minus)]
            (known if i<len(history) else future).extend(data)
        if (i+1)%15==0:
            print('足形成',formation,i+1,flush=True)
    assert known==comparison,(formation,'旧最終2場の純特徴')
    old.I.save(WORK / NAMES[formation],known+future)
    return {'旧2場一致':len(known),'追加7場':len(future),'入力':old.I.ref(WORK/NAMES[formation])}


# ----------------------------------------
def main() -> None:
    """
    機能：純特徴2形成と入力の指紋を作業領域に保存する。
    引数：なし。
    返り値：None。
    """
    WORK.mkdir(parents=True,exist_ok=True)
    with ProcessPoolExecutor(max_workers=4) as workers:
        entries=list(workers.map(load_new,DATES))
        checks=list(workers.map(form,(0,1)))
    old.I.save(WORK/'形成検査.json',{'入力':entries,'形成':checks})


if __name__=='__main__':
    main()
