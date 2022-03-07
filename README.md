# pylseox-mqtt
MQTT transmitter for LPOW pulse oximeter

This project is intended to be able to be used with any BLE Pulse Oximeter, but I've not gotten the code to handle any more than my own right now, the LPOW A340B. The project is to send the datapoints from the device to log in Home Assistant.

This project folder is set up to be pretty much ready-to-go for use with Balena Cloud. To get it going, either create a `.env` file in the project root that contains required settings before running `balena push <projectname>`, or in the web UI as a variable on the device. Currently the code only supports authenticated mqtt hosts over non-TLS but this is my next project.

Config requires the following fields:

- mqtt_host
- mqtt_user
- mqtt_pass
- ble_address -- this is the BLE MAC of your LPOW pulse oximeter

Optionally, you can include these, which will default to 'Generic' if not specified:

- brand
- model

And that's it! It should appear in auto-discovery for Home Assistant automatically, and sensors will be marked 'available' once the device is reading.