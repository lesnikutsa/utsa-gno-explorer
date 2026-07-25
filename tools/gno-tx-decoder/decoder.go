package main

import (
	"bufio"
	"bytes"
	"encoding/base64"
	"encoding/json"
	"fmt"
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
	protocolVersion = 1
	maxLineBytes    = 8 << 20
	maxTxBytes      = 4 << 20
	maxIDRunes      = 128
	maxMessages     = 20
	maxSummaryBytes = 16_384
	maxLabelRunes   = 80
	maxTypeRunes    = 160
	maxTokenRunes   = 64
	maxScalarRunes  = 160
)

type request struct {
	ID       string `json:"id"`
	TxBase64 string `json:"tx_base64"`
}
type response struct {
	ProtocolVersion int      `json:"protocol_version"`
	ID              string   `json:"id,omitempty"`
	OK              bool     `json:"ok"`
	Summary         *summary `json:"summary,omitempty"`
	ErrorCode       string   `json:"error_code,omitempty"`
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
	ExpiresAt       string `json:"expires_at,omitempty"`
	AllowPathsCount *int   `json:"allow_paths_count,omitempty"`
	SpendLimit      string `json:"spend_limit,omitempty"`
	SpendPeriod     string `json:"spend_period,omitempty"`
}

func runProtocol(in io.Reader, out io.Writer) {
	r := bufio.NewReaderSize(in, 64*1024)
	w := bufio.NewWriter(out)
	defer w.Flush()
	for {
		line, tooLarge, err := readLine(r)
		if len(bytes.TrimSpace(line)) != 0 || tooLarge {
			resp := handleLine(line, tooLarge)
			encoded, marshalErr := json.Marshal(resp)
			if marshalErr != nil {
				encoded = []byte(`{"protocol_version":1,"ok":false,"error_code":"internal_error"}`)
			}
			_, _ = w.Write(encoded)
			_ = w.WriteByte('\n')
			_ = w.Flush()
		}
		if err == io.EOF {
			return
		}
		if err != nil {
			return
		}
	}
}

func readLine(r *bufio.Reader) ([]byte, bool, error) {
	var line []byte
	for {
		part, prefix, err := r.ReadLine()
		if len(line) <= maxLineBytes {
			line = append(line, part...)
		}
		if !prefix {
			return line, len(line) > maxLineBytes, err
		}
		if len(line) > maxLineBytes { // Drain the rest of this request without retaining it.
			for prefix && err == nil {
				_, prefix, err = r.ReadLine()
			}
			return nil, true, err
		}
	}
}

