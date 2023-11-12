import sys
import socket
import time
import signal
import numpy as np
import os
from threading import Thread

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QApplication, QMainWindow, QLabel, QVBoxLayout, QWidget
from PyQt6.QtGui import QPixmap

from stimpack.util import ROOT_DIR

# Define the host and port for the receiver
LOCAL_HOST = '127.0.0.1'  # Change this to the receiver's IP address
DEFAULT_PORT = 33335  # Change this to the receiver's port

class KeyTrac(QMainWindow):
    def __init__(self, host=LOCAL_HOST, port=DEFAULT_PORT, relative_control=True, verbose=False):
        super().__init__()
        self.host = host
        self.port = port
        self.relative_control = relative_control
        self.verbose = verbose

        # Create a socket and connect to the receiver
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM) # UDP
        self.sock.settimeout(0)
        # self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM) # TCP
        # self.sock.connect((self.host, self.port))

        self.key_count = 0
        self.pos = {"x": 0, "y": 0, "z":0, "theta": 0, "phi": 0, "roll": 0}
        if self.relative_control:
            self.step = {"forward": 0.01, "right": 0.01, "up":0.01, "theta": np.pi/16, "phi": np.pi/16, "roll": np.pi/16} # in m and radians
        else:
            self.step = {"x": 0.01, "y": 0.01, "z":0.01, "theta": np.pi/16, "phi": np.pi/16, "roll": np.pi/16} # in m and radians

        self.initUI()

        # Send state messages periodically, in addition to when a key is pressed
        self.send_state_timer = QTimer()
        self.send_state_timer.timeout.connect(self.send_state_message)
        self.send_state_timer.start(500) # in ms

        # Receive messages on a loop using Thread
        self.receiving = True
        self.receive_thread = Thread(target=self.receive_loop)
        self.receive_thread.start()

    def initUI(self):
        # self.setGeometry(100, 100, 400, 300)
        self.setWindowTitle(f"KeyTrac (Host: {self.host}, Port: {self.port}))")

        central_widget = QWidget(self)
        self.setCentralWidget(central_widget)

        layout = QVBoxLayout(central_widget)

        # Load an image using QPixmap
        pixmap = QPixmap(os.path.join(ROOT_DIR, "device/locomotion/keytrac/keytrac_map.png"))

        if not pixmap.isNull():
            label = QLabel()
            label.setPixmap(pixmap)
            label.setScaledContents(True)  # Allow the image to be scaled when resizing
            layout.addWidget(label)
    
    def handle_key_absolute_control(self, key):
        if key == Qt.Key.Key_Left:
            key_description = "left: theta,phi,roll step /= 2"
            self.step["theta"] /= 2
            self.step["phi"] /= 2
            self.step["roll"] /= 2
        elif key == Qt.Key.Key_Right:
            key_description = "right: theta,phi,roll step *= 2"
            self.step["theta"] *= 2
            self.step["phi"] *= 2
            self.step["roll"] *= 2
        elif key == Qt.Key.Key_Up:
            key_description = "up: xyz step *= 2"
            self.step["x"] *= 2
            self.step["y"] *= 2
            self.step["z"] *= 2
        elif key == Qt.Key.Key_Down:
            key_description = "down: xyz step /= 2"
            self.step["x"] /= 2
            self.step["y"] /= 2
            self.step["z"] /= 2
        elif key == Qt.Key.Key_Y:
            key_description = "Y: z+"
            self.pos["z"] += self.step["z"]
        elif key == Qt.Key.Key_H:
            key_description = "H: z-"
            self.pos["z"] -= self.step["z"]
        elif key == Qt.Key.Key_U:
            key_description = "U: phi+"
            self.pos["phi"] += self.step["phi"]
        elif key == Qt.Key.Key_J:
            key_description = "J: phi-"
            self.pos["phi"] -= self.step["phi"]
        elif key == Qt.Key.Key_I:
            key_description = "I: roll+"
            self.pos["roll"] += self.step["roll"]
        elif key == Qt.Key.Key_K:
            key_description = "K: roll-"
            self.pos["roll"] -= self.step["roll"]
        elif key == Qt.Key.Key_W:
            key_description = "W: y+"
            self.pos["y"] += self.step["y"]
        elif key == Qt.Key.Key_S:
            key_description = "S: y-"
            self.pos["y"] -= self.step["y"]
        elif key == Qt.Key.Key_A:
            key_description = "A: x-"
            self.pos["x"] -= self.step["x"]
        elif key == Qt.Key.Key_D:
            key_description = "D: x+"
            self.pos["x"] += self.step["x"]
        elif key == Qt.Key.Key_Q:
            key_description = "Q: theta+"
            self.pos["theta"] += self.step["theta"]
        elif key == Qt.Key.Key_E:
            key_description = "E: theta-"
            self.pos["theta"] -= self.step["theta"]
        else:
            if self.verbose:
                print(f"Key {key} not recognized.")
            return

        self.key_count += 1

        return key_description
    
    def handle_key_relative_control(self, key):
        # Incomplete implementation for phi and roll
        if key == Qt.Key.Key_Left:
            key_description = "left: rotation step /= 2"
            self.step["theta"] /= 2
            self.step["phi"] /= 2
            self.step["roll"] /= 2
        elif key == Qt.Key.Key_Right:
            key_description = "right: rotation step *= 2"
            self.step["theta"] *= 2
            self.step["phi"] *= 2
            self.step["roll"] *= 2
        elif key == Qt.Key.Key_Up:
            key_description = "up: translation step *= 2"
            self.step["forward"] *= 2
            self.step["right"] *= 2
            self.step["up"] *= 2
        elif key == Qt.Key.Key_Down:
            key_description = "down: translation step /= 2"
            self.step["forward"] /= 2
            self.step["right"] /= 2
            self.step["up"] /= 2
        elif key == Qt.Key.Key_Y:
            key_description = "Y: up"
            self.pos["z"] += self.step["up"]
        elif key == Qt.Key.Key_H:
            key_description = "H: down"
            self.pos["z"] -= self.step["up"]
        elif key == Qt.Key.Key_U:
            key_description = "U: turn up"
            self.pos["phi"] += self.step["phi"]
        elif key == Qt.Key.Key_J:
            key_description = "J: turn down"
            self.pos["phi"] -= self.step["phi"]
        elif key == Qt.Key.Key_I:
            key_description = "I: roll right"
            self.pos["roll"] += self.step["roll"]
        elif key == Qt.Key.Key_K:
            key_description = "K: roll left"
            self.pos["roll"] -= self.step["roll"]
        elif key == Qt.Key.Key_W:
            key_description = "W: forward"
            self.pos["x"] -= self.step["forward"] * np.sin(self.pos["theta"])
            self.pos["y"] += self.step["forward"] * np.cos(self.pos["theta"])
        elif key == Qt.Key.Key_S:
            key_description = "S: backward"
            self.pos["x"] += self.step["forward"] * np.sin(self.pos["theta"])
            self.pos["y"] -= self.step["forward"] * np.cos(self.pos["theta"])
        elif key == Qt.Key.Key_A:
            key_description = "A: left"
            self.pos["x"] -= self.step["right"] * np.cos(self.pos["theta"])
            self.pos["y"] -= self.step["right"] * np.sin(self.pos["theta"])
        elif key == Qt.Key.Key_D:
            key_description = "D: right"
            self.pos["x"] += self.step["right"] * np.cos(self.pos["theta"])
            self.pos["y"] += self.step["right"] * np.sin(self.pos["theta"])
        elif key == Qt.Key.Key_Q:
            key_description = "Q: turn left"
            self.pos["theta"] += self.step["theta"]
        elif key == Qt.Key.Key_E:
            key_description = "E: turn right"
            self.pos["theta"] -= self.step["theta"]
        else:
            if self.verbose:
                print(f"Key {key} not recognized.")
            return

        self.key_count += 1

        return key_description

    def construct_state_message(self, key_description=None):
        if key_description is None:
            key_description = "No key pressed"
        timestamp = time.time()
        message = f"KT, {self.key_count}, {key_description}, " + \
                    f"{self.pos['x']}, {self.pos['y']}, {self.pos['z']}, {self.pos['theta']}, {self.pos['phi']}, {self.pos['roll']}, " + \
                    f"{timestamp}\n"
        return message

    def send_state_message(self, key_description=None):
        message = self.construct_state_message(key_description)

        try:
            self.sock.sendto(message.encode(), (self.host, self.port)) # UDP
        except:
            print("Failed to send message.")
            return
        # self.sock.sendall(message.encode()) # TCP

    def receive_message(self):
        # Receive a message from the receiver
        try:
            data, addr = self.sock.recvfrom(1024)
            message = data.decode()
        except socket.timeout as e:
            print(e)
            return
        except socket.error as e:
            # print(e)
            return

        if message == "reset_pos":
            self.reset_position()

    def receive_loop(self):
        while self.receiving:
            self.receive_message()

    def reset_position(self):
        self.pos = {"x": 0, "y": 0, "z":0, "theta": 0, "phi": 0, "roll": 0}

    def keyPressEvent(self, event):
        if self.relative_control:
            key_description = self.handle_key_relative_control(event.key())
        else:
            key_description = self.handle_key_absolute_control(event.key())
        
        # Send the key press description and the current position
        self.send_state_message(key_description)

        if self.verbose:
            print(f"Pressed {key_description}")
            print(f"Current position: {self.pos}")
            print(f"Current step size: {self.step}")

    def closeEvent(self, event):
        # Close the socket
        print("Closing socket...")
        self.receiving = False
        self.sock.close()
    
    def sigint_handler(self, signal, frame):
        print("SIGINT received.")
        self.closeEvent(None)
        print("Exiting...")
        sys.exit(0)

def main():
    host = LOCAL_HOST
    port = DEFAULT_PORT
    relative_control = True
    verbose = False
    if len(sys.argv) > 1:
        host = sys.argv[1]
    if len(sys.argv) > 2:
        port = int(sys.argv[2])
    if len(sys.argv) > 3:
        relative_control = bool(sys.argv[3])
    if len(sys.argv) > 4:
        verbose = bool(sys.argv[4])

    app = QApplication(sys.argv)
    window = KeyTrac(host=host, port=port, relative_control=relative_control, verbose=verbose)
    window.show()

    # Set up a SIGINT (Ctrl+C) signal handler
    signal.signal(signal.SIGINT, window.sigint_handler)
    # signal.signal(signal.SIGINT, signal.SIG_DFL)

    # Create a QTimer to periodically trigger an event in the event loop, so Ctrl+C can be handled
    timer = QTimer()
    timer.timeout.connect(lambda: None)  # Empty lambda function
    timer.start(1000)

    sys.exit(app.exec())

if __name__ == "__main__":
    main()