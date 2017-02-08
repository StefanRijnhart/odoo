# -*- coding: utf-8 -*-
try:
    import simplejson as json
except ImportError:
    import json

import logging
import pprint
import werkzeug

from openerp import http, SUPERUSER_ID
from openerp.http import request

_logger = logging.getLogger(__name__)


class BuckarooController(http.Controller):
    _return_url = 'https://www.roetz-bikes.com/payment/buckaroo/return'
    _cancel_url = 'https://www.roetz-bikes.com/payment/buckaroo/cancel'
    _exception_url = 'https://www.roetz-bikes.com/payment/buckaroo/error'
    _reject_url = 'https://www.roetz-bikes.com/payment/buckaroo/reject'

    @http.route([
        '/payment/buckaroo/return',
        '/payment/buckaroo/cancel',
        '/payment/buckaroo/error',
        '/payment/buckaroo/reject',
    ], type='http', auth='none')
    def buckaroo_return(self, **post):
        """ Buckaroo."""
        _logger.info('Buckaroo: entering form_feedback with post data %s', pprint.pformat(post))  # debug
        request.registry['payment.transaction'].form_feedback(request.cr, SUPERUSER_ID, post, 'buckaroo', context=request.context)
        if post.get('brq_statuscode') in ('190', '790', '791', '792', '793'):
            return_url = '/shop/payment/validate'        
        else:
            return_url = '/page/payment-failed'
        #return_url = post.pop('return_url', '')
        #_logger.info(return_url)
        #if not return_url:
        #    data ='' + post.pop('ADD_RETURNDATA', '{}').replace("'", "\"")
        #    custom = json.loads(data)
        #    return_url = custom.pop('return_url', '/')
        #    _logger.info(return_url)
        return werkzeug.utils.redirect(return_url)
