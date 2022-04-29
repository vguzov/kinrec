import logging

#Logging
class ColoredFormatter(logging.Formatter):

    grey = "\x1b[38;20m"
    yellow = "\x1b[33;20m"
    red = "\x1b[31;20m"
    bold_red = "\x1b[31;1m"
    reset = "\x1b[0m"
    format = '%(asctime)s:%(name)s:%(levelname)s::: %(message)s'

    FORMATS = {
        logging.DEBUG: grey + format + reset,
        logging.INFO: grey + format + reset,
        logging.WARNING: yellow + format + reset,
        logging.ERROR: red + format + reset,
        logging.CRITICAL: bold_red + format + reset
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._formatters = {level: logging.Formatter(log_fmt, datefmt='%H:%M:%S') for level, log_fmt in
                       self.FORMATS.items()}

    def format(self, record):
        formatter = self._formatters.get(record.levelno)
        return formatter.format(record)
