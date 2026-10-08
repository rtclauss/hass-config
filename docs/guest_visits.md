# Guest visits while away (cat sitters, friends, family)

Tracking issue: #1088. Automations live in `packages/trips.yaml`; the alarm response is in `packages/alerts.yaml`.

## What visitors do

Send anyone this line ahead of time:

> While we're away the alarm is on. Come in through the garage with the keypad code, or tap the Tyson picture on the mantle with your phone.

Nothing to install. Optional: a small card by the mantle with the same line.

## How a visit becomes "expected"

Only while `input_boolean.trip` is on and `binary_sensor.bayesian_zeke_home` is off.

1. **Garage keypad or remote.** `trip_garage_credentialed_open_starts_visit` fires when `cover.garage_door` goes `opening` with no Home Assistant user/automation context, the ratgdo motor runs and the wall button was not pressed. Keypad, remote and car HomeLink look the same to the ratgdo, so any of them starts a visit.
2. **Tap the right picture.** Three NFC tags (one behind each mantle frame) hold a plain URL to an HA webhook. Tyson is the accept hook; the other two are decoys that strobe immediately. Accept only works when the alarm is pending/triggered or an entry was seen in the last 30 minutes.

Both call `script.trip_guest_visit_start`, which unlocks the virtual `lock.front_door_lock` so the existing `trip_guest_door_unlock_open_house` flow disarms the alarm, turns camera motion off, docks the vacuums and turns the water on.

## When nobody is expected

Entry or motion while armed and away: push with a snapshot now, critical push at +10 minutes, and the entry/foyer/hall lights strobe at +15 minutes unless a visit starts or the alarm is disarmed. The strobe stops as soon as either happens.

## When a visit ends

`trip_guest_visit_expiry` relocks the virtual front door 2 hours after the last sign of a person (4 hour hard cap), which runs `trip_guest_door_lock_close_house` (re-arm, water off, motion detection on). `trip_guest_visit_early_end` can end it sooner: after 20 minutes into a visit, once the garage closes and the main level is motion-free for 10 minutes. `trip_stale_disarm_rearm` re-arms if the house sits disarmed for 30 minutes with no visit.

## Setup checklist

### A. What to buy

- **NFC stickers or tags, at least 3 (a pack of 10 is ~$10): NTAG215 or NTAG216.** Not NTAG213: a Nabu Casa hook URL is long (roughly 150+ characters) and NTAG213 only holds about 140 bytes, so it may not fit. NTAG215 (504 bytes) is plenty.
- If a picture frame has a metal frame or metal backing, buy the "on-metal" / ferrite-backed variant, or stick the tag on the glass side or mat instead. Bare tags stop working against metal.
- Optional: a small printed card for the mantle.

### B. Make three webhook ids and give them to Home Assistant

1. Generate three random ids (run three times):
   `python3 -c "import secrets; print(secrets.token_urlsafe(32))"`
2. On the Home Assistant host, add them to `secrets.yaml` (File editor add-on or SSH). Never commit them:
   ```yaml
   guest_tap_accept_webhook_id: <id 1>
   guest_tap_decoy_a_webhook_id: <id 2>
   guest_tap_decoy_b_webhook_id: <id 3>
   ```
   Write down which is which in your password manager (accept = the Tyson tag).
3. Deploy this branch the way you normally do, then **restart** Home Assistant (Developer tools > Restart) so the new package automations, scripts and webhooks register. Check Settings > System > Repairs and the log for errors.

### C. Expose each webhook through Nabu Casa

The three automation webhook triggers are `local_only: false` and accept GET, which is what a phone tapping a tag sends.

1. Settings > Home Assistant Cloud > **Webhooks**. The three ids should be listed (they appear once the automation has loaded). If the list is empty, reload automations or restart and check that the automation `trip_guest_nfc_picture_tap` loaded without errors.
2. Turn on the cloud webhook toggle for each one, then copy its URL. It looks like `https://hooks.nabu.casa/<long token>`.
3. Keep a note of which URL belongs to the accept hook and which to each decoy.
4. If you do not use Nabu Casa, the fallback is `https://<your external_url>/api/webhook/<id>`; only do that if that URL is already safely exposed.

### D. Write the URLs to the tags

1. Install a free NFC writer app on your phone (for example **NFC Tools** on iPhone or Android).
2. In the app: Write > Add a record > **URL / URI** > paste one hook URL > Write > hold the phone to a tag. Do this for all three, one URL per tag.
3. Label the tags with a tiny mark on the back (not the front) so you know which is the accept one before they are hidden.
4. Optional, permanent: use the app's "make read only" so a visitor cannot overwrite a tag. Do this only after testing.

### E. Place them

1. Stick one tag to the back of (or on the glass or mat of) each of three similar mantle pictures. NFC range is only a few centimetres, so the tag must sit right behind where a phone will be held. Put the accept tag behind the Tyson picture.
2. Keep all three at the same spot on their frames so the right one is not obvious.
3. Test each tag with an iPhone (XS or newer) and an Android phone, with the phone resting where a visitor would hold it, through the frame.

### F. Test it

1. **Reachability (no side effects):** with trip mode off, open the accept URL on a phone over cellular or guest Wi-Fi. The page is blank. In Home Assistant, open the `trip_guest_nfc_picture_tap` automation trace: it should show a webhook trigger that stopped at the trip condition. That proves the hook works from outside without disarming anything.
2. **Live run (needs real away + trip on):** set `input_boolean.trip` on while you are out, then check each case:
   - keypad open of the garage: alarm disarms, "Guest visit started" push, no strobe;
   - enter another way and tap the Tyson tag: alarm disarms, foyer lights blink twice;
   - tap a decoy: critical push and strobe, which stops when you disarm;
   - enter and do nothing: push now, critical push at 10 minutes, strobe at 15 minutes;
   - tap the Tyson tag with no entry in the last 30 minutes: nothing happens;
   - leave and wait: the visit ends 2 hours after the last activity and the house re-arms (or earlier via the garage-cycle shortcut after the first 20 minutes).
3. Check the automation traces for each branch.

## Known limits

- iPhone XS or newer reads tags in the background (a banner appears; tap it). Older iPhones and phones with NFC switched off cannot read them. Tapping a webhook GET shows a blank page; the confirmation is the foyer lights blinking twice.
- Keypad detection is inferred from the 2026-10-07 garage data (no context on `opening`); it must be confirmed with a real keypad open. A remote, car HomeLink or HomeKit open looks the same.
- An intruder gets up to 15 minutes before the strobe; the push with a snapshot and the critical push at 10 minutes are the safety net.
