package main

import (
	"bytes"
	"encoding/json"
	"os/exec"
	"path/filepath"
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
