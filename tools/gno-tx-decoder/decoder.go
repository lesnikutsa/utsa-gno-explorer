package main

import (
	"bufio"
	"bytes"
	"encoding/base64"
	"encoding/json"
	"io"
	"reflect"
	"strings"
	"unicode"

	"github.com/gnolang/gno/gno.land/pkg/sdk/vm"
	"github.com/gnolang/gno/tm2/pkg/amino"
	"github.com/gnolang/gno/tm2/pkg/sdk/auth"
	"github.com/gnolang/gno/tm2/pkg/sdk/bank"
	"github.com/gnolang/gno/tm2/pkg/std"
)

const (
	protocolVersion   = 1
	maxLineBytes      = 8 << 20
	maxTxBytes        = 4 << 20
	maxIDRunes        = 128
	maxMessages       = 20
	maxSummaryBytes   = 16_384
	maxDetailsBytes   = 48 << 10
	maxArgumentValues = 16
	maxArgumentRunes  = 256
	maxLabelRunes     = 80
	maxTypeRunes      = 160
	maxTokenRunes     = 64
	maxScalarRunes    = 160
)

type request struct {
	ID               string `json:"id"`
	TxBase64         string `json:"tx_base64"`
	IncludeArguments bool   `json:"include_arguments,omitempty"`
}
type response struct {
	ProtocolVersion int      `json:"protocol_version"`
	ID              string   `json:"id,omitempty"`
	OK              bool     `json:"ok"`
	Summary         *summary `json:"summary,omitempty"`
	Details         *details `json:"details,omitempty"`
	ErrorCode       string   `json:"error_code,omitempty"`
}
type details struct {
	MessageArguments []messageArguments `json:"message_arguments"`
}
type messageArguments struct {
	MessageIndex int      `json:"message_index"`
	Values       []string `json:"values"`
	Truncated    bool     `json:"truncated"`
}
type summary struct {
	SchemaVersion     int       `json:"schema_version"`
	ChainFamily       string    `json:"chain_family"`
	ParseStatus       string    `json:"parse_status"`
	MessageCount      int       `json:"message_count"`
	MessagesTruncated bool      `json:"messages_truncated"`
	Primary           core      `json:"primary"`
	Messages          []message `json:"messages"`
}
type core struct {
	Type     string `json:"type"`
	Category string `json:"category"`
	Action   string `json:"action"`
	Label    string `json:"label"`
}
type message struct {
	Type            string `json:"type"`
	Category        string `json:"category"`
	Action          string `json:"action"`
	Label           string `json:"label"`
	Sender          string `json:"sender,omitempty"`
	Recipient       string `json:"recipient,omitempty"`
	PackagePath     string `json:"package_path,omitempty"`
	PackageName     string `json:"package_name,omitempty"`
	Function        string `json:"function,omitempty"`
	ArgsCount       *int   `json:"args_count,omitempty"`
	FileCount       *int   `json:"file_count,omitempty"`
	Send            string `json:"send,omitempty"`
	Amount          string `json:"amount,omitempty"`
	ExpiresAt       *int64 `json:"expires_at,omitempty"`
	AllowPathsCount *int   `json:"allow_paths_count,omitempty"`
	SpendLimit      string `json:"spend_limit,omitempty"`
	SpendPeriod     *int64 `json:"spend_period,omitempty"`
}
type decoderFunc func([]byte) (*summary, error)

func runProtocol(in io.Reader, out io.Writer) { runProtocolWithDecoder(in, out, decode) }
func runProtocolWithDecoder(in io.Reader, out io.Writer, decodeFn decoderFunc) {
	r := bufio.NewReaderSize(in, 64*1024)
	w := bufio.NewWriter(out)
	defer w.Flush()
	for {
		line, large, err := readLine(r)
		if len(bytes.TrimSpace(line)) != 0 || large {
			encoded, merr := json.Marshal(safeHandleLine(line, large, decodeFn))
			if merr != nil {
				encoded = []byte(`{"protocol_version":1,"ok":false,"error_code":"internal_error"}`)
			}
			_, _ = w.Write(encoded)
			_ = w.WriteByte('\n')
			_ = w.Flush()
		}
		if err != nil {
			return
		}
	}
}
func readLine(r *bufio.Reader) ([]byte, bool, error) {
	var line []byte
	large := false
	for {
		part, prefix, err := r.ReadLine()
		if !large {
			if len(line)+len(part) > maxLineBytes {
				line = nil
				large = true
			} else {
				line = append(line, part...)
			}
		}
		if !prefix {
			return line, large, err
		}
	}
}

