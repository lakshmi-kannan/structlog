# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Processors and helpers specific to the `logging module
<http://docs.python.org/2/library/logging.html>`_ from the `Python standard
library <http://docs.python.org/>`_.

See also :doc:`structlog's standard library support <standard-library>`.
"""

from __future__ import absolute_import, division, print_function

import logging

from structlog._base import BoundLoggerBase
from structlog._compat import PY3
from structlog._exc import DropEvent
from structlog._frames import _find_first_app_frame_and_name, _format_stack


class _FixedFindCallerLogger(logging.Logger):
    """
    Change the behavior of findCaller to cope with structlog's extra frames.
    """
    def findCaller(self, stack_info=False):
        """
        Finds the first caller frame outside of structlog so that the caller
        info is populated for wrapping stdlib.
        This logger gets set as the default one when using LoggerFactory.
        """
        f, name = _find_first_app_frame_and_name(['logging'])
        if PY3:  # pragma: nocover
            if stack_info:
                sinfo = _format_stack(f)
            else:
                sinfo = None
            return f.f_code.co_filename, f.f_lineno, f.f_code.co_name, sinfo
        else:
            return f.f_code.co_filename, f.f_lineno, f.f_code.co_name


class BoundLogger(BoundLoggerBase):
    """
    Python Standard Library version of :class:`structlog.BoundLogger`.
    Works exactly like the generic one except that it takes advantage of
    knowing the logging methods in advance.

    Use it like::

        configure(
            wrapper_class=structlog.stdlib.BoundLogger,
        )

    """
    def __getattr__(self, item):
        return getattr(self._logger, item)

    def debug(self, event=None, *args, **kw):
        """
        Process event and call ``Logger.debug()`` with the result.
        """
        return self._proxy_to_logger('debug', event, *args, **kw)

    def info(self, event=None, *args, **kw):
        """
        Process event and call ``Logger.info()`` with the result.
        """
        return self._proxy_to_logger('info', event, *args, **kw)

    def warning(self, event=None, *args, **kw):
        """
        Process event and call ``Logger.warning()`` with the result.
        """
        return self._proxy_to_logger('warning', event, *args, **kw)

    warn = warning

    def error(self, event=None, *args, **kw):
        """
        Process event and call ``Logger.error()`` with the result.
        """
        return self._proxy_to_logger('error', event, *args, **kw)

    def critical(self, event=None, *args, **kw):
        """
        Process event and call ``Logger.critical()`` with the result.
        """
        return self._proxy_to_logger('critical', event, *args, **kw)

    def _proxy_to_logger(self, method_name, event=None, *event_args,
                         **event_kw):
        if event_args:
            event_kw['positional_args'] = event_args
        return super(BoundLogger, self)._proxy_to_logger(method_name, event,
                                                         *event_args,
                                                         **event_kw)

    def exception(self, event=None, **kw):
        """
        Process event and call ``Logger.error()`` with the result, after
        setting ``exc_info`` to `True`.
        """
        kw['exc_info'] = True
        return self.error(event=event, **kw)


class LoggerFactory(object):
    """
    Build a standard library logger when an *instance* is called.

    Sets a custom logger using `logging.setLogggerClass` so variables in
    log format are expanded properly.

    >>> from structlog import configure
    >>> from structlog.stdlib import LoggerFactory
    >>> configure(logger_factory=LoggerFactory())

    :param ignore_frame_names: When guessing the name of a logger, skip frames
        whose names *start* with one of these.  For example, in pyramid
        applications you'll want to set it to
        ``['venusian', 'pyramid.config']``.
    :type ignore_frame_names: `list` of `str`
    """
    def __init__(self, ignore_frame_names=None):
        self._ignore = ignore_frame_names
        logging.setLoggerClass(_FixedFindCallerLogger)

    def __call__(self, *args):
        """
        Deduce the caller's module name and create a stdlib logger.

        If an optional argument is passed, it will be used as the logger name
        instead of guesswork.  This optional argument would be passed from the
        :func:`structlog.get_logger` call.  For example
        ``struclog.get_logger('foo')`` would cause this method to be called
        with ``'foo'`` as its first positional argument.

        :rtype: `logging.Logger`

        .. versionchanged:: 0.4.0
            Added support for optional positional arguments.  Using the first
            one for naming the constructed logger.
        """
        if args:
            return logging.getLogger(args[0])

        # We skip all frames that originate from within structlog or one of the
        # configured names.
        _, name = _find_first_app_frame_and_name(self._ignore)
        return logging.getLogger(name)


class StdlibFormatEventRenderer(object):
    """
    Applies stdlib-like string formatting to the `event` key with the arguments
    in the `positional_args` key. This is populated by
    `structlog.stdlib.BoundLogger` or can be manually set.

    `positional_args` can be any iterable, but a dictionary as the single
    element of the tuple is used instead of the tuple, to mantain compatibility
    with the undocumented feature of stdlib logging.

    """
    def __init__(self, strip_positional_args=False):
        self.strip_positional_args = strip_positional_args

    def __call__(self, _, __, event_dict):
        args = event_dict.get('positional_args')
        if args:
            args = tuple(args)
            if len(args) == 1 and isinstance(args[0], dict) and args[0]:
                args = args[0]
            event_dict['event'] = event_dict['event'] % args
            if self.strip_positional_args:
                event_dict.pop('positional_args')
        return event_dict

# Adapted from the stdlib

CRITICAL = 50
FATAL = CRITICAL
ERROR = 40
WARNING = 30
WARN = WARNING
INFO = 20
DEBUG = 10
NOTSET = 0

_nameToLevel = {
    'critical': CRITICAL,
    'error': ERROR,
    'warn': WARNING,
    'warning': WARNING,
    'info': INFO,
    'debug': DEBUG,
    'notset': NOTSET,
}


def filter_by_level(logger, name, event_dict):
    """
    Check whether logging is configured to accept messages from this log level.

    Should be the first processor if stdlib's filtering by level is used so
    possibly expensive processors like exception formatters are avoided in the
    first place.

    >>> import logging
    >>> from structlog.stdlib import filter_by_level
    >>> logging.basicConfig(level=logging.WARN)
    >>> logger = logging.getLogger()
    >>> filter_by_level(logger, 'warn', {})
    {}
    >>> filter_by_level(logger, 'debug', {})
    Traceback (most recent call last):
    ...
    DropEvent
    """
    if logger.isEnabledFor(_nameToLevel[name]):
        return event_dict
    else:
        raise DropEvent
