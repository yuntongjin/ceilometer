#
# Copyright 2015 Intel, Inc
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import collections
import uuid

from oslo_log import log
from oslo_utils import timeutils

from ceilometer.i18n import _
from ceilometer import transformer
from ceilometer.event.storage import models
from copy import deepcopy

LOG = log.getLogger(__name__)

def traits_to_hash(traits):
    pass

class BracketerTransformer(transformer.EventTransformerBase):
    """Multi event bracketer transformer.

    Transformer that performs bracketer operations
    over one or more event.
    """

    def __init__(self, source=None, target=None, **kwargs):
        self.source = source or {}
        self.target = target or {}
        self.required_events = []

        super(BracketerTransformer, self).__init__(**kwargs)
        for event in self.source:
            self.required_events.append(event.get('event_type'))

        self.begin_event_type = self.required_events[0]
        self.end_event_type = self.required_events[-1]

        self.target_trait_name = self.target['traits'].get('name')
        self.target_trait_type = self.target['traits'].get('type')

        self.misconfigured = len(self.required_events) < 2
        if not self.misconfigured:
            self.cache = collections.defaultdict(dict)
            self.latest_timestamp = None
        else:
            LOG.warn(_('Event transformer must use at least 2 event'))

    def _update_cache(self, _event):
        """Update the cache with the latest sample."""
        event_type = _event.event_type
        if event_type not in self.required_events:
            return

        for trait in _event.traits:
            if trait.name == 'request_id':
                request_id = trait.value
                break
        #if resource_id is none ?

        self.cache[request_id][event_type] = _event

    def _check_requirements(self, resource_id):
        """Check if all the required events are available in the cache."""
        for required_event in self.required_events:
            if (required_event not in self.cache[resource_id] 
            or not self.cache[resource_id][required_event]):
                return False

        return True

    def _bracketer_calculate(self, request_id):
        """Evaluate the brackelet expression and return a new event if successful."""
        try:
            begin_event = self.cache[request_id][self.begin_event_type]
            end_event = self.cache[request_id][self.end_event_type]

            result = timeutils.delta_seconds(begin_event.generated,
                                             end_event.generated)

            if result < 0:
                LOG.warn(_('brackelet result %(result)s'
                           'from %(begin_event)s: %(end_event)s < 0'),
                         {'result': result,
                          'begin_event': begin_event,
                          'end_event': end_event})
                return

            event_type = self.target.get('event_type')
            message_id = uuid.uuid4()
            when = timeutils.utcnow()
            #End_event has resource_id trait
            traits = deepcopy(end_event.traits)
            latency_trait = models.Trait(self.target_trait_name,
                                         self.target_trait_type,
                                         result)
            traits.append(latency_trait)
            raw = {}

            event = models.Event(message_id, event_type, when, traits, raw)
            print event
            return event
        except Exception:
            LOG.warn(_('Unable to evaluate Evaluate the brackelet expression'))

    def handle_event(self, context, _event):
        self._update_cache(_event)
        new_event = []
        # TODO: context has request_id, no need for loop here
        for request_id in self.cache:
            if self._check_requirements(request_id):
                new_event.append(self._bracketer_calculate(request_id))
                self.cache[request_id][self.begin_event_type] = None
                self.cache[request_id][self.end_event_type] = None
            else:
                LOG.warn(_('Unable to perform calculation, not all of '
                            '{%s} are present'),
                            ', '.join(self.required_events))

        return new_event

    def flush(self, context):
        pass
