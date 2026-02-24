# auth_service.py

def initialize_user_session(user_id, session_timeout):
    """
    Starts a new session for a verified user.
    """
    print(f"Session started for {user_id} with a {session_timeout}ms timeout.")
    return True