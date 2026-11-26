"""Lambda tests: pairing, input checks, config and Volvo errors. Fake DynamoDB, fake Volvo token endpoint.

Run: python3 -m unittest discover -s infra/lambda -p 'test_*.py'
"""

import json
import os
import re
import sys
import time
import unittest
import urllib.parse

os.environ.setdefault("PAIRING_TABLE", "test-pairing")

import token_exchange as tx  # noqa: E402


class ConditionalCheckFailedException(Exception):
    pass


class FakeDynamo:
    """Just the DynamoDB calls and expressions token_exchange uses."""

    class exceptions:
        ConditionalCheckFailedException = ConditionalCheckFailedException

    def __init__(self):
        self.items = {}
        self.calls = []

    def _check(self, item, cond, names, values):
        if not cond:
            return
        for part in cond.split(" AND "):
            part = part.strip()
            m = re.fullmatch(r"attribute_(not_)?exists\((\w+)\)", part)
            if m:
                exists = item is not None and m.group(2) in item
                ok = not exists if m.group(1) else exists
            else:
                left, op, right = part.split()
                left = (names or {}).get(left, left)
                if item is None or left not in item:
                    ok = False
                else:
                    a, b = item[left], values[right]
                    if "N" in b:
                        a, b = int(a["N"]), int(b["N"])
                    ok = a == b if op == "=" else (a > b if op == ">" else a < b)
            if not ok:
                raise ConditionalCheckFailedException(part)

    def put_item(self, TableName, Item, ConditionExpression=None, **kw):
        key = Item["code"]["S"]
        self._check(self.items.get(key), ConditionExpression, None, None)
        self.items[key] = dict(Item)

    def get_item(self, TableName, Key, ConsistentRead=False):
        item = self.items.get(Key["code"]["S"])
        return {"Item": dict(item)} if item else {}

    def update_item(self, TableName, Key, UpdateExpression, ConditionExpression=None,
                    ExpressionAttributeNames=None, ExpressionAttributeValues=None,
                    ReturnValues=None):
        key = Key["code"]["S"]
        item = self.items.get(key)
        self._check(item, ConditionExpression, ExpressionAttributeNames, ExpressionAttributeValues)
        item = self.items.setdefault(key, {"code": {"S": key}})
        verb, rest = UpdateExpression.split(" ", 1)
        changed = {}
        for assign in rest.split(","):
            if verb == "SET":
                name, val = [x.strip() for x in assign.split("=")]
                item[name] = ExpressionAttributeValues[val]
            else:  # ADD
                name, val = assign.split()
                cur = int(item.get(name, {"N": "0"})["N"])
                item[name] = {"N": str(cur + int(ExpressionAttributeValues[val]["N"]))}
            changed[name] = item[name]
        return {"Attributes": changed}

    def delete_item(self, TableName, Key, ConditionExpression=None,
                    ExpressionAttributeValues=None, ReturnValues=None):
        key = Key["code"]["S"]
        item = self.items.get(key)
        self._check(item, ConditionExpression, None, ExpressionAttributeValues)
        self.items.pop(key, None)
        return {"Attributes": item} if ReturnValues == "ALL_OLD" and item else {}


CONFIG = {"allowed-origins": "https://piotrserafin.github.io", "client-id": "x",
          "client-secret": "s", "vcc-api-key": "k", "redirect-uri": "https://r",
          "scopes": "openid"}

TOKENS = {"access_token": "at", "refresh_token": "rt", "expires_in": 300,
          "token_type": "Bearer", "vcc_api_key": "key"}


VERIFIER = "v" * 64


def post(**params):
    return post_body(urllib.parse.urlencode(params))


def post_handler(**params):
    """Through lambda_handler, with its top-level error handling."""
    return post_body(urllib.parse.urlencode(params), handler=tx.lambda_handler)


def post_body(body, handler=None):
    event = {
        "requestContext": {"http": {"method": "POST"}},
        "headers": {},
        "body": body,
    }
    resp = handler(event, None) if handler else tx._handle(event)
    body = resp["body"]
    return resp["statusCode"], (json.loads(body) if body else None)


class LambdaTest(unittest.TestCase):
    """Fake DynamoDB and Volvo; counts Volvo token calls."""

    def setUp(self):
        self.db = FakeDynamo()
        self.volvo_calls = 0
        tx._dynamodb = self.db
        tx._config = dict(CONFIG)
        tx._config_expires = time.time() + 3600

        def fake_fetch(body):
            self.volvo_calls += 1
            return 200, dict(TOKENS)

        self._orig_fetch = tx.fetch_tokens
        tx.fetch_tokens = fake_fetch

    def tearDown(self):
        tx.fetch_tokens = self._orig_fetch
        tx._dynamodb = None
        tx._config = {}
        tx._config_expires = 0


