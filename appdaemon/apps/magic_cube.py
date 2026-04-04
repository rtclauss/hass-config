import hassapi as hass
import datetime
from datetime import datetime

class RemoteControl(hass.Hass):
    def initialize(self) -> None:
       if 'event' in self.args:
            self.listen_event(self.handle_event, self.args['event'])

    def handle_event(self, event_name, data, kwargs):
        self.log(data)
        if data['device_ieee'] == self.args['id']:
            #self.log(data['args'])
            if 'flip' in data['command']:
                self.log('in flip')
                self.log(data['args'])
                if data['args']['activated_face'] == 1:
                    self.log('Cube flip bottom to top. Turn on ' + self.args['light'])
                    self.turn_on(self.args['light'], transition = 10)
                if data['args']['activated_face'] == 4:
                    self.log('Cube flip top to bottom. Turn off ' + self.args['light'])
                    self.turn_off(self.args['light'], transition = 10)
            elif data['command'] == 'knock':
                self.log('knock {}'.format(data['args']))
            elif data['command'] == 'slide':
                self.log('slide {}'.format(data['args']))
            elif data['command'] == 'shake':
                self.log('shake {}'.format(data['args']))
            elif data['command'] == 'drop':
                self.log('drop {}'.format(data['args']))
            elif 'rotate' in data['command']:
                self.log("rotate")
                self.log(data['args']['relative_degrees'])
                #self.log('Rotation of ' + data['args']['relative_degrees'])
                rotation = data['args']['relative_degrees']
                self.log("Rotation set to {}".format(rotation))
                currentBrightness = self.get_state(self.args['light'], attribute="brightness")
                if currentBrightness == 0 or currentBrightness == None:
                    newLevel = int(255 * (rotation/500))
                else:
                    newLevel = currentBrightness + int(255 * (rotation/500))
                
                if newLevel > 255:
                    newLevel = 255
                elif newLevel < 0:
                    self.log("turning off light "+ self.args['light'])
                    self.turn_off(self.args['light'], transition = 10)
                    return
                
                self.log('Setting brightness to ' + str(newLevel))
                self.turn_on(self.args['light'], brightness = newLevel, transition = 2)
                #self.args['light']