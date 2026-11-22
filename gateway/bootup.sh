#!/bin/sh
# Place at the SD-card root. /etc/init.d/S99bootdone runs it as root at boot.
# Opens a passwordless root shell over the network. Remove the card = stock.
telnetd -l /bin/sh -p 2323 &
exit 0
