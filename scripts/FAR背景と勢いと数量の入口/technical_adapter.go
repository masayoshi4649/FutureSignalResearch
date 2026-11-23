package minientry99

import (
	fixed96 "github.com/masayoshi4649/SessionTradeExecuter/minichart"
	e3 "github.com/masayoshi4649/SessionTradeExecuter/minie3"
)

// AssessEntryTechnical は金融の現在候補を全field対応で停止E3純式へ渡します。
//
// 引数: input(e3.TechnicalGateInput)、candidate(EntryCandidate)、policy(string)は公開文脈・旧適格候補・E3/E3Sです。
// 返り値: e3.TechnicalAssessment/errorは全checkと判断、又は公開出典の不整合です。
// 候補のSource/方向/価格/量/時刻は変更せず、A/ABへの名の置換は行いません。
func AssessEntryTechnical(input e3.TechnicalGateInput, candidate EntryCandidate, policy string) (e3.TechnicalAssessment, error) {
	s := candidate.Source
	pure := fixed96.EntryCandidate{
		Ordinal: candidate.Ordinal, At: candidate.At, Side: candidate.Side, Quote: candidate.Quote,
		Available: candidate.Available, Quantity: candidate.Quantity,
		Source: fixed96.SourceIdentity{
			Method: s.Method, SignalID: s.SignalID, Kind: s.Kind, Parent: s.Parent,
			SourceID: s.SourceID, QuantityMicro: s.QuantityMicro, BirthQuantity: s.BirthQuantity,
			BirthTime: s.BirthTime, BirthQuote: s.BirthQuote,
		},
	}
	return e3.AssessTechnicalGate(input, pure, policy)
}
