"""132の方向同体検査に必要な非金融3源だけを新規workへ復元する。"""
from pathlib import Path
import argparse
import gzip
import hashlib
import json
import zipfile

FORMAL = Path(__file__).resolve().parent.parent
ROOT = FORMAL.parents[1]


def sha(body: bytes) -> str:
    """
    機能: 復元する内容の指紋を返す。
    引数: body(bytes)。
    返り値: strはSHA256。
    """
    return hashlib.sha256(body).hexdigest()


# ----------------------------------------
def put(root: Path, name: str, body: bytes) -> None:
    """
    機能: 新規復元先内へ同体bytesを保存する。
    引数: root(Path)、name(str)は相対先、body(bytes)。
    返り値: None。既存の原本へ上書きしない。
    """
    path = (root / name).resolve()
    assert path.is_relative_to(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        assert path.read_bytes() == body
        return
    with path.open('xb') as handle:
        handle.write(body)


# ----------------------------------------
def main() -> None:
    """
    機能: 小型コードと共有特徴/方向票/純chooserを未作成workへ復元する。
    引数: CLI --destination(Path)はrepoのwork内の未作成先。
    返り値: None。金融正本・Rawを読まず、損益を計算しない。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('--destination', type=Path, required=True)
    args = parser.parse_args()
    destination = args.destination.resolve()
    assert destination.is_relative_to(ROOT / 'work') and not destination.exists()
    destination.mkdir(parents=True)
    manifest = json.loads((FORMAL / '保管索引.json').read_bytes())
    code = manifest['コード']
    archive = FORMAL / '再現資料' / code['ZIP']
    assert sha(archive.read_bytes()) == code['ZIP_SHA256']
    with zipfile.ZipFile(archive) as z:
        assert z.testzip() is None
        for item in code['格納源']:
            body = z.read(item['path'])
            assert sha(body) == item['sha256']
            put(destination, item['path'], body)
    for item in manifest['共有非金融入力']:
        body = (ROOT / item['保存元']).read_bytes()
        assert sha(body) == item['保存SHA256']
        decoded = gzip.decompress(body)
        assert sha(decoded) == item['解凍SHA256']
        put(destination, item['復元先'], decoded)
    item = manifest['共有純関数']
    archive = ROOT / item['保存元ZIP']
    assert sha(archive.read_bytes()) == item['ZIP_SHA256']
    with zipfile.ZipFile(archive) as z:
        body = z.read(item['entry'])
    assert sha(body) == item['コードSHA256']
    put(destination, item['復元先'], body)
    print(json.dumps({'成功': True, '復元先': str(destination), '非金融入力数': 3,
                      '132金融実行': False, '金融正本読取': False, 'Raw読取': False,
                      '新CSV生成': False, '金融前F1作成': False}, ensure_ascii=False))


if __name__ == '__main__':
    main()
