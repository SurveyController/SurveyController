# SPDX-License-Identifier: CC0-1.0
"""Real MCP SDK stdio transport; owns only the child it starts for this run."""
from contextlib import asynccontextmanager
from datetime import timedelta
import json
import os
from pathlib import Path
import sys
import time


def unpack(raw):
    if not isinstance(raw, dict):
        raw = raw.model_dump(mode="json", by_alias=True, exclude_none=True)
    if "structuredContent" in raw:
        return raw["structuredContent"]
    texts = [b["text"] for b in raw.get("content", []) if b.get("type") == "text"]
    if len(texts) == 1:
        try:
            return json.loads(texts[0])
        except ValueError:
            return texts[0]
    return texts


def tool_error(raw, value):
    return bool(raw.get("isError") or (isinstance(value, dict) and
                (value.get("error") or value.get("mode") == "error" or
                 value.get("status") in ("error", "failed"))))


class LoggedSession:
    def __init__(self, session, work):
        self.session, self.work, self.seq = session, work, 0

    async def invoke(self, method, params=None, allow_error=False):
        params = params or {}
        self.seq += 1
        start = time.monotonic()
        record = {"seq": self.seq, "method": method, "params": params, "started_at": time.time()}
        with (self.work / "mcp.jsonl").open("a", encoding="utf-8") as log:
            log.write(json.dumps({**record, "phase": "start"}) + "\n")
        try:
            if method == "initialize":
                result = await self.session.initialize()
            elif method == "tools/list":
                result = await self.session.list_tools()
            else:
                result = await self.session.call_tool(params["name"], params.get("arguments", {}))
            raw = result.model_dump(mode="json", by_alias=True, exclude_none=True)
            file = f"{self.seq:04}.json"
            (self.work / file).write_text(json.dumps(raw, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
            value = unpack(raw)
            failed = tool_error(raw, value)
            record.update(status="error" if failed else "ok", result=file)
            if failed and not allow_error:
                raise RuntimeError(f"MCP {params.get('name', method)} failed: {value}")
            return value
        except BaseException as exc:
            record.update(status="error", exception=str(exc))
            raise
        finally:
            record.update(phase="end", elapsed_ms=round((time.monotonic() - start) * 1000, 3))
            with (self.work / "mcp.jsonl").open("a", encoding="utf-8") as log:
                log.write(json.dumps(record) + "\n")

    async def call(self, name, arguments=None, allow_error=False):
        return await self.invoke("tools/call", {"name": name, "arguments": arguments or {}}, allow_error)

    async def list_tools(self):
        return await self.invoke("tools/list")


@asynccontextmanager
async def connect(work, candidate):
    # Lazy imports let --help and archive/security tests run with the stdlib alone.
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    work, candidate = Path(work).resolve(), Path(candidate).resolve()
    work.mkdir(parents=True, exist_ok=False)
    temporary = work / "tmp"
    temporary.mkdir()
    env = {"PYTHONPATH": str(candidate / "src"), "PYTHONDONTWRITEBYTECODE": "1",
           "NO_PROXY": "127.0.0.1,localhost", "no_proxy": "127.0.0.1,localhost",
           "TMPDIR": str(temporary), "TMP": str(temporary), "TEMP": str(temporary)}
    params = StdioServerParameters(command=sys.executable, args=["-B", "-m", "camoufox_reverse_mcp"],
                                   env=env, cwd=str(work))
    meta = {"candidate": str(candidate), "python": sys.executable, "client_pid": os.getpid(),
            "started_at": time.time(), "transport": "mcp-sdk-stdio", "attach": False}
    try:
        with (work / "stderr.log").open("w", encoding="utf-8") as err:
            async with stdio_client(params, errlog=err) as (read, write):
                async with ClientSession(read, write, read_timeout_seconds=timedelta(seconds=90)) as session:
                    client = LoggedSession(session, work)
                    await client.invoke("initialize")
                    try:
                        yield client
                    finally:
                        # This is the child stdio session, never the user's active MCP connection.
                        await client.call("close_browser", allow_error=True)
    finally:
        meta["ended_at"] = time.time()
        (work / "session.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
