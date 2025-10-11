#!/usr/bin/env python3
"""
Services Package Initialization

This package contains all service layer components for the KPTV Restreamer application.
It exports connection management, caching, filtering, aggregation, and streaming services.

@package KPTV Restreamer
@author Kevin Pirnie <me@kpirnie.com>
@copyright Copyright (c) 2025
"""
from .connection_manager import ConnectionManager
from .stream_cache import StreamCache, StreamBuffer, CachedStream
from .stream_mapper import StreamNameMapper
from .stream_filter import StreamFilter
from .stream_aggregator import StreamAggregator
from .stream_service import StreamService

# hold the necessary modules
__all__ = [
    "ConnectionManager",
    "StreamCache",
    "StreamBuffer",
    "CachedStream",
    "StreamNameMapper",
    "StreamFilter",
    "StreamAggregator",
    "StreamService",
]