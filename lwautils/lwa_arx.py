""" ARX is a class to encapsulate controlling LWA ARX boards.

    >>> # Example using ARX class
    >>>
    >>> import lwautils.lwa_arx as arx
    >>> import lwautils.ArxException as arxe
    >>> brd_addr = 2
    >>> try:
    >>>    my_arx = arx.ARX()
    >>>    mc_temp = my_arx.get_microcontroller_temp(brd_addr)
    >>>    # return channel config for channel 0
    >>>    chan = 0
    >>>    cfg = my_arx.get_chan_cfg(brd_addr, chan)
    >>>    print(cfg)
    >>>    {'sig_on': False, 'narrow_lpf': False, 'narrow_hpf': False,
    >>>     'first_atten': 0.0, 'second_atten': 0.0, 'dc_on': False}
    >>>    # Set first_atten to 3.5dB using above cfg dictionary for channel 0
    >>>    cfg['first_atten'] = 3.5
    >>>    my_arx.set_chan_cfg(brd_addr, chan, cfg)
    >>> except arxe.ArxException as ae:
    >>>     print(ae)
"""

import sys
import time
import logging
import json
from pathlib import Path
from pkg_resources import Requirement, resource_filename
import dsautils.dsa_store as ds
import dsautils.dsa_syslog as dsl
import lwautils.ArxException as ARXE
import lwautils.cmd_rsp as cr
ETCDCONF = resource_filename(Requirement.parse("lwa-pyutils"),
                             "lwautils/conf/etcdConfig.yml")
sys.path.append(str(Path('..')))

CMD_KEY_BASE = '/cmd/arx/'
MON_KEY_BASE = '/mon/arx/'
RESP_KEY_BASE = '/resp/arx/'
MILLISECONDS = .001
# wait for arx board to exec and push to etcd.
CMD_TIMEOUT = 0.15  # seconds
USER_TIMEOUT = 500 * MILLISECONDS
ONEWIRE_TEMP_TIMEOUT = 1200 * MILLISECONDS

# Required channel configuration keys
SIG_ON = 'sig_on'
NARROW_LPF = 'narrow_lpf'
NARROW_HPF = 'narrow_hpf'
FIRST_ATTEN = 'first_atten'
SECOND_ATTEN = 'second_atten'
DC_ON = 'dc_on'
REQ_CONFIG_KEYS = [
    SIG_ON, NARROW_LPF, NARROW_HPF, FIRST_ATTEN, SECOND_ATTEN, DC_ON
]

# attenuations in units of 0.5dB
ATTEN_SCALE = 0.5
MIN_ATTENUATION = 0
MAX_ATTENUATION = 63

# Time between polling for command to show up.
TEN_ms = 0.010

# Maximum number of analog channels on ARX board
MAX_CHAN = 16
MIN_CHAN = 0

BRD_ID_LEN = 4

# the scale is (2.0 A/V)*(.004 V/count) = 8 mA per ADC count.
BOARD_MA_PER_COUNT = 8.0
MIN_BOARD_CURRENT_MA = 0
# check this value
MAX_BOARD_CURRENT_MA = 5000

# millivolt/count
MVOLT_PER_COUNT = 4
# coax milliamp/volt conversion factor
COAX_MA_PER_VOLT = 100
# fiber milliamp/volt conversion factor
FIBER_MA_PER_VOLT = 1

# for converstion of chan ADC counts to power
PWR_COUNTS_PER_VOLT = 2.296
PWR_LOAD_OHMS = 50.0
MIN_PWR_COUNT = 0
# check this value
MAX_PWR_COUNT = 4095

# Maximum memory location for stored configurations
MAX_LOC = 3
MIN_LOC = 0

MIN_BAUD_FACTOR = 1
MAX_BAUD_FACTOR = 0xFF

MIN_BRD_ADDR = 0x01
MAX_BRD_ADDR = 0x7e

MIN_1WIRE_DEV_COUNT = 0

FIRST_ATTEN_MASK = 0x01f8
FIRST_ATTEN_START_BIT = 3
SECOND_ATTEN_MASK = 0x7e00
SECOND_ATTEN_START_BIT = 9

MIN_HASH_IDX = 10
MAX_HASH_IDX = 15

ANLG_ERRORS = {31: "Invalid channel number"}

SET_CHAN_CFG_ERRORS = {
    31: "Invalid argument",
    32: "Channel number out of range",
    33: "I2C bus timeout",
    34: "I2C bus slave failed to acknowledge"
}
SET_ALL_CHAN_CFG_ERRORS = {
    31: "The number of argument characters was not 4.",
    33: "I2C bus timeout",
    34: "I2C bus slave failed to acknowledge"
}

SET_ALL_DIFFERENT_CHAN_CFG_ERRORS = {
    31: "The number of argument characters was not 64.",
    33: "I2C bus timeout",
    34: "I2C bus slave failed to acknowledge"
}

LOAD_ERRORS = {
    31: "memory index out of range",
    32: "no data was stored at that memory index (configuration unchnaged)",
    33: "I2C bus timeout",
    34: "I2C bus slave failed to acknowledge"
}

SAVE_ERRORS = {31: "memory index out of range.", 32: "write failed."}

ONEWIRE_SEARCH_ERRORS = {31: "error communicating on 1-wire bus"}

ONEWIRE_SERIAL_NUMBER_ERRORS = {
    31: "argument invalid.",
    32: "argument out of range (>N)."
}

ONEWIRE_TEMP_ERRORS = {
    31: "no sensors available",
    32: "unable to read all sensors"
}

COMM_ERRORS = {
    31: "Invalid address (not 1 to 126)",
    32: "Argument contains a non-hex character",
    33: "Attempt to change baud rate failed"
}

