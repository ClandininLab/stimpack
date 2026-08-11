#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DAQ (data acquisition) device classes

@author: minseung
"""
from typing import Optional

from stimpack.module import BaseModule
from stimpack.rpc.multicall import MyMultiCall
from stimpack.rpc.transceiver import MySocketClient

class DAQ(BaseModule):
    module_name = 'daq'   # prefix on errors reported to the client

    def send_trigger(self, *args, **kwargs):
        print('Warning, send_trigger method has not been overwritten by a child class!')
        pass

class DAQonServer(DAQ):
    '''
    Dummy DAQ class for when the DAQ resides on the server, so that we can call methods as if the DAQ is on the client side.
    '''
    def __init__(self, verbose=False):
        super().__init__(verbose=verbose)  # call the parent class init method
        self.manager = None

    def set_manager(self, manager:MySocketClient):
        self.manager = manager

    def send_trigger(self, multicall:Optional[MyMultiCall]=None, **kwargs):
        # Queued in the batch OR sent now, never both: both would reach the hardware twice --
        # once immediately and once when the batch dispatches.
        if multicall is not None and isinstance(multicall, MyMultiCall):
            multicall.target('voltage_out').send_trigger(**kwargs)
            return multicall
        if self.manager is not None:
            self.manager.target('voltage_out').send_trigger(**kwargs)

    def output_step(self, multicall:Optional[MyMultiCall]=None, **kwargs):
        if multicall is not None and isinstance(multicall, MyMultiCall):
            multicall.target('voltage_out').output_step(**kwargs)
            return multicall
        if self.manager is not None:
            self.manager.target('voltage_out').output_step(**kwargs)
