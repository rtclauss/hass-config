## Blend the data from the bayesian binary home/away sensor with device tracker
import appdaemon.plugins.hass.hassapi as hass

class add_gps(hass.Hass):

  def initialize(self):
    self.device_id = "bayesian_zeke_home"
    self.bayesian = self.args["bayesian_input"]
    self.log("In init...")
    self.log(self.args)
    self.call_service("device_tracker/see", dev_id=self.device_id)
    self.log("calling get_state on {}".format(self.args["gps_location_sources"]))
    sensor = self.get_state(self.args["gps_location_sources"], attribute="all")
    self.log("got gps data {}".format(sensor))
    
    self.log("calling get_state on {}".format(self.args["bayesian_input"]))
    bayesian_state = self.get_state(self.args["bayesian_input"])
    self.log("got state data {}".format(bayesian_state))
    
    self.log("registering callback {} {}".format(self.location_update, self.args["gps_location_sources"]))
    self.listen_state(self.location_update, entity = self.args["gps_location_sources"])
    
  def location_update(self, entity, attribute, old, new, kwargs):
    self.log("in location_update")
    self.log("{} {} {} {} {}".format(entity, attribute, old, new, kwargs))
    
    # Get current state of bayesian input
    bayesian_state = self.get_state(self.bayesian, attribute="all")
    self.log("here is the current bayesian state: {}".format(bayesian_state))
    state = self.get_state(entity, attribute="all")
    self.log("here is the GPS state: {}".format(state))
    if bayesian_state['state'] == "on":
      config = self.get_hass_config()
      self.log("My current position is {}(Lat), {}(Long)".format(config["latitude"], config["longitude"]))
      self.log("here we go setting {} to home with GPS: Accuracy {}, Latitude: {}, Longitude: {}".format(self.device_id, state["attributes"]["gps_accuracy"], config["latitude"], config["longitude"]))
      self.call_service("device_tracker/see", dev_id=self.device_id, attributes={"home_probability": bayesian_state["attributes"]["probability"]}, gps_accuracy=state["attributes"]["gps_accuracy"], gps=[config["latitude"], config["longitude"]], battery = state["attributes"]["battery"]) 
    else:
      self.log("My current position is {}(Lat), {}(Long)".format(state["attributes"]["latitude"], state["attributes"]["longitude"]))
      self.log("here we go setting {} to away with GPS: Accuracy {}, Latitude: {}, Longitude: {}".format(self.device_id, state["attributes"]["gps_accuracy"], state["attributes"]["latitude"], state["attributes"]["longitude"]))
      self.call_service("device_tracker/see", dev_id=self.device_id, attributes={"home_probability": bayesian_state["attributes"]["probability"]}, gps_accuracy=state["attributes"]["gps_accuracy"], gps=[state["attributes"]["latitude"], state["attributes"]["longitude"]], battery = state["attributes"]["battery"]) 
    