import hassapi as hass
import datetime
from datetime import datetime

class DeconzHelper(hass.Hass):
    def initialize(self) -> None:
        self.listen_event(self.event_received, "zha_event")

    def event_received(self, event_name, data, kwargs):
        event_data = data["event"]
        event_id = data["id"]
        event_received = datetime.now()

        self.log("Deconz event received from {}. Event was: {}".format(event_id, event_data))
        self.set_state("sensor." + event_id, state = event_data, attributes = {"event_data": event_data, "event_received": str(event_received), "sensor": event_id, "source": "deconz_event"})