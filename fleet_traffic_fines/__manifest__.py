# Part of Fleet Traffic Fines. See LICENSE file for full copyright and licensing details.
{
    "name": "Fleet Traffic Fines",
    "version": "18.0.1.0.0",
    "summary": "See traffic fines per vehicle and driver, with deadlines, and send notices to vyto",
    "description": """
Traffic fines for your fleet, right where your vehicles are.

Shows the traffic fine cases of your vyto account on vehicles and drivers,
creates activities for upcoming deadlines and sends new notices to vyto.
Requires a vyto account (external service).
""",
    "category": "Human Resources/Fleet",
    "author": "vyto",
    "website": "https://vyto.ai",
    "license": "LGPL-3",
    "depends": ["fleet", "mail"],
    "data": [
        "security/fleet_traffic_fines_security.xml",
        "security/ir.model.access.csv",
        "data/ir_cron.xml",
        "wizard/fleet_traffic_fine_upload_views.xml",
        "views/fleet_traffic_fine_views.xml",
        "views/fleet_vehicle_views.xml",
        "views/res_partner_views.xml",
        "views/res_config_settings_views.xml",
        "views/fleet_traffic_fines_menus.xml",
    ],
    "images": ["static/description/cover.png"],
    "installable": True,
    "application": False,
}
