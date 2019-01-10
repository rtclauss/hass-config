import appdaemon.plugins.hass.hassapi as hass
import datetime
from datetime import datetime

class AutomaticHelper(hass.Hass):
    def initialize(self) -> None:
        self.listen_event(self.event_received, "automatic_update")

    def event_received(self, event_name, data, kwargs):
        event_type = data["type"]
        event_location = data["location"]
        event_received = datetime.now()

        self.log("Automatic event received from {}. Event was: {}".format(event_type, event_location))
        self.set_state("sensor.automatic_event", state = event_type, attributes = {"event_data": event_location, "event_received": str(event_received)})