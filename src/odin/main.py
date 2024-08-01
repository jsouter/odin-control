"""ODIN server main functions.

This module implements the main entry point for the ODIN server. It handles parsing
configuration options, loading adapters and creating the appropriate HTTP server instances.

Tim Nicholls, STFC Application Engineering Group
"""
import sys
import logging
import signal
import threading

import tornado.ioloop
from tornado.autoreload import add_reload_hook

from odin.http.server import HttpServer
from odin.config.parser import ConfigParser, ConfigError
from odin.logconfig import add_graylog_handler
from typing import List, Optional
_stop_ioloop = False  # Global variable to indicate ioloop should be shut down


def main(argv: Optional[List[str]] = None):
    """Run the odin-control server.

    This function is the main entry point for the odin-control server. It parses configuration
    options from the command line and any files, resolves adapters and launches the main
    API server before entering the IO processing loop.

    :param argv: argument list to pass to parser if called programatically
    """
    config = ConfigParser()

    # Define configuration options and add to the configuration parser
    config.define('http_addr', default='0.0.0.0', option_help='Set HTTP/S server address')
    config.define('http_port', default=8888, option_help='Set HTTP server port')
    config.define('enable_http', default=True, option_help='Enable HTTP')
    config.define('https_port', default=8443, option_help='Set HTTPS server port')
    config.define('enable_https', default=False, option_help='Enable HTTPS')
    config.define('ssl_cert_file', default='cert.pem', option_help='Set SSL certificate file for HTTPS')
    config.define('ssl_key_file', default='key.pem', option_help='Set SSL key file for HTTPS')
    config.define('debug_mode', default=False, option_help='Enable tornado debug mode')
    config.define('access_logging', default=None, option_help="Set the tornado access log level",
                  metavar="debug|info|warning|error|none")
    config.define('static_path', default='./static', option_help='Set path for static file content')
    config.define('enable_cors', default=False,
                  option_help='Enable cross-origin resource sharing (CORS)')
    config.define('cors_origin', default='*', option_help='Specify allowed CORS origin')
    config.define('graylog_server', default=None, option_help="Graylog server address and :port")
    config.define('graylog_logging_level', default=logging.INFO, option_help="Graylog logging level")
    config.define('graylog_static_fields', default=None,
                  option_help="Comma separated list of key=value pairs to add to every log message metadata")

    # Parse configuration options and any configuration file specified
    try:
        config.parse(argv)
    except ConfigError as e:
        logging.error('Failed to parse configuration: %s', e)
        return 2

    if config.graylog_server is not None:
        add_graylog_handler(
            config.graylog_server,
            config.graylog_logging_level,
            config.graylog_static_fields
        )

    # Get the Tornado ioloop instance
    ioloop = tornado.ioloop.IOLoop.instance()

    # Launch the HTTP server with the parsed configuration
    http_server = HttpServer(config)

    # If debug mode is enabled, add an autoreload hook to the server to ensure that adapter cleanup
    # methods are called as the server reloads
    if config.debug_mode:
        add_reload_hook(http_server.cleanup_adapters)

    def shutdown_handler(sig_name):  # pragma: no cover
        """Shut down the running server cleanly.

        This inner function implements a signal handler to shut down the running server cleanly in
        response to a signal. The underlying HTTP server is stopped, preventing new connections
        from being accepted, and a global flag set true to allow a periodic task to terminate the
        ioloop cleanly.

        :param signum: signal number that the handler was invoked with
        :param _: unused stack frame
        """
        global _stop_ioloop
        logging.info('%s signal received, shutting down', sig_name)

        # Stop the HTTP server
        http_server.stop()

        # Tell the periodic callback to stop the ioloop when next invokved
        _stop_ioloop = True

    def stop_ioloop():  # pragma: no cover
        """Stop the running ioloop cleanly.

        This inner function is run as a periodic callback and stops the ioloop when requested by
        the signal handler. This mechansim is necessary to ensure that the ioloop stops cleanly
        under all conditions, for instance when adapters and handlers have not been correctly
        initialised.
        """
        global _stop_ioloop
        if _stop_ioloop:
             logging.debug("Stopping ioloop")

             # Stop the ioloop
             ioloop.stop()

    # Register a shutdown signal handler and start an ioloop stop callback only if this is the
    # main thread
    if isinstance(threading.current_thread(), threading._MainThread):  # pragma: no cover
        signal.signal(signal.SIGINT, lambda signum, frame: shutdown_handler('Interrupt'))
        signal.signal(signal.SIGTERM, lambda signum, frame: shutdown_handler('Terminate'))
        tornado.ioloop.PeriodicCallback(stop_ioloop, 1000).start()

    # Start the ioloop
    ioloop.start()

    # If the application isn't shutting down due to the signal handler being invoked (e.g. when
    # running in a secondary thread), ensure the HTTP server stops cleanly
    if not _stop_ioloop:
        http_server.stop()

    # At shutdown, clean up the state of the loaded adapters
    http_server.cleanup_adapters()

    logging.info('ODIN server shutdown')

    return 0


def main_deprecate(argv=None):  # pragma: no cover
    """Deprecated main entry point for running the odin control server.

    This method adds an entry point for running odin control server that is run by the
    deprecated odin_server command. It simply runs the main entry point as normal having
    printing a deprecation warning.
    """
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter('always', DeprecationWarning)
        message = """

The odin_server script entry point is deprecated and will be removed in future releases. Consider
using \'odin_control\' instead

            """
        warnings.warn(message, DeprecationWarning, stacklevel=1)

    main(argv)


if __name__ == '__main__':  # pragma: no cover
    sys.exit(main())
