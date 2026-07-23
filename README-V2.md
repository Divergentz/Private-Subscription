# Divergentz Subscription v2

Generated files:

- `divergentz.txt`: configurations whose host and port accepted a TCP connection.
- `all-configs.txt`: all collected and deduplicated configurations.
- `health-report.json`: parsing and TCP test report.
- `sub.txt`: compatibility copy of `divergentz.txt`.

Important: TCP success is only a preliminary health check. It does not prove
that authentication, TLS, Reality, WebSocket, gRPC, or full proxy traffic works.
