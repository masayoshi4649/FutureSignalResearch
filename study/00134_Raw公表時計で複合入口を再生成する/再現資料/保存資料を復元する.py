"""134の共有63源・追加15源と保存入力を復元し、履歴F1と再集計用台帳を分ける。"""
from pathlib import Path
from datetime import datetime, timezone
import argparse
import gzip
import hashlib
import json
import zipfile

FORMAL = Path(__file__).resolve().parent.parent
ROOT = FORMAL.parents[1]
RUN = 'work/134公表時計の評価'
F1_SHA = 'd76eb2017da90f160b1b6c78485a26c28fa63f03954ec7748bc6b49802396eb6'


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
    機能: 新規復元先の内部へ同体bytesを保存する。
    引数: root(Path)、name(str)は相対先、body(bytes)。
    返り値: None。同名既存は完全同体に限る。
    """
    target = (root / name).resolve()
    assert target.is_relative_to(root)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        assert target.read_bytes() == body, name
    else:
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
    機能: 保存観測の再集計用workを作り、元のF0/F1を同体保持する。
    引数: CLI --destination(Path)、--without-observations(bool)。
    返り値: None。Raw/83・84MB派生入力/実行体を複製せず、金融計算を呼ばない。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('--destination', required=True, type=Path)
    parser.add_argument('--without-observations', action='store_true')
    args = parser.parse_args()
    destination = args.destination.resolve()
    assert destination.is_relative_to(ROOT / 'work') and not destination.exists()
    destination.mkdir(parents=True)
    manifest = json.loads((FORMAL / '保管索引.json').read_bytes())
    for key in ('共有固定コード', '追加固定コード', '後発コード'):
        if key not in manifest:
            continue
        item = manifest[key]
        archive = ROOT / item['保存元ZIP'] if key == '共有固定コード' else FORMAL / '再現資料' / item['ZIP']
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
        put(destination, f'{RUN}/{name}.json', (FORMAL / '検査' / (name + '.json')).read_bytes())
    original = (FORMAL / '検査/F1.json').read_bytes()
    assert sha(original) == F1_SHA
    fixed = json.loads(original)
    anchor = next(Path(p) for p in fixed['ファイル'] if p.endswith('study\\00134_Raw公表時計で複合入口を再生成する\\README.md'))
    old_root = anchor.parents[2]
    mapped = {str(destination / Path(name).relative_to(old_root)): expected for name, expected in fixed['ファイル'].items()}
    replay = {'成功': True, '試行': 134, '段階': '保存観測の再集計用パス照合。金融前固定ではない',
              '作成UTC': datetime.now(timezone.utc).isoformat(), '元F1_SHA256': sha(original),
              '元の履歴F1を変更': False, '新しい事前F1として扱う': False,
              '変更内容': '元F1のrepo内相対位置だけを新規復元先へ写像。源SHAは全て同じ',
              '未複製の外部源': manifest['意図して複製しない固定源'],
              '注意': '実行体と巨大入力の存在を保証する新F1ではない。保存観測の再集計に使う入力とコードの照合台帳',
              'ファイル': mapped}
    ledger = f'{RUN}/再現用パス台帳.json'
    put(destination, ledger, (json.dumps(replay, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))
    print(json.dumps({'成功': True, '復元先': str(destination), '原F1_SHA256': sha(original),
                      '保存観測を復元': not args.without_observations, '原F1変更': False,
                      '再現用パス台帳SHA256': sha((destination / ledger).read_bytes()),
                      'Raw/巨大入力/実行体の複製': False, '金融計算': False}, ensure_ascii=False))


if __name__ == '__main__':
    main()
