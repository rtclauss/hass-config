import appdaemon.plugins.hass.hassapi as hass
from random import randint
import datetime

# From https://github.com/mmmmmtasty/HomeAssistantConfig/blob/master/appdaemon-apps/brighten_lights.py

# If we are in night or morning mode, brighten the lights if someone continues to be in the area
#
# Takes the following parameters
# - sensors
# - brightness_slider
# - max_brightness_slider

# TODO update to recognise motion across all sliders
class BrightenLights(hass.Hass):

  def initialize(self):
    # Define a handle to be used for all timers
    self.handle = None
    self.transition = self.args['transition_time_sec']

    # Register callbacks for all sensors we were passed
    for sensor in self.args["sensors"].split(","):
      self.log(sensor)
      self.listen_state(self.motion, sensor)

  # On motion brighten the lights in 20 seconds 
  def motion(self, entity, attribute, old, new, kwargs):
    # Debug
    #self.log(', '.join(['{}={!r}'.format(k, v) for k, v in kwargs.items()]))
    #self.log("Detected Motion in {}".format(self.args["sensors"]))
    workday = self.get_state("binary_sensor.workday_sensor")
    #self.log("is it a work day? {}".format(workday))
    
    if new == 'on' and workday == 'on':
      if self.get_state(self.args["light"], attribute="brightness") == None:
        self.turn_on(self.args["light"], brightness_pct = 100, transition = self.transition)
