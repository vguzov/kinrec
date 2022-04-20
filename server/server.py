import toml
import os
import logging
from argparse import ArgumentParser
from copy import deepcopy

from kinrec_server.controller import MainController
from kinrec_server.parameters import default_parameters

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("server_script")

parser = ArgumentParser("Kinect recorder system -- Main server script")
parser.add_argument("-w", "--workdir", default="./kinrec")
parser.add_argument("-h", "--hostname", default="kinrec.cv:4400")

args = parser.parse_args()

os.makedirs(args.workdir, exist_ok=True)
params_path = os.path.join(args.workdir, "params.toml")
if os.path.isfile(params_path):
    parameters_dict = toml.load(open(params_path))
else:
    parameters_dict = deepcopy(default_parameters)
    toml.dump(parameters_dict, open(params_path, "w"))

main_controller = MainController(args.hostname)
main_controller.start()


