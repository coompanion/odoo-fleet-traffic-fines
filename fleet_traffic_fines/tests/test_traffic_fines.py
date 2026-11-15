# Part of Fleet Traffic Fines. See LICENSE file for full copyright and licensing details.
import base64
from datetime import date, timedelta
from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged

from ..models.vyto_api import PARAM_API_KEY, PARAM_LAST_SYNC, normalize_plate

API = "odoo.addons.fleet_traffic_fines.models.vyto_api.VytoApi"


def vyto_case(case_id, plate="B-VY 201", status="Neu", deadline=None, updated="2026-11-10T10:00:00+00:00", offense="2026-11-05T13:32:00+00:00"):
    return {
        "id": case_id,
        "url": f"https://app.vyto.ai/cases/{case_id}",
        "status": status,
        "open": status in ("Neu", "Zugeordnet", "Bereit"),
        "kind": "Zeugenanhörung",
        "reference": f"AZ-{case_id[:4]}",
        "license_plate": plate,
        "license_plate_normalized": normalize_plate(plate),
        "offense_at": offense,
        "offense_timezone": "Europe/Berlin",
        "offense": "Speeding",
        "offense_location": "Berlin",
        "amount": 35.0,
        "currency": "EUR",
        "authority": "Stadt Musterstadt",
        "letter_date": "2026-11-08",
        "deadline": deadline,
        "deadlines": {"response": deadline, "objection": None, "payment": None},
        "updated_at": updated,
    }


