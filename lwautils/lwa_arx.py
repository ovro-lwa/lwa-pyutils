""" ARX is a class to encapsulate controlling a LWA ARX board.

    >>> # Example using ARX class
    >>>
    >>> import lwautils.lwa_arx as arx
    >>> arx2 = arx.ARX(2)
    >>> arx2.temp()
    >>> arx2.arxn()
    >>> arx2.echo("abcdef")
"""

import sys
import time
import logging
from pathlib import Path
from pkg_resources import Requirement, resource_filename
import dsautils.dsa_store as ds
import dsautils.dsa_syslog as dsl
ETCDCONF = resource_filename(Requirement.parse("lwa-pyutils"),
                             "lwautils/conf/etcdConfig.yml")
sys.path.append(str(Path('..')))

CMD_KEY_BASE = '/cmd/arx/'
MON_KEY_BASE = '/mon/arx/'
# wait for arx board to exec and push to etcd.
CMD_TIMEOUT = 0.15


class ARX:
    """Class encapsulates controlling LWA ARX board.
    """

    def __init__(self, arx_num):
        """c-tor. Specify ARX addres. Use 0 for all ARX boards

        :param arx_num: ARX board address or list of ARX to control. 0 for all.
        :type arx_num: Integer or Array of Integers. [0-255]
        """
        self.arx_nums = []
        # Test contructor
        if isinstance(arx_num, list):
            self.arx_nums = arx_num
        else:
            self.arx_nums.append(arx_num)

        self.my_store = ds.DsaStore(ETCDCONF)
        self.cmd_key_base = CMD_KEY_BASE
        self.mon_key_base = MON_KEY_BASE
        self.log = dsl.DsaSyslogger('dsa', 'arx', logging.INFO, 'Arx')
        self.log.function('c-tor')
        self.log.info("Created Arx object")

    def _send(self, cmd):
        """Private helper to send command dictionary to arx board.

        :param cmd: Dictionary containing arx board command.
        :type cmd: Dictionary
        """

        self.my_store.put_dict(self.key, cmd)

    def _get(self, key):
        """Private helper to get dictionary for an arx board.

        :param key : Monitor key for ARX board(i.e. /mon/arx/2).
        :type key: String
        """

        return self.my_store.get_dict(key)

    def _sendreceive(self, cmd, val = ''):
        """Private helper to send and receive cmds from ARX boards

        :param cmd: Command to send
        :param val: Optional arguments for command
        :type cmd: String
        :type val: String
        """
        cmd = {}
        cmd['cmd'] = cmd
        cmd['val'] = val
        rtn = []
        for arx_num in arx_nums:
            self.key = "CMD_KEY_BASE{}".format(arx_num)
            self._send(cmd)
            # wait 150ms for command to be executed
            time.sleep(CMD_TIMEOUT)
            mon_key = "MON_KEY_BASE{}".format(arx_num)
            arx_d = _get(mon_key)
            rtn.append(arx_d[cmd])
        return rtn
        
    def arxn(self):
        """Return ARX board ID.
        """
        return self._sendreceive('arxn')

    def temp(self):
        """Return ARX board temperature in C.
        """
        return self._sendreceive('temp')

    def echo(self, val):
        """Return echoed val.
        """
        return self._sendreceive('echo', val)
    
