"""eCourtsIndia Partner API integration for the Maharashtra Courts app."""

from .client import EcourtsIndiaClient, EcourtsIndiaError
from .routes import eci_bp

__all__ = ["EcourtsIndiaClient", "EcourtsIndiaError", "eci_bp"]
