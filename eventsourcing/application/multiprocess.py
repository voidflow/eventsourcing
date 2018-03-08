import multiprocessing
import time
from time import sleep

import redis

from eventsourcing.application.process import Prompt, System
from eventsourcing.domain.model.events import subscribe, unsubscribe
from eventsourcing.infrastructure.sqlalchemy.manager import SQLAlchemyRecordManager
from eventsourcing.interface.notificationlog import RecordManagerNotificationLog
from eventsourcing.utils.uuids import uuid_from_application_name


class Multiprocess(object):

    def __init__(self, system):
        self.poll_interval = 10
        assert isinstance(system, System)
        self.system = system
        self.os_processes = None

    def start(self):
        assert self.os_processes is None, "Already started"
        self.redis = redis.Redis()

        self.os_processes = []

        for process_class, upstream_classes in self.system.followings.items():

            # Setup tables.
            with process_class(setup_tables=False):
                pass

            # Start operating system process.
            os_process = OperatingSystemProcess(
                application_process_class=process_class,
                upstream_names=[cls.__name__.lower() for cls in upstream_classes],
                poll_interval=self.poll_interval,
            )
            os_process.start()
            self.os_processes.append(os_process)

    def prompt_about(self, process_name=None):
        for process_class in self.system.process_classes:

            patience = 50
            name = process_class.__name__.lower()

            if process_name and process_name != name:
                continue

            num_expected_subscriptions = len(self.system.followings[process_class])
            while self.redis.publish(name, '') < num_expected_subscriptions:
                if patience:
                    sleep(0.1)
                    patience -= 1
                else:
                    raise Exception("Couldn't publish to expected number of subscribers "
                                    "({}, {})".format(name, num_expected_subscriptions))

    def close(self):
        for os_process in self.os_processes:
            self.redis.publish(os_process.application_process_class.__name__.lower(), 'KILL')

        for os_process in self.os_processes:
            os_process.join(timeout=1)

        for os_process in self.os_processes:
            if os_process.is_alive:
                os_process.terminate()

        self.os_processes = None

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


class OperatingSystemProcess(multiprocessing.Process):

    def __init__(self, application_process_class, upstream_names, poll_interval=5, *args, **kwargs):
        super(OperatingSystemProcess, self).__init__(*args, **kwargs)
        self.application_process_class = application_process_class
        self.upstream_names = upstream_names
        self.daemon = True
        self.poll_interval = poll_interval

    def run(self):
        self.redis = redis.Redis()
        self.pubsub = self.redis.pubsub()

        # Construct process application.
        self.process = self.application_process_class()

        # Follow upstream notification logs.
        for upstream_name in self.upstream_names:

            # Subscribe to prompts from upstream channels.
            self.pubsub.subscribe(upstream_name)

            # Obtain a notification log for the upstream process.
            if upstream_name == self.process.name:
                # Upstream is this process's application,
                # so use own notification log.
                notification_log = self.process.notification_log
            else:
                # For a different application, we need to construct a notification
                # log with a record manager that has the upstream application ID.
                # Currently assumes all applications are using the same database
                # and record manager class. If it wasn't the same database,we would
                # to use a remote notification log, and upstream would need to provide
                # an API from which we can pull. It's not unreasonable to have a fixed
                # number of application processes connecting to the same database.
                record_manager = self.process.event_store.record_manager
                assert isinstance(record_manager, SQLAlchemyRecordManager)
                application_id = uuid_from_application_name(upstream_name)
                notification_log = RecordManagerNotificationLog(
                    record_manager=type(record_manager)(
                        session=record_manager.session,
                        record_class=record_manager.record_class,
                        contiguous_record_ids=record_manager.contiguous_record_ids,
                        sequenced_item_class=record_manager.sequenced_item_class,
                        application_id=application_id
                    ),
                    section_size=self.process.notification_log.section_size
                )

            # Make the process follow the upstream notification log.
            self.process.follow(upstream_name, notification_log)

        # Subscribe to broadcast prompts published by the process application.
        subscribe(handler=self.broadcast_prompt, predicate=self.is_prompt)

        # Run a loop.
        try:
            while True:
                try:
                    self.loop_on_prompts()
                    # self.run_loop_with_sleep()
                except Exception as e:
                    # Todo: Log this, or stderr?
                    print("Caught exception: {}".format(e))

        finally:
            unsubscribe(handler=self.broadcast_prompt, predicate=self.is_prompt)

    def loop_on_prompts(self):

        # Run once, in case prompts were missed.
        self.process.run()

        # Loop on getting prompts.
        while True:
            # Note, get_message() returns immediately with None if timeout=0.
            item = self.pubsub.get_message(timeout=self.poll_interval)
            # Todo: Make the poll interval gradually increase if there only timeouts?
            if item is None:
                # Basically, we're polling after each timeout interval.
                self.process.run()
            elif item['type'] == 'message':
                # Identify message, and take appropriate action.
                if item['data'] == b"KILL":
                    # Shutdown.
                    self.pubsub.unsubscribe()
                    self.process.close()
                    break
                else:
                    # Pull from upstream.
                    upstream_application_name = item['channel'].decode('utf8')
                    prompt = Prompt(upstream_application_name)

                    self.process.run(prompt)

                    # Todo: Check the reader position reflects the prompt notification ID? Skip if done.
                    # Todo: Replace above sleep with check the prompted notification is available (otherwise repeat).
                    # Todo: Put the notification ID in the prompt?
                    # Todo: Put the whole notification in the prompt, so if it's the only thing we don't have,
                    # it can be processed.

            elif item['type'] == 'subscribe':
                pass
            elif item['type'] == 'unsubscribe':
                pass

            else:
                raise Exception(item)

    def broadcast_prompt(self, prompt):
        assert isinstance(prompt, Prompt)
        self.redis.publish(prompt.sender_process_name, prompt.end_position)

    @staticmethod
    def is_prompt(event):
        return isinstance(event, Prompt)


    # def run_loop_with_sleep(self):
    #     while True:
    #         self.process.run()
    #         time.sleep(.1)