package main

import (
	"encoding/base64"
	"encoding/json"
	"strings"
	"testing"
	"unicode/utf8"

	"github.com/gnolang/gno/gno.land/pkg/sdk/vm"
	"github.com/gnolang/gno/tm2/pkg/amino"
	"github.com/gnolang/gno/tm2/pkg/sdk/auth"
	"github.com/gnolang/gno/tm2/pkg/sdk/bank"
	"github.com/gnolang/gno/tm2/pkg/std"
)

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
	tests := []struct {
		name               string
		msg                std.Msg
		typ, action, label string
	}{
		{"call", vm.MsgCall{}, "gno.vm.MsgCall", "call", "Contract Call"},
		{"run", vm.MsgRun{}, "gno.vm.MsgRun", "run", "Run Package"},
		{"add", vm.MsgAddPackage{}, "gno.vm.MsgAddPackage", "add_package", "Add Package"},
		{"send", bank.MsgSend{}, "gno.bank.MsgSend", "send", "Send Tokens"},
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
		})
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
