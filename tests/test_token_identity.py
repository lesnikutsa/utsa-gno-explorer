from api.token_identity import TokenIdentity, extract_token_identity


def source(text):
    return [{"filename": "main.gno", "file_kind": "gno_source", "content": text}]


def test_one_line_identity():
    assert extract_token_identity(source('var coin = grc20.NewToken(owner, "Solana", "SOL", 9)')) == TokenIdentity("Solana", "SOL", 9)


def test_multiline_comments_and_escaped_literal():
    identity = extract_token_identity(source('grc20.NewToken(\n owner, /* identity */ "S\\"olana",\n "SOL", 9,\n)'))
    assert identity == TokenIdentity('S"olana', "SOL", 9)


def test_ambiguous_malformed_and_non_literal_are_unverified():
    assert not extract_token_identity(source('grc20.NewToken(x, "A", "A", 6); grc20.NewToken(x, "B", "B", 8)')).verified
    assert not extract_token_identity(source('grc20.NewToken(x, getName(), "A", 6)')).verified
    assert not extract_token_identity(source('grc20.NewToken(x, "A", "A", decimals)')).verified


def test_source_is_not_executed(tmp_path):
    marker = tmp_path / "executed"
    payload = f'__import__("pathlib").Path("{marker}").touch(); grc20.NewToken(x, "A", "A", 6)'
    assert extract_token_identity(source(payload)).verified
    assert not marker.exists()
