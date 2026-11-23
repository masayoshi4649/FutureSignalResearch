"""206純特徴と金融前の独立純条件確認を小さなSource ZIPへ保存する。"""
from pathlib import Path
import hashlib
import json
import shutil
import subprocess
import sys
import zipfile

ROOT=Path(__file__).resolve().parents[2]
HERE=Path(__file__).parent
TRIAL=ROOT/'study/00206_指数間の相対変化を複合入口へ加える'
INPUT=ROOT/'inputs/00206_両指数の固定端点相対変化'


# ----------------------------------------
def ref(path: Path) -> dict:
    """
    機能: 相対pathと物理指紋を得る。
    引数: path(Path)。
    返り値: dictはpath/bytes/sha256。
    """
    with path.open('rb') as stream:sha=hashlib.file_digest(stream,'sha256').hexdigest()
    return {'path':path.relative_to(ROOT).as_posix(),'bytes':path.stat().st_size,'sha256':sha}


# ----------------------------------------
def archive(name: str,paths: list[Path]) -> dict:
    """
    機能: 元相対構造のSourceを決定的ZIPと索引へ保存する。
    引数: name(str)、paths(list[Path])は正式名と対象。
    返り値: dictは索引。
    """
    target=TRIAL/(name+'.zip')
    with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED,compresslevel=9) as z:
        for p in sorted(paths):
            info=zipfile.ZipInfo(p.relative_to(ROOT).as_posix(),(2026,11,18,0,0,0));info.compress_type=zipfile.ZIP_DEFLATED
            z.writestr(info,p.read_bytes())
    result={'試行':206,'archive':ref(target),'members':[ref(p) for p in sorted(paths)],'金融実行なし':True,
        '原板と生成入力の重複収録なし':True,'dependencies':{'Python':'3.14.3','numpy':'2.5.4','tzdata':'2026.6'}}
    (TRIAL/(name+'索引.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return result


# ----------------------------------------
def main() -> None:
    """
    機能: 純Source・全件独立票・版2束縛票を保存し、ZIPの別展開で人工票を再現する。
    引数: なし。
    返り値: None。金融Sourceと金融結果は生成・変更しない。
    """
    paths=[p for p in HERE.iterdir() if p.suffix in ('.py','.md','.json')]
    pure=archive('純特徴Source',paths)
    check=ROOT/'work/206独立確認'
    condition=archive('純条件独立Source',[check/'純条件を独立確認する.py',check/'版2へ束縛する.py'])
    audit=TRIAL/'監査';audit.mkdir(exist_ok=True)
    for name in ('純判定独立確認206.json','純判定独立確認206_v2.json'):shutil.copy2(check/name,audit/name)
    dest=ROOT/'work/206純Source展開';assert not dest.exists();dest.mkdir(parents=True)
    for index in (pure,condition):
        with zipfile.ZipFile(ROOT/index['archive']['path']) as z:
            for r in index['members']:
                body=z.read(r['path']);target=dest/r['path'];target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(body)
                assert hashlib.sha256(body).hexdigest()==r['sha256']
                if target.suffix=='.py':compile(body,str(target),'exec')
    extracted=dest/'scripts/指数間純特徴206'
    subprocess.run([sys.executable,'-X','utf8',str(extracted/'人工確認.py')],check=True)
    assert (extracted/'人工確認.json').read_bytes()==(HERE/'人工確認.json').read_bytes()
    proof={'試行':206,'成功':True,'純特徴ZIP':pure['archive'],'純条件独立ZIP':condition['archive'],
        '全memberSHA一致':len(pure['members'])+len(condition['members']),'別展開人工19項目の票byte同体':True,
        '純全件独立確認':ref(INPUT/'独立純特徴確認.json'),'実prefix確認':ref(INPUT/'実prefix確認.json'),
        '版2純条件独立確認':ref(audit/'純判定独立確認206_v2.json')}
    (TRIAL/'純Source展開確認.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(proof,ensure_ascii=False),flush=True)


# ----------------------------------------
if __name__=='__main__':main()
