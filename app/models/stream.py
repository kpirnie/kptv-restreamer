from dataclasses import dataclass, field
from typing import List, Optional


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


@dataclass
class FilterConfig:
    """Configuration for stream filtering"""
    include_name_patterns: List[str] = field(default_factory=list)
    include_stream_patterns: List[str] = field(default_factory=list)
    exclude_name_patterns: List[str] = field(default_factory=list)
    exclude_stream_patterns: List[str] = field(default_factory=list)


@dataclass
class XtreamAuthConfig:
    """Xtream API authentication configuration"""
    enabled: bool = False
    username: str = "admin"
    password: str = "admin"


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
