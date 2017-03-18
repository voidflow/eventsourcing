import datetime
from time import mktime

import six
from dateutil.relativedelta import relativedelta
from six import with_metaclass

from eventsourcing.domain.model.entity import EventSourcedEntity, AbstractEntityRepository, Created, AttributeChanged
from eventsourcing.domain.model.events import OldDomainEvent, publish, QualnameABCMeta, create_timesequenced_event_id
from eventsourcing.exceptions import RepositoryKeyError
from eventsourcing.utils.time import timestamp_from_uuid, utc_timezone


class MessageLogged(OldDomainEvent):
    def __init__(self, message, entity_id):
        super(MessageLogged, self).__init__(entity_id=entity_id, entity_version=None, message=message)

    @property
    def message(self):
        return self.__dict__['message']

    @property
    def entity_id(self):
        return self.__dict__['entity_id']


def make_bucket_id(log_name, timestamp, bucket_size):
    d = datetime.datetime.utcfromtimestamp(timestamp)

    assert isinstance(d, datetime.datetime)
    if bucket_size.startswith('year'):
        bucket_id = '{:04}'.format(
            d.year
        )
    elif bucket_size.startswith('month'):
        bucket_id = '{:04}-{:02}'.format(
            d.year,
            d.month
        )
    elif bucket_size.startswith('day'):
        bucket_id = '{:04}-{:02}-{:02}'.format(
            d.year,
            d.month,
            d.day
        )
    elif bucket_size.startswith('hour'):
        bucket_id = '{:04}-{:02}-{:02}_{:02}'.format(
            d.year,
            d.month,
            d.day,
            d.hour
        )
    elif bucket_size.startswith('minute'):
        bucket_id = '{:04}-{:02}-{:02}_{:02}-{:02}'.format(
            d.year,
            d.month,
            d.day,
            d.hour,
            d.minute
        )
    elif bucket_size.startswith('second'):
        bucket_id = '{:04}-{:02}-{:02}_{:02}-{:02}-{:02}'.format(
            d.year,
            d.month,
            d.day,
            d.hour,
            d.minute,
            d.second
        )
    else:
        raise ValueError("Bucket size not supported: {}".format(bucket_size))
    return log_name + '_' + bucket_id


ONE_YEAR = relativedelta(years=1)
ONE_MONTH = relativedelta(months=1)
ONE_DAY = relativedelta(days=1)
ONE_HOUR = relativedelta(hours=1)
ONE_MINUTE = relativedelta(minutes=1)
ONE_SECOND = relativedelta(seconds=1)


def next_bucket_starts(timestamp, bucket_size):
    starts = bucket_starts(timestamp, bucket_size)
    duration = bucket_duration(bucket_size)
    return timestamp_from_datetime((starts + duration))


def previous_bucket_starts(timestamp, bucket_size):
    starts = bucket_starts(timestamp, bucket_size)
    duration = bucket_duration(bucket_size)
    return timestamp_from_datetime((starts - duration))


def timestamp_from_datetime(dt):
    assert dt.tzinfo, "Datetime object does not have tzinfo"
    try:
        # Only in Python 3.3+.
        return dt.timestamp()
    except AttributeError:
        return mktime(dt.timetuple()) + (dt.microsecond / 1000000.0)


def bucket_starts(timestamp, bucket_size):
    dt = datetime.datetime.utcfromtimestamp(timestamp)
    assert isinstance(dt, datetime.datetime)
    if bucket_size.startswith('year'):
        return datetime.datetime(dt.year, 1, 1, tzinfo=utc_timezone)
    elif bucket_size.startswith('month'):
        return datetime.datetime(dt.year, dt.month, 1, tzinfo=utc_timezone)
    elif bucket_size.startswith('day'):
        return datetime.datetime(dt.year, dt.month, dt.day, tzinfo=utc_timezone)
    elif bucket_size.startswith('hour'):
        return datetime.datetime(dt.year, dt.month, dt.day, dt.hour, tzinfo=utc_timezone)
    elif bucket_size.startswith('minute'):
        return datetime.datetime(dt.year, dt.month, dt.day, dt.hour, dt.minute, tzinfo=utc_timezone)
    elif bucket_size.startswith('second'):
        return datetime.datetime(dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second, tzinfo=utc_timezone)
    else:
        raise ValueError("Bucket size not supported: {}".format(bucket_size))


BUCKET_SIZES = {
    'year': ONE_YEAR,
    'month': ONE_MONTH,
    'day': ONE_DAY,
    'hour': ONE_HOUR,
    'minute': ONE_MINUTE,
    'second': ONE_SECOND,
}


def bucket_duration(bucket_size):
    try:
        return BUCKET_SIZES[bucket_size]
    except KeyError:
        raise ValueError("Bucket size not supported: {}. Must be one of: {}"
                         "".format(bucket_size, BUCKET_SIZES.keys()))


class Log(EventSourcedEntity):

    class Started(Created):
        pass

    class BucketSizeChanged(AttributeChanged):
        pass

    def __init__(self, name, bucket_size=None, **kwargs):
        super(Log, self).__init__(**kwargs)
        self._name = name
        self._bucket_size = bucket_size

    @property
    def name(self):
        return self._name

    @property
    def started_on(self):
        return self.created_on

    @property
    def bucket_size(self):
        return self._bucket_size

    def append_message(self, message):
        assert isinstance(message, six.string_types)
        domain_event_id = create_timesequenced_event_id()
        entity_bucket_id = make_bucket_id(self.name, timestamp_from_uuid(domain_event_id), self.bucket_size)
        event = MessageLogged(
            entity_id=entity_bucket_id,
            message=message,
        )
        publish(event)
        return event


class LogRepository(AbstractEntityRepository):

    def get_or_create(self, log_name, bucket_size):
        """
        Gets or creates a log.

        :rtype: Log
        """
        try:
            return self[log_name]
        except RepositoryKeyError:
            return start_new_log(log_name, bucket_size=bucket_size)


def start_new_log(name, bucket_size=None):
    if bucket_size is None:
        bucket_size = 'year'
    if bucket_size not in BUCKET_SIZES:
        raise ValueError("Bucket size '{}' not supported, must be one of: {}"
                         "".format(bucket_size, BUCKET_SIZES.keys()))
    event = Log.Started(
        entity_id=name,
        name=name,
        bucket_size=bucket_size
    )
    entity = Log.mutate(event=event)
    publish(event)
    return entity


def get_logger(log):
    """
    :rtype: Logger
    """
    return Logger(log=log)


class Logger(with_metaclass(QualnameABCMeta)):

    def __init__(self, log):
        assert isinstance(log, Log), type(log)
        self._log = log

    def log(self, message):
        return self._log.append_message(message)
