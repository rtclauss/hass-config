import appdaemon.plugins.hass.hassapi as hass
from datetime import date
from datetime import datetime, time
from datetime import timedelta
from dateutil import parser

class AutomaticHelper(hass.Hass):
    def initialize(self) -> None:
        self.tracked_device = self.args['tracker_input']
        self.calendar = self.args['calendar']
        self.driving_time = self.args["driving_time"]
        self.notify_target = self.args["notify_target"]
        self.listen_event(self.event_received, "automatic_update")

    def event_received(self, event_name, data, kwargs):
        event_type = data["type"]
        event_location = data["location"]
        event_received = datetime.now()

        self.log("Automatic event received from {}. Event was: {}".format(event_type, event_location))
        self.set_state("sensor.automatic_event", state = event_type, attributes = {"event_data": event_location, "event_received": str(event_received)})
        
        location = self.get_state(self.tracked_device)
        calendar_start_time = parser.parse(self.get_state(self.calendar, attribute="start_time"))
        
        now = datetime.now()
        
        fourpm = datetime.combine(date.today(), time(16, 0))
        
        driving_time = calendar_start_time - timedelta(minutes=self.driving_time)
        
        self.log("location {}. calendar_start_time {}. driving_time {}".format(location, calendar_start_time, driving_time))
        
        if event_type == "ignition:on":
            if location == "Work":
                #if not self.now_is_between(driving_time, calendar_start_time) and now > fourpm:
                ## need another statement in case I leave for a baseball game
                if not (driving_time < now < calendar_start_time):
                    self.log("Looks like you're going home right away. Turning on Nest")
                    self.call_service(self.notify_target, message="Looks like you're going home right away. Turning on Nest")
                    self.call_service("climate/set_away_mode", away_mode="false")
            elif location == "OCC":
                if datetime.today().weekday() in (0,1,6):
                    self.log("Leaving OCC. Turning on Nest")
                    self.call_service(self.notify_target, message="Leaving OCC. Turning on Nest")
                    self.call_service("climate/set_away_mode", away_mode="false")
            elif location == "SPCC":
                if datetime.today().weekday() in (2,6):
                    self.log("Leaving SPCC. Turning on Nest")
                    self.call_service(self.notify_target, message="Leaving SPCC. Turning on Nest")
                    self.call_service("climate/set_away_mode", away_mode="false")
            
        