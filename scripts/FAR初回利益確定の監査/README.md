# H0金融監査（人工検査段階）

人工だけの独立Python監査。固定96の出生枠・Source・予約・約定・全経路u/W・Account MTM/DD・費用・最終0の規範をSHA importで継承する。空Harvestは旧markを直再用し、H0だけ初回strict u正益のActivation.gainを最低床へ重ねる。Go計算器・市場・原板は呼ばない。

`HarvestPath(actual, audit, gate_provider)` の `step(q, batches, atr)` / `timer(at, batches)` / `grid(at)` / `finish()` は固定96と同型。`gate_provider.claim(key, opportunity)` は金融前資格後の独立候補へ判断を返す。H0の外Keyとconfig.harvest_policyだけを初期化用に明示投影し、注文・約定・Source・MTM・未知を落とさない。期待IDは元のH0 Keyから生成する。金融topとconfigのタグ集合を厳密に検査し、追加された未知字段も拒否する。

新H0 markは、pre_fillで初u正益・床を保存し、既存fillとSource処理後のafter_sourceで未予約残量だけを要求する。最低床はmax(0,初Activation.gain)、旧固定2ATR床と前回床をmaxで重ねる。専用理由は「初回費用後残玉正益の全量確定」。約定のstrict後続Index/遅延/正常気配、半円の費用、Source ceil配分・全残、予約込みcapと全正常行の両phase評価は継承する。

Go型の停止人工4場面×16口座を `inspect_fixture(value)` で照合する。AB callbackはGo人工と同じ常時allowの独立定数から返し、保存Gateを期待判断へ読み戻さない。金融前資格とcallbackの一回集合も照合する。これを自然3分・15分技法の成立、原板からのSource/ATR生成、H0市場収益の証明にはしない。固定技法照合moduleはSHA参照しているが、この手製allow scopeでは技法数値の新検査数は0。

```powershell
& work/venvs/technical-tree/Scripts/python.exe -B -X utf8 scripts/FAR初回利益確定の監査/初回利益確定の金融照合.py --fixtures work/97利益確定案/人工/停止版 --out work/97金融監査案/新規人工結果.json
& work/venvs/technical-tree/Scripts/python.exe -B -X utf8 scripts/FAR初回利益確定の監査/破損を確認する.py --fixtures work/97利益確定案/人工/停止版 --out work/97金融監査案/新規破損結果.json
```

床の緩和、初u=0への保存証拠改変、起動出典の未来、Source前への要求phase、同原行fill出典、Source/保護注文順の入替、予約超過、旧reason、Key/configの不一致、未知tagを壊した11反証を拒否する。u=0反証は保存値の破損検出であり、Go側の直接単元u=0試験やSource自然到達可能性とは区別する。

次のTape接続では、同じ `HarvestPath` へ全Scalar行・Source・時計を公開順に供給し、gate providerを固定96の純技法再計算へ置き換える必要がある。現在のAPI人工でその接続や原板出典を成功扱いしない。自然gateなら候補なしも含む全grid Currentと公開チャート、H0/旧Key別のcallbackを結び、Rootの固定96全件/Tape構築へ依存を明示する。旧対照8口座の96全文、全入力・コード指紋、全場末完結の市場側照合はまだ実行していない。

旧96・Go金融・条件・正式記録は編集0。未参加の仮想利益、退出後価格、理想ピークは評価しない。

## 完成Tapeと現在候補の接続

`Tapeと金融の照合.py` の `inspect_tape(tape, new97)` は、全Scalar、Source通知、Force、枠を独立金融へ配送する。各現在候補と固定96の純Python技法から全checkを再計算し、保存された採否を期待値へ読み戻さない。人工6場面×16会計の302,900照合、新callback80件は一致し、接続の破損12種類を拒否した。この6場面にはForceがないため、そのpositive接続を成功扱いしない。[証拠](../../study/00097_初回費用後利益の全量確定/Tape金融接続人工の停止.json)

原板、自然Source、ATR、確定3/15分数値の新生成はこの接続で実行しない。それらは固定96とTape構築の出典へ結ぶ。市場の2/54場は条件と入力集合を固定後に別実行する。
