""" ARX is a class to encapsulate controlling a LWA ARX board.

    >>> # Example using ARX class
    >>>
    >>> import lwautils.lwa_arx as arx
    >>> import lwautils.ArxException as arxe
    >>> brd_addr = 2
    >>> try:
    >>>    my_arx = arx.ARX()
    >>>    brd_temp = my_arx.get_board_temp(brd_addr)
    >>>    brd_id = my_arx.get_board_id(brd_addr)
    >>>    echo_rtn = my_arx.echo(brd_addr, "abcdef")
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
ETCDCONF = resource_filename(Requirement.parse("lwa-pyutils"),
                             "lwautils/conf/etcdConfig.yml")
sys.path.append(str(Path('..')))

CMD_KEY_BASE = '/cmd/arx/'
MON_KEY_BASE = '/mon/arx/'
# wait for arx board to exec and push to etcd.
CMD_TIMEOUT = 0.15

# Maximum number of analog channels on ARX board
MAX_CHAN = 16
MIN_CHAN = 0

# Maximum memory location for stored configurations
MAX_LOC = 3
MIN_LOC = 0

MIN_1WIRE_DEV_COUNT = 0

FIRST_ATTEN_MASK = 0x01f8
FIRST_ATTEN_START_BIT = 3
SECOND_ATTEN_MASK = 0x7e00
SECOND_ATTEN_START_BIT = 9

ANLG_ERRORS = {31: "Invalid channel number"}

SET_CHAN_CFG_ERRORS = {31: "Invalid argument",
                       32: "Channel number out of range",
                       33: "I2C bus timeout",
                       34: "I2C bus slave failed to acknowledge"}
SET_ALL_CHAN_CFG_ERRORS = {31: "The number of argument characters was not 4."}

SET_ALL_DIFFERENT_CHAN_CFG_ERRORS = {31: "The number of argument characters was not 48."}

LOAD_ERRORS = {31: "memory index out of range",
               32: "no data was stored at that memory index (configuration unchnaged)",
               33: "I2C bus timeout",
               34: "I2C bus slave failed to acknowledge"}

SAVE_ERRORS = {31: "memory index out of range.",
               32: "write failed."}

ONEWIRE_SEARCH_ERRORS = {31: "error communicating on 1-wire bus"}

ONEWIRE_SERIAL_NUMBER_ERRORS = {31: "argument invalid.",
                                32: "argument out of range (>N)."}

ONEWIRE_TEMP_ERRORS = {31: "no sensors available",
                       32: "unable to read all sensors"}

class ARX:
    def __init__(self):
        """c-tor. Controls and Monitors ARX boards.

        """
        print(ETCDCONF)
        self.my_store = ds.DsaStore(ETCDCONF)
        self.cmd_key_base = CMD_KEY_BASE
        self.mon_key_base = MON_KEY_BASE
        self.log = dsl.DsaSyslogger('lwa', 'arx', logging.INFO, 'Arx')
        self.log.function('c-tor')
        self.log.info("Created Arx object")
        self.chan_cfg = MAX_CHAN*[0]
        self.chan_cfg_signal_on = MAX_CHAN*[True]

    def _check_time(self, time: int):
        """Helper to check range of time.

        Args
        ----
        time
           Time sent to ARX board

        Raises
        ------
        ArxException
            Contains ARX error messages if any

        """

        if time < 0:
            raise ARXE.ArxException("time must be > 0. time= {}".format(time))
        
    def _check_rtn(self, rtn: dict, errors: dict):
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
        
        err_msg_json = rtn['err_str']
        if err_msg_json != "":
            try:
                err = json.loads(err_msg_json)
                err_msg = "NAK {} - {}".format(err['NAK'], errors[err['NAK']])
            except:
                raise ARXE.ArxException(err_msg_json)
            raise ARXE.ArxException(err_msg)

        return ""

    def _check_channel(self, chan: int):
        """Helper to check range of channel

        Args
        ----
        chan
           ARX Channel number. 0 indexed. MIN_CHAN_NUM <= chan <= MAX_CHAN_NUM

        """
        
        if chan < MIN_CHAN or chan > MAX_CHAN-1:
            raise ARXE.ArxException("Invalid channel number: {}".format(chan))

    def _check_location(self, loc: int):
        """Helper to check range of memory location.

        Args
        ----
        loc
           ARX memory location number. 0 indexed. MIN_LOC_NUM <= loc <= MAX_LOC_NUM

        """

        if chan < MIN_LOC or chan > MAX_LOC-1:
            raise ARXE.ArxException("Invalid location number: {}".format(loc))

    def _check_1wire_device(self, dev_num: int):
        """Helper to check range of 1-wire device count.

        Args
        ----
        dev_num
           ARX 1-wire device number. 0 indexed. MIN_1WIRE_DEV_COUNT <= dev_num

        """

        if dev_num < MIN_1WIRE_DEV_COUNT:
            raise ARXE.ArxException("Invalid 1-wire number: {}".format(dev_num))
        
    def _send(self, arx_addr: int, cmd: str, val: str):
        """Private helper to send command dictionary to arx board.

        Args
        ----
        arx_addr
            ARX board address
        cmd
            An ARX board command.
        val
            Args if any for ARX command

        Returns
        -------

        """
        cmd_dict = {}
        cmd_dict['cmd'] = cmd
        cmd_dict['val'] = val
        key = "{}{}".format(CMD_KEY_BASE, arx_addr)
        self.my_store.put_dict(key, cmd_dict)

    def _get(self, arx_addr: str) -> dict:
        """Private helper to get dictionary for an arx board.

        Args
        ----
        arx_addr
            ARX board address

        Returns
        -------
        dict
            Dictionary contains value associated with key

        """
        key = "{}{}".format(MON_KEY_BASE,arx_addr)
        return self.my_store.get_dict(key)

    def _sendreceive(self, arx_addr: int, cmd: str, val: str = ''):
        """Private helper to send and receive cmds from an ARX board

        Args
        ----
        arx_addr
           Arx board address to send command to.
        cmd
           Command to send
        val
           Optional arguments for command

        """
        rtn = []
        
        self._send(arx_addr, cmd, val)
        # wait 150ms for command to be executed
        time.sleep(CMD_TIMEOUT)
        arx_d = self._get(arx_addr)
        print(arx_d)
        rtn.append(arx_d)
        
        return rtn

    def set_chan_cfg_lowpass_wide(self, chan: int):
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
        show_chan_cfg()
        set_chan_cfg()
        set_chan_cfg_lowpass_narrow()

        """        
        self.chan_cfg[chan] |= 0x01
        if self.chan_cfg_signal_on[chan]:
            self._set_chan_cfg_signal_bit_on(chan)
        else:
            self._set_chan_cfg_signal_bit_off(chan)

    def set_chan_cfg_lowpass_narrow(self, chan: int):
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
        show_chan_cfg()
        set_chan_cfg()
        set_chan_cfg_lowpass_wide()

        """

        self._check_channel(chan)
        
        self.chan_cfg[chan] &= ~(1)
        if self.chan_cfg_signal_on[chan]:
            self._set_chan_cfg_signal_bit_on(chan)
        else:
            self._set_chan_cfg_signal_bit_off(chan)

    def set_chan_cfg_signal_on_state(self, chan: int, val: bool = True):
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
        show_chan_cfg()
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
        show_chan_cfg()
        set_chan_cfg()
        set_chan_cfg_lowpass_narrow()

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

    def set_chan_cfg_highpass_wide(self, chan: int):
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
        show_chan_cfg()
        set_chan_cfg()
        set_chan_cfg_lowpass_narrow()
        set_chan_cfg_lowpass_wide()
        set_chan_cfg_highpass_narrow()

        """
        
        self.check_channel(chan)
        self.chan_cfg[chan] |= (1 << 2)

    def set_chan_cfg_highpass_narrow(self, chan: int):
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
        show_chan_cfg()
        set_chan_cfg()
        set_chan_cfg_lowpass_narrow()
        set_chan_cfg_lowpass_wide()
        set_chan_cfg_highpass_wide()

        """
        self._check_channel(chan)
        self.chan_cfg[chan] &= ~(1 << 2)

    def set_chan_cfg_input_dc_pwr_on(self, chan: int):
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
        show_chan_cfg()
        set_chan_cfg()
        set_chan_dc_pwr_off()

        """

        self._check_channel(chan)
        
        self.chan_cfg[chan] |= (1 << 15)

    def set_chan_cfg_input_dc_pwr_off(self, chan: int):
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
        show_chan_cfg()
        set_chan_cfg()
        set_chan_dc_pwr_on()

        """        
        self.chan_cfg[chan] &= ~(1 << 15)
        

    def set_chan_cfg_first_atten(self, chan: int, val: int):
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
        show_chan_cfg()
        set_chan_cfg()
        set_chan_cfg_second_atten()

        """

        self._check_channel(chan)
        
        if val < 0 or val > 63:
            raise ARXE.ArxException("Invalid first atten setting: {}".format(val))
        b = (val ^ 0xFFFF) & 0x3F

        # clear b3:b8 
        self.chan_cfg[chan] ^= FIRST_ATTEN_MASK

        # set b3:b8 with b
        self.chan_cfg[chan] |= (b << FIRST_ATTEN_START_BIT)

    def set_chan_cfg_second_atten(self, chan: int, val: int):
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
        show_chan_cfg()
        set_chan_cfg()
        set_chan_cfg_first_narrow()

        """

        self._check_channel(chan)
        
        if val < 0 or val > 63:
            raise ARXE.ArxException("Invalid first atten setting: {}".format(val))

        # invert atten. control bits.
        b = (val ^ 0xFFFF) & 0x3F

        # clear b9:b14
        self.chan_cfg[chan] ^= SECOND_ATTEN_MASK

        # set b9:b14 with b
        self.chan_cfg[chan] |= (b << SECOND_ATTEN_START_BIT)
    
    def show_chan_cfg(self, chan: int, verbose: bool = False, cfg: int = None):
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
        
        if cfg == None:
            print("{:016b}".format(self.chan_cfg[chan]))
        else:
            print("{:016b}".format(cfg))

        if verbose:
            print("b0 = lowpass filter (1=wide, 0=narrow)")
            print("b1 = signal on when b1 == b0. off otherwise")
            print("b2 = highpass filter (1=wide, 0=narrow)")
            print("b3:b8 = first attenuation (inverted) in steps of 0.5dB. Max=63(31.5dB)")
            print("b9:b14 = second attenuation (inverted) in steps of 0.5dB Max=63(31.5dB)")
            print("b15 = dc power state (1=on, 0=off)")

    def set_chan_cfg(self, arx_addr: int, chan: int) -> str:
        """Sends the channel configuration to the ARX board.

        Args
        ----
        arx_addr
            ARX board address
        chan
            The ARX channel to configure. 0 indexed.

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
        set_all_chan_cfg()
        set_all_different_chan_cfg()
        set_chan_cfg_input_dc_pwr_off()
        set_chan_cfg_input_dc_pwr_on()
        set_chan_cfg_lowpass_narrow()
        set_chan_cfg_lowpass_wide()
        set_chan_cfg_highpass_narrow()
        set_chan_cfg_highpass wade()
        set_chan_cfg_first_atten()
        set_chan_cfg_second_atten()
        show_chan_cfg()

        """

        self._check_channel(chan)
        
        chan_cfg_str = "{:1x}{:04x}".format(chan, self.chan_cfg[chan])
        rtn = self._sendreceive(arx_addr, 'setc', chan_cfg_str)

        return self._check_rtn(rtn[0], SET_CHAN_CFG_ERRORS)


    def get_chan_cfg(self, arx_addr: int, chan: int) -> int:
        """Return the ARX channel's configuration.

        Args
        ----
        arx_addr
           ARX board address
        chan
           ARX channel number. 0 indexed

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
        show_chan_cfg()

        """

        self._check_channel(chan)

        chan_str = "{:1x}".format(chan)
        rtn = self._sendreceive(arx_addr, 'getc', chan_str)

        return self._check_rtn(rtn[0], SET_CHAN_CFG_ERRORS)


    def set_all_chan_cfg(self, arx_addr, chan: int):
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
           Configuration to send

        Raises
        ------
        ArxException
           Any ARX errors.

        See Also
        --------
        set_all_different_chan_cfg()
        set_chan_cfg()
        set_chan_cfg_input_dc_pwr_off()
        set_chan_cfg_input_dc_pwr_on()
        set_chan_cfg_lowpass_narrow()
        set_chan_cfg_lowpass_wide()
        set_chan_cfg_highpass_narrow()
        set_chan_cfg_highpass wade()
        set_chan_cfg_first_atten()
        set_chan_cfg_second_atten()
        show_chan_cfg()

        """
        
        chan_cfg_str = "{:04x}".format(self.chan_cfg[chan])
        rtn = self._sendreceive(arx_addr, 'seta', chan_cfg_str)

        return self._check_rtn(rtn[0], SET_ALL_CHAN_CFG_ERRORS)

    def set_all_different_chan_cfg(self, arx_addr):
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

        Raises
        ------
        ArxException
           Any ARX errors.

        See Also
        --------
        set_all_chan_cfg()
        set_chan_cfg()
        set_chan_cfg_input_dc_pwr_off()
        set_chan_cfg_input_dc_pwr_on()
        set_chan_cfg_lowpass_narrow()
        set_chan_cfg_lowpass_wide()
        set_chan_cfg_highpass_narrow()
        set_chan_cfg_highpass wade()
        set_chan_cfg_first_atten()
        set_chan_cfg_second_atten()
        show_chan_cfg()

        """

        chan_cfg_str = ''.join("{:04x}".format(x) for x in self.chan_cfg)
        rtn = self._sendreceive(arx_addr, 'sets', chan_cfg_str)

        return self._check_rtn(rtn[0], SET_ALL_DIFFERENT_CHAN_CFG_ERRORS)
    
    def get_board_id(self, arx_addr: int) -> int:
        """Return ARX board ID.

        Args
        ----
        arx_addr
            ARX board address

        Returns
        -------
        int
            8bit integer of the ARX board ID

        Raises
        ------
        ArxException
           Any arrors with the ARX board.

        """
        
        rtn = self._sendreceive(arx_addr, 'arxn')
        return rtn[0]['brd_id']

    def get_board_temp(self, arx_addr: int) -> float:
        """Return ARX board temperature in C.

        Args
        ----
        arx_addr
            ARX board address

        Returns
        -------
        float
           ARX board temperature in C.

        Raises
        ------
        ArxException
           Any arrors with the ARX board.
        
        """

        rtn = self._sendreceive(arx_addr, 'temp')
        return rtn[0]['brd_temp']

    def echo(self, arx_addr: int, val: str) -> str:
        """Return echoed val.

        Args
        ----
        arx_addr
           ARX board address
        val
           ASCII chacters to be echoed.

        Returns
        -------
        str
            Input contained in val

        Raises
        ------
        ArxException
           Any arrors with the ARX board.
        

        """
        rtn = self._sendreceive(arx_addr, 'echo', val)
        return rtn[0]['echo']

    def raw(self, arx_addr: int, cmd: str):
        """Return hex byte stream from given command

        Args
        ----
        arx_addr
           ARX board address

        Raises
        ------
        ArxException
           Any ARX errors.

        """

        rtn = self._sendreceive(arx_addr, 'raw', cmd)
        return rtn[0]['raw']
    

    def get_time(self, arx_addr: int) -> int:
        """Return the board time since setting.

        Args
        ----
        arx_addr
           ARX board address

        Returns
        -------
        int
            Time in seconds based on time board was last set to.

        Raises
        ------
        ArxException
            All ARX related expections.

        """

        rtn = self._sendreceive(arx_addr, 'gtim')
        return rtn[0]['brd_time_sec']

    def set_time(self, arx_addr: int, time: int) -> str:
        """Set the board time in seconds.

        Args
        ----
        arx_addr
            ARX board address.

        time
            Represents time in seconds.

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
        
        time_str = "{}".format(time)
        rtn = self._sendreceive(arx_addr, 'stim', time_str)
        return rtn[0]['err_str']

    
    def get_chan_voltage(self, arx_addr: int, chan: int) -> int:
        """Return 16bit digitized voltage from a specified analog channel

        Args
        ----
        arx_addr
            ARX board address.
        chan
            Specifies channel. 0 indexed

        Returns
        -------
        int
            Digitized voltage as a 16bit value.

        Raises
        ----------
        ArxException


        """

        self._check_channel(chan)
        chan_str = "{:02x}".format(chan)
        rtn = self._sendreceive(arx_addr, 'anlg', chan_str)

        self._check_rtn(rtn[0], ANLG_ERRORS)
        
        return rtn[0]['chan_volts']

    def load_cfg(self, arx_addr: int, loc: int) -> str:
        """Load config from stored memory location.

        Args
        ----
        arx_addr
            ARX board address.
        loc
           Memory location. Allowed: 0,1 or 2.

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

        rtn = self._sendreceive(arx_addr, 'load', loc_str)

        self._check_rtn(rtn[0], LOAD_ERRORS)
        return rtn[0]['err_str']

    def save_cfg(self, arx_addr: int, loc: int) -> str:
        """Save channel configuration to 1 of 3 memory locations.

        Args
        ----
        arx_addr
            ARX board address.
        loc
           Memory location. Allowed: 0,1 or 2.

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

        rtn = self._sendreceive(arx_addr, 'save', loc_str)

        return self._check_rtn(rtn[0], SAVE_ERRORS)


    def get_chan_power(self, arx_addr: int, chan: int) -> int:
        """Return specified channel power

        Args
        ----
        arx_addr
            ARX board address.
        chan
           Channel number. 0 indexed

        Returns
        -------
        str
           Empty string on no errors

        Raises
        ------
        ArxException
            Any ARX error.

        """
        
        self._check_channel(chan)

        chan_str = "{:1x}".format(chan)

        rtn = self._sendreceive(arx_addr, 'powc', chan_str)

        self._check_rtn(rtn[0], None)
        return rtn[0]['chan_power'][0]

    def get_all_chan_power(self, arx_addr: int) -> list:
        """Return power for all ARX channels.

        Args
        ----
        arx_addr
            ARX board address.

        Returns
        -------
        list
           Power for all ARX channels.

        Raises
        ------
        ArxException
            Any ARX error.

        """
        rtn = self._sendreceive(arx_addr, 'powa')

        self._check_rtn(rtn[0], None)
        return rtn[0]['chan_power']

    def get_chan_current(self, arx_addr: int, chan: int) -> int:
        """Return specified channel current

        Args
        ----
        arx_addr
            ARX board address.
        chan
           Channel number. 0 indexed

        Returns
        -------
        int
           Current for specified channel. Units: TBD

        Raises
        ------
        ArxException
            Any ARX error.

        """
        self._check_channel(chan)

        chan_str = "{:1x}".format(chan)
        rtn = self._sendreceive(arx_addr, 'curc', chan_str)

        self._check_rtn(rtn[0], None)
        return rtn[0]['chan_current'][0]

    def get_all_chan_current(self, arx_addr: int) -> list:
        """Return all channel currents

        Args
        ----
        arx_addr
            ARX board address.

        Returns
        -------
        list
           Current for each channel

        Raises
        ------
        ArxException
            Any ARX error.

        """
        rtn = self._sendreceive(arx_addr, 'cura')

        self._check_rtn(rtn[0], None)
        return rtn[0]['chan_current']

    def get_board_current(self, arx_addr: int) -> int:
        """Return ARX board current.

        Args
        ----
        arx_addr
            ARX board address.

        Returns
        -------
        int
           ARX Board current. Units: TBD

        Raises
        ------
        ArxException
            Any ARX error.

        """
        rtn = self._sendreceive(arx_addr, 'curb')

        self._check_rtn(rtn[0], None)
        return rtn[0]['brd_current']

    def search_1wire(self, arx_addr: int) -> int:
        """Search the 1wire buss for devices and returns count.

        Args
        ----
        arx_addr
            ARX board address.

        Returns
        -------
        int
           Count of 1wire devices found on bus.

        Raises
        ------
        ArxException
            Any ARX error.

        """
        rtn = self._sendreceive(arx_addr, 'owse')

        self._check_rtn(rtn[0], ONEWIRE_SEARCH_ERRORS)
        return rtn[0]['1wire_dev_count']

    def get_1wire_count(self, arx_addr: int) -> int:
        """Returns previously found 1wire device count.

        Args
        ----
        arx_addr
            ARX board address.

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

        See Also
        --------
        search_1wire()

        """
        
        rtn = self._sendreceive(arx_addr, 'owdc')

        self._check_rtn(rtn[0], None)
        return rtn[0]['1wire_dev_count']

    def get_1wire_SN(self, arx_addr: int, dev_num: int) -> int:
        """Return specified 1wire serial number

        Args
        ----
        arx_addr
            ARX board address.
        dev_num
           1wire device number. 0 indexed

        Returns
        -------
        int
           Serial number of 1wire device as a 64bit integer

        Raises
        ------
        ArxException
            Any ARX error.

        """

        rtn = self._sendreceive(arx_addr, 'owsn')

        self._check_rtn(rtn[0], ONEWIRE_SERIAL_NUMBER_ERRORS)
        return rtn[0]['1wire_sn']

    def get_1wire_temp(self, arx_addr: int) -> list:
        """Return temperatures in C for all 1wire devices.

        Args
        ----
        arx_addr
            ARX board address.
        
        Returns
        -------
        list
           1wire device temperatures in C

        Raises
        ------
        ArxException
            Any ARX error.

        """

        rtn = self._sendreceive(arx_addr, 'owte')

        self._check_rtn(rtn[0], ONEWIRE_TEMP_ERRORS)
        return rtn[0]['1wire_temp']
    
        