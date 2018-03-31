import appdaemon.plugins.hass.hassapi as hass

#
# Hellow World App
#
# Args:
#

class HelloWorld(hass.Hass):

  def initialize(self):
    self.log('Hello World!')
    self.log("hi")
