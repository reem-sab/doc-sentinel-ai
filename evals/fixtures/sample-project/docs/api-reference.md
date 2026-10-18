# API reference

## auth_service

### initialize_user_session(user_id, session_timeout)

Starts a new session for a verified user.

| Parameter | Type | Description |
| --- | --- | --- |
| `user_id` | str | The verified user's ID. |
| `session_timeout` | int | Session timeout in milliseconds. |

Returns a session dictionary with `user_id` and `timeout_ms`.

### end_user_session(session)

Ends a session started with `initialize_user_session`. Returns `True`.

## audit

### start_audit(api_key, paths=None)

Starts a documentation audit.

| Parameter | Type | Description |
| --- | --- | --- |
| `api_key` | str | Required. Your API key. |
| `paths` | list[str] | Optional. Files to audit. Defaults to every `.md` file under the current folder. |

Returns a dictionary with the audited `files` and the `retries` setting.
