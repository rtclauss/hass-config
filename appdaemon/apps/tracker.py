## Blend the data from the bayesian binary home/away sensor with device tracker
import appdaemon.plugins.hass.hassapi as hass

class add_gps(hass.Hass):

  def initialize(self):
    self.device_id = "bayesian_zeke_home"
    self.bayesian = self.args["bayesian_input"]
    self.gps_sensor = self.args["gps_location_sources"]
    
    #self.log("In init...")
    #self.log(self.args)
    
    self.setup_location()
    
    #self.log("registering callback {} {}".format(self.location_update, self.gps_sensor))
    self.listen_state(self.location_update, entity = self.gps_sensor)
    self.listen_state(self.location_update, entity = self.bayesian)
    
    
  def setup_location(self):
    #self.log("in setup_location")
    #self.log("calling get_state on {}".format(self.gps_sensor))
    sensor_state = self.get_state(self.gps_sensor, attribute="all")
    #self.log("got gps data {}".format(sensor_state))
    
    #self.log("calling get_state on {}".format(self.bayesian))
    bayesian_state = self.get_state(self.bayesian, attribute="all")
    self.log("got state data {}".format(bayesian_state, ))
    self.run_update(bayesian_state=bayesian_state, sensor_state=sensor_state)
    
  def location_update(self, entity, attribute, old, new, kwargs):
    #self.log("in location_update")
    #self.log("triggered by: {} {} {} {} {}".format(entity, attribute, old, new, kwargs))
    bayesian_state = self.get_state(self.bayesian, attribute="all")
    #self.log("here is the current bayesian state: {}".format(bayesian_state))
    gps_sensor_state = self.get_state(self.gps_sensor, attribute="all")
    #self.log("here is the GPS state: {}".format(gps_sensor_state))
    self.run_update(bayesian_state=bayesian_state, sensor_state=gps_sensor_state)
    
    
  def run_update(self, bayesian_state, sensor_state):
    gps_attributes = sensor_state["attributes"]
    self.log("here is the gps attribute data: {}".format(gps_attributes))
    #self.log("do we have everything: {}".format(gps_attributes.viewKeys() & {"latitude", "longitude"})
    
    if bayesian_state['state'] == "on":
      config = self.get_hass_config()
      self.log("bayes says I am home")
      #self.log("My current position is {}(Lat), {}(Long)".format(config["latitude"], config["longitude"]))
      #self.log("here we go setting {} to home with GPS: Accuracy {}, Latitude: {}, Longitude: {}".format(self.device_id, 0, config["latitude"], config["longitude"]))
      self.call_service("device_tracker/see", dev_id=self.device_id, attributes={"home_probability": bayesian_state["attributes"]["probability"]}, gps=[config["latitude"], config["longitude"]], battery=gps_attributes.get("battery", 100)) 
    else:
      self.log("bayes says I am away")
      if gps_attributes.keys() != {"latitude", "longitude", "gps_accuracy", "battery"}:
        try:
          self.log("My current position is {}(Lat), {}(Long)".format(gps_attributes["latitude"], gps_attributes["longitude"]))
          self.log("here we go setting {} to away with GPS: Accuracy {}, Latitude: {}, Longitude: {}".format(self.device_id, gps_attributes["gps_accuracy"], gps_attributes["latitude"], gps_attributes["longitude"]))
          self.call_service("device_tracker/see", dev_id=self.device_id, 
          attributes = {"home_probability": bayesian_state["attributes"]["probability"],
            "course": gps_attributes["course"],
            #"floor":  gps_attributes["floor"],
            "source_type":  "gps",
            "speed":  gps_attributes["speed"],
            "timestamp": gps_attributes["timestamp"],
            "trigger": gps_attributes["trigger"],
            "vertical_accuracy": gps_attributes["vertical_accuracy"]
          }, 
          gps_accuracy = gps_attributes["gps_accuracy"], 
          gps = [gps_attributes["latitude"], gps_attributes["longitude"]], 
          battery = gps_attributes["battery"])
        except KeyError as e:
          self.log("KeyError: missing information from bayes sensor, defaulting back to bayesian state")
          self.call_service("device_tracker/see", dev_id=self.device_id, attributes={"home_probability": bayesian_state["attributes"]["probability"]})
      else:
        self.log("missing information from gps sensor, defaulting back to bayesian state")
        self.call_service("device_tracker/see", dev_id=self.device_id, attributes={"home_probability": bayesian_state["attributes"]["probability"]})