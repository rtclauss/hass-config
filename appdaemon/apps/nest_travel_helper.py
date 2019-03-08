import appdaemon.plugins.hass.hassapi as hass

class NestTravelHelper(hass.Hass):
    def initialize(self) -> None:
        self.driving_sensor = self.args['driving_sensor']
        self.phone = self.args['phone']
        self.thermostat = self.args["thermostat"]
        self.outside_temp_feels_like = self.args['outside_temp_feels_like']
        self.log("Configured to use {}, {}, and {} to determine nest conditions".format(self.driving_sensor, self.phone, self.thermostat, self.outside_temp_feels_like))
        self.listen_state(self.state_changed, self.thermostat, attribute = "all")
        

    def state_changed(self, entity, attribute, old, new, kwargs):
        #self.log("Nest state for {} changed received from {}. Event was: {}".format(entity, old, new))
        new_operation_mode = new['attributes']["operation_mode"]
        old_operation_mode = old['attributes']["operation_mode"]
        #new_away_mode = new['attributes']["away_mode"]
        #old_away_mode = old['attributes']['away_mode']
        
        driving_state = self.get_state(self.driving_sensor)
        
        outside_temp = float(self.get_state(self.outside_temp_feels_like))
        if outside_temp < 45:
            operation_mode = 'heat'
        elif 45 <= outside_temp < 67:
            operation_mode = 'auto'
        elif outside_temp >= 67:
            operation_mode = 'cool'
        
        ## Not sure if I need to check if windows are open or not.  Nest should be turned off so no change in state should happen.
        
        if driving_state == 'on' and new_operation_mode == "eco":
            self.call_service(self, 'climate/set_operation_mode', entity_id = entity, operation_mode = operation_mode)
        
        ## not sure if I need this next if statement
        #if driving_sensor == 'on' and new_away_mode = "on":
        #    self.call_service(self, 'climate/set_away_mode', entity_id = entity, away_mode = old_away_mode)

