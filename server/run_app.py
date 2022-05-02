import logging
from argparse import ArgumentParser

from kinrec_server.app import KinRecApp
from kinrec_server.internal import ColoredFormatter

logger = logging.getLogger("KRS")
logger.setLevel(logging.DEBUG)
stream_handler = logging.StreamHandler()
stream_handler.setLevel(logging.DEBUG)
stream_handler.setFormatter(ColoredFormatter())
logger.addHandler(stream_handler)

ws_logger = logging.getLogger("websockets")
ws_logger.setLevel(logging.INFO)
ws_logger.addHandler(stream_handler)

# import pydevd_pycharm
# pydevd_pycharm.settrace('192.168.1.41', port=4567, stdoutToServer=True, stderrToServer=True)

if __name__ == "__main__":
    parser = ArgumentParser("Kinect recorder system -- Main server script")
    parser.add_argument("-w", "--workdir", default="./kinrec")
    parser.add_argument("-host", "--hostname", default="192.168.1.40:4400")  # kinrec.cv:4400
    args = parser.parse_args()
    # Create the class
    test_gui = KinRecApp(number_of_kinects=4, workdir=args.workdir, server_address=args.hostname)
    # run the event loop
    test_gui.start()
