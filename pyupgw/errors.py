"""Errors defined by the library"""


class ClientError(Exception):
    """Error in client operation"""


class AuthenticationError(ClientError):
    """Error in authentication"""
