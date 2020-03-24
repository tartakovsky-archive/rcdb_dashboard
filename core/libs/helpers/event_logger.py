import io
import csv
import logging


class CSVFormatter(logging.Formatter):

    def __init__(self, template, timestamp=True, write_head=True):
        super().__init__()
        self.template = template
        self.timestamp = timestamp

        self.buffer = io.StringIO()

        header = list(template.keys())

        if timestamp:
            header.insert(0, 'timestamp')

        self.writer = csv.DictWriter(self.buffer, header)
        if write_head:
            self.writer.writeheader()

    def format(self, record):
        row_data = {k: record.__dict__[k] for k in self.template}
        if self.timestamp:
            row_data['timestamp'] = int(record.created) * 1000

        self.writer.writerow(row_data)
        data = self.buffer.getvalue()
        self.buffer.truncate(0)
        self.buffer.seek(0)
        return data.strip()


def log_method_factory(level):
    def log(self, msg=None, *args, **kwargs):
        extra = self.get_extra(kwargs)
        if extra and self.isEnabledFor(level):
            for k in extra:
                kwargs.pop(k)

            self._log(level, msg, args, extra=extra, **kwargs)

    return log


class EventDataLogger(logging.Logger):

    def __init__(self, template, name, raise_invalid_type=True, level=logging.NOTSET):
        super().__init__(name, level)
        self.template = template

        self.raise_invalid_type = raise_invalid_type

    def get_extra(self, log_kwargs):
        if self.raise_invalid_type:
            extra = {}
            for key, _type in self.template.items():
                val = log_kwargs[key]
                if not isinstance(val, _type):
                    try:
                        val = _type(val)
                    except Exception:
                        raise ValueError(f'Expected type of `{key}` is {_type}')
                extra[key] = val
            return extra
        else:
            return {k: log_kwargs[k] for k in self.template}

    log = log_method_factory(logging.INFO)
    info = log_method_factory(logging.INFO)
    debug = log_method_factory(logging.DEBUG)
    error = log_method_factory(logging.ERROR)
    warning = log_method_factory(logging.WARNING)
    critical = log_method_factory(logging.CRITICAL)

    @classmethod
    def init_logging(
        cls,
        template,
        name='event_data_logger',
        level=logging.NOTSET,
        raise_invalid_type=True,
        formatter=None,
        handlers=None,
        file_handler_path=None
    ):
        if not handlers:
            handlers = []

        if file_handler_path:
            handlers.append(logging.FileHandler(file_handler_path))
        elif not handlers:
            handlers.append(logging.StreamHandler())

        if not formatter:
            formatter = CSVFormatter(template)

        logger = cls(template, name, raise_invalid_type, level)

        for handler in handlers:
            handler.setFormatter(formatter)
            logger.addHandler(handler)

        return logger


if __name__ == "__main__":
    # from custom_logging import EventDataLogger

    template = {"foo": int, "bar": str, "x": float}

    logger = EventDataLogger.init_logging(template, name="name", file_handler_path='log.csv')
    logger.log(foo=2, bar='some asdaw"', x=3.2)
    logger.debug(foo=2, bar='some', x=.2)
    logger.info(foo=2, bar='some', x=.2)

    try:
        logger.log(foo=2, bar='some asdaw"')
    except KeyError as e:
        print(e)

    try:
        logger.log(foo=2, bar='some asdaw"', x='wrong type')
    except ValueError as e:
        print(e)