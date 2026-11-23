"""133の固定コードと保存入力を新規workへ復元し、履歴F1を改変せず再現用パスを写像する。"""
from pathlib import Path
from datetime import datetime, timezone
import argparse
import gzip
import hashlib
import json
import zipfile

FORMAL = Path(__file__).resolve().parent.parent
ROOT = FORMAL.parents[1]


def sha(body: bytes) -> str:
    """
    機能: 復元するbytesの指紋を返す。
    引数: body(bytes)。
    返り値: strはSHA256。
    """
    return hashlib.sha256(body).hexdigest()


# ----------------------------------------
def put(root: Path, name: str, body: bytes) -> None:
    """
    機能: 新規復元先内へ同体bytesを保存する。
    引数: root(Path)、name(str)は相対先、body(bytes)。
    返り値: None。原本を更新せず、同名は同体だけ許す。
    """
    target = (root / name).resolve()
    assert target.is_relative_to(root)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        assert target.read_bytes() == body
        return
    with target.open('xb') as handle:
        handle.write(body)


# ----------------------------------------
def restore_item(destination: Path, item: dict) -> None:
    """
    機能: 正式な同体又はgzip資源を照合して作業用に戻す。
    引数: destination(Path)、item(dict)は保存元/形式/復元先/指紋。
    返り値: None。
    """
    body = (ROOT / item['保存元']).read_bytes()
    assert sha(body) == item['保存SHA256']
    expanded = gzip.decompress(body) if item['形式'] == 'gzip' else body
    assert sha(expanded) == item['解凍SHA256']
    put(destination, item['復元先'], expanded)


# ----------------------------------------
def main() -> None:
    """
    機能: コード/保存観測からの再集計を再現する新規workを作る。
    引数: CLI --destination(Path)、--without-observations(bool)はRaw再観測時の任意指定。
    返り値: None。177MB共用Input/Raw/実行体を複製せず、金融計算を呼ばない。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('--destination', required=True, type=Path)
    parser.add_argument('--without-observations', action='store_true')
    args = parser.parse_args()
    destination = args.destination.resolve()
    assert destination.is_relative_to(ROOT / 'work') and not destination.exists()
    destination.mkdir(parents=True)
    manifest = json.loads((FORMAL / '保管索引.json').read_bytes())
    for key in ('固定コード', '後発コード'):
        if key not in manifest:
            continue
        item = manifest[key]
        archive = FORMAL / '再現資料' / item['ZIP']
        assert sha(archive.read_bytes()) == item['ZIP_SHA256']
        with zipfile.ZipFile(archive) as z:
            assert z.testzip() is None
            for source in item['格納源']:
                body = z.read(source['path'])
                assert sha(body) == source['sha256']
                put(destination, source['path'], body)
    for item in manifest['新共用入力'] + manifest['共有参照'] + manifest['小型段階証跡']:
        restore_item(destination, item)
    if not args.without_observations:
        restore_item(destination, manifest['新正逆観測'])
    for name in ('F0', 'F1'):
        put(destination, f'work/133探索期限の評価/{name}.json', (FORMAL / '検査' / (name + '.json')).read_bytes())
    original = (FORMAL / '検査/F1.json').read_bytes()
    assert sha(original) == '98379bf9359ab918db931f649298fec88826bb2df71330c459612eec786c70a3'
    fixed = json.loads(original)
    anchor = next(Path(p) for p in fixed['ファイル'] if p.endswith('study\\00133_全場参加を維持して強い入口の探索期限を延ばす\\README.md'))
    old_root = anchor.parents[2]
    mapped = {str(destination / Path(name).relative_to(old_root)): expected for name, expected in fixed['ファイル'].items()}
    replay = {'成功': True, '試行': 133, '段階': '保存観測の再集計用パス照合。金融前固定ではない',
              '作成UTC': datetime.now(timezone.utc).isoformat(), '元F1_SHA256': sha(original),
              '元の履歴F1を変更': False, '新しい事前F1として扱う': False,
              '変更内容': '元F1の各ファイルのrepo内相対位置を新規復元先へ写像。源SHAは全て同じ',
              '未複製の外部源': manifest['意図して複製しない固定源'],
              '注意': '実行体/177MB入力の存在を保証する新F1ではない。保存済み観測の再集計CLIが使う入力/コードを照合する台帳',
              'ファイル': mapped}
    ledger = 'work/133探索期限の評価/再現用パス台帳.json'
    put(destination, ledger, (json.dumps(replay, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))
    print(json.dumps({'成功': True, '復元先': str(destination), '保存観測を復元': not args.without_observations,
                      '原F1_SHA256': sha(original), '再現用パス台帳SHA256': sha((destination / ledger).read_bytes()),
                      '原F1変更': False, 'Raw/177MB/実行体の複製': False, '金融計算': False}, ensure_ascii=False))


if __name__ == '__main__':
    main()
