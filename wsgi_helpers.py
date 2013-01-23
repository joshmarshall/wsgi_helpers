import base64
import json
import mimetypes
import os
import re
import time
from wsgiref.handlers import format_date_time as format_date


class Router(object):

    def __init__(self, routes):
        self._routes = []
        for route, handler in routes:
            if not hasattr(route, "match"):
                if not route.startswith("^"):
                    route = "^" + route
                if not route.endswith("$"):
                    route = route + "$"
                route = re.compile(route)
            self._routes.append((route, handler))

    def __call__(self, environ, start_response):
        path = environ["PATH_INFO"]
        environ["headers"] = _Headers(environ)
        for route, handler in self._routes:
            if route.match(path):
                return handler(environ, start_response)
        return handle_404()(environ, start_response)


class _Headers(object):

    def __init__(self, environ):
        self._environ = environ
        self._headers = dict([
            (h[5:].lower().replace("_", "-"), v)
            for h, v in self._environ.items()
            if h.startswith("HTTP_")
        ])

    def get(self, header, **kwargs):
        value = self._headers.get(header.lower())
        if value is None and not "default" in kwargs:
            raise MissingHeader("Unknown HTTP header '%s'" % (header))
        return value or kwargs["default"]


class MissingHeader(Exception):
    pass


class handle_file(object):

    def __init__(self, path, use_cache=True, expires=3600):
        self._path = os.path.abspath(path)
        self._use_cache = use_cache
        self._cache = None
        self._expires = expires
        self._last_modified = os.stat(self._path).st_mtime
        self._etag = self._generate_etag()
        self._mimetype = mimetypes.guess_type(self._path)[0]

    def _generate_etag(self):
        stat = os.stat(self._path)
        return base64.b64encode(
            "%s%s%s" % (stat.st_ino, stat.st_mtime, stat.st_size))

    def __call__(self, environ, start_response):
        etag_match = environ["headers"].get("If-None-Match", default=None)
        now = time.time()
        expire_time = now + self._expires
        headers = [
            ("Cache-Control", "max-age=%d" % (self._expires)),
            ("Date", format_date(now)),
            ("Expires", format_date(expire_time)),
            ("Last-Modified", format_date(self._last_modified)),
            ("ETag", self._etag)
        ]

        if self._etag == etag_match:
            start_response("304 Not Modified", headers)
            return ""

        modified = os.stat(self._path).st_mtime
        if not self._use_cache or self._cache is None or \
                modified > self._last_modified:
            self._last_modified = modified
            with open(self._path, "r") as fp:
                self._cache = fp.read()
            self._etag = self._generate_etag()

        headers.append(("Content-type", self._mimetype))
        start_response("200 OK", headers)
        return self._cache


def handle_404(message="Not found."):
    def return_404(environ, start_response):
        start_response(
            "404 Not Found", [("Content-type", "application/json")])
        return json.dumps({"error": 404, "message": message})
    return return_404


def handle_static(root, static_path="static"):
    def handle_static_file(environ, start_response):
        path = environ["PATH_INFO"]
        path = path.split(root, 1)[1]
        while path.startswith(".") or path.startswith("/"):
            path = path[1:]
        # no going up a directory
        path = path.replace("..", "")
        full_path = os.path.abspath(os.path.join(static_path, path))
        if not os.path.isfile(full_path):
            return handle_404("Path %s not found." % (full_path))(
                environ, start_response)
        return handle_file(full_path, use_cache=False)(environ, start_response)
    return handle_static_file
