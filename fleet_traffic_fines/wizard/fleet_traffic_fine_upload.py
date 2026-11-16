# Part of Fleet Traffic Fines. See LICENSE file for full copyright and licensing details.
import hashlib

from odoo import fields, models, _
from odoo.exceptions import UserError

from ..models.vyto_api import VytoApi

MAX_BYTES = 5 * 1024 * 1024


class FleetTrafficFineUpload(models.TransientModel):
    _name = "fleet.traffic.fine.upload"
    _description = "Send a traffic notice to vyto"

    vehicle_id = fields.Many2one("fleet.vehicle", string="Vehicle",
                                 help="vyto uses its license plate if the notice itself shows none.")
    file = fields.Binary(string="Notice (PDF)", required=True, attachment=False)
    filename = fields.Char()

    def action_upload(self):
        self.ensure_one()
        content = self.file.content if self.file else b""
        if not content.startswith(b"%PDF-"):
            raise UserError(_("Please choose a PDF file."))
        if len(content) > MAX_BYTES:
            raise UserError(_("The file is larger than 5 MB."))
        # Same file from the same database is sent only once (vyto answers with the first upload)
        dbuuid = self.env["ir.config_parameter"].sudo().get_str("database.uuid")
        external_ref = f"odoo-{dbuuid[:8]}-{hashlib.sha256(content).hexdigest()[:32]}"
        result = VytoApi(self.env).upload_document(
            content,
            self.filename or "notice.pdf",
            license_plate=self.vehicle_id.license_plate or None,
            external_ref=external_ref,
        )
        if result.get("duplicate"):
            message = _("vyto already has this notice.")
        else:
            message = _("Sent to vyto. The case appears here with the next sync once vyto has read the notice.")
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "type": "success",
                "message": message,
                "next": {"type": "ir.actions.act_window_close"},
            },
        }
