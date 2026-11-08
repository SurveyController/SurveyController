#!/usr/bin/env python3
"""Compare the documented MCP tool schemas with a selected local checkout."""
import argparse
import json
import sys
from pathlib import Path

parser=argparse.ArgumentParser()
parser.add_argument('--mcp-root',required=True)
parser.add_argument('--write',action='store_true')
args=parser.parse_args()
sys.path.insert(0,str(Path(args.mcp_root).resolve()/'src'))
from camoufox_reverse_mcp import __version__
from camoufox_reverse_mcp.server import mcp
current={'schema_version':1,'mcp_version':__version__,
         'tools':sorted([{'name':tool.name,'parameters':tool.parameters} for tool in mcp._tool_manager.list_tools()],key=lambda x:x['name'])}
path=Path(__file__).resolve().parents[1]/'references/mcp-tools.json'
if args.write:
    path.write_text(json.dumps(current,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('Updated',len(current['tools']),'tool schemas')
else:
    previous=json.loads(path.read_text(encoding='utf-8'))
    previous['tools'].sort(key=lambda x:x['name'])
    if current!=previous:
        raise SystemExit('MCP contract changed; review compatibility and regenerate the snapshot with --write')
    print('MCP tool contract matches:',len(current['tools']))
