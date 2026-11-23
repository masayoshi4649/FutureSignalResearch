package continuous101

import (
	"compress/gzip"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"reflect"
	"regexp"
	"sort"
	"time"

	warm "github.com/masayoshi4649/SessionTradeExecuter/chartwarmup96"
	"github.com/masayoshi4649/SessionTradeExecuter/internal/strategy"
	oldtape "github.com/masayoshi4649/SessionTradeExecuter/lighttape97"
)

const Proof100SHA = "4a8bc486e329f65f17e2395f781b2efd7cf76c5630d91924b611e90254725af3"
const Manifest80SHA = "b939bc91b33fd86e933534c3b991d844b8a0200a5f14710e1bd5004edc1aab42"
const Study100 = "study/00100_費用後利益化の前後で保護を分ける"

type AllowedEntry struct {
	Session   string `json:"session"`
	NativeSHA string `json:"native_sha256"`
}
type Allowed struct {
	Version  int            `json:"version"`
	ProofSHA string         `json:"proof100_sha256"`
	Entries  []AllowedEntry `json:"entries"`
}
type TapeEntry struct {
	Session string `json:"session"`
	Path    string `json:"path"`
	SHA     string `json:"sha256"`
}
type TapeIndex struct {
	Version int         `json:"version"`
	Stage   string      `json:"stage"`
	Entries []TapeEntry `json:"entries"`
}
type Arguments struct {
	Root, Proof, Allowed, Manifest, Index, Out, Stage, Stop, First2 string
	MaxNKRows                                                       int
	MaxHeapMiB                                                      uint64
}

// OwnedPaths は停止が省略できない所有コード/仕様集合を返します。
//
// 引数: ありません。
// 返り値: []stringはrepo相対の固定13pathです。
func OwnedPaths() []string {
	names := []string{"sidecar.go", "build.go", "input.go", "production.go", "stream.go", "build_test.go", "go.mod", "go.sum", "cmd/build/main.go", "実装前計画.md", "README.md", "由来.json", "許可54.json"}
	out := []string{}
	for _, n := range names {
		out = append(out, "scripts/保護判断の連続技法入力/"+n)
	}
	return out
}

type closure struct {
	Trial    int               `json:"試行"`
	Complete bool              `json:"比較保存完了"`
	Scenes   int               `json:"場数"`
	Files    map[string]string `json:"自己を除く正式指紋"`
	Core     map[string]string `json:"固定金融/監査236"`
	Post     map[string]string `json:"後処理コードSHA256"`
}

// digest は明示ファイルの現在SHAを得ます。
//
// 引数: path(string)は許可済みファイルです。
// 返り値: string/errorはSHA256又はIO不正です。
func digest(path string) (string, error) {
	f, e := os.Open(path)
	if e != nil {
		return "", e
	}
	defer f.Close()
	h := sha256.New()
	if _, e = io.Copy(h, f); e != nil {
		return "", e
	}
	return hex.EncodeToString(h.Sum(nil)), nil
}

// readJSON は明示metadata又はRoot実行時の保存入力を読みます。
//
// 引数: path(string)、target(any)はファイルと受け皿です。
// 返り値: errorはIO/JSON不正です。暗黙の探索はしません。
func readJSON(path string, target any) error {
	raw, e := os.ReadFile(path)
	if e != nil {
		return e
	}
	return json.Unmarshal(raw, target)
}

