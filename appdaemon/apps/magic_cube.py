import appdaemon.plugins.hass.hassapi as hass
import datetime
from datetime import datetime

class RemoteControl(hass.Hass):
    def initialize(self) -> None:
       if 'event' in self.args:
            self.listen_event(self.handle_event, self.args['event'])

    def handle_event(self, event_name, data, kwargs):
        if data['id'] == self.args['id']:
            self.log(data['event'])
            if data['event'] == 1006:
                self.log('Cube flip bottom to top. Turn on ' + self.args['light'])
                self.turn_on(self.args['light'])
            elif data['event'] == 6001:
                self.log('Cube flip top to bottom. Turn off ' + self.args['light'])
                self.turn_off(self.args['light'])
            elif data['event'] == 3002:
                self.log('Button dim down')
            elif data['event'] == 4002:
                self.log('Button off')
            elif '00' not in str(data['event']):
                #self.log('Rotation of ' + str(data['event']/100.0))
                rotation = data['event']
                currentBrightness = self.get_state(self.args['light'], attribute="brightness")
                if currentBrightness == 0 or currentBrightness == None:
                    newLevel = int(255 * (rotation/10000))
                else:
                    newLevel = currentBrightness + int(255 * (rotation/10000))
                
                if newLevel > 255:
                    newLevel = 255
                elif newLevel < 0:
                    #self.log("turning off light "+ self.args['light'])
                    self.turn_off(self.args['light'])
                    return
                
                #self.log('Setting brightness to ' + str(newLevel))
                self.turn_on(self.args['light'], brightness = newLevel)
                #self.args['light']