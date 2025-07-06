from stimpack.rpc.transceiver import MyTransceiver

class MyMultiCall:
    """
    A class to collect multiple function calls and send them as a single request list.
    This is useful for reducing the number of requests sent over the network 
        and for sending multiple requests approximately coincidentally.
    """
    def __init__(self, transceiver:MyTransceiver):
        self.transceiver = transceiver
        self.request_list = []

    def __getattr__(self, name) -> callable:
        def f(*args, **kwargs) -> None:
            request = {'name': name, 'args': args, 'kwargs': kwargs}
            self.request_list.append(request)

        return f

    def __call__(self):
        self.transceiver.write_request_list(self.request_list)

    def __str__(self) -> str:
        return str(self.request_list)

    def target(self, target_name:str):
        """
        Directs all function calls to the remote module with target name.
        """
        class remote_module_target:
            def __getattr__(target_self, target_attr_name:str) -> callable:
                def g(*args, **kwargs) -> None:
                    request = {'target': target_name, 
                               'name': target_attr_name, 
                               'args': args, 
                               'kwargs': kwargs}
                    self.request_list.append(request)
                return g
        return remote_module_target()