class PairingTest(LambdaTest):
    def start(self):
        status, data = post(action="pair_start")
        self.assertEqual(status, 200)
        return data["code"], data["secret"]

    def login(self, code):
        return post(grant_type="authorization_code", code="c", code_verifier=VERIFIER, pair=code)

    def poll(self, code, secret):
        return post(action="pair_poll", code=code, secret=secret)

    def confirm(self, code, value):
        return post(action="pair_confirm", code=code, confirm=value)

    def test_full_flow(self):
        code, secret = self.start()
        self.assertEqual(self.poll(code, secret), (202, {"status": "pending"}))

        status, data = self.login(code)
        self.assertEqual(status, 200)
        self.assertNotIn("access_token", data)  # the browser never sees tokens
        confirm = data["confirm_code"]
        self.assertRegex(confirm, r"^[A-HJKMNP-Z2-9]{6}$")

        # Logged in but not confirmed: still no tokens for the poller
        self.assertEqual(self.poll(code, secret), (202, {"status": "confirm"}))

        # Typed the way people type it
        typed = (confirm[:3] + "-" + confirm[3:]).lower()
        self.assertEqual(self.confirm(code, typed), (200, {"ok": True}))

        status, data = self.poll(code, secret)
        self.assertEqual(status, 200)
        self.assertEqual(data["access_token"], "at")
        # Collected once only
        self.assertEqual(self.poll(code, secret)[0], 404)

    def test_link_owner_cannot_collect_without_code(self):
        # Someone starts a pairing and gets another person to log in with it.
        code, secret = self.start()
        self.login(code)
        for _ in range(100):
            self.assertEqual(self.poll(code, secret)[0], 202)
        self.assertNotIn("confirmed", self.db.items[code])

    def test_wrong_codes_delete_pairing(self):
        code, secret = self.start()
        _, data = self.login(code)
        wrong = "AAAAAA" if data["confirm_code"] != "AAAAAA" else "BBBBBB"
        for left in range(tx.CONFIRM_MAX_ATTEMPTS - 1, 0, -1):
            self.assertEqual(self.confirm(code, wrong), (403, {"error": "wrong_code", "attempts_left": left}))
        self.assertEqual(self.confirm(code, wrong)[0], 404)
        self.assertNotIn(code, self.db.items)
        # Even the right code is useless now
        self.assertEqual(self.confirm(code, data["confirm_code"])[0], 404)
        self.assertEqual(self.poll(code, secret)[0], 404)

    def test_confirm_needs_login_first(self):
        code, _ = self.start()
        self.assertEqual(self.confirm(code, "ABCDEF")[0], 404)

    def test_confirm_rejects_bad_input(self):
        code, _ = self.start()
        self.login(code)
        self.assertEqual(self.confirm(code, "ABC")[0], 400)
        self.assertEqual(self.confirm(code, "ABCDE0")[0], 400)  # 0 is not in the alphabet
        self.assertEqual(self.confirm("short", "ABCDEF")[0], 404)

    def test_expired_or_unknown_pairing_skips_volvo(self):
        self.assertEqual(self.login("x" * 22)[0], 410)
        code, _ = self.start()
        self.db.items[code]["ttl"] = {"N": str(int(time.time()) - 1)}
        self.assertEqual(self.login(code)[0], 410)
        self.assertEqual(self.volvo_calls, 0)

    def test_second_login_on_same_pairing_rejected(self):
        code, _ = self.start()
        self.assertEqual(self.login(code)[0], 200)
        self.assertEqual(self.login(code)[0], 410)
        self.assertEqual(self.volvo_calls, 1)

    def test_wrong_secret_looks_like_unknown(self):
        code, _ = self.start()
        self.assertEqual(self.poll(code, "nope")[0], 404)



