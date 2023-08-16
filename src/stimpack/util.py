import inspect
import os
from PyQt6.QtWidgets import QMessageBox

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
ICON_PATH = os.path.join(ROOT_DIR, '_assets', 'icon.png')

def get_all_subclasses(cls):
    def ordered_unique_list(seq):
        seen = set()
        return [x for x in seq if x not in seen and not seen.add(x)]
    
    return ordered_unique_list(cls.__subclasses__() + [s for c in cls.__subclasses__() for s in get_all_subclasses(c)])

def make_as(parameter, parent_class):
    """Return parameter as parent class object if it is a dictionary."""
    if type(parameter) is dict: # trajectory-specifying dict
        subclasses = get_all_subclasses(parent_class)
        subclass_names = [sc.__name__ for sc in subclasses]
        
        assert parameter['name'] in subclass_names, f'Unrecognized subclass name {parameter["name"]} for parent class {parent_class.__name__}.'
        
        subclass_candidates = [sc for sc in subclasses if sc.__name__ == parameter['name']]
        if len(subclass_candidates) > 1:
            print(f'Multiple subclasses with name {parameter["name"]} for parent class {parent_class.__name__}.')
            print(f'Choosing the last one: {subclass_candidates[-1]}')
        
        chosen_subclass = subclass_candidates[-1]
        
        # check that all required arguments are specified
        traj_params = inspect.signature(chosen_subclass.__init__).parameters.values()
        for p in traj_params:
            if p.name != 'self' and p.kind == p.POSITIONAL_OR_KEYWORD and p.default is p.empty:
                assert p.name in parameter, f'Required subclass parameter {p.name} not specified.'
        
        # remove name parameter
        parameter.pop('name')
        
        return chosen_subclass(**parameter)
    
    else: # not specified as a dict, just return the original param
        return parameter

def listify(x, type_):
    if isinstance(x, (list, tuple)):
        return x

    if isinstance(x, type_):
        return [x]

    raise ValueError('Unknown input type: {}'.format(type(x)))

def open_message_window(title="Alert", text=""):
    msg = QMessageBox()
    msg.setWindowTitle(title)
    msg.setText(text)
    msg.exec()

