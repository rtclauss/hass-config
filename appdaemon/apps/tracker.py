## Blend the data from the bayesian binary home/away sensor with device tracker
import appdaemon.plugins.hass.hassapi as hass
import copy
from datetime import datetime, timedelta, timezone


from geopy.distance import great_circle

class add_gps(hass.Hass):

  def initialize(self):
    self.device_id = self.args["bayesian_device_tracker_name"]
    self.bayesian = self.args["bayesian_input"]
    self.gps_sensors = self.args["gps_location_sources"]
    self.minimum_update_distance = self.args["minimum_update_distance"]
    self.minimum_update_window = self.args["minimum_update_window"]
    
    #self.log("preparing to system on init")
    self.bayes_updated(entity=self.bayesian, attribute={}, old={}, new={}, kwargs={})
    #self.log('done with init')
    
    #self.log("registering callback {} {}".format(self.location_update, self.gps_sensors))
    self.listen_state(self.bayes_updated, entity = self.bayesian)
    for tracker in self.gps_sensors:
      self.listen_state(self.location_update, entity = tracker, attribute="all")
    
  
  def bayes_updated(self, entity, attribute, old, new, kwargs):
    sensor_state = self.get_state(entity, attribute="all")
    if sensor_state['state'] == 'on':
      config = self.get_plugin_config()
      self.log("bayes says I am home")
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
    last_changed = self.convert_utc(bayesian_state.get("last_updated"))
    difference = datetime.now(timezone.utc) - last_changed
    if difference.total_seconds() > self.minimum_update_window:
      self.log("Binary Bayesian Sensor State last changed {} seconds ago.  Time for an update".format(difference.total_seconds()))
    else:
      return
    gps_sensors_state = self.get_state(entity, attribute="all")
    #self.log("here is the GPS state: {}".format(gps_sensors_state))
    #qbayes_location = self.get_state("device_tracker."+self.device_id, attribute="all")
    old_lat_long = (old["attributes"].get("latitude"), old["attributes"].get("longitude"))
    #self.log("old location is: {}".format(old_lat_long))
    new_lat_long = (new["attributes"].get("latitude"), new["attributes"].get("longitude"))
    #self.log("new location is: {}".format(new_lat_long))
    distance = great_circle(old_lat_long, new_lat_long).meters
    self.log("distance between updates is: {}".format(distance))
    if distance <= self.minimum_update_distance:
      self.log("Looks like sensor {} is pretty stationary. Not Updating.".format(entity))
      return
    self.run_update(bayesian_state=bayesian_state, sensor_state=gps_sensors_state)
    

  def run_update(self, bayesian_state, sensor_state):
    #self.log("in run_update")
    gps_attributes = sensor_state["attributes"]
    #self.log("sensor state: {}".format(sensor_state))
    #self.log("here is the gps attribute data: {}".format(gps_attributes))
    ###self.log("do we have everything: {}".format(gps_attributes.viewKeys() & {"latitude", "longitude"})
    
    if bayesian_state['state'] == "on":
      config = self.get_plugin_config()
      self.log("bayes says I am home")
      #self.log("My current position is {}(Lat), {}(Long)".format(config["latitude"], config["longitude"]))
      #self.log("here we go setting {} to home with GPS: Accuracy {}, Latitude: {}, Longitude: {}".format(self.device_id, 0, config["latitude"], config["longitude"]))
      self.call_service("device_tracker/see", dev_id=self.device_id, attributes={"course": 0.0, "speed": 0.0, "home_probability": bayesian_state["attributes"]["probability"]}, gps=[config["latitude"], config["longitude"]]) 
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
            #self.log("here we go setting {} to somewhere with GPS: Accuracy {}, Latitude: {}, Longitude: {}".format(self.device_id, gps_attributes["gps_accuracy"], gps_attributes["latitude"], gps_attributes["longitude"]))
            attributes = copy.deepcopy(gps_attributes)
            #self.log("{}".format(attributes['battery']))
            probability = bayesian_state["attributes"]["probability"]
            attributes['home_probability'] = probability
            
            ## iOS apps use m/s as the speed, not mph.  Need to convert.
            if 'speed' in attributes.keys() and 'wethop' in sensor_state['entity_id']:
              if attributes['speed'] == -1:
                attributes['speed'] = 0
              else:
                attributes['speed'] = attributes['speed'] / 0.44704
              self.log("new speed is: {}".format(attributes['speed']))
              
            # We can get false positives, like WetHop flashing home on a geofence exit.
            # Use the attributes of the bayesian sensor to determine if the transition is correct
            if probability <= bayesian_state["attributes"]["probability_threshold"] and sensor_state['state'] == "home":
              self.error("False positive jump to home zone.  Not updating Bayesian Sensor")
              self.error("Bayesian state: {}".format(bayesian_state))
              self.error("Sensor state: {}".format(sensor_state))
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
            self.error("KeyError {}: missing information from sensor. Returning with no action.".format(e))
            #self.call_service("device_tracker/see", dev_id=self.device_id, attributes={"home_probability": bayesian_state["attributes"]["probability"]})
      else:
        self.error("missing information from gps sensor. Returning with no action.")
        #self.call_service("device_tracker/see", dev_id=self.device_id, attributes={"home_probability": bayesian_state["attributes"]["probability"]})
        