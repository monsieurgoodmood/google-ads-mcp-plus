# Copyright 2026 ByteBerry Analytics LLC
#
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
#
# Project: https://github.com/monsieurgoodmood/google-ads-mcp-plus

"""google-ads-mcp-plus — Google Ads read, audit, and guarded write for MCP clients.

This is NOT an officially supported Google product.

Entry points installed with this package:

* ``google-ads-mcp-plus``       — the MCP server (what Claude Code connects to)
* ``google-ads-plus-audit``     — CLI account audit, read-only
* ``google-ads-plus-campaign``  — CLI Search campaign creation, paused by default
"""

__version__ = "0.1.0"

__all__ = ["validators", "config_loader", "create_campaign", "audit", "server"]
