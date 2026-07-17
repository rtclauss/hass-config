# Built-In Security Dashboard

Home Assistant's built-in Security dashboard is the primary automatic view for
alarm, lock, cover, camera, door/window, motion, and person entities. The
Activity sidebar is supplied by Logbook and shows the most recent 24 hours on
wide screens.

Official references:

- [Home Assistant 2026.5 release notes](https://www.home-assistant.io/blog/2026/05/06/release-20265/#activity-log-on-the-security-dashboard)
- [Built-in dashboard documentation](https://www.home-assistant.io/dashboards/dashboards/)
- [Recorder filtering](https://www.home-assistant.io/integrations/recorder/#configure-filter)

## Repository Contract

- Keep `logbook:` enabled in `configuration.yaml`; the Activity sidebar depends
  on it.
- Record the security state domains used by Activity: `alarm_control_panel`,
  `lock`, `cover`, `binary_sensor`, and `person`.
- Keep the `camera` domain excluded from Recorder. Camera tiles still appear on
  the Security dashboard, while door/window and camera-motion binary sensors
  provide the useful activity events without retaining camera state history.
- Give physical camera-motion binary sensors `device_class: motion`. A camera
  entity alone does not replace the motion event source.
- Assign devices to their real Home Assistant areas. Follow
  `docs/room_intent.yaml`; in particular, the legacy living-room camera belongs
  to `dining_room`.

Removing the camera exclusion would record all camera-domain entities,
including mail images, vacuum maps, printer feeds, and unavailable legacy
cameras. That adds churn and retained metadata without improving the door,
window, alarm, lock, cover, person, or camera-motion events already shown in
Activity.

## Runtime Audit — 2026-07-14

Verified against the live Home Assistant 2026.7.2 instance:

- `/security` rendered the Activity sidebar on a wide desktop viewport with
  same-day door activity.
- The dashboard grouped door/window, lock, cover, alarm, camera, and person
  entities across the configured floors and areas.
- Recorder history contained recent alarm, front-door, garage-door, and person
  states. Physical camera entities had no retained states, as configured.
- Front-door, office-window, guest-room-window, Tiki-camera-motion, and garage
  devices were assigned to Hallway, Office, Guest room, Tiki Room, and Garage.
- The legacy living-room camera device was moved through Home Assistant's
  device-registry API to Dining room, matching the room-intent mapping.
- `binary_sensor.tikiroomcam_motionsensor` lacked a device class. The package
  customization now classifies it as `motion`, matching the living-room camera
  sensor and making the entity eligible for security activity presentation
  after the updated config is deployed.

## Post-Deploy Check

After deploying this config, reload customizations or restart Home Assistant,
then open `/security` on a wide screen and confirm:

1. The Activity sidebar is visible and shows recent security events.
2. Tiki Room Camera Motion is classified as motion in Tiki Room.
3. Camera tiles remain visible even though camera state history remains empty.
4. Door/window, alarm, lock, cover, and person events continue to populate the
   24-hour activity list.
