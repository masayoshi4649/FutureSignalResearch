"""市場前原文458から15行だけを校正し、結合器の固定入力93を新規先へ復元する。"""

import argparse
import hashlib
import json
from pathlib import Path


ROOT = Path(r'S:\GitHub\masayoshi4649\FutureSignalResearch')
SOURCE_SHA = '45837672457a1b9119a840a38430a5a28c8f24252ea3b3918f23a681c5251c10'
TARGET_SHA = '93d864b4afd115ca68c5f40191a87d1efb10b8cb6bccf35aa7946fd2d8b4b3c6'
CURRENT = ROOT / 'study/00114_順行と反転の取得確認を分ける/設定と結果.md'


def digest(path: Path) -> str:
    """機能: 明示ファイルの全bytes指紋を返す。

    引数: path(Path)は原文・差分・現在表・新規出力。
    返り値: strはSHA256。原板/Native/CSVは読まない。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def restore(source: Path, patch: Path, patch_sha: str, output: Path) -> dict:
    """機能: 15行の前値と固定SHAを確認し、93の完全同bytesを新規先だけへ保存する。

    引数: source/patch/output(Path)、patch_sha(str)は元458・差分・未作成先・差分SHA。
    返り値: dictは新規復元Refと前後不変。元原文と現在結果表へは書かない。
    """
    if not all(path.is_absolute() for path in (source, patch, output)):
        raise ValueError('全て絶対pathが必要')
    source, patch, output = source.resolve(), patch.resolve(), output.resolve()
    if output.exists() or output in (source, patch, CURRENT.resolve()):
        raise ValueError('元原文/差分/現在結果表/既存先への書込みは禁止')
    if digest(patch) != patch_sha or digest(source) != SOURCE_SHA:
        raise ValueError('元458又は差分のSHA不一致')
    data = json.loads(patch.read_text(encoding='utf-8'))
    if (data['version'], data['trial'], data['source']['sha256'], data['target_sha256']) != (1, 114, SOURCE_SHA, TARGET_SHA):
        raise ValueError('114の458から93への固定差分だけ')
    edits = data['edits']
    if len(edits) != 15 or [row['line'] for row in edits] != sorted({row['line'] for row in edits}):
        raise ValueError('順序付き重複なしの15行だけ')
    before = {str(source): digest(source), str(patch): digest(patch)}
    if CURRENT.exists():
        before[str(CURRENT.resolve())] = digest(CURRENT)
    lines = source.read_bytes().decode('utf-8').splitlines(keepends=True)
    for row in edits:
        line = row['line']
        if type(line) is not int or not 1 <= line <= len(lines) or lines[line - 1] != row['from']:
            raise ValueError('校正する行番号又は前値の不一致')
        lines[line - 1] = row['to']
    body = ''.join(lines).encode('utf-8')
    if hashlib.sha256(body).hexdigest() != TARGET_SHA:
        raise ValueError('復元93の全bytes不一致')
    if not output.parent.is_dir():
        raise ValueError('明示した出力の親folderが必要')
    with output.open('xb') as stream:
        stream.write(body)
    after = {path: digest(Path(path)) for path in before}
    if before != after or digest(output) != TARGET_SHA:
        raise ValueError('原文/現在表の変化又は新規出力差')
    return {'成功': True, '出力': {'path': str(output), 'sha256': TARGET_SHA}, '変更行数': 15,
            '入力前SHA256': before, '入力後SHA256': after, '前後不変': True,
            '金融条件/指標閾値の変更': False, '原板/Native/CSV読取': False}


def main() -> None:
    """機能: 明示された原文・固定差分から別の未作成ファイルだけを復元する。

    引数: CLI source/patch/patch-sha/output(str)は明示入力と新規先。
    返り値: None。少量の復元確認を表示し、表結合や金融を実行しない。
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--patch', type=Path, required=True)
    parser.add_argument('--patch-sha', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(restore(args.source, args.patch, args.patch_sha, args.output), ensure_ascii=False))


if __name__ == '__main__':
    main()
