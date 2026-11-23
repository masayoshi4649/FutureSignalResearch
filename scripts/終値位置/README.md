# CCI突破と足内終値位置

[試行00033](../../study/00033_CCI突破と足内終値位置/README.md)の二入口・三運用比較。T0は固定31C0、T1だけ同じ公開3分足の実方向CLVstrict正を追加する。旧T0_X0はA5参考、新T0_XF/T1_XFは現在の返済BBO含み益から往復費用122円を引いた金額がstrict正になれば追尾を起動する。売買対称・最低名目同値床・非緩和を維持する。

旧31のCCI/BB/context/case六明細は[入口参照](../../study/00033_CCI突破と足内終値位置/入口参照.json)から共有する。新大明細は形状選別・全運用詳細・追尾の三系列のみで、Git外のworkへ保存する。先着ラベルをlive信号へ渡さず、旧ケースの選別は固定後の評価にだけ用いる。

Python3.14.3・NumPy2.5.3。主/独立準備と最終人工の一致後、出典固定と正式再生を行う。正式出力は上書きしない。

```powershell
C:/Python314/python.exe -X utf8 scripts/終値位置/検証.py --prepare
C:/Python314/python.exe -X utf8 scripts/終値位置/状態独立確認.py --prepare
C:/Python314/python.exe -X utf8 scripts/終値位置/合成検証.py --final
C:/Python314/python.exe -X utf8 scripts/終値位置/検証.py
C:/Python314/python.exe -X utf8 scripts/終値位置/状態独立確認.py --実行許可
C:/Python314/python.exe -X utf8 scripts/終値位置/追尾独立確認.py --実行許可
C:/Python314/python.exe -X utf8 scripts/終値位置/独立監査.py --api-base http://127.0.0.1:8092
C:/Python314/python.exe -X utf8 scripts/終値位置/対応診断.py
C:/Python314/python.exe -X utf8 scripts/終値位置/レポート.py
```

全66場は既使用。片道11円・micro倍率10円/pt・ラージBBO代理、追加片道5/10ptの同約定費用感度を記録する。起動想定は片道5ptで固定し、感度ごとに起動を変えない。CLV幅0と符号選別、純入口と現実参加、共通建玉と片側参加、名目床と費用後損益を分ける。前ATR距離は診断だけに留め、結果に合わせた帯域選別を追加しない。
