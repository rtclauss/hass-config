## Blend the data from the bayesian binary home/away sensor with device tracker
import appdaemon.plugins.hass.hassapi as hass

class add_gps(hass.Hass):

  def initialize(self):
    self.device_id = "bayesian_zeke_home"
    self.bayesian = self.args["bayesian_input"]
    self.gps_sensor = self.args["gps_location_sources"]
    
    self.log("In init...")
    self.log(self.args)
    
    self.setup_location()
    
    self.log("registering callback {} {}".format(self.location_update, self.args["gps_location_sources"]))
    self.listen_state(self.location_update, entity = self.args["gps_location_sources"])
    
    
  def setup_location(self):
    self.log("in setup_location")
    self.log("calling get_state on {}".format(self.gps_sensor))
    sensor_state = self.get_state(self.gps_sensor, attribute="all")
    self.log("got gps data {}".format(sensor_state))
    
    self.log("calling get_state on {}".format(self.bayesian))
    bayesian_state = self.get_state(self.bayesian, attribute="all")
    self.log("got state data {}".format(bayesian_state, ))
    self.run_update(bayesian_state=bayesian_state, sensor_state=sensor_state)
    
  def location_update(self, entity, attribute, old, new, kwargs):
    self.log("in location_update")
    self.log("{} {} {} {} {}".format(entity, attribute, old, new, kwargs))
    bayesian_state = self.get_state(self.bayesian, attribute="all")
    self.log("here is the current bayesian state: {}".format(bayesian_state))
    sensor_state = self.get_state(entity, attribute="all")
    self.log("here is the GPS state: {}".format(sensor_state))
    self.run_update(bayesian_state=bayesian_state, sensor_state=sensor_state)
    
    
  def run_update(self, bayesian_state, sensor_state):
    if bayesian_state['state'] == "on":
      config = self.get_hass_config()
      self.log("bayes says I am home")
      self.log("My current position is {}(Lat), {}(Long)".format(config["latitude"], config["longitude"]))
      gps_attributes = sensor_state["attributes"]
      self.log("here we go setting {} to home with GPS: Accuracy {}, Latitude: {}, Longitude: {}".format(self.device_id, 0, config["latitude"], config["longitude"]))
      self.call_service("device_tracker/see", dev_id=self.device_id, attributes={"home_probability": bayesian_state["attributes"]["probability"]}, gps=[config["latitude"], config["longitude"]], battery=gps_attributes.get("battery", 100)) 
    else:
      self.log("bayes says I am away")
      self.log("My current position is {}(Lat), {}(Long)".format(sensor_state["attributes"]["latitude"], sensor_state["attributes"]["longitude"]))
      self.log("here we go setting {} to away with GPS: Accuracy {}, Latitude: {}, Longitude: {}".format(self.device_id, sensor_state["attributes"]["gps_accuracy"], sensor_state["attributes"]["latitude"], sensor_state["attributes"]["longitude"]))
      self.call_service("device_tracker/see", dev_id=self.device_id, attributes={"home_probability": bayesian_state["attributes"]["probability"]}, gps_accuracy=sensor_state["attributes"]["gps_accuracy"], gps=[sensor_state["attributes"]["latitude"], sensor_state["attributes"]["longitude"]], battery = sensor_state["attributes"]["battery"]) 