from flask import Flask, render_template
import pyowm
from flask_socketio import SocketIO, emit
import time
import shelve

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
startTime = 0
stopTime = 0


def should_flow_start():
    get_weather()
    # check if weather and time conditions allow for flow to start
    # and last shutdowntime was long enough ago
    # if so create new shutdownTime

def get_weather():
    global weather, lastRequestTime # make object global so they can be accessed by client template
    now = time.time()

    if (lastRequestTime <= now - requestTimeout * 60 * 60):
        observation = owm.weather_at_coords(lat,lon)
        weather = observation.get_weather()
        lastRequestTime = now


def flow_loop():
    while True:
        should_flow_start()
        if (shutdownTime <= currentTime):
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
    # Filter input first
    time = message['time']
    state = message['state']
    setSprinkler(state, time)


@socketio.on('getFlow')
def send_flow():
    emit('passFlow', {'flow': flowLiters})

print(time.strftime("%H"))


# while __name__=='__main__':
#     socketio.run(app)
#     flow_loop()
