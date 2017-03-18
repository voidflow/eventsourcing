from abc import ABCMeta, abstractproperty

import six

from eventsourcing.domain.model.events import OldDomainEvent


class AbstractSnapshop(six.with_metaclass(ABCMeta)):

    @abstractproperty
    def topic(self):
        """
        Path to the class of the snapshotted entity.
        """

    @abstractproperty
    def attrs(self):
        """
        State of the snapshotted entity.
        """

    @abstractproperty
    def at_event_id(self):
        """
        Event ID.
        """


class Snapshot(OldDomainEvent, AbstractSnapshop):

    def __init__(self, entity_id, topic, attrs, domain_event_id):
        super(Snapshot, self).__init__(entity_id=entity_id, topic=topic, attrs=attrs, domain_event_id=domain_event_id,
                                       entity_version=None)

    @property
    def topic(self):
        """Path to the class.
        """
        return self.__dict__['topic']

    @property
    def attrs(self):
        """Attributes of the instance.
        """
        return self.__dict__['attrs']

    @property
    def at_event_id(self):
        return self.__dict__['domain_event_id']
