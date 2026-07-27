import base64
import json
import unittest
from unittest.mock import patch

from scripts.inspect_rpc import GnoRpcClient, RpcError


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


if __name__ == "__main__": unittest.main()
