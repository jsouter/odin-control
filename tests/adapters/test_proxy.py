import sys
import threading
import logging

if sys.version_info[0] == 3:  # pragma: no cover
    from unittest.mock import Mock, patch
else:                         # pragma: no cover
    from mock import Mock, patch

from nose.tools import assert_true, assert_equal, assert_not_equal, assert_in

from tornado.testing import AsyncHTTPTestCase, bind_unused_port
from tornado.ioloop import IOLoop
from tornado.web import Application, RequestHandler
from tornado.httpserver import HTTPServer
import tornado.gen

from odin.adapters.proxy import ProxyTarget, ProxyAdapter
from odin.adapters.parameter_tree import ParameterTree, ParameterTreeError
from odin.adapters.adapter import wants_metadata
from odin.testing.utils import LogCaptureFilter
from odin.util import convert_unicode_to_string


class ProxyTestHandler(RequestHandler):

    data = {
        'one': (1, None),  # this allows for auto generated metadata for testing purposes
        'two': 2.0,
        'pi': 3.14,
        'more':
        {
            'three': 3.0,
            'replace': 'Replace Me!',
            'even_more': {
                'extra_val': 5.5
            }
        }
    }
    param_tree = ParameterTree(data)

    def initialize(self, server):
        server.access_count += 1

    def get(self, path=''):
        try:
            data_ref = self.param_tree.get(path, wants_metadata(self.request))
            self.write(data_ref)

        except ParameterTreeError as param_e:
            self.set_status(404)
            self.write_error(404)
            # return a 404 error (not found)
        except Exception as other_e:
            print(other_e.message)
            self.write_error(500)
    
    def put(self, path):
        
        response_body = convert_unicode_to_string(tornado.escape.json_decode(self.request.body))
        try:
            self.param_tree.set(path, response_body)
            data_ref = self.param_tree.get(path)

            self.write(data_ref)

        except ParameterTreeError:
            self.set_status(404)
            self.write_error(404)

        except Exception as other_e:
            print(other_e.message)
            self.write_error(500)


class ProxyTestServer(object):

    def __init__(self,):

        self.server_ioloop = IOLoop()
        self.access_count = 0

        @tornado.gen.coroutine
        def init_server():
            sock, self.port = bind_unused_port()
            app = Application([('/(.*)', ProxyTestHandler, dict(server=self))])
            self.server = HTTPServer(app)
            self.server.add_socket(sock)
        self.server_ioloop.run_sync(init_server)

        self.server_thread = threading.Thread(target=self.server_ioloop.start)

    def start(self):

        self.server_thread.start()

    def stop(self):

        def stop_server():

            self.server.stop()

            @tornado.gen.coroutine
            def slow_stop():
                for i in range(5):
                    yield
                self.server_ioloop.stop()
            
            self.server_ioloop.add_callback(slow_stop)

        self.server_ioloop.add_callback(stop_server)
        self.server_thread.join()
        self.server_ioloop.close(all_fds=True)

    def get_access_count(self):
        return self.access_count

    def clear_access_count(self):
        self.access_count = 0

class TestProxyTarget():

    @classmethod
    def setup_class(cls):

        cls.test_server = ProxyTestServer()
        cls.test_server.start()
        cls.port = cls.test_server.port

        cls.name = 'test_target'
        cls.url = 'http://127.0.0.1:{}/'.format(cls.port)
        cls.request_timeout = 0.1

        cls.proxy_target = ProxyTarget(cls.name, cls.url, cls.request_timeout)

    @classmethod
    def teardown_class(cls):

        cls.proxy_target.http_client.close()
        cls.test_server.stop()

    def test_proxy_target_init(self):

        assert_equal(self.proxy_target.name, self.name)
        assert_equal(self.proxy_target.url, self.url)
        assert_equal(self.proxy_target.request_timeout, self.request_timeout)

    def test_proxy_target_remote_get(self):

        self.proxy_target.last_update = ''

        self.proxy_target.remote_get()
        assert_equal(self.proxy_target.data, ProxyTestHandler.param_tree.get(""))
        assert_equal(self.proxy_target.status_code, 200)
        assert_not_equal(self.proxy_target.last_update, '')

    def test_param_tree_get(self):

        param_tree = self.proxy_target.status_param_tree.get('')
        for tree_element in ['url', 'status_code', 'error', 'last_update']:
            assert_true(tree_element in param_tree)

    def test_proxy_target_http_get_error_404(self):

        bad_url = self.url + 'notfound/'
        proxy_target = ProxyTarget(self.name, bad_url, self.request_timeout)
        proxy_target.remote_get('notfound')
        
        assert_equal(proxy_target.status_code, 404)
        assert_in('Not Found', proxy_target.error_string)

    def test_proxy_target_other_error(self):

        bad_url = 'http://127.0.0.1:{}'.format(self.port + 1)
        proxy_target = ProxyTarget(self.name, bad_url, self.request_timeout)
        proxy_target.remote_get()

        assert_equal(proxy_target.status_code, 502)
        assert_in('Connection refused', proxy_target.error_string)


