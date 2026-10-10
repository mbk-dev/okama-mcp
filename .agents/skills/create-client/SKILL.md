---
name: create-client
description: Route client registration to a human using local Planner intake; use only an existing anonymous client code with MCP.
---

# Local human client intake

Client registration is a human-only operation outside the AI conversation. Do not
collect, request, read or repeat names, contacts, identifying notes or source files.
Do not construct registration payloads. The former `client_create` MCP tool is
removed and must not be called. The packaged skill installer is retired.

Tell the user to enter personal details in Planner's local human intake CLI, outside
this AI session. That CLI requires the updated privacy-capable Planner source;
older published companions do not provide the new privacy boundary. Refer to the
installation's Planner intake guide for the exact command and configured database.
Do not run intake on the user's behalf or inspect its input file or private output.

Ask only for the resulting anonymous registry code, such as `c-0001`. Once the
user provides an existing code, `client_get` can verify its safe pseudonymous
record. If local code tools are unavailable, explain that the server needs an
explicit local database and the `okama_planner.ai` facade. Do not fall back to raw
registry APIs, database inspection or identity resolution.

MCP updates accept only sex, birth year and investment declaration date. Other
identity edits stay in the human intake interface. Residency calls accept only
year and country; free-text notes stay local. Financial plans can be saved, loaded
and forecast through the client code and version tools. Tool errors remain generic;
do not ask for private database contents to diagnose them.
