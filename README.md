# Fleet Traffic Fines (Odoo)

[![Tests](https://github.com/coompanion/odoo-fleet-traffic-fines/actions/workflows/test.yml/badge.svg?branch=18.0)](https://github.com/coompanion/odoo-fleet-traffic-fines/actions/workflows/test.yml)

Odoo module that shows the traffic fine cases of a [vyto](https://vyto.ai) account on fleet vehicles and drivers,
creates activities for upcoming deadlines and sends new notices to vyto.

**Requires a vyto account (external service).** The module only mirrors cases; reading the notices, finding the driver,
answering the authority and billing happen in vyto.

## Features
- Menu *Fleet > Traffic Fines*: list with filters (open, deadline within 7 days, without vehicle), grouping by status, vehicle, driver
- Smart button on the vehicle ("Traffic fines open") and on the driver (contact)
- Vehicle match by license plate (spaces and dashes ignored, archived vehicles included)
- Driver from the vehicle's driver history on the day of the offense (only if exactly one driver)
- Hourly sync from vyto; a to-do activity for the vehicle's fleet manager for each new deadline (never twice)
- *Upload notice* on the vehicle and in the menu: sends a PDF to vyto with the vehicle's license plate

## Installation
1. Copy the folder `fleet_traffic_fines` into your addons path. No extra Python packages are needed.
2. Update the apps list and install *Fleet Traffic Fines*.

Odoo Online cannot install third-party modules; use Odoo.sh or an on-premise installation.

## Setup
1. In vyto: *Settings > Integrations > API keys > New key*, with the permissions "read cases" and "upload notices".
2. In Odoo: *Fleet > Configuration > Settings > Traffic Fines (vyto)*, paste the key, *Test connection*, save.
3. Optional: *Traffic Fines > Sync now* for the first sync; afterwards it runs every hour.

## Permissions
- Fleet users: read traffic fines
- Fleet managers: additionally upload notices and run the sync
- Settings (API key): administrators

## Branches
One branch per Odoo version: `17.0`, `18.0`, `19.0`.

## License
LGPL-3, see `LICENSE`.
