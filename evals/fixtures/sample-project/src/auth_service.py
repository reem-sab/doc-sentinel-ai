"""Session handling for verified users."""


def initialize_user_session(user_id, session_timeout):
    """
    Start a new session for a verified user.

    session_timeout is in milliseconds.
    """
    print(f"Session started for {user_id} with a {session_timeout}ms timeout.")
    return {"user_id": user_id, "timeout_ms": session_timeout}


def end_user_session(session):
    """End a session started with initialize_user_session."""
    print(f"Session ended for {session['user_id']}.")
    return True