// Catalog は固定閉鎖metadataから54場だけを取り出します。
//
// 引数: root/proof(string)はrepoと固定100完了です。
// 返り値: Allowed/closure/errorは許可54/元metadata/不正です。Native本文は読みません。
func Catalog(root, proof string) (Allowed, closure, error) {
	out := Allowed{Version: 1, ProofSHA: Proof100SHA, Entries: []AllowedEntry{}}
	var c closure
	expected := filepath.Join(root, filepath.FromSlash(Study100), "完了記録.json")
	a, _ := filepath.Abs(proof)
	b, _ := filepath.Abs(expected)
	h, e := digest(proof)
	if e != nil || a != b || h != Proof100SHA {
		return out, c, fmt.Errorf("固定100完了path/SHA不一致")
	}
	if e = readJSON(proof, &c); e != nil {
		return out, c, e
	}
	if c.Trial != 100 || !c.Complete || c.Scenes != 54 || len(c.Core) != 236 || len(c.Post) != 5 {
		return out, c, fmt.Errorf("固定100完了metadata不正")
	}
	re := regexp.MustCompile(`^成果物/(\d{4}-\d{2}-\d{2}_(?:Day|Night))\.json\.gz$`)
	for name, sha := range c.Files {
		if m := re.FindStringSubmatch(filepath.ToSlash(name)); m != nil {
			out.Entries = append(out.Entries, AllowedEntry{m[1], sha})
		}
	}
	sort.Slice(out.Entries, func(i, j int) bool { return out.Entries[i].Session < out.Entries[j].Session })
	if len(out.Entries) != 54 {
		return out, c, fmt.Errorf("許可54不足")
	}
	return out, c, nil
}

// Select は全集合が固定54と一致するときだけstage集合を返します。
//
// 引数: got/expected(Allowed)、stage(string)は台帳二値と実行段階です。
// 返り値: []string/errorは固定2又は54、又は追加/欠落/重複/未許可です。
func Select(got, expected Allowed, stage string) ([]string, error) {
	if !reflect.DeepEqual(got, expected) || (stage != "first2" && stage != "full54") {
		return nil, fmt.Errorf("許可54全体又はstage不一致")
	}
	seen := map[string]bool{}
	ids := []string{}
	for _, r := range got.Entries {
		if seen[r.Session] || len(r.NativeSHA) != 64 {
			return nil, fmt.Errorf("許可重複/SHA不正")
		}
		seen[r.Session] = true
		if stage == "full54" || r.Session == "2026-09-21_Day" || r.Session == "2026-09-21_Night" {
			ids = append(ids, r.Session)
		}
	}
	expectedCount := 54
	if stage == "first2" {
		expectedCount = 2
	}
	if len(ids) != expectedCount {
		return nil, fmt.Errorf("stage集合不足")
	}
	return ids, nil
}

// ResolveTapeSource は旧100台帳と同じ基準で存在とSHAを先行検査します。
//
// 引数: indexPath(string)、entry(TapeEntry)は台帳pathと保存入力のmetadataです。
// 返り値: TapeEntry/errorは絶対pathへ解決した値、又は欠落/型/指紋不正です。JSON値を展開しません。
func ResolveTapeSource(indexPath string, entry TapeEntry) (TapeEntry, error) {
	if entry.Path == "" || len(entry.SHA) != 64 {
		return entry, fmt.Errorf("Tape Source path/SHA不正")
	}
	if !filepath.IsAbs(entry.Path) {
		entry.Path = filepath.Join(filepath.Dir(indexPath), entry.Path)
	}
	absolute, e := filepath.Abs(entry.Path)
	if e != nil {
		return entry, e
	}
	entry.Path = absolute
	info, e := os.Stat(absolute)
	if e != nil {
		return entry, e
	}
	if !info.Mode().IsRegular() {
		return entry, fmt.Errorf("Tape Sourceが通常ファイルでない:%s", absolute)
	}
	got, e := digest(absolute)
	if e != nil {
		return entry, e
	}
	if got != entry.SHA {
		return entry, fmt.Errorf("Tape Source SHA差:%s", entry.Session)
	}
	return entry, nil
}

