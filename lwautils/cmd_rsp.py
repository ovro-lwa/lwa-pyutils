""" CmdRsp is a class to provide command and response via ETCD.

    >>> # Example using CmdRsp class
    >>>
    >>> import lwautils.cmd_rsp as cr
    >>> try:
    >>>    my_cr = cr.CmdRsp('LWA')
    >>>    my_cr.set_resonse_key('/resp/arx/2')
    >>>    resp_dict = my_cr.send('cmd/arx/2', 'echo', 'abcd')
"""

import sys
import time
import copy
import logging
import datetime
import uuid
from pathlib import Path
from pkg_resources import Requirement, resource_filename
import dsautils.dsa_store as ds
import dsautils.dsa_syslog as dsl
import lwautils.TimeoutException as toe
import lwautils.ServiceNoResponseException as snre

ETCDCONF = resource_filename(Requirement.parse("lwa-pyutils"),
                             "lwautils/conf/etcdConfig.yml")
sys.path.append(str(Path('..')))

# 1 Millisecond
MILLISECONDS = 0.001

# control range of characters to pull out of UUID hash.
MIN_HASH_IDX = 10
MAX_HASH_IDX = 15


class CmdRsp:
    def __init__(self, project: str = ''):
        """c-tor.Provides command and response via ETCD

        Args
        ----
        project
            Project name for logs

        """
        self.my_store = ds.DsaStore(ETCDCONF)

        self.log = dsl.DsaSyslogger(project, 'cmd_rsp', logging.INFO, 'CmdRsp')
        self.log.function('c-tor')
        self.log.info("Created CmdRsp object")
        self.cmd_id = None
        self.response_d = None
        self.response_key = None
        self.user_timeout = 500 * MILLISECONDS

    def _gen_cmd_id(self, ) -> str:
        """Helper to generate a unuque id for command response to ensure
           clients get the correct response for their command.

        Returns
        -------
        str
           A uniq string for use as a command id

        """

        # The id is created by grabbing the current time in ISO8601 format
        # which gives us precision and then appends random chars on it using
        # uuid. The number of chars is specified using MIN_HASH_IDX,
        # MAX_HASH_IDX.
        id0 = datetime.datetime.now().isoformat()
        id0 += '_' + str(uuid.uuid4())[MIN_HASH_IDX:MAX_HASH_IDX]

        return id0

    def _mon_prefix_callback(self, event: list):
        """Handles callbacks for command responses

        The monitor packet must contain the cmd_id.

        Args
        ----
        event
            list containing the etcd_key and dictionary containing response data

        """
        #print('callback: key: {}'.format(event[0]))
        #print('callback: rsp: {}'.format(event[1]))
        if event[0] == self.full_response_key:
            # now look to see if cmd_id matches
            if event[1]['id'] == self.cmd_id:
                self.response_d = event[1]

    def set_response_key(self, resp_key):
        """Set the response key for the command.

        Args
        ----
        resp_key
            The reponse key to watch

        """
        self.response_key = resp_key

    def send(self,
             key: str,
             cmd: str,
             val: any = '',
             timeout: int = 500 * MILLISECONDS) -> list:
        """Send command and payload to etcd.

        Note
        ----
        This function uses the following command structure to interact
        with a service connected to Etcd.
        cmd_d = {'cmd': <cmd>, 'val': <val>, 'id': <cmd_id>}

        The service will rspond with at least the same <cmd_id> of the form:
        resp_d = {'id': <cmd_id>, ...}

        Args
        ----
        key
           Etcd key
        cmd
            A command understood by receiving object
        val
            Optional args for command.
        timeout
            Optional user timeoute for command. Defaults to 500ms
     
        Returns
        -------
        list
           contains the response key and response dictionary.

        """
        self.cmd_id = self._gen_cmd_id()
        self.full_response_key = self.response_key + '-' + self.cmd_id
        self.response_d = None
        cmd_dict = {}
        cmd_dict['cmd'] = cmd
        cmd_dict['id'] = self.cmd_id
        cmd_dict['respkey'] = self.full_response_key
        val_dict = {}
        if isinstance(val, dict):
            val_dict = copy.deepcopy(val)
        else:
            val_dict['val'] = str(val)
        cmd_dict['val'] = val_dict

        watch_id = self.my_store.add_watch_prefix(self.full_response_key,
                                                  self._mon_prefix_callback)
        self.my_store.put_dict(key, cmd_dict)

        # now wait for dictionary to get populated by callback
        user_timeout_count = 0
        user_timeout_count_max = timeout / (10 * MILLISECONDS)
        while self.response_d is None and user_timeout_count < user_timeout_count_max:
            time.sleep(10 * MILLISECONDS)
            user_timeout_count += 1

        self.my_store.cancel(watch_id)

        if cmd != 'rset' and self.response_d is None:
            # get data via Get
            try:
                self.response_d = self.my_store.get_dict(self.full_response_key)
                if self.response_d is None:
                    raise snre.ServiceNoResponseException()
                self.my_store.delete(self.full_response_key)
                return self.response_d
            except:
                # Oops, no response from service and user_timeout reached
                raise snre.ServiceNoResponseException()
        else:
            self.my_store.delete(self.full_response_key)
            return self.response_d
