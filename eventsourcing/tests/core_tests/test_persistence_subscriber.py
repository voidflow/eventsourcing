import unittest

from eventsourcing.application.policies import PersistencePolicy, PersistenceSubscriber, TimestampEntityEvent
from eventsourcing.domain.model.events import OldDomainEvent, VersionEntityEvent, publish
from eventsourcing.infrastructure.eventstore import AbstractEventStore

try:
    from unittest import mock
except:
    import mock


class TestPersistenceSubscriber(unittest.TestCase):
    def tearDown(self):
        # Close the persistence subscriber.
        self.persistence_subscriber.close()

    def test_published_events_are_appended_to_event_store(self):
        # Setup the persistence subscriber with an event store.
        event_store = mock.Mock(spec=AbstractEventStore)
        self.persistence_subscriber = PersistenceSubscriber(event_store=event_store)

        # Check the event store's append method has NOT been called.
        assert isinstance(event_store, AbstractEventStore)
        self.assertEqual(0, event_store.append.call_count)

        # Publish a (mock) domain event.
        domain_event = mock.Mock(spec=OldDomainEvent)
        publish(domain_event)

        # Check the append method HAS been called once with the domain event.
        event_store.append.assert_called_once_with(domain_event)


class TestNewPersistenceSubscriber(unittest.TestCase):
    def setUp(self):
        # Setup the persistence subscriber with an event store.
        self.ve_es = mock.Mock(spec=AbstractEventStore)
        self.te_es = mock.Mock(spec=AbstractEventStore)
        self.ps = PersistencePolicy(
            version_entity_event_store=self.ve_es,
            timestamp_entity_event_store=self.te_es,
        )

    def tearDown(self):
        # Close the persistence subscriber.
        self.ps.close()

    def test_published_events_are_appended_to_event_store(self):
        # Check the event store's append method has NOT been called.
        assert isinstance(self.ve_es, AbstractEventStore)
        assert isinstance(self.te_es, AbstractEventStore)
        self.assertEqual(0, self.ve_es.append.call_count)
        self.assertEqual(0, self.te_es.append.call_count)

        # Publish a (mock) version entity event.
        domain_event1 = mock.Mock(spec=VersionEntityEvent)
        publish(domain_event1)

        # Check the append method HAS been called once with the domain event.
        self.ve_es.append.assert_called_once_with(domain_event1)
        self.assertEqual(0, self.te_es.append.call_count)

        # Publish a (mock) timestamp entity event.
        domain_event2 = mock.Mock(spec=TimestampEntityEvent)
        publish(domain_event2)

        # Check the append method HAS been called once with the domain event.
        self.ve_es.append.assert_called_once_with(domain_event1)
        self.te_es.append.assert_called_once_with(domain_event2)
