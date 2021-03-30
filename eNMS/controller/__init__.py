from functools import wraps

from eNMS.controller.administration import AdministrationController
from eNMS.controller.automation import AutomationController
from eNMS.controller.custom import CustomController
from eNMS.controller.inventory import InventoryController


class Controller(
    AdministrationController,
    AutomationController,
    CustomController,
    InventoryController,
):
    def register_endpoint(self, func):
        setattr(self, func.__name__, func)

        @wraps(func)
        def wrapper(*args, **kwargs):
            return func(*args, **kwargs)

        return wrapper


controller = Controller()
