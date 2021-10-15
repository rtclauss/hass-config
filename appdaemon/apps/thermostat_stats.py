import hassapi as hass
import datetime
import sqlalchemy

from sqlalchemy import Column, Integer, String, Float, DateTime
from sqlalchemy.ext.declarative import declarative_base
Base = declarative_base()

class ThermostatChanges(Base):
    __tablename__ = 'thermostat'
    
    id = Column(Integer, primary_key=True)
    changed_item = Column(String)
    old_temp = Column(Float)
    new_temp = Column(Float)
    
    old_target = Column(Float)
    new_target = Column(Float)
    
    new_state = Column(String)
    old_state = Column(String)

    house_average_humidity = Column(Float)
    house_average_temp = Column(Float)

    outside_temp = Column(Float)
    outside_humidity = Column(Float)
    outside_cloud_cover = Column(Float)

    time = Column(DateTime)

    def __str__(self):
        return "changed item: %s, old temp: %s, new temp: %s, old_target: %s, new_target: %s, old_state: %s, new_state: %s, house_average_humidity: %s, house_average_temp: %s, outside_temp: %s, outside_humidity: %s, outside_cloud_cover: %s" % (self.changed_item, self.old_temp, self.new_temp, self.old_target, self.new_target, self.old_state, self.new_state, self.house_average_humidity, self.house_average_temp, self.outside_temp, self.outside_humidity, self.outside_cloud_cover)
        

class ThermostatStats(hass.Hass):
    def initialize(self) -> None:
        self.house_average_temp_sensor = self.args['house_average_temp']
        self.house_average_humidity_sensor = self.args['house_average_humidity']

        self.thermostat = self.args["thermostat"]
        
        self.outside_temp_feels_like = self.args['outside_temp_feels_like']
        self.outside_temp_sensor = self.args["outside_temp"]
        self.outside_cloud_cover_sensor = self.args["outside_cloud_cover"]
        self.outside_humidity_sensor = self.args["outside_humidity"]
        self.listen_state(self.state_changed, self.thermostat, attribute="all")
        self.listen_state(self.state_changed, self.house_average_temp_sensor, attribute="all")
        engine = sqlalchemy.create_engine("sqlite:////config/thermostat.db", echo = True)
        self.log(engine)
        Base.metadata.create_all(engine)
        from sqlalchemy.orm import sessionmaker
        Session = sessionmaker(bind = engine)
        self.session = Session()

    def state_changed(self, entity, attribute, old, new, kwargs):
        self.log("State for {} changed from {} to {}".format(entity, old, new))

        #self.log("Hvac action from {} to {}".format(old['attributes'].get("hvac_action"), new['attributes'].get("hvac_action")))
        if entity == "sensor.average_house_temp":
            ### Need to get the thermostat values
            self.log("Grabbing Thermostat state")
            old = self.get_state(self.thermostat, attribute="all")
            new = old

        self.log("All attributes for old are: {}".format(old['attributes']))
        

        old_hvac_action = old['attributes'].get("hvac_action")
        new_hvac_action = new['attributes'].get("hvac_action")

        old_temp = old['attributes'].get("current_temperature")
        new_temp = new['attributes'].get("current_temperature")

        old_target_temp = old['attributes'].get("temperature")
        new_target_temp = new['attributes'].get("temperature")
        
        if old_hvac_action == new_hvac_action:
            self.log("No change in hvac state, temperature change of {} to {}".format(old_temp, new_temp))
            changed_item="monitored_temp"
        elif old_hvac_action == 'idle':
            self.log("Turning on hvac to {} with target temp of {}".format(new_hvac_action, new_target_temp))
            changed_item="hvac_action"
        elif new_hvac_action == 'idle':
            self.log("Idling hvac from running in mode {} due to reaching temperature {}".format(old_hvac_action, new_target_temp))
            changed_item="hvac_action"
        
        ## These two always win, never see hvac_action in the database
        if new_target_temp == old_target_temp:
            if entity == "sensor.average_house_temp":
                self.log("house temperature changed")
                changed_item = "avg_house_temp"
            else:
                self.log("No change in target temp, temperature change of {} to {}".format(old_temp, new_temp))
                changed_item="monitored_temp"
        else:
            self.log("Target temp changed from {} to {}".format(old_target_temp, new_target_temp))
            changed_item="target_temp"

        # if new == old:
        #     return
        #new_away_mode = new['attributes']["away_mode"]
        #old_away_mode = old['attributes']['away_mode']

        avg_house_temp = float(self.get_state(self.house_average_temp_sensor))

        self.log("average house humdity is: {} of type {}".format(self.get_state(self.house_average_humidity_sensor), type(self.get_state(self.house_average_humidity_sensor))))
        
        ahh = self.get_state(self.house_average_humidity_sensor)
        if ahh == 'unknown':
            avg_house_humidity = -1
        else:
            avg_house_humidity = float(self.get_state(self.house_average_humidity_sensor))

        outside_temp = float(self.get_state(self.outside_temp_sensor))
        outside_cloud_cover = float(self.get_state(self.outside_cloud_cover_sensor))
        outside_humidity = float(self.get_state(self.outside_humidity_sensor))


        tempInfo = ThermostatChanges(changed_item=changed_item, old_temp = old_temp, new_temp = new_temp, old_target = old_target_temp, new_target = new_target_temp, new_state = new_hvac_action, old_state=old_hvac_action, time = datetime.datetime.now(), house_average_humidity=avg_house_humidity, house_average_temp=avg_house_temp, outside_temp=outside_temp, outside_humidity=outside_humidity, outside_cloud_cover=outside_cloud_cover)
        self.log("Writing to thermostat.db: {}".format(tempInfo))
        self.session.add(tempInfo)
        self.session.commit()
        self.log("DB Update Done")

