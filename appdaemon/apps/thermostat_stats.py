import datetime
import json

import hassapi as hass
import sqlalchemy
from sqlalchemy import Boolean, Column, DateTime, Float, Integer, String, Text
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()


class ThermostatChanges(Base):
    __tablename__ = "thermostat"

    id = Column(Integer, primary_key=True)
    changed_item = Column(String)
    old_temp = Column(Float)
    new_temp = Column(Float)

    old_target = Column(Float)
    new_target = Column(Float)
    target_temp_low = Column(Float)
    target_temp_high = Column(Float)

    new_state = Column(String)
    old_state = Column(String)
    hvac_mode = Column(String)
    fan_mode = Column(String)
    preset_mode = Column(String)
    equipment_running = Column(String)
    thermostat_current_humidity = Column(Float)
    thermostat_humidity_setpoint = Column(Float)
    humidifier_in_equipment_running = Column(Boolean)
    humidifier_state = Column(String)
    humidifier_on = Column(Boolean)
    humidifier_target = Column(Float)
    humidifier_current_humidity = Column(Float)
    humidifier_mode = Column(String)
    humidifier_action = Column(String)
    humidifier_min_humidity = Column(Float)
    humidifier_max_humidity = Column(Float)
    humidifier_available_modes_json = Column(Text)
    humidifier_attrs_json = Column(Text)

    house_average_humidity = Column(Float)
    house_average_temp = Column(Float)

    outside_temp = Column(Float)
    outside_temp_feels_like = Column(Float)
    outside_humidity = Column(Float)
    outside_cloud_cover = Column(Float)
    wind_speed = Column(Float)
    wind_gust = Column(Float)
    wind_bearing = Column(Float)

    occupancy_state = Column(String)
    occupancy_value = Column(Float)
    window_open_state = Column(String)
    window_open = Column(Boolean)

    sun_state = Column(String)
    sun_elevation = Column(Float)
    sun_azimuth = Column(Float)

    trigger_entity = Column(String)
    trigger_attribute = Column(String)
    trigger_old_state = Column(String)
    trigger_new_state = Column(String)
    context_id = Column(String)
    context_user_id = Column(String)
    context_parent_id = Column(String)
    thermostat_attrs_json = Column(Text)

    time = Column(DateTime)
    aux_heat_on = Column(Boolean)

    def __str__(self):
        return (
            "changed_item=%s old_temp=%s new_temp=%s old_target=%s new_target=%s "
            "old_state=%s new_state=%s hvac_mode=%s fan_mode=%s preset_mode=%s aux_heat_on=%s "
            "thermostat_current_humidity=%s thermostat_humidity_setpoint=%s "
            "humidifier_in_equipment_running=%s humidifier_state=%s humidifier_on=%s humidifier_target=%s "
            "humidifier_current_humidity=%s humidifier_mode=%s humidifier_action=%s "
            "house_average_temp=%s house_average_humidity=%s outside_temp=%s feels_like=%s "
            "outside_humidity=%s outside_cloud_cover=%s wind_speed=%s wind_gust=%s wind_bearing=%s "
            "occupancy_state=%s occupancy_value=%s window_open_state=%s window_open=%s "
            "trigger_entity=%s trigger_attribute=%s trigger_old_state=%s trigger_new_state=%s"
            % (
                self.changed_item,
                self.old_temp,
                self.new_temp,
                self.old_target,
                self.new_target,
                self.old_state,
                self.new_state,
                self.hvac_mode,
                self.fan_mode,
                self.preset_mode,
                self.aux_heat_on,
                self.thermostat_current_humidity,
                self.thermostat_humidity_setpoint,
                self.humidifier_in_equipment_running,
                self.humidifier_state,
                self.humidifier_on,
                self.humidifier_target,
                self.humidifier_current_humidity,
                self.humidifier_mode,
                self.humidifier_action,
                self.house_average_temp,
                self.house_average_humidity,
                self.outside_temp,
                self.outside_temp_feels_like,
                self.outside_humidity,
                self.outside_cloud_cover,
                self.wind_speed,
                self.wind_gust,
                self.wind_bearing,
                self.occupancy_state,
                self.occupancy_value,
                self.window_open_state,
                self.window_open,
                self.trigger_entity,
                self.trigger_attribute,
                self.trigger_old_state,
                self.trigger_new_state,
            )
        )