func safeHandleLine(line []byte, large bool, decodeFn decoderFunc) (result response) {
	result = response{ProtocolVersion: protocolVersion}
	if !large {
		var req request
		dec := json.NewDecoder(bytes.NewReader(line))
		dec.DisallowUnknownFields()
		if dec.Decode(&req) == nil && dec.Decode(&struct{}{}) == io.EOF && req.ID != "" && printable(req.ID, maxIDRunes) == req.ID {
			result.ID = req.ID
		}
	}
	defer func() {
		if recover() != nil {
			result.OK = false
			result.Summary = nil
			result.Details = nil
			result.ErrorCode = "internal_error"
		}
	}()
	return handleLineWithDecoder(line, large, decodeFn)
}
func handleLine(line []byte, large bool) response { return safeHandleLine(line, large, decode) }
func handleLineWithDecoder(line []byte, large bool, decodeFn decoderFunc) response {
	base := response{ProtocolVersion: protocolVersion}
	if large {
		base.ErrorCode = "input_too_large"
		return base
	}
	var req request
	dec := json.NewDecoder(bytes.NewReader(line))
	dec.DisallowUnknownFields()
	if dec.Decode(&req) != nil || dec.Decode(&struct{}{}) != io.EOF {
		base.ErrorCode = "invalid_json"
		return base
	}
	base.ID = printable(req.ID, maxIDRunes)
	if base.ID != req.ID || req.ID == "" {
		base.ErrorCode = "invalid_request"
		return base
	}
	if req.TxBase64 == "" {
		base.ErrorCode = "missing_tx_base64"
		return base
	}
	if base64.StdEncoding.DecodedLen(len(req.TxBase64)) > maxTxBytes {
		base.ErrorCode = "input_too_large"
		return base
	}
	raw, err := base64.StdEncoding.Strict().DecodeString(req.TxBase64)
	if err != nil {
		base.ErrorCode = "invalid_base64"
		return base
	}
	if len(raw) > maxTxBytes {
		base.ErrorCode = "input_too_large"
		return base
	}
	s, err := decodeFn(raw)
	if err != nil {
		base.ErrorCode = "amino_decode_failed"
		return base
	}
	base.OK = true
	base.Summary = s
	if req.IncludeArguments {
		tx, detailErr := decodeTransaction(raw)
		if detailErr != nil {
			base.OK = false
			base.Summary = nil
			base.ErrorCode = "amino_decode_failed"
			return base
		}
		base.Details = argumentDetails(tx)
	}
	return base
}

func argumentDetails(tx std.Tx) *details {
	result := &details{MessageArguments: make([]messageArguments, 0, min(len(tx.Msgs), maxMessages))}
	for index, msg := range tx.Msgs {
		if len(result.MessageArguments) == maxMessages {
			break
		}
		var args []string
		switch value := msg.(type) {
		case vm.MsgCall:
			args = value.Args
		case *vm.MsgCall:
			if value == nil {
				continue
			}
			args = value.Args
		default:
			continue
		}
		entry := messageArguments{MessageIndex: index, Values: make([]string, 0, min(len(args), maxArgumentValues)), Truncated: len(args) > maxArgumentValues}
		for _, argument := range args[:min(len(args), maxArgumentValues)] {
			bounded, shortened := printableArgument(argument, maxArgumentRunes)
			entry.Values = append(entry.Values, bounded)
			entry.Truncated = entry.Truncated || shortened
		}
		result.MessageArguments = append(result.MessageArguments, entry)
	}
	for detailsJSONSize(result) > maxDetailsBytes {
		removed := false
		for index := len(result.MessageArguments) - 1; index >= 0; index-- {
			entry := &result.MessageArguments[index]
			if len(entry.Values) > 0 {
				entry.Values = entry.Values[:len(entry.Values)-1]
				entry.Truncated = true
				removed = true
				break
			}
		}
		if !removed {
			break
		}
	}
	return result
}

