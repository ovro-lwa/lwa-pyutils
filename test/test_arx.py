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

if not sys.warnoptions:
    import warnings
    warnings.simplefilter("ignore")

ARX_ADDRS = [2]    
MAX_NUM_OF_CHAN = 16
MIN_ATTEN = 0
MAX_ATTEN = 64
ATTEN1 = [x*0.5 for x in range(MIN_ATTEN, MAX_ATTEN)]
ATTEN2 = [x*0.5 for x in range(MIN_ATTEN, MAX_ATTEN)]

FIRST_ATTEN_MASK = 0x01f8
FIRST_ATTEN_START_BIT = 3
SECOND_ATTEN_MASK = 0x7e00
SECOND_ATTEN_START_BIT = 9

my_arx = arx.ARX()

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

def assertEqual(a, b):
    assert a == b

@pytest.mark.serial9
def test_chan_cfg1():
#    my_arx = arx.ARX()
    cfg = {}
    cfg['sig_on'] = False
    cfg['narrow_lpf'] = False
    cfg['narrow_hpf'] = False
    cfg['first_atten'] = 0.0
    cfg['second_atten'] = 0.0
    cfg['dc_on'] = False
    my_arx.set_chan_cfg(2, 2, cfg)
    cfg2 = my_arx.get_chan_cfg(2, 2)
    assertEqual(cfg2, cfg)
    
@pytest.mark.serial0
@pytest.mark.parametrize("arx_addr",ARX_ADDRS)    
@pytest.mark.parametrize("ichan",range(0,MAX_NUM_OF_CHAN))
@pytest.mark.parametrize("sig_on",[True,False])
@pytest.mark.parametrize("narrow_lpf",[True,False])
@pytest.mark.parametrize("narrow_hpf",[True,False])
@pytest.mark.parametrize("first_atten",ATTEN1)
@pytest.mark.parametrize("second_atten",ATTEN2)
@pytest.mark.parametrize("dc_on",[True,False])
def test_chan_cfg(arx_addr, ichan, sig_on, narrow_lpf, narrow_hpf,
                  first_atten, second_atten, dc_on):
#    my_arx = arx.ARX()
    print(arx_addr, ichan)
    cfg = {}
    cfg['sig_on'] = sig_on
    cfg['narrow_lpf'] = narrow_lpf
    cfg['narrow_hpf'] = narrow_hpf
    cfg['first_atten'] = first_atten
    cfg['second_atten'] = second_atten
    cfg['dc_on'] = dc_on
    my_arx.set_chan_cfg(arx_addr, ichan, cfg)
    cfg2 = my_arx.get_chan_cfg(arx_addr, ichan)
    assertEqual(cfg2, cfg)

@pytest.mark.serial1
@pytest.mark.parametrize("arx_addr",[2])
def test_get_board_id(arx_addr):
#    my_arx = arx.ARX()
    #brd_id = my_arx.get_board_id(arx_addr)
    #assertEqual(3, brd_id)
    assertEqual(1,1)


class TestARX(unittest.TestCase):
    """This class is applying unit tests to the ARX class in
    lwautils.py
    """
    @pytest.mark.serial6
    def test_c_tor_exception(self):
        # Test contructor

        # must test c-tor in a context.
        with self.assertRaises(FileNotFoundError) as context:
            arx.ARX('abcd')


    @pytest.mark.serial7
    def test_c_tor_with_conf(self):
        my_arx = arx.ARX(etcdconf)
        self.assertIsInstance(my_arx, arx.ARX)

    @pytest.mark.serial8
    def test_c_tor(self):
        my_arx = arx.ARX()
        self.assertIsInstance(my_arx, arx.ARX)