class ThermostatStats(hass.Hass):
    def initialize(self) -> None:
        self.house_average_temp_sensor = self.args["house_average_temp"]
        self.house_average_humidity_sensor = self.args["house_average_humidity"]
        self.thermostat_database = self.args["thermostat_db"]
        self.thermostat = self.args["thermostat"]
        self.sun = self.args["sun"]

        self.outside_temp_feels_like = self.args.get("outside_temp_feels_like")
        self.outside_temp_sensor = self.args["outside_temp"]
        self.outside_cloud_cover_sensor = self.args["outside_cloud_cover"]
        self.outside_humidity_sensor = self.args["outside_humidity"]
        self.occupancy_sensor = self.args.get("occupancy") or self.args.get("occupancy_sensor")
        self.window_open_sensor = self.args.get("window_open") or self.args.get("window_open_sensor")
        self.wind_speed_sensor = self.args.get("wind_speed") or self.args.get("wind_speed_sensor")
        self.wind_gust_sensor = self.args.get("wind_gust") or self.args.get("wind_gust_sensor")
        self.wind_bearing_sensor = self.args.get("wind_bearing") or self.args.get("wind_bearing_sensor")
        self.humidifier_sensor = self.args.get("humidifier") or self.args.get("humidifier_sensor")
        self.humidifier_target_sensor = self.args.get("humidifier_target") or self.args.get("humidifier_target_sensor")

        self.listen_state(self.state_changed, self.thermostat, attribute="all")
        self.listen_state(self.state_changed, self.house_average_temp_sensor, attribute="all")
        optional_entities = [
            self.occupancy_sensor,
            self.window_open_sensor,
            self.wind_speed_sensor,
            self.wind_gust_sensor,
            self.wind_bearing_sensor,
            self.humidifier_sensor,
            self.humidifier_target_sensor,
        ]
        for entity_id in optional_entities:
            if entity_id:
                self.listen_state(self.state_changed, entity_id, attribute="all")

        engine = sqlalchemy.create_engine(self.thermostat_database, echo=True)
        Base.metadata.create_all(engine)
        self._ensure_optional_columns(engine)

        from sqlalchemy.orm import sessionmaker

        Session = sessionmaker(bind=engine)
        self.session = Session()

    def _ensure_optional_columns(self, engine):
        # Keep existing DBs working by adding new model fields in-place.
        ddl = [
            "ALTER TABLE thermostat ADD COLUMN IF NOT EXISTS target_temp_low DOUBLE PRECISION",
            "ALTER TABLE thermostat ADD COLUMN IF NOT EXISTS target_temp_high DOUBLE PRECISION",
            "ALTER TABLE thermostat ADD COLUMN IF NOT EXISTS hvac_mode VARCHAR",
            "ALTER TABLE thermostat ADD COLUMN IF NOT EXISTS fan_mode VARCHAR",
            "ALTER TABLE thermostat ADD COLUMN IF NOT EXISTS preset_mode VARCHAR",
            "ALTER TABLE thermostat ADD COLUMN IF NOT EXISTS equipment_running VARCHAR",
            "ALTER TABLE thermostat ADD COLUMN IF NOT EXISTS thermostat_current_humidity DOUBLE PRECISION",
            "ALTER TABLE thermostat ADD COLUMN IF NOT EXISTS thermostat_humidity_setpoint DOUBLE PRECISION",
            "ALTER TABLE thermostat ADD COLUMN IF NOT EXISTS humidifier_in_equipment_running BOOLEAN",
            "ALTER TABLE thermostat ADD COLUMN IF NOT EXISTS humidifier_state VARCHAR",
            "ALTER TABLE thermostat ADD COLUMN IF NOT EXISTS humidifier_on BOOLEAN",
            "ALTER TABLE thermostat ADD COLUMN IF NOT EXISTS humidifier_target DOUBLE PRECISION",
            "ALTER TABLE thermostat ADD COLUMN IF NOT EXISTS humidifier_current_humidity DOUBLE PRECISION",
            "ALTER TABLE thermostat ADD COLUMN IF NOT EXISTS humidifier_mode VARCHAR",
            "ALTER TABLE thermostat ADD COLUMN IF NOT EXISTS humidifier_action VARCHAR",
            "ALTER TABLE thermostat ADD COLUMN IF NOT EXISTS humidifier_min_humidity DOUBLE PRECISION",
            "ALTER TABLE thermostat ADD COLUMN IF NOT EXISTS humidifier_max_humidity DOUBLE PRECISION",
            "ALTER TABLE thermostat ADD COLUMN IF NOT EXISTS humidifier_available_modes_json TEXT",
            "ALTER TABLE thermostat ADD COLUMN IF NOT EXISTS humidifier_attrs_json TEXT",
            "ALTER TABLE thermostat ADD COLUMN IF NOT EXISTS outside_temp_feels_like DOUBLE PRECISION",
            "ALTER TABLE thermostat ADD COLUMN IF NOT EXISTS wind_speed DOUBLE PRECISION",
            "ALTER TABLE thermostat ADD COLUMN IF NOT EXISTS wind_gust DOUBLE PRECISION",
            "ALTER TABLE thermostat ADD COLUMN IF NOT EXISTS wind_bearing DOUBLE PRECISION",
            "ALTER TABLE thermostat ADD COLUMN IF NOT EXISTS occupancy_state VARCHAR",
            "ALTER TABLE thermostat ADD COLUMN IF NOT EXISTS occupancy_value DOUBLE PRECISION",
            "ALTER TABLE thermostat ADD COLUMN IF NOT EXISTS window_open_state VARCHAR",
            "ALTER TABLE thermostat ADD COLUMN IF NOT EXISTS window_open BOOLEAN",
            "ALTER TABLE thermostat ADD COLUMN IF NOT EXISTS trigger_entity VARCHAR",
            "ALTER TABLE thermostat ADD COLUMN IF NOT EXISTS trigger_attribute VARCHAR",
            "ALTER TABLE thermostat ADD COLUMN IF NOT EXISTS trigger_old_state VARCHAR",
            "ALTER TABLE thermostat ADD COLUMN IF NOT EXISTS trigger_new_state VARCHAR",
            "ALTER TABLE thermostat ADD COLUMN IF NOT EXISTS context_id VARCHAR",
            "ALTER TABLE thermostat ADD COLUMN IF NOT EXISTS context_user_id VARCHAR",
            "ALTER TABLE thermostat ADD COLUMN IF NOT EXISTS context_parent_id VARCHAR",
            "ALTER TABLE thermostat ADD COLUMN IF NOT EXISTS thermostat_attrs_json TEXT",
        ]
        with engine.begin() as conn:
            for statement in ddl:
                conn.execute(sqlalchemy.text(statement))

    @staticmethod
    def _safe_float(value):
        if value in (None, "unknown", "unavailable", ""):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _safe_sensor_float(self, entity_id):
        if not entity_id:
            return None
        return self._safe_float(self.get_state(entity_id))

    def _safe_sensor_state(self, entity_id):
        if not entity_id:
            return None
        value = self.get_state(entity_id)
        if value in (None, "unknown", "unavailable", ""):
            return None
        return str(value)

    @staticmethod
    def _state_to_bool(value):
        if value is None:
            return None
        normalized = str(value).strip().lower()
        if normalized in ("on", "open", "true", "home", "occupied", "1"):
            return True
        if normalized in ("off", "closed", "false", "away", "not_home", "clear", "0"):
            return False
        return None

    def _state_to_numeric(self, value):
        boolean_value = self._state_to_bool(value)
        if boolean_value is not None:
            return 1.0 if boolean_value else 0.0
        return self._safe_float(value)

    @staticmethod
    def _safe_state_payload(payload):
        if isinstance(payload, dict) and "attributes" in payload:
            return payload
        return None

    def _safe_entity_payload(self, entity_id):
        if not entity_id:
            return None
        payload = self.get_state(entity_id, attribute="all")
        return self._safe_state_payload(payload)

    @staticmethod
    def _state_str(payload):
        if payload is None:
            return None
        return payload.get("state")

    def state_changed(self, entity, attribute, old, new, kwargs):
        old_payload = self._safe_state_payload(old)
        new_payload = self._safe_state_payload(new)

        # We only process complete payloads.
        if old_payload is None or new_payload is None:
            return

        thermostat_before = old_payload
        thermostat_after = new_payload
        if entity != self.thermostat:
            thermostat_after = self.get_state(self.thermostat, attribute="all")
            if thermostat_after is None or "attributes" not in thermostat_after:
                return
            thermostat_before = thermostat_after

        old_attr = thermostat_before.get("attributes", {})
        new_attr = thermostat_after.get("attributes", {})

        old_hvac_action = old_attr.get("hvac_action")
        new_hvac_action = new_attr.get("hvac_action")
        old_temp = self._safe_float(old_attr.get("current_temperature"))
        new_temp = self._safe_float(new_attr.get("current_temperature"))

        old_target_temp = self._safe_float(old_attr.get("temperature"))
        new_target_temp = self._safe_float(new_attr.get("temperature"))
        target_temp_low = self._safe_float(new_attr.get("target_temp_low"))
        target_temp_high = self._safe_float(new_attr.get("target_temp_high"))

        if entity == self.house_average_temp_sensor:
            changed_item = "avg_house_temp"
        elif entity == self.thermostat and old_hvac_action != new_hvac_action:
            changed_item = "hvac_action"
        elif entity == self.thermostat and old_target_temp != new_target_temp:
            changed_item = "target_temp"
        elif entity == self.thermostat and old_temp != new_temp:
            changed_item = "monitored_temp"
        elif entity == self.occupancy_sensor:
            changed_item = "occupancy"
        elif entity == self.window_open_sensor:
            changed_item = "window_open"
        elif entity in (self.wind_speed_sensor, self.wind_gust_sensor, self.wind_bearing_sensor):
            changed_item = "wind"
        elif entity in (self.humidifier_sensor, self.humidifier_target_sensor):
            changed_item = "humidifier"
        else:
            changed_item = "thermostat_attr"

        avg_house_temp = self._safe_sensor_float(self.house_average_temp_sensor)
        avg_house_humidity = self._safe_sensor_float(self.house_average_humidity_sensor)

        outside_temp = self._safe_sensor_float(self.outside_temp_sensor)
        outside_temp_feels_like = (
            self._safe_sensor_float(self.outside_temp_feels_like)
            if self.outside_temp_feels_like
            else None
        )
        outside_cloud_cover = self._safe_sensor_float(self.outside_cloud_cover_sensor)
        wind_speed = self._safe_sensor_float(self.wind_speed_sensor)
        wind_gust = self._safe_sensor_float(self.wind_gust_sensor)
        wind_bearing = self._safe_sensor_float(self.wind_bearing_sensor)
        occupancy_state = self._safe_sensor_state(self.occupancy_sensor)
        occupancy_value = self._state_to_numeric(occupancy_state)
        window_open_state = self._safe_sensor_state(self.window_open_sensor)
        window_open = self._state_to_bool(window_open_state)
        humidifier_payload = None
        if self.humidifier_sensor:
            if entity == self.humidifier_sensor and new_payload is not None:
                humidifier_payload = new_payload
            else:
                humidifier_payload = self._safe_entity_payload(self.humidifier_sensor)
        humidifier_attr = humidifier_payload.get("attributes", {}) if humidifier_payload else {}
        humidifier_state = (
            humidifier_payload.get("state")
            if humidifier_payload and humidifier_payload.get("state") not in (None, "unknown", "unavailable", "")
            else self._safe_sensor_state(self.humidifier_sensor)
        )
        humidifier_on = self._state_to_bool(humidifier_state)
        humidifier_target = self._safe_sensor_float(self.humidifier_target_sensor)
        humidifier_target_from_entity = self._safe_float(humidifier_attr.get("humidity"))
        if humidifier_target is None:
            humidifier_target = humidifier_target_from_entity
        humidifier_current_humidity = self._safe_float(humidifier_attr.get("current_humidity"))
        humidifier_mode = humidifier_attr.get("mode")
        humidifier_action = humidifier_attr.get("action")
        humidifier_min_humidity = self._safe_float(humidifier_attr.get("min_humidity"))
        humidifier_max_humidity = self._safe_float(humidifier_attr.get("max_humidity"))
        humidifier_available_modes = humidifier_attr.get("available_modes")
        humidifier_available_modes_json = (
            json.dumps(humidifier_available_modes, default=str)
            if humidifier_available_modes is not None
            else None
        )
        humidifier_attrs_json = (
            json.dumps(humidifier_attr, sort_keys=True, default=str) if humidifier_attr else None
        )
        outside_humidity = self._safe_sensor_float(self.outside_humidity_sensor)

        sun_azimuth = self._safe_float(self.get_state(self.sun, attribute="azimuth"))
        sun_elevation = self._safe_float(self.get_state(self.sun, attribute="elevation"))
        sun_state = self.get_state(self.sun)

        equipment_running = (new_attr.get("equipment_running") or "").lower()
        aux_heat_on = "aux" in equipment_running
        humidifier_in_equipment_running = "humidifier" in equipment_running
        thermostat_current_humidity = self._safe_float(new_attr.get("current_humidity"))
        thermostat_humidity_setpoint = self._safe_float(new_attr.get("humidity"))

        context = thermostat_after.get("context") or {}
        thermostat_attrs_json = json.dumps(new_attr, sort_keys=True, default=str)

        temp_info = ThermostatChanges(
            changed_item=changed_item,
            old_temp=old_temp,
            new_temp=new_temp,
            old_target=old_target_temp,
            new_target=new_target_temp,
            target_temp_low=target_temp_low,
            target_temp_high=target_temp_high,
            new_state=new_hvac_action,
            old_state=old_hvac_action,
            hvac_mode=new_attr.get("hvac_mode"),
            fan_mode=new_attr.get("fan_mode"),
            preset_mode=new_attr.get("preset_mode"),
            equipment_running=equipment_running or None,
            thermostat_current_humidity=thermostat_current_humidity,
            thermostat_humidity_setpoint=thermostat_humidity_setpoint,
            humidifier_in_equipment_running=humidifier_in_equipment_running,
            humidifier_state=humidifier_state,
            humidifier_on=humidifier_on,
            humidifier_target=humidifier_target,
            humidifier_current_humidity=humidifier_current_humidity,
            humidifier_mode=humidifier_mode,
            humidifier_action=humidifier_action,
            humidifier_min_humidity=humidifier_min_humidity,
            humidifier_max_humidity=humidifier_max_humidity,
            humidifier_available_modes_json=humidifier_available_modes_json,
            humidifier_attrs_json=humidifier_attrs_json,
            house_average_humidity=avg_house_humidity,
            house_average_temp=avg_house_temp,
            outside_temp=outside_temp,
            outside_temp_feels_like=outside_temp_feels_like,
            outside_humidity=outside_humidity,
            outside_cloud_cover=outside_cloud_cover,
            wind_speed=wind_speed,
            wind_gust=wind_gust,
            wind_bearing=wind_bearing,
            occupancy_state=occupancy_state,
            occupancy_value=occupancy_value,
            window_open_state=window_open_state,
            window_open=window_open,
            sun_state=sun_state,
            sun_azimuth=sun_azimuth,
            sun_elevation=sun_elevation,
            trigger_entity=entity,
            trigger_attribute=attribute,
            trigger_old_state=self._state_str(old_payload),
            trigger_new_state=self._state_str(new_payload),
            context_id=context.get("id"),
            context_user_id=context.get("user_id"),
            context_parent_id=context.get("parent_id"),
            thermostat_attrs_json=thermostat_attrs_json,
            time=datetime.datetime.utcnow(),
            aux_heat_on=aux_heat_on,
        )

        self.session.add(temp_info)
        self.session.commit()