class ARX:
    def __init__(self, conf: str = None):
        """c-tor. Controls and Monitors ARX boards.

        """
        print(ETCDCONF)
        if conf is not None:
            self.my_store = ds.DsaStore(conf)
        else:
            self.my_store = ds.DsaStore(ETCDCONF)
        self.my_cr = cr.CmdRsp('LWA')
        self.cmd_key_base = CMD_KEY_BASE
        self.mon_key_base = MON_KEY_BASE
        self.resp_key_base = RESP_KEY_BASE
        self.log = dsl.DsaSyslogger('lwa', 'arx', logging.INFO, 'Arx')
        self.log.function('c-tor')
        self.log.info("Created Arx object")
        self.chan_cfg = MAX_CHAN * [0]
        self.chan_cfg_signal_on = MAX_CHAN * [True]
        self.cmd_id = ""
        self.arx_addr = -1
        self.brd_sn = None
        self.sw_ver = None
        self.input_coupling = None
        self.onewire_temp_count = None
        self.onewire_temp_chan_map = None


    def _check_brd_addr(self, brd_addr: int):
        if brd_addr < MIN_BRD_ADDR or brd_addr > MAX_BRD_ADDR:
            raise ARXE.ArxException(
                "Invalid board address: {:02X}".format(brd_addr))

    def _check_baud_factor(self, baud_factor):
        if baud_factor < MIN_BAUD_FACTOR or baud_factor > MAX_BAUD_FACTOR:
            raise ARXE.ArxException(
                "Invalid baud factor: {}".format(baud_factor))

    def _check_config_dict(self, chan_cfg: dict):
        """Check required keys in dictionary
        """
        for key in REQ_CONFIG_KEYS:
            if key not in chan_cfg:
                raise ARXE.ArxException(
                    "Missing configuration key: {}".format(key))

    def _check_attenuation(self, atten: int):
        if atten < MIN_ATTENUATION or atten > MAX_ATTENUATION:
            raise ARXE.ArxException("Invalid attenuation: {}".format(atten))

    def _set_local_chan_cfg(self, chan: int, chan_cfg: dict):
        self._check_config_dict(chan_cfg)

        self._set_chan_cfg_signal_on_state(chan, chan_cfg[SIG_ON])

        if chan_cfg[NARROW_HPF]:
            self._set_chan_cfg_highpass_narrow(chan)
        else:
            self._set_chan_cfg_highpass_wide(chan)

        if chan_cfg[NARROW_LPF]:
            self._set_chan_cfg_lowpass_narrow(chan)
        else:
            self._set_chan_cfg_lowpass_wide(chan)

        atten = int(chan_cfg[FIRST_ATTEN] / ATTEN_SCALE)
        self._check_attenuation(atten)
        self._set_chan_cfg_first_atten(chan, atten)
        atten = int(chan_cfg[SECOND_ATTEN] / ATTEN_SCALE)
        self._check_attenuation(atten)
        self._set_chan_cfg_second_atten(chan, atten)
        if chan_cfg[DC_ON]:
            self._set_chan_cfg_input_dc_pwr_on(chan)
        else:
            self._set_chan_cfg_input_dc_pwr_off(chan)

    def _getBoardSN(self, brd_id: str) -> int:
        brd_hex_sn = brd_id[:BRD_ID_LEN]

    def _getFirmwareVersion(self, brd_id: int) -> int:
        brd_hex_sw_ver = brd_id[:BRD_ID_LEN]

    def _convert_chan_power(self, chan_pwr_counts: list) -> float:
        pwr = []
        for pwr_c in chan_pwr_counts:
            if pwr_c < MIN_PWR_COUNT:
                raise ARXE.ArxException(
                    "Channel Power counts < {}".format(MIN_PWR_COUNT))
            if pwr_c > MAX_PWR_COUNT:
                raise ARXE.ArxException(
                    "Channel Power counts > {}".format(MAX_PWR_COUNT))
            pwr.append(pwr_c)
        return pwr

    def _get_atten(self, att: int, mask: int, start_bit: int, val: int) -> int:
        b = (att ^ 0xFFFF) & 0x3F

        # clear b9:b14
        val &= ~mask

        # set b9:b14 with b
        val |= (b << start_bit)

        return val

    def _check_time(self, time0: int):
        """Helper to check range of time.

        Args
        ----
        time0
           Time sent to ARX board

        Raises
        ------
        ArxException
            Contains ARX error messages if any

        """

        if time0 < 0:
            raise ARXE.ArxException("time must be > 0. time= {}".format(time))

    def _check_rtn(self, rtn: dict, errors: dict = None):
        """Helper to check errors in rtn

        Args
        ----
        rtn
           Returned dictionary.
        errors
           Dictionary mapping error numbers to strings

        Raises
        ------
        ArxException
            Contains ARX error messages if any

        """
        # print("_check_rtn: rtn: {}".format(rtn))
        err_msg_json = rtn['err_str']
        if err_msg_json is None:
            raise ARXE.ArxException("Return in None")
        if err_msg_json != "":
            try:
                # print("_check_rtn: err_msg_json: {}".format(err_msg_json))
                err = json.loads(err_msg_json)
            except:
                raise ARXE.ArxException("Unable to parse json error msg")
            if errors is not None and err['ERR'] == 'NAK':
                err_msg = "{} {} - {}".format(err['ERR'], err['MSG'],
                                              errors[err['MSG']])
                raise ARXE.ArxException(err_msg)
            elif err['ERR'] != 'NAK':
                err_msg = "{} {}".format(err['ERR'], err['MSG'])
                raise ARXE.ArxException(err_msg)
            raise ARXE.ArxException(err_msg_json)

        return ""

    def _check_channel(self, chan: int):
        """Helper to check range of channel

        Args
        ----
        chan
           ARX Channel number. 0 indexed. MIN_CHAN_NUM <= chan <= MAX_CHAN_NUM

        """

        if chan < MIN_CHAN or chan > MAX_CHAN - 1:
            raise ARXE.ArxException("Invalid channel number: {}".format(chan))

    def _check_location(self, loc: int):
        """Helper to check range of memory location.

        Args
        ----
        loc
           ARX memory location number. 0 indexed. MIN_LOC_NUM <= loc <= MAX_LOC_NUM

        """

        if loc < MIN_LOC or loc > MAX_LOC - 1:
            raise ARXE.ArxException(
                "Invalid memory location number: {}".format(loc))

    def _check_1wire_device(self, dev_num: int):
        """Helper to check range of 1-wire device count.

        Args
        ----
        dev_num
           ARX 1-wire device number. 0 indexed. MIN_1WIRE_DEV_COUNT <= dev_num

        """

        if dev_num < MIN_1WIRE_DEV_COUNT:
            raise ARXE.ArxException(
                "Invalid 1-wire number: {}".format(dev_num))

    def _send(self,
              arx_addr: int,
              cmd: str,
              val: str = '',
              user_timeout: int = USER_TIMEOUT) -> list:
        """Private helper to send command dictionary to arx board.

        Args
        ----
        arx_addr
            ARX board address
        cmd
            An ARX board command.
        val
            Args if any for ARX command
        user_timeout
            User specified timeout on command. Defaults to 500ms

        Returns
        -------

        """

        key = '{}{}'.format(RESP_KEY_BASE, arx_addr)
        self.my_cr.set_response_key(key)

        cmd_key = '{}{}'.format(CMD_KEY_BASE, arx_addr)
        rtn = self.my_cr.send(cmd_key, cmd, val, user_timeout)

        return rtn

    def _set_chan_cfg_lowpass_wide(self, chan: int):
        """Set a channel's lowpass filter to wide.

        Note
        ----
        This function only manipulates the local configuration.
        Use set_chan_config() to send to ARX board.

        Args
        ----
        chan
            Channel number. 0 indexed.

        See Also
        --------
        set_chan_cfg()

        """
        self.chan_cfg[chan] &= ~(1)
        if self.chan_cfg_signal_on[chan]:
            self._set_chan_cfg_signal_bit_on(chan)
        else:
            self._set_chan_cfg_signal_bit_off(chan)

    def _set_chan_cfg_lowpass_narrow(self, chan: int):
        """Set a channel's lowpass filter to narrow.

        Note
        ----
        This function only manipulates the local configuration.
        Use set_chan_config() to send to ARX board.

        Args
        ----
        chan
            Channel number. 0 indexed.

        Raises
        ------
        ArxException
           Any ARX errors.

        See Also
        --------
        set_chan_cfg()

        """

        self._check_channel(chan)

        self.chan_cfg[chan] |= 0x01
        if self.chan_cfg_signal_on[chan]:
            self._set_chan_cfg_signal_bit_on(chan)
        else:
            self._set_chan_cfg_signal_bit_off(chan)

    def _set_chan_cfg_signal_on_state(self, chan: int, val: bool = True):
        """Set a channel's signal on state.

        Note
        ----
        This function only manipulates the local configuration.
        Use set_chan_config() to send to ARX board.

        Args
        ----
        chan
            Channel number. 0 indexed.
        val
            True for ON, False for OFF

        Raises
        ------
        ArxException
           Any ARX errors.

        See Also
        --------
        set_chan_cfg()

        """
        self._check_channel(chan)

        self.chan_cfg_signal_on[chan] = val
        if val:
            self._set_chan_cfg_signal_bit_on(chan)
        else:
            self._set_chan_cfg_signal_bit_off(chan)

    def _set_chan_cfg_signal_bit_on(self, chan: int):
        """Helper to set a channel's signal bit to ON.

        Note
        ----
        This function only manipulates the local configuration.
        Use set_chan_config() to send to ARX board.

        Args
        ----
        chan
            Channel number. 0 indexed.

        Raises
        ------
        ArxException
           Any ARX errors.

        See Also
        --------
        set_chan_cfg()

        """

        b0 = self.chan_cfg[chan] & 0x0001
        if b0 == 0:
            self.chan_cfg[chan] &= ~(1 << 1)
        else:
            self.chan_cfg[chan] |= (1 << 1)

    def _set_chan_cfg_signal_bit_off(self, chan: int):
        b0 = self.chan_cfg[chan] & 0x0001
        if b0 == 0:
            self.chan_cfg[chan] |= (1 << 1)
        else:
            self.chan_cfg[chan] &= ~(1 << 1)

    def _set_chan_cfg_highpass_wide(self, chan: int):
        """Set a channel's highpass filter to wide.

        Note
        ----
        This function only manipulates the local configuration.
        Use set_chan_config() to send to ARX board.

        Args
        ----
        chan
            Channel number. 0 indexed.

        Raises
        ------
        ArxException
           Any ARX errors.

        See Also
        --------
        set_chan_cfg()

        """

        self._check_channel(chan)
        # 1=narrow, 0=wide. 
        self.chan_cfg[chan] &= ~(1 << 2)

    def _set_chan_cfg_highpass_narrow(self, chan: int):
        """Set a channel's highpass filter to narrow.

        Note
        ----
        This function only manipulates the local configuration.
        Use set_chan_config() to send to ARX board.

        Args
        ----
        chan
            Channel number. 0 indexed.

        Raises
        ------
        ArxException
           Any ARX errors.

        See Also
        --------
        set_chan_cfg()

        """
        self._check_channel(chan)
        # 1=narrow, 0=wide. 
        self.chan_cfg[chan] |= (1 << 2)

    def _set_chan_cfg_input_dc_pwr_on(self, chan: int):
        """Set a channel's DC power to ON.

        Note
        ----
        This function only manipulates the local configuration.
        Use set_chan_config() to send to ARX board.

        Args
        ----
        chan
            Channel number. 0 indexed.

        Raises
        ------
        ArxException
           Any ARX errors.

        See Also
        --------
        set_chan_cfg()

        """

        self._check_channel(chan)

        self.chan_cfg[chan] |= (1 << 15)

    def _set_chan_cfg_input_dc_pwr_off(self, chan: int):
        """Set a channel's DC power to OFF.

        Note
        ----
        This function only manipulates the local configuration.
        Use set_chan_config() to send to ARX board.

        Args
        ----
        chan
            Channel number. 0 indexed.

        Raises
        ------
        ArxException
           Any ARX errors.

        See Also
        --------
        set_chan_cfg()

        """
        self.chan_cfg[chan] &= ~(1 << 15)

    def _set_chan_cfg_first_atten(self, chan: int, val: int):
        """Set first attenuation value for specified channel in dB

        Args
        ----
        chan
           Channel number to set
        val
           Attenuation value in units of 0.5db

        Note
        ----
        This function only manipulates the local configuration.
        Use set_chan_config() to send to ARX board.

        Raises
        ------
        ArxException
           Any ARX errors.

        See Also
        --------
        set_chan_cfg()

        """

        self._check_channel(chan)

        if val < 0 or val > 63:
            raise ARXE.ArxException(
                "Invalid first atten setting: {}".format(val))
        self.chan_cfg[chan] = self._get_atten(val, FIRST_ATTEN_MASK,
                                              FIRST_ATTEN_START_BIT,
                                              self.chan_cfg[chan])

    def _set_chan_cfg_second_atten(self, chan: int, val: int):
        """Set second attenuation value for specified channel in dB

        Args
        ----
        chan
           Channel number to set
        val
           Attenuation value in units of 0.5db

        Raises
        ------
        ArxException
           Any ARX errors.

        Note
        ----
        This function only manipulates the local configuration.
        Use set_chan_config() to send to ARX board.

        See Also
        --------
        set_chan_cfg()

        """

        self._check_channel(chan)

        if val < 0 or val > 63:
            raise ARXE.ArxException(
                "Invalid first atten setting: {}".format(val))

        self.chan_cfg[chan] = self._get_atten(val, SECOND_ATTEN_MASK,
                                              SECOND_ATTEN_START_BIT,
                                              self.chan_cfg[chan])

    def _show_chan_cfg(self,
                       chan: int,
                       verbose: bool = False,
                       cfg: int = None):
        """Show the binary representation of the channel configuration.

        Args
        ----
        chan
            ARX channel number. 0 indexed.
        verbose
            True to print out bit definitions.
        cfg
            16b integer representation of channel configuration.
            If None, then internal configuration is shown.

        Raises
        ------
        ArxException
           Any ARX errors.

        Note
        ----
        Bit definitions for 16bit configuration integer.

        b0 = lowpass filter (1=wide, 0=narrow)

        b1 = signal on when b1 == b0. off otherwise

        b2 = highpass filter (1=wide, 0=narrow)

        b3:b8 = first attenuation (inverted) in steps of 0.5dB. Max=63(31.5dB)

        b9:b14 = second attenuation (inverted) in steps of 0.5dB Max=63(31.5dB)

        b15 = dc power state (1=on, 0=off)

        See Also
        --------
        get_chan_cfg()


        """

        self._check_channel(chan)

        if cfg is None:
            print("{:016b}".format(self.chan_cfg[chan]))
        else:
            print("{:016b}".format(cfg))

        if verbose:
            print("b0 = lowpass filter (1=wide, 0=narrow)")
            print("b1 = signal on when b1 == b0. off otherwise")
            print("b2 = highpass filter (1=wide, 0=narrow)")
            print(
                "b3:b8 = first attenuation (inverted) in steps of 0.5dB. Max=63(31.5dB)"
            )
            print(
                "b9:b14 = second attenuation (inverted) in steps of 0.5dB Max=63(31.5dB)"
            )
            print("b15 = dc power state (1=on, 0=off)")

    def set_chan_cfg(self,
                     arx_addr: int,
                     chan: int,
                     chan_cfg: dict,
                     user_timeout: int = USER_TIMEOUT):
        """Set a channel's configuration.

        Args
        ----
        arx_addr
           ARX board address
        chan
           ARX board channel. 0 indexed.
        chan_cfg
           Dictionary with following keys:
           'narrow_lpf': bool, True for narrow LPF, False for 'wide'.
           'narrow_hpf': bool, True for narrow HPF, False for 'wide'.
           'first_atten': float, 0.5dB resolution. 0-31.5.
           'second_atten': float. 0.5dB resolution. 0-31.5.
           'sig_on': bool, True, False to turn signal off.
           'dc_on': bool, True. False to turn DC off.
        user_timeout
           User defined timeout. Default 500ms

        """

        self._set_local_chan_cfg(chan, chan_cfg)
        self._set_chan_cfg(arx_addr, chan, user_timeout)

    def _set_chan_cfg(self,
                      arx_addr: int,
                      chan: int,
                      user_timeout: int = USER_TIMEOUT) -> str:
        """Sends the channel configuration to the ARX board.

        Args
        ----
        arx_addr
            ARX board address
        chan
            The ARX channel to configure. 0 indexed.
        user_timeout
            User specified timeout on command. Defaults to 500ms

        Raises
        ------
        ArxException
           Any ARX errors.

        Note
        ----
        Sends the internal channel configuration to the ARX board.
        Changing the internal configuration can be done using the other
        `set_chan_cfg_` functions.

        Returns
        -------
        str
           Empty on no errors

        See Also
        --------
        set_chan_cfg()
        set_all_chan_cfg()
        set_all_different_chan_cfg()

        """

        self._check_channel(chan)

        chan_cfg_str = "{:1X}{:04X}".format(chan, self.chan_cfg[chan])
        rtn = self._send(arx_addr, 'setc', chan_cfg_str, user_timeout)

        return self._check_rtn(rtn, SET_CHAN_CFG_ERRORS)

    def get_chan_cfg(self,
                     arx_addr: int,
                     chan: int,
                     user_timeout: int = USER_TIMEOUT) -> dict:
        """Return the ARX channel's configuration.

        Args
        ----
        arx_addr
           ARX board address
        chan
           ARX channel number. 0 indexed
        user_timeout
            User specified timeout on command. Defaults to 500ms

        Returns
        -------
        dict
           A dictionary with the following keys:
           'sig_on':  True if signal is set to on.
           'narrow_lpf': True. False for wide filter.
           'narrow_hpf': True. False for wide filter.
           'first_atten': float 0.5dB resolution. 0-31.5.
           'second_atten': float 0.5dB resolution. 0-31.5.
           'dc_on': True if DC is on, False otherwise.

        Raises
        ------
        ArxException
           Any ARX errors.

        See Also
        --------
        set_chan_cfg()
        set_all_chan_cfg()
        set_all_different_chan_cfg()

        """
        chan_cfg = self._get_chan_cfg(arx_addr, chan, user_timeout)
        # self._show_chan_cfg(0, chan_cfg)
        lpf_wide = self._get_lpf(chan_cfg)
        hpf_wide = self._get_hpf(chan_cfg)
        sig_on = self._is_sig_on(chan_cfg)
        first_atten = self._get_first_atten(chan_cfg) * ATTEN_SCALE
        second_atten = self._get_second_atten(chan_cfg) * ATTEN_SCALE
        dc_on = self._is_dc_on(chan_cfg)

        rtn = {}
        rtn[SIG_ON] = sig_on
        rtn[NARROW_LPF] = (lpf_wide == 0)
        rtn[NARROW_HPF] = (hpf_wide == 0)
        rtn[FIRST_ATTEN] = first_atten
        rtn[SECOND_ATTEN] = second_atten
        rtn[DC_ON] = dc_on

        return rtn

    def get_all_chan_cfg(self,
                         arx_addr: int,
                         user_timeout: int = USER_TIMEOUT) -> list:
        """Return all ARX channel configurations.

        Args
        ----
        arx_addr
           ARX board address
        user_timeout
            User specified timeout on command. Defaults to 500ms

        Returns
        -------
        list
           Each element in the list is
           a dictionary with the following keys:
           'sig_on':  True if signal is set to on.
           'narrow_lpf': True. False for wide filter.
           'narrow_hpf': True. False for wide filter.
           'first_atten': float 0.5dB resolution. 0-31.5.
           'second_atten': float 0.5dB resolution. 0-31.5.
           'dc_on': True if DC is on, False otherwise.

        Raises
        ------
        ArxException
           Any ARX errors.

        See Also
        --------
        set_chan_cfg()
        set_all_chan_cfg()
        set_all_different_chan_cfg()

        """
        chan_cfgs = self._get_all_chan_cfg(arx_addr, user_timeout)
        #self._show_chan_cfg(0, chan_cfg)
        rtn = []
        for chan_cfg in chan_cfgs:
            lpf_wide = self._get_lpf(chan_cfg)
            hpf_wide = self._get_hpf(chan_cfg)
            sig_on = self._is_sig_on(chan_cfg)
            first_atten = self._get_first_atten(chan_cfg) * ATTEN_SCALE
            second_atten = self._get_second_atten(chan_cfg) * ATTEN_SCALE
            dc_on = self._is_dc_on(chan_cfg)

            cfg = {}
            cfg[SIG_ON] = sig_on
            cfg[NARROW_LPF] = (lpf_wide == 0)
            cfg[NARROW_HPF] = (hpf_wide == 0)
            cfg[FIRST_ATTEN] = first_atten
            cfg[SECOND_ATTEN] = second_atten
            cfg[DC_ON] = dc_on
            rtn.append(cfg)

        return rtn

    def _get_lpf(self, chan_cfg: int) -> int:
        return chan_cfg & 0x01

    def _get_hpf(self, chan_cfg: int) -> int:
        return (chan_cfg & (1 << 2)) >> 2

    def _is_sig_on(self, chan_cfg: int) -> bool:
        lpf = self._get_lpf(chan_cfg)
        so = (chan_cfg & (1 << 1)) >> 1
        return so == lpf

    def _get_first_atten(self, chan_cfg: int) -> int:
        return ((chan_cfg ^ 0xffff) & 0x01f8) >> 3

    def _get_second_atten(self, chan_cfg: int) -> int:
        return ((chan_cfg ^ 0xffff) & 0x7f00) >> 9

    def _is_dc_on(self, chan_cfg: int) -> bool:
        dc_on = (chan_cfg & 0x8000) >> 15
        return dc_on == 1

    def _get_chan_cfg(self,
                      arx_addr: int,
                      chan: int,
                      user_timeout: int = USER_TIMEOUT) -> int:
        """Return the ARX channel's configuration.

        Args
        ----
        arx_addr
           ARX board address
        chan
           ARX channel number. 0 indexed
        user_timeout
            User specified timeout on command. Defaults to 500ms

        Returns
        -------
        int
           A 16bit integer representation of the configuration.

        Raises
        ------
        ArxException
           Any ARX errors.

        See Also
        --------
        set_chan_cfg()
        set_all_chan_cfg()
        set_all_different_chan_cfg()

        """

        self._check_channel(chan)

        chan_str = "{:1X}".format(chan)
        rtn = self._send(arx_addr, 'getc', chan_str, user_timeout)

        self._check_rtn(rtn, SET_CHAN_CFG_ERRORS)
        return rtn['chan_config'][0]

    def _get_all_chan_cfg(self,
                          arx_addr: int,
                          user_timeout: int = USER_TIMEOUT) -> int:
        """Return all ARX channel configurations.

        Args
        ----
        arx_addr
           ARX board address
        user_timeout
            User specified timeout on command. Defaults to 500ms

        Returns
        -------
        int
           A 16bit integer representation of the configuration.

        Raises
        ------
        ArxException
           Any ARX errors.

        See Also
        --------
        set_chan_cfg()
        set_all_chan_cfg()
        set_all_different_chan_cfg()

        """

        rtn = self._send(arx_addr, 'geta', '', user_timeout)

        self._check_rtn(rtn, SET_CHAN_CFG_ERRORS)
        return rtn['chan_config']
    
    def set_all_chan_cfg(self,
                         arx_addr: int,
                         chan_cfg: dict,
                         user_timeout: int = USER_TIMEOUT):
        """Sends configuration defined in 'chan_cfg' to all channels on the ARX board.

        Args
        ----
        arx_addr
           ARX board address.
        chan_cfg
           Dictionary with following keys:
           'narrow_lpf': bool, True for narrow LPF, False for 'wide'.
           'narrow_hpf': bool, True for narrow HPF, False for 'wide'.
           'first_atten': float, 0.5dB resolution. 0-31.5.
           'second_atten': float. 0.5dB resolution. 0-31.5.
           'sig_on': bool, True, False to turn signal off.
           'dc_on': bool, True. False to turn DC off.

        user_timeout
            User specified timeout on command. Defaults to 500ms

        Raises
        ------
        ArxException
           Any ARX errors.

        See Also
        --------
        set_chan_cfg()
        set_all_chan_cfg()
        set_all_different_chan_cfg()

        """

        chan = 0
        self._set_local_chan_cfg(chan, chan_cfg)
        self._set_all_chan_cfg(arx_addr, chan, user_timeout)

    def _set_all_chan_cfg(self,
                          arx_addr,
                          chan: int,
                          user_timeout: int = USER_TIMEOUT):
        """Sends configuration defined for 'chan' to all channels on the ARX board.

        Note
        ----
        Sends the internal channel configuration to all channels
        on the specified ARX board.
        Changing the internal configuration can be done using the other
        `set_chan_cfg_` functions.

        Args
        ----
        arx_addr
           ARX board address.
        chan
           Channel config to use to send to all ARX channels
        user_timeout
            User specified timeout on command. Defaults to 500ms

        Raises
        ------
        ArxException
           Any ARX errors.

        See Also
        --------
        set_chan_cfg()
        set_all_chan_cfg()
        set_all_different_chan_cfg()

        """

        chan_cfg_str = "{:04X}".format(self.chan_cfg[chan])
        rtn = self._send(arx_addr, 'seta', chan_cfg_str, user_timeout)

        return self._check_rtn(rtn, SET_ALL_CHAN_CFG_ERRORS)

    def set_all_different_chan_cfg(self,
                                   arx_addr,
                                   chan_cfgs: list,
                                   user_timeout: int = USER_TIMEOUT):
        """Sends configurations defined in chan_cfgs for each channel to the ARX board. 

        Args
        ----
        arx_addr
           ARX board address.
        chan_cfgs
           list of dictionaries. list ordered by channel number. dictionary
           contains keys:
           'narrow_lpf': True, False for 'wide'.
           'narrow_hpf': True, False for 'wide'.
           'sig_on': True to turn sig. on. False for off.
           'first_atten': float.  0.5 dB resolution. 0-31.5.
           'second_atten': float 0.5 dB resolution. 0-31.5.
           'dc_on': True, False for off.
        user_timeout
            User specified timeout on command. Defaults to 500ms

        Raises
        ------
        ArxException
           Any ARX errors.

        See Also
        --------
        set_chan_cfg()
        set_all_chan_cfg()
        set_all_different_chan_cfg()

        """
        [
            self._set_local_chan_cfg(chan, cfg)
            for chan, cfg in enumerate(chan_cfgs)
        ]
        self._set_all_different_chan_cfg(arx_addr, user_timeout)

    def _set_all_different_chan_cfg(self,
                                    arx_addr,
                                    user_timeout: int = USER_TIMEOUT):
        """Sends all configurations defined for each channel to the ARX board.

        Note
        ----
        Sends the internal channel configurations to the ARX board.
        Each channel can have a different configuration.
        Changing the internal configuration can be done using the other
        `set_chan_cfg_` functions.

        Args
        ----
        arx_addr
           ARX board address.
        user_timeout
            User specified timeout on command. Defaults to 500ms

        Raises
        ------
        ArxException
           Any ARX errors.

        See Also
        --------
        set_chan_cfg()
        set_all_chan_cfg()
        set_all_differentchan_cfg()

        """

        chan_cfg_str = ''.join("{:04X}".format(x) for x in self.chan_cfg)
        rtn = self._send(arx_addr, 'sets', chan_cfg_str, user_timeout)

        return self._check_rtn(rtn, SET_ALL_DIFFERENT_CHAN_CFG_ERRORS)

    def get_board_sn(self,
                     arx_addr: int,
                     user_timeout: int = USER_TIMEOUT) -> int:
        """Return ARX board serial number. This is board specific
        immutable value.

        Args
        ----
        arx_addr
            ARX board address
        user_timeout
            User specified timeout on command. Defaults to 500ms

        Returns
        -------
        int
            16bit integer of the ARX board ID

        Raises
        ------
        ArxException
           Any arrors with the ARX board.

        """

        if self.brd_sn != None:
            return self.brd_sn
        else:
            brd_dict = self.get_board_info(arx_addr,
                                           user_timeout)
            return self.brd_sn

    def get_board_info(self,
                     arx_addr: int,
                     user_timeout: int = USER_TIMEOUT) -> dict:
        """Return following information from an ARX board:
           serial number, software version string, input_coupling array
           and the number of known temperature sensors.
           The serial number is a board specific immutable value.
           The input_coupling array is of length 16 and whose element
           index represents the channel index. A vaule 0 represents a coax
           coupled antenna and a 1 represents a fiber coupled antenna.

        Args
        ----
        arx_addr
            ARX board address
        user_timeout
            User specified timeout on command. Defaults to 500ms

        Returns
        -------
        dict
            Dictionary with the following keys:
            'brd_sn', 'sw_ver', 'input_coupling', '1wire_temp_count',
            '1wire_temp_chan_map'

        Raises
        ------
        ArxException
           Any arrors with the ARX board.

        """

        rtn = self._send(arx_addr, 'arxn', '',user_timeout)
        self._check_rtn(rtn)
        self.brd_sn = rtn['brd_id']
        self.sw_ver = rtn['sw_ver']
        self.input_coupling = rtn['input_coupling']
        self.onewire_temp_count = rtn['1wire_temp_count']
        self.onewire_temp_chan_map = rtn['1wire_temp_chan_map']
        rtn_d = {}
        rtn_d['brd_sn'] = self.brd_sn
        rtn_d['sw_ver'] = self.sw_ver
        rtn_d['input_coupling'] = self.input_coupling
        rtn_d['1wire_temp_count'] = self.onewire_temp_count
        rtn_d['1wire_temp_chan_map'] = self.onewire_temp_chan_map
        return rtn_d
                       
    def get_board_id(self,
                     arx_addr: int,
                     user_timeout: int = USER_TIMEOUT) -> int:
        """DEPRECATED. Return ARX board serial number. This is board
        specific immutable value. Use get_board_sn() or
        get_board_info(). This function will be removed in a future release.

        Args
        ----
        arx_addr
            ARX board address
        user_timeout
            User specified timeout on command. Defaults to 500ms

        Returns
        -------
        int
            16bit integer of the ARX board ID

        Raises
        ------
        ArxException
           Any arrors with the ARX board.

        """

        return get_board_sn(arx_addr, user_timeout)

    def get_firmware_version(self,
                             arx_addr: int,
                             user_timeout: int = USER_TIMEOUT) -> int:
        """Return firmware version installed on ARX board.

        Args
        ----
        arx_addr
            ARX board address
        user_timeout
            User specified timeout on command. Defaults to 500ms

        Returns
        -------
        int
            16bit integer of the firmware version installed on ARX board.

        Raises
        ------
        ArxException
           Any arrors with the ARX board.

        """

        if self.sw_ver is not None:
            return self.sw_ver
        else:
            brd_dict = self.get_board_info(arx_addr,
                                           user_timeout)
            return self.sw_ver

    def get_microcontroller_temp(self,
                                 arx_addr: int,
                                 user_timeout: int = USER_TIMEOUT) -> float:
        """Return ARX board's microcontroller temperature in C. Resolution 0.1C

        Args
        ----
        arx_addr
            ARX board address
        user_timeout
            User specified timeout on command. Defaults to 500ms

        Returns
        -------
        float
           ARX board's microcontroller temperature in C.

        Raises
        ------
        ArxException
           Any arrors with the ARX board.

        """

        rtn = self._send(arx_addr, 'temp', '',user_timeout)
        self._check_rtn(rtn)
        return rtn['brd_temp']

    def echo(self,
             arx_addr: int,
             val: str,
             user_timeout: int = USER_TIMEOUT) -> str:
        """Return echoed val.

        Args
        ----
        arx_addr
           ARX board address
        val
           ASCII chacters to be echoed.
        user_timeout
            User specified timeout on command. Defaults to 500ms

        Returns
        -------
        str
            Input contained in val

        Raises
        ------
        ArxException
           Any arrors with the ARX board.

        """

        rtn = self._send(arx_addr, 'echo', val, user_timeout)
        self._check_rtn(rtn)
        rtn2 = rtn['echo']
        e_val = rtn2.split("ECHO")[1]
        if e_val != str(val):
            raise ARXE.ArxException(
                "Echo return do not match sent. Sent= {}, return= {}".format(
                    val, e_val))
        return rtn['echo']

    def raw(self, arx_addr: int, cmd: str, user_timeout: int = USER_TIMEOUT) -> str:
        """Return byte stream for given command as Python 2 str type of hex digits. Each pair of digits represents the byte value in hex format.

        Args
        ----
        arx_addr
           ARX board address
        user_timeout
            User specified timeout on command. Defaults to 500ms

        Raises
        ------
        ArxException
           Any ARX errors.

        """

        rtn = self._send(arx_addr, 'raw', cmd, user_timeout)
        self._check_rtn(rtn)
        return rtn['raw']

    def _get_time(self,
                  arx_addr: int,
                  user_timeout: int = USER_TIMEOUT) -> int:
        """Return the board time since setting.

        Args
        ----
        arx_addr
           ARX board address
        user_timeout
            User specified timeout on command. Defaults to 500ms

        Returns
        -------
        int
            Time in seconds based on time board was last set to.

        Raises
        ------
        ArxException
            All ARX related expections.

        """

        rtn = self._send(arx_addr, 'gtim', '',user_timeout)
        self._check_rtn(rtn)
        return rtn['brd_time_sec']

    def _set_time(self,
                  arx_addr: int,
                  time0: int,
                  user_timeout: int = USER_TIMEOUT) -> str:
        """Set the board time in seconds.

        Args
        ----
        arx_addr
            ARX board address.
        time0
            Represents time in seconds.
        user_timeout
            User specified timeout on command. Defaults to 500ms

        Returns
        -------
        str
           Empty string for no errors.

        Raises
        ------
        ArxException
           Contains any error messages.

        """

        self._check_time(time)

        time_str = "{}".format(time0)
        rtn = self._send(arx_addr, 'gtim', time_str, user_timeout)
        self._check_rtn(rtn)
        return rtn['err_str']

    def get_chan_voltage(self,
                         arx_addr: int,
                         chan: int,
                         user_timeout: int = USER_TIMEOUT) -> int:
        """Return 16bit digitized voltage from the processor's ADC channel.
        Range 0:255. Note: these channels are not necessarily equal to the
        16 signal channels.

        Note
        ----
        Many values are invalid.

        Args
        ----
        arx_addr
            ARX board address.
        chan
            Specifies the processor's ADC channel number. 0 indexed
        user_timeout
            User specified timeout on command. Defaults to 500ms

        Returns
        -------
        int
            Digitized voltage as a 16bit value in volts.

        Raises
        ----------
        ArxException


        """

        self._check_channel(chan)
        chan_str = "{:02X}".format(chan)
        rtn = self._send(arx_addr, 'anlg', chan_str, user_timeout)

        self._check_rtn(rtn, ANLG_ERRORS)

        return rtn['chan_adc_millivolts']/1000.

    def load_cfg(self,
                 arx_addr: int,
                 loc: int,
                 user_timeout: int = USER_TIMEOUT) -> str:
        """Load config from stored memory location.

        Note
        ----
        On a power cycle, contents from memory locatation 0 will be loaded.

        Args
        ----
        arx_addr
            ARX board address.
        loc
           Memory location. Allowed: 0,1 or 2.
        user_timeout
            User specified timeout on command. Defaults to 500ms

        Returns
        -------
        str
           Empty string for no errors.

        Raises
        ------
        ArxException
           Any ARX errors

        """

        self._check_location(loc)
        loc_str = "{}".format(loc)

        rtn = self._send(arx_addr, 'load', loc_str, user_timeout)

        return self._check_rtn(rtn, LOAD_ERRORS)

    def save_cfg(self,
                 arx_addr: int,
                 loc: int,
                 user_timeout: int = USER_TIMEOUT) -> str:
        """Save channel configuration to 1 of 3 memory locations. 0 indexed.

        Note
        ----
        On a power cycle, contents from memory locatation 0 will be loaded.

        Args
        ----
        arx_addr
            ARX board address.
        loc
           Memory location. Allowed: 0,1 or 2.
        user_timeout
            User specified timeout on command. Defaults to 500ms

        Returns
        -------
        str
           Empty string for no errors.

        Raises
        ------
        ArxException
           Any ARX errors

        """

        self._check_location(loc)

        loc_str = "{}".format(loc)

        rtn = self._send(arx_addr, 'save', loc_str, user_timeout)

        return self._check_rtn(rtn, SAVE_ERRORS)

    def get_chan_power(self,
                       arx_addr: int,
                       chan: int,
                       user_timeout: int = USER_TIMEOUT) -> float:
        """Return specified RF rms power at the output of specified channel
        assuming a 50 Ohm load.


        Args
        ----
        arx_addr
            ARX board address.
        chan
           Channel number. 0 indexed
        user_timeout
            User specified timeout on command. Defaults to 500ms

        Returns
        -------
        float
           Channel power in Watts

        Raises
        ------
        ArxException
            Any ARX error.

        """

        self._check_channel(chan)

        chan_str = "{:1X}".format(chan)

        rtn = self._send(arx_addr, 'powc', chan_str, user_timeout)
        self._check_rtn(rtn)

        pwr_watts = []
        for pwr in rtn['chan_microwatts']:
            pwr_watts.append(pwr*1e-6)
        return pwr_watts[0]

    def get_all_chan_power(self,
                           arx_addr: int,
                           user_timeout: int = USER_TIMEOUT) -> list:
        """Return RF rms power at the output for all channels
        assuming a 50 Ohm load.

        Args
        ----
        arx_addr
            ARX board address.
        user_timeout
            User specified timeout on command. Defaults to 500ms

        Returns
        -------
        list
           Power in Watts for all ARX channels.

        Raises
        ------
        ArxException
            Any ARX error.

        """
        rtn = self._send(arx_addr, 'powa', '',user_timeout)
        self._check_rtn(rtn)
        pwr_watts = []
        for pwr in rtn['chan_microwatts']:
            # convert to watts
            pwr_watts.append(pwr*1e-6)
        return pwr_watts

    def _get_chan_current_adc(self,
                              arx_addr: int,
                              chan: int,
                              user_timeout: int = USER_TIMEOUT) -> int:
        """Return specified channel current in adc counts.
        For coax-connected antennas, this is the current drawn by
        the FEE; the scale is 100 mA / V.
        For fiber-connected antennas, this is the photodiode current at the ARX
        board with a scale of 1.0 mA/V
        This current comes from the external 15V power supply.

        Note
        ----
        The processor has a 10b A/D converter set to a range of 0 to 4.096V.
        This class is not responsible for antenna to type(e.g. coax,fiber)
        mapping. User applications will take the value from this function and
        scale appropriately to give the correct current for the antenna.

        Args
        ----
        arx_addr
           ARX board address.
        chan
           Channel number. 0 indexed
        user_timeout
           User specified timeout on command. Defaults to 500ms

        Returns
        -------
        int
           Current for specified channel in ADC counts

        Raises
        ------
        ArxException
            Any ARX error.

        """
        self._check_channel(chan)

        # For coax-connected antennas, this is the current drawn by the FEE;
        # a value of 4095 corresponds to 500 mA.  For fiber-connected antnnas,
        # this is the photodiode current at the ARX board; 4095 corresponds to
        # 5 mA.

        chan_str = "{:1X}".format(chan)
        rtn = self._send(arx_addr, 'curc', chan_str, user_timeout)
        self._check_rtn(rtn)

        return rtn['chan_current_adc'][0]

    def _adc2volts(self, adc: int) -> float:
        return adc * MVOLT_PER_COUNT / 1000.

    def _volts2Amps(self, volts: float, coupling: int) -> float:
        if 0 == coupling:
            return volts * COAX_MA_PER_VOLT / 1000.
        else:
            return volts * FIBER_MA_PER_VOLT / 1000.

    def get_chan_current(self,
                         arx_addr: int,
                         chan: int,
                         user_timeout: int = USER_TIMEOUT) -> int:
        """Return specified channel current in Amps.
        This current comes from the external 15V power supply.

        Args
        ----
        arx_addr
           ARX board address.
        chan
           Channel number. 0 indexed
        user_timeout
           User specified timeout on command. Defaults to 500ms

        Returns
        -------
        float
           Current for specified channel in Amps

        Raises
        ------
        ArxException
            Any ARX error.

        """
        self._check_channel(chan)
        chan_adc = self._get_chan_current_adc(arx_addr, chan, user_timeout)
        if self.input_coupling is None:
            self.get_board_info(arx_addr, user_timeout)
        volts = self._adc2volts(chan_adc)

        return self._volts2Amps(volts, self.input_coupling[chan])
    
    def _get_all_chan_current_adc(self,
                             arx_addr: int,
                             user_timeout: int = USER_TIMEOUT) -> list:
        """Return all channel currents.
           See: get_chan_current() for details.

        Args
        ----
        arx_addr
            ARX board address.
        user_timeout
            User specified timeout on command. Defaults to 500ms

        Returns
        -------
        list
           Current for each channel in ADC units.

        Raises
        ------
        ArxException
            Any ARX error.

        """
        rtn = self._send(arx_addr, 'cura', '',user_timeout)
        self._check_rtn(rtn)

        return rtn['chan_current_adc']

    def get_all_chan_current(self,
                             arx_addr: int,
                             user_timeout: int = USER_TIMEOUT) -> list:
        """Return all channel currents.
           See: get_chan_current() for details.

        Args
        ----
        arx_addr
            ARX board address.
        user_timeout
            User specified timeout on command. Defaults to 500ms

        Returns
        -------
        list
           Current for each channel in Amps.

        Raises
        ------
        ArxException
            Any ARX error.

        """
        adc_list = self._get_all_chan_current_adc(arx_addr, user_timeout)
        if self.input_coupling is None:
            self.get_board_info(arx_addr, user_timeout)
        current = []
        for idx, adc in enumerate(adc_list):
            volts = self._adc2volts(adc)
            current.append(self._volts2Amps(volts, self.input_coupling[idx]))
        return current

    def get_board_current(self,
                          arx_addr: int,
                          user_timeout: int = USER_TIMEOUT) -> int:
        """Return the total DC current drawn by circuitry on this ARX board.
        This current comes from the 6V external power supply,
        regulated to 5V on the board.

        Args
        ----
        arx_addr
            ARX board address.
        user_timeout
            User specified timeout on command. Defaults to 500ms

        Returns
        -------
        int
           ARX Board current. Units: Amperes

        Raises
        ------
        ArxException
            Any ARX error.

        """
        rtn = self._send(arx_addr, 'curb', '', user_timeout)
        self._check_rtn(rtn)
        return rtn['brd_milliamps'] * 0.001

    def _search_1wire(self,
                      arx_addr: int,
                      user_timeout: int = USER_TIMEOUT) -> int:
        """Search the 1wire buss for devices and returns count.

        Args
        ----
        arx_addr
            ARX board address.
        user_timeout
            User specified timeout on command. Defaults to 500ms

        Returns
        -------
        int
           Count of 1wire devices found on bus.

        Raises
        ------
        ArxException
            Any ARX error.

        """
        rtn = self._send(arx_addr, 'owse', '',user_timeout)

        self._check_rtn(rtn, ONEWIRE_SEARCH_ERRORS)
        return rtn['1wire_dev_count']

    def get_1wire_count(self,
                        arx_addr: int,
                        user_timeout: int = USER_TIMEOUT) -> int:
        """Returns previously found 1wire device count.

        Args
        ----
        arx_addr
            ARX board address.
        user_timeout
            User specified timeout on command. Defaults to 500ms

        Note
        ----
        Does not search the 1wire bus but uses a stored value from
        the last search.

        Returns
        -------
        int
           Number of 1wire devices found during last scan of the bus.

        Raises
        ------
        ArxException
            Any ARX error.

        """

        rtn = self._send(arx_addr, 'owdc', '',user_timeout)
        self._check_rtn(rtn)

        return rtn['1wire_dev_count']

    def get_1wire_SN(self,
                      arx_addr: int,
                      dev_num: int,
                      user_timeout: int = USER_TIMEOUT) -> str:
        """Return specified 1wire serial number.

        Args
        ----
        arx_addr
            ARX board address.
        dev_num
           1wire device number. 0 indexed
        user_timeout
            User specified timeout on command. Defaults to 500ms

        Returns
        -------
        str
           Serial number of 1wire device as a 16 char hex string

        Raises
        ------
        ArxException
            Any ARX error.

        """

        dev = '{:01X}'.format(dev_num)
        rtn = self._send(arx_addr, 'owsn', dev, user_timeout)

        self._check_rtn(rtn, ONEWIRE_SERIAL_NUMBER_ERRORS)
        return rtn['1wire_sn']


    def get_1wire_temp(self,
                       arx_addr: int,
                       user_timeout: int = ONEWIRE_TEMP_TIMEOUT) -> list:
        """Return temperatures in C for all 1wire devices.
        There are N such values, in order of the sensor's index number
        where N is the number of sensors.

        Args
        ----
        arx_addr
            ARX board address.
        user_timeout
            User specified timeout on command. Defaults to 1.2sec

        Returns
        -------
        list
           1wire device temperatures in C

        Raises
        ------
        ArxException
            Any ARX error.

        See Also
        --------
        get_1wire_count

        """

        rtn = self._send(arx_addr, 'owte', '',user_timeout)

        self._check_rtn(rtn, ONEWIRE_TEMP_ERRORS)
        return rtn['1wire_temp']

    def reset(self, arx_addr: int, user_timeout: int = USER_TIMEOUT):
        """Reset the processor on the ARX board. The board will reset to its
        initial state as if the power had been cycled.

        Args
        ----
        arx_addr
           ARX Board address.
        user_timeout
           User defined timeout. Default: 500ms

        Raises
        ------
        ArxException on any ARX related errors.

        """
        rtn = self._send(arx_addr, 'rset', '',user_timeout)
        # Dont' check return as this command does not respond so a read
        # timeout on the serial device will occur. Ignore it.

    def comm(self,
             arx_addr: int,
             new_brd_addr: int,
             baud_factor: int = None,
             user_timeout: int = USER_TIMEOUT):
        """Set the RS485 address and baud rate.

        Note
        ----
        Use with caution. Incorrect parameters will cause loss of communication
        until a manual power cycle.

        Args
        ----
        arx_addr
           ARX Board address.
        new_brd_addr
           Two ascii character [0x01,0x7e] other than NULL. Will be set to
           0x80 + new_brd_addr. Future communication must use this address.
        baud_factor
           Unsinged 16b value for setting baud rate = 16*baud_factor Hz.
           Default: None(No change to baud rate).
        user_timeout
           User defined timeout. Default: 500ms

        Raises
        ------
        ArxException on any ARX related errors.

        """
        self._check_brd_addr(new_brd_addr)
        val = new_brd_addr
        if baud_factor is not None:
            self._check_baud_factor(baud_factor)
            val = '{}{:04X}'.format(val, baud_factor * 16)

        rtn = self._send(arx_addr, 'comm', val, user_timeout)
        self._check_rtn(rtn, COMM_ERRORS)
        return ""

    def last(self, arx_addr: int, user_timeout: int = USER_TIMEOUT):
        """Return the last command sent to the ARX board.

        Args
        ----
        arx_addr
           ARX Board address.
        user_timeout
           User defined timeout. Default: 500ms

        Raises
        ------
        ArxException on any ARX related errors.

        """
        rtn = self._send(arx_addr, 'last', '',user_timeout)
        self._check_rtn(rtn, None)
        return rtn['last_cmd']
