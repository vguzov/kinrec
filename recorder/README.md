# Kinrec recording client
This part is responsible for recording the data from the Azure Kinect camera and sending it to the server. 
It is designed to be run on a laptop with Ubuntu 22.04 with Azure Kinect camera connected. One client controls one camera. 
Several clients can be run on multiple laptops to record from multiple cameras.

## How to deploy the client
Here are the instructions to deploy the client on a laptop with Ubuntu 22.04.
**Note**: desktop version of Ubuntu is used, as Azure Kinect SDK needs OpenGL screen to work, and background context like EGL is not supported, 
which in turn requires X server.

**Step 0.** Install the dependencies:
```bash
sudo apt install -y build-essential git ffmpeg
```

**Step 1.** Install the Azure Kinect SDK. 
Unfortunately, the SDK is only available in the Microsoft repository for Ubuntu 18.04, however, it works fine on Ubuntu 22.04, if installed manually.
To do so, follow the instructions below:
```bash
# Get the .deb files from the Microsoft repository for Ubuntu 18.04
wget https://packages.microsoft.com/ubuntu/18.04/prod/pool/main/libk/libk4a1.4/libk4a1.4_1.4.2_amd64.deb
wget https://packages.microsoft.com/ubuntu/18.04/prod/pool/main/libk/libk4a1.4-dev/libk4a1.4-dev_1.4.2_amd64.deb
# Install the packages
sudo dpkg -i libk4a1.4_1.4.2_amd64.deb
sudo dpkg -i libk4a1.4-dev_1.4.2_amd64.deb
# Install the dependencies, if needed
sudo apt-get install -f
```

**Step 2.** Clone this repository:
```bash
git clone https://github.com/vguzov/kinrec.git
```

**Step 3.** Install the Python dependencies:
Install any conda distribution, e.g., Miniconda, and create a new environment:
```bash
conda conda env create -f kinrec/recorder/conda_env.yml
```

**Step 4.** (Optional) Enable shutdown without password to be able to turn off or reboot the laptop after the recording is finished:
```bash
echo "${USER} ALL=(ALL) NOPASSWD: /usr/sbin/shutdown" | sudo tee -a /etc/sudoers >> /dev/null
```

**Step 5.** Enable autostart of the recording client on boot:
```bash
REPODIR="${HOME}/kinrec" # Folder where the repository is cloned
LOGFILE="${HOME}/kinrec_data/kinrec.log" # Path for log file
STARTSCRIPT="${HOME}/kinrec_data/kinrec_autostart.sh" # Path to store the autostart script
KINREC_RECDIR="${HOME}/kinrec_data" # Directory to store the recordings
KINREC_SERVER="192.168.1.40:4400" # Hostname (with port) of the recording sever
echo -e "[Unit]\nDescription=Kinrec recorder autostart\n[Service]\nUser=${USER}\nWorkingDirectory=$(dirname ${STARTSCRIPT})\nExecStart=${STARTSCRIPT}\nType=simple\nTimeoutStopSec=2\nRestart=always\nRestartSec=3\n[Install]\nWantedBy=multi-user.target\n" | sudo tee /etc/systemd/system/kinrec.service >> /dev/null
mkdir -p "$(dirname ${STARTSCRIPT})"
echo -e "#!/bin/bash\ncd /tmp/.X11-unix && for x in X*; do LAST_DISP=\":\${x#X}\"; done\ncd ${WORKDIR}/kinrec/ \ngit pull \ncd recorder \nDISPLAY=\$LAST_DISP ${WORKDIR}/miniconda/envs/kinrec/bin/python run.py -rd ${KINREC_RECDIR} --logfile ${LOGFILE} --server ${KINREC_SERVER} \n" > "${STARTSCRIPT}"
chmod 755 "${STARTSCRIPT}"
sudo systemctl daemon-reload
sudo systemctl enable kinrec
sudo systemctl start kinrec
```

**Step 6.** Additional setup:
 - (optional) Set computer to ignore lid close (run scripts/lid_nosleep.sh)
 - Turn on "Log in automatically"
 - Turn off "Suspend when on battery"
 - Turn off "Automatic screen lock"
 - (optional) Thinkpads: `apt install tlp tlp-rdw`

**Step 7.** Reboot the laptop to start the recording client:
```bash
sudo reboot
```

## Troubleshooting
If the recording client does not start, check the logs:
```bash
journalctl -u kinrec
# and/or
cat ${LOGFILE}
```

Potential issues:
 - The `DISPLAY` environment variable is not set correctly - try to set it manually in the `kinrec_autostart.sh` script
 - The `kinrec` service is not enabled