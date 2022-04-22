from argparse import ArgumentParser
import logging
from kinrec_recorder.recorder import MainController
from kinrec_recorder.net import NetHandler

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("runner")

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
