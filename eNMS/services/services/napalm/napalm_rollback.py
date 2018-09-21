from sqlalchemy import Column, ForeignKey, Integer

from eNMS.services.connections import napalm_connection
from eNMS.services.models import multiprocessing, Service, service_classes


class NapalmRollbackService(Service):

    __tablename__ = 'NapalmRollbackService'

    id = Column(Integer, ForeignKey('Service.id'), primary_key=True)
    device_multiprocessing = True

    __mapper_args__ = {
        'polymorphic_identity': 'napalm_rollback_service',
    }

    def job(self, incoming_payload):
        results = {}
        for device in self.task.compute_targets():
            try:
                napalm_driver = napalm_connection(device)
                napalm_driver.open()
                napalm_driver.rollback()
                napalm_driver.close()
                result, success = 'Rollback successful', True
            except Exception as e:
                results[device.name] = f'task failed ({e})'
                results['success'] = False
        return results


service_classes['Napalm Rollback Service'] = NapalmRollbackService
