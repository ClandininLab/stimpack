class MyMultiCall:
    def __init__(self, transceiver):
        self.transceiver = transceiver
        self.request_list = []

    def __getattr__(self, name):
        def f(*args, **kwargs):
            request = {'name': name, 'args': args, 'kwargs': kwargs}
            self.request_list.append(request)

        return f

    def __call__(self):
        self.transceiver.write_request_list(self.request_list)

    def __str__(self):
        return str(self.request_list)

    def target(self, target_name):
        class dummy_target:
            def __getattr__(target_self, target_attr_name):
                def g(*args, **kwargs):
                    request = {'target': target_name, 
                               'name': target_attr_name, 
                               'args': args, 
                               'kwargs': kwargs}
                    self.request_list.append(request)
                return g
        return dummy_target()