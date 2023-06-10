#!/usr/bin/env python3

import sys

from stimpack.rpc.transceiver import MySocketServer
from stimpack.rpc.util import get_kwargs

def main():
    kwargs = get_kwargs()

    server = MySocketServer(host=kwargs['host'], port=kwargs['port'], name='EchoServer', threaded=False)

    def echo(text):
        print(text)
        sys.stdout.flush()

    server.register_function(echo)
    server.loop()

if __name__ == '__main__':
    main()