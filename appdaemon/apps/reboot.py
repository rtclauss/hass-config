import hassapi as hass
import os

from datetime import datetime, timedelta

class restart_ha(hass.Hass):

  def initialize(self):
    self.log("In init...")
    self.log(self.args)
    
    self.host_to_ping = self.args["host_to_ping"]

    self.num_failures = 0
    
    self.handle = self.run_every(self.ping_server, datetime.now()+timedelta(seconds=15), 33*60 )
    
    
  def ping_server(self, kwargs):
    #self.log("in ping_server. pinging {}".format(self.host_to_ping))
    response = os.system("ping -c 5 -w 5 "+ self.host_to_ping +"> /dev/null 2>&1")
    
    if response == 0:
      if self.num_failures > 0:
        self.log("Can connect to internet. Reducing failures by one from: {} ".format(self.num_failures))
        self.num_failures = self.num_failures - 1
      pass
      #self.log("connected to internet")
    else:
      self.num_failures = self.num_failures + 1
      self.log("Cannot connect to internet. this is the {} time this has happened".format(self.num_failures))
      if self.num_failures >= 5:
        self.log("We have failed to connect {} times. Rebooting host.".format(self.num_failures))
        self.call_service("hassio/host_reboot")
    