class InputChecksTest(LambdaTest):
    """Junk never reaches Volvo."""

    def assertRejected(self, status_and_data, error):
        self.assertEqual(status_and_data, (400, {"error": error}))
        self.assertEqual(self.volvo_calls, 0)

    def exchange(self, code="a1b2.c3d4-e5f6", verifier=VERIFIER):
        return post(grant_type="authorization_code", code=code, code_verifier=verifier)

    def refresh(self, token):
        return post(grant_type="refresh_token", refresh_token=token)

    def test_valid_requests_pass(self):
        self.assertEqual(self.exchange()[0], 200)
        jwt = "eyJhbGciOiJIUzUxMiJ9.eyJzdWIiOiIxIn0.c2lnX-_x"
        self.assertEqual(self.refresh(jwt)[0], 200)
        self.assertEqual(self.volvo_calls, 2)

    def test_bad_auth_code(self):
        self.assertRejected(self.exchange(code="a" * 2049), "invalid_code")
        self.assertRejected(self.exchange(code="abc def"), "invalid_code")
        self.assertRejected(self.exchange(code="abc&x=1"), "invalid_code")

    def test_bad_code_verifier(self):
        self.assertRejected(self.exchange(verifier="short"), "invalid_code_verifier")
        self.assertRejected(self.exchange(verifier="v" * 129), "invalid_code_verifier")
        self.assertRejected(self.exchange(verifier="v" * 42 + "!"), "invalid_code_verifier")

    def test_bad_refresh_token(self):
        self.assertRejected(self.refresh("t" * 8193), "invalid_refresh_token")
        self.assertRejected(self.refresh("tok\nen"), "invalid_refresh_token")

    def test_huge_body(self):
        status, data = post_body("x" * (2 * tx.MAX_BODY_BYTES + 1))
        self.assertEqual((status, data), (413, {"error": "request_too_large"}))
        self.assertEqual(self.volvo_calls, 0)



class FakeSSM:
    def __init__(self, values):
        self.values = values
        self.loads = 0

    def get_parameters(self, Names, WithDecryption):
        self.loads += 1
        return {"Parameters": [{"Name": n, "Value": self.values[n.split("/")[-1]]}
                               for n in Names if n.split("/")[-1] in self.values]}


class ConfigAndErrorsTest(unittest.TestCase):
    """Config cache, fail-closed config, Volvo network errors, safe logs."""

    def setUp(self):
        self.ssm = FakeSSM(dict(CONFIG))
        fake_boto3 = type(sys)("boto3")
        fake_boto3.client = lambda name: self.ssm
        self._orig_boto3 = sys.modules.get("boto3")
        sys.modules["boto3"] = fake_boto3
        tx._config, tx._config_expires = {}, 0
        self._orig_urlopen = tx.urllib.request.urlopen
        self.logs = []
        self._orig_print = tx.print if hasattr(tx, "print") else None
        tx.print = lambda line: self.logs.append(json.loads(line))

    def tearDown(self):
        if self._orig_boto3 is None:
            sys.modules.pop("boto3", None)
        else:
            sys.modules["boto3"] = self._orig_boto3
        tx.urllib.request.urlopen = self._orig_urlopen
        del tx.print
        tx._config, tx._config_expires = {}, 0

    def test_config_cached_then_reloaded(self):
        tx.get_config()
        tx.get_config()
        self.assertEqual(self.ssm.loads, 1)
        tx._config_expires = time.time() - 1
        tx.get_config()
        self.assertEqual(self.ssm.loads, 2)

    def test_missing_config_fails_closed(self):
        del self.ssm.values["allowed-origins"]
        status, data = post_handler(action="pair_start")
        self.assertEqual((status, data), (503, {"error": "not_configured"}))
        self.assertEqual(self.logs, [{"level": "error", "event": "config_missing",
                                      "params": ["allowed-origins"]}])

    def volvo_fails(self, exc):
        def urlopen(req, timeout=None):
            self.assertEqual(timeout, tx.VOLVO_TIMEOUT_SECONDS)
            raise exc
        tx.urllib.request.urlopen = urlopen
        return post(grant_type="refresh_token", refresh_token="tok.en")

    def test_network_error_hides_reason(self):
        exc = tx.urllib.error.URLError(OSError("getaddrinfo failed for auth.volvocars.com"))
        status, data = self.volvo_fails(exc)
        self.assertEqual(status, 502)
        self.assertEqual(data["error"], "network_error")
        self.assertNotIn("getaddrinfo", json.dumps(data))
        self.assertEqual(self.logs[-1]["event"], "volvo_network_error")

    def test_timeout(self):
        self.assertEqual(self.volvo_fails(TimeoutError())[0], 504)
        status, _ = self.volvo_fails(tx.urllib.error.URLError(TimeoutError()))
        self.assertEqual(status, 504)

    def test_unhandled_error_logs_type_only(self):
        def boom(body):
            raise ValueError("secret-token-in-message")
        orig, tx.fetch_tokens = tx.fetch_tokens, boom
        try:
            status, data = post_handler(grant_type="refresh_token", refresh_token="tok.en")
        finally:
            tx.fetch_tokens = orig
        self.assertEqual((status, data), (500, {"error": "internal_error"}))
        self.assertEqual(self.logs, [{"level": "error", "event": "unhandled",
                                      "error": "ValueError", "kind": "refresh_token"}])


if __name__ == "__main__":
    unittest.main()