@tagged("post_install", "-at_install")
class TestTrafficFines(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env["ir.config_parameter"].sudo().set_param(PARAM_API_KEY, "vyto_" + "A" * 43)
        # Independent of an earlier real sync in the same database
        cls.env["ir.config_parameter"].sudo().set_param(PARAM_LAST_SYNC, "")
        cls.manager_user = cls.env["res.users"].create({
            "name": "Fleet Manager",
            "login": "fleet_manager_tf",
            "group_ids": [(6, 0, [cls.env.ref("fleet.fleet_group_manager").id])],
        })
        brand = cls.env["fleet.vehicle.model.brand"].create({"name": "Test Brand"})
        model = cls.env["fleet.vehicle.model"].create({"name": "Test Model", "brand_id": brand.id})
        cls.driver_a = cls.env["res.partner"].create({"name": "Driver A"})
        cls.driver_b = cls.env["res.partner"].create({"name": "Driver B"})
        cls.vehicle = cls.env["fleet.vehicle"].create({
            "model_id": model.id,
            "license_plate": "B VY201",
            "manager_id": cls.manager_user.id,
        })
        Log = cls.env["fleet.vehicle.assignation.log"]
        Log.create({"vehicle_id": cls.vehicle.id, "driver_id": cls.driver_a.id, "date_start": date(2026, 11, 1), "date_end": date(2026, 11, 5)})
        Log.create({"vehicle_id": cls.vehicle.id, "driver_id": cls.driver_b.id, "date_start": date(2026, 11, 6)})
        cls.Fine = cls.env["fleet.traffic.fine"]

    def _sync(self, pages):
        with patch(f"{API}.list_cases", side_effect=pages) as mocked:
            received = self.Fine._sync_from_vyto()
        return received, mocked

    def test_sync_creates_and_matches_vehicle_and_driver(self):
        received, _mock = self._sync([{"data": [vyto_case("11111111-0000-0000-0000-000000000001")], "has_more": False}])
        self.assertEqual(received, 1)
        fine = self.Fine.search([("vyto_id", "=", "11111111-0000-0000-0000-000000000001")])
        self.assertEqual(fine.vehicle_id, self.vehicle, "plate matches regardless of spaces and dashes")
        self.assertEqual(fine.driver_id, self.driver_a, "driver from the history on the offense day")
        self.assertEqual(fine.kind, "Zeugenanhörung")
        self.assertTrue(fine.is_open)

    def test_sync_is_incremental_and_updates(self):
        cid = "11111111-0000-0000-0000-000000000002"
        self._sync([{"data": [vyto_case(cid)], "has_more": False}])
        self.assertEqual(self.env["ir.config_parameter"].sudo().get_param(PARAM_LAST_SYNC), "2026-11-10T10:00:00+00:00")
        _received, mocked = self._sync([{"data": [vyto_case(cid, status="Abgeschlossen", updated="2026-11-12T08:00:00+00:00")], "has_more": False}])
        self.assertEqual(mocked.call_args.kwargs.get("updated_since"), "2026-11-10T10:00:00+00:00")
        fines = self.Fine.search([("vyto_id", "=", cid)])
        self.assertEqual(len(fines), 1, "same vyto case is updated, not duplicated")
        self.assertEqual(fines.status, "Abgeschlossen")
        self.assertFalse(fines.is_open)

    def test_sync_follows_pages(self):
        pages = [
            {"data": [vyto_case("11111111-0000-0000-0000-000000000003")], "has_more": True, "next_cursor": "c1"},
            {"data": [vyto_case("11111111-0000-0000-0000-000000000004")], "has_more": False},
        ]
        received, mocked = self._sync(pages)
        self.assertEqual(received, 2)
        self.assertEqual(mocked.call_args_list[1].kwargs.get("cursor"), "c1")

    def test_ambiguous_or_unknown_driver_stays_empty(self):
        # Offense on the day of the driver change: both histories cover it
        self.env["fleet.vehicle.assignation.log"].create({
            "vehicle_id": self.vehicle.id, "driver_id": self.driver_b.id, "date_start": date(2026, 11, 5), "date_end": date(2026, 11, 5)})
        self._sync([{"data": [
            vyto_case("11111111-0000-0000-0000-000000000005"),
            vyto_case("11111111-0000-0000-0000-000000000006", plate="M-XX 1"),
        ], "has_more": False}])
        ambiguous = self.Fine.search([("vyto_id", "=", "11111111-0000-0000-0000-000000000005")])
        unknown = self.Fine.search([("vyto_id", "=", "11111111-0000-0000-0000-000000000006")])
        self.assertFalse(ambiguous.driver_id)
        self.assertFalse(unknown.vehicle_id)

    def test_smart_button_counts(self):
        self._sync([{"data": [
            vyto_case("11111111-0000-0000-0000-000000000007"),
            vyto_case("11111111-0000-0000-0000-000000000008", status="Abgeschlossen"),
        ], "has_more": False}])
        self.vehicle.invalidate_recordset(["traffic_fine_open_count"])
        self.assertEqual(self.vehicle.traffic_fine_open_count, 1)
        self.assertEqual(self.driver_a.traffic_fine_count, 2)
        action = self.vehicle.action_view_traffic_fines()
        self.assertEqual(action["domain"], [("vehicle_id", "=", self.vehicle.id)])

    def test_deadline_activity_once_per_deadline(self):
        cid = "11111111-0000-0000-0000-000000000009"
        deadline = (date.today() + timedelta(days=5)).isoformat()
        self._sync([{"data": [vyto_case(cid, deadline=deadline)], "has_more": False}])
        fine = self.Fine.search([("vyto_id", "=", cid)])
        self.assertEqual(len(fine.activity_ids), 1)
        self.assertEqual(fine.activity_ids.user_id, self.manager_user)
        # Same deadline again: no second activity
        self._sync([{"data": [vyto_case(cid, deadline=deadline, updated="2026-11-11T00:00:00+00:00")], "has_more": False}])
        self.assertEqual(len(fine.activity_ids), 1)
        # Deadline moved: old one replaced
        later = (date.today() + timedelta(days=9)).isoformat()
        self._sync([{"data": [vyto_case(cid, deadline=later, updated="2026-11-12T00:00:00+00:00")], "has_more": False}])
        self.assertEqual(len(fine.activity_ids), 1)
        self.assertEqual(fine.activity_ids.date_deadline.isoformat(), later)
        # Closed: activity removed
        self._sync([{"data": [vyto_case(cid, status="Abgeschlossen", deadline=None, updated="2026-11-13T00:00:00+00:00")], "has_more": False}])
        self.assertFalse(fine.activity_ids)

    def test_upload_sends_pdf_with_plate_and_stable_reference(self):
        pdf = b"%PDF-1.4 test"
        wizard = self.env["fleet.traffic.fine.upload"].with_user(self.manager_user).create({
            "vehicle_id": self.vehicle.id, "file": base64.b64encode(pdf), "filename": "notice.pdf"})
        with patch(f"{API}.upload_document", return_value={"id": "u1", "status": "received"}) as mocked:
            wizard.action_upload()
            wizard.action_upload()
        first, second = mocked.call_args_list
        self.assertEqual(first.args[0], pdf)
        self.assertEqual(first.kwargs["license_plate"], "B VY201")
        self.assertEqual(first.kwargs["external_ref"], second.kwargs["external_ref"], "same file, same reference")

    def test_upload_rejects_non_pdf(self):
        wizard = self.env["fleet.traffic.fine.upload"].create({"file": base64.b64encode(b"<html>"), "filename": "x.html"})
        with self.assertRaises(UserError):
            wizard.action_upload()

    def test_missing_key_is_a_clear_error(self):
        self.env["ir.config_parameter"].sudo().set_param(PARAM_API_KEY, "")
        with self.assertRaises(UserError):
            self.Fine._sync_from_vyto()
        # The cron must not crash
        self.Fine._cron_sync_vyto()

    def test_fleet_user_can_read_but_not_write(self):
        self._sync([{"data": [vyto_case("11111111-0000-0000-0000-000000000010")], "has_more": False}])
        user = self.env["res.users"].create({
            "name": "Fleet User", "login": "fleet_user_tf",
            "group_ids": [(6, 0, [self.env.ref("fleet.fleet_group_user").id])]})
        fine = self.Fine.with_user(user).search([("vyto_id", "=", "11111111-0000-0000-0000-000000000010")])
        self.assertTrue(fine.name)
        with self.assertRaises(Exception):
            fine.write({"status": "Bereit"})
