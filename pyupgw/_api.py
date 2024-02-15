"""
Low level API

This module is meant for developing the high level client, and should rarely be
used directly.  Breaking changes may be introduced between minor versions.
"""

# pylint: disable=too-many-arguments

import contextlib
import os
import threading
import typing
from collections.abc import Awaitable

import aiohttp
from awscrt.auth import AwsCredentialsProvider
from awscrt.io import ClientTlsContext, TlsContextOptions
from dict_deep import deep_get
from pycognito import Cognito

PYUPGW_AWS_CLIENT_ID = os.getenv(
    "PYUPGW_AWS_CLIENT_ID", default="63qkc36u3eje4lp8ums9njmarv"
)
PYUPGW_AWS_REGION = os.getenv("PYUPGW_AWS_REGION", default="eu-central-1")
PYUPGW_AWS_USER_POOL_ID = os.getenv(
    "PYUPGW_AWS_USER_POOL_ID", default="eu-central-1_HfciXliKM"
)
PYUPGW_AWS_ID_PROVIDER = os.getenv(
    "PYUPGW_AWS_ID_PROVIDER",
    default="cognito-idp.eu-central-1.amazonaws.com/eu-central-1_HfciXliKM",
)
PYUPGW_AWS_IDENTITY_ENDPOINT = os.getenv(
    "PYUPGW_AWS_IDENTITY_ENDPOINT",
    default="cognito-identity.eu-central-1.amazonaws.com",
)
PYUPGW_AWS_IOT_ENDPOINT = os.getenv(
    "PYUPGW_AWS_IOT_ENDPOINT",
    default="a1b4blxx3o9kj3-ats.iot.eu-central-1.amazonaws.com",
)
PYUPGW_SERVICE_API_BASE_URL = os.getenv(
    "PYUPGW_SERVICE_API_BASE_URL", default="https://service-api.purmo.uleeco.com/api/v1"
)
PYUPGW_SERVICE_API_COMPANY = os.getenv("PYUPGW_SERVICE_API_COMPANY", default="purmo")

_tls_ctx = ClientTlsContext(TlsContextOptions())


def is_authentication_error(ex: Exception):
    """
    Return ``True`` if ``ex`` is authentication error, ``False`` otherwise

    This function is necessary, because botocore generates exception types on
    the fly, so it's not possible to just import the correct exception type and
    except it...
    """
    return "NotAuthorized" in str(
        deep_get(ex, ["__class__", "__name__"], getter=getattr)
    )


class AwsApi:
    """Low level AWS API"""

    def __init__(
        self,
        username: str,
        region: str | None = None,
        client_id: str | None = None,
        user_pool_id: str | None = None,
        id_provider: str | None = None,
        identity_endpoint: str | None = None,
    ):
        self._region = region or PYUPGW_AWS_REGION
        self._id_provider = id_provider or PYUPGW_AWS_ID_PROVIDER
        self._identity_endpoint = identity_endpoint or PYUPGW_AWS_IDENTITY_ENDPOINT
        self._cognito = Cognito(
            user_pool_id=user_pool_id or PYUPGW_AWS_USER_POOL_ID,
            client_id=client_id or PYUPGW_AWS_CLIENT_ID,
            username=username,
        )
        self._identity_lock = threading.Lock()
        self._cached_password: str | None = None

    def authenticate(self, password: str) -> tuple[str, str]:
        """Authenticate with ``password``

        Returns:
          Tuple containing id token and access token
        """
        with self._identity_lock:
            self._cognito.authenticate(password)
            self._cached_password = password
        return self._cognito.id_token, self._cognito.access_token

    def check_token(self):
        """Check identity token and refresh if necessary

        Returns:
          ``True`` if the token was refreshed, ``False`` otherwise
        """
        with self._identity_lock:
            try:
                return self._cognito.check_token(renew=True)
            except Exception as ex:
                # Fallback to authenticating with password if refresh token  fails
                if is_authentication_error(ex) and self._cached_password is not None:
                    self._cognito.authenticate(self._cached_password)
                    return True
                raise

    def get_tokens(self) -> tuple[str, str]:
        """Get identity and access tokens from a previous authentication

        Returns:
          Tuple containing id token and access token
        """
        self.check_token()
        return self._cognito.id_token, self._cognito.access_token

    def get_credentials_provider(self, identity_id: str) -> AwsCredentialsProvider:
        """Get credentials for a previously authenticated identity"""
        return AwsCredentialsProvider.new_cognito(
            endpoint=self._identity_endpoint,
            identity=identity_id,
            logins=[(self._id_provider, self._cognito.id_token)],
            tls_ctx=_tls_ctx,
        )


class ServiceApi:
    """Low level service API"""

    def __init__(
        self,
        base_url: str | None = None,
        company: str | None = None,
    ):
        self._base_url = base_url or PYUPGW_SERVICE_API_BASE_URL
        self._company = company or PYUPGW_SERVICE_API_COMPANY

    async def _service_api_get(
        self,
        endpoint: str,
        id_token: str,
        access_token: str,
        client_session: aiohttp.ClientSession | None = None,
        **kwargs,
    ):
        headers: dict[str, str] = kwargs.pop("headers", {})
        headers.update(
            {
                "x-auth-token": id_token,
                "x-company-code": self._company,
                "x-access-token": access_token,
            }
        )
        cs_ctx = (
            typing.cast(
                contextlib.AbstractAsyncContextManager[aiohttp.ClientSession],
                contextlib.nullcontext(client_session),
            )
            if client_session
            else aiohttp.ClientSession()
        )
        async with cs_ctx as cs:
            async with cs.get(
                f"{self._base_url}/{endpoint}",
                headers=headers,
                **kwargs,
            ) as response:
                return await response.json()

    def get_slider_list(
        self,
        id_token: str,
        access_token: str,
        client_session: aiohttp.ClientSession | None = None,
    ) -> Awaitable[typing.Any]:
        """Get slider list from the service API"""
        return self._service_api_get(
            "occupants/slider_list", id_token, access_token, client_session
        )

    def get_slider_details(
        self,
        slider_id: str,
        slider_type: str,
        id_token: str,
        access_token: str,
        client_session: aiohttp.ClientSession | None = None,
    ) -> Awaitable[typing.Any]:
        """Get slider details from the service API"""
        return self._service_api_get(
            "occupants/slider_details",
            id_token,
            access_token,
            client_session,
            params={"id": slider_id, "type": slider_type},
        )
