import time, os, sys, json, logging, uuid, re
from bluepy import btle
from datetime import datetime
#from multiprocessing import Process, Queue
from dotenv import dotenv_values
import paho.mqtt.client as mqtt


class PulseOxHandler(btle.DefaultDelegate):
    _topics = {}
    _mqtt_client = None
    def __init__(self, topics, mqtt_client):
        self._topics = topics
        self._mqtt_client = mqtt_client
        btle.DefaultDelegate.__init__(self)

    def _announce_status(self,status):
        availability = "ON" if status == "Reading" else "OFF"
        self._mqtt_client.publish(self._topics['status'],status)
        self._mqtt_client.publish(self._topics['availability'],availability)

    def handleNotification(self, handle, data):
        global ble_fail_count
        global ble_next_reconnect_delay
        global packets_by_type
        try:
            if len(data) == 7 and data[0] == 241:
                ble_fail_count = 0
                #q.put(data)
                if data[1] > 100 or data[2] > 200:
                    self._announce_status('Calibrating')
                    logging.debug("Calibrating...")
                elif data[1] <= 100 and data[2] <= 200:
                    logging.debug(f"SpO2: {data[1]}% \tBPM: {data[2]} \tPI: {data[4]/10.0}%")
                    self._announce_status('Reading')
                    self._mqtt_client.publish(self._topics['spo2'],data[1])
                    self._mqtt_client.publish(self._topics['bpm'],data[2])
                    self._mqtt_client.publish(self._topics['pi'],data[4]/10.0)
                else:
                    self._announce_status('Off')

                if ble_fail_count >= (ble_inactivity_timeout / ble_read_period):
                    # disconnect from device to conserve power
                    logging.warn("BLE: Inactivity timeout, disconnecting...")
                    ble_fail_count = 0
                    ble_next_reconnect_delay = ble_inactivity_delay
                    peripheral.disconnect()
                    self._announce_status('Reconnecting')
            elif data[0] == 240:
                ble_fail_count = 0
                self._mqtt_client.publish(self._topics['ppg'],json.dumps([x for x in data[1:-1]]))
        except Exception as e:
            logging.error(f"Data Handler Exception: {e}")

    def mqtt_flat(self):
        self._announce_status('Off')
        self._mqtt_client.publish(self._topics['spo2'], '')
        self._mqtt_client.publish(self._topics['bpm'], '')
        self._mqtt_client.publish(self._topics['pi'], '')
        self._mqtt_client.publish(self._topics['ppg'], '')

def get_mac():
    return ':'.join(re.findall('..', '%012x' % uuid.getnode()))

def get_discovery_payload(config, sensor):
    payload =  {
        "stat_t": f"pulseox/{config['host']}/sensors/{sensor['id']}",
        "unit_of_meas": sensor['units'],
        "icon": sensor['icon'],
        "uniq_id": f"{config['host']}_{sensor['id']}",
        "dev": {
            "ids": [config['host']],
            "cns":[['mac',config['mac']]],
            "name": f"{config['brand']} Pulse Oximeter",
            "mdl": config['model'],
            "mf": config['brand'],
            "sw": config['version']
        },
    }
    if sensor['id'] != 'status':
        payload.update({
            "avty_t": f"homeassistant/sensor/{config['host']}/availability",
            "pl_avail": "ON",
            "pl_not_avail": "OFF"
        })
    if 'category' in sensor.keys():
        payload["ent_cat"] = sensor['category']
    payload['name'] = f"{payload['dev']['name']} {sensor['name']}"
    logging.debug(f"Payload: {payload}")
    return payload

