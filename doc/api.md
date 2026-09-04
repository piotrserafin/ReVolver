Base URL: `https://api.volvocars.com/connected-vehicle/v2`

## Commands (POST /vehicles/{vin}/commands/{command})

All commands take an empty JSON body `{}` and return `{data: {vin, invokeStatus, message}}`.

| Endpoint              | Action                |
| --------------------- | --------------------- |
| `flash`               | Flash exterior lights |
| `honk`                | Honk horn             |
| `honk-flash`          | Honk and Flash        |
| `lock`                | Lock doors            |
| `lock-reduced-guard`  | Lock (reduced guard)  |
| `unlock`              | Unlock doors          |
| `climatization-start` | Start A/C / heater    |
| `climatization-stop`  | Stop A/C / heater     |
| `engine-start`        | Remote start engine   |
| `engine-stop`         | Remote stop engine    |

### Response Status Codes

| Code | Description                                            |
| ---- | ------------------------------------------------------ |
| 200  | Successful                                             |
| 400  | Bad Request — validation failed                        |
| 401  | Unauthorized — bad token or API key                    |
| 403  | Forbidden — missing scopes                             |
| 404  | Not Found                                              |
| 422  | Unprocessable — business rule failure (e.g., car busy) |
| 500  | Internal Server Error                                  |
| 503  | Service Unavailable                                    |
| 504  | Gateway Timeout                                        |

## Status (GET /vehicles/{vin}/{endpoint})

| Endpoint                | Data                               | Response Fields                                  |
| ----------------------- | ---------------------------------- | ------------------------------------------------ |
| `doors`                 | Lock state + each door open/closed | `centralLock.value`, `frontLeftDoor.value`, etc. |
| `windows`               | Each window open/closed            | `frontLeftWindow.value`, etc.                    |
| `fuel`                  | Fuel amount                        | `fuelAmount.value` (liters)                      |
| `state`¹                | EV battery + electric range         | `batteryChargeLevel.value` (%), `electricRange.value` (km/mi) |
| `capabilities`¹         | Which energy data points a VIN supports | `getEnergyState.isSupported` (bool)          |
| `odometer`              | Total distance                     | `odometer.value` (km)                            |
| `engine-status`         | Running or off                     | `engineStatus.value`                             |
| `diagnostics`           | Engine diagnostics                 | various                                          |
| `brakes`                | Brake fluid level                  | `brakeFluid.value`                               |
| `tyres`                 | Tyre pressure status               | per-tyre values                                  |
| `warnings`              | Active warnings                    | various                                          |
| `statistics`            | Trip stats                         | various                                          |
| `command-accessibility` | Which commands are available       | per-command availability                         |

### Common Response Format

All status fields follow the pattern:

```json
{
  "data": {
    "fieldName": {
      "value": "LOCKED",
      "unit": "string",
      "timestamp": "2024-01-15T10:30:00Z"
    }
  }
}
```

## Authentication Headers

```
Authorization: Bearer <access_token>
vcc-api-key: <application_api_key>
Content-Type: application/json
```

## Currently Used in ReVolver

**Commands:** flash, honk-flash, lock, unlock, climatization-start, climatization-stop

**Status:** doors (lock state), fuel (fuel level), state (EV battery, Energy API v2)

¹ `state` / `capabilities` live on the **Energy API v2** (`https://api.volvocars.com/energy/v2/vehicles/{vin}/...`), not the Connected Vehicle base URL. `state` requires `energy:state:read`; `capabilities` requires `energy:capability:read` (Energy API v1 / `recharge-status` was removed — returns 410 GONE). On first launch per VIN the app checks `capabilities.getEnergyState.isSupported` (cached in JS localStorage); only if supported does it call `/state`, then shows battery % under a "Battery" label as a fallback when `/fuel` has no `fuelAmount`. Range units follow the response `unit` (`km` or `mi`, market-dependent).
