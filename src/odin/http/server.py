"""odin.http.server - ODIN HTTP Server class.

This module provides the core HTTP server class used in ODIN, which handles all client requests,
handing off API requests to the appropriate API route and adapter plugins, and defining the
default route used to serve static content.

Tim Nicholls, STFC Application Engineering
"""
import logging
import tornado.gen
import tornado.web
import tornado.ioloop
from tornado.log import access_log

from odin.config.parser import ConfigError
from odin.http.routes.api import ApiRoute
from odin.http.routes.default import DefaultRoute


class HttpServer(object):
    """HTTP server class."""

    def __init__(self, config):
        """Initialise the HttpServer object.

        :param config: parsed configuration container
        """
        settings = {
            "debug": config.debug_mode,
            "log_function": self.log_request,
        }

        # Set the up the access log level
        if config.access_logging is not None:
            try:
                level_val = getattr(logging, config.access_logging.upper())
                access_log.setLevel(level_val)
            except AttributeError:
                logging.error(
                    "Access logging level {} not recognised".format(config.access_logging)
                )

        # Create an API route
        self.api_route = ApiRoute(enable_cors=config.enable_cors, cors_origin=config.cors_origin)

        # Resolve the list of adapters specified
        try:
            adapters = config.resolve_adapters()
        except ConfigError as e:
            logging.warning('Failed to resolve API adapters: %s', e)
            adapters = {}

        # Register adapters with the API route
        for adapter in adapters:
            self.api_route.register_adapter(adapters[adapter])

        # Initialize adapters for all those that require inter adapter communication
        self.api_route.initialize_adapters()

        # Get request handlers for adapters registered with the API route
        handlers = self.api_route.get_handlers()

        # Create a default route for static content and get handlers
        default_route = DefaultRoute(config.static_path)
        handlers += default_route.get_handlers()

        # Create the Tornado web application for these handlers
        self.application = tornado.web.Application(handlers, **settings)

    def listen(self, port, host=''):
        """Listen for HTTP client requests.

        :param port: port to listen on
        :param host: host address to listen on
        """
        self.application.listen(port, host)

    def log_request(self, handler):
        """Log completed request information.

        This method is passed to the tornado.web.Application instance to override the
        default request logging behaviour. In doing so, successful requests are logged
        at debug level rather than info in order to reduce the rate of logging under
        normal conditions.

        :param handler: currently active request handler
        """
        if handler.get_status() < 400:
            log_method = access_log.debug
        elif handler.get_status() < 500:
            log_method = access_log.warning
        else:
            log_method = access_log.error
        request_time = 1000.0 * handler.request.request_time()
        log_method("%d %s %.2fms", handler.get_status(),
                   handler._request_summary(), request_time)

    def cleanup_adapters(self):
        """Clean up state of registered adapters.
        """
        self.api_route.cleanup_adapters()