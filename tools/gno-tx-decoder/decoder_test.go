package main

import (
	"encoding/base64"
	"encoding/json"
	"strings"
	"testing"
	"unicode/utf8"

	"github.com/gnolang/gno/gno.land/pkg/sdk/vm"
	"github.com/gnolang/gno/gnovm/pkg/gnolang"
	"github.com/gnolang/gno/tm2/pkg/amino"
	"github.com/gnolang/gno/tm2/pkg/crypto"
	"github.com/gnolang/gno/tm2/pkg/sdk/auth"
	"github.com/gnolang/gno/tm2/pkg/sdk/bank"
	"github.com/gnolang/gno/tm2/pkg/std"
)

type unknownTestMsg struct{}

func (unknownTestMsg) Route() string                { return "test" }
func (unknownTestMsg) Type() string                 { return "unknown" }
func (unknownTestMsg) ValidateBasic() error         { return nil }
func (unknownTestMsg) GetSignBytes() []byte         { return nil }
func (unknownTestMsg) GetSigners() []crypto.Address { return nil }

func encodeTx(t *testing.T, msgs ...std.Msg) string {
	t.Helper()
	raw, err := amino.Marshal(std.Tx{Msgs: msgs, Memo: "MEMO_SENTINEL"})
	if err != nil {
		t.Fatal(err)
	}
	return base64.StdEncoding.EncodeToString(raw)
}
func decodeMessages(t *testing.T, msgs ...std.Msg) *summary {
	t.Helper()
	raw, err := base64.StdEncoding.DecodeString(encodeTx(t, msgs...))
	if err != nil {
		t.Fatal(err)
	}
	s, err := decode(raw)
	if err != nil {
		t.Fatal(err)
	}
	return s
}

func TestSupportedMessages(t *testing.T) {
	caller := crypto.Address{1}
	recipient := crypto.Address{2}
	coins := std.Coins{{Denom: "ugnot", Amount: 7}}
	call := vm.MsgCall{Caller: caller, Send: coins, PkgPath: "gno.land/r/demo/call", Func: "Render", Args: []string{"ARG_SENTINEL_ONE", "ARG_SENTINEL_TWO"}}
	run := vm.MsgRun{Caller: caller, Send: coins, Package: &gnolang.MemPackage{Name: "runpkg", Files: []*gnolang.MemFile{{Name: "RUN_NAME_SENTINEL", Body: "RUN_BODY_SENTINEL"}, {Name: "two.gno", Body: "package runpkg"}}}}
	add := vm.MsgAddPackage{Creator: caller, Send: coins, Package: &gnolang.MemPackage{Path: "gno.land/r/demo/add", Name: "addpkg", Files: []*gnolang.MemFile{{Name: "ADD_NAME_SENTINEL", Body: "ADD_BODY_SENTINEL"}, {Name: "two.gno", Body: "package addpkg"}}}}
	send := bank.MsgSend{FromAddress: caller, ToAddress: recipient, Amount: coins}
	tests := []struct {
		name               string
		msg                std.Msg
		typ, action, label string
	}{
		{"call", call, "gno.vm.MsgCall", "call", "Contract Call"},
		{"run", run, "gno.vm.MsgRun", "run", "Run Package"},
		{"add", add, "gno.vm.MsgAddPackage", "add_package", "Add Package"},
		{"send", send, "gno.bank.MsgSend", "send", "Send Tokens"},
		{"create-session", auth.MsgCreateSession{}, "gno.auth.MsgCreateSession", "create_session", "Create Session"},
		{"revoke-session", auth.MsgRevokeSession{}, "gno.auth.MsgRevokeSession", "revoke_session", "Revoke Session"},
		{"revoke-all", auth.MsgRevokeAllSessions{}, "gno.auth.MsgRevokeAllSessions", "revoke_all_sessions", "Revoke All Sessions"},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			s := decodeMessages(t, tt.msg)
			if s.ChainFamily != "gno" || s.ParseStatus != "parsed" || s.Primary.Type != tt.typ || s.Primary.Action != tt.action || s.Primary.Label != tt.label {
				t.Fatalf("unexpected summary: %#v", s)
			}
			serialized, _ := json.Marshal(s)
			for _, sentinel := range []string{"ARG_SENTINEL_ONE", "ARG_SENTINEL_TWO", "RUN_NAME_SENTINEL", "RUN_BODY_SENTINEL", "ADD_NAME_SENTINEL", "ADD_BODY_SENTINEL"} {
				if strings.Contains(string(serialized), sentinel) {
					t.Fatalf("exposed %q", sentinel)
				}
			}
		})
	}
	callSummary := decodeMessages(t, call).Messages[0]
	if callSummary.Sender != caller.String() || callSummary.PackagePath != call.PkgPath || callSummary.Function != call.Func || callSummary.ArgsCount == nil || *callSummary.ArgsCount != 2 || callSummary.Send != coins.String() {
		t.Fatalf("%#v", callSummary)
	}
	runSummary := decodeMessages(t, run).Messages[0]
	if runSummary.PackageName != "runpkg" || runSummary.FileCount == nil || *runSummary.FileCount != 2 {
		t.Fatalf("%#v", runSummary)
	}
	addSummary := decodeMessages(t, add).Messages[0]
	if addSummary.PackagePath != "gno.land/r/demo/add" || addSummary.PackageName != "addpkg" || addSummary.FileCount == nil || *addSummary.FileCount != 2 {
		t.Fatalf("%#v", addSummary)
	}
	sendSummary := decodeMessages(t, send).Messages[0]
	if sendSummary.Sender != caller.String() || sendSummary.Recipient != recipient.String() || sendSummary.Amount != coins.String() {
		t.Fatalf("%#v", sendSummary)
	}
}

