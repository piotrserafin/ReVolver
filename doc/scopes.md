# Volvo OAuth Scopes

OAuth scopes requested by ReVolver during login. Configured in SSM under
`/revolver/scopes` (space-separated) and sent in the `authorize` request.

Endpoint paths are relative to their API base URL:

- Connected Vehicle: `https://api.volvocars.com/connected-vehicle/v2`
- Energy: `https://api.volvocars.com/energy/v2`

## Identity

| Scope    | Description                                                                | Endpoint      |
| -------- | -------------------------------------------------------------------------- | ------------- |
| `openid` | OpenID Connect — required to authenticate the user and receive an ID token | — (auth only) |

## Connected Vehicle API (`conve:*`)

| Scope                             | Description                                                                   | Endpoint                                                                     |
| --------------------------------- | ----------------------------------------------------------------------------- | ---------------------------------------------------------------------------- |
| `conve:battery_charge_level`      | Read battery charge level (legacy — worked only with removed Energy API v1)   | — (use `energy:state:read`)                                                  |
| `conve:brake_status`              | Read brake fluid level/status                                                 | `GET /vehicles/{vin}/brakes`                                                 |
| `conve:climatization_start_stop`  | Start/stop climatization (A/C / heater)                                       | `POST /vehicles/{vin}/commands/climatization-start` · `…/climatization-stop` |
| `conve:command_accessibility`     | Read whether commands are currently available (car online/driving)            | `GET /vehicles/{vin}/command-accessibility`                                  |
| `conve:commands`                  | List the commands supported by the vehicle                                    | `GET /vehicles/{vin}/commands`                                               |
| `conve:connectivity_status`       | Read vehicle connectivity status                                              | — (not exposed in v2 spec)                                                   |
| `conve:diagnostics_engine_status` | Read engine diagnostics data                                                  | `GET /vehicles/{vin}/engine`                                                 |
| `conve:diagnostics_workshop`      | Read workshop/service diagnostics (service warning, distance/time to service) | `GET /vehicles/{vin}/diagnostics`                                            |
| `conve:doors_status`              | Read door open/closed status                                                  | `GET /vehicles/{vin}/doors`                                                  |
| `conve:engine_start_stop`         | Remote engine start/stop                                                      | `POST /vehicles/{vin}/commands/engine-start` · `…/engine-stop`               |
| `conve:engine_status`             | Read engine running status                                                    | `GET /vehicles/{vin}/engine-status`                                          |
| `conve:environment`               | Read external environment data (e.g., external temperature)                   | — (not exposed in v2 spec)                                                   |
| `conve:fuel_status`               | Read fuel amount/level                                                        | `GET /vehicles/{vin}/fuel`                                                   |
| `conve:honk_flash`                | Honk the horn and/or flash the lights                                         | `POST /vehicles/{vin}/commands/honk` · `…/flash` · `…/honk-flash`            |
| `conve:lock`                      | Lock the vehicle                                                              | `POST /vehicles/{vin}/commands/lock` · `…/lock-reduced-guard`                |
| `conve:lock_status`               | Read central lock status                                                      | `GET /vehicles/{vin}/doors`                                                  |
| `conve:navigation`                | Send destinations to the vehicle navigation                                   | — (separate Navigation API)                                                  |
| `conve:odometer_status`           | Read odometer (total distance)                                                | `GET /vehicles/{vin}/odometer`                                               |
| `conve:trip_statistics`           | Read trip statistics (incl. distance-to-empty)                                | `GET /vehicles/{vin}/statistics`                                             |
| `conve:tyre_status`               | Read tyre pressure status                                                     | `GET /vehicles/{vin}/tyres`                                                  |
| `conve:unlock`                    | Unlock the vehicle                                                            | `POST /vehicles/{vin}/commands/unlock`                                       |
| `conve:vehicle_relation`          | Read the user→vehicle relation (list of VINs the account owns)                | `GET /vehicles` · `GET /vehicles/{vin}`                                      |
| `conve:warnings`                  | Read active vehicle warnings                                                  | `GET /vehicles/{vin}/warnings`                                               |
| `conve:windows_status`            | Read window (and sunroof) open/closed status                                  | `GET /vehicles/{vin}/windows`                                                |

## Energy API v2 (`energy:*`)

Used for EV/PHEV battery state (battery charge level, electric range). The
Connected Vehicle API has no battery endpoint; the Energy API v2 provides it.
Note: the legacy `conve:battery_charge_level` scope only worked with the removed
Energy API v1 (`recharge-status`, now 410 GONE) — v2 requires the `energy:*` scopes below.

| Scope                    | Description                                                           | Endpoint                           |
| ------------------------ | --------------------------------------------------------------------- | ---------------------------------- |
| `energy:state:read`      | Read latest energy state (battery %, electric range, charging status) | `GET /vehicles/{vin}/state`        |
| `energy:capability:read` | Read which energy data points a vehicle supports                      | `GET /vehicles/{vin}/capabilities` |

## Location

| Scope           | Description                                               | Endpoint                                   |
| --------------- | --------------------------------------------------------- | ------------------------------------------ |
| `location:read` | Read the vehicle's last known GPS location (Location API) | `GET /location/v1/vehicles/{vin}/location` |
