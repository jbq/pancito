import syslog

def tostr(msg):
    if isinstance(msg, unicode):
        return msg.encode('utf8')
    return str(msg)

def debug(msg):
    syslog.syslog(syslog.LOG_DEBUG, tostr(msg))

def info(msg):
    syslog.syslog(syslog.LOG_INFO, tostr(msg))

def notice(msg):
    syslog.syslog(syslog.LOG_NOTICE, tostr(msg))

def warn(msg):
    syslog.syslog(syslog.LOG_WARNING, tostr(msg))

def error(msg):
    syslog.syslog(syslog.LOG_ERR, tostr(msg))

def crit(msg):
    syslog.syslog(syslog.LOG_CRIT, tostr(msg))

def emerg(msg):
    syslog.syslog(syslog.LOG_EMERG, tostr(msg))

def log_exc(tb=None):
    """Log traceback line by line with severity error in syslog"""
    if tb is not None:
        assert isinstance(tb, str)

    if tb == None:
        import traceback
        tb = traceback.format_exc()

    for line in tb.split("\n"):
        syslog.syslog(syslog.LOG_ERR, line)
