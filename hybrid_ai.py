"""
Simple script for interacting with Gemini
See: https://ai.google.dev/gemini-api/docs/image-understanding
Tested against google-genai version 1.46

For convenient experimenting, it takes care of some housekeeping bits:

- Saving images and text output
- Prevent overwriting previous results at next run

Gemini- and MQTT-part inspired by an example from Robert K. Brown (robert.brown@axis.com)

A few things need to be set up for this script to work, see accompanying
README file.

Note: This file uses a tabwidth of 3 spaces.
"""

import time
import json
import base64
from abc import ABC, abstractmethod
from signal import signal, SIGINT
from sys import exit
import os
import argparse
import datetime
import atexit

from dotenv import load_dotenv

from google import genai
from google.genai import types

import paho.mqtt.client as paho
from paho import mqtt

#-------------------------------------------------------------------------------
#
#  Utilities                                                                {{{1
#
#-------------------------------------------------------------------------------

def percentage(string_value):
   """
   Convert to a percentage for class/color scores
   """
   if '%' in string_value:
      decimal_value = float(string_value.strip('%')) / 100
   else:
      decimal_value = float(string_value)
   return f"{decimal_value * 100:.2f}%"

def ask_gemini(prompt: str, image_data: bytes):
   """
   Note: Free tier gemini-2.5-flash has 250 per day rate limit
   """
   response = gemini.models.generate_content(
    # model='gemini-2.5-flash',
      model='gemini-2.5-flash-lite',
      contents=[
         types.Part.from_bytes(
           data = image_data,
           mime_type = 'image/jpeg'
         ),
         prompt
      ]
   )
   return response

def handle_sigint(sig, frame):
   """
   """
   print('Bye')
   exit(0)

#-------------------------------------------------------------------------------
#
#  MQTT interfacing                                                         {{{1
#
#-------------------------------------------------------------------------------

class MQTTMessageHandler(ABC):

   def __init__(self):
      pass

   @abstractmethod
   def handle(self, msg : mqtt.client.MQTTMessage):
      pass

def on_connect(client, userdata, flags, rc, properties=None):
    """
        Prints the result of the connection with a reasoncode to stdout ( used as callback for connect )

        :param client: the client itself
        :param userdata: userdata is set when initiating the client, here it is userdata=None
        :param flags: these are response flags sent by the broker
        :param rc: stands for reasonCode, which is a code for the connection result
        :param properties: can be used in MQTTv5, but is optional
    """
    print("CONNECTION received with code %s." % rc)

def on_publish(client, userdata, mid, properties=None):
    """
        Prints mid to stdout to reassure a successful publish ( used as callback for publish )

        :param client: the client itself
        :param userdata: userdata is set when initiating the client, here it is userdata=None
        :param mid: variable returned from the corresponding publish() call, to allow outgoing messages to be tracked
        :param properties: can be used in MQTTv5, but is optional
    """
    print("mid: " + str(mid))

def on_subscribe(client, userdata, mid, granted_qos, properties=None):
    """
        Prints a reassurance for successfully subscribing

        :param client: the client itself
        :param userdata: userdata is set when initiating the client, here it is userdata=None
        :param mid: variable returned from the corresponding publish() call, to allow outgoing messages to be tracked
        :param granted_qos: this is the qos that you declare when subscribing, use the same one for publishing
        :param properties: can be used in MQTTv5, but is optional
    """
    print("Subscribed: " + str(mid) + " " + str(granted_qos))

def on_message(client, userdata : MQTTMessageHandler, msg : mqtt.client.MQTTMessage):
    """
        Prints a mqtt message to stdout ( used as callback for subscribe )

        :param client: the client itself
        :param userdata: userdata is set when initiating the client, here it is userdata=None
        :param msg: the message with topic and payload
    """
    userdata.handle(msg)


#-------------------------------------------------------------------------------
#
#  Snapshot storage                                                         {{{1
#
#-------------------------------------------------------------------------------

class FileStorage:
   """
   Straightforward logic to manage the snapshots when the numbers run into the
   thousands. It creates a subdirectory per 1024 snapshots

   It also tries to restart where it got Ctrl-C'ed last time. YMMV
   """
   def __init__(self, location: str):
      """
      Start in path 'location', create it if it doesn't exist
      Throws exception if it fails
      """
      self.img_counter = 0
      if not os.path.exists(location):
         os.makedirs(location)
      else:
         if os.path.isfile(location):
            raise FileExistsError(location)
         if not os.access(location, os.W_OK):
            raise Exception(f'Path not writeable: {location}')

      self.base = location
      print(f'Initializing snapshot-storage in {self.base}')
      self.counter_file = os.path.join(location, 'index')
      if os.path.exists(self.counter_file):
         with open(self.counter_file, 'rt') as f:
            self.img_counter = int(f.read())
            print(f'Resuming storage at image {self.img_counter}')

      atexit.register(self.cleanup)

   def store_image(self, label: str, image_data: bytes):
      """
      """
      filename = None
      if image_data is not None:
         path = os.path.join(self.base, f'{ self.img_counter // 1024:04}')
         if not os.path.exists(path):
            os.mkdir(path)
         with open(filename := f'{path}/image_{self.img_counter:05}_{label}.jpg', 'wb') as image_file:
             image_file.write(image_data)
         self.img_counter += 1
      return filename

   def cleanup(self):
      """
      Help orderly shutdown
      """
      with open(self.counter_file, 'wt') as f:
         f.write(str(self.img_counter))
      print('Closed storage')

#-------------------------------------------------------------------------------
#
#  Track handling & Gemini requests                                         {{{1
#
#-------------------------------------------------------------------------------

