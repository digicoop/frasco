
import logging
import re


BLACK, RED, GREEN, YELLOW, BLUE, MAGENTA, CYAN, WHITE = range(8)
#The background is set with 40 plus the number of the color, and the foreground with 30
#These are the sequences need to get colored ouput
RESET_COLOR_SEQ = "\033[0m"
COLOR_SEQ = "\033[1;%dm"


def remove_all_handlers_from_logger(logger):
    for handler in logger.handlers:
        logger.removeHandler(handler)
    return logger


class ColorizingStreamHandler(logging.StreamHandler):
    def format(self, record):
        return self.colorize(super(ColorizingStreamHandler, self).format(record), record)

    def colorize(self, message, record):
        color = None
        if record.levelname == 'ERROR':
            color = RED
        if record.levelname == 'WARNING':
            color = YELLOW
        elif record.name.startswith('sqlalchemy.engine'):
            if re.match(r"(SELECT|WITH)", record.msg):
                color = BLUE
            elif re.match(r"(INSERT|UPDATE|DELETE)", record.msg):
                color = MAGENTA
            elif re.match(r"(BEGIN|COMMIT|ROLLBACK)", record.msg):
                color = GREEN
        if color:
            message = "\n".join([COLOR_SEQ % (30 + color) + line + RESET_COLOR_SEQ for line in message.split("\n")])
        return message


class ExcludeWerkzeugLogFilter(logging.Filter):
    def filter(self, record):
        return record.name != 'werkzeug'
