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
    runtime = datetime.time(datetime.now()+timedelta(seconds=10))
    self.log("Will run once at "+str(runtime))
    # self.handle_onetime = self.run_once(self.calculate_value, runtime)
    self.calculate_value(self)
    #self.handle_regular = self.run_every(self.calculate_value, "now+15", 15*60) # will run every 15 minutes (15 minutes * 60 seconds)
    self.day_empty_handle = self.run_daily(self.calculate_value, "16:00:01")
    # Don't use. not sure where I'm at in bed # self.night_occupied_handle = self.run_daily(self.calculate_value, "03:00:01")
    
  def calculate_value(self, kwargs):
    try:
      for load_cell in self.args['load_cells']:
        # we don't have the full set of day_data yet, so use yesterday's value
        # self.log("Now is {}".format(datetime.now()))
        night_occupied_start_time = datetime.now().replace(hour=3,minute=0,second=0)
        night_occupied_end_time = datetime.now().replace(hour=5,minute=0,second=0)

        if datetime.now().hour < 16:
          day_unoccupied_start_time = (datetime.now()-timedelta(days=1)).replace(hour=13, minute=0, second=0)
          day_unoccupied_end_time = (datetime.now()-timedelta(days=1)).replace(hour=21, minute=0, second=0)
        else:
          day_unoccupied_start_time = datetime.now().replace(hour=13,minute=0,second=0)
          day_unoccupied_end_time = datetime.now().replace(hour=21, minute=0, second=0)
        self.log("Querying {} unoccupied times from {} to {}".format(load_cell, day_unoccupied_start_time, day_unoccupied_end_time))
        day_data = self.get_history(entity_id=load_cell, start_time = day_unoccupied_start_time, end_time=day_unoccupied_end_time)
        # self.log(day_data)

        # Calculate today's unoccupied data
        day_unoccupied_number = 0
        day_unoccupied_total = 0.0
        # self.log(len(day_data[0]))
        for entry in day_data[0]: # for some reason we get a list of size one of lists
          # self.log(type(entry['state']))
          # self.log(load_cell + " " + entry['state'])
          if entry['state'] != 'unavailable' and entry['state'] != 'unknown':
            day_unoccupied_number += 1
            day_unoccupied_total += float(entry['state'])

        day_unoccupied_average = day_unoccupied_total/day_unoccupied_number
        self.log("Day unoccupied average is: {}".format(str(day_unoccupied_average)))
        self.set_state(load_cell+"_average", state=math.trunc(day_unoccupied_average))
        # next lines forces a value
        # self.set_state("sensor.raw_bed_load_cell_1"+"_average", state=math.trunc(320000))
        # self.set_state("sensor.raw_bed_load_cell_2"+"_average", state=math.trunc(400000))
        
        # Calculate the occupied values from last night only if I was home last night. 
        self.log("get_history")
        ryan_night_history = [[]]
        ryan_night_history = self.get_history(entity_id="device_tracker.bayesian_zeke_home", start_time = night_occupied_start_time, end_time=night_occupied_end_time)
        self.log("get_history done")
        self.log(len(ryan_night_history))
        # sometimes this is zero so return an empty nested array, just like a get_history (with valuyes)
        if len(ryan_night_history) == 0:
          ryan_night_history=[[]]
        for event in ryan_night_history[0]:
          # self.log(event)
          if event["state"] == "home":
            self.log("Ryan was home last night so calculate the occupied values")
            self.log("Querying {} occupied times from {} to {}".format(load_cell, night_occupied_start_time, night_occupied_end_time))
            night_data = self.get_history(entity_id=load_cell, start_time = night_occupied_start_time, end_time=night_occupied_end_time)
          else:
            # USE A VALUE FROM 20 DAYS AGO
            # todo fix
            self.log("Ryan was NOT home last night so calculate the occupied values from 17 days ago")

            # self.log(night_occupied_start_time - timedelta(days=17))
            # self.log(night_occupied_end_time - timedelta(days=17))

            night_data = self.get_history(entity_id=load_cell, start_time = (night_occupied_start_time-timedelta(days=17)), end_time=(night_occupied_end_time-timedelta(days=17)))
          # self.log(len(night_data[0]))
          self.log("night data")
          
          # self.log(night_data)
          night_occupied_number = 0
          night_occupied_total = 0.0
          for entry in night_data[0]: # for some reason we get a list of size one of lists
            # self.log(type(entry['state']))
            # self.log(load_cell + " " + entry['state'])
            if entry['state'] != 'unavailable' and entry['state'] != 'unknown':
              night_occupied_number += 1
              night_occupied_total += float(entry['state'])

          night_occupied_average = night_occupied_total/night_occupied_number
          self.log("Night occupied average is: {}".format(str(night_occupied_average)))
          self.set_state(load_cell+"_night_occupied_average", state=math.trunc(night_occupied_average))
          # next lines forces a value
          # self.set_state("sensor.raw_bed_load_cell_1"+"_average", state=math.trunc(320000))
          # self.set_state("sensor.raw_bed_load_cell_2"+"_average", state=math.trunc(400000))

          # Calculate the previous day's day_data.

      for load_cell in self.args['load_cells']:
        day_unoccupied_start_time = (datetime.now()-timedelta(days=1)).replace(hour=13, minute=0, second=0)
        day_unoccupied_end_time = (datetime.now()-timedelta(days=1)).replace(hour=21, minute=0, second=0)

        night_occupied_start_time = (datetime.now()-timedelta(days=1)).replace(hour=3,minute=0,second=0)
        night_occupied_end_time = (datetime.now()-timedelta(days=1)).replace(hour=5,minute=0,second=0)

        self.log("Querying prior day's {} unoccupied times from {} to {}".format(load_cell, day_unoccupied_start_time, day_unoccupied_end_time))
        day_data = self.get_history(entity_id=load_cell, start_time = day_unoccupied_start_time, end_time=day_unoccupied_end_time)
        day_number = 0
        day_total = 0.0
        # self.log(day_data)
        for entry in day_data[0]: # for some reason we get a list of size one of lists
          # self.log(type(entry['state']))
          # self.log(load_cell + " " + entry['state'])
          if entry['state'] != 'unavailable' and entry['state'] != 'unknown':
            day_number += 1
            day_total += float(entry['state'])
        day_average = day_total/day_number
        self.log(load_cell + " " + str(day_average))
        self.set_state(load_cell+"_yesterday_average", state=math.trunc(day_average))

        self.log("Querying prior day's {} occupied times from {} to {}".format(load_cell, night_occupied_start_time, night_occupied_end_time))
        night_data = self.get_history(entity_id=load_cell, start_time = night_occupied_start_time, end_time=night_occupied_end_time)
        night_number = 0
        night_total = 0.0
        # self.log(night_data)
        if not night_data:
          # no data returned
          night_average=day_average-5000
          self.log("No occupied data found. Let's go with unoccupied value -5000: {}".format(night_average))
          self.set_state(load_cell+"_yesterday_night_average", state=math.trunc(night_average))
          return

        for entry in night_data[0]: # for some reason we get a list of size one of lists
          # self.log(type(entry['state']))
          # self.log(load_cell + " " + entry['state'])
          if entry['state'] != 'unavailable' and entry['state'] != 'unknown':
            night_number += 1
            night_total += float(entry['state'])

        night_average = night_total/night_number
        # self.log(load_cell + " " + str(night_average))
        self.set_state(load_cell+"_yesterday_night_average", state=math.trunc(night_average))
    except Exception as e:
      self.log(e)
      self.log("Exception thrown during processing. Maybe HA is down/unreachable. Trying again in 5 minutes.")
      runtime = datetime.time(datetime.now()+timedelta(minutes=5))
      self.log("Will run once at "+str(runtime))
      self.handle_onetime = self.run_once(self.calculate_value, runtime)


