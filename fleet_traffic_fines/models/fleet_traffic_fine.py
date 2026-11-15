# Part of Fleet Traffic Fines. See LICENSE file for full copyright and licensing details.
import logging
from datetime import date, datetime

import pytz

from odoo import api, fields, models, _

from .vyto_api import PARAM_LAST_SYNC, VytoApi, VytoApiError, normalize_plate

_logger = logging.getLogger(__name__)

# Values as delivered by vyto (German), labels in English; translated back in i18n/de.po
KIND_SELECTION = [
    ("Verkehrsordnungswidrigkeit", "Traffic offense"),
    ("Zeugenanhörung", "Witness hearing"),
    ("Verwarnung", "Warning notice"),
    ("Bußgeldbescheid", "Fine notice"),
    ("Zahlungsaufforderung", "Payment request"),
    ("Mahnung", "Reminder"),
    ("Inkasso", "Debt collection"),
    ("Mahnbescheid", "Court payment order"),
    ("Vollstreckungsbescheid", "Enforcement order"),
    ("Pfändung", "Garnishment"),
    ("Unfall", "Accident / damage"),
    ("Anderes", "Other"),
]
STATUS_SELECTION = [
    ("Neu", "New"),
    ("Zugeordnet", "Driver assigned"),
    ("Bereit", "Ready to send"),
    ("Abgeschlossen", "Done"),
    ("Archiviert", "Archived"),
]
OPEN_STATUSES = ("Neu", "Zugeordnet", "Bereit")


def _parse_datetime(value):
    """ISO 8601 from vyto → naive UTC datetime as Odoo stores it."""
    if not value:
        return False
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo:
        dt = dt.astimezone(pytz.UTC).replace(tzinfo=None)
    return dt


def _parse_date(value):
    return date.fromisoformat(value[:10]) if value else False


