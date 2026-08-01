package main

import (
	"bytes"
	"encoding/base64"
	"encoding/json"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"

	"github.com/gnolang/gno/gno.land/pkg/sdk/vm"
	"github.com/gnolang/gno/tm2/pkg/crypto"
	"github.com/gnolang/gno/tm2/pkg/sdk/bank"
	"github.com/gnolang/gno/tm2/pkg/std"
)

func protocolResponse(t *testing.T, includeArguments bool, messages ...std.Msg) response {
	t.Helper()
	line, err := json.Marshal(request{ID: "detail-1", TxBase64: encodeTx(t, messages...), IncludeArguments: includeArguments})
	if err != nil {
		t.Fatal(err)
	}
	return handleLine(line, false)
}

func TestArgumentsAreOptionalAndOutsideSummary(t *testing.T) {
	call := vm.MsgCall{Args: []string{"argument one", "", "argument two"}}
	without := protocolResponse(t, false, call)
	encoded, err := json.Marshal(without)
	if err != nil {
		t.Fatal(err)
	}
	if without.Details != nil || bytes.Contains(encoded, []byte("details")) || bytes.Contains(encoded, []byte("argument one")) {
		t.Fatalf("optional details changed legacy response: %s", encoded)
	}
	with := protocolResponse(t, true, call)
	if !with.OK || with.Details == nil || len(with.Details.MessageArguments) != 1 {
		t.Fatalf("%#v", with)
	}
	entry := with.Details.MessageArguments[0]
	if entry.MessageIndex != 0 || entry.Truncated || strings.Join(entry.Values, "|") != "argument one||argument two" {
		t.Fatalf("%#v", entry)
	}
	if with.Summary.Messages[0].ArgsCount == nil || *with.Summary.Messages[0].ArgsCount != 3 {
		t.Fatalf("summary args_count changed: %#v", with.Summary.Messages[0])
	}
}

func TestArgumentsKeepMessageIndexesAndSkipUnsupportedTypes(t *testing.T) {
	response := protocolResponse(t, true,
		vm.MsgCall{Args: []string{"first"}},
		bank.MsgSend{FromAddress: crypto.Address{1}, ToAddress: crypto.Address{2}},
		vm.MsgCall{Args: []string{"third"}},
	)
	entries := response.Details.MessageArguments
	if len(entries) != 2 || entries[0].MessageIndex != 0 || entries[1].MessageIndex != 2 || entries[1].Values[0] != "third" {
		t.Fatalf("%#v", entries)
	}
}

func TestArgumentBoundsFilteringAndTruncation(t *testing.T) {
	arguments := make([]string, 17)
	arguments[0] = "keep\x00line\ntext"
	arguments[1] = strings.Repeat("界", maxArgumentRunes+1)
	for index := 2; index < len(arguments); index++ {
		arguments[index] = "value"
	}
	entry := protocolResponse(t, true, vm.MsgCall{Args: arguments}).Details.MessageArguments[0]
	if len(entry.Values) != maxArgumentValues || entry.Values[0] != "keeplinetext" || len([]rune(entry.Values[1])) != maxArgumentRunes || !entry.Truncated {
		t.Fatalf("%#v", entry)
	}
}

func TestArgumentDetailsCompactJSONSizeBound(t *testing.T) {
	messages := make([]std.Msg, maxMessages)
	for index := range messages {
		arguments := make([]string, maxArgumentValues)
		for argumentIndex := range arguments {
			arguments[argumentIndex] = strings.Repeat("🙂", maxArgumentRunes)
		}
		messages[index] = vm.MsgCall{Args: arguments}
	}
	detail := protocolResponse(t, true, messages...).Details
	encoded, err := json.Marshal(detail)
	if err != nil {
		t.Fatal(err)
	}
	if len(encoded) > maxDetailsBytes {
		t.Fatalf("details size %d", len(encoded))
	}
	if !detail.MessageArguments[len(detail.MessageArguments)-1].Truncated {
		t.Fatal("expected trailing values to be marked truncated")
	}
}

func TestRequestedArgumentsKeepMalformedInputsSafe(t *testing.T) {
	invalidBase64, _ := json.Marshal(request{ID: "bad-base64", TxBase64: "%%%", IncludeArguments: true})
	if response := handleLine(invalidBase64, false); response.OK || response.Details != nil || response.ErrorCode != "invalid_base64" {
		t.Fatalf("%#v", response)
	}
	invalidAmino, _ := json.Marshal(request{ID: "bad-amino", TxBase64: base64.StdEncoding.EncodeToString([]byte{0}), IncludeArguments: true})
	if response := handleLine(invalidAmino, false); response.OK || response.Details != nil || response.ErrorCode != "amino_decode_failed" {
		t.Fatalf("%#v", response)
	}
}

