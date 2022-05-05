#!/bin/bash

echo "HandleLidSwitch=ignore" | sudo tee -a /etc/systemd/logind.conf >> /dev/null
echo "Lid close will be ignored after restart"