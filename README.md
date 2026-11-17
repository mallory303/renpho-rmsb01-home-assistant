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
2. HA validates either the R-MSB01 manufacturer/model data or the verified connectable **Renpho-Scale + FFE0** advertisement, then opens one bounded GATT session.
3. The integration performs the VA handshake. In **Auto** mode it does not select a visitor; the scale uses its native stored-user weight identification and returns a slot number. A named manual profile instead selects **visitor 254**.
4. A complete TN measurement updates the latest-measurement sensors. Auto measurements assigned to an explicitly enrolled slot also update only that person's sensors.
5. HA disconnects after completion. Failed or interrupted sessions retain the previous completed values.

Repeated advertisements are suppressed after a successful measurement for 45 seconds. Failed attempts may retry after 5 seconds. Sessions time out after 75 seconds.

## Sensors

Each measurement provides:

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

The original 14 sensors remain compatible and always represent the **latest completed measurement**, including an unassigned one. Every HA profile also has its own set of 14 sensors and Recorder history. Per-person sensors restore their last values after an HA restart; shared latest-measurement sensors populate on the next measurement after a restart.

## Measurement users and enrollment

Open **Settings → Devices & services → Renpho R-MSB01 Scale → Configure** to add, edit, delete, and select named HA profiles. Each profile has its own age, height, and gender.

### Automatic family-member identification

1. Create one HA profile for each family member.
2. Keep the Renpho app and other BLE clients disconnected, and wake the scale beside the HA host.
3. Choose **Enroll / sync scale profile**, select one person, and confirm. Repeat for each family member.
4. The enrollment operation reads slots 1–8 first. It then reuses a verified mapping, synchronizes an existing enrolled profile, or asks the scale to allocate a free slot. It never deletes or intentionally overwrites a stored scale user.
5. After successful enrollment, the measurement selector is set to **Auto**. Family members can then use the scale without interacting with Home Assistant.

Enrollment is the **only** operation that writes a stored user. Adding, renaming, selecting, or deleting an HA profile does not delete or modify a stored scale user. Editing an enrolled person's age, height, or gender marks the profile as needing synchronization; run **Enroll / sync scale profile** again before relying on its body-composition values.

The integration maps only the returned scale slot to an explicitly enrolled HA profile. It does not guess identities from weight. An unassigned or unknown slot updates the shared latest-measurement sensors but **no person's history**, and fires `renpho_rmsb01_unassigned_measurement` with the entry ID and slot number. Native weight identification is performed by the scale, so its handling of similar-weight or ambiguous users remains a hardware limitation.

For manual operation, select a named profile instead of **Auto**. The next measurement uses visitor 254 and updates that HA profile's sensors; stored scale users are not modified. Existing single-profile installations migrate automatically and retain manual behavior until **Auto** is explicitly selected.

## Renpho Scale card

The integration includes a dashboard card with a **visual editor**. Open a dashboard, choose **Add card → Renpho Scale**, then:

1. Select the scale's shared weight sensor.
2. Use **Measurement mode** to choose **Auto** or a forced visitor profile.
3. Use **View measurement history for** to choose whose per-person values appear. This selector changes only the dashboard view and does not connect to the scale.
4. Open **Values to display** and select exactly which of the 14 measurements you want.
5. Optionally change the card title, set **History range (days)** (default **30**, range 1–365), or hide either selector, then save.

Select any value tile to open the full Home Assistant **History** page for that entity over the configured time range, defaulting to **30 days**. YAML `history_days` provides the same setting. The card uses the entity registry to resolve each person's actual entity IDs, including renamed entities, and falls back to the shared sensors when no per-person mapping exists. It distinguishes waiting for the scale, missing entities, and unassigned measurements. The card resource is copied to `/local/` and registered automatically, including a content hash for reliable updates and restarts.

### Progress arrows

Every numeric tile compares its value with the **previous completed measurement for that same person**. Shared tiles use the previous shared measurement instead. A small **green ▲/▼** marks movement in the configured beneficial direction, **red ▲/▼** marks the opposite, and a gray **→** means no change. Per-person arrows and their comparison baselines survive Home Assistant restarts; an unassigned Auto measurement never changes a person's baseline. When upgrading an installation that has no saved baseline, each per-person sensor recovers the preceding distinct measurement from its own recorder history, ignoring unavailable states and duplicate restart states. This makes existing measurements show their arrows immediately after the upgrade when recorder history is available. Without a recovered baseline, the first new measurement compares against the restored current value. The timestamp tile does not display a trend arrow.

The default display conventions are:

- **Lower is better:** weight, BMI, body fat, subcutaneous fat, visceral fat, and body age.
- **Higher is better:** body water, muscle percentage, muscle mass, bone mass, lean body mass, protein, and basal metabolic rate.

These are configurable display conventions, not a medical assessment. For example, increasing weight may be your goal. Override any metric with `trend_directions` in YAML; valid directions are `up` and `down`.

Equivalent YAML:

```yaml
type: custom:renpho-rmsb01-card
title: Renpho Scale
entity: sensor.renpho_r_msb01_weight
history_days: 30
show_user_selector: true
show_view_selector: true
metrics:
  - weight
  - bmi
  - body_fat
  - body_water
  - muscle_percentage
  - bone_mass
  - body_age
  - last_measurement
trend_directions:
  weight: up
  basal_metabolic_rate: down
```

The shared sibling entity IDs are derived from the weight sensor's prefix. `user_entity` and `view_entity` optionally override the two derived select entity IDs. Optional YAML `entities` overrides remain available for shared/fallback sensors:

```yaml
entities:
  body_fat: sensor.my_custom_fat_sensor
  bmi: sensor.my_custom_bmi_sensor
```

## Privacy

Measurements and named profiles stay local between the scale and Home Assistant. In manual mode the selected demographics are sent as visitor data; in Auto mode enrolled demographics and a generated slot key are stored by the scale. No cloud endpoint is used. This repository contains only integration code and synthetic test fixtures—not captured personal measurements or real scale identities.

## Troubleshooting

- Keep the Renpho app and other BLE clients disconnected during measurement or enrollment.
- Wake the scale near the HA host if discovery or enrollment does not appear.
- Check that HA's **Bluetooth** integration is configured and the adapter is powered.
- Manual setup accepts a Bluetooth address even while the scale is asleep.
- If enrollment reports a stale slot/key mapping or no free slot, it stops without registering, synchronizing, deleting, or overwriting a user.
- If Auto reports an unassigned measurement, enroll that user or select a manual profile; the integration will not infer their identity from weight.
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

The tests cover synthetic live/stored TN decoding, resistance transforms, manual and automatic GATT handshakes, stored-user reads, registration/sync rejection paths, explicit slot attribution, unknown-user isolation, enrollment safety, profile migration and selection, advertisement validation, disconnect handling, recorder-history baseline recovery, frontend resource registration, and card measurement/view selection.

## Scope

Validated specifically for R-MSB01(V6.0) VA/TN. Stored-history synchronization and other Renpho protocol families are not implemented. Body-composition values are produced by the scale firmware using its identified stored profile or the configured visitor profile. Research tooling only; not medical advice.