if __name__ == "__main__":
    logging.basicConfig(format="{asctime} [{levelname[0]}] {message}",style='{',level=logging.DEBUG)
    config_keys = ['ble_address','mqtt_host','mqtt_user','mqtt_pass','brand','model']
    config = {"brand":"Generic","model":"Generic"}
    try:
        config.update(dotenv_values())
        config.update({x:os.environ.get(x) for x in config_keys if x in os.environ.keys()})
        assert(len(config) >= len(config_keys))
        assert(config_keys == [x for x in config_keys if x in config.keys()])
        assert(None not in config.values())
    except AssertionError:
        logging.error(f"Missing some configuration keys, requires all of the following: {config_keys}")
        logging.error(f"Found the following vars: {config}")
        sys.exit(1)
    except Exception as e:
        logging.error(f"Unexpected issue importing configuration: {e}")
        sys.exit(1)
    
    if 'version' not in config.keys():
        if os.environ.get('BALENA_RELEASE_HASH') != None:
            config['version'] = os.environ.get('BALENA_RELEASE_HASH')
        else:
            config['version'] = ''
    config['host'] = os.environ.get('HOSTNAME')
    config['mac'] = get_mac()

    ble_address = config['ble_address']
    ble_read_period = 2
    ble_reconnect_delay = 10
    ble_inactivity_timeout = 300
    ble_inactivity_delay = 130
    packets_by_type = {}
    ble_next_reconnect_delay = ble_reconnect_delay
    ble_fail_count = 0

    mqttc = mqtt.Client()
    mqttc.username_pw_set(config['mqtt_user'],config['mqtt_pass'])
    mqttc.connect(config['mqtt_host'])
    peripheral = btle.Peripheral()
    sensors = [
        {'id':'spo2', 'name': 'SpO2', 'units': '%', 'icon':'mdi:water-percent'},
        {'id':'bpm','name': 'Heart Rate', 'units': 'BPM', 'icon':'mdi:heart-pulse'},
        {'id':'pi','name':'Perfusion Index','units':'%','icon':'mdi:water-opacity','category':'diagnostic'},
        {'id':'status','name':'Status','units':'','icon':'mdi:check-network', 'category':'diagnostic'},
        {'id':'ppg','name':'PPG','units':'','icon':'mdi:heart-pulse','category':'diagnostic'}
    ]
    publish_topics = {}
    for sensor in sensors:
        payload = get_discovery_payload(config,sensor)
        discovery_topic = f"homeassistant/sensor/{config['host']}/{sensor['id']}/config"
        mqttc.publish(discovery_topic,payload=json.dumps(payload),retain=True)
        publish_topics[sensor['id']] = payload['stat_t']
    publish_topics['availability'] = f"homeassistant/sensor/{config['host']}/availability"
    mqttc.loop_start()
    pulseox = PulseOxHandler(publish_topics, mqttc)
    while True:
        try:
            last_time = datetime.now()
            start_time = datetime.now()
            ble_fail_count = 0
            logging.info(f"BLE: Connecting to device {ble_address}...")
            # Connect to the peripheral
            #peripheral = btle.Peripheral(ble_address, ble_type)
            peripheral.connect(ble_address)
            logging.info(f"BLE: Connected to device {ble_address}")
            # Set the notification delegate
            peripheral.setDelegate(pulseox)
            subscribe_handle = None
            ble_uuid = "0000fff0-0000-1000-8000-00805f9b34fb"

            # this is general magic GATT stuff
            # notify handles will have a UUID that begins with this
            ble_notify_uuid_prefix = "00002902"
            subscribe_bytes = b'\x01\x00'

            # find the desired service
            service = peripheral.getServiceByUUID(ble_uuid)
            if service is not None:
                logging.debug(f"Found service: {service}")
                descs = service.getDescriptors()
                # this is the important part-
                # find the handles that we will write to and subscribe for notifications
                for desc in descs:
                    str_uuid = str(desc.uuid).lower()
                    if str_uuid.startswith(ble_notify_uuid_prefix):
                        subscribe_handle = desc.handle
                        logging.debug(f"*** Found subscribe handle: {subscribe_handle} ({str_uuid})")

            if subscribe_handle is not None:
                # we found the handles that we need
                logging.debug("Found required handle")

                # now that we're subscribed for notifications, waiting for TX/RX...
                logging.info("Reading from device...")
                while True:
                    # this call performs the subscribe for notifications
                    response = peripheral.writeCharacteristic(
                        subscribe_handle, subscribe_bytes, withResponse=True)

                    # this call performs the request for data
                    #response = peripheral.writeCharacteristic(write_handle, write_bytes, withResponse=True)

                    peripheral.waitForNotifications(1.0)
                    time.sleep(ble_read_period)

        except btle.BTLEException as e:
            logging.error(f"BTLEException: {e}")

        except IOError as e:
            logging.error(f"IOError: {e}")

        except KeyboardInterrupt:
            logging.warning("KeyboardInterrupt, exiting")
            pulseox.mqtt_flat()
            sys.exit(1)

        except Exception as e:
            logging.error(f"Exception: {e}")
        finally:
            pulseox.mqtt_flat()

        try:
            pulseox._announce_status('Reconnecting')
            logging.info(f"BLE: Waiting {ble_next_reconnect_delay} seconds to reconnect...")
            time.sleep(ble_next_reconnect_delay)
            ble_next_reconnect_delay = ble_reconnect_delay
        except KeyboardInterrupt:
            logging.warning("KeyboardInterrupt, exiting")
            pulseox.mqtt_flat()
            sys.exit(1)
        except Exception as e:
            logging.error(f"Exception: {e}")
        finally:
            pulseox.mqtt_flat()
