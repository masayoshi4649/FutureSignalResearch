package minichart

import warm "github.com/masayoshi4649/SessionTradeExecuter/chartwarmup96"

// GateAssessmentRecord は出生の金融採否と共有された枠時点の技法判定を結びます。
type GateAssessmentRecord struct {
	Key        string              `json:"key"`
	Ordinal    int                 `json:"ordinal"`
	Source     SourceIdentity      `json:"source"`
	Assessment TechnicalAssessment `json:"assessment"`
}

// appendChartHistory は当場で公開済みの直近三足だけを値で保持します。
//
// 引数: history([]warm.Snapshot)とsnapshot(warm.Snapshot)は過去と新しい公開値です。
// 返り値: []warm.Snapshotは新しい連続性を技法側で検査する最大三要素です。
func appendChartHistory(history []warm.Snapshot, snapshot warm.Snapshot) []warm.Snapshot {
	result := append(append([]warm.Snapshot{}, history...), snapshot)
	if len(result) > 3 {
		result = result[len(result)-3:]
	}
	return result
}
