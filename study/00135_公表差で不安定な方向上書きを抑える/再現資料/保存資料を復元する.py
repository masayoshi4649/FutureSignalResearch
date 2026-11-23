"""135の履歴F1の全15源を復元し、絶対パスだけを別名の再集計用台帳へ写像する。"""
from pathlib import Path
from datetime import datetime, timezone
import argparse
import gzip
import hashlib
import json
import zipfile

FORMAL = Path(__file__).resolve().parent.parent
ROOT = FORMAL.parents[1]
OWN = 'work/公表差で反転が不安定な入口を保守化する'
F1_SHA = '841514160f4ea92036a06688cbce5b1404f6f3ae0040751e0a7aa44b0211a0c2'


def sha(body: bytes) -> str:
    """
    機能: 復元内容の指紋を返す。
    引数: body(bytes)。
    返り値: strはSHA256。
    """
    return hashlib.sha256(body).hexdigest()


# ----------------------------------------
def put(root: Path, name: str, body: bytes) -> None:
    """
    機能: 復元先内部へ同体bytesを保存する。
    引数: root(Path)、name(str)は相対位置、body(bytes)。
    返り値: None。同名は完全同体に限る。
    """
    path = (root / name).resolve(); assert path.is_relative_to(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        assert path.read_bytes() == body, name
    else:
        with path.open('xb') as handle:
            handle.write(body)


# ----------------------------------------
def main() -> None:
    """
    機能: 固定コード/旧保存観測/方向票を新規workへ復元する。
    引数: CLI --destination(Path)。
    返り値: None。Raw・巨大派生入力・金融計算・CSV生成を呼ばない。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('--destination', required=True, type=Path)
    args = parser.parse_args(); destination = args.destination.resolve()
    assert destination.is_relative_to(ROOT / 'work') and not destination.exists()
    destination.mkdir(parents=True)
    manifest = json.loads((FORMAL / '保管索引.json').read_bytes())
    for key in ('共有固定コード', '追加固定コード', '後発コード'):
        if key not in manifest:
            continue
        item = manifest[key]
        path = ROOT / item['保存元ZIP'] if key == '共有固定コード' else FORMAL / '再現資料' / item['ZIP']
        assert sha(path.read_bytes()) == item['ZIP_SHA256']
        with zipfile.ZipFile(path) as z:
            assert z.testzip() is None
            for source in item['格納源']:
                body = z.read(source['path']); assert sha(body) == source['sha256']
                put(destination, source['path'], body)
    for item in manifest['新共用入力'] + manifest['共有参照']:
        body = (ROOT / item['保存元']).read_bytes(); assert sha(body) == item['保存SHA256']
        decoded = gzip.decompress(body) if item['形式'] == 'gzip' else body
        assert sha(decoded) == item['解凍SHA256']
        put(destination, item['復元先'], decoded)
    original = (FORMAL / '検査/F1.json').read_bytes(); assert sha(original) == F1_SHA
    put(destination, f'{OWN}/F1.json', original)
    f1 = json.loads(original)
    anchor = next(Path(p) for p in f1['ファイル'] if p.endswith('study\\00135_公表差で不安定な方向上書きを抑える\\README.md'))
    old_root = anchor.parents[2]
    mapped = {str(destination / Path(p).relative_to(old_root)): h for p, h in f1['ファイル'].items()}
    assert len(mapped) == 15 and all(sha(Path(p).read_bytes()) == h for p, h in mapped.items())
    ledger = {'成功': True, '試行': 135, '段階': '保存観測の再集計用パス照合。金融前固定ではない',
              '作成UTC': datetime.now(timezone.utc).isoformat(), '元F1_SHA256': sha(original),
              '元の履歴F1を変更': False, '新しい事前F1として扱う': False,
              '変更内容': '全15源のSHAを保ち、repo内相対位置を新workへ写像', 'ファイル': mapped}
    put(destination, f'{OWN}/再現用パス台帳.json', (json.dumps(ledger,ensure_ascii=False,indent=2)+'\n').encode('utf-8'))
    print(json.dumps({'成功': True, '復元源': 15, '原F1同体': True, '復元先': str(destination),
                      '原板/巨大派生入力読取': False, '金融実行': False},ensure_ascii=False))


if __name__ == '__main__':
    main()
