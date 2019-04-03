import appdaemon.plugins.hass.hassapi as hass

class NestTravelHelper(hass.Hass):
    def initialize(self) -> None:
        self.driving_sensor = self.args['driving_sensor']
        self.phone = self.args['phone']
        self.thermostat = self.args["thermostat"]
        self.outside_temp_feels_like = self.args['outside_temp_feels_like']
        self.outside_temp_is = self.args["outside_temp"]
        self.log("Configured to use {}, {}, and {} to determine nest conditions".format(self.driving_sensor, self.phone, self.thermostat, self.outside_temp_feels_like))
        self.listen_state(self.state_changed, self.thermostat)

    def state_changed(self, entity, attribute, old, new, kwargs):
        self.log("Nest state for {} changed from {} to {}".format(entity, old, new))
        if new == old:
            return
        #new_away_mode = new['attributes']["away_mode"]
        #old_away_mode = old['attributes']['away_mode']
        
        driving_state = self.get_state(self.driving_sensor)
        
        outside_temp_feels = self.get_state(self.outside_temp_feels_like)
        outside_temp_is = self.get_state(self.outside_temp_is)
        if outside_temp_feels == "unkown":
            outside_temp = float(outside_temp_is)
        elif outside_temp_is != "unknown":
            outside_temp = float(outside_temp_feels)
        else:
            outside_temp = None

        if outside_temp == None:
            operation_mode = 'auto'
        elif outside_temp < 50:
            operation_mode = 'heat'
        elif 50 <= outside_temp < 67:
            operation_mode = 'auto'
        elif outside_temp >= 67:
            operation_mode = 'cool'
        
        ## Not sure if I need to check if windows are open or not.  Nest should be turned off so no change in state should happen.
        
        if driving_state == 'on' and new == "eco":
            self.log("Calling set_operation_mode with values: {} {}".format(entity, operation_mode))
            self.call_service(self, 'climate/set_operation_mode', entity_id = entity, operation_mode = operation_mode)
        
        ## not sure if I need this next if statement
        #if driving_sensor == 'on' and new_away_mode = "on":
        #    self.call_service(self, 'climate/set_away_mode', entity_id = entity, away_mode = old_away_mode)


