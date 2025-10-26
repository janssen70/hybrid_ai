# hybrid_ai
Send "Best Snapshots" from Axis Scene Analytics to Gemini for further analysis

It works by listening to Consolidated Tracks which come with a Best Snapshot.
It requires a number of things to be set up. The instructions below take some
shortcuts. These are fine if you do not regularly use MQTT or Python. You will
know what to do when you do.

### Gemini account
 - [Get yourself an API key](https://ai.google.dev/gemini-api/docs/api-key)
 - [Make the key available](https://ai.google.dev/gemini-api/docs/api-key#set-api-env-var) by setting an environment variable or modifying the script


### MQTT Broker
 - You can use public one like [Hive MQ](https://www.hivemq.com/mqtt/public-mqtt-broker/)
 - This script was tested with a local [Mosquitto](https://mosquitto.org/)
 - On Ubuntu, use this command to install. It will not give you the latest one
   but that's fine
   ````
   sudo apt install mosquitto
   ```
 - An example mosquitto configuration can be found in this repository. Install
   it as follows. It's a bit untidy by overwriting the main mosquitto.conf
   file:
   ```
   sudo cp mosquitto.conf /etc/mosquitto/mosquitto.conf
   ```
 - Initialize the password file with an initial user. Use the credentials as
   found in the Python script, or use something else and modify the script
   ```
   sudo mosquitto_passwd -c /etc/mosquitto/passwd <username>
   ```
 - If adding more users, do not use the -c argument. Use -h first to see
   details
 - Restart mosquitto
   ```
   sudo systemctl restart mosquitto
   ```

### Camera setup
A number of steps is required to setup the camera. It's recommended to upgrade
to the latest version first. This script was tested against Axis OS 12.5 and
12.6. Some API calls must be performed, but fortunately this can be done
interactively through the Swagger UI.

TBD


## Python setup
Some non-standard modules are required to make use of MQTT and Gemini. Install
as follows:

```
python3 -m pip install -r requirements.txt
```

If you're new to Python you may run into some problems. You can take these
steps to solve quickly without learning to understand virtual environments:

 - Some distributions come without pip. It needs to be installed using the
   package manager.
   ```
   sudo apt install python3-pip
   ```
 - You get an error message that the install may break system packages. This
   can be workarounded as follows, but carefully note first you _must_ run
   this _without_ sudo in front so that the modules will be installed locally
   in your user account.  Thus, no system packages will be broken
   ```
   python3 -m pip install --break-system-packages -r requirements.txt
   ```
