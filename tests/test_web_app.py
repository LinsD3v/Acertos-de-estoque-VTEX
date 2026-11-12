from __future__ import annotations

import base64
import csv
import io
import unittest
from concurrent.futures import ThreadPoolExecutor

from backend.app import _password_hash, app

TEST_PASSWORD = "test-password-for-session"


class StockWebAppTests(unittest.TestCase):
    def setUp(self) -> None:
        app.config.update(TESTING=True, SECRET_KEY="test-secret-key-long-enough-for-cookie-signing")
        app.config["PASSWORD_HASH"] = _password_hash(TEST_PASSWORD)
        self.client = app.test_client()
        self.login()

    def login(self) -> None:
        response = self.client.post("/login", data={"password": TEST_PASSWORD})
        self.assertEqual(response.status_code, 302)

    def test_authentication_and_health_endpoint(self) -> None:
        client = app.test_client()
        self.assertEqual(client.get("/login").status_code, 200)
        self.assertEqual(client.get("/").status_code, 302)
        self.assertEqual(client.get("/api/health").status_code, 401)
        self.assertEqual(self.client.get("/api/health").get_json(), {"status": "ok"})
        self.assertEqual(self.client.get("/").status_code, 200)

    def test_process_returns_preview_diagnostics_and_download_files(self) -> None:
        gix_content = "CÓDIGO;ESTOQUEATUAL\n0020197;7,75\nnão-mapeado;4\n".encode("utf-8-sig")
        response = self.client.post(
            "/api/process",
            data={"gix_file": (io.BytesIO(gix_content), "gix.csv")},
            content_type="multipart/form-data",
        )

        self.assertEqual(response.status_code, 200, response.get_json())
        payload = response.get_json()
        self.assertEqual(payload["record_count"], 1)
        self.assertEqual(payload["preview"][0]["SkuId"], "119917")
        self.assertEqual(payload["preview"][0]["RefId"], "7891019177189")
        self.assertIn("unmatched_gix", [item["code"] for item in payload["diagnostics"]])

        csv_bytes = base64.b64decode(payload["files"]["csv"]["base64"])
        xls_bytes = base64.b64decode(payload["files"]["xls"]["base64"])
        self.assertTrue(csv_bytes.startswith(b"\xef\xbb\xbf"))
        self.assertTrue(xls_bytes.startswith(bytes.fromhex("D0CF11E0A1B11AE1")))
        rows = list(csv.DictReader(io.StringIO(csv_bytes.decode("utf-8-sig"))))
        self.assertEqual(rows[0]["SkuId"], "119917")

    def test_process_requires_gix_csv(self) -> None:
        self.assertEqual(self.client.post("/api/process", data={}).status_code, 400)
        response = self.client.post(
            "/api/process",
            data={"gix_file": (io.BytesIO(b"data"), "gix.xls")},
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 400)

    def test_simultaneous_requests_have_isolated_outputs(self) -> None:
        def process(gix: str) -> tuple[str, str]:
            client = app.test_client()
            login = client.post("/login", data={"password": TEST_PASSWORD})
            if login.status_code != 302:
                raise AssertionError(f"Login falhou: {login.status_code}")
            content = f"CÓDIGO;ESTOQUEATUAL\n{gix};9\n".encode("utf-8-sig")
            response = client.post(
                "/api/process",
                data={"gix_file": (io.BytesIO(content), "gix.csv")},
                content_type="multipart/form-data",
            )
            if response.status_code != 200:
                raise AssertionError(response.get_json())
            output = base64.b64decode(response.get_json()["files"]["csv"]["base64"])
            rows = list(csv.DictReader(io.StringIO(output.decode("utf-8-sig"))))
            return rows[0]["SkuId"], rows[0]["TotalQuantity"]

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(process, ("0020197", "0020198")))

        self.assertEqual(results, [("119917", "9"), ("119916", "9")])


if __name__ == "__main__":
    unittest.main()
