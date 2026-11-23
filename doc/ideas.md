# Feature Ideas

Unplanned ideas, not yet committed to. When one is picked up, move it to [features.md](features.md) with a plan.

Endpoints refer to the specs in `doc/` (Connected Vehicle v2, Energy v2, Location v1). Not yet checked what our car actually returns for the new endpoints.

## Small

### App Glance status
The ReVolver entry in the watch launcher shows e.g. "Locked · 28L (240km)" without opening the app. The status is already persisted on the watch. Platforms with app glances only (not aplite).

### Car picker instead of typing the VIN
`GET /vehicles` lists the account's cars. Settings offer a picker instead of a VIN text field. Prepares for multiple cars.

### Odometer and trip stats
Second screen (DOWN): odometer (`/odometer`), average fuel consumption and trip meters (`/statistics`, already fetched for range).

### Data age
Show "updated 5 min ago" next to the status. Each Volvo value carries a `timestamp`.

## Medium

### Car health screen
Combine `/warnings` (bulbs), `/tyres` (pressure), `/brakes` (fluid) and `/diagnostics` (service due, washer fluid, oil). Show "All OK" or a list of problems; ⚠ marker on the main screen when something needs attention.

### Scheduled climate
Settings: e.g. "weekdays 7:00 → Climate On". The watch wakeup API launches ReVolver at that time and runs the action through the Quick Launch path (no Unlock). Risks: phone must be connected, phone OS may restrict background PebbleKit JS. Needs a test before committing.

### EV charging details
Energy API `/state` also has charger connection, charging status, time to full and target level. Only for EV / plug-in hybrid users.

### "Still unlocked" warning
When the app closes and the car shows Unlocked or an open window: vibrate and offer "Lock now?".

## Parked

### Find my car
Feature #5, PR #9. Phase 3: open navigation on the phone.
