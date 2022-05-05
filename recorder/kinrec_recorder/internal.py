import logging

#Logging
class ColoredFormatter(logging.Formatter):

    grey = "\x1b[38;20m"
    yellow = "\x1b[33;20m"
    red = "\x1b[31;20m"
    bold_red = "\x1b[31;1m"
    reset = "\x1b[0m"

    FORMATS = {
        logging.DEBUG: grey + "{fmt}" + reset,
        logging.INFO: grey + "{fmt}" + reset,
        logging.WARNING: yellow + "{fmt}" + reset,
        logging.ERROR: red + "{fmt}" + reset,
        logging.CRITICAL: bold_red + "{fmt}" + reset
    }

    def __init__(self, fmt=None, datefmt=None, style='%'):
        super().__init__(fmt=fmt, datefmt=datefmt, style=style)
        self._formatters = {level: logging.Formatter(log_fmt.format(fmt=fmt), datefmt=datefmt) for level, log_fmt in
                       self.FORMATS.items()}

    def format(self, record):
        formatter = self._formatters.get(record.levelno)
        return formatter.format(record)
