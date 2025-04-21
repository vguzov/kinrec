# Kinrec recording server

This server provides a GUI for controlling the Kinect recorders. 

Capabilities:
- Start/stop recording
- Set recording parameters
- Preview the color/depth images
- Download/delete the recordings from all recorders

### Initial setup
Rename `kinrec/params.toml.example` to `kinrec/params.toml`, enter the id of each Kinect and assign a number (alias) that will be used to identify the Kinect in the GUI.
The id is the serial number of the Kinect, which can be found in the Azure Kinect Viewer.

### Run the server
```bash
python run_app.py --workdir <path to params and recordings> --host <ip:port> -n <number of recorders>
```