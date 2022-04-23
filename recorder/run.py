from argparse import ArgumentParser
import logging
from kinrec_recorder.recorder import MainController
from kinrec_recorder.net import NetHandler

logger = logging.getLogger("KR")
logger.setLevel(logging.INFO)
stream_handler = logging.StreamHandler()

stream_handler.setLevel(logging.INFO)
stream_handler.setFormatter(logging.Formatter('%(asctime)s:%(name)s:%(levelname)s::: %(message)s',
                                              datefmt='%H:%M:%S'))
logger.addHandler(stream_handler)

ws_logger = logging.getLogger("websockets")
ws_logger.setLevel(logging.INFO)
ws_logger.addHandler(stream_handler)

# import pydevd_pycharm
# pydevd_pycharm.settrace('192.168.1.41', port=4567, stdoutToServer=True, stderrToServer=True)

if __name__ == "__main__":
    parser = ArgumentParser("Kinect recorder")
    parser.add_argument("-rd", "--recdir", default="kinrec/recordings",
                        help="Folder where all the recordings are stored")
    parser.add_argument("-s", "--server", default="192.168.1.40:4400", help="Server address and port")

    args = parser.parse_args()
    logger.info("Starting network")
    net = NetHandler(args.server)
    net.start()
    logger.info("Starting main controller")
    controller = MainController(net_handler=net, recordings_dir=args.recdir)
    controller.main_loop()
