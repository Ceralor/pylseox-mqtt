import time, os, sys
from bluepy import btle
from datetime import datetime
#from multiprocessing import Process, Queue
from dotenv import dotenv_values
import paho.mqtt.client as mqtt
import json

class ReadDelegate(btle.DefaultDelegate):
    def __init__(self):
        btle.DefaultDelegate.__init__(self)

    def handleNotification(self, handle, data):
        global ble_fail_count
        global ble_next_reconnect_delay
        global packets_by_type
        global mqttc
        #global q
        try:
            if len(data) == 7 and data[0] == 241:
                ble_fail_count = 0
                #q.put(data)
                calibrating = False
                if data[1] == 127:
                    calibrating = True
                    mqttc.publish('pulseox/status','calibrating')
                    print("Calibrating...")
                else:
                    print(f"SpO2: {data[1]}% \tBPM: {data[2]} \tPI: {data[4]/10.0}%")
                    mqttc.publish('pulseox/spo2',data[1])
                    mqttc.publish('pulseox/bpm',data[2])
                    mqttc.publish('pulseox/pi',data[4]/10.0)
                    if calibrating == True:
                        calibrating = False
                        mqttc.publish('pulseox/status','reading')
                if ble_fail_count >= (ble_inactivity_timeout / ble_read_period):
                    # disconnect from device to conserve power
                    print("BLE: Inactivity timeout, disconnecting...")
                    ble_fail_count = 0
                    ble_next_reconnect_delay = ble_inactivity_delay
                    peripheral.disconnect()
            elif data[0] == 240:
                ble_fail_count = 0
                mqttc.publish('pulseox/ppg',json.dumps([x for x in data[1:-1]]))
        except Exception as e:
            print(f"Data Handler Exception: {e}")

if __name__ == "__main__":
    config = dotenv_values()

    # ble config params
    # ble address of device
    ble_address = config['ble_address']
    # seconds to wait between reads
    ble_read_period = 2
    # seconds to wait between btle reconnection attempts
    ble_reconnect_delay = 10
    # seconds of btle inactivity (not worn/calibrating) before force-disconnect
    ble_inactivity_timeout = 300
    # seconds to wait after inactivity timeout before reconnecting resumes
    ble_inactivity_delay = 130
    packets_by_type = {}
    # mqtt config params

    # other params
    ble_next_reconnect_delay = ble_reconnect_delay
    ble_fail_count = 0
    mqttc = mqtt.Client()
    mqttc.username_pw_set(config['mqtt_user'],config['mqtt_pass'])
    mqttc.connect(config['mqtt_host'])
    peripheral = btle.Peripheral()
    mqttc.loop_start()
    while True:
        try:
            last_time = datetime.now()
            start_time = datetime.now()
            ble_fail_count = 0
            print(f"BLE: Connecting to device {ble_address}...")
            # Connect to the peripheral
            #peripheral = btle.Peripheral(ble_address, ble_type)
            peripheral.connect(ble_address)
            print(f"BLE: Connected to device {ble_address}")
            # Set the notification delegate
            peripheral.setDelegate(ReadDelegate())
            subscribe_handle = None
            ble_uuid = "0000fff0-0000-1000-8000-00805f9b34fb"

            # this is general magic GATT stuff
            # notify handles will have a UUID that begins with this
            ble_notify_uuid_prefix = "00002902"
            subscribe_bytes = b'\x01\x00'

            # find the desired service
            service = peripheral.getServiceByUUID(ble_uuid)
            if service is not None:
                print(f"Found service: {service}")
                descs = service.getDescriptors()
                # this is the important part-
                # find the handles that we will write to and subscribe for notifications
                for desc in descs:
                    str_uuid = str(desc.uuid).lower()
                    if str_uuid.startswith(ble_notify_uuid_prefix):
                        subscribe_handle = desc.handle
                        print(f"*** Found subscribe handle: {subscribe_handle} ({str_uuid})")

            if subscribe_handle is not None:
                # we found the handles that we need
                print("Found required handle")

                # now that we're subscribed for notifications, waiting for TX/RX...
                print("Reading from device...")
                while True:
                    # this call performs the subscribe for notifications
                    response = peripheral.writeCharacteristic(
                        subscribe_handle, subscribe_bytes, withResponse=True)

                    # this call performs the request for data
                    #response = peripheral.writeCharacteristic(write_handle, write_bytes, withResponse=True)

                    peripheral.waitForNotifications(1.0)
                    time.sleep(ble_read_period)

        except btle.BTLEException as e:
            print(f"BTLEException: {e}")

        except IOError as e:
            print(f"IOError: {e}")

        except KeyboardInterrupt:
            print("KeyboardInterrupt, exiting")
            sys.exit()

        except Exception as e:
            print(f"Exception: {e}")

        try:
            print(f"BLE: Waiting {ble_next_reconnect_delay} seconds to reconnect...")
            time.sleep(ble_next_reconnect_delay)
            ble_next_reconnect_delay = ble_reconnect_delay
        except KeyboardInterrupt:
            print("KeyboardInterrupt, exiting")
            sys.exit()
        except Exception as e:
            print(f"Exception: {e}")
