AsyncAPI specs for Service Bus commands/events live here. Every command schema
requires: tenant, site, device, correlation_id, expiry, idempotency_key.
The C# edge connector and the Python outbox validate against these files.
