"""201の純特徴だけのSourceカプセルを恒久保存する。金融Sourceは含めない。"""
from pathlib import Path
import hashlib
import json
import zipfile

ROOT=Path(__file__).resolve().parents[2]
HERE=Path(__file__).parent
DEST=ROOT/'study/00201_板数量の更新尺度を複合入口へ加える'
INPUT=ROOT/'inputs/00201_両指数の板数量純特徴'


# ----------------------------------------
def ref(path):
    """
    機能: 小さい保存資源を相対パスと指紋で識別する。
    引数: path(Path)は対象。
    返り値: dictはpath/bytes/sha256。
    """
    raw=path.read_bytes()
    return dict(path=path.relative_to(ROOT).as_posix(),bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())


# ----------------------------------------
def main():
    """
    機能: 純Sourceと仕様をZIPに保存し、原板と生成入力は参照だけにする。
    引数: なし。
    返り値: None。SourceZIPと索引を検証して保存する。
    """
    files=sorted([p for p in HERE.iterdir() if p.is_file() and p.suffix in ('.py','.md','.json')])
    files.append(INPUT/'README.md')
    DEST.mkdir(parents=True,exist_ok=True)
    archive=DEST/'純特徴Source.zip'
    assert not archive.exists(),'Sourceカプセルの意図しない上書きを防ぐ'
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED,compresslevel=9) as z:
        for path in files:
            info=zipfile.ZipInfo(path.relative_to(ROOT).as_posix(),date_time=(2026,11,18,0,0,0))
            info.compress_type=zipfile.ZIP_DEFLATED
            z.writestr(info,path.read_bytes())
    with zipfile.ZipFile(archive) as z:
        assert len(z.namelist())==len(files)
        for p in files:assert z.read(p.relative_to(ROOT).as_posix())==p.read_bytes()
    audit=json.loads((INPUT/'独立純特徴監査.json').read_text(encoding='utf-8'))
    assert audit['成功'] and audit['q0']==75675 and audit['比較']==529725
    value=dict(試行=201,用途='純特徴生成と独立監査のみ',SourceZIP=ref(archive),Source=[ref(p) for p in files],
               恒久入力=[ref(INPUT/name) for name in ('抽出前固定.json.gz','完了.json','独立純特徴監査.json')],
               原板複製=False,金融Source=False,workのみ依存=False,
               依存版=dict(Python='3.14.3',NumPy='2.5.4',orjson='3.13.0'),
               再現範囲='恒久純q0と全83原板から7板特徴を再生成。旧技術100特徴や金融結果は再生成範囲外。',
               移転制約='固定票内の元入力・Source絶対パスを維持する。ZIPの各Sourceはリポジトリ相対構造で展開できる。')
    (DEST/'純特徴Source索引.json').write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(成功=True,件数=len(files),ZIP=ref(archive)),ensure_ascii=False))


# ----------------------------------------
if __name__=='__main__':
    main()
