package actorport97

import (
	"fmt"

	actual "github.com/masayoshi4649/SessionTradeExecuter/minichart"
	harvest "github.com/masayoshi4649/SessionTradeExecuter/miniharvest"
	native "github.com/masayoshi4649/SessionTradeExecuter/mininative"
)

// GateAssessmentRecord は現在候補と純判定全文を金融JSON外へ固定します。
type GateAssessmentRecord struct {
	Key        string                     `json:"key"`
	Ordinal    int                        `json:"ordinal"`
	Source     actual.SourceIdentity      `json:"source"`
	Candidate  actual.EntryCandidate      `json:"candidate"`
	Assessment actual.TechnicalAssessment `json:"assessment"`
}

// CapturedHarvest は技法評価を金融JSON外へ一度だけ保存する観測用factoryです。
type CapturedHarvest struct {
	Records *[]GateAssessmentRecord
}

// New は停止金融factoryを包み、純評価の保存だけを追加します。
//
// 引数: session(native.Session)、cfg(Config)は明示した時計と入口/出口です。
// 返り値: Actor/errorは観測wrapper又は不正設定です。金融本文を変更しません。
func (f CapturedHarvest) New(session native.Session, cfg Config) (Actor, error) {
	if f.Records == nil {
		return nil, fmt.Errorf("技法判定の保存口が欠落")
	}
	a, err := (Harvest97{}).New(session, cfg)
	if err != nil {
		return nil, err
	}
	return &capturedActor{Actor: a, inner: a.(*newActor), records: f.Records}, nil
}

type capturedActor struct {
	Actor
	inner   *newActor
	records *[]GateAssessmentRecord
}

// Grid は実際の現在候補に対する純式の全文を保存します。
//
// 引数: at(float64)、input(*actual.TechnicalGateInput)は当時の時計と保存文脈です。
// 返り値: errorは金融/純式契約の不整合です。旧採否の転記や二回評価は行いません。
func (a *capturedActor) Grid(at float64, input *actual.TechnicalGateInput) error {
	if input == nil || input.At != at {
		return fmt.Errorf("定時公開文脈の欠落")
	}
	var callback harvest.EntryGate
	if a.inner.gate != "" {
		callback = func(candidate harvest.EntryCandidate) (harvest.GateDecision, error) {
			a.inner.callbacks++
			current := ConvertCandidate(candidate)
			assessment, err := actual.AssessTechnicalGate(*input, current, a.inner.gate)
			if err != nil {
				return harvest.GateDecision{}, err
			}
			*a.records = append(*a.records, GateAssessmentRecord{Key: a.inner.book.Snapshot().Key, Ordinal: current.Ordinal, Source: current.Source, Candidate: current, Assessment: assessment})
			return harvest.GateDecision(assessment.Decision), nil
		}
	}
	return a.inner.book.OnEntryGridWithGate(at, callback)
}
