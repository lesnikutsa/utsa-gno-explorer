# Valopers fixture provenance

The Markdown layout is transcribed from the current authoritative
`examples/gno.land/r/gnops/valopers/valopers.gno` `renderHome` and
`Valoper.Render` contracts. The Ed25519 detail layout is based on the official
`filetests/z_2_filetest.gno` assertion. Addresses, descriptions, and the
Secp256k1 vector are deterministic test substitutions, not claimed Testnet 13
captures. The keys use the current Bech32-of-Amino interface encoding described
by `tm2/pkg/crypto/bech32.go`; expected raw bytes are fixed independently in the
tests. No credentials, headers, signatures, or private material are present.
Live Testnet 13 capture remains an exp2 validation step.

`tests/test_validator_profiles.py` separately contains the exact Ed25519 gpub
and expected raw base64 assertion from official `z_2_filetest.gno`. The list
fixtures use the relative `?page=N` links emitted by authoritative
`p/nt/avl/v0/pager.Page.Picker`; their addresses remain deterministic.