func handleLine(line []byte, tooLarge bool) response {
	base := response{ProtocolVersion: protocolVersion}
	if tooLarge {
		base.ErrorCode = "input_too_large"
		return base
	}
	var req request
	dec := json.NewDecoder(bytes.NewReader(line))
	dec.DisallowUnknownFields()
	if err := dec.Decode(&req); err != nil {
		base.ErrorCode = "invalid_json"
		return base
	}
	if dec.Decode(&struct{}{}) != io.EOF {
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
	s, err := decode(raw)
	if err != nil {
		base.ErrorCode = "amino_decode_failed"
		return base
	}
	base.OK, base.Summary = true, s
	return base
}

func decode(raw []byte) (*summary, error) {
	var tx std.Tx
	if err := amino.Unmarshal(raw, &tx); err != nil {
		return nil, err
	}
	s := &summary{SchemaVersion: 1, ChainFamily: "gno", ParseStatus: "parsed", MessageCount: len(tx.Msgs), Messages: make([]message, 0, min(len(tx.Msgs), maxMessages))}
	if len(tx.Msgs) == 0 {
		s.ParseStatus = "unsupported"
		s.Primary = core{Type: "gno.unknown", Category: "unknown", Action: "unknown", Label: "Gno Transaction"}
		return bound(s), nil
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
	return bound(s), nil
}

func summarizeMessage(msg std.Msg) (message, bool) {
	var m message
	switch msg.(type) {
	case vm.MsgCall, *vm.MsgCall:
		m = message{Type: "gno.vm.MsgCall", Category: "contract", Action: "call", Label: "Contract Call"}
		m.Sender = fieldText(msg, "Caller", "Sender")
		m.PackagePath = fieldText(msg, "PkgPath", "PackagePath")
		m.Function = fieldText(msg, "Func", "Function")
		m.ArgsCount = fieldLen(msg, "Args")
		m.Send = fieldText(msg, "Send")
	case vm.MsgRun, *vm.MsgRun:
		m = message{Type: "gno.vm.MsgRun", Category: "contract", Action: "run", Label: "Run Package"}
		m.Sender = fieldText(msg, "Caller", "Sender")
		m.PackageName = nestedText(msg, []string{"Package", "Name"})
		m.FileCount = nestedLen(msg, []string{"Package", "Files"})
		m.Send = fieldText(msg, "Send")
	case vm.MsgAddPackage, *vm.MsgAddPackage:
		m = message{Type: "gno.vm.MsgAddPackage", Category: "contract", Action: "add_package", Label: "Add Package"}
		m.Sender = fieldText(msg, "Creator", "Sender")
		m.PackagePath = nestedText(msg, []string{"Package", "Path"})
		m.PackageName = nestedText(msg, []string{"Package", "Name"})
		m.FileCount = nestedLen(msg, []string{"Package", "Files"})
		m.Send = fieldText(msg, "Deposit", "Send")
	case bank.MsgSend, *bank.MsgSend:
		m = message{Type: "gno.bank.MsgSend", Category: "bank", Action: "send", Label: "Send Tokens"}
		m.Sender = fieldText(msg, "FromAddress", "Sender")
		m.Recipient = fieldText(msg, "ToAddress", "Recipient")
		m.Amount = fieldText(msg, "Amount")
	case auth.MsgCreateSession, *auth.MsgCreateSession:
		m = message{Type: "gno.auth.MsgCreateSession", Category: "auth", Action: "create_session", Label: "Create Session"}
		m.Sender = fieldText(msg, "Creator", "Sender")
		m.ExpiresAt = fieldText(msg, "ExpiresAt")
		m.AllowPathsCount = fieldLen(msg, "AllowedPaths", "AllowPaths")
		m.SpendLimit = fieldText(msg, "SpendLimit")
		m.SpendPeriod = fieldText(msg, "SpendPeriod")
	case auth.MsgRevokeSession, *auth.MsgRevokeSession:
		m = message{Type: "gno.auth.MsgRevokeSession", Category: "auth", Action: "revoke_session", Label: "Revoke Session", Sender: fieldText(msg, "Creator", "Sender")}
	case auth.MsgRevokeAllSessions, *auth.MsgRevokeAllSessions:
		m = message{Type: "gno.auth.MsgRevokeAllSessions", Category: "auth", Action: "revoke_all_sessions", Label: "Revoke All Sessions", Sender: fieldText(msg, "Creator", "Sender")}
	default:
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
	return cleanMessage(m), true
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
	m.ExpiresAt = printable(m.ExpiresAt, maxScalarRunes)
	m.SpendLimit = printable(m.SpendLimit, maxScalarRunes)
	m.SpendPeriod = printable(m.SpendPeriod, maxScalarRunes)
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
func valueOf(v any) reflect.Value {
	x := reflect.ValueOf(v)
	for x.IsValid() && (x.Kind() == reflect.Pointer || x.Kind() == reflect.Interface) {
		if x.IsNil() {
			return reflect.Value{}
		}
		x = x.Elem()
	}
	return x
}
func path(v any, names ...string) reflect.Value {
	x := valueOf(v)
	for _, name := range names {
		if !x.IsValid() || x.Kind() != reflect.Struct {
			return reflect.Value{}
		}
		x = x.FieldByName(name)
		x = valueOf(x)
	}
	return x
}
func fieldText(v any, names ...string) string {
	for _, n := range names {
		if x := path(v, n); x.IsValid() {
			return printable(fmt.Sprint(x.Interface()), maxScalarRunes)
		}
	}
	return ""
}
func nestedText(v any, names []string) string {
	x := path(v, names...)
	if !x.IsValid() {
		return ""
	}
	return printable(fmt.Sprint(x.Interface()), maxScalarRunes)
}
func fieldLen(v any, names ...string) *int {
	for _, n := range names {
		if x := path(v, n); x.IsValid() && (x.Kind() == reflect.Slice || x.Kind() == reflect.Array || x.Kind() == reflect.Map || x.Kind() == reflect.String) {
			q := x.Len()
			return &q
		}
	}
	return nil
}
func nestedLen(v any, names []string) *int {
	x := path(v, names...)
	if !x.IsValid() || !(x.Kind() == reflect.Slice || x.Kind() == reflect.Array || x.Kind() == reflect.Map) {
		return nil
	}
	q := x.Len()
	return &q
}
