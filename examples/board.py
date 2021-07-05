import lwautils.lwa_arx as arx
import lwautils.ArxException as arxe

NUMCHAN = 16
ma = arx.ARX()

def show_all_cfg(acfg, key):
    print(key)
    print(" ", [acfg[i][key] for i in range(0:NUMCHAN)])

def show_arr(arr, name):
    print(name)
    print(" ", [arr[i] for i in range(0:NUMCHAN)])

try:
    # get all channel configurations for ARX board addr = 31
    arx_addr = 31
    all_cfg = ma.get_all_chan_cfg(arx_addr)

    # show dc_on state for all channels
    show_all_cfg(all_cfg, 'dc_on')

    # show first attenuation setting for all channels
    show_all_cfg(all_cfg, 'first_atten')

    # get and show all channels power
    all_pwr = ma.get_all_chan_power(arx_addr)
    show_arr(all_pwr, 'power[W]')

    # get and set all channels to same configuration. In this case
    # set dc_on to False
    cfg = ma.get_chan_cfg(arx_addr)
    cfg['dc_on'] = False
    # uncomment to use!!
    # ma.set_all_chan_cfg(arx_addr, cfg)
except arxe.ArxException as ae:
    print(ae)
