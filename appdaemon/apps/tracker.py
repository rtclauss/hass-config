# Blend the data from the bayesian binary home/away sensor with device tracker
import hassapi as hass
import copy
from datetime import datetime, timedelta, timezone

from geopy.distance import great_circle

from pygeodesy import ellipsoidalNvector
# from pygeodesy import ellipsoidalVincenty
from pygeodesy import ellipsoidalKarney


class BayesianDeviceTracker(hass.Hass):
    def initialize(self):
        self.bayesian_device_tracker_id = self.args["bayesian_device_tracker_name"]
        self.bayesian = self.args["bayesian_input"]
        self.gps_sensor_sources = self.args["gps_location_sources"]
        self.minimum_update_distance = self.args["minimum_update_distance"]
        self.minimum_update_window = self.args["minimum_update_window"]
        self.gps_accuracy_tolerance = self.args["gps_accuracy_tolerance"]
        # Stable display name for the fused tracker. Without this, set_state would
        # inherit whatever friendly_name the last GPS source carried (e.g. the
        # Tesla's "Nigori Location tracker"), since set_state -- unlike the old
        # device_tracker.see -- applies attributes verbatim.
        self.tracker_friendly_name = self.args.get(
            "bayesian_device_tracker_friendly_name", "Zeke")
        # Per-source last accepted position {source_entity_id: (lat, lon)} for the
        # accumulated-distance gate in location_update.
        self._last_accepted_pos = {}

        self.log("preparing to system on init")
        self.bayes_updated(entity=self.bayesian, attribute={}, old={}, new={}, kwargs={})
        self.log('done with init')

        self.log("registering callback {} {}".format(self.location_update, self.gps_sensor_sources))
        self.log("registering callback for changes on bayesian sensor: {}".format(self.bayesian))
        self.listen_state(self.bayes_updated, entity_id=self.bayesian)
        for tracker in self.gps_sensor_sources:
            self.log("registering tracking callback for gps item {}".format(tracker))
            self.listen_state(self.location_update, entity_id=tracker, attribute="all")

    def bayes_updated(self, entity, attribute, old, new, kwargs):
        sensor_state = self.get_state(entity, attribute="all")
        if sensor_state['state'] == 'on':
            config = self.get_plugin_config()
            self.log("bayes_updated and bayes sensor says I am home")
            self.log("My current position is {}(Lat), {}(Long)".format(config["latitude"], config["longitude"]))
            self.log("here we go setting {} to home with GPS: Accuracy {}, Latitude: {}, Longitude: {}".format(self.bayesian_device_tracker_id, 0, config["latitude"], config["longitude"]))
            self.update_tracker(
                latitude=config["latitude"],
                longitude=config["longitude"],
                attributes={
                    "course": 0.0,
                    "home_probability": sensor_state["attributes"]["probability"],
                },
                # The bayesian sensor is the home/away authority; force "home"
                # rather than relying on zone resolution, which can silently
                # fail (e.g. get_state("zone") returning None) and leave the
                # tracker "not_home" while the sensor says we're home.
                state="home",
            )
        else:
            return

    def location_update(self, entity, attribute, old, new, kwargs):
        self.log("in location_update")
        self.log("triggered by: {} {} {} {} {}".format(entity, attribute, old, new, kwargs))
        bayesian_state = self.get_state(self.bayesian, attribute="all")
        self.log("here is the current bayesian tracker state: {}".format(bayesian_state))

        try:
            if new["attributes"].get("gps_accuracy") > self.gps_accuracy_tolerance:
                self.log("New GPS coordinates not accurate at {} m. Not updating.".format(new["attributes"].get("gps_accuracy")))
                return
        except TypeError as te:
            self.log("No new GPS Coordinates.  Continuing")

        qbayes_location = self.get_state(
            "device_tracker." + self.bayesian_device_tracker_id, attribute="all")
        try:
            last_changed = self.convert_utc(
                qbayes_location['attributes']['gps_updated'])  # get("last_updated"))
            difference = datetime.now(timezone.utc) - last_changed
            if difference.total_seconds() > self.minimum_update_window:
                pass
                self.log("Bayesian Device Tracker GPS Location last changed {} seconds ago.  Time for an update".format(difference.total_seconds()))
            else:
                self.log("Bayesian Device Tracker GPS Location last changed less than {} seconds ago.  Not Updating.".format(self.minimum_update_window))
                return
            fresh_restart = False
        except (KeyError, TypeError):
            # KeyError: entity exists but has no gps_updated attribute yet.
            # TypeError: entity does not exist yet (get_state returned None) --
            #   e.g. a cold start before the first set_state, now that the tracker
            #   is no longer persisted via the legacy device_tracker.see path.
            # Either way, treat it as a fresh restart and push a location update.
            fresh_restart = True
            self.log("Newly restarted HASS so there is no gps_updated attribute.  Updating location")
        gps_sensors_state = self.get_state(entity, attribute="all")
        self.log("here is the GPS state: {}".format(gps_sensors_state))

        #qbayes_location = self.get_state("device_tracker."+self.bayesian_device_tracker_id, attribute="all")
        
        try:
            new_lat = new["attributes"].get("latitude")
        except Exception as e:
            self.error(e)
            self.error("Could not get new latitude")

        try: 
            new_lon = new["attributes"].get("longitude")
        except Exception as e:
            self.error(e)
            self.error("Could not get new longitude")

        try:
            # new_lat_log = ellipsoidalNvector.LatLon(lat=new_lat, lon=new_lon)
            new_lat_log = ellipsoidalNvector.LatLon(new_lat, new_lon)
        except Exception as e:
            # Tesla does not have location data after being home for a while.
            self.error(e)
            self.error("Error calculating new vector with new coordinates. {}".format(new))
            return

        try:
            # old_lat_log = ellipsoidalNvector.LatLon(lat=old["attributes"].get(
            #     "latitude"), lon=old["attributes"].get("longitude"))
            old_lat_log = ellipsoidalNvector.LatLon(old["attributes"].get(
                "latitude"), old["attributes"].get("longitude"))
        except:
            # Home Assistant has restarted so we have no previous state for the device tracker. Let's use the new location state
            # for the old value.
            try:
                old_lat_log = new_lat_log
                self.log("Error getting old lat-long. Setting old value to new value")
                self.error("KeyError deleting {}: missing information from gps sensor. continuing...".format(ke))
                pass
            except:
                # Tesla does not have location data after being home for a while.
                self.error("Error with old coordinates. {}".format(new))
                return

        #mean_of_points = ellipsoidalNvector.meanOf(
        #    [old_lat_log, new_lat_log], LatLon=ellipsoidalVincenty.LatLon)
        #self.log("Mean of old and new location is {}".format(mean_of_points))
        
        # Accumulated-distance gate, measured PER SOURCE against that source's own
        # last accepted position -- not the source's immediately-previous report and
        # not the global fused position.
        #   * Per-source (vs the fused position): with phone + vehicle trackers at
        #     different places, the fused position reflects whichever source updated
        #     last, so a stationary source's refresh would read as movement and the
        #     published location / zone would ping-pong between the two.
        #   * Accumulated (vs the immediately-previous report): a source that reports
        #     more often than it travels `minimum_update_distance` (e.g. a phone while
        #     walking) would otherwise have every small delta discarded and never
        #     accumulate, leaving the tracker stale and missing zone crossings.
        baseline = self._last_accepted_pos.get(entity)
        if not fresh_restart:
            # Reference position for BOTH the distance gate and the zone check: this
            # source's own last accepted fix, or -- on first sighting after an
            # AppDaemon-only restart (fused entity retained, `_last_accepted_pos`
            # empty) -- the source's own previous report. Using the source's own
            # reference (never the global fused position/zone) is what keeps a
            # stationary source in a different zone from ping-ponging the fused
            # tracker, and keeps an unchanged first sighting from publishing.
            if baseline is not None:
                ref_lat, ref_lon = baseline
            else:
                old_attrs = (old or {}).get("attributes", {}) or {}
                ref_lat, ref_lon = old_attrs.get("latitude"), old_attrs.get("longitude")
                if ref_lat is None or ref_lon is None:
                    ref_lat, ref_lon = new_lat, new_lon
            reference = ellipsoidalNvector.LatLon(ref_lat, ref_lon)
            distance = new_lat_log.distanceTo(reference)
            self.log("Vincenty Distance from {}'s baseline is: {}".format(entity, distance))
            if distance <= self.minimum_update_distance:
                # Under the distance gate: suppress jitter UNLESS this source crossed a
                # zone boundary relative to its OWN reference (a small move can still
                # cross a boundary, e.g. 8 m inside -> 8 m outside = 16 m). Only when
                # away: the bayesian sensor pins state to "home" otherwise.
                zone_changed = False
                if bayesian_state and bayesian_state.get("state") != "on":
                    acc = (new.get("attributes") or {}).get("gps_accuracy", 0)
                    new_zone = self.resolve_tracker_state(new_lat, new_lon, acc)
                    base_zone = self.resolve_tracker_state(ref_lat, ref_lon, acc)
                    zone_changed = new_zone != base_zone
                    if zone_changed:
                        self.log("Zone change {} -> {} for {} within distance gate; publishing.".format(
                            base_zone, new_zone, entity))
                if not zone_changed:
                    # First sighting only (setdefault): anchor the baseline at the
                    # reference (the source's previous report), not `new`, so the
                    # already-measured segment still participates in accumulation.
                    self._last_accepted_pos.setdefault(entity, (ref_lat, ref_lon))
                    self.log("Looks like sensor {} is pretty stationary. Not Updating.".format(entity))
                    return
        # Accepted (movement past the threshold, or a genuine fresh restart): publish,
        # and advance this source's baseline ONLY if run_update actually published.
        # run_update can reject a report (e.g. the false-positive "home" guard); advancing
        # the baseline prematurely would make the corrective callback look stationary and
        # get skipped, leaving the fused tracker stale.
        published = self.run_update(bayesian_state=bayesian_state,
                                    sensor_state=gps_sensors_state)
        if published:
            self._last_accepted_pos[entity] = (new_lat, new_lon)

    def run_update(self, bayesian_state, sensor_state):
        self.log("in run_update")
        gps_attributes = sensor_state["attributes"]
        attributes = copy.deepcopy(gps_attributes)
        self.log("sensor state: {}".format(sensor_state))
        self.log("here is the gps attribute data: {}".format(gps_attributes))
        # self.log("do we have everything: {}".format(gps_attributes.viewKeys() & {"latitude", "longitude"})

        # iOS apps use m/s as the speed, not mph.  Need to convert.
        if 'speed' in attributes.keys() and 'wethop' in sensor_state['entity_id']:
            if attributes['speed'] == -1:
                self.log("ios says speed is -1, setting speed to 0")
                attributes['speed'] = 0.0
            else:
                # Convert to mph
                attributes['speed'] = (attributes['speed'] / 0.44704)
                self.log("setting speed from ios to: {}".format(attributes['speed']))
            self.log("new ios speed is: {}".format(attributes['speed']))
        # elif 'speed' in attributes.keys():
        #     #Traccar reports speed in knots
        #     attributes['speed'] = attributes['speed'] * 1.151
        #     self.log("traccar entity {} says new speed is: {}".format(
        #         sensor_state['entity_id'],
        #         attributes['speed']))
        elif 'speed' not in attributes.keys():
            attributes['speed'] = 0.0
            self.log("No 'speed' in attributes in update from sensor data: {}".format(sensor_state))


        if bayesian_state['state'] == "on":
            config = self.get_plugin_config()
            self.log("Bayesian sensor says I am home. Setting device_tracker to home")
            self.log("My current position is {}(Lat), {}(Long)".format(config["latitude"], config["longitude"]))
            self.log("here we go setting {} to home with GPS: Accuracy {}, Latitude: {}, Longitude: {}".format(self.bayesian_device_tracker_id, 0, config["latitude"], config["longitude"]))
            self.update_tracker(
                latitude=config["latitude"],
                longitude=config["longitude"],
                attributes={
                    "course": 0.0,
                    "speed": attributes['speed'],
                    "home_probability": bayesian_state["attributes"]["probability"],
                },
                state="home",
            )
            return True
        else:
            self.log("bayes says I am away")
            if gps_attributes.keys() != {"latitude", "longitude", "gps_accuracy"}:
                self.log("bayes away log: tracker {}, motion {}, type(motion) {}".format(gps_attributes.get("tracker"), gps_attributes.get("motion"), type(gps_attributes.get("motion"))))
                try:
                    self.log("My current position is {}(Lat), {}(Long)".format(gps_attributes["latitude"], gps_attributes["longitude"]))
                    self.log("here we go setting {} to somewhere with GPS: Accuracy {}, Latitude: {}, Longitude: {}".format(self.bayesian_device_tracker_id, gps_attributes["gps_accuracy"], gps_attributes["latitude"], gps_attributes["longitude"]))
                    attributes = copy.deepcopy(gps_attributes)
                    # self.log("{}".format(attributes['battery']))
                    probability = bayesian_state["attributes"]["probability"]
                    attributes['home_probability'] = probability

                    # We can get false positives, like WetHop flashing home on a geofence enter/exit.
                    # Use the attributes of the bayesian sensor to determine if the transition is correct
                    if probability <= bayesian_state["attributes"]["probability_threshold"] and sensor_state['state'] == "home":
                        #self.error(
                        #    "False positive jump to home zone.  Not updating Bayesian Sensor")
                        #self.error(
                        #    "Bayesian state: {}".format(bayesian_state))
                        #self.error("Sensor state: {}".format(sensor_state))
                        return False

                    try:
                        del attributes['battery']
                    except KeyError as ke:
                        #self.error("KeyError deleting {}: missing information from gps sensor. continuing...".format(ke))
                        pass

                    try:
                        del attributes['battery_level']
                    except KeyError as ke:
                        #self.error("KeyError deleting {}: missing information from gps sensor. continuing...".format(ke))
                        pass
                    # Different trackers give the direction of travel in different ways, need a way to get the value!
                    attributes['course'] = gps_attributes.get(
                        'dirOfTravel', gps_attributes.get("course", gps_attributes.get('bearing', gps_attributes.get('heading', -1))))
                    try:
                        del attributes['dirOfTravel']
                    except KeyError as ke:
                        #self.error("KeyError deleting {}: missing information from gps sensor. continuing...".format(ke))
                        pass
                    try:
                        del attributes['bearing']
                    except KeyError as ke:
                        #self.error("KeyError deleting {}: missing information from gps sensor. continuing...".format(ke))
                        pass

                    attributes['timestamp'] = gps_attributes.get(
                        "timestamp", gps_attributes.get('last_changed', ""))
                    try:
                        del attributes['last_changed']
                    except KeyError as ke:
                        #self.error("KeyError deleting {}: missing information from gps sensor. continuing...".format(ke))
                        pass
                    try:
                        del attributes['tracker']
                    except KeyError as ke:
                        #self.error("KeyError deleting {}: missing information from gps sensor. continuing...".format(ke))
                        pass

                    # To try and eliminate flashes backward in location from older/stale data, let's find the mean of the old location
                    # and the new sensor data and use that mean as the location.
                    dev_tracker_state = self.get_state(
                        "device_tracker." + self.bayesian_device_tracker_id, attribute="all")
                    # todo the old state may not have a latitude or longitude when hass restart
                    self.log("here is the previous device_tracker state: {}".format(dev_tracker_state))

                    # new_lat_log_p = ellipsoidalNvector.LatLon(lat=gps_attributes.get(
                    #     "latitude"), lon=gps_attributes.get("longitude"))
                    new_lat_log_p = ellipsoidalNvector.LatLon(gps_attributes.get(
                        "latitude"), gps_attributes.get("longitude"))
                    # NB: formatting a pygeodesy LatLon with str.format raises
                    # (_NotImplementedError in named.__format__), so log the raw coords.
                    self.log("new location is: {}, {}".format(
                        gps_attributes.get("latitude"), gps_attributes.get("longitude")))

                    try:
                        # old_lat_log_p = ellipsoidalNvector.LatLon(
                        #     lat=dev_tracker_state["attributes"]["latitude"], lon=dev_tracker_state["attributes"]["longitude"])
                        old_lat_log_p = ellipsoidalNvector.LatLon(
                            dev_tracker_state["attributes"]["latitude"], dev_tracker_state["attributes"]["longitude"])
                    except (KeyError, TypeError):
                        # No previous location for the tracker: either HA restarted
                        # (KeyError: state present, no latitude/longitude yet) or the
                        # entity does not exist at all (TypeError: get_state returned
                        # None, now possible since we no longer persist via
                        # device_tracker.see). Use the new location for the old value
                        # so update_tracker can (re)create the entity.
                        old_lat_log_p = new_lat_log_p

                    # LatLon objects are not str.format-safe (see note above).
                    # self.log("old location is: {}".format(old_lat_log_p))
                    
                    # Let's try the intermediate calculation and change the mean depending on the speed.
                    # The away branch re-copies gps_attributes above, discarding the
                    # speed=0.0 default set at the top of run_update. Sources without a
                    # 'speed' attribute (e.g. the iOS phone tracker) would otherwise
                    # raise KeyError here -- silently swallowed by the outer
                    # `except KeyError: pass`, so the away update never ran and the
                    # tracker stayed 'home' while actually away.
                    speed = attributes.get('speed', 0.0)
                    if old_lat_log_p.distanceTo(new_lat_log_p) > 402336: # 250 miles or 402 km. Useful when landing at a new destination
                        update_ratio = 1.0
                    else:
                        if speed is not None:
                            # Going from old-> new as below means we use larger fractions: 0.9, 0.95, etc
                            # if we go from new -> old, use smaller fractions: 0.1, 0.05, etc
                            if speed > 10:
                                update_ratio=0.9
                            else:
                                update_ratio=0.95
                        else:
                            update_ratio=0.95
                    mean_of_points = old_lat_log_p.intermediateTo(new_lat_log_p, update_ratio)
                    # LatLon is not str.format-safe; log its scalar coords instead.
                    self.log("Mean of location between old and new is {}, {}".format(
                        float(mean_of_points.lat), float(mean_of_points.lon)))


                    self.log("{}".format(attributes))
                    attributes['latitude'] = mean_of_points.lat
                    attributes['longitude'] = mean_of_points.lon

                    # Add source of update
                    attributes['source_tracker'] = sensor_state['entity_id']

                    # rtclauss add gps_update_time_attribute
                    attributes['gps_updated'] = datetime.now(timezone.utc).isoformat()
                    self.update_tracker(
                        # rtclauss 11/15/18 - use mean location
                        latitude=mean_of_points.lat,
                        longitude=mean_of_points.lon,
                        attributes=attributes,
                        gps_accuracy=gps_attributes["gps_accuracy"],
                    )
                    return True
                except KeyError as e:
                    pass
                    # self.error(
                    #     "KeyError {}: missing information from sensor {}. Returning with no action.".format(e, sensor_state['entity_id']))
            else:
                self.error("missing information from gps sensor. Returning with no action.")
        # No publish happened (false positive, missing data, or an error path).
        return False

    # Attributes a GPS source may carry that must never be copied onto the fused
    # tracker, because set_state applies them verbatim (unlike device_tracker.see).
    STRIP_ATTRS = (
        "friendly_name", "in_zones", "context", "entity_id", "state",
        "last_changed", "last_updated", "last_reported",
    )

    def update_tracker(self, latitude, longitude, attributes, gps_accuracy=0, state=None):
        """Update the Bayesian device tracker's state and attributes.

        Replaces the deprecated ``device_tracker.see`` service (removed in Home
        Assistant Core 2027.5) with a direct ``set_state`` call. Home Assistant's
        zone triggers evaluate the tracker's ``latitude``/``longitude`` attributes
        rather than the state string, so preserving accurate GPS attributes keeps
        the existing zone enter/leave automations working. Pass ``state`` to force
        a state string (the bayesian home path does this); otherwise it is
        resolved to ``home``/zone-name/``not_home`` here to mirror what
        ``device_tracker.see`` used to compute.
        """
        entity_id = "device_tracker." + self.bayesian_device_tracker_id
        merged = copy.deepcopy(attributes) if attributes else {}
        # Drop identity / HA-managed keys that a GPS source may carry, so the fused
        # tracker never impersonates its last source (friendly_name), advertises
        # stale zone membership (in_zones), or echoes state metadata.
        for key in self.STRIP_ATTRS:
            merged.pop(key, None)
        merged["latitude"] = latitude
        merged["longitude"] = longitude
        merged["gps_accuracy"] = gps_accuracy
        merged["source_type"] = "gps"
        merged["friendly_name"] = self.tracker_friendly_name
        # Always stamp gps_updated: location_update throttles on it, and replace=True
        # (below) would otherwise drop it on home-path writes that don't set it.
        merged.setdefault("gps_updated", datetime.now(timezone.utc).isoformat())
        if state is None:
            state = self.resolve_tracker_state(latitude, longitude, gps_accuracy)
        self.log("update_tracker: setting {} -> state={!r} lat={} lon={} acc={} attr_keys={}".format(
            entity_id, state, latitude, longitude, gps_accuracy, sorted(merged.keys())))
        # replace=True: AppDaemon's set_state merges attributes by default, so
        # stripping a key from `merged` does NOT remove it from an entity that
        # already carries it (stale in_zones/source_tracker/altitude persist
        # indefinitely). Replace the whole attribute mapping so the tracker only
        # ever exposes the keys set here.
        self.set_state(entity_id, state=state, attributes=merged, replace=True)
        self.log("update_tracker: readback state after set_state = {!r}".format(self.get_state(entity_id)))

    def resolve_tracker_state(self, latitude, longitude, gps_accuracy=0):
        """Map GPS coordinates to a device_tracker state string.

        Mirrors Home Assistant's ``async_active_zone`` / ``device_tracker.see``
        behavior: the smallest (then closest) active zone containing the point
        wins, the home zone maps to ``home``, any other zone maps to its friendly
        name, and no matching zone yields ``not_home``.
        """
        if latitude is None or longitude is None:
            self.log("resolve_tracker_state: None coordinates -> not_home")
            return "not_home"
        zones = self._zone_states()
        if not zones:
            self.log("resolve_tracker_state: no zones available -> not_home")
            return "not_home"

        best = None  # tuple of (radius, distance, entity_id, friendly_name)
        for entity_id, zone in zones.items():
            attrs = (zone or {}).get("attributes", {}) or {}
            if attrs.get("passive"):
                continue
            zone_lat = attrs.get("latitude")
            zone_lon = attrs.get("longitude")
            radius = attrs.get("radius")
            if zone_lat is None or zone_lon is None or radius is None:
                continue
            try:
                distance = great_circle((latitude, longitude), (zone_lat, zone_lon)).meters
            except Exception:  # pragma: no cover - defensive against bad coordinates
                continue
            # Same in-zone test HA uses: within radius, expanded by GPS accuracy.
            if distance - (gps_accuracy or 0) >= radius:
                continue
            candidate = (radius, distance, entity_id, attrs.get("friendly_name", entity_id))
            if best is None or candidate[:2] < best[:2]:
                best = candidate

        if best is None:
            self.log("resolve_tracker_state: point ({}, {}) acc={} matched no active zone -> not_home".format(
                latitude, longitude, gps_accuracy))
            return "not_home"
        self.log("resolve_tracker_state: best={} radius={} dist={:.1f} for point ({}, {})".format(
            best[2], best[0], best[1], latitude, longitude))
        if best[2] == "zone.home":
            return "home"
        return best[3]

    def _zone_states(self):
        """Return ``{zone_entity_id: full_state_dict}`` for all zones.

        NB: this AppDaemon does NOT support ``get_state("zone", attribute="all")``
        -- querying a specific attribute across a whole domain raises
        ``ValueError: Querying a specific attribute is only possible for a single
        entity``. (#940 hid this behind a broad ``except``, which made every
        resolution fall through to ``not_home``.) So enumerate the domain with a
        plain ``get_state("zone")`` and fetch each zone's attributes with a
        single-entity ``attribute="all"`` call.
        """
        try:
            ids = self.get_state("zone")  # {entity_id: state}
        except Exception as exc:
            self.log("_zone_states: get_state('zone') raised {}: {}".format(type(exc).__name__, exc))
            return {}
        if not isinstance(ids, dict) or not ids:
            self.log("_zone_states: get_state('zone') returned {!r}; no zones".format(ids))
            return {}

        result = {}
        for zid in ids:
            try:
                z = self.get_state(zid, attribute="all")
            except Exception:
                z = None
            if isinstance(z, dict):
                result[zid] = z
        self.log("_zone_states: {} zones via per-entity enumeration".format(len(result)))
        return result
