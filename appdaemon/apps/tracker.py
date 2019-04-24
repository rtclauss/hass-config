## Blend the data from the bayesian binary home/away sensor with device tracker
import appdaemon.plugins.hass.hassapi as hass
import copy

class add_gps(hass.Hass):

  def initialize(self):
    self.device_id = "bayesian_zeke_home"
    self.bayesian = self.args["bayesian_input"]
    self.gps_sensors = self.args["gps_location_sources"]
    
    #self.log("registering callback {} {}".format(self.location_update, self.gps_sensors))
    self.listen_state(self.bayes_updated, entity = self.bayesian)
    for tracker in self.gps_sensors:
      self.listen_state(self.location_update, entity = tracker)

  
  def bayes_updated(self, entity, attribute, old, new, kwargs):
    sensor_state = self.get_state(entity, attribute="all")
    if sensor_state['state'] == 'home':
      config = self.get_plugin_config()
      #self.log("bayes says I am home")
      #self.log("My current position is {}(Lat), {}(Long)".format(config["latitude"], config["longitude"]))
      #self.log("here we go setting {} to home with GPS: Accuracy {}, Latitude: {}, Longitude: {}".format(self.device_id, 0, config["latitude"], config["longitude"]))
      self.call_service("device_tracker/see", dev_id=self.device_id, attributes={"course": 0.0, "home_probability": sensor_state["attributes"]["probability"]}, gps=[config["latitude"], config["longitude"]]) 
    else:
      return
  
  # def setup_location(self, tracker):
  #   #self.log("in setup_location")
  #   #self.log("calling get_state on {}".format(tracker))
  #   sensor_state = self.get_state(tracker, attribute="all")
  #   #self.log("got gps data {}".format(sensor_state))
  #   #self.log("calling get_state on {}".format(self.bayesian))
  #   bayesian_state = self.get_state(self.bayesian, attribute="all")
  #   #self.log("got state data {}".format(bayesian_state, ))
  #   self.run_update(bayesian_state=bayesian_state, sensor_state=sensor_state)


  def location_update(self, entity, attribute, old, new, kwargs):
    #self.log("in location_update")
    #self.log("triggered by: {} {} {} {} {}".format(entity, attribute, old, new, kwargs))
    bayesian_state = self.get_state(self.bayesian, attribute="all")
    #self.log("here is the current bayesian state: {}".format(bayesian_state))
    gps_sensors_state = self.get_state(entity, attribute="all")
    #self.log("here is the GPS state: {}".format(gps_sensors_state))
    self.run_update(bayesian_state=bayesian_state, sensor_state=gps_sensors_state)
    

  def run_update(self, bayesian_state, sensor_state):
    #self.log("in run_update")
    gps_attributes = sensor_state["attributes"]
    #self.log("sensor state: {}".format(sensor_state))
    #self.log("here is the gps attribute data: {}".format(gps_attributes))
    ###self.log("do we have everything: {}".format(gps_attributes.viewKeys() & {"latitude", "longitude"})
    
    if bayesian_state['state'] == "on":
      config = self.get_plugin_config()
      #self.log("bayes says I am home")
      #self.log("My current position is {}(Lat), {}(Long)".format(config["latitude"], config["longitude"]))
      #self.log("here we go setting {} to home with GPS: Accuracy {}, Latitude: {}, Longitude: {}".format(self.device_id, 0, config["latitude"], config["longitude"]))
      self.call_service("device_tracker/see", dev_id=self.device_id, attributes={"course": 0.0, "home_probability": bayesian_state["attributes"]["probability"]}, gps=[config["latitude"], config["longitude"]]) 
    else:
      #self.log("bayes says I am away")
      if gps_attributes.keys() != {"latitude", "longitude", "gps_accuracy"}:
        #self.log("{} {} {}".format(gps_attributes.get("tracker"), gps_attributes.get("motion"), type(gps_attributes.get("motion"))))
        if gps_attributes.get("tracker") == "traccar" and gps_attributes.get("motion", False) == False:
          #self.log("Traccar not moving. Returning and using existing location data.")
          return
        else:
          try:
            #self.log("My current position is {}(Lat), {}(Long)".format(gps_attributes["latitude"], gps_attributes["longitude"]))
            self.log("here we go setting {} to somewhere with GPS: Accuracy {}, Latitude: {}, Longitude: {}".format(self.device_id, gps_attributes["gps_accuracy"], gps_attributes["latitude"], gps_attributes["longitude"]))
            attributes = copy.deepcopy(gps_attributes)
            #self.log("{}".format(attributes['battery']))
            probability = bayesian_state["attributes"]["probability"]
            attributes['home_probability'] = probability
            # We can get false positives, like WetHop flashing home on a geofence exit.
            # Use the attributes of the bayesian sensor to determine if the transition is correct
            if probability <= bayesian_state["attributes"]["probability_threshold"] and sensor_state['state'] == "home":
              self.error("False positive jump to home zone.  Not updating Bayesian Sensor")
              return
            
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
            attributes['course'] = gps_attributes.get('dirOfTravel', gps_attributes.get("course", -1))
            try:
              del attributes['dirOfTravel']
            except KeyError as ke:
              #self.error("KeyError deleting {}: missing information from gps sensor. continuing...".format(ke))
              pass
            
            attributes['timestamp'] = gps_attributes.get("timestamp", gps_attributes.get('last_changed',""))
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
            
            #self.log("{}".format(attributes))
            self.call_service("device_tracker/see", dev_id=self.device_id, 
            attributes = attributes, 
            gps_accuracy = gps_attributes["gps_accuracy"], 
            gps = [gps_attributes["latitude"], gps_attributes["longitude"]])
          except KeyError as e:
            self.error("KeyError {}: missing information from bayes sensor, defaulting back to bayesian state".format(e))
            self.call_service("device_tracker/see", dev_id=self.device_id, attributes={"home_probability": bayesian_state["attributes"]["probability"]})
      else:
        self.error("missing information from gps sensor, defaulting back to bayesian state")
        self.call_service("device_tracker/see", dev_id=self.device_id, attributes={"home_probability": bayesian_state["attributes"]["probability"]})
        