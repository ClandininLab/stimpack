import sys
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QMainWindow, QLabel, QVBoxLayout, QWidget
from PyQt6.QtGui import QPixmap
import socket
import time
import signal
import numpy as np

# Define the host and port for the receiver
LOCAL_HOST = '127.0.0.1'  # Change this to the receiver's IP address
DEFAULT_PORT = 33335  # Change this to the receiver's port

class KeyTrac(QMainWindow):
    def __init__(self, host=LOCAL_HOST, port=DEFAULT_PORT):
        super().__init__()
        self.host = host
        self.port = port

        # Create a socket and connect to the receiver
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM) # UDP

        # self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM) # TCP
        # self.sock.connect((self.host, self.port))

        self.key_count = 0
        self.pos = {"x": 0, "y": 0, "z":0, "theta": 0}
        self.step = {"x": 0.01, "y": 0.01, "z":0.01, "theta": np.pi/16} # in m and radians

        self.initUI()

    def initUI(self):
        # self.setGeometry(100, 100, 400, 300)
        self.setWindowTitle(f"KeyTrac (Host: {self.host}, Port: {self.port}))")

        central_widget = QWidget(self)
        self.setCentralWidget(central_widget)

        layout = QVBoxLayout(central_widget)

        # Load an image using QPixmap
        pixmap = QPixmap("keytrac_map.png")

        if not pixmap.isNull():
            label = QLabel()
            label.setPixmap(pixmap)
            label.setScaledContents(True)  # Allow the image to be scaled when resizing
            layout.addWidget(label)
    
    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Left:
            key_pressed = "left: theta step /= 2"
            self.step["theta"] /= 2
        elif event.key() == Qt.Key.Key_Right:
            key_pressed = "right: theta step *= 2"
            self.step["theta"] *= 2
        elif event.key() == Qt.Key.Key_Up:
            key_pressed = "up: xyz step *= 2"
            self.step["x"] *= 2
            self.step["y"] *= 2
            self.step["z"] *= 2
        elif event.key() == Qt.Key.Key_Down:
            key_pressed = "down: xyz step /= 2"
            self.step["x"] /= 2
            self.step["y"] /= 2
            self.step["z"] /= 2
        elif event.key() == Qt.Key.Key_PageUp:
            key_pressed = "pageup: up"
            self.pos["z"] += self.step["z"]
        elif event.key() == Qt.Key.Key_PageDown:
            key_pressed = "pagedown: down"
            self.pos["z"] -= self.step["z"]
        elif event.key() == Qt.Key.Key_W:
            key_pressed = "W: forward"
            self.pos["y"] += self.step["y"]
        elif event.key() == Qt.Key.Key_S:
            key_pressed = "S: backward"
            self.pos["y"] -= self.step["y"]
        elif event.key() == Qt.Key.Key_A:
            key_pressed = "A: left"
            self.pos["x"] -= self.step["x"]
        elif event.key() == Qt.Key.Key_D:
            key_pressed = "D: right"
            self.pos["x"] += self.step["x"]
        elif event.key() == Qt.Key.Key_Q:
            key_pressed = "Q: turn left"
            self.pos["theta"] += self.step["theta"]
        elif event.key() == Qt.Key.Key_E:
            key_pressed = "E: turn right"
            self.pos["theta"] -= self.step["theta"]
        else:
            return

        self.key_count += 1
        timestamp = time.time()

        message = f"KT, {self.key_count}, {key_pressed}, " + \
                    f"{self.pos['x']}, {self.pos['y']}, {self.pos['z']}, {self.pos['theta']}, " + \
                    f"{timestamp}\n"

        # Send the key press information
        try:
            self.sock.sendto(message.encode(), (self.host, self.port)) # UDP
        except:
            print("Failed to send message.")
            return
        # self.sock.sendall(message.encode()) # TCP

        print(f"Pressed {key_pressed}")
        print(f"Current position: {self.pos}")
        print(f"Current step size: {self.step}")

    def closeEvent(self, event):
        # Close the socket
        print("Closing socket...")
        self.sock.close()
    
def sigint_handler(signal, frame):
    sys.exit(0)

def main():
    host = LOCAL_HOST
    port = DEFAULT_PORT
    if len(sys.argv) > 1:
        host = sys.argv[1]
    if len(sys.argv) > 2:
        port = int(sys.argv[2])

    app = QApplication(sys.argv)
    window = KeyTrac(host=host, port=port)
    window.show()

    # Set up a SIGINT (Ctrl+C) signal handler
    # signal.signal(signal.SIGINT, sigint_handler)
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    sys.exit(app.exec())

if __name__ == "__main__":
    main()