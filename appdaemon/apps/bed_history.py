import hassapi as hass
import os
import math

from datetime import datetime, timedelta

class bed_history(hass.Hass):

  def initialize(self):
    self.log("In init...")
    self.log(self.args)
    
    # self.load_cells = self.args["load_cells"]
    self.log("Loading for load cells "+ str(self.args["load_cells"]))
    # self.day_empty_handle = self.run_every(self.calculate_value, datetime.now()+timedelta(seconds=5), 33*60 )
    # runtime = datetime.time(datetime.now()+timedelta(seconds=15))
    # self.log("Will run once at "+str(runtime))
    # self.handle_onetime = self.run_once(self.calculate_value, runtime)
    self.handle_regular = self.run_every(self.calculate_value, "now+15", 15*60) # will run every 15 minutes (15 minutes * 60 seconds)
    # self.day_empty_handle = self.run_daily(self.calculate_value, "16:00:01")
    # Don't use. not sure where I"m at in bed # self.night_occupied_handle = self.run_daily(self.calculate_value, "03:00:01")
    
  def calculate_value(self, kwargs):
    for load_cell in self.args['load_cells']:
      # we don't have the full set of data yet, so use yesterday's value
      if datetime.now().hour < 16:
        start_time = (datetime.now()-timedelta(days=1)).replace(hour=13, minute=0, second=0)
        end_time = (datetime.now()-timedelta(days=1)).replace(hour=16, minute=0, second=0)
      else:
        start_time = datetime.now().replace(hour=13,minute=0,second=0)
        end_time = datetime.now().replace(hour=16, minute=0, second=0)
      self.log("Querying {} times from {} to {}".format(load_cell, start_time, end_time))
      data = self.get_history(entity_id=load_cell, start_time = start_time, end_time=end_time)
      number = 0
      total = 0.0
      # self.log(data)
      for entry in data[0]: # for some reason we get a list of size one of lists
        # self.log(type(entry['state']))
        # self.log(load_cell + " " + entry['state'])
        if entry['state'] != 'unavailable' and entry['state'] != 'unknown':
          number += 1
          total += float(entry['state'])

      average = total/number
      self.log(load_cell + " " + str(average))
      self.set_state(load_cell+"_average", state=math.trunc(average))
      # next lines forces a value
      # self.set_state("sensor.raw_bed_load_cell_1"+"_average", state=math.trunc(320000))
      # self.set_state("sensor.raw_bed_load_cell_2"+"_average", state=math.trunc(400000))
    