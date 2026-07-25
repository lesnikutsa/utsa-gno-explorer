package main

import (
	"bytes"
	"encoding/json"
	"strings"
	"testing"
)

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

func TestOversizedLineDoesNotStopProtocol(t *testing.T) {
	input := strings.Repeat("x", maxLineBytes+1) + "\n{}\n"
	var out bytes.Buffer
	runProtocol(strings.NewReader(input), &out)
	lines := strings.Split(strings.TrimSpace(out.String()), "\n")
	if len(lines) != 2 {
		t.Fatalf("%q", out.String())
	}
}