func TestMultiMessageAndLimit(t *testing.T) {
	msgs := make([]std.Msg, 21)
	for i := range msgs {
		msgs[i] = bank.MsgSend{}
	}
	s := decodeMessages(t, msgs...)
	if s.MessageCount != 21 || len(s.Messages) != 20 || !s.MessagesTruncated || s.Primary.Type != "gno.bank.MsgSend" {
		t.Fatalf("unexpected summary: %#v", s)
	}
}

func TestDeterministicBoundedAndNoExposure(t *testing.T) {
	s := decodeMessages(t, vm.MsgCall{})
	a, _ := json.Marshal(s)
	b, _ := json.Marshal(decodeMessages(t, vm.MsgCall{}))
	if string(a) != string(b) {
		t.Fatal("summary is not deterministic")
	}
	if len(a) > maxSummaryBytes || !utf8.Valid(a) {
		t.Fatalf("invalid bound: %d", len(a))
	}
	for _, sentinel := range []string{"MEMO_SENTINEL", "Args", "Signature", "PublicKey", "Body"} {
		if strings.Contains(string(a), sentinel) {
			t.Fatalf("exposed %q", sentinel)
		}
	}
}

func TestUnknownAndEmptyTransactions(t *testing.T) {
	unknown := summarizeTransaction(std.Tx{Msgs: []std.Msg{unknownTestMsg{}}})
	if unknown.ParseStatus != "unsupported" || unknown.MessageCount != 1 || unknown.Primary.Category != "unknown" || unknown.Primary.Action != "unknown" || unknown.Primary.Label != "Unsupported Gno Message" || unknown.Primary.Type == "" {
		t.Fatalf("%#v", unknown)
	}
	empty := summarizeTransaction(std.Tx{})
	if empty.ParseStatus != "unsupported" || empty.MessageCount != 0 || len(empty.Messages) != 0 || empty.Primary.Type != "gno.unknown" {
		t.Fatalf("%#v", empty)
	}
}

func TestPrintableClipsUnicodeRunes(t *testing.T) {
	got := printable("界🙂éabc", 3)
	if got != "界🙂é" || !utf8.ValidString(got) {
		t.Fatalf("%q", got)
	}
}

func TestBoundDropsTrailingMessages(t *testing.T) {
	text := strings.Repeat("界", maxScalarRunes)
	m := message{Type: strings.Repeat("t", maxTypeRunes), Category: "contract", Action: "call", Label: strings.Repeat("l", maxLabelRunes), Sender: text, Recipient: text, PackagePath: text, PackageName: text, Function: text, Send: text, Amount: text, SpendLimit: text}
	messages := make([]message, maxMessages)
	for i := range messages {
		messages[i] = m
	}
	primary := core{Type: "first.type", Category: "contract", Action: "call", Label: "First"}
	s := bound(&summary{SchemaVersion: 1, ChainFamily: "gno", ParseStatus: "parsed", MessageCount: 99, Primary: primary, Messages: messages})
	b, err := json.Marshal(s)
	if err != nil {
		t.Fatal(err)
	}
	if len(b) > maxSummaryBytes || !s.MessagesTruncated || s.MessageCount != 99 || s.Primary != primary || len(s.Messages) >= maxMessages {
		t.Fatalf("size=%d summary=%#v", len(b), s)
	}
}

func TestInvalidInputs(t *testing.T) {
	if got := handleLine([]byte(`{"id":"x","tx_base64":"%%%"}`), false); got.ErrorCode != "invalid_base64" {
		t.Fatalf("%#v", got)
	}
	if got := handleLine([]byte(`{"id":"x","tx_base64":"AA=="}`), false); got.ErrorCode != "amino_decode_failed" {
		t.Fatalf("%#v", got)
	}
	if got := handleLine(nil, true); got.ErrorCode != "input_too_large" {
		t.Fatalf("%#v", got)
	}
}