func detailsJSONSize(value *details) int {
	encoded, err := json.Marshal(value)
	if err != nil {
		return maxDetailsBytes + 1
	}
	return len(encoded)
}

func printableArgument(value string, limit int) (string, bool) {
	var bounded strings.Builder
	count := 0
	shortened := false
	for _, character := range value {
		if !unicode.IsPrint(character) {
			shortened = true
			continue
		}
		if count == limit {
			shortened = true
			continue
		}
		bounded.WriteRune(character)
		count++
	}
	return bounded.String(), shortened
}

func decode(raw []byte) (*summary, error) {
	tx, err := decodeTransaction(raw)
	if err != nil {
		return nil, err
	}
	return summarizeTransaction(tx), nil
}
func decodeTransaction(raw []byte) (std.Tx, error) {
	var tx std.Tx
	if err := amino.Unmarshal(raw, &tx); err != nil {
		return std.Tx{}, err
	}
	return tx, nil
}
func summarizeTransaction(tx std.Tx) *summary {
	s := &summary{SchemaVersion: 1, ChainFamily: "gno", ParseStatus: "parsed", MessageCount: len(tx.Msgs), Messages: make([]message, 0, min(len(tx.Msgs), maxMessages))}
	if len(tx.Msgs) == 0 {
		s.ParseStatus = "unsupported"
		s.Primary = core{Type: "gno.unknown", Category: "unknown", Action: "unknown", Label: "Gno Transaction"}
		return bound(s)
	}
	for i, msg := range tx.Msgs {
		m, known := summarizeMessage(msg)
		if !known {
			s.ParseStatus = "unsupported"
		}
		if i == 0 {
			s.Primary = core{m.Type, m.Category, m.Action, m.Label}
		}
		if i < maxMessages {
			s.Messages = append(s.Messages, m)
		} else {
			s.MessagesTruncated = true
		}
	}
	return bound(s)
}

func summarizeMessage(msg std.Msg) (message, bool) {
	var m message
	switch v := msg.(type) {
	case vm.MsgCall:
		return summarizeMsgCall(v), true
	case *vm.MsgCall:
		if v != nil {
			return summarizeMsgCall(*v), true
		}
	case vm.MsgRun:
		return summarizeMsgRun(v), true
	case *vm.MsgRun:
		if v != nil {
			return summarizeMsgRun(*v), true
		}
	case vm.MsgAddPackage:
		return summarizeMsgAddPackage(v), true
	case *vm.MsgAddPackage:
		if v != nil {
			return summarizeMsgAddPackage(*v), true
		}
	case bank.MsgSend:
		return summarizeMsgSend(v), true
	case *bank.MsgSend:
		if v != nil {
			return summarizeMsgSend(*v), true
		}
	case auth.MsgCreateSession:
		return summarizeMsgCreateSession(v), true
	case *auth.MsgCreateSession:
		if v != nil {
			return summarizeMsgCreateSession(*v), true
		}
	case auth.MsgRevokeSession:
		return summarizeMsgRevokeSession(v), true
	case *auth.MsgRevokeSession:
		if v != nil {
			return summarizeMsgRevokeSession(*v), true
		}
	case auth.MsgRevokeAllSessions:
		return summarizeMsgRevokeAllSessions(v), true
	case *auth.MsgRevokeAllSessions:
		if v != nil {
			return summarizeMsgRevokeAllSessions(*v), true
		}
	}
	t := reflect.TypeOf(msg)
	if t != nil {
		for t.Kind() == reflect.Pointer {
			t = t.Elem()
		}
		m.Type = printable(t.PkgPath()+"."+t.Name(), maxTypeRunes)
	}
	if m.Type == "" {
		m.Type = "gno.unknown"
	}
	m.Category = "unknown"
	m.Action = "unknown"
	m.Label = "Unsupported Gno Message"
	return m, false
}

