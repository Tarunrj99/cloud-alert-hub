"""Cloud event adapters. Each function maps a raw cloud event to a
:class:`CanonicalAlert`. Keep per-cloud quirks contained inside these modules.
"""

from .aws_sns import from_aws_sns
from .azure_eventgrid import from_azure_eventgrid
from .gcp_pubsub import from_gcp_pubsub
from .generic import from_generic

__all__ = ["from_aws_sns", "from_azure_eventgrid", "from_gcp_pubsub", "from_generic"]
