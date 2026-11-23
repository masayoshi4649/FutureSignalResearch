# 15分定時の局所再開

[試行50の計画](../../study/00050_15分定時の局所再開/検証計画.md)を実装する。旧49の価格入力、数値銀行、時計、先着、運用を直接使用し、旧コードの大域値を変更しない。

- `入口.py`：当時公開足だけで調整/失敗/再開を監視し、最初の定時枠で消費する。
- `検証.py`：固定と一度の市場実行。S1は旧結果を参照し、P0/P1だけを再生する。
- `保存物確認.py`：保存物をBBO・現金・独立先着へ照合する。
- `レポート.py`：市場計算を行わず保存正本から帳票を作る。

環境はPython 3.14.3、NumPy 2.5.3。PowerShellでリポジトリルートから実行する。人工検査は日本語ファイル名のため、自動discoverに任せず明示実行する。

```powershell
C:/Python314/python.exe -X utf8 scripts/局所再開/入口の人工検査.py
C:/Python314/python.exe -X utf8 scripts/局所再開/接続の人工検査.py
C:/Python314/python.exe -X utf8 scripts/局所再開/検証.py --freeze
C:/Python314/python.exe -X utf8 scripts/局所再開/検証.py --run
C:/Python314/python.exe -X utf8 scripts/局所再開/保存物確認.py --self-test
C:/Python314/python.exe -X utf8 scripts/局所再開/保存物確認.py --run --viewer-url http://127.0.0.1:8092
C:/Python314/python.exe -X utf8 scripts/局所再開/レポート.py
C:/Python314/python.exe -X utf8 scripts/局所再開/レポート.py --check
```

固定/市場実行/証明は既存成果物の上書きを拒否する。再実行を強行せず、開始したプロセスと成果物を先に確認する。旧49の元監査129差と期限同秒補足を両方保持し、新候補の先着期待値には補足側の規約を使用する。