// LoadRequest は機械派生readerだけで板とCSVを公開Requestへ変換します。
//
// 引数: input(InputSession)、root(string)、t(oldtape.Tape)は固定台帳/原根/旧Tapeです。
// 返り値: Request/品質map/errorは当場入力/元品質/不正です。Source/金融を運転しません。
func LoadRequest(input InputSession, root string, t oldtape.Tape) (Request, map[string]RawQuality, error) {
	s, e := sessionClock(input.ID)
	req := Request{Session: s, Scene: warm.Scene{ID: input.ID, Contract: input.Contract, Start: s.Start}, Rows: []Row{}, Candles: []CandleEvent{}, Grids: []float64{}}
	q := map[string]RawQuality{}
	if e != nil {
		return req, q, e
	}
	if s != t.Session {
		return req, q, fmt.Errorf("旧Tape場時計差")
	}
	method := "D164_15"
	if s.Kind == "Night" {
		method = "P164_06"
	}
	params, e := strategy.ParametersForMethod("NK225", s.Kind, method)
	if e != nil {
		return req, q, e
	}
	for _, ref := range []string{"TOPIX", "NK225"} {
		path, er := verifyInput(root, input.Files[ref+"_book"])
		if er != nil {
			return req, q, er
		}
		rows, quality, er := readBoards(path, ref, s)
		if er != nil {
			return req, q, er
		}
		if len(quality.Contracts) != 1 || ref == "NK225" && quality.Contracts[0] != input.Contract {
			return req, q, fmt.Errorf("限月差")
		}
		q[ref] = quality
		for _, r := range rows {
			req.Rows = append(req.Rows, Row{r.Board, r.Line})
		}
		for _, interval := range []int{60, 300} {
			path, er = verifyInput(root, input.Files[fmt.Sprintf("%s_candle_%d", ref, interval)])
			if er != nil {
				return req, q, er
			}
			cs, er := readCandles(path, ref, interval, params.Features.CandleDelay, s)
			if er != nil {
				return req, q, er
			}
			for _, c := range cs {
				req.Candles = append(req.Candles, CandleEvent{c.Reference, c.Interval, c.Candle, c.At})
			}
		}
	}
	for _, ev := range t.Events {
		if ev.Kind == "grid" {
			req.Grids = append(req.Grids, ev.At)
		}
	}
	return req, q, nil
}

// saveNew は新規ファイルだけへJSONを保存します。
//
// 引数: path(string)、v(any)、compressed(bool)は新規先/値/gzip有無です。
// 返り値: errorは既存/IO/JSON不正です。
func saveNew(path string, v any, compressed bool) error {
	f, e := os.OpenFile(path, os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0600)
	if e != nil {
		return e
	}
	if compressed {
		g := gzip.NewWriter(f)
		e = json.NewEncoder(g).Encode(v)
		if er := g.Close(); e == nil {
			e = er
		}
	} else {
		enc := json.NewEncoder(f)
		enc.SetIndent("", "  ")
		e = enc.Encode(v)
	}
	if er := f.Close(); e == nil {
		e = er
	}
	return e
}

