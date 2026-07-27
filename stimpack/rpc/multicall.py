from typing import Any, Callable

from stimpack.rpc.transceiver import MyTransceiver, reject_private_attribute

class MyMultiCall:
    """
    Collects several calls and sends them as one request list.

    This cuts the number of round trips over the socket, and -- more importantly for timing --
    makes the calls arrive together, so they are acted on at approximately the same moment
    rather than spread across several sends.

    Calls are accumulated by attribute access and dispatched when the object itself is called::

        multicall = MyMultiCall(manager)
        multicall.target('visual').start_stim()
        multicall.target('voltage_out').output_step(output_channels='DAC0', ...)
        multicall()     # both sent here, as one request list

    The batch is cleared on dispatch, so the same object can be filled and called again.
    """
    def __init__(self, transceiver:MyTransceiver):
        self.transceiver = transceiver
        self.request_list = []

    def __getattr__(self, name: str) -> Callable[..., None]:
        reject_private_attribute(name)
        def f(*args: Any, **kwargs: Any) -> None:
            request = {'name': name, 'args': args, 'kwargs': kwargs}
            self.request_list.append(request)

        return f

    def __call__(self):
        self.transceiver.write_request_list(self.request_list)
        # Clear after flushing so re-invoking the same MyMultiCall does not re-send every request.
        self.request_list = []

    def __str__(self) -> str:
        return str(self.request_list)

    def target(self, target_name:str):
        """
        Directs all function calls to the remote module with target name.
        """
        class remote_module_target:
            def __getattr__(target_self, target_attr_name: str) -> Callable[..., None]:
                reject_private_attribute(target_attr_name)
                def g(*args: Any, **kwargs: Any) -> None:
                    request = {'target': target_name, 
                               'name': target_attr_name, 
                               'args': args, 
                               'kwargs': kwargs}
                    self.request_list.append(request)
                return g
        return remote_module_target()