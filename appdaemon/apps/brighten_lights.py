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
    self.am_i_home = self.args['am_i_home']

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
    guest_mode = self.get_state(self.args["guest_mode"])
    #self.log("is guest_mode on? {}".format(guest_mode))
    if self.now_is_between(self.args["start_window"], self.args["end_window"]) and new == 'on' and workday == 'on' and self.get_state(self.am_i_home) == 'on':
      if self.get_state(self.args["light"], attribute="brightness") == None:
        brightness = 1
        self.turn_on(self.args["light"], brightness = brightness)
        # Play wake up music if bedroom lights turn on.
        # Maybe I should wake up if a guest is up?  If so, uncomment the next if statement and fix indent
        if self.args["sensors"] == "binary_sensor.master_bedroom_motion": 
          self.turn_on("script.spotify_wake_up")
          step = 0.05
          current_volume = 0.05
          i = 1
          while (current_volume < 0.55):
            current_volume = current_volume + step
            self.run_in(self.increase_volume, i*randint(1, 10), new_volume = current_volume)
            i += 1
      else:
        brightness = self.get_state(self.args["light"], attribute="brightness")
      
      # Don't do anything if we are already at max brightness
      #if  int(float(self.get_state(self.args["brightness_slider"]))) == int(float(self.get_state(self.args["max_brightness_slider"]))):
      if int(float(brightness)) == 255:
        return

      self.run_in(self.brighten, seconds = self.args["transition_time_sec"], delay=self.args["transition_time_sec"], entity_id = entity, last_increase = 0)

    else:
      return

  # Increase the local brightness if the sensor is still on
  def brighten(self, kwargs):
    # Debug
    #self.log(', '.join(['{}={!r}'.format(k, v) for k, v in kwargs.items()]))

    # If the motion sensor is still on, increase the brightness
    if self.get_state(kwargs["entity_id"]) == 'on':
      if self.get_state(self.args["light"], attribute="brightness") == None:
        current_brightness = 1
        self.turn_on(self.args["light"], brightness = brightness)
      else:
        current_brightness = self.get_state(self.args["light"], attribute="brightness")
      max_brightness = 255
      # Increase the brightness by 3% of the difference between current and max to start, then double that every time up to max
      if kwargs["last_increase"] == 0:
        current_increase = (max_brightness - current_brightness) * 0.06
        if current_increase < 1:
          current_increase = 1
        new_brightness = current_brightness + current_increase
      else:
        current_increase = int(float(kwargs["last_increase"]) * 1.1)
        new_brightness = current_brightness + current_increase
      # Make sure we are not going above the max brightness
      at_max_brightness = False
      if new_brightness > max_brightness:
        new_brightness = int(max_brightness)
        at_max_brightness = True
      #self.log("Increasing brightness from {} to {}".format(current_brightness, new_brightness))
      self.turn_on(self.args["light"], brightness = new_brightness)
      # check if we're done.
      if at_max_brightness:
        #self.log("Done fading in {}".format(self.args["light"]))
        return
      # Check again in 20 seconds
      self.run_in(self.brighten, seconds = kwargs["delay"], delay = kwargs["delay"], entity_id = kwargs["entity_id"], last_increase = current_increase)
      
  def increase_volume(self, kwargs):
    new_volume = kwargs['new_volume']
    self.call_service("media_player/volume_set", entity_id="media_player.spotify", volume_level=new_volume)
      