# Renpho R-MSB01 Scale for Home Assistant

Local Bluetooth integration for the **Renpho R-MSB01(V6.0)** scale. It receives weight and body-composition measurements directly from the scale—no Renpho app, account, or cloud connection.

## Requirements

- Home Assistant **2026.11.0 or newer**.
- A connectable Bluetooth adapter managed by Home Assistant, such as the Raspberry Pi's built-in adapter.
- A compatible R-MSB01 scale within Bluetooth range.

## Install with the Marketplace

1. Open **Marketplace → ⋮ → Custom repositories**.
2. Add `https://github.com/mallory303/renpho-rmsb01-home-assistant` with category **Integration**.
3. Install **Renpho R-MSB01 Scale**.
4. Fully restart Home Assistant.
5. Open **Settings → Devices & services → Add integration → Renpho R-MSB01 Scale**.
6. Enter the age, height, and gender to use for visitor measurements.

Manual installation also works: copy `custom_components/renpho_rmsb01` to `/config/custom_components/`, restart HA, and add the integration.

## How it works

1. A scale advertisement wakes the integration.
2. HA validates the R-MSB01 manufacturer/model data and opens one bounded GATT session.
3. The integration performs the VA handshake and selects **visitor 254** using the configured profile. Stored scale users are not modified.
4. A complete TN measurement updates all sensors together, then HA disconnects.
5. Failed or interrupted sessions retain the previous completed values.

Repeated advertisements are suppressed after a successful measurement for 45 seconds. Failed attempts may retry after 5 seconds. Sessions time out after 75 seconds.

## Sensors

- Weight
- BMI
- Body fat
- Subcutaneous fat
- Visceral fat
- Body water
- Muscle percentage and muscle mass
- Bone mass and lean body mass
- Protein
- Basal metabolic rate
- Body age
- Last-measurement timestamp

Once populated, values remain available while the scale sleeps. After an HA restart, they populate on the next new measurement; Recorder history is unaffected.

## Privacy

Measurements stay local between the scale and Home Assistant. The configured profile is sent directly to the scale over BLE. No cloud endpoint is used. This repository contains only integration code and synthetic test fixtures—not captured personal measurements.

## Troubleshooting

- Keep the Renpho app and other BLE clients disconnected during measurement.
- Wake the scale near the HA host if discovery does not appear.
- Check that HA's **Bluetooth** integration is configured and the adapter is powered.
- Manual setup accepts a Bluetooth address even while the scale is asleep.
- Enable debug logs for `custom_components.renpho_rmsb01` if sessions do not complete.

## Development

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-test.txt
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/ruff check custom_components tests
```

The tests cover synthetic live/stored TN decoding, resistance transforms, the complete GATT handshake, profile encoding, advertisement validation, and disconnect handling.

## Scope

Validated specifically for R-MSB01(V6.0) VA/TN. Stored-history synchronization and other Renpho protocol families are not implemented. Body-composition values are produced by the scale firmware using the configured visitor profile. Research tooling only; not medical advice.
