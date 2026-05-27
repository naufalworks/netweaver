#!/bin/bash
cd /Users/azfar.naufal/Documents/myhermes
rm -f .tini/daemon_stop .tini/daemon.pid
PYTHONUNBUFFERED=1 python3 -u daemon.py start --mode auto > /tmp/daemon_out2.log 2>&1
echo "DAEMON_EXIT=$?" >> /tmp/daemon_out2.log
