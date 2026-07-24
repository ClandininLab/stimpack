#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DAQ (data acquisition) device classes

@author: minseung
"""
import warnings, traceback
from typing import Optional

from stimpack.rpc.multicall import MyMultiCall
from stimpack.rpc.transceiver import MySocketClient, is_broadcast

class DAQ():
    def __init__(self, verbose=False):
        self.verbose = verbose
        self.error_reporter = None  # optional callback(level, text); set by BaseServer to reach the client
        pass

    def on_connection_close(self):
        pass

    def handle_request_list(self, request_list):
        for request in request_list:
            if request['name'] in dir(self):
                # If the request is a method of this class, execute it, isolating handler errors.
                try:
                    getattr(self, request['name'])(*request.get('args', []), **request.get('kwargs', {}))
                except Exception as e:
                    warnings.warn(f"{self.__class__.__name__}: error handling '{request['name']}':\n{traceback.format_exc()}")
                    if self.error_reporter is not None:
                        try:
                            self.error_reporter('error', f"daq: {request['name']}: {type(e).__name__}: {e}")
                        except Exception:
                            pass
            else:
                # Silently skipping an unknown name is how a mis-named DAQ call (e.g. an old
                # pre-target() name, or a camelCase typo) ends up never firing. Report it.
                msg = f"{self.__class__.__name__}: no such method '{request['name']}'"
                if is_broadcast(request):
                    continue          # a target('all') broadcast this module simply doesn't handle
                warnings.warn(msg)
                if self.error_reporter is not None:
                    try:
                        self.error_reporter('error', f'daq: {msg}')
                    except Exception:
                        pass
    
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
        if multicall is not None and isinstance(multicall, MyMultiCall):
            multicall.target('daq').send_trigger(**kwargs)
        if self.manager is not None:
            self.manager.target('daq').send_trigger(**kwargs)

    def output_step(self, multicall:Optional[MyMultiCall]=None, **kwargs):
        if multicall is not None and isinstance(multicall, MyMultiCall):
            multicall.target('daq').output_step(**kwargs)
        if self.manager is not None:
            self.manager.target('daq').output_step(**kwargs)
