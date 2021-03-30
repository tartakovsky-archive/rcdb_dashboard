from ninja import Schema


class CredentialData(Schema):
    access_token: str
    token_type: str = 'bearer'
