"""The MCP server answers a request with one JSON line, and a notification with none."""

import io
import json

from agent_actions.tooling.mcp.server import (
    INTERNAL_ERROR,
    INVALID_PARAMS,
    INVALID_REQUEST,
    METHOD_NOT_FOUND,
    PARSE_ERROR,
    PROTOCOL_VERSIONS,
    McpServer,
    RpcError,
)


def _ask(server: McpServer, method: str, params=None, request_id=1):
    message = {"jsonrpc": "2.0", "id": request_id, "method": method}
    if params is not None:
        message["params"] = params
    return json.loads(server.answer(json.dumps(message)))


def test_initialize_answers_the_version_the_client_asked_for_when_it_is_known():
    reply = _ask(McpServer(), "initialize", {"protocolVersion": PROTOCOL_VERSIONS[-1]})

    assert reply["result"]["protocolVersion"] == PROTOCOL_VERSIONS[-1]
    assert reply["result"]["serverInfo"]["name"] == "agent-actions"


def test_initialize_answers_its_newest_version_to_one_it_does_not_know():
    reply = _ask(McpServer(), "initialize", {"protocolVersion": "1999-01-01"})

    assert reply["result"]["protocolVersion"] == PROTOCOL_VERSIONS[0]


def test_the_capabilities_name_what_the_server_was_given_handlers_for():
    server = McpServer(instructions="how to work")
    assert _ask(server, "initialize")["result"]["capabilities"] == {}

    server.handle("tools/list", lambda params: {"tools": []})
    result = _ask(server, "initialize")["result"]

    assert result["capabilities"] == {"tools": {}}
    assert result["instructions"] == "how to work"


def test_a_notification_gets_no_reply_known_or_not():
    server = McpServer()

    assert server.answer('{"jsonrpc": "2.0", "method": "notifications/initialized"}') is None
    assert server.answer('{"jsonrpc": "2.0", "method": "no/such/thing"}') is None


def test_an_unknown_method_a_bad_message_and_bad_json_are_errors_with_their_codes():
    server = McpServer()

    assert _ask(server, "no/such/method")["error"]["code"] == METHOD_NOT_FOUND
    assert json.loads(server.answer("{not json"))["error"]["code"] == PARSE_ERROR
    assert json.loads(server.answer('{"id": 4}'))["error"]["code"] == INVALID_REQUEST
    assert json.loads(server.answer("[1, 2]"))["error"]["code"] == INVALID_REQUEST


def test_a_handler_s_rpc_error_is_answered_and_any_other_is_an_internal_error():
    server = McpServer()

    def refuses(params):
        raise RpcError(INVALID_PARAMS, "not that")

    def breaks(params):
        raise ValueError("boom")

    server.handle("a", refuses)
    server.handle("b", breaks)

    assert _ask(server, "a")["error"] == {"code": INVALID_PARAMS, "message": "not that"}
    assert _ask(server, "b")["error"] == {"code": INTERNAL_ERROR, "message": "ValueError: boom"}


def test_the_reply_carries_the_id_of_its_request_whatever_its_type():
    server = McpServer()

    assert _ask(server, "ping", request_id="abc")["id"] == "abc"
    assert _ask(server, "ping", request_id=0) == {"jsonrpc": "2.0", "id": 0, "result": {}}


def test_serve_answers_each_line_and_skips_blank_ones():
    requests = "\n".join(
        [
            json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping"}),
            "",
            json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
            json.dumps({"jsonrpc": "2.0", "id": 2, "method": "ping"}),
        ]
    )
    written = io.StringIO()

    McpServer().serve(io.StringIO(requests + "\n"), written)

    replies = [json.loads(line) for line in written.getvalue().splitlines()]
    assert [reply["id"] for reply in replies] == [1, 2]
