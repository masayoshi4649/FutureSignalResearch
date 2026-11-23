"""固定入口の寄り前通知に、東証相場表の現物前場リターンを事後照合する。"""

import gzip
import hashlib
import json
import statistics
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.request import urlopen

import pymupdf


保存先 = Path(__file__).resolve().parent
キャッシュ = 保存先.parents[1] / "work" / "214現物日報"
日本時間 = timezone(timedelta(hours=9))
対象銘柄 = {"1321": "日経ETF", "1306": "TOPIX ETF", "6857": "アドバンテスト", "8035": "東京エレクトロン"}
東証休場 = {"2026-09-21", "2026-09-22", "2026-09-23", "2026-10-12", "2026-11-03"}


def 前場価格(path: Path) -> dict:
    """機能：東証日報の午前欄に限り、対象4銘柄の始値と終値を取得する。

    引数：path（Path）は現物の日次相場表PDF。
    返り値：dict。銘柄コードに対応する前場始値・終値・紙面のPDFページ番号。
    """
    結果 = {}
    with pymupdf.open(path) as 資料:
        for 番号, ページ in enumerate(資料, 1):
            語 = ページ.get_text("words")
            午前 = [v for v in 語 if v[4] == "午前"]
            if len(午前) != 1 or not 310 < 午前[0][0] < 330:
                continue
            for 左, 上, _, _, 値, *_ in 語:
                if 値 not in 対象銘柄 or not 69 < 左 < 79:
                    continue
                行 = [v for v in 語 if abs(v[1] - 上) < 1]
                # 日報の金額欄は右揃えで、午前4列の右端は342、402、462、522。
                四本値 = []
                for 右端 in (342, 402, 462, 522):
                    読み値 = [v[4] for v in 行 if abs(v[2] - 右端) < 2]
                    if len(読み値) != 1:
                        raise ValueError((path, 値, 番号, 右端, 読み値))
                    四本値.append(float(読み値[0].replace(",", "")))
                始, 高, 安, 終 = 四本値
                if not 安 <= min(始, 終) <= max(始, 終) <= 高 or 値 in 結果:
                    raise ValueError((path, 値, 四本値))
                結果[値] = {"始値": 始, "終値": 終, "ページ": 番号}
            if len(結果) == len(対象銘柄):
                break
    if set(結果) != set(対象銘柄):
        raise ValueError((path, list(結果)))
    return 結果


def 実行() -> None:
    """機能：試行213の9時前通知と当日公開後の現物価格を対応付ける。

    引数：なし。
    返り値：None。東証PDFをworkにキャッシュし、抽出結果を本試行のJSONに保存する。
    """
    元 = next(保存先.parent.glob("00213*/同期照合の明細.json.gz"))
    通知一覧 = json.loads(gzip.decompress(元.read_bytes()))
    場別 = {}
    休場件数 = {}
    for 指数, 一覧 in 通知一覧.items():
        休場件数[指数] = 0
        for 通知 in 一覧:
            時刻 = datetime.fromtimestamp(通知["通知"], 日本時間)
            if 時刻.hour != 8 or 時刻.minute < 45:
                continue
            日付 = 時刻.date().isoformat()
            if 日付 in 東証休場:
                休場件数[指数] += 1
                continue
            場 = 場別.setdefault(日付, {"通知": {}})
            if 指数 in 場["通知"]:
                raise ValueError((指数, 日付, "複数の入口"))
            場["通知"][指数] = {"日本時間": 時刻.isoformat(), "側": "買" if 通知["側"] == 0 else "売"}

    # ----------------------------------------
    キャッシュ.mkdir(parents=True, exist_ok=True)
    符号付き = {名: {列: [] for 列 in (*対象銘柄, "半導体2社平均")} for 名 in 通知一覧}
    for 日付, 場 in sorted(場別.items()):
        日 = 日付.replace("-", "")
        url = f"https://www.jpx.co.jp/automation/markets/statistics-equities/daily/files/{日[:6]}/stq_{日}.pdf"
        path = キャッシュ / f"{日付}.pdf"
        if not path.exists():
            with urlopen(url, timeout=40) as 応答:
                pdf = 応答.read()
            if not pdf.startswith(b"%PDF-"):
                raise ValueError(url)
            path.write_bytes(pdf)
        場.update({"出典": url, "SHA256": hashlib.sha256(path.read_bytes()).hexdigest(), "現物": 前場価格(path)})
        for 指数, 通知 in 場["通知"].items():
            符号 = 1 if 通知["側"] == "買" else -1
            変化 = {列: 符号 * (足["終値"] / 足["始値"] - 1) * 100 for 列, 足 in 場["現物"].items()}
            変化["半導体2社平均"] = statistics.mean(変化[列] for 列 in ("6857", "8035"))
            for 列, 騰落率 in 変化.items():
                符号付き[指数][列].append(騰落率)

    # ----------------------------------------
    集計 = {}
    for 指数, 対応 in 符号付き.items():
        集計[指数] = {}
        for 列, 値 in 対応.items():
            集計[指数][列] = {
                "件数": len(値), "同方向": sum(v > 0 for v in 値), "横ばい": 値.count(0),
                "平均パーセント": round(statistics.mean(値), 4),
                "中央値パーセント": round(statistics.median(値), 4),
            }
    結果 = {"同期照合SHA256": hashlib.sha256(元.read_bytes()).hexdigest(), "PyMuPDF": pymupdf.VersionBind,
          "東証休場除外": 休場件数, "集計": 集計, "日別": dict(sorted(場別.items()))}
    (保存先 / "現物の午前値動き.json").write_text(json.dumps(結果, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    実行()
