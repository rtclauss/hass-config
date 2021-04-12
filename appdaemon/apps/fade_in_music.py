import hassapi as hass
from random import randint
import datetime

# TODO update to recognise motion across all sliders
class FadeInMusic(hass.Hass):
  am_i_already_fading_in_spotify = "off"

  def initialize(self):
    # Define a handle to be used for all timers
    self.handle = None
    self.transition = self.args['transition_time_sec']
    self.already_fading_in_spotify = self.args["already_fading_in_spotify"]

    # Register callbacks for all sensors we were passed
    for sensor in self.args["sensors"]:
      self.log(sensor)
      self.listen_state(self.motion, sensor)

  # On motion brighten the lights in 20 seconds 
  def motion(self, entity, attribute, old, new, kwargs):
    # Debug
    #self.log(', '.join(['{}={!r}'.format(k, v) for k, v in kwargs.items()]))
    #self.log("Detected Motion in {}".format(self.args["sensors"]))
    #workday = self.get_state("binary_sensor.workday_sensor")
    #self.log("is it a work day? {}".format(workday))
    
    if new == 'on': # and workday == 'on':
      # Play wake up music
      FadeInMusic.am_i_already_fading_in_spotify  = self.get_state(self.already_fading_in_spotify)
      if not FadeInMusic.am_i_already_fading_in_spotify == 'on': 
        self.log("already fading in spotify is {}".format(FadeInMusic.am_i_already_fading_in_spotify))
        self.turn_on(self.already_fading_in_spotify)
        self.turn_on("script.spotify_wake_up")
        self.call_service("media_player/media_stop", entity_id="media_player.bedroom")
        self.call_service("media_player/media_stop", entity_id="media_player.office")
        step = 0.01
        current_volume = 0.01
        i = 1
        while (current_volume <= 0.3):
          current_volume = current_volume + step
          self.run_in(self.increase_volume, i*6, new_volume = current_volume)
          i += 1

  def increase_volume(self, kwargs):
    new_volume = kwargs['new_volume']
    self.log("new wake up volume is {}".format(new_volume))
    self.call_service("media_player/volume_set", entity_id="media_player.spotify", volume_level=new_volume)
      
