import appdaemon.plugins.hass.hassapi as hass
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

    # Register callbacks for all sensors we were passed
    for sensor in self.args["sensors"].split(","):
      self.log(sensor)
      self.listen_state(self.motion, sensor)

  # On motion brighten the lights in 20 seconds 
  def motion(self, entity, attribute, old, new, kwargs):
    #TODO check if lamp is on.
    #TODO Reset lamp brightness to 1
    if self.now_is_between(self.args["start_window"], self.args["end_window"]) and new == 'on':
      if self.get_state(self.args["light"], attribute="brightness") == None:
        brightness = 1
        self.turn_on(self.args["light"], brightness = brightness)
      else:
        brightness = self.get_state(self.args["light"], attribute="brightness")
      
      # Don't do anything if we are already at max brightness
      #if  int(float(self.get_state(self.args["brightness_slider"]))) == int(float(self.get_state(self.args["max_brightness_slider"]))):
      if int(float(brightness)) == 255:
        return

      self.run_in(self.brighten, delay = self.args["transition_time_sec"], entity_id = entity, last_increase = 0)

    else:
      return

  # Increase the local brightness if the sensor is still on
  def brighten(self, kwargs):
    # If the motion sensor is still on, increase the brightness
    if self.get_state(kwargs["entity_id"]) == 'on':
      current_brightness = int(float(self.get_state(self.args["light"], attribute="brightness")))
      max_brightness = 255
      # Increase the brightness by 3% of the difference between current and max to start, then double that every time up to max
      if kwargs["last_increase"] == 0:
        current_increase = (max_brightness - current_brightness) * 0.06
        new_brightness = current_brightness + current_increase
      else:
        current_increase = int(float(kwargs["last_increase"]) * 1.1)
        new_brightness = current_brightness + current_increase
      # Make sure we are not going above the max brightness
      if new_brightness > max_brightness:
        new_brightness = int(max_brightness)
      self.log("Increasing brightness from {} to {}".format(current_brightness, new_brightness))
      self.turn_on(self.args["light"], brightness = new_brightness)
      # Check again in 20 seconds
      self.run_in(self.brighten, delay = kwargs["delay"], entity_id = kwargs["entity_id"], last_increase = current_increase)