#!/usr/bin/env python

from flask import Flask, render_template
import pyowm
from flask_socketio import SocketIO, emit
import time
import shelve
from threading import Thread
import types
import numbers
import decimal
import RPi.GPIO as GPIO
import logging

#logging.basicConfig(level=logging.DEBUG, filename="weatherlog.log")

owm = pyowm.OWM('8cb7e0fcf5a41cd34812845fd6aa876e')  # from https://home.openweathermap.org/api_keys
app = Flask(__name__)
app.config['SECRET_KEY'] = 'secret!'
socketio = SocketIO(app)

# defaults
flowLiters = 0
sprinklerInterval = 50
sprinklerTime = 10
minTemp = 21
startTime = 6
stopTime = 19

db = shelve.open('database.db')
# create db entry if it does not yet exist
if (not db.has_key('flowLiters')):
    db['flowLiters'] = flowLiters
    db['sprinklerInterval'] = sprinklerInterval # mins wait time to turn sprinkler on
    db['sprinklerTime'] = sprinklerTime # mins of sprinkler to be turned on
    db['minTemp'] = minTemp
    db['startTime'] = startTime
    db['stopTime'] = stopTime
else:
    flowLiters = db['flowLiters']
    sprinklerInterval = db['sprinklerInterval']
    sprinklerTime = db['sprinklerTime']
    minTemp = db['minTemp']
    startTime = db['startTime']
    stopTime = db['stopTime']
db.close()

# set location 
lat = 52.246712
lon = 6.847556

flowPinState = False 
shutdownTime = time.time() # unix timestamp on when to close flow
requestTimeout = 10 # only request api every x mins

# set GPIO pins
GPIO.setmode(GPIO.BCM) # use GPIO numbers not pin numbers
flowPin = 18 # the GPIO pin number for the flow valve controller
ratePin = 24 # the GPIO pin that receives flow meter interrupts

# set up flow rate counter
flowFactor = 5.3 # pulses/sec per litre/minute of flow
flowRate = 0
flowRateCount = 0
def increment_flow_count(channel):
    global flowRateCount
    flowRateCount = flowRateCount + 1

GPIO.setup(flowPin, GPIO.OUT)
GPIO.output(flowPin, flowPinState)
GPIO.setup(ratePin, GPIO.IN)
GPIO.add_event_detect(ratePin, GPIO.FALLING, callback=increment_flow_count)

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
    global shutdownTime
    get_weather()
    rain = weather.get_rain()
    temp = weather.get_temperature('celsius').get("temp")
    hourOfDay = float(time.strftime("%H"))
    if ((hourOfDay >= startTime) and (hourOfDay < stopTime)): # inside day range
        if (time.time() >= shutdownTime + sprinklerInterval * 60 ):
            #TODO make sure rain is about to fall within x minutes
            if (not rain): # make sure it's not already raining (or about to rain)
                if (temp >= minTemp):
                    shutdownTime = time.time() + sprinklerTime * 60 # set new shutdown time in future
                else: 
                    print("not warm enough")
            else:
                print("it's raining")
        else: 
            print("it's not time yet")
    else: 
        print("not inside time range")
def switch_loop():
    global flowPinState
    while True:
        try:
            should_flow_start()
            if (shutdownTime > time.time()):
                flowPinState = True
            else: 
                flowPinState = False
            GPIO.output(flowPin, not flowPinState) # inverse state because of inverting circuit
            time.sleep(1)
        except Exception, e:
            logging.debug("pin switch loop crashed because: " + e)

# ------- Flow meter -----------

def flow_loop():
    global flowRate, flowLiters
    prevPulses = flowRateCount
    dbStoreInterval = 10
    prevStore = time.time() # db store timer

    while True:
        flowRate = (flowRateCount - prevPulses) / flowFactor # flow in litre/min
        prevPulses = flowRateCount
        flowLiters  = flowLiters + flowRate / 60 # increment liters by 1/60th of the flowRate
        if prevStore + dbStoreInterval < time.time():
            store_in_db()
            prevStore = time.time()
        time.sleep(1)

def store_in_db():
    try:
        db = shelve.open('database.db')
        db['flowLiters'] = flowLiters
        db['sprinklerInterval'] = sprinklerInterval # mins wait time to turn sprinkler on
        db['sprinklerTime'] = sprinklerTime # mins of sprinkler to be turned on
        db['minTemp'] = minTemp
        db['startTime'] = startTime
        db['stopTime'] = stopTime
        db.close()
    except Exception, e:
        logging.debug("DB store exception: " + e)


# ---------------- WEB ------------------

def sendSprinkler():
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

def getSettings():
    msg = {'sprinklerInterval': sprinklerInterval,
            'sprinklerTime': sprinklerTime,
            'minTemp': minTemp,
            'startTime': startTime,
            'stopTime': stopTime
        }
    emit('getSettings', msg)
    print("sending settings")

@app.route('/')
def index():
    return render_template('index.html',weather=weather)

@socketio.on('connect')
def init_message():
    sendSprinkler()
    getSettings()

@socketio.on('getSettings')
def sendSettings():
    getSettings()

@socketio.on('setSettings')
def setSettings(msg):
    global sprinklerInterval, sprinklerTime, minTemp, startTime, stopTime
    try:
      _sprinklerInterval = float(msg['sprinklerInterval'])
      _sprinklerTime = float(msg['sprinklerTime'])
      _minTemp = float(msg['minTemp'])
      _startTime = float(msg['startTime'])
      _stopTime = float(msg['stopTime'])
      if _startTime < _stopTime and _startTime >= 0 and _startTime <= 24 and _stopTime > 0 and _stopTime < 24:
        sprinklerInterval = _sprinklerInterval
        sprinklerTime = _sprinklerTime
        minTemp = _minTemp
        startTime = _startTime
        stopTime = _stopTime
        getSettings()
        print("Setting new settings")
      else:
        print("startTime later then Stoptime")
    except:
        print("contained wrong filetype")


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
    msg = {'flow': flowLiters,
           'flowSpeed': flowRate
        }
    emit('passFlow', msg)

# ------------- Main ---------------

if __name__=='__main__':
    app.debug = False
    webThread = Thread(target=socketio.run, args=(app, '0.0.0.0'))
    webThread.setDaemon(True)
    webThread.start()

    switchThread = Thread(target=switch_loop)
    switchThread.setDaemon(True)
    switchThread.start()

    flowThread = Thread(target=flow_loop)
    flowThread.setDaemon(True)
    flowThread.start()

    while True: # to keep threads alive
        pass
