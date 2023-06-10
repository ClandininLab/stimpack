import sys, json

from collections import defaultdict
from socket import socket
from threading import Thread

def start_daemon_thread(target):
    t = Thread(target=target)
    t.daemon = True
    t.start()

def stream_is_binary(stream):
    return 'b' in stream.mode

def find_free_port(host=''):
    # ref: https://stackoverflow.com/a/36331860
    s = socket()
    s.bind((host, 0))
    name = s.getsockname()[1]
    s.close()
    return name

def get_kwargs():
    try:
        kwargs = JSONCoderWithTuple.decode(sys.argv[1])
    except:
        kwargs = {}

    return defaultdict(lambda: None, kwargs)

def get_from_dict(dictionary, keys, default=None, remove=False):
    if isinstance(keys, str):
        keys = [keys]
    return_list = []
    for k in keys:
        if k in dictionary:
            return_list.append(dictionary.pop(k) if remove else dictionary[k])
        else:
            return_list.append(default)
    return return_list[0] if len(return_list) == 1 else return_list

class JSONCoderWithTuple():
    def encode(obj):
        def hint_tuples(item):
            if isinstance(item, tuple):
                return {'__tuple__': True, 'items': item}
            if isinstance(item, list):
                return [hint_tuples(e) for e in item]
            if isinstance(item, dict):
                return {key: hint_tuples(value) for key, value in item.items()}
            else:
                return item

        return json.JSONEncoder().encode(hint_tuples(obj))
    
    def decode(obj):
        def hinted_tuple_hook(obj):
            if '__tuple__' in obj:
                return tuple(obj['items'])
            else:
                return obj
            
        return json.loads(obj, object_hook=hinted_tuple_hook)