from machine import ADC, Pin
from time import sleep
import logging
import network
import socket
import struct
import uasyncio as asyncio

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

SSID = "roverc.pro"
PASS = "roverc.pro" # we don't really care
REMOTE = "192.168.4.1"
PORT = 1234
COUNT_MAX = 0xFFFFFFFF
U16_MAX = 0xFFFF
UPDATE_FREQ = 0.01

JOY_X_PIN = 1
JOY_Y_PIN = 2
JOY_BTN_PIN = 47

connected = asyncio.Event()

class Joy:
    def __init__(self, x_pin: int = JOY_X_PIN, y_pin: int = JOY_Y_PIN, btn_pin: int = JOY_BTN_PIN):
        self.x = ADC(Pin(x_pin))
        self.y = ADC(Pin(y_pin))
        self.btn = Pin(btn_pin, Pin.IN, Pin.PULL_UP)

        self.x.width(ADC.WIDTH_12BIT)
        self.y.width(ADC.WIDTH_12BIT)
        self.x.atten(ADC.ATTN_11DB)
        self.y.atten(ADC.ATTN_11DB)
        self.x_min = 0
        self.y_min = 0

    @property
    def angle(self) -> tuple[int, int]:
        x = self.x.read_u16()
        y = self.y.read_u16()

        x = mapn(x, self.x_min, 65535, -127, 127)
        y = mapn(y, self.y_min, 65535, -127, 127)

        return int(x), int(y)

    @property
    def pressed(self) -> bool:
        return not self.btn.value()

    def calibrate(self):
        print("Calibrating joystick...")
        print("> Place the joystick in the center")
        cal_x, cal_y = 0, 0
        sleep(2.5)

        print(">> Calibrating center", end=" ")
        for i in range(100):
            cal_x += self.x.read_u16()
            sleep(0.005)
            cal_y += self.y.read_u16()
            sleep(0.005)
            if i % 20 == 0:
                print(".", end=" ")

        print()
        x_center, y_center = cal_x / 100, cal_y / 100
        print(f">>! Correction X: {x_center}")
        print(f">>! Correction Y: {y_center}")

        # bottom-left
        x_min, y_min = 0, 0
        print("> Place the joystick in the bottom-left corner")
        sleep(2.5)
        print(">> Calibrating bottom-left", end=" ")
        for i in range(100):
            x_min += self.x.read_u16()
            sleep(0.005)
            y_min += self.y.read_u16()
            sleep(0.005)
            if i % 20 == 0:
                print(".", end=" ")

        x_min /= 100
        y_min /= 100

        print()
        print(f">>! X: {x_min}")
        print(f">>! Y: {y_min}")

        # top-right

        x_max, y_max = 0, 0
        print("> Place the joystick on the top-right corner")
        sleep(2.5)
        print(">> Calibrating top-right", end=" ")
        for i in range(100):
            x_max += self.x.read_u16()
            sleep(0.005)
            y_max += self.y.read_u16()
            sleep(0.005)
            if i % 20 == 0:
                print(".", end=" ")

        x_max /= 100
        y_max /= 100

        print()
        print(f">>! X: {x_max}")
        print(f">>! Y: {y_max}")

        if x_max < x_min:
            x_max, x_min = x_min, x_max

        if y_max < y_min:
            y_max, y_min = y_min, y_max

        print(f"X range: [{x_min}, {x_max}]")
        print(f"Y range: [{y_min}, {y_max}]")


def mapn(x, in_min, in_max, out_min, out_max):
    return (x - in_min) * (out_max - out_min) / (in_max - in_min) + out_min


async def conn_task():
    sta_if = network.WLAN(network.WLAN.IF_STA)
    sta_if.ipconfig(gw4="192.168.4.1", addr4="192.168.4.2/24")
    while True:
        while sta_if.isconnected():
            await connected.set()
            # refresh every 500 ms
            asyncio.sleep(0.5)

        await connected.clear()
        logging.warning("Disconnection detected!")
        sta_if.active(False)
        sta_if.active(True)
        sta_if.connect(SSID, PASS)
        # wait until connection happens
        while not sta_if.isconnected():
            ...
        await connected.set()


async def main():
    joy = Joy()
    #joy.calibrate()
    
    # launch the connection thread
    conn_task_obj = asyncio.create_task(conn_task())
    
    # wait for connection to happen
    await connected.wait()
    
    # Create a socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.connect((REMOTE, PORT))
    
    count = 0
    last_x, last_y, last_btn_state = -128, -128, False
    while await connected.wait():
        x, y = joy.angle
        logging.debug("X: %d, Y: %d", x, y)
        pressed = joy.pressed
        if x == last_x and y == last_y and pressed == last_btn_state:
            asyncio.sleep(UPDATE_FREQ)
            continue
    
        last_x, last_y, last_btn_state = x, y, pressed
        try:
            ret = sock.send(struct.pack("!IbbB", count, x, y, pressed))
            assert ret == 7, f"Send failed: {ret}"
            logging.debug("datagram sent")
        except OSError as e:
            logging.warning("error when sending datagram: %s", e)
        finally:
            count = (count + 1) % COUNT_MAX
            if count == 0:
                logging.info("Count reset")
            asyncio.sleep(UPDATE_FREQ)

    await conn_task_obj

asyncio.run(main())