class FleetTrafficFine(models.Model):
    _name = "fleet.traffic.fine"
    _description = "Traffic Fine"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "deadline asc, offense_date desc, id desc"
    _rec_name = "name"

    name = fields.Char(compute="_compute_name", store=True)
    vyto_id = fields.Char(string="vyto ID", required=True, readonly=True, index=True, copy=False)
    vyto_url = fields.Char(string="Open in vyto", readonly=True)
    company_id = fields.Many2one("res.company", required=True, readonly=True, default=lambda self: self.env.company)
    license_plate = fields.Char(readonly=True)
    license_plate_normalized = fields.Char(readonly=True, index=True)
    vehicle_id = fields.Many2one("fleet.vehicle", string="Vehicle", readonly=True, index=True, tracking=True)
    driver_id = fields.Many2one("res.partner", string="Driver", readonly=True, index=True, tracking=True,
                                help="Driver of the vehicle on the day of the offense, taken from the vehicle's driver history.")
    manager_id = fields.Many2one(related="vehicle_id.manager_id", string="Fleet Manager")
    kind = fields.Selection(KIND_SELECTION, readonly=True)
    status = fields.Selection(STATUS_SELECTION, readonly=True, tracking=True)
    is_open = fields.Boolean(string="Open", readonly=True, index=True)
    reference = fields.Char(string="Authority reference", readonly=True)
    authority = fields.Char(readonly=True)
    offense = fields.Char(readonly=True)
    offense_location = fields.Char(readonly=True)
    offense_date = fields.Datetime(readonly=True)
    offense_timezone = fields.Char(readonly=True)
    letter_date = fields.Date(readonly=True)
    amount = fields.Monetary(readonly=True, currency_field="currency_id")
    currency_id = fields.Many2one("res.currency", readonly=True)
    deadline = fields.Date(readonly=True, tracking=True, help="Earliest deadline of an open case")
    deadline_response = fields.Date(string="Response deadline", readonly=True)
    deadline_objection = fields.Date(string="Objection deadline", readonly=True)
    deadline_payment = fields.Date(string="Payment deadline", readonly=True)
    vyto_updated_at = fields.Datetime(string="Last change in vyto", readonly=True)
    deadline_activity_id = fields.Many2one("mail.activity", readonly=True, copy=False, index="btree_not_null")

    _vyto_id_company_uniq = models.Constraint(
        "unique(vyto_id, company_id)",
        "Each vyto case exists only once per company.",
    )

    @api.depends("reference", "license_plate", "kind")
    def _compute_name(self):
        kinds = dict(self._fields["kind"]._description_selection(self.env))
        for fine in self:
            parts = [kinds.get(fine.kind) or _("Traffic fine"), fine.reference or fine.license_plate]
            fine.name = " – ".join(p for p in parts if p)

    def action_open_in_vyto(self):
        self.ensure_one()
        return {"type": "ir.actions.act_url", "url": self.vyto_url, "target": "new"}

    # ------------------------------------------------------------------
    # Sync from vyto
    # ------------------------------------------------------------------

    @api.model
    def _cron_sync_vyto(self):
        try:
            self._sync_from_vyto()
        except VytoApiError as e:
            _logger.warning("Traffic fines sync skipped: %s", e)

    @api.model
    def _sync_from_vyto(self):
        """Fetch cases changed since the last sync and mirror them. Returns the number of cases received."""
        api_client = VytoApi(self.env)
        icp = self.env["ir.config_parameter"].sudo()
        since = icp.get_param(PARAM_LAST_SYNC) or None
        latest = since
        cursor = None
        received = 0
        vehicles = self._vehicles_by_plate()
        while True:
            page = api_client.list_cases(updated_since=since, cursor=cursor)
            for case in page.get("data", []):
                self._upsert_case(case, vehicles)
                received += 1
                if not latest or case["updated_at"] > latest:
                    latest = case["updated_at"]
            if not page.get("has_more"):
                break
            cursor = page.get("next_cursor")
        # Vehicles created after a fine arrived: try to match again
        self.sudo().search([("vehicle_id", "=", False), ("license_plate_normalized", "!=", False)])._match_vehicle(vehicles)
        if latest:
            icp.set_param(PARAM_LAST_SYNC, latest)
        self._schedule_deadline_activities()
        return received

    @api.model
    def _vehicles_by_plate(self):
        """Normalized plate → vehicle. Active vehicles win over archived ones (a sold car may share the plate)."""
        result = {}
        vehicles = self.env["fleet.vehicle"].sudo().with_context(active_test=False).search(
            [("license_plate", "!=", False)], order="active asc, id asc")
        for vehicle in vehicles:
            key = normalize_plate(vehicle.license_plate)
            if key:
                result[key] = vehicle
        return result

    @api.model
    def _upsert_case(self, case, vehicles):
        currency = self.env["res.currency"].with_context(active_test=False).search([("name", "=", case.get("currency") or "EUR")], limit=1)
        deadlines = case.get("deadlines") or {}
        kinds = {k for k, _label in KIND_SELECTION}
        statuses = {k for k, _label in STATUS_SELECTION}
        values = {
            "vyto_url": case.get("url"),
            "license_plate": case.get("license_plate"),
            "license_plate_normalized": case.get("license_plate_normalized") or normalize_plate(case.get("license_plate")),
            "kind": case.get("kind") if case.get("kind") in kinds else "Anderes" if case.get("kind") else False,
            "status": case.get("status") if case.get("status") in statuses else False,
            "is_open": bool(case.get("open")),
            "reference": case.get("reference"),
            "authority": case.get("authority"),
            "offense": case.get("offense"),
            "offense_location": case.get("offense_location"),
            "offense_date": _parse_datetime(case.get("offense_at")),
            "offense_timezone": case.get("offense_timezone"),
            "letter_date": _parse_date(case.get("letter_date")),
            "amount": case.get("amount") or 0.0,
            "currency_id": currency.id or False,
            "deadline": _parse_date(case.get("deadline")),
            "deadline_response": _parse_date(deadlines.get("response")),
            "deadline_objection": _parse_date(deadlines.get("objection")),
            "deadline_payment": _parse_date(deadlines.get("payment")),
            "vyto_updated_at": _parse_datetime(case.get("updated_at")),
        }
        fine = self.sudo().search([("vyto_id", "=", case["id"]), ("company_id", "=", self.env.company.id)], limit=1)
        if fine:
            fine.write(values)
        else:
            fine = self.sudo().create(dict(values, vyto_id=case["id"], company_id=self.env.company.id))
        fine._match_vehicle(vehicles)
        return fine

    def _match_vehicle(self, vehicles):
        for fine in self:
            vehicle = vehicles.get(fine.license_plate_normalized or "")
            if vehicle and fine.vehicle_id != vehicle:
                fine.vehicle_id = vehicle
            fine.driver_id = fine._driver_on_offense_day()

    def _offense_day(self):
        """Day of the offense in the time zone of the offense location (driver history only knows days)."""
        self.ensure_one()
        if not self.offense_date:
            return False
        try:
            tz = pytz.timezone(self.offense_timezone or "Europe/Berlin")
        except pytz.UnknownTimeZoneError:
            tz = pytz.timezone("Europe/Berlin")
        return pytz.UTC.localize(self.offense_date).astimezone(tz).date()

    def _driver_on_offense_day(self):
        """The one driver assigned to the vehicle on the offense day; nobody if unknown or ambiguous."""
        self.ensure_one()
        day = self._offense_day()
        if not self.vehicle_id or not day:
            return self.env["res.partner"]
        logs = self.env["fleet.vehicle.assignation.log"].sudo().search([
            ("vehicle_id", "=", self.vehicle_id.id),
            ("date_start", "<=", day),
            "|", ("date_end", "=", False), ("date_end", ">=", day),
        ])
        drivers = logs.mapped("driver_id")
        return drivers if len(drivers) == 1 else self.env["res.partner"]

    # ------------------------------------------------------------------
    # Deadline activities
    # ------------------------------------------------------------------

    @api.model
    def _schedule_deadline_activities(self):
        """One to-do per open fine and deadline, for the fleet manager of the vehicle. Never twice for the same deadline."""
        fines = self.sudo().search([("is_open", "=", True), ("deadline", "!=", False), ("vehicle_id.manager_id", "!=", False)])
        for fine in fines:
            current = fine.deadline_activity_id
            if current.exists() and current.date_deadline == fine.deadline:
                continue
            if current.exists():
                current.unlink()
            activity = fine.activity_schedule(
                "mail.mail_activity_data_todo",
                date_deadline=fine.deadline,
                summary=_("Traffic fine deadline: %(ref)s", ref=fine.reference or fine.license_plate or ""),
                note=_("Handle this case in vyto before the deadline."),
                user_id=fine.vehicle_id.manager_id.id,
            )
            fine.deadline_activity_id = activity
        # Closed fines: remove their open deadline to-do
        closed = self.sudo().search([("is_open", "=", False), ("deadline_activity_id", "!=", False)])
        closed.deadline_activity_id.exists().unlink()
        closed.deadline_activity_id = False

    @api.model
    def action_sync_now(self):
        received = self._sync_from_vyto()
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "type": "success",
                "message": _("%(count)s changed case(s) received from vyto.", count=received),
                "next": {"type": "ir.actions.client", "tag": "soft_reload"},
            },
        }
