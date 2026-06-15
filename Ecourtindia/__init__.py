"""eCourtsIndia Partner API integration for the Maharashtra Courts app."""

from .client import EcourtsIndiaClient, EcourtsIndiaError
from .routes import eci_bp
from .secret import get_api_key

__all__ = ["EcourtsIndiaClient", "EcourtsIndiaError", "eci_bp", "get_api_key"]