// RunFirst は固定metadata/停止/入力を検査して許可stageのsidecarを新規作成します。
//
// 引数: args(Arguments)は全入力を明示したRoot用CLI引数です。
// 返り値: errorは不一致です。実行許可を得たRootだけが呼びます。
func RunFirst(args Arguments) error {
	if args.MaxNKRows == 0 {
		args.MaxNKRows = 1000000
	}
	if args.MaxHeapMiB == 0 {
		args.MaxHeapMiB = 4096
	}
	if args.MaxNKRows < 1 || args.MaxHeapMiB < 64 || args.MaxHeapMiB > 65536 {
		return fmt.Errorf("資源上限が不正")
	}
	if args.Root == "" || args.Proof == "" || args.Allowed == "" || args.Manifest == "" || args.Index == "" || args.Out == "" || args.Stop == "" {
		return fmt.Errorf("必須引数不足")
	}
	if _, e := os.Stat(args.Out); !os.IsNotExist(e) {
		return fmt.Errorf("新規出力だけ許可")
	}
	expected, c, e := Catalog(args.Root, args.Proof)
	if e != nil {
		return e
	}
	var got Allowed
	if e = readJSON(args.Allowed, &got); e != nil {
		return e
	}
	ids, e := Select(got, expected, args.Stage)
	if e != nil {
		return e
	}
	var stop struct {
		Success bool              `json:"成功"`
		Code    map[string]string `json:"所有コードSHA256"`
		Exe     string            `json:"実行物SHA256"`
	}
	if e = readJSON(args.Stop, &stop); e != nil {
		return e
	}
	if len(stop.Code) != len(OwnedPaths()) {
		return fmt.Errorf("所有停止集合が不足")
	}
	for _, p := range OwnedPaths() {
		if len(stop.Code[p]) != 64 {
			return fmt.Errorf("所有停止path/SHAが不足")
		}
	}
	exe, _ := os.Executable()
	exeSHA, e := digest(exe)
	if e != nil || !stop.Success || exeSHA != stop.Exe || len(stop.Code) == 0 {
		return fmt.Errorf("停止/実行物不一致")
	}
	before := map[string]string{}
	paths := map[string]string{}
	for p, h := range c.Core {
		paths[filepath.Join(args.Root, filepath.FromSlash(p))] = h
	}
	for p, h := range c.Post {
		paths[filepath.Join(args.Root, filepath.FromSlash(p))] = h
	}
	for p, h := range stop.Code {
		paths[filepath.Join(args.Root, filepath.FromSlash(p))] = h
	}
	for p, h := range paths {
		actual, er := digest(p)
		if er != nil || actual != h {
			return fmt.Errorf("固定コード不一致:%s", p)
		}
		before[p] = actual
	}
	for _, p := range []string{args.Proof, args.Allowed, args.Manifest, args.Index, args.Stop, exe} {
		h, er := digest(p)
		if er != nil {
			return er
		}
		before[p] = h
	}
	if before[args.Manifest] != Manifest80SHA {
		return fmt.Errorf("固定80台帳差")
	}
	indexName := "接続2場Tape台帳.json"
	if args.Stage == "full54" {
		indexName = "正式54Tape台帳.json"
	}
	if before[args.Index] != c.Files[indexName] {
		return fmt.Errorf("固定100のTape台帳SHA差")
	}
	var index TapeIndex
	if e = readJSON(args.Index, &index); e != nil {
		return e
	}
	if index.Version != 1 || index.Stage != args.Stage || len(index.Entries) != len(ids) {
		return fmt.Errorf("Tape台帳stage/集合差")
	}
	byTape := map[string]TapeEntry{}
	for _, r := range index.Entries {
		if _, ok := byTape[r.Session]; ok {
			return fmt.Errorf("Tape重複")
		}
		resolved, er := ResolveTapeSource(args.Index, r)
		if er != nil {
			return er
		}
		r = resolved
		byTape[r.Session] = r
	}
	for _, id := range ids {
		if _, ok := byTape[id]; !ok {
			return fmt.Errorf("Tape場欠落")
		}
	}
	if args.Stage == "full54" {
		var first struct {
			Success   bool              `json:"成功"`
			Stage     string            `json:"stage"`
			Code      map[string]string `json:"所有コードSHA256"`
			Proof     string            `json:"固定100完了SHA256"`
			Unchanged bool              `json:"前後不変"`
			Scope     string            `json:"scope"`
			Sessions  []string          `json:"sessions"`
			Source    bool              `json:"source_reexecuted"`
			Finance   bool              `json:"financial_executed"`
		}
		if args.First2 == "" || readJSON(args.First2, &first) != nil || !first.Success || first.Stage != "first2" || first.Proof != Proof100SHA || !first.Unchanged || first.Scope != "固定100と旧Tapeの連続技法sidecar構築" || first.Source || first.Finance || !reflect.DeepEqual(first.Sessions, []string{"2026-09-21_Day", "2026-09-21_Night"}) || !reflect.DeepEqual(first.Code, stop.Code) {
			return fmt.Errorf("同版first2成功が必要")
		}
		h, er := digest(args.First2)
		if er != nil {
			return er
		}
		before[args.First2] = h
	}
	var manifest InputManifest
	if e = readJSON(args.Manifest, &manifest); e != nil {
		return e
	}
	if e = ValidateManifest(manifest); e != nil {
		return e
	}
	byInput := map[string]InputSession{}
	for _, s := range manifest.Sessions {
		byInput[s.ID] = s
	}
	for _, id := range ids {
		if _, ok := byInput[id]; !ok {
			return fmt.Errorf("板台帳場欠落")
		}
	}
	for _, id := range ids {
		for _, file := range byInput[id].Files {
			p := filepath.Join(manifest.Root, filepath.FromSlash(file.Path))
			before[p] = file.SHA256
		}
		entry := byTape[id]
		before[entry.Path] = entry.SHA
	}
	if e = os.MkdirAll(filepath.Dir(args.Out), 0700); e != nil {
		return e
	}
	if e = os.Mkdir(args.Out, 0700); e != nil {
		return e
	}
	details := []any{}
	var seed *warm.Seed
	previousScene := ""
	for _, id := range ids {
		sceneStart := time.Now()
		entry := byTape[id]
		t, er := oldtape.LoadCache(entry.Path, entry.SHA)
		if er != nil {
			return er
		}
		req, quality, er := LoadRequest(byInput[id], manifest.Root, t)
		if er != nil {
			return er
		}
		p := filepath.Join(args.Out, id+".records.jsonl.gz")
		file, er := os.OpenFile(p, os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0600)
		if er != nil {
			return er
		}
		gz := gzip.NewWriter(file)
		value, next, match, stats, er := WriteStream(req, seed, t, gz, Budget{uint64(args.MaxHeapMiB) * 1024 * 1024, args.MaxNKRows})
		closeGZ := gz.Close()
		closeFile := file.Close()
		if er != nil {
			_ = saveNew(filepath.Join(args.Out, id+".失敗.json"), map[string]any{"成功": false, "session": id, "不一致": er.Error(), "stream統計": stats, "source_reexecuted": false, "financial_executed": false}, false)
			return er
		}
		if closeGZ != nil {
			return closeGZ
		}
		if closeFile != nil {
			return closeFile
		}
		seed = next
		value.Provenance = map[string]string{"old_tape_path": entry.Path, "old_tape_gzip_sha256": entry.SHA, "proof100_sha256": Proof100SHA, "manifest80_sha256": Manifest80SHA, "previous_scene": previousScene, "raw_csv_provenance": "完了.jsonの入力コードSHA256前後から当場6入力を参照"}
		previousScene = id
		header := filepath.Join(args.Out, id+".header.json")
		if er = saveNew(header, value, false); er != nil {
			return er
		}
		info, er := os.Stat(p)
		if er != nil {
			return er
		}
		h, er := digest(p)
		if er != nil {
			return er
		}
		headerSHA, er := digest(header)
		if er != nil {
			return er
		}
		details = append(details, map[string]any{"session": id, "path": p, "SHA256": h, "header": header, "header_SHA256": headerSHA, "圧縮bytes": info.Size(), "場全経過秒": time.Since(sceneStart).Seconds(), "stream統計": stats, "資源上限": Budget{args.MaxHeapMiB * 1024 * 1024, args.MaxNKRows}, "旧Scalar/全5分Input": match, "旧Ending全文比較": false, "Ending範囲": "新bank.Sealの保存と無損失復元だけ・旧Ending出典は別途必要", "品質": quality})
		fmt.Printf("完了 %s 原行%d 枠%d bytes%d heap標本%d\n", id, value.RowCount, len(value.Grids), info.Size(), stats.SampledHeapMax)
	}
	for p, h := range before {
		after, er := digest(p)
		if er != nil || after != h {
			return fmt.Errorf("入力/コード前後差:%s", p)
		}
	}
	return saveNew(filepath.Join(args.Out, "完了.json"), map[string]any{"成功": true, "scope": "固定100と旧Tapeの連続技法sidecar構築", "stage": args.Stage, "固定100完了SHA256": Proof100SHA, "sessions": ids, "所有コードSHA256": stop.Code, "入力コードSHA256前後": before, "前後不変": true, "details": details, "source_reexecuted": false, "financial_executed": false, "features_recomputed": true, "charts_recomputed": true}, false)
}
