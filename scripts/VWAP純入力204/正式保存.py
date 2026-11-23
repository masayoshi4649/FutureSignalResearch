"""204純入力の最小Sourceと保存索引を固定する。原板・キャッシュは複製しない。"""
from pathlib import Path
import hashlib
import json
import re
import zipfile

ROOT=Path(__file__).resolve().parents[2];HERE=Path(__file__).parent
STUDY=ROOT/'study/00204_VWAPと価格構造の両指数入口';DATA=ROOT/'inputs/00204_両指数の配信VWAP純入力'


def record(path: Path) -> dict:
    """
    機能: 正式成果物の相対パスと内容指紋を作る。
    引数: path(Path)。
    返り値: dictはpath・bytes・SHA256。
    """
    body=path.read_bytes();return {'path':path.relative_to(ROOT).as_posix(),'bytes':len(body),'sha256':hashlib.sha256(body).hexdigest()}


def main() -> None:
    """
    機能: 純入力のSourceをZIPへ保存し、正本指紋とリンクを検査する。
    引数: なし。
    返り値: None。固定済みの売買条件や金融結果は生成しない。
    """
    sources=sorted(p for p in HERE.iterdir() if p.is_file() and p.suffix in ('.py','.json','.md'))
    target=STUDY/'純入力Source.zip'
    if not target.exists():
        with zipfile.ZipFile(target,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as z:
            for p in sources:
                info=zipfile.ZipInfo(p.relative_to(ROOT).as_posix(),(2000,1,1,0,0,0));info.compress_type=zipfile.ZIP_DEFLATED
                z.writestr(info,p.read_bytes())
    with zipfile.ZipFile(target) as z:
        assert sorted(z.namelist())==sorted(p.relative_to(ROOT).as_posix() for p in sources)
        for p in sources:assert z.read(p.relative_to(ROOT).as_posix())==p.read_bytes()
    files=sorted(p for p in DATA.rglob('*') if p.is_file())+sorted(STUDY.glob('*.md'))+[target]
    result={'金融未使用':True,'状態':'TOPIX純入力監査と仮説案。売買条件・新金融は未実行。',
        'Source':[record(p) for p in sources],'正本':[record(p) for p in files],
        '原板':'201抽出前固定票の83TOPIX場を共用。原板複製なし。','入力保存':'q0キャッシュはinputsへ一度だけ保存。Source ZIPへは複製しない。'}
    out=STUDY/'保存索引.json';body=(json.dumps(result,ensure_ascii=False,indent=2)+'\n').encode()
    if out.exists():assert out.read_bytes()==body
    else:out.write_bytes(body)
    checks=0
    for md in [*STUDY.glob('*.md'),DATA/'README.md']:
        for link in re.findall(r'\]\(([^)]+)\)',md.read_text(encoding='utf-8')):
            if '://' in link or link.startswith('#'):continue
            assert (md.parent/link.split('#')[0]).resolve().exists(),(md,link);checks+=1
    print('Source',len(sources),'正本',len(files),'リンク',checks,'一致')


if __name__=='__main__':main()
