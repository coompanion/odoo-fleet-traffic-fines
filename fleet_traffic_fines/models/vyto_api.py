# Part of Fleet Traffic Fines. See LICENSE file for full copyright and licensing details.
"""Small client for the vyto API v1 (https://vyto.ai).

Only the endpoints this module needs: ping, list cases (incremental), upload a notice.
The API key is stored as system parameter and never leaves the server.
"""
import logging
import re

import requests

from odoo import _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

DEFAULT_API_URL = "https://zcyezroeuxkmfoiffgjm.supabase.co/functions/v1/api/v1"
PARAM_API_KEY = "fleet_traffic_fines.api_key"
PARAM_API_URL = "fleet_traffic_fines.api_url"
PARAM_LAST_SYNC = "fleet_traffic_fines.last_sync"
TIMEOUT = 30


def normalize_plate(plate):
    """Same rule as vyto: upper case, only letters (incl. German umlauts) and digits."""
    return re.sub(r"[^A-ZÄÖÜ0-9]", "", (plate or "").upper())


class VytoApiError(UserError):
    pass


class VytoApi:
    def __init__(self, env):
        self.env = env
        icp = env["ir.config_parameter"].sudo()
        self.api_key = (icp.get_param(PARAM_API_KEY) or "").strip()
        self.base_url = (icp.get_param(PARAM_API_URL) or DEFAULT_API_URL).strip().rstrip("/")
        if not self.api_key:
            raise VytoApiError(_("No vyto API key configured. Add it in Fleet > Configuration > Settings."))
        if not self.base_url.startswith("https://"):
            raise VytoApiError(_("The vyto API URL must start with https://."))

    def _request(self, method, path, **kwargs):
        url = f"{self.base_url}{path}"
        headers = {"Authorization": f"Bearer {self.api_key}", "Accept": "application/json"}
        try:
            response = requests.request(method, url, headers=headers, timeout=TIMEOUT, **kwargs)
        except requests.RequestException as e:
            _logger.warning("vyto API %s %s failed: %s", method, path, e)
            raise VytoApiError(_("vyto is not reachable right now. Please try again later.")) from e
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        if response.status_code >= 400:
            message = (payload.get("error") or {}).get("message") or response.reason
            _logger.warning("vyto API %s %s: HTTP %s %s", method, path, response.status_code, message)
            if response.status_code == 401:
                raise VytoApiError(_("vyto rejected the API key. Check it in Fleet > Configuration > Settings."))
            raise VytoApiError(_("vyto answered with an error (HTTP %(status)s): %(message)s", status=response.status_code, message=message))
        return payload

    def ping(self):
        return self._request("GET", "/ping")

    def list_cases(self, updated_since=None, cursor=None, limit=200):
        params = {"limit": limit}
        if updated_since:
            params["updated_since"] = updated_since
        if cursor:
            params["cursor"] = cursor
        return self._request("GET", "/cases", params=params)

    def upload_document(self, content, filename, license_plate=None, external_ref=None):
        data = {}
        if license_plate:
            data["license_plate"] = license_plate
        if external_ref:
            data["external_ref"] = external_ref
        files = {"file": (filename or "notice.pdf", content, "application/pdf")}
        return self._request("POST", "/documents", data=data, files=files)