func TestProtocolContinuesAfterMalformedLine(t *testing.T) {
	tx := encodeTx(t)
	valid := `{"id":"good","tx_base64":"` + tx + `"}`
	input := valid + "\n{" + "\n\n" + valid + "\n"
	var out bytes.Buffer
	runProtocol(strings.NewReader(input), &out)
	lines := strings.Split(strings.TrimSpace(out.String()), "\n")
	if len(lines) != 3 {
		t.Fatalf("got %d response lines: %s", len(lines), out.String())
	}
	for i, line := range lines {
		var r response
		if err := json.Unmarshal([]byte(line), &r); err != nil {
			t.Fatal(err)
		}
		if i == 1 && r.ErrorCode != "invalid_json" {
			t.Fatalf("%#v", r)
		}
		if i != 1 && !r.OK {
			t.Fatalf("%#v", r)
		}
	}
}

func TestProtocolRecoversPerRequest(t *testing.T) {
	tx := encodeTx(t)
	valid := `{"id":"good","tx_base64":"` + tx + `"}`
	panicRequest := `{"id":"panic","tx_base64":"` + tx + `"}`
	calls := 0
	decodeFn := func(raw []byte) (*summary, error) {
		calls++
		if calls == 2 {
			panic("PANIC_SENTINEL")
		}
		return decode(raw)
	}
	var out bytes.Buffer
	runProtocolWithDecoder(strings.NewReader(valid+"\n"+panicRequest+"\n"+valid+"\n"), &out, decodeFn)
	lines := strings.Split(strings.TrimSpace(out.String()), "\n")
	if len(lines) != 3 {
		t.Fatalf("got %d lines", len(lines))
	}
	for i, line := range lines {
		if strings.Contains(line, "PANIC_SENTINEL") || strings.Contains(line, tx) {
			t.Fatal("response exposed panic or payload")
		}
		var r response
		if err := json.Unmarshal([]byte(line), &r); err != nil {
			t.Fatal(err)
		}
		if i == 1 {
			if r.OK || r.ErrorCode != "internal_error" || r.ID != "panic" {
				t.Fatalf("%#v", r)
			}
		} else if !r.OK {
			t.Fatalf("%#v", r)
		}
	}
}

func TestCommandJSONLSubprocess(t *testing.T) {
	binary := filepath.Join(t.TempDir(), "gno-tx-decoder")
	build := exec.Command("go", "build", "-trimpath", "-o", binary, ".")
	if output, err := build.CombinedOutput(); err != nil {
		t.Fatalf("build command: %v\n%s", err, output)
	}
	tx := encodeTx(t)
	valid := `{"id":"good","tx_base64":"` + tx + `"}`
	cmd := exec.Command(binary)
	cmd.Stdin = strings.NewReader(valid + "\n{\n" + valid + "\n")
	var stdout, stderr bytes.Buffer
	cmd.Stdout = &stdout
	cmd.Stderr = &stderr
	if err := cmd.Run(); err != nil {
		t.Fatal(err)
	}
	if stderr.Len() != 0 {
		t.Fatalf("stderr: %s", stderr.String())
	}
	lines := strings.Split(strings.TrimSpace(stdout.String()), "\n")
	if len(lines) != 3 {
		t.Fatalf("stdout: %s", stdout.String())
	}
	for i, line := range lines {
		var r response
		if err := json.Unmarshal([]byte(line), &r); err != nil {
			t.Fatal(err)
		}
		if i == 1 {
			if r.ErrorCode != "invalid_json" {
				t.Fatalf("%#v", r)
			}
		} else if !r.OK {
			t.Fatalf("%#v", r)
		}
	}
}

func TestOversizedLineDoesNotStopProtocol(t *testing.T) {
	input := strings.Repeat("x", maxLineBytes+1) + "\n{}\n"
	var out bytes.Buffer
	runProtocol(strings.NewReader(input), &out)
	lines := strings.Split(strings.TrimSpace(out.String()), "\n")
	if len(lines) != 2 {
		t.Fatalf("%q", out.String())
	}
}
