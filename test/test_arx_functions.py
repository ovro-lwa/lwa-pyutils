#!/usr/bin/env python

import lwautils.lwa_arx as arx
import lwautils.ArxException as arxe

ma = arx.ARX()

ADDRS = [17, 21, 27, 31, 45]
CHANS = [0, 15]

def getBoardInfo(addr):
    print("  Testing get_board_info...")
    bi = ma.get_board_info(addr)
    for k,v in bi.items():
        print("    {}: {}".format(k,v))
    print("  Done")

def getMicroControllerTemp(addr):
    print("  Testing get_microcontroller_temp...")
    mt = ma.get_microcontroller_temp(addr)
    print("    Temp: {}C".format(mt))
    print("  Done")

def echo(addr):
    print("  Testing echo...")
    e = ma.echo(addr, 1234)
    print("    echo: {}".format(e))
    e = ma.echo(addr, "abc")
    print("    echo: {}".format(e))
    e = ma.echo(addr, "Ab12")
    print("    echo: {}".format(e))
    print("  Done")

def raw(addr):
    print("  Testing raw...")
    rtn = ma.raw(addr, "ECHO12")
    print("    {}".format(rtn))
    print("  Done")

def getChanVoltage(addr, chans):
    print("  Testing get_chan_voltage...")
    for chan in chans:
        rtn = ma.get_chan_voltage(addr, chan)
        print("  chan: {}  {}V".format(chan, rtn))
    print("  Done")

def getChanPower(addr, chans):
    print("  Testing get_chan_power...")
    for chan in chans:
        rtn = ma.get_chan_power(addr, chan)
        print("  chan: {}  {}W".format(chan, rtn))
    print("  Done")

def getAllChanPower(addr):
    print("  Testing get_all_chan_power...")
    rtn = ma.get_all_chan_power(addr)
    for chan in range(len(rtn)):
        print("  chan: {}  {}W".format(chan, rtn[chan]))
    print("  Done")

def getChanCurrent(addr, chans):
    print("  Testing get_chan_current...")
    for chan in chans:
        rtn = ma.get_chan_current(addr, chan)
        print("  chan: {}  {}A".format(chan, rtn))
    print("  Done")

def getAllChanCurrent(addr):
    print("  Testing get_all_chan_current...")
    rtn = ma.get_all_chan_current(addr)
    for chan in range(len(rtn)):
        print("  chan: {}  {}A".format(chan, rtn[chan]))
    print("  Done")

def getBoardCurrent(addr):
    print("  Testing get_board_current...")
    mt = ma.get_board_current(addr)
    print("    Board Current: {}A".format(mt))
    print("  Done")

def get1wireCount(addr):
    print("  Testing get_1wire_count...")
    mt = ma.get_1wire_count(addr)
    print("    1wire Count: {}".format(mt))
    print("  Done")

def get1wireSN(addr, dev_count):
    print("  Testing get_1wire_SN...")
    for d in range(dev_count):
        mt = ma.get_1wire_SN(addr, d)
        print("    dev: {}  SN: {}".format(d, mt))
    print("  Done")

def get1wireTemp(addr):
    print("  Testing get_1wire_Temp...")
    mt = ma.get_1wire_temp(addr)
    for d in range(len(mt)):
        print("    dev: {}  Temp: {}C".format(d, mt[d]))
    print("  Done")
    
for addr in ADDRS:
    try:
        print("Board Address: {}".format(addr))
        getBoardInfo(addr)
        getMicroControllerTemp(addr)
        echo(addr)
        getChanVoltage(addr, CHANS)
        getChanPower(addr, CHANS)
        getAllChanPower(addr)
        getChanCurrent(addr, CHANS)
        getAllChanCurrent(addr)
        getBoardCurrent(addr)
        get1wireCount(addr)
        get1wireTemp(addr)
        get1wireSN(addr, 3)
        raw(addr)
    except arxe.ArxException as ae:
        print(ae)
        pass
