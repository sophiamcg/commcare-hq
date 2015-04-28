import logging
from datetime import datetime

from dimagi.utils.couch.database import get_db
from corehq.toggles import BLANKET

from .factory import RequestModelFactory, ResponseModelFactory
from .models import *
from .profiler import Profiler

Logger = logging.getLogger('blanket')


class BlanketMiddleware(object):

    def __init__(self, *args, **kwargs):
        self.db = get_db(postfix='blanket')

    def _is_enabled(user=None, domain=None):
        return BLANKET.enabled(user) or BLANKET.enabled(domain)

    def time_taken(self, start_time, end_time):
        d = end_time - start_time
        return d.seconds * 1000 + d.microseconds / 1000

    def process_request(self, request):
        if True and not request.path.startswith('/blanket'):

            request.blanket_is_intercepted = True
            request.profiler = Profiler()
            request.profiler.start_python_profiler()
            try:
                request_model = RequestModelFactory(request).construct_request_model()
                self.db.save_doc(request_model)
                request.blanket_request_id = request_model['_id']
            except Exception, e:
                print 'NOT LOGGED'
                request.blanket_is_intercepted = False

    def _process_response(self, response, request):

        request.profiler.stop_python_profiler()

        doc = self.db.get(request.blanket_request_id)
        request_model = BlanketRequestDocument.wrap(doc)
        request_model.line_profile = request.profiler.finalize()
        request_model.end_time = datetime.utcnow()
        request_model.time_taken = self.time_taken(request_model.start_time, request_model.end_time)


        response_model = ResponseModelFactory(response).construct_response_model()
        self.db.save_doc(response_model)

        request_model.response = response_model
        self.db.save_doc(request_model)


    def process_response(self, request, response):
        if getattr(request, 'blanket_is_intercepted', False):
            self._process_response(response, request)
        return response
