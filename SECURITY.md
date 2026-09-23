# Security configuration

The application uses safe development defaults, but a deployed instance should set these environment variables:

- `SECRET_KEY`: a stable random value of at least 32 bytes. If omitted, a random key is generated at startup, which is safe for local use but does not preserve sessions across restarts or multiple workers.
- `ALLOWED_ORIGINS`: comma-separated HTTPS origins allowed to connect to Socket.IO, for example `https://anagrams.example.com`. If omitted, Socket.IO permits same-origin connections only.
- `COOKIE_SECURE=true`: enable this whenever the deployment uses HTTPS.
HTTP and Socket.IO payloads are capped at 64 KiB. Expensive dictionary, hint, bot, definition, and puzzle endpoints have in-process per-client rate limits. A multi-instance public deployment should additionally enforce rate limits at its reverse proxy.
