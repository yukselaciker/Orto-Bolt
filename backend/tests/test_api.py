from __future__ import annotations

import unittest

from fastapi.testclient import TestClient

from backend.app.main import app
from core.bolton_logic import analyze_anterior, analyze_overall
from backend.app.storage import DB_PATH


SAMPLE_MEASUREMENTS = {
    16: 10.4,
    15: 7.1,
    14: 7.3,
    13: 8.1,
    12: 6.6,
    11: 8.7,
    21: 8.7,
    22: 6.5,
    23: 8.0,
    24: 7.2,
    25: 7.0,
    26: 10.2,
    46: 11.0,
    45: 7.2,
    44: 7.3,
    43: 7.0,
    42: 6.1,
    41: 5.4,
    31: 5.3,
    32: 6.0,
    33: 6.9,
    34: 7.1,
    35: 7.0,
    36: 10.8,
}


class AnalysisApiTests(unittest.TestCase):
    def setUp(self) -> None:
        if DB_PATH.exists():
            DB_PATH.unlink()
        self.client = TestClient(app)

    def test_anterior_endpoint_matches_core_logic(self) -> None:
        response = self.client.post(
            "/api/v1/analysis/anterior",
            json={"measurements": SAMPLE_MEASUREMENTS},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        expected = analyze_anterior(SAMPLE_MEASUREMENTS)

        self.assertEqual(payload["ratio"], expected.ratio)
        self.assertEqual(payload["difference"], expected.difference)
        self.assertEqual(payload["discrepancy_mm"], expected.discrepancy_mm)
        self.assertEqual(payload["discrepancy_arch"], expected.discrepancy_arch)

    def test_combined_endpoint_matches_core_logic(self) -> None:
        response = self.client.post(
            "/api/v1/analysis/combined",
            json={"measurements": SAMPLE_MEASUREMENTS},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()

        expected_ant = analyze_anterior(SAMPLE_MEASUREMENTS)
        expected_ovr = analyze_overall(SAMPLE_MEASUREMENTS)

        self.assertEqual(payload["anterior"]["ratio"], expected_ant.ratio)
        self.assertEqual(payload["overall"]["ratio"], expected_ovr.ratio)
        self.assertEqual(payload["overall"]["discrepancy_mm"], expected_ovr.discrepancy_mm)

    def test_export_json_endpoint_returns_analysis_payload(self) -> None:
        response = self.client.post(
            "/api/v1/export/json",
            json={
                "measurements": SAMPLE_MEASUREMENTS,
                "patient_id": "Test Hasta",
                "report_date": "27.03.2026",
                "maxilla_filename": "ust.stl",
                "mandible_filename": "alt.stl",
                "treatment_notes": "Not",
            },
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["patient_id"], "Test Hasta")
        self.assertIn("analysis", payload)
        self.assertIn("measurement_rows", payload)

    def test_patient_and_record_flow(self) -> None:
        patient = self.client.post(
            "/api/v1/patients",
            json={"name": "Ayse Test", "patient_code": "P-001", "notes": "Kontrol"},
        )
        self.assertEqual(patient.status_code, 200)
        patient_payload = patient.json()

        record = self.client.post(
            "/api/v1/records",
            json={
                "patient_id": patient_payload["id"],
                "title": "Ilk kayit",
                "analysis_mode": "anterior",
                "payload": {
                    "saved_at": "2026-03-27T12:00:00",
                    "mode": "anterior",
                    "values": {"11": "8.7"},
                    "result": None,
                    "maxillaInfo": None,
                    "mandibleInfo": None,
                    "activeViewerJaw": "maxillary",
                    "maxillaFile": None,
                    "mandibleFile": None,
                    "landmarks": [],
                },
            },
        )
        self.assertEqual(record.status_code, 200)
        record_payload = record.json()
        self.assertEqual(record_payload["title"], "Ilk kayit")

        listed = self.client.get(f"/api/v1/records?patient_id={patient_payload['id']}")
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(len(listed.json()), 1)

        searched = self.client.get("/api/v1/patients?q=ayse")
        self.assertEqual(searched.status_code, 200)
        self.assertEqual(len(searched.json()), 1)

        deleted = self.client.delete(f"/api/v1/records/{record_payload['id']}")
        self.assertEqual(deleted.status_code, 200)
        self.assertTrue(deleted.json()["deleted"])


if __name__ == "__main__":
    unittest.main()
