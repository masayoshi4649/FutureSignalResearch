"""保存したgzipから元metadata JSONの全bytesだけを未作成work先へ復元する。"""

import argparse
import gzip
import hashlib
import json
from pathlib import Path


ROOT = next(p for p in Path(__file__).resolve().parents if (p / 'AGENTS.md').is_file() and (p / 'study').is_dir())


def digest(body: bytes) -> str:
    """機能: 内容を解析せずbytesのSHAを計算する。

    引数: body(bytes)は任意の内容。
    返り値: strはSHA256。
    """
    return hashlib.sha256(body).hexdigest()


def restore(index: Path, expected: str, item: str, output: Path) -> dict:
    """機能: 索引とgzipを認証し元JSONの全bytesを復元する。

    引数: index/output(Path)、expected/item(str)は索引・未作成work先・SHA・ID。
    返り値: dictは復元先Ref。payloadのJSON意味解析と金融計算はしない。
    """
    if not index.is_absolute() or not output.is_absolute() or output.exists() or not output.is_relative_to(ROOT / 'work'):
        raise ValueError('索引は絶対位置、復元先は未作成workだけ')
    raw = index.read_bytes()
    if digest(raw) != expected:
        raise ValueError('復元metadataのSHA差')
    metadata = json.loads(raw)
    rows = [r for r in metadata['項目'] if r['id'] == item]
    if metadata['試行'] != 116 or metadata['成功'] is not True or len(rows) != 1:
        raise ValueError('復元する項目は一つだけ')
    row = rows[0]
    source = (index.parent / row['stored_relative']).resolve()
    if not source.is_relative_to(index.parent.resolve()):
        raise ValueError('保存gzipの相対位置が不正')
    encoded = source.read_bytes()
    if digest(encoded) != row['stored']['sha256'] or len(encoded) != row['stored']['bytes']:
        raise ValueError('保存gzipのSHA/size差')
    body = gzip.decompress(encoded)
    if digest(body) != row['original']['sha256'] or len(body) != row['original']['bytes']:
        raise ValueError('元JSON bytesのSHA/size差')
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('xb') as stream:
        stream.write(body)
    if digest(output.read_bytes()) != row['original']['sha256']:
        raise ValueError('復元後SHA差')
    return {'成功': True, 'path': str(output), 'sha256': row['original']['sha256'], 'bytes': len(body),
            'JSON意味解析': False, '金融再計算': False}


def main() -> None:
    """機能: 索引で選んだ一つのmetadataをCLIから復元する。

    引数: CLI index/sha256/item/output(str)は索引・期待SHA・ID・新規先。
    返り値: None。復元Refだけを表示する。
    """
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--index', required=True, type=Path)
    p.add_argument('--sha256', required=True)
    p.add_argument('--item', required=True)
    p.add_argument('--output', required=True, type=Path)
    a = p.parse_args()
    print(json.dumps(restore(a.index.resolve(), a.sha256, a.item, a.output.resolve()), ensure_ascii=False))


if __name__ == '__main__':
    main()
