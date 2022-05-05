import os
from argparse import ArgumentParser
import logging
from logging.handlers import RotatingFileHandler
from kinrec_recorder.recorder import MainController
from kinrec_recorder.net import NetHandler
from kinrec_recorder.internal import ColoredFormatter

logger = logging.getLogger("KR")
logger.setLevel(logging.INFO)
stream_handler = logging.StreamHandler()

stream_handler.setLevel(logging.INFO)
stream_handler.setFormatter(
    ColoredFormatter(fmt='%(asctime)s:%(name)s:%(levelname)s::: %(message)s', datefmt='%H:%M:%S'))
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
    parser.add_argument("--logfile", default=None)
    parser.add_argument("--logfile_maxsize", type=float, default=20., help="logfile maxsize (in MB)")
    parser.add_argument("--logfile_backups", type=int, default=1, help="logfile backup count")
    parser.add_argument("-s", "--server", default="192.168.1.40:4400", help="Server address and port")

    args = parser.parse_args()

    if args.logfile is not None:
        os.makedirs(os.path.dirname(args.logfile), exist_ok=True)
        file_handler = RotatingFileHandler(args.logfile, mode='a', maxBytes=int(args.logfile_maxsize * 2 ** 20),
                                          backupCount=args.logfile_backups)
        file_formatter = logging.Formatter(fmt='%(asctime)s:%(name)s:%(levelname)s::: %(message)s', datefmt='%H:%M:%S')
        file_handler.setFormatter(file_formatter)
        file_handler.setLevel(logging.INFO)
        logger.addHandler(file_handler)
        ws_logger.addHandler(file_handler)

    logger.info("Starting network")
    net = NetHandler(args.server)
    net.start()
    logger.info("Starting main controller")
    controller = MainController(net_handler=net, recordings_dir=args.recdir)
    controller.main_loop()
