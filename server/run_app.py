import logging
from argparse import ArgumentParser

from kinrec_server.app import KinRecApp

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("run_app_script")

if __name__ == "__main__":
    parser = ArgumentParser("Kinect recorder system -- Main server script")
    parser.add_argument("-w", "--workdir", default="./kinrec")
    parser.add_argument("-h", "--hostname", default="kinrec.cv:4400")
    args = parser.parse_args()
    # Create the class
    test_gui = KinRecApp(number_of_kinects=4, workdir=args.workdir, server_address=args.hostname)
    # run the event loop
    test_gui.start()
