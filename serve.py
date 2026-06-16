#!/usr/bin/env python3
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError


ROOT = Path(__file__).resolve().parent


def dynamic_html_match(route):
    parts = route.strip("/").split("/")
    if parts == [""]:
        return None

    for html_file in ROOT.rglob("*.html"):
        route_parts = html_file.relative_to(ROOT).with_suffix("").parts
        if route_parts[-1] == "index":
            route_parts = route_parts[:-1]
        if len(route_parts) != len(parts):
            continue
        if all(
            exported == actual
            or (exported.startswith("[") and exported.endswith("]"))
            for exported, actual in zip(route_parts, parts)
        ):
            return html_file
    return None


class ExpoExportHandler(SimpleHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type, api-key")
        self.end_headers()

    def do_POST(self):
        if self.path.startswith("/__llm_proxy/") or self.path.startswith("/api/llm-proxy/"):
            self.proxy_llm_request()
            return
        super().do_POST()

    def proxy_llm_request(self):
        target_url = self.build_proxy_target()
        if not target_url:
            self.send_error(400, "Invalid proxy target")
            return

        content_length = int(self.headers.get("Content-Length", "0") or "0")
        body = self.rfile.read(content_length)
        headers = {
            key: value
            for key, value in self.headers.items()
            if key.lower()
            not in {"host", "origin", "referer", "content-length", "accept-encoding", "connection"}
        }

        request = Request(target_url, data=body, headers=headers, method="POST")
        try:
            with urlopen(request, timeout=30) as response:
                response_body = response.read()
                self.send_response(response.status)
                self.copy_proxy_headers(response.headers.items(), len(response_body))
                self.end_headers()
                self.wfile.write(response_body)
        except HTTPError as error:
            response_body = error.read()
            self.send_response(error.code)
            self.copy_proxy_headers(error.headers.items(), len(response_body))
            self.end_headers()
            self.wfile.write(response_body)
        except URLError as error:
            message = str(error.reason).encode("utf-8")
            self.send_response(502)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(message)))
            self.end_headers()
            self.wfile.write(message)

    def build_proxy_target(self):
        parsed = urlparse(self.path)
        parts = unquote(parsed.path).split("/")
        legacy_proxy = len(parts) >= 5 and parts[1] == "__llm_proxy"
        api_proxy = len(parts) >= 6 and parts[1] == "api" and parts[2] == "llm-proxy"
        if not legacy_proxy and not api_proxy:
            return None

        scheme_index = 2 if legacy_proxy else 3
        scheme = parts[scheme_index]
        if scheme not in {"http", "https"}:
            return None

        host = parts[scheme_index + 1]
        path = "/" + "/".join(parts[scheme_index + 2 :])
        query = f"?{parsed.query}" if parsed.query else ""
        return f"{scheme}://{host}{path}{query}"

    def copy_proxy_headers(self, headers, body_length):
        blocked = {"connection", "content-encoding", "content-length", "transfer-encoding"}
        for key, value in headers:
            if key.lower() not in blocked:
                self.send_header(key, value)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(body_length))

    def translate_path(self, path):
        parsed = urlparse(path)
        clean_path = unquote(parsed.path).lstrip("/")
        route_path = clean_path.strip("/")

        if not clean_path:
            return str(ROOT / "index.html")

        candidate = ROOT / clean_path
        if candidate.is_dir():
            index = candidate / "index.html"
            if index.exists():
                return str(index)
        elif candidate.exists():
            return str(candidate)

        html_candidate = ROOT / f"{route_path}.html"
        if html_candidate.exists():
            return str(html_candidate)

        nested_index = candidate / "index.html"
        if nested_index.exists():
            return str(nested_index)

        dynamic_candidate = dynamic_html_match(route_path)
        if dynamic_candidate:
            return str(dynamic_candidate)

        return str(ROOT / "index.html")


if __name__ == "__main__":
    server = ThreadingHTTPServer(("127.0.0.1", 4173), ExpoExportHandler)
    print("Serving http://127.0.0.1:4173")
    server.serve_forever()
