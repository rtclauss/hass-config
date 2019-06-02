import appdaemon.plugins.hass.hassapi as hass
from enum import Enum
from machine import Machine, ANY, StateOn, StateOff, Timeout

class States(Enum):
  IDLE = 1
  CLEAN = 2
  CLEANING = 3
  MUSTY = 4
globals().update(States.__members__) # Make the states accessible without the States. prefix.

class CleanMachine(hass.Hass):
    def initialize(self):
        self.vibration = self.args['vibration_sensor']
        self.door = self.args['open_sensor']

        machine = Machine(self, States)

        machine.add_transitions(IDLE, StateOn(self.vibration), CLEANING, on_transition=self.cleaning)
        machine.add_transition(CLEANING, StateOff(self.vibration), CLEAN, on_transition=self.clean)
        machine.add_transition(CLEAN, Timeout(86400), MUSTY, on_transition=self.musty)
        machine.add_transition(CLEAN, StateOn(self.door), IDLE, on_transition=self.idle)
        machine.add_transition(MUSTY, StateOn(self.door), IDLE, on_transition=self.idle)
        
        machine.log_graph_link()

    def cleaning(self):
        self.select_option("input_select.washer_state", "CLEANING")

    def clean(self):
        self.select_option("input_select.washer_state", "CLEAN")
        
    def idle(self):
        self.select_option("input_select.washer_state", "IDLE")

    def musty(self):
        self.select_option("input_select.washer_state", "MUSTY")
