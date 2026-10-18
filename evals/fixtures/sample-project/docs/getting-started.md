# Getting started with Sentinel SDK

## Start a session

Call `initialize_user_session(user_id, session_timeout)` with the user's ID and
a timeout in milliseconds:

```python
from auth_service import initialize_user_session

session = initialize_user_session("user-42", 30000)
```

## Run an audit

Call `start_audit(api_key)` to scan every Markdown file in the current folder:

```python
from audit import start_audit

result = start_audit("YOUR_KEY")
```

## End the session

Call `end_user_session(session)` when you are done.
