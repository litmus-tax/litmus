"""What every command runs with: its arguments, connection, output, client and credential."""

import argparse
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from litmus.client.cli.connection import Connection, resolve
from litmus.client.cli.credentials import Store, default_store
from litmus.client.cli.output import Output
from litmus.client.cli.session import Credential, Sessions
from litmus.client.sdk.client import Client


@dataclass
class Context:
  """One command's invocation."""

  args: argparse.Namespace
  environ: Mapping[str, str]
  output: Output
  cwd: Path
  transport: httpx.BaseTransport | None = None
  store_factory: Callable[[Mapping[str, str]], Store] = default_store
  cache: dict[str, object] = field(default_factory=dict[str, object])

  @property
  def connection(self) -> Connection:
    """The deployment, tenant and portfolio (interfaces Rule 7.7)."""
    if 'connection' not in self.cache:
      self.cache['connection'] = resolve(
        url=getattr(self.args, 'url', None),
        tenant=getattr(self.args, 'tenant', None),
        portfolio=getattr(self.args, 'portfolio', None),
        environ=self.environ,
        cwd=self.cwd,
      )
    connection = self.cache['connection']
    assert isinstance(connection, Connection)
    return connection

  @property
  def store(self) -> Store:
    """Where credentials are kept."""
    if 'store' not in self.cache:
      self.cache['store'] = self.store_factory(self.environ)
    return self.cache['store']  # pyright: ignore[reportReturnType]

  def client(self) -> Client:
    """A client for the connection, without a credential until `authorize`."""
    if 'client' not in self.cache:
      self.cache['client'] = Client(self.connection.url, transport=self.transport)
    client = self.cache['client']
    assert isinstance(client, Client)
    return client

  def sessions(self) -> Sessions:
    """The connection's credential finder."""
    return Sessions(self.connection, self.store, self.client(), self.environ)

  def authorize(self, *, tenant: bool = True) -> Client:
    """The client, sending the connection's credential (see `session`)."""
    credential = self.credential(tenant=tenant)
    client = self.client()
    client.token = credential.token
    return client

  def credential(self, *, tenant: bool = True) -> Credential:
    """The credential this command sends."""
    return self.sessions().credential(tenant=tenant)
