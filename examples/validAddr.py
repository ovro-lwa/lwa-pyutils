#!/usr/bin/env python

# Simple application to list online/offline ARX addresses

import lwautils.lwa_arx as arx

def find():
    """find reports which ARX address are online/offline
    """
    
    ma = arx.ARX()
    for id in range(0,50):
        try:
            ma.get_board_info(id)
            print("Online: {}".format(id))
        except:
            print("Offline: {}".format(id))
            pass

if __name__ == "__main__":
    find()

