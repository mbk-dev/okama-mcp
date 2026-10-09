---
name: create-client
description: Create and verify a client in an explicitly configured local okama Planner registry through MCP. Use for registering a person from free-form details and resolving missing fields or possible duplicates.
---

# Create a client

Use the local MCP tools `client_list`, `client_create`, `client_get`,
`client_set_tax_residency` and `client_get_tax_residency`. If these tools are absent,
explain that the local server needs `stdio --client-db` with a Planner storage
companion; collecting inputs alone does not create a record. The public HTTP
service cannot access the local registry. Keep client details in that registry
and authorized local documents.

## Collect and validate

Extract facts into Planner's `details` fields: `full_name`, `sex` (`male`/`female`),
exact `birth_year`, `email`, `phone`, `telegram`, integer `telegram_id`, `whatsapp`,
`max_messenger`, `brokers`, `primary_channel` and registration-purpose `note`.
The primary channel values are `email`, `phone`, `telegram`, `whatsapp`, `max`;
it needs the matching contact. Residency is separate: explicit calendar year and
assigned two-letter ISO country code, plus an optional note.

Ask one grouped question for missing details and let the user answer unknown,
none or skip for each. Only the name is required. Preserve a known partial name;
request the exact birth year instead of deriving it from an approximate age.
Missing brokers means unknown: omit `brokers` or pass null. Explicitly no brokers
means `brokers: []`. Preserve supplied order, resolve empty broker names and
case-only repetitions before writing. Show unsupported supplied facts and explain
that they have no registry field; do not hide investment goals/profile in `note`.

Do not ask for generated `id`, `code` or `created_at`. `ips_sent_at` records a
previously sent declaration; it does not request document generation. Unknown
fields are rejected. Do not invent extra fields to carry facts.

## Create once and resolve duplicates

1. Check `client_list` for possible existing records, including alternate spelling
   and matching contacts. The server checks normalized full names; it cannot
   decide whether differently named records describe the same person.
2. Generate a unique `request_id` for this creation operation and retain it for all
   retries. Call `client_create` with `details` and that ID. Default
   `allow_duplicate` is false.
3. `status: duplicate` returns candidates without creating anything. Show their
   codes and ask whether this is an existing client or a different namesake. For
   an existing person use the selected code; change details only if requested via
   `client_update(code, changes)`. For a confirmed different namesake, repeat the
   unpersisted request with `allow_duplicate: true` and the same ID.
4. Keep the returned stable identifier when the result is `status: created`
   or `replayed`. The returned `client.code` is that identifier (e.g. `c-0001`). Changing the input after a completed ID is an error; use `client_update`
   for later edits. A lost response must be retried with the same ID and input.
5. A pending receipt means a process interrupted creation. Inspect `client_list`
   and `client_get`, report the ambiguity, and stop creation until it is resolved.
   A new ID or automatic namesake override can create an unwanted second record.

For each supplied residency call `client_set_tax_residency` with
`{"code": "<assigned-code>", "residency": {"year": 2026, "country": "DE"}}`,
using the actual supplied year/country. Repeating this updates that year. If a
later step fails, continue with the retained code; never create the person again.

## Verify and report

Read `client_get(code)` and compare each supplied field to the saved record.
Read each explicit year via `client_get_tax_residency(code, year)`; earlier years
are not inherited. Report the stable code, saved details, skipped/unknown fields
and unsupported facts. A YAML document or a conversation note is not proof of
persistence. Registry storage records residence; it does not calculate taxes.