func summarizeMsgCall(v vm.MsgCall) message {
	n := len(v.Args)
	return cleanMessage(message{Type: "gno.vm.MsgCall", Category: "contract", Action: "call", Label: "Contract Call", Sender: v.Caller.String(), PackagePath: v.PkgPath, Function: v.Func, ArgsCount: &n, Send: v.Send.String()})
}
func summarizeMsgRun(v vm.MsgRun) message {
	m := message{Type: "gno.vm.MsgRun", Category: "contract", Action: "run", Label: "Run Package", Sender: v.Caller.String(), Send: v.Send.String()}
	if v.Package != nil {
		m.PackageName = v.Package.Name
		n := len(v.Package.Files)
		m.FileCount = &n
	}
	return cleanMessage(m)
}
func summarizeMsgAddPackage(v vm.MsgAddPackage) message {
	m := message{Type: "gno.vm.MsgAddPackage", Category: "contract", Action: "add_package", Label: "Add Package", Sender: v.Creator.String(), Send: v.Send.String()}
	if v.Package != nil {
		m.PackagePath = v.Package.Path
		m.PackageName = v.Package.Name
		n := len(v.Package.Files)
		m.FileCount = &n
	}
	return cleanMessage(m)
}
func summarizeMsgSend(v bank.MsgSend) message {
	return cleanMessage(message{Type: "gno.bank.MsgSend", Category: "bank", Action: "send", Label: "Send Tokens", Sender: v.FromAddress.String(), Recipient: v.ToAddress.String(), Amount: v.Amount.String()})
}
func summarizeMsgCreateSession(v auth.MsgCreateSession) message {
	n := len(v.AllowPaths)
	expires, period := v.ExpiresAt, v.SpendPeriod
	return cleanMessage(message{Type: "gno.auth.MsgCreateSession", Category: "auth", Action: "create_session", Label: "Create Session", Sender: v.Creator.String(), ExpiresAt: &expires, AllowPathsCount: &n, SpendLimit: v.SpendLimit.String(), SpendPeriod: &period})
}
func summarizeMsgRevokeSession(v auth.MsgRevokeSession) message {
	return cleanMessage(message{Type: "gno.auth.MsgRevokeSession", Category: "auth", Action: "revoke_session", Label: "Revoke Session", Sender: v.Creator.String()})
}
func summarizeMsgRevokeAllSessions(v auth.MsgRevokeAllSessions) message {
	return cleanMessage(message{Type: "gno.auth.MsgRevokeAllSessions", Category: "auth", Action: "revoke_all_sessions", Label: "Revoke All Sessions", Sender: v.Creator.String()})
}

func bound(s *summary) *summary {
	for len(s.Messages) > 0 {
		b, _ := json.Marshal(s)
		if len(b) <= maxSummaryBytes {
			return s
		}
		s.Messages = s.Messages[:len(s.Messages)-1]
		s.MessagesTruncated = true
	}
	b, _ := json.Marshal(s)
	if len(b) <= maxSummaryBytes {
		return s
	}
	return &summary{SchemaVersion: 1, ChainFamily: "gno", ParseStatus: "unsupported", MessageCount: s.MessageCount, MessagesTruncated: true, Primary: core{Type: "gno.unknown", Category: "unknown", Action: "unknown", Label: "Gno Transaction"}, Messages: []message{}}
}
func cleanMessage(m message) message {
	m.Type = printable(m.Type, maxTypeRunes)
	m.Category = printable(m.Category, maxTokenRunes)
	m.Action = printable(m.Action, maxTokenRunes)
	m.Label = printable(m.Label, maxLabelRunes)
	m.Sender = printable(m.Sender, maxScalarRunes)
	m.Recipient = printable(m.Recipient, maxScalarRunes)
	m.PackagePath = printable(m.PackagePath, maxScalarRunes)
	m.PackageName = printable(m.PackageName, maxScalarRunes)
	m.Function = printable(m.Function, maxScalarRunes)
	m.Send = printable(m.Send, maxScalarRunes)
	m.Amount = printable(m.Amount, maxScalarRunes)
	m.SpendLimit = printable(m.SpendLimit, maxScalarRunes)
	return m
}
func printable(s string, limit int) string {
	s = strings.TrimSpace(s)
	var b strings.Builder
	n := 0
	for _, r := range s {
		if unicode.IsPrint(r) {
			if n == limit {
				break
			}
			b.WriteRune(r)
			n++
		}
	}
	return b.String()
}