class TestProxyAdapter():

    @classmethod
    def setup_class(cls):

        cls.log_capture_filter = LogCaptureFilter()
        logging.getLogger().setLevel(logging.DEBUG)

        cls.num_targets = 2

        cls.test_servers = []
        cls.ports = []
        cls.target_config = ""

        for _ in range(cls.num_targets):

            test_server = ProxyTestServer()
            test_server.start()
            cls.test_servers.append(test_server)
            cls.ports.append(test_server.port)

        cls.target_config = ','.join([
            "node_{}=http://127.0.0.1:{}/".format(tgt, port) for (tgt, port) in enumerate(cls.ports)
        ])

        cls.adapter_kwargs = {
            'targets': cls.target_config,
            'request_timeout': 1.0,
        }
        cls.adapter = ProxyAdapter(**cls.adapter_kwargs)

        cls.path = ''
        cls.request = Mock
        cls.request.headers = {'Accept': 'application/json', 'Content-Type': 'application/json'}
        cls.request.body = '{"pi":2.56}'

    @classmethod
    def teardown_class(cls):

        for target in cls.adapter.targets:
            target.http_client.close()
        for test_server in cls.test_servers:
            test_server.stop()

    @classmethod
    def clear_access_counts(cls):

        for test_server in cls.test_servers:
            test_server.clear_access_count()

    def test_adapter_loaded(self):

        expected_msg = "ProxyAdapter with {} targets loaded".format(self.num_targets)
        assert_true(expected_msg in self.log_capture_filter.log_debug())

    def test_adapter_get(self):

        response = self.adapter.get(self.path, self.request)
        
        assert_true('status' in response.data)
        
        assert_equal(len(response.data), self.num_targets+1)
        
        for tgt in range(self.num_targets):
            node_str = 'node_{}'.format(tgt)
            assert_true(node_str in response.data)
            assert_equal(response.data[node_str], ProxyTestHandler.param_tree.get(''))

    def test_adapter_get_metadata(self):
        self.request.headers["Accept"] += ";metadata=True"
        response = self.adapter.get(self.path, self.request)

        assert_true("status" in response.data)
        for tgt in range(self.num_targets):
            node_str = 'node_{}'.format(tgt)
            assert_true(node_str in response.data)
            assert_true("one" in response.data[node_str])
            assert_true("type" in response.data[node_str]['one'])

    def test_adapter_get_status_metadata(self):
        self.request.headers["Accept"] += ";metadata=True"
        response = self.adapter.get(self.path, self.request)

        assert_true("status" in response.data)
        assert_true("node_0" in response.data["status"])
        assert_true("type" in response.data['status']['node_0']['error'])

    def test_adapter_put(self):

        response = self.adapter.put(self.path, self.request)

        assert_true('status' in response.data)

        assert_equal(len(response.data), self.num_targets+1)

        for tgt in range(self.num_targets):
            node_str = 'node_{}'.format(tgt)
            assert_true(node_str in response.data)
            assert_equal(convert_unicode_to_string(response.data[node_str]), ProxyTestHandler.param_tree.get(''))

    def test_adapter_get_proxy_path(self):

        node = self.adapter.targets[0].name
        path = "more/even_more"
        response = self.adapter.get("{}/{}".format(node, path), self.request)
        assert_equal(response.data["even_more"], ProxyTestHandler.data["more"]["even_more"])
        assert_equal(self.adapter.param_tree.get('')['status'][node]['status_code'], 200)

    def test_adapter_get_proxy_path_trailing_slash(self):
        node = self.adapter.targets[0].name
        path = "more/even_more/"
        response = self.adapter.get("{}/{}".format(node, path), self.request)
        assert_equal(response.data["even_more"], ProxyTestHandler.data["more"]["even_more"])
        assert_equal(self.adapter.param_tree.get('')['status'][node]['status_code'], 200)

    def test_adapter_put_proxy_path(self):

        node = self.adapter.targets[0].name
        path = "more/"
        self.request.body = '{"replace": "been replaced"}'
        response = self.adapter.put("{}/{}".format(node, path), self.request)
        assert_equal(response.status_code, 200)
        assert_equal(convert_unicode_to_string(response.data["more"]["replace"]), "been replaced")

    def test_adapter_get_bad_path(self):

        missing_path = 'missing/path'
        response = self.adapter.get(missing_path, self.request)

        assert_true('error' in response.data)
        assert_equal('Invalid path: {}'.format(missing_path), response.data['error'])

    def test_adapter_put_bad_path(self):

        missing_path = 'missing/path'
        response = self.adapter.put(missing_path, self.request)

        assert_true('error' in response.data)
        assert_equal('Invalid path: {}'.format(missing_path), response.data['error'])

    def test_adapter_put_bad_type(self):

        self.request.body = "bad_body"
        response = self.adapter.put(self.path, self.request)

        assert_true('error' in response.data)
        assert_true('Failed to decode PUT request body:' in response.data['error'])

    def test_adapter_bad_timeout(self):

        bad_timeout = 'not_timeout'
        bad_adapter = ProxyAdapter(request_timeout=bad_timeout)

        expected_msg = 'Illegal timeout specified for ProxyAdapter: {}'.format(bad_timeout)
        assert_true(expected_msg in self.log_capture_filter.log_error())

    def test_adapter_bad_target_spec(self):

        bad_target_spec = 'bad_target_1,bad_target_2'
        bad_adapter = ProxyAdapter(targets=bad_target_spec)

        expected_msg = 'Illegal target specification for ProxyAdapter: bad_target_1'
        assert_true(expected_msg in self.log_capture_filter.log_error())

    def test_adapter_no_target_spec(self):

        bad_adapter = ProxyAdapter()

        expected_msg = "Failed to resolve targets for ProxyAdapter"
        assert_true(expected_msg in self.log_capture_filter.log_error())

    def test_adapter_get_access_count(self):

        self.clear_access_counts()

        response = self.adapter.get(self.path, self.request)

        access_counts = [server.get_access_count() for server in self.test_servers]
        assert_equal(access_counts, [1]*self.num_targets)

    def test_adapter_counter_get_single_node(self):

        path = self.path + 'node_{}'.format(self.num_targets-1)

        self.clear_access_counts()
        response = self.adapter.get(path, self.request)
        access_counts = [server.get_access_count() for server in self.test_servers]
        
        assert_true(path in response.data)
        assert_equal(sum([server.get_access_count() for server in self.test_servers]), 1)
