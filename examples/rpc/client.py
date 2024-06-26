#!/usr/bin/env python3

import stimpack.rpc.echo_server

from stimpack.rpc.launch import launch_server

def main():
    client = launch_server(stimpack.rpc.echo_server)
    client.echo('hi')

if __name__ == '__main__':
    main()
