#!/usr/bin/env python3
"""
Sources Package Initialization

This package contains all stream source implementations for the KPTV Restreamer.
It exports the base class and concrete source types for M3U and Xtream providers.

@package KPTV Restreamer
@author Kevin Pirnie <me@kpirnie.com>
@copyright Copyright (c) 2025
"""

# setup the necessary imports
from .base import StreamSource
from .xtream import XtreamSource
from .m3u import M3USource

# now hold the modules
__all__ = ["StreamSource", "XtreamSource", "M3USource"]