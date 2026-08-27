from app.security.local_auth import get_or_create_local_token


def get_cli_auth_token() -> str:
    """
    Obtain the existing ULTRON local authentication token through
    the application's secret-storage abstraction.

    The CLI never reads the token file directly.
    """
    return get_or_create_local_token()