import base64
import json
import unittest
from unittest.mock import patch

from scripts.inspect_rpc import GnoRpcClient, MAX_ABCI_RESPONSE_BYTES, RpcError


class GovernanceRpcTests(unittest.TestCase):
    def test_abci_query_uses_official_json_wrapped_base64_transport(self):
        client = GnoRpcClient("https://rpc.example")
        payload = {"result": {"response": {"ResponseBase": {"Error": None, "Data": base64.b64encode(b"render").decode()}}}}
        with patch.object(client, "get", return_value=payload) as get:
            self.assertEqual(client.abci_query("vm/qrender", "gno.land/r/gov/dao:"), "render")
        get.assert_called_once_with("abci_query", path=json.dumps("vm/qrender"), data=json.dumps(base64.b64encode(b"gno.land/r/gov/dao:").decode()), prove="false")

    def test_abci_query_rejects_rpc_error_and_malformed_data(self):
        client = GnoRpcClient("https://rpc.example")
        with patch.object(client, "get", return_value={"result": {"response": {"ResponseBase": {"Error": "failed", "Data": ""}}}}):
            with self.assertRaises(RpcError): client.abci_query("vm/qrender", "realm:")
        with patch.object(client, "get", return_value={"result": {"response": {"ResponseBase": {"Error": None, "Data": "%%%"}}}}):
            with self.assertRaises(RpcError): client.abci_query("vm/qrender", "realm:")

    def test_abci_query_validates_height_utf8_and_response_limit(self):
        client = GnoRpcClient("https://rpc.example")
        for height in (0, -1, True, "1"):
            with self.assertRaisesRegex(RpcError, "positive integer"):
                client.abci_query("vm/qrender", "realm:", height=height)
        invalid_utf8 = base64.b64encode(b"\xff").decode()
        with patch.object(client, "get", return_value={"result": {"response": {"ResponseBase": {"Error": None, "Data": invalid_utf8}}}}):
            with self.assertRaisesRegex(RpcError, "UTF-8"):
                client.abci_query("vm/qrender", "realm:", height=1)
        oversized = base64.b64encode(b"x" * (MAX_ABCI_RESPONSE_BYTES + 1)).decode()
        with patch.object(client, "get", return_value={"result": {"response": {"ResponseBase": {"Error": None, "Data": oversized}}}}):
            with self.assertRaisesRegex(RpcError, "size limit"):
                client.abci_query("vm/qrender", "realm:")


if __name__ == "__main__": unittest.main()
