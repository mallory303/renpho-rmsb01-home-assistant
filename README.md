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

## Measurement users

Open **Settings → Devices & services → Renpho R-MSB01 Scale → Configure** to add, edit, delete, and select named HA-side profiles. Each profile has its own age, height, and gender. The selected profile is sent as **visitor 254** with the next measurement; stored scale users are never modified.

The native `select.renpho_r_msb01_user` entity and the card dropdown both select the **next-measurement user**. Changing users preserves the last completed measurement, and the weight entity/card identify the profile that produced it. Existing single-profile installations migrate automatically to **User 1**.

## Renpho Scale card

The integration includes a dashboard card with a **visual editor**. Open a dashboard, choose **Add card → Renpho Scale**, then:

1. Select the scale's weight sensor.
2. Use **User for next measurement** to choose a profile, or hide the selector in the editor.
3. Open **Values to display** and select exactly which of the 14 measurements you want.
4. Optionally change the card title and save.

Select any value tile to open its normal Home Assistant history/more-info dialog. The card shows **Waiting for scale** when entities exist but no measurement has arrived, and a separate error when entity IDs are missing. The card resource is copied to `/local/` and registered automatically, including a content hash for reliable updates and restarts.

Equivalent YAML:

```yaml
type: custom:renpho-rmsb01-card
title: Renpho Scale
entity: sensor.renpho_r_msb01_weight
show_user_selector: true
metrics:
  - weight
  - bmi
  - body_fat
  - body_water
  - muscle_percentage
  - bone_mass
  - body_age
  - last_measurement
```

The sibling entity IDs are derived from the weight sensor's prefix. `user_entity` optionally overrides the derived `select.renpho_r_msb01_user`. If you rename individual measurement entities, optional YAML `entities` overrides are available:

```yaml
entities:
  body_fat: sensor.my_custom_fat_sensor
  bmi: sensor.my_custom_bmi_sensor
```

## Privacy

Measurements and named profiles stay local between the scale and Home Assistant. The active profile is sent directly to the scale over BLE. No cloud endpoint is used. This repository contains only integration code and synthetic test fixtures—not captured personal measurements.

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
node --check custom_components/renpho_rmsb01/www/renpho-rmsb01-card.js
node --test tests/card.test.mjs
```

The tests cover synthetic live/stored TN decoding, resistance transforms, the complete GATT handshake, profile migration and selection, advertisement validation, disconnect handling, frontend resource registration, and card user/metric selection and connection status.

## Scope

Validated specifically for R-MSB01(V6.0) VA/TN. Stored-history synchronization and other Renpho protocol families are not implemented. Body-composition values are produced by the scale firmware using the configured visitor profile. Research tooling only; not medical advice.
