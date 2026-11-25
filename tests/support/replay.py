"""Stands in for the network in tests. A local HTTP server answers every API request with a
function of the decoded request body and keeps what it was sent, so a test reads the exact
request the real client built. Nothing is patched: LangChain and the Anthropic SDK run as they
do against the real API.
"""

import itertools
import json
import threading
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlunsplit

DEPARTMENTS = {"billing": "billing", "field operations": "field_operations", "hr": "hr"}
_ids = itertools.count(1)


class Replay:
    """`respond` gets the decoded request body and returns `(status, response_body)`."""

    def __init__(self) -> None:
        self.requests: list[dict] = []
        self.raw: list[str] = []
        self._respond: Callable[[dict], tuple[int, dict]] | None = None
        self._lock = threading.Lock()
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        threading.Thread(target=self._server.serve_forever, daemon=True).start()

    @property
    def url(self) -> str:
        host, port = self._server.server_address

        return urlunsplit(("http", f"{host}:{port}", "", "", ""))

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()

    def respond(self, respond: Callable[[dict], tuple[int, dict]]) -> None:
        self._respond = respond

    def always(self, status: int, body: dict) -> None:
        """Answers every request with the same response."""
        self.respond(lambda _body: (status, body))

    def sequence(self, responses: list[dict]) -> None:
        """Answers with `responses` in order, one per request."""
        queue = iter(responses)
        self.respond(lambda _body: (200, next(queue)))

    def roles(self, **queues: list[dict]) -> None:
        """Answers each request with the next response queued for its role: `chief_of_staff`,
        `judge`, `grader` (the eval judge) or a department (`billing`, `field_operations`,
        `hr`), told apart by the system prompt."""
        waiting = {name: iter(responses) for name, responses in queues.items()}
        self.respond(lambda body: (200, next(waiting[role(body)])))

    def _handler(self) -> type[BaseHTTPRequestHandler]:
        replay = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                raw = self.rfile.read(int(self.headers["content-length"])).decode()

                with replay._lock:
                    replay.raw.append(raw)
                    replay.requests.append(json.loads(raw))
                    status, body = replay._respond(json.loads(raw))

                sent = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(sent)))
                self.end_headers()
                self.wfile.write(sent)

            def log_message(self, *_arguments: object) -> None:
                pass

        return Handler


def role(body: dict) -> str:
    """The role a request body belongs to, from its system prompt."""
    system = body["system"][0]["text"]

    if system.startswith("You route"):
        return "chief_of_staff"

    if system.startswith("You check one proposal"):
        return "judge"

    if system.startswith("You grade one proposal"):
        return "grader"

    name = system.removeprefix("You are the ").split(" agent", 1)[0]

    return DEPARTMENTS[name]


def tool_use(name: str, arguments: dict) -> dict:
    """A recorded-shape response that calls one tool."""
    call = {"type": "tool_use", "id": f"toolu_{next(_ids)}", "name": name, "input": arguments}

    return _message("tool_use", [call], {"input_tokens": 0, "output_tokens": 1})


def end_turn(text: str) -> dict:
    """A recorded-shape response that ends the turn with text."""
    return _message("end_turn", [{"type": "text", "text": text}], {"output_tokens": 1})


def grade(agrees: bool, reason: str = "Same decision.") -> dict:
    """An eval judge response: whether staff would accept the proposal."""
    return json_text({"reason": reason, "agrees": agrees})


def verdict(sensible: bool, reason: str = "Fits.") -> dict:
    """A judge response with a verdict."""
    return json_text({"reason": reason, "sensible": sensible})


def route(department: str, concerns: tuple[str, ...] = ()) -> dict:
    """A front door response that routes to `department` (or "unsure"), naming `concerns`."""
    answer = {
        "reason": "Unclear.",
        "department": department,
        "intent": "a question",
        "concerns": list(concerns),
    }

    return json_text(answer)


def json_text(answer: object) -> dict:
    """A response whose text is `answer` as JSON."""
    return text(json.dumps(answer))


def text(reply: str) -> dict:
    """A response with this text and no token usage."""
    return _message("end_turn", [{"type": "text", "text": reply}], {})


def _message(stop_reason: str, content: list[dict], usage: dict) -> dict:
    return {
        "id": "msg_replayed",
        "type": "message",
        "role": "assistant",
        "model": "replayed",
        "content": content,
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": {"input_tokens": 0, "output_tokens": 0, **usage},
    }
