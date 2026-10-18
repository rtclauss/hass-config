import hassapi as hass
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
        self.zone_departure_rules = self.args.get("zone_departure_rules", [])
        # TODO change this listen_event to leaving work
        #More text
        #self.listen_event(self.event_received, "traccar_ignition_on")
        self.listen_state(self.location_update, entity=self.tracked_device, old="Work", new="Away")
        for rule in self.zone_departure_rules:
            self.listen_state(self.location_update, entity=self.tracked_device, old=rule["zone"], new=rule.get("arrival_zone", "Away"))

    def location_update(self, entity, attribute, old, new, kwargs):
        self.log(entity)
        self.log(attribute)
        self.log(old)
        self.log(new)


    def event_received(self, event_name, data, kwargs):
        event_type = data["type"]
        event_location = data["location"]
        event_received = datetime.now()

        if event_type == "ignition:on":
            self.set_state("input_boolean.car_in_motion", state="on")
        elif event_type == "ignition:off" or event_type == "trip:finished":
            self.set_state("input_boolean.car_in_motion", state="off")
        
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
                if now > fourpm and not (driving_time < now < calendar_start_time):
                    self.log("Looks like you're going home right away. Turning on Nest")
                    self.call_service(self.notify_target, message="Looks like you're going home right away. Turning on Nest")
                    self.call_service("climate/set_preset_mode", preset_mode="none")
            else:
                for rule in self.zone_departure_rules:
                    if location != rule["zone"]:
                        continue
                    if datetime.today().weekday() in rule["weekdays"]:
                        message = "Leaving a scheduled location. Turning on Nest"
                        self.log(message)
                        self.call_service(self.notify_target, message=message)
                        self.call_service("climate/set_preset_mode", preset_mode="none")
                    break
            
        