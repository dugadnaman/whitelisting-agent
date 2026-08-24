"""
Comprehensive Multi-Tenant Authentication & Strict Tenant Isolation Tests.
Verifies signup, login, JWT validation, 403 Forbidden tenant isolation, and team management.
"""

import os
import unittest
import uuid

from fastapi.testclient import TestClient

import api
import auth


class TestMultiTenantAuth(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(api.app)

    def test_signup_and_login_flow(self):
        """Verify user signup binds to selected tenant and login returns signed JWT."""
        unique_email = f"test_user_{uuid.uuid4().hex[:6]}@bajajfinserv.in"
        signup_payload = {
            "email": unique_email,
            "password": "SecurePassword123",
            "name": "Test Bajaj Operator",
            "tenant_id": "bajaj",
            "role": "operator",
        }

        # 1. Signup
        r_signup = self.client.post("/api/auth/signup", json=signup_payload)
        self.assertEqual(r_signup.status_code, 200, f"Signup failed: {r_signup.text}")
        signup_data = r_signup.json()
        self.assertIn("token", signup_data)
        self.assertEqual(signup_data["user"]["tenant_id"], "bajaj")

        # 2. Login
        r_login = self.client.post("/api/auth/login", json={"email": unique_email, "password": "SecurePassword123"})
        self.assertEqual(r_login.status_code, 200)
        login_data = r_login.json()
        token = login_data["token"]
        self.assertIsNotNone(token)

        # 3. Verify /api/auth/me
        r_me = self.client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(r_me.status_code, 200)
        me_data = r_me.json()
        self.assertEqual(me_data["email"], unique_email)
        self.assertEqual(me_data["tenant_id"], "bajaj")

    def test_invalid_login_rejected(self):
        """Invalid credentials return 401 Unauthorized."""
        r = self.client.post("/api/auth/login", json={"email": "nonexistent@user.com", "password": "WrongPassword"})
        self.assertEqual(r.status_code, 401)
        self.assertIn("Invalid email or password", r.json()["detail"])

    def test_duplicate_email_signup_rejected(self):
        """Attempting to signup with existing email returns 400 Bad Request."""
        unique_email = f"dup_{uuid.uuid4().hex[:6]}@tata.com"
        payload = {"email": unique_email, "password": "PassWord123", "name": "Tata User", "tenant_id": "tata"}
        r1 = self.client.post("/api/auth/signup", json=payload)
        self.assertEqual(r1.status_code, 200)

        # Duplicate signup attempt
        r2 = self.client.post("/api/auth/signup", json=payload)
        self.assertEqual(r2.status_code, 400)
        self.assertIn("already exists", r2.json()["detail"])

    def test_strict_tenant_isolation_enforcement(self):
        """
        Critical Multi-Tenant Isolation Check:
        Bajaj operator CANNOT access Tata templates, stats, or credentials.
        Tata operator CANNOT access Bajaj templates, stats, or credentials.
        """
        # 1. Login as Bajaj Operator
        r_bajaj_login = self.client.post("/api/auth/login", json={"email": "bajaj@karix.com", "password": "Bajaj@123"})
        self.assertEqual(r_bajaj_login.status_code, 200)
        bajaj_token = r_bajaj_login.json()["token"]
        bajaj_headers = {"Authorization": f"Bearer {bajaj_token}"}

        # 2. Login as Tata Operator
        r_tata_login = self.client.post("/api/auth/login", json={"email": "tata@karix.com", "password": "Tata@123"})
        self.assertEqual(r_tata_login.status_code, 200)
        tata_token = r_tata_login.json()["token"]
        tata_headers = {"Authorization": f"Bearer {tata_token}"}

        # --- Bajaj user allowed on Bajaj ---
        self.assertEqual(self.client.get("/api/stats?account=bajaj", headers=bajaj_headers).status_code, 200)
        self.assertEqual(self.client.get("/api/credentials?account=bajaj", headers=bajaj_headers).status_code, 200)

        # --- Bajaj user strictly BLOCKED from Tata with 403 Forbidden ---
        r_blocked_1 = self.client.get("/api/stats?account=tata", headers=bajaj_headers)
        self.assertEqual(r_blocked_1.status_code, 403)
        self.assertIn("Access Denied", r_blocked_1.json()["detail"])

        r_blocked_2 = self.client.get("/api/templates?account=tata", headers=bajaj_headers)
        self.assertEqual(r_blocked_2.status_code, 403)

        r_blocked_3 = self.client.get("/api/credentials?account=tata", headers=bajaj_headers)
        self.assertEqual(r_blocked_3.status_code, 403)

        # --- Tata user allowed on Tata ---
        self.assertEqual(self.client.get("/api/stats?account=tata&channel=rcs", headers=tata_headers).status_code, 200)
        self.assertEqual(self.client.get("/api/credentials?account=tata", headers=tata_headers).status_code, 200)

        # --- Tata user strictly BLOCKED from Bajaj with 403 Forbidden ---
        r_blocked_4 = self.client.get("/api/stats?account=bajaj", headers=tata_headers)
        self.assertEqual(r_blocked_4.status_code, 403)
        self.assertIn("Access Denied", r_blocked_4.json()["detail"])

        r_blocked_5 = self.client.get("/api/templates?account=bajaj", headers=tata_headers)
        self.assertEqual(r_blocked_5.status_code, 403)

    def test_superadmin_accesses_all_tenants(self):
        """Platform Superadmin (admin@karix.com) can access any tenant organization."""
        r_admin_login = self.client.post("/api/auth/login", json={"email": "admin@karix.com", "password": "Admin@123"})
        self.assertEqual(r_admin_login.status_code, 200)
        admin_token = r_admin_login.json()["token"]
        admin_headers = {"Authorization": f"Bearer {admin_token}"}

        # Superadmin can query Bajaj and Tata
        self.assertEqual(self.client.get("/api/stats?account=bajaj", headers=admin_headers).status_code, 200)
        self.assertEqual(self.client.get("/api/stats?account=tata&channel=rcs", headers=admin_headers).status_code, 200)

    def test_copilot_tenant_isolation(self):
        """AI Copilot blocks cross-tenant query attempts for locked operators."""
        r_bajaj_login = self.client.post("/api/auth/login", json={"email": "bajaj@karix.com", "password": "Bajaj@123"})
        bajaj_token = r_bajaj_login.json()["token"]
        bajaj_headers = {"Authorization": f"Bearer {bajaj_token}"}

        # Request targeting Tata from Bajaj operator
        r_chat = self.client.post(
            "/api/agent/chat",
            json={"message": "List templates for tata", "account": "tata"},
            headers=bajaj_headers,
        )
        self.assertEqual(r_chat.status_code, 403)
        self.assertIn("Access Denied", r_chat.json()["detail"])


if __name__ == "__main__":
    unittest.main()
