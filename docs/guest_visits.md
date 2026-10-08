# Guest visits while away (cat sitters, friends, family)

Tracking issue: #1088. Automations live in `packages/trips.yaml`; the alarm response is in `packages/alerts.yaml`.

## What visitors do

Send anyone this line ahead of time:

> While we're away the alarm is on. Come in through the garage with the keypad code, or tap the Tyson picture on the mantle with your phone.

Nothing to install. Optional: a small card by the mantle with the same line.

## How a visit becomes "expected"

Only while `input_boolean.trip` is on and `binary_sensor.bayesian_zeke_home` is off.

1. **Garage keypad or remote.** `trip_garage_credentialed_open_starts_visit` fires when `cover.garage_door` goes `opening` with no Home Assistant user/automation context, the ratgdo motor runs and the wall button was not pressed. Keypad, remote and car HomeLink look the same to the ratgdo, so any of them starts a visit.
2. **Tap the right picture.** Three NFC tags (one behind each mantle frame) hold a plain URL to an HA webhook. Tyson is the accept hook; the other two are decoys that strobe immediately. Accept only works when the alarm is pending/triggered or an entry was seen in the last 30 minutes, and the webhook ids live in `secrets.yaml` (never committed).

Both call `script.trip_guest_visit_start`, which unlocks the virtual `lock.front_door_lock` so the existing `trip_guest_door_unlock_open_house` flow disarms the alarm, turns camera motion off, docks the vacuums and turns the water on.

## When nobody is expected

Entry or motion while armed and away: push with a snapshot now, critical push at +10 minutes, and the entry/foyer/hall lights strobe at +15 minutes unless a visit starts or the alarm is disarmed. The strobe stops as soon as either happens.

## When a visit ends

`trip_guest_visit_expiry` relocks the virtual front door 2 hours after the last sign of a person (4 hour hard cap), which runs `trip_guest_door_lock_close_house` (re-arm, water off, motion detection on). `trip_guest_visit_early_end` can end it sooner: after 20 minutes into a visit, once the garage closes and the main level is motion-free for 10 minutes. `trip_stale_disarm_rearm` re-arms if the house sits disarmed for 30 minutes with no visit.

## One-time setup

1. Add three unguessable webhook ids to `secrets.yaml` on the Home Assistant host (the CI placeholders are in `travis_secrets.yaml`):
   `guest_tap_accept_webhook_id`, `guest_tap_decoy_a_webhook_id`, `guest_tap_decoy_b_webhook_id`.
   Generate each with `python3 -c "import secrets; print(secrets.token_urlsafe(32))"`.
2. Get the Nabu Casa hook URLs (Settings > Automations > the `trip_guest_nfc_picture_tap` webhook triggers > the cloud webhook toggle) or build `https://hooks.nabu.casa/<id>` from each cloud webhook. Use these, not `external_url`.
3. Write each URL to its own NTAG213 tag as a plain URL (NDEF) record with any NFC writer app. Do not use Home Assistant's tag feature; it needs the app.
4. Stick the tags behind the frames. Label nothing on the tags themselves.

## Verify on real phones before relying on it

- iPhone XS or newer reads tags in the background (a banner appears; tap it). Older iPhones and phones with NFC switched off cannot.
- Tapping a webhook GET shows a blank page. The confirmation is the foyer lights blinking twice.
- Keypad detection is inferred from the 2026-10-07 garage data (no context on `opening`); confirm with a real keypad open while trip mode is on and a trip-simulated away state.
