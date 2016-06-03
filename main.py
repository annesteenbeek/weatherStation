from flask import Flask, render_template
import pyowm
from flask_socketio import SocketIO, emit
import time
import shelve
from threading import Thread
import types

owm = pyowm.OWM('8cb7e0fcf5a41cd34812845fd6aa876e')  # from https://home.openweathermap.org/api_keys
app = Flask(__name__)
app.config['SECRET_KEY'] = 'secret!'
socketio = SocketIO(app)
db = shelve.open('database.db')

# create db entry if it does not yet exist
if (not db.has_key('flowLiters')):
    db['flowLiters'] = 0 


lastRequestTime = time.time()
# set location 
lat = 52.246712
lon = 6.847556

flowPinState = False 
shutdownTime = time.time() # unix timestamp on when to close flow
requestTimeout = 10 # only request api every x mins
sprinklerInterval = 50 # mins between sprinkler states
sprinklerTime = 10 # mins of sprinkler to be turend on
minTemp = 21
startTime = 6
stopTime = 19

def get_weather():
    global weather, lastRequestTime # make object global so they can be accessed by client template
    now = time.time()

    if (lastRequestTime <= now - requestTimeout * 60 * 60):
        observation = owm.weather_at_coords(lat,lon)
        weather = observation.get_weather()
        lastRequestTime = now

def should_flow_start():
    get_weather()
    rain = weather.get_rain()
    t = temp.get("temp")
    hourOfDay = time.strftime("%H")
    if ((hourOfDay >= startTime) and (hourOfDay < stopTime)): # inside day range
        if (time.time() >= shutdownTime + sprinklerInterval * 60 * 60):
            #TODO make sure rain is about to fall within x minutes
            if (not rain): # make sure it's not already raining (or about to rain)
                if (t >= minTemp):
                    shutdownTime = time.time() + sprinklerTime * 60 *60 # set new shutdown time in future
                    #TODO write to database



def flow_loop():
    while True:
        should_flow_start()
        if (shutdownTime <= time.time()):
            flowPinState = True
        else: 
            flowPinState = False
        # write pinstate
        time.sleep(1)

def sendSprinkler():
    emit('getSprinkler', {'state': flowPinState, 'time': shutdownTime})

def setSprinkler(state, time):
    global flowPinState, shutdownTime # change the global state of the sprinkler
    if (state):
        shutdownTime = time.time() + time * 60 * 60
        flowPinState = True # Set pin state in advance to be send back
    else:
        shutdownTime = time.time()
        flowPinState = False
    #TODO write shutdown time to db
    sendSprinkler() # return new state to client

@app.route('/')
def index():
    return render_template('index.html', temp=temp, weather=weather)

@socketio.on('connect')
def init_message():
    sendSprinkler()

@socketio.on('getSprinkler')
def returnSprinkler():
    sendSprinkler()

@socketio.on('setSprinkler')
def handle_message(message):
    minInterval = 0
    maxInterval = 20
    time = message['time']
    state = message['state']
    if (time.isDigit() and (type(state)==type(True))): # check for correct types
        if ((time > minInterval) and (time <= maxInterval)): # check for reasonable value
            setSprinkler(state, time)
        else:
            emit('invalidInput', {'error': "invalid time sent"})
    else:
        emit('invalidInput', {'error': "wrong type sent"})



@socketio.on('getFlow')
def send_flow():
    emit('passFlow', {'flow': flowLiters})



# if __name__=='__main__':
#      Start thread for switch
#       start thread for web
#       start thread for flow
#     socketio.run(app)
#     flow_loop()
