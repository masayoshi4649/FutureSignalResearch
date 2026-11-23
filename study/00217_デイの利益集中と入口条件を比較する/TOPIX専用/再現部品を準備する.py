"""恒久アーカイブの同一指紋の旧部品を作業領域に用意する。"""
from hashlib import sha256
from pathlib import Path
from zipfile import ZipFile
import json

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def main() -> None:
    """
    機能：固定一覧の旧部品をSHA256照合し、不足分だけを元の作業位置に復元する。
    引数：なし。
    返り値：None。既存ファイルの内容が異なる場合は処理を終了する。
    """
    entries = json.loads((HERE/'復元部品.json').read_text(encoding='utf-8'))
    for row in entries:
        target = (ROOT/row['部品']).resolve()
        assert target.is_relative_to(ROOT/'work')
        with ZipFile(ROOT/row['元']) as archive:
            archived = archive.read(row['部品'])
        assert sha256(archived).hexdigest()==row['SHA256']
        if target.exists():
            assert sha256(target.read_bytes()).hexdigest()==row['SHA256'],target
        else:
            target.parent.mkdir(parents=True,exist_ok=True)
            target.write_bytes(archived)
    print('旧部品の指紋照合完了',len(entries))


if __name__=='__main__':
    main()