class TracksHandler(MQTTMessageHandler):
   """
   Sends snapshots to Gemini and keeps a log of the results
   Saves the snapshots
   """
   def __init__(self, storage : FileStorage):
      super().__init__()
      self.img_counter = 0
      self.storage = storage
      self.logname = f'{storage.base}/{datetime.datetime.now().strftime("%Y-%m-%d-%H-%M")}.log'
      self.logfile = open(self.logname, 'w')
      atexit.register(self.cleanup)

   def cleanup(self):
      self.logfile.close()
      print('Closed log')

   def log(self, content):
      print(content)
      self.logfile.write(content)
      self.logfile.write('\n')

   def handle(self, msg : mqtt.client.MQTTMessage):

      jdata = json.loads(msg.payload)
      is_completed = jdata.get('end_reason', 'none') == 'Completed'

      # Get image and if available, convert to binary
      if (image_data := jdata.get('image', {'data': None}).get('data')):
         image_data = base64.b64decode(image_data)

      mclass = None
      if 'classes' in jdata:
         # data.classes[0].type - get the highest ranking metadata classification
         best_class = jdata['classes'][0]
         mclass = best_class.get('type')

      mduration = str(jdata['duration'])
      fduration = float(mduration)

      if is_completed and image_data is not None and mclass is not None and fduration > 2.0:

          mclassrank = str(best_class['score'])

          if image_data is not None:
             filename = self.storage.store_image(mclass, image_data)

          # Get highest scoring color and scoring percentile
          mcolor = None
          mcolorrank = None
          if 'colors' in best_class:
             mcolor = str(best_class['colors'][0]['name'])
             mcolorrank = str(best_class['colors'][0]['score'])

          #
          # Experimentation area. Start making detection modifications here
          #
          
          if ((mclass == 'Car') or (mclass == 'Truck') or (mclass == 'Bus') or (mclass == 'Vehicle')):

             self.log(f'{mclass}! {filename}')
             # print('\nAXIS Metadata Object ID: ' + str(jdata['id']))
             # print(f'Vehicle type: {mclass} ({percentage(mclassrank)})')
             # if mcolor:
             #     print(f'Vehicle color: {mcolor} ({percentage(mcolorrank)})')
             # print('Time tracked: ' + mduration + ' sec')

             # prompt = 'Please tell me the make, model, trim, color, and estimated year of the ' + mclass + ' shown in this picture, as well as any other interesting characteristics or attributes. Do not share your reasoning. Format your response as succinctly as possible.'
             # response = ask_gemini(prompt, image_data)

          elif mclass == 'Bike':
             pass
             self.log(f'Bike! {filename}')
             # response = ask_gemini('In this picture is a vehicle on two wheels, determine the type. Answer with a single word.', image_data)
             # self.log(f'Vehicle type: {response.text}\n\n* * *')

          elif mclass == 'Human':
              pass
              self.log(f'Human! {filename}')
              # response = ask_gemini('In this picture is a human. Can you also see a dog? Answer yes or no', image_data)
              # self.log(f'Is there a dog: {response.text}\n\n* * *')
              # Dogs seldom walk close to their owner :( More practical
              # testcase would be maybe: 'Is this a man or a woman?'
          else:
             self.log(f'Ignored: {mclass}')
      else:
          # Tell why we didn't process
          self.log(f'Ignored: {"" if is_completed  else "in"}complete, {"" if image_data else "no "}image, {"" if "classes" in jdata else "no "}classes, {"length okay" if fduration > 2.0 else "too short"}')
          # Dump payload
          # self.log(f'Ignored: {msg.payload}')
          pass

if __name__ == '__main__':

   signal(SIGINT, handle_sigint)

   # Preload environment settings
   load_dotenv('environment.env')
   if not os.getenv('MQTT_HOST'):
      os.environ['MQTT_HOST'] = '127.0.0.1'

   # Get settings from commandline
   parser = argparse.ArgumentParser(description = 'Send Best snapshots to Gemini')
   parser.add_argument('-k', '--api_key', type=str, required=False, default = os.getenv('GEMINI_API_KEY'), help='Gemini API key for authentication')
   parser.add_argument('-u', '--mqtt_username', type=str, required=False, default = os.getenv('MQTT_USER'), help='Username for MQTT broker')
   parser.add_argument('-p', '--mqtt_password', type=str, required=False, default = os.getenv('MQTT_PASS'), help='Password for MQTT broker')
   parser.add_argument('-b', '--mqtt_host', type=str, required=False, default = os.getenv('MQTT_HOST'), help='Hostname or IP address of MQTT broker')
   parser.add_argument('-t', '--mqtt_topic', type=str, required=False, default = os.getenv('MQTT_TOPIC', 'track_topic'), help='Hostname or IP address of MQTT broker')
   parser.add_argument('-s', '--storage', type=str, required=False, default = os.getenv('IMAGE_PATH', 'images'), help='Path to storage location. Will be created if it doesn\t exist')
   args = parser.parse_args()

   print('Initializing genai...')
   gemini = genai.Client(api_key = args.api_key)

   storage = FileStorage(args.storage)

   print('Initializing mqtt connection...')
   # See: https://eclipse.dev/paho/files/paho.mqtt.python/html/client.html
   client = paho.Client(paho.CallbackAPIVersion.VERSION2, userdata = TracksHandler(storage))
   client.on_connect = on_connect

   # Note: working with unsecured MQTT for simplicity
   client.username_pw_set(args.mqtt_username, args.mqtt_password)
   client.connect(args.mqtt_host, 1883)
   client.on_subscribe = on_subscribe
   client.on_message = on_message
   client.on_publish = on_publish
   client.subscribe(args.mqtt_topic)

   print('Entering loop')
   # you can also use loop_start and loop_stop
   client.loop_forever()

# vim: set nowrap sw=3 sts=3 et fdm=marker:

