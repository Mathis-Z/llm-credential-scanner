"""
Definition of all DB models used in the scanner.
"""

import json
import peewee as pw

from .db import BaseModel

# list of credentials that should always be tested
# TODO: this should probably be expanded and also moved out of this file
DEFAULT_CREDS = [('admin', 'admin'), ('admin', 'password'), ('username', 'password')]

class Service(BaseModel):
    """A discovered service with host, port and https true/false"""
    pk = pw.AutoField()
    host = pw.CharField(max_length=64)
    port = pw.IntegerField()
    https = pw.BooleanField()
    enum_in_progress = pw.BooleanField(default=False)
    _credentials = pw.TextField(null=True, default=None) # None means not searched yet

    class Meta:
        constraints = [pw.SQL('UNIQUE (host, port)')]

    def url(self):
        protocol = 'https' if self.https else 'http'
        return f"{protocol}://{self.host}:{self.port}"

    def __str__(self):
        return self.url()

    @property
    def credentials(self):
        # must convert to tuple to make them hashable
        return [tuple(cred_pair) for cred_pair in json.loads(self._credentials)] if self._credentials else None

    @credentials.setter
    def credentials(self, new_value):
        self._credentials = json.dumps(new_value)

    def add_credentials(self, creds: tuple[str, str]):
        """Add a (user,password) tuple to the list of possible default credentials for this service"""
        existing = json.loads(self._credentials or '[]')
        # Normalize all credentials to tuples before de-duplication
        normalized = [tuple(pair) for pair in existing] + [tuple(creds)]
        self.credentials = list(set(normalized))

    def gather_keywords(self):
        """Gathers all keywords from all endpoints of this service. Removes duplicates"""
        keywords = set()
        for endpoint in self.endpoints: # pylint: disable=E1101
            keywords = keywords.union(set(endpoint.keywords or []))
        return list(keywords)

    def endpoint_with_working_creds_found(self):
        return self.endpoints.where(Endpoint.working_credentials != '').count() > 0


class Endpoint(BaseModel):
    """A path on a service that responded with a non-error status code"""
    pk = pw.AutoField()
    service = pw.ForeignKeyField(Service, backref='endpoints')
    path = pw.CharField()
    initial_path = pw.CharField() # the first path used to reach this endpoint (before redirects)
    is_login = pw.BooleanField(default=False)
    page_source = pw.TextField() # raw HTML of the page at this endpoint
    md_hash = pw.CharField(max_length=32) # hash of whitespace-stripped, markdownified page source; for endpoint de-duplication
    # keywords from the page at this endpoint; None means not analyzed yet
    _keywords = pw.TextField(null=True, default=None)
    _tested_credentials = pw.TextField(default="[]") # for login panels only
    working_credentials = pw.CharField(default="")

    class Meta:
        constraints = [pw.SQL('UNIQUE (service_id, path)')]

    def url(self):
        return f"{self.service.url()}/{str(self.path).lstrip('/')}"

    @property
    def keywords(self):
        return json.loads(self._keywords) if self._keywords else None

    @keywords.setter
    def keywords(self, value: list[str]):
        self._keywords = json.dumps(value)

    @property
    def tested_credentials(self):
        # must convert to tuple to make them hashable
        return [tuple(cred_pair) for cred_pair in json.loads(self._tested_credentials)]

    @tested_credentials.setter
    def tested_credentials(self, new_value):
        self._tested_credentials = json.dumps(new_value)

    def add_tested_credentials(self, creds_pair):
        self.tested_credentials = list(set(self.tested_credentials + [creds_pair]))

    def untested_credentials(self):
        """The list of credentials that still need to be tested on this login"""
        if self.is_login:
            return list(set(self.service.credentials or DEFAULT_CREDS) - set(self.tested_credentials))
        else:
            return []

# TODO: if this was implemented, a CVE matching would be easy to implement
# but how to identify application version?
#class ServiceIdentity(BaseModel):
#    """The identity of a service, including identifier and version, as determined by the LLM"""
#    service = pw.ForeignKeyField(model=Service, unique=True, primary_key=True)
#    identifier = pw.CharField(max_length=128) # identifier string for this software, e.g., OpenSSH
#    version = pw.CharField(max_length=128) # version identifier, e.g., 9.2p1
#    github_url = pw.CharField(max_length=256, null=True) # optional GitHub URL for this software
#    documentation_url = pw.CharField(max_length=256, null=True) # optional documentation URL for this software
