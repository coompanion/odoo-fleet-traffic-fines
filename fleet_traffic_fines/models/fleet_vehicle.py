# Part of Fleet Traffic Fines. See LICENSE file for full copyright and licensing details.
from odoo import fields, models, _


class FleetVehicle(models.Model):
    _inherit = "fleet.vehicle"

    traffic_fine_ids = fields.One2many("fleet.traffic.fine", "vehicle_id", string="Traffic Fines")
    traffic_fine_open_count = fields.Integer(compute="_compute_traffic_fine_open_count", string="Open traffic fines")

    def _compute_traffic_fine_open_count(self):
        data = self.env["fleet.traffic.fine"]._read_group(
            [("vehicle_id", "in", self.ids), ("is_open", "=", True)], ["vehicle_id"], ["__count"])
        counts = {vehicle.id: count for vehicle, count in data}
        for vehicle in self:
            vehicle.traffic_fine_open_count = counts.get(vehicle.id, 0)

    def action_view_traffic_fines(self):
        self.ensure_one()
        action = self.env["ir.actions.act_window"]._for_xml_id("fleet_traffic_fines.action_fleet_traffic_fine")
        action.update({
            "domain": [("vehicle_id", "=", self.id)],
            "context": {"search_default_filter_open": 1, "default_vehicle_id": self.id},
            "name": _("Traffic Fines of %(vehicle)s", vehicle=self.display_name),
        })
        return action

    def action_upload_traffic_notice(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Upload notice"),
            "res_model": "fleet.traffic.fine.upload",
            "view_mode": "form",
            "target": "new",
            "context": {"default_vehicle_id": self.id},
        }
