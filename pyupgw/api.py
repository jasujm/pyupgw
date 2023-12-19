"""Low level API"""

from pycognito import Cognito
from awscrt.auth import AwsCredentialsProvider
from awscrt.io import ClientTlsContext, TlsContextOptions
import boto3.session

AWS_REGION = "eu-central-1"
AWS_CLIENT_ID = "63qkc36u3eje4lp8ums9njmarv"
AWS_IDENTITY_POOL_ID = "eu-central-1:b0e2bccc-5392-4c36-beca-faf051dc47e2"
AWS_USER_POOL_ID = "eu-central-1_HfciXliKM"
AWS_ID_PROVIDER = "cognito-idp.eu-central-1.amazonaws.com/eu-central-1_HfciXliKM"
AWS_IDENTITY_ENDPOINT = "cognito-identity.eu-central-1.amazonaws.com"

_tls_ctx = ClientTlsContext(TlsContextOptions())
_boto3_session = boto3.session.Session(region_name=AWS_REGION)
_cognito_identity_client = _boto3_session.client("cognito-identity")


def get_authentication(username: str, password: str):
    """Authenticate with `username` and `password`"""
    auth = Cognito(
        user_pool_id=AWS_USER_POOL_ID, client_id=AWS_CLIENT_ID, username=username
    )
    auth.authenticate(password)
    return auth


def get_credentials_provider(auth: Cognito):
    """Get credentials from previous authentication"""
    identity_id_response = _cognito_identity_client.get_id(
        IdentityPoolId=AWS_IDENTITY_POOL_ID, Logins={AWS_ID_PROVIDER: auth.id_token}
    )
    identity_id = identity_id_response["IdentityId"]
    return AwsCredentialsProvider.new_cognito(
        endpoint=AWS_IDENTITY_ENDPOINT,
        identity=identity_id,
        logins=[(AWS_ID_PROVIDER, auth.id_token)],
        tls_ctx=_tls_ctx,
    )
