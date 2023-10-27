#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DAQ (data acquisition) device classes

@author: minseung
"""

from stimpack.rpc.multicall import MyMultiCall

class DAQ():
    def __init__(self):
        pass

    def handle_request_list(self, request_list):
        for request in request_list:
            if request['name'] in dir(self):
                # If the request is a method of this class, execute it.
                getattr(self, request['name'])(*request['args'], **request['kwargs'])
            else:
                print(f"{self.__class__.__name__}: Requested method {request['name']} not found.")
    
    def send_trigger(self):
        print('Warning, send_trigger method has not been overwritten by a child class!')
        pass

class DAQonServer(DAQ):
    '''
    Dummy DAQ class for when the DAQ resides on the server, so that we can call methods as if the DAQ is on the client side.
    Assumes that server has registered functions "daq_send_trigger" and "daq_output_step".
    '''
    def __init__(self):
        super().__init__()  # call the parent class init method
        self.manager = None
    def set_manager(self, manager):
        self.manager = manager
    def send_trigger(self, multicall=None, **kwargs):
        if multicall is not None and isinstance(multicall, MyMultiCall):
            multicall.daq_send_trigger(**kwargs)
            return multicall
        if self.manager is not None:
            self.manager.daq_send_trigger(**kwargs)
    def output_step(self, multicall=None, **kwargs):
        if multicall is not None and isinstance(multicall, MyMultiCall):
            multicall.daq_output_step(**kwargs)
            return multicall
        if self.manager is not None:
            self.manager.daq_output_step(**kwargs)
