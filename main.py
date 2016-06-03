from flask import Flask, render_template
import pyowm
from flask_socketio import SocketIO, emit
import time
import shelve
from threading import Thread
import types
import numbers
import decimal

owm = pyowm.OWM('8cb7e0fcf5a41cd34812845fd6aa876e')  # from https://home.openweathermap.org/api_keys
app = Flask(__name__)
app.config['SECRET_KEY'] = 'secret!'
socketio = SocketIO(app)
db = shelve.open('database.db')

# create db entry if it does not yet exist
if (not db.has_key('flowLiters')):
    db['flowLiters'] = 0 


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

# set initial values
observation = owm.weather_at_coords(lat,lon)
weather = observation.get_weather()
lastRequestTime = 0

# ------------- flow controller ----------------

def get_weather():
    global weather, lastRequestTime # make object global so they can be accessed by client template
    now = time.time()

    if (lastRequestTime <= now - requestTimeout * 60):
        observation = owm.weather_at_coords(lat,lon)
        weather = observation.get_weather()
        lastRequestTime = now

def should_flow_start():
    get_weather()
    rain = weather.get_rain()
    temp = weather.get_temperature('celsius').get("temp")
    hourOfDay = time.strftime("%H")
    if ((hourOfDay >= startTime) and (hourOfDay < stopTime)): # inside day range
        if (time.time() >= shutdownTime + sprinklerInterval * 60 ):
            #TODO make sure rain is about to fall within x minutes
            if (not rain): # make sure it's not already raining (or about to rain)
                if (temp >= minTemp):
                    shutdownTime = time.time() + sprinklerTime * 60 # set new shutdown time in future
                    #TODO write to database



def switch_loop():
    while True:
        should_flow_start()
        if (shutdownTime <= time.time()):
            flowPinState = True
        else: 
            flowPinState = False
        # write pinstate
        time.sleep(1)

# ------- Flow meter -----------

def flow_loop():
    h=1



# ---------------- WEB ------------------

def sendSprinkler():
    print("sending pin state: " + str(flowPinState))
    emit('getSprinkler', {'state': flowPinState, 'time': shutdownTime})

def setSprinkler(state, interval):
    print("received state: " + str(state))
    print("received interval: " + str(interval))
    global flowPinState, shutdownTime # change the global state of the sprinkler
    if (state):
        shutdownTime = time.time() + interval * 60
        flowPinState = True # Set pin state in advance to be send back
    else:
        shutdownTime = time.time()
        flowPinState = False
    print("Manually setting pinState to: " + str(flowPinState)) 

    #TODO write shutdown time to db
    sendSprinkler() # return new state to client

@app.route('/')
def index():
    return render_template('index.html',weather=weather)

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
    state = message['state']
    try:
        interval = float(message['time'])
    except:
        print("invalid timer type")
        emit('invalidInput', {'error': "wrong type sent"})

    # check if time is a number object
    numberResult = [isinstance(interval, numbers.Number) for x in (0, 0.0, 0j, decimal.Decimal(0))]
    if (numberResult and (type(state)==type(True))): # check for correct types
        if ((interval > minInterval) and (interval < maxInterval)): # check for reasonable value
            setSprinkler(state, interval)
        else:
            emit('invalidInput', {'error': "invalid time sent"})
            print("Error, invalid time: " + interval)
    else:
        emit('invalidInput', {'error': "wrong type sent"})
        print("Error, wrong type")



@socketio.on('getFlow')
def send_flow():
    emit('passFlow', {'flow': db['flowLiters']})

# ------------- Main ---------------

if __name__=='__main__':
    webThread = Thread(target=socketio.run, args=(app, ) )
    webThread.setDaemon(True)
    webThread.start()

    switchThread = Thread(target=switch_loop)
    switchThread.setDaemon(True)
    switchThread.start()

    flowThread = Thread(target=flow_loop)
    flowThread.setDaemon(True)
    flowThread.start()

    while True: # to keep threads alive
        time.sleep(1)
