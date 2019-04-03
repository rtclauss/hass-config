import appdaemon.plugins.hass.hassapi as hass
import os

class restart_ha(hass.Hass):

  def initialize(self):
    self.log("In init...")
    self.log(self.args)
    
    self.host_to_ping = self.args["host_to_ping"]
    
    self.handle = self.run_every(self.ping_server, self.datetime(), 33*60 )
    
    
  def ping_server(self, kwargs):
    #self.log("in ping_server. pinging {}".format(self.host_to_ping))
    response = os.system("ping -c 2 -w 5 "+ self.host_to_ping +"> /dev/null 2>&1")
    
    if response == 0:
      pass
      #self.log("connected to internet")
    else:
      self.log("Cannot connect to internet. rebooting HA host")
      self.call_service("hassio/host_reboot")
    