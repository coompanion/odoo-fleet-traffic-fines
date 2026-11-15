# Part of Fleet Traffic Fines. See LICENSE file for full copyright and licensing details.
from odoo import fields, models, _

from .vyto_api import DEFAULT_API_URL, PARAM_API_KEY, PARAM_API_URL, VytoApi


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    vyto_api_key = fields.Char(string="vyto API key", config_parameter=PARAM_API_KEY,
                               help="Create the key in vyto under Settings > Integrations > API keys.")
    vyto_api_url = fields.Char(string="vyto API URL", config_parameter=PARAM_API_URL, default=DEFAULT_API_URL,
                               help="Only change this for a vyto test environment.")

    def action_vyto_test_connection(self):
        self.ensure_one()
        # Test what was typed, even before saving
        self.execute()
        result = VytoApi(self.env).ping()
        account = (result.get("account") or {}).get("name") or "-"
        scopes = ", ".join((result.get("key") or {}).get("scopes") or [])
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "type": "success",
                "title": _("Connected to vyto"),
                "message": _("Account: %(account)s. Permissions: %(scopes)s.", account=account, scopes=scopes),
            },
        }
