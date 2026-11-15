# Part of Fleet Traffic Fines. See LICENSE file for full copyright and licensing details.
from odoo import fields, models, _


class ResPartner(models.Model):
    _inherit = "res.partner"

    traffic_fine_count = fields.Integer(compute="_compute_traffic_fine_count", string="Traffic fines",
                                        groups="fleet.fleet_group_user")

    def _compute_traffic_fine_count(self):
        data = self.env["fleet.traffic.fine"]._read_group([("driver_id", "in", self.ids)], ["driver_id"], ["__count"])
        counts = {partner.id: count for partner, count in data}
        for partner in self:
            partner.traffic_fine_count = counts.get(partner.id, 0)

    def action_view_traffic_fines(self):
        self.ensure_one()
        action = self.env["ir.actions.act_window"]._for_xml_id("fleet_traffic_fines.action_fleet_traffic_fine")
        action.update({
            "domain": [("driver_id", "=", self.id)],
            "context": {},
            "name": _("Traffic Fines of %(driver)s", driver=self.display_name),
        })
        return action
