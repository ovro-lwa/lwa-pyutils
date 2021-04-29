"""Test code for lwa_arx.py
   execute 'pytest' to run tests.
"""

import pytest
import sys
from pathlib import Path
import unittest
sys.path.append(str(Path('..')))

import lwautils.lwa_arx as arx

from pkg_resources import Requirement, resource_filename
etcdconf = resource_filename(Requirement.parse("lwa-pyutils"), "lwautils/conf/etcdConfig.yml")

MAX_NUM_OF_CHAN = 4
FIRST_ATTEN_MASK = 0x01f8
FIRST_ATTEN_START_BIT = 3
SECOND_ATTEN_MASK = 0x7e00
SECOND_ATTEN_START_BIT = 9

def get_first_atten(val, fa):
    b = (val ^ 0xFFFF) & 0x3F

    # clear b3:b8 
    fa &= ~FIRST_ATTEN_MASK

    # set b3:b8 with b
    fa |= (b << FIRST_ATTEN_START_BIT)

    print('val: {}, mask: {:016b}, b: {:016b}, fa: {:016b}'.format(val, FIRST_ATTEN_MASK, b, fa))
    return fa

def get_second_atten(val, fa):
    b = (val ^ 0xFFFF) & 0x3F

    # clear b9:b14
    fa &= ~SECOND_ATTEN_MASK

    # set b9:b14 with b
    fa |= (b << SECOND_ATTEN_START_BIT)

    print('val: {}, mask: {:016b}, b: {:016b}, fa: {:016b}'.format(val, SECOND_ATTEN_MASK, b, fa))
    return fa

class TestARX(unittest.TestCase):
    """This class is applying unit tests to the ARX class in
    lwautils.py
    """
    @pytest.mark.serial
    def test_c_tor_exception(self):
        # Test contructor

        # must test c-tor in a context.
        with self.assertRaises(FileNotFoundError) as context:
            arx.ARX('abcd')


    @pytest.mark.serial
    def test_c_tor_with_conf(self):
        my_arx = arx.ARX(etcdconf)
        self.assertIsInstance(my_arx, arx.ARX)

    @pytest.mark.serial
    def test_c_tor(self):
        my_arx = arx.ARX()
        self.assertIsInstance(my_arx, arx.ARX)

    @pytest.mark.serial
    def test_get_board_id(self):
        my_arx = arx.ARX()
        brd_id = my_arx.get_board_id(2)
        self.assertEqual(3, brd_id)

    @pytest.mark.serial
    def test_set_chan_cfg_lowpass_narrow(self):
        my_arx = arx.ARX()
        for ichan in range(0,MAX_NUM_OF_CHAN):
            my_arx.set_chan_cfg_lowpass_narrow(ichan)
            self.assertEqual(0, my_arx.chan_cfg[ichan])

    @pytest.mark.serialLPNARX
    def test_set_chan_cfg_lowpass_narrow_on_ARX(self):
        my_arx = arx.ARX()
        for bsig in [False,True]:
            for ichan in range(0,MAX_NUM_OF_CHAN):
                my_arx.set_chan_cfg_signal_on_state(ichan, bsig)
                my_arx.set_chan_cfg_lowpass_narrow(ichan)
                my_arx.set_chan_cfg(2, ichan)
                arx_chan_cfg = my_arx.get_chan_cfg(2, ichan)
                self.assertEqual(my_arx.chan_cfg[ichan], arx_chan_cfg)
            
    @pytest.mark.serial
    def test_set_chan_cfg_lowpass_wide(self):
        my_arx = arx.ARX()
        val = {}
        val[False] = 0b0000000000000001
        val[True] = 0b0000000000000011
        for bsig in [False,True]:
            for ichan in range(0,MAX_NUM_OF_CHAN):
                my_arx.set_chan_cfg_signal_on_state(ichan, bsig)
                my_arx.set_chan_cfg_lowpass_wide(ichan)
                self.assertEqual(val[bsig], my_arx.chan_cfg[ichan])

    @pytest.mark.serialLPWARX
    def test_set_chan_cfg_lowpass_wide_on_ARX(self):
        my_arx = arx.ARX()
        for bsig in [False,True]:
            for ichan in range(0,MAX_NUM_OF_CHAN):
                my_arx.set_chan_cfg_signal_on_state(ichan, bsig)
                my_arx.set_chan_cfg_lowpass_wide(ichan)
                my_arx.set_chan_cfg(2, ichan)
                arx_chan_cfg = my_arx.get_chan_cfg(2, ichan)
                self.assertEqual(my_arx.chan_cfg[ichan], arx_chan_cfg)

    # with signal bit on.            
    @pytest.mark.serial
    def test_set_chan_cfg_signal_on_state(self):
        my_arx = arx.ARX()
        for ichan in range(0,MAX_NUM_OF_CHAN):
            my_arx.set_chan_cfg_signal_on_state(ichan, True)
            my_arx.set_chan_cfg_lowpass_narrow(ichan)
            self.assertEqual(0, my_arx.chan_cfg[ichan])
            my_arx.set_chan_cfg_lowpass_wide(ichan)
            self.assertEqual(0b0000000000000011, my_arx.chan_cfg[ichan])

    @pytest.mark.serial
    def test_set_chan_cfg_highpass_narrow(self):
        my_arx = arx.ARX()
        for ichan in range(0,MAX_NUM_OF_CHAN):
            my_arx.set_chan_cfg_highpass_narrow(ichan)
            self.assertEqual(0, my_arx.chan_cfg[ichan])

    @pytest.mark.serial
    def test_set_chan_cfg_highpass_wide(self):
        my_arx = arx.ARX()
        for ichan in range(0,MAX_NUM_OF_CHAN):
            my_arx.set_chan_cfg_highpass_wide(ichan)
            self.assertEqual(0b0000000000000100, my_arx.chan_cfg[ichan])

    @pytest.mark.fatten
    def test_set_chan_cfg_first_attten(self):
        my_arx = arx.ARX()
        v = 3
        for iatten in range(0, 64):
            v = get_first_atten(iatten, v);
            for ichan in range(0,MAX_NUM_OF_CHAN):
                my_arx.set_chan_cfg_lowpass_wide(ichan)
                my_arx.set_chan_cfg_first_atten(ichan, iatten)
                self.assertEqual(v, my_arx.chan_cfg[ichan])

    @pytest.mark.satten
    def test_set_chan_cfg_second_attten(self):
        my_arx = arx.ARX()
        v = 3
        for iatten in range(0, 64):
            v = get_second_atten(iatten, v);
            for ichan in range(0,MAX_NUM_OF_CHAN):
                my_arx.set_chan_cfg_lowpass_wide(ichan)
                my_arx.set_chan_cfg_second_atten(ichan, iatten)
                self.assertEqual(v, my_arx.chan_cfg[ichan])
            
            
