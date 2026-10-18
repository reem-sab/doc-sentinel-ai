# Sentinel SDK

Sentinel SDK audits Markdown documentation and manages user sessions.

## Quick start

```python
from audit import start_audit

result = start_audit(api_key="YOUR_KEY")
print(result["files"])
```

See [Getting started](docs/getting-started.md) for a walkthrough and the
[API reference](docs/api-reference.md) for every function.
