#!/usr/bin/env python3
"""
Stream Data Models Module

This module defines all data models and configuration classes for the KPTV Restreamer.
It includes models for streams, sources, filters, and application configuration.

@package KPTV Restreamer
@author Kevin Pirnie <me@kpirnie.com>
@copyright Copyright (c) 2025
"""

# add our imports
from dataclasses import dataclass, field
from typing import List, Optional

"""
Information about a single stream

Contains metadata and URL information for an individual stream from a source.
"""
@dataclass
class StreamInfo:
    """Information about a single stream"""
    name: str
    url: str
    source_id: str
    category: str = ""
    group: str = ""
    logo: str = ""
    stream_id: Optional[str] = None
    tvg_id: str = ""
    tvg_name: str = ""
    tvg_language: str = ""
    tvg_country: str = ""
    tvg_url: str = ""
    radio: str = ""
    aspect_ratio: str = ""
    audio_track: str = ""
    epg_channel_id: str = ""
    parent_code: str = ""
    display_name: str = ""

"""
Configuration for a stream source

Defines connection parameters and behavior for a single stream source provider.
"""
@dataclass
class SourceConfig:
    """Configuration for a stream source"""
    name: str
    type: str  # 'xtream' or 'm3u'
    url: str
    username: Optional[str] = None
    password: Optional[str] = None
    max_connections: int = 5
    refresh_interval: int = 300  # seconds
    enabled: bool = True
    exp_date: Optional[str] = None
    epg_url: Optional[str] = None
    stream_name_prefix: str = ""
    stream_name_suffix: str = ""

"""
Configuration for stream filtering

Defines regex patterns for including or excluding streams based on names and URLs.
"""
@dataclass
class FilterConfig:
    """Configuration for stream filtering"""
    include_name_patterns: List[str] = field(default_factory=list)
    include_stream_patterns: List[str] = field(default_factory=list)
    exclude_name_patterns: List[str] = field(default_factory=list)
    exclude_stream_patterns: List[str] = field(default_factory=list)

"""
Xtream API authentication configuration

Contains credentials and settings for Xtream Codes API compatibility.
"""
@dataclass
class XtreamAuthConfig:
    """Xtream API authentication configuration"""
    enabled: bool = False
    username: str = "admin"
    password: str = "admin"

"""
Main application configuration

Top-level configuration containing all sources, filters, and global settings.
"""
@dataclass
class AppConfig:
    """Main application configuration"""
    sources: List[SourceConfig] = field(default_factory=list)
    filters: FilterConfig = field(default_factory=FilterConfig)
    max_total_connections: int = 100
    bind_host: str = "0.0.0.0"
    bind_port: int = 8080
    public_url: str = "http://localhost:8080"
    log_level: str = "INFO"
    xtream_auth: XtreamAuthConfig = field(default_factory=XtreamAuthConfig)
    