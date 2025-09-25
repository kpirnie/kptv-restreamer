#!/usr/bin/env python3
"""
HLS/TS Stream Restreamer
A Python application for restreaming live HLS and TS streams from multiple sources.
"""

import asyncio
import aiohttp
import re
import json
import yaml
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set, Tuple, Any
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urljoin, urlparse
import argparse
from contextlib import asynccontextmanager
import hashlib
import base64
from urllib.parse import quote, unquote

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import StreamingResponse, PlainTextResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
from pydantic import BaseModel


# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


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


@dataclass
class FilterConfig:
    """Configuration for stream filtering"""
    include_name_patterns: List[str] = field(default_factory=list)
    include_stream_patterns: List[str] = field(default_factory=list)
    exclude_name_patterns: List[str] = field(default_factory=list)
    exclude_stream_patterns: List[str] = field(default_factory=list)


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


class StreamNameMapper:
    """Handles stream name encoding/decoding for URL safety"""
    
    def __init__(self):
        self.name_to_id = {}
        self.id_to_name = {}
        self._lock = asyncio.Lock()
    
    def _generate_safe_id(self, name: str) -> str:
        """Generate a URL-safe ID from stream name - alphanumeric only"""
        # Keep only alphanumeric characters
        clean_id = re.sub(r'[^a-zA-Z0-9]', '', name)
        
        # Ensure we have something
        if not clean_id:
            clean_id = "unknownstream"
        
        return clean_id
    
    async def get_stream_id(self, name: str) -> str:
        """Get URL-safe ID for stream name"""
        async with self._lock:
            if name not in self.name_to_id:
                stream_id = self._generate_safe_id(name)
                
                # Handle duplicates by appending number
                base_id = stream_id
                counter = 1
                while stream_id in self.id_to_name:
                    stream_id = f"{base_id}{counter}"
                    counter += 1
                
                # Store both directions
                self.name_to_id[name] = stream_id
                self.id_to_name[stream_id] = name
            
            return self.name_to_id[name]
    
    async def get_stream_name(self, stream_id: str) -> str:
        """Get original stream name from URL-safe ID"""
        async with self._lock:
            return self.id_to_name.get(stream_id, "")
    
    async def get_all_mappings(self) -> dict:
        """Get all current mappings for debugging"""
        async with self._lock:
            return {
                "name_to_id": self.name_to_id.copy(),
                "id_to_name": self.id_to_name.copy(),
                "total_streams": len(self.name_to_id),
                "total_unique_ids": len(self.id_to_name)
            }


class ConnectionManager:
    """Manages connection limits and tracking"""
    
    def __init__(self, max_total: int):
        self.max_total = max_total
        self.source_connections: Dict[str, int] = {}
        self.source_limits: Dict[str, int] = {}
        self.total_connections = 0
        self._lock = asyncio.Lock()
    
    def can_acquire_connection(self, source_id: str) -> bool:
        """Check if a connection can be acquired without actually acquiring it"""
        current_source = self.source_connections.get(source_id, 0)
        source_limit = self.source_limits.get(source_id, 5)
        
        return (current_source < source_limit and 
                self.total_connections < self.max_total)

    async def acquire_connection(self, source_id: str) -> bool:
        """Attempt to acquire a connection for a source"""
        async with self._lock:
            current_source = self.source_connections.get(source_id, 0)
            source_limit = self.source_limits.get(source_id, 5)
            
            if (current_source < source_limit and 
                self.total_connections < self.max_total):
                self.source_connections[source_id] = current_source + 1
                self.total_connections += 1
                return True
            return False
    
    async def release_connection(self, source_id: str):
        """Release a connection for a source"""
        async with self._lock:
            if source_id in self.source_connections:
                self.source_connections[source_id] = max(0, 
                    self.source_connections[source_id] - 1)
                self.total_connections = max(0, self.total_connections - 1)
    
    def set_source_limit(self, source_id: str, limit: int):
        """Set connection limit for a source"""
        self.source_limits[source_id] = limit

    async def get_connection_info(self) -> Dict[str, Any]:
        """Get detailed connection information"""
        async with self._lock:
            return {
                "total_connections": self.total_connections,
                "max_total": self.max_total,
                "available_total": self.max_total - self.total_connections,
                "source_connections": self.source_connections.copy(),
                "source_limits": self.source_limits.copy(),
                "source_availability": {
                    source: limit - self.source_connections.get(source, 0)
                    for source, limit in self.source_limits.items()
                }
            }


class StreamSource:
    """Base class for stream sources"""
    
    def __init__(self, config: SourceConfig, session: aiohttp.ClientSession):
        self.config = config
        self.session = session
        self.streams: Dict[str, StreamInfo] = {}
        self.last_refresh = None
        self._refresh_lock = asyncio.Lock()
    
    async def should_refresh(self) -> bool:
        """Check if source needs refreshing"""
        if self.last_refresh is None:
            return True
        
        elapsed = datetime.now() - self.last_refresh
        return elapsed.total_seconds() >= self.config.refresh_interval
    
    async def refresh_streams(self) -> bool:
        """Refresh stream list from source"""
        async with self._refresh_lock:
            if not await self.should_refresh():
                return True
            
            try:
                streams = await self._fetch_streams()
                self.streams = {s.name: s for s in streams}
                self.last_refresh = datetime.now()
                logger.info(f"Refreshed {len(self.streams)} streams from {self.config.name}")
                return True
            except Exception as e:
                logger.error(f"Failed to refresh streams from {self.config.name}: {e}")
                return False
    
    async def _fetch_streams(self) -> List[StreamInfo]:
        """Fetch streams from source (implemented by subclasses)"""
        raise NotImplementedError


class XtreamSource(StreamSource):
    """XStream Codes API source"""
    
    async def _fetch_streams(self) -> List[StreamInfo]:
        streams = []
        
        # Fetch live streams
        live_url = f"{self.config.url}/player_api.php"
        params = {
            'username': self.config.username,
            'password': self.config.password,
            'action': 'get_live_streams'
        }
        
        try:
            async with self.session.get(live_url, params=params) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    for stream in data:
                        stream_url = f"{self.config.url}/live/{self.config.username}/{self.config.password}/{stream.get('stream_id', '')}.ts"
                        
                        streams.append(StreamInfo(
                            name=stream.get('name', ''),
                            url=stream_url,
                            source_id=self.config.name,
                            category=stream.get('category_name', ''),
                            logo=stream.get('stream_icon', ''),
                            stream_id=str(stream.get('stream_id', ''))
                        ))
        except Exception as e:
            logger.error(f"Failed to fetch live streams: {e}")
        
        # Fetch VOD streams
        try:
            vod_params = params.copy()
            vod_params['action'] = 'get_vod_streams'
            
            async with self.session.get(live_url, params=vod_params) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    for stream in data:
                        stream_url = f"{self.config.url}/movie/{self.config.username}/{self.config.password}/{stream.get('stream_id', '')}.mp4"
                        
                        streams.append(StreamInfo(
                            name=stream.get('name', ''),
                            url=stream_url,
                            source_id=self.config.name,
                            category=stream.get('category_name', ''),
                            logo=stream.get('stream_icon', ''),
                            stream_id=str(stream.get('stream_id', ''))
                        ))
        except Exception as e:
            logger.error(f"Failed to fetch VOD streams: {e}")
        
        # Fetch series
        try:
            series_params = params.copy()
            series_params['action'] = 'get_series'
            
            async with self.session.get(live_url, params=series_params) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    for series in data:
                        # For series, we need to get episodes
                        series_id = series.get('series_id', '')
                        series_name = series.get('name', '')
                        
                        streams.append(StreamInfo(
                            name=f"{series_name} (Series)",
                            url=f"{self.config.url}/series/{self.config.username}/{self.config.password}/{series_id}.ts",
                            source_id=self.config.name,
                            category=series.get('category_name', ''),
                            logo=series.get('cover', ''),
                            stream_id=str(series_id)
                        ))
        except Exception as e:
            logger.error(f"Failed to fetch series: {e}")
        
        return streams


class M3USource(StreamSource):
    """M3U playlist source"""
    
    async def _fetch_streams(self) -> List[StreamInfo]:
        streams = []
        
        try:
            async with self.session.get(self.config.url) as resp:
                if resp.status == 200:
                    content = await resp.text()
                    streams = self._parse_m3u(content)
        except Exception as e:
            logger.error(f"Failed to fetch M3U playlist: {e}")
        
        return streams
    
    def _parse_m3u(self, content: str) -> List[StreamInfo]:
        """Parse M3U playlist content"""
        streams = []
        lines = content.strip().split('\n')
        
        current_info = {}
        for line in lines:
            line = line.strip()
            
            if line.startswith('#EXTINF:'):
                # Parse EXTINF line for metadata
                parts = line.split(',', 1)
                if len(parts) == 2:
                    current_info['name'] = parts[1].strip()
                
                # Parse additional attributes
                if 'group-title=' in line:
                    match = re.search(r'group-title="([^"]*)"', line)
                    if match:
                        current_info['group'] = match.group(1)
                
                if 'tvg-logo=' in line:
                    match = re.search(r'tvg-logo="([^"]*)"', line)
                    if match:
                        current_info['logo'] = match.group(1)
                
                if 'tvg-name=' in line:
                    match = re.search(r'tvg-name="([^"]*)"', line)
                    if match:
                        current_info['name'] = match.group(1)
            
            elif line and not line.startswith('#'):
                # This is a stream URL
                if 'name' in current_info:
                    streams.append(StreamInfo(
                        name=current_info.get('name', 'Unknown'),
                        url=line,
                        source_id=self.config.name,
                        group=current_info.get('group', ''),
                        logo=current_info.get('logo', '')
                    ))
                current_info = {}
        
        return streams


class StreamFilter:
    """Handles stream filtering based on regex patterns"""
    
    def __init__(self, config: FilterConfig):
        self.config = config
        self._compile_patterns()
    
    def _compile_patterns(self):
        """Compile regex patterns"""
        try:
            self.include_name_regex = [re.compile(p, re.IGNORECASE) 
                                      for p in self.config.include_name_patterns]
            self.include_stream_regex = [re.compile(p, re.IGNORECASE) 
                                        for p in self.config.include_stream_patterns]
            self.exclude_name_regex = [re.compile(p, re.IGNORECASE) 
                                      for p in self.config.exclude_name_patterns]
            self.exclude_stream_regex = [re.compile(p, re.IGNORECASE) 
                                        for p in self.config.exclude_stream_patterns]
        except re.error as e:
            logger.error(f"Invalid regex pattern: {e}")
            # Fallback to empty patterns
            self.include_name_regex = []
            self.include_stream_regex = []
            self.exclude_name_regex = []
            self.exclude_stream_regex = []
    
    def should_include_stream(self, stream: StreamInfo) -> bool:
        """Check if stream should be included based on filters"""
        try:
            # Check exclude patterns first
            for pattern in self.exclude_name_regex:
                if pattern.search(stream.name):
                    return False
            
            for pattern in self.exclude_stream_regex:
                if pattern.search(stream.url):
                    return False
            
            # Check include patterns
            if self.include_name_regex:
                name_match = any(pattern.search(stream.name) 
                               for pattern in self.include_name_regex)
                if not name_match:
                    return False
            
            if self.include_stream_regex:
                stream_match = any(pattern.search(stream.url) 
                                 for pattern in self.include_stream_regex)
                if not stream_match:
                    return False
            
            return True
        except Exception as e:
            logger.error(f"Error filtering stream {stream.name}: {e}")
            return False


class StreamAggregator:
    """Aggregates and groups streams from multiple sources"""
    
    def __init__(self, stream_filter: StreamFilter):
        self.sources: Dict[str, StreamSource] = {}
        self.filter = stream_filter
        self.grouped_streams: Dict[str, List[StreamInfo]] = {}
        self._lock = asyncio.Lock()
    
    def add_source(self, source: StreamSource):
        """Add a stream source"""
        self.sources[source.config.name] = source
    
    async def refresh_all_sources(self):
        """Refresh all sources and rebuild grouped streams"""
        tasks = []
        for source in self.sources.values():
            if source.config.enabled:
                tasks.append(source.refresh_streams())
        
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        await self._rebuild_grouped_streams()
    
    async def _rebuild_grouped_streams(self):
        """Rebuild grouped streams from all sources"""
        async with self._lock:
            self.grouped_streams.clear()
            
            for source in self.sources.values():
                if not source.config.enabled:
                    continue
                
                for stream in source.streams.values():
                    if self.filter.should_include_stream(stream):
                        name = stream.name
                        if name not in self.grouped_streams:
                            self.grouped_streams[name] = []
                        self.grouped_streams[name].append(stream)
            
            logger.info(f"Grouped {len(self.grouped_streams)} unique streams")
    
    def get_grouped_streams(self) -> Dict[str, List[StreamInfo]]:
        """Get current grouped streams"""
        return self.grouped_streams.copy()


class StreamRestreamer:
    """Main application class"""
    
    def __init__(self, config: AppConfig):
        self.config = config
        self.session = None
        self.connection_manager = ConnectionManager(config.max_total_connections)
        self.stream_filter = StreamFilter(config.filters)
        self.aggregator = StreamAggregator(self.stream_filter)
        self.name_mapper = StreamNameMapper()
        self.refresh_task = None
    
    async def initialize(self):
        """Initialize the application"""
        # Create HTTP session with longer timeout for streaming
        timeout = aiohttp.ClientTimeout(
            total=None,  # No total timeout for streaming
            connect=30,  # 30 seconds to connect
            sock_read=300  # 5 minutes for reading data
        )
        connector = aiohttp.TCPConnector(
            limit=100, 
            limit_per_host=20,
            keepalive_timeout=300,  # Keep connections alive for 5 minutes
            enable_cleanup_closed=True
        )
        self.session = aiohttp.ClientSession(timeout=timeout, connector=connector)
        
        # Setup sources
        for source_config in self.config.sources:
            self.connection_manager.set_source_limit(
                source_config.name, source_config.max_connections)
            
            if source_config.type == 'xtream':
                source = XtreamSource(source_config, self.session)
            elif source_config.type == 'm3u':
                source = M3USource(source_config, self.session)
            else:
                logger.warning(f"Unknown source type: {source_config.type}")
                continue
            
            self.aggregator.add_source(source)
        
        # Start refresh task
        self.refresh_task = asyncio.create_task(self._refresh_loop())
        
        # Initial refresh
        await self.aggregator.refresh_all_sources()
 
    async def cleanup(self):
        """Cleanup resources"""
        if self.refresh_task:
            self.refresh_task.cancel()
            try:
                await self.refresh_task
            except asyncio.CancelledError:
                pass
        
        if self.session:
            await self.session.close()
    
    async def _refresh_loop(self):
        """Background task to refresh sources"""
        while True:
            try:
                await asyncio.sleep(60)  # Check every minute
                await self.aggregator.refresh_all_sources()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in refresh loop: {e}")
        
    async def get_m3u8_playlist(self) -> str:
        """Generate M3U8 playlist of all grouped streams"""
        grouped_streams = self.aggregator.get_grouped_streams()
        
        lines = ['#EXTM3U']
        
        for name, streams in grouped_streams.items():
            # Use the first stream for metadata
            primary_stream = streams[0]
            
            extinf = f'#EXTINF:-1'
            if primary_stream.group:
                extinf += f' group-title="{primary_stream.group}"'
            if primary_stream.logo:
                extinf += f' tvg-logo="{primary_stream.logo}"'
            extinf += f',{name}'
            
            lines.append(extinf)
            
            # Get URL-safe ID for this stream name
            stream_id = await self.name_mapper.get_stream_id(name)
            full_url = f"{self.config.public_url.rstrip('/')}/stream/{stream_id}"
            lines.append(full_url)
        
        return '\n'.join(lines)

    async def test_stream_url(self, url: str) -> bool:
        """Test if a stream URL is accessible"""
        try:
            async with self.session.head(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                return resp.status == 200
        except Exception as e:
            logger.error(f"Stream test failed for {url}: {e}")
            return False

    async def stream_content(self, stream_id: str):
        """Stream content for a specific stream with automatic failover"""
        # Get original stream name from the URL-safe ID
        stream_name = await self.name_mapper.get_stream_name(stream_id)
        if not stream_name:
            # Try to find by direct lookup in grouped streams
            grouped_streams = self.aggregator.get_grouped_streams()
            for name in grouped_streams.keys():
                test_id = await self.name_mapper.get_stream_id(name)
                if test_id == stream_id:
                    stream_name = name
                    break
            
            if not stream_name:
                # Debug: log all available mappings
                mappings = await self.name_mapper.get_all_mappings()
                logger.error(f"Stream ID '{stream_id}' not found in mappings. Available: {list(mappings['id_to_name'].keys())}")
                raise HTTPException(status_code=404, detail=f"Stream ID '{stream_id}' not found")
        
        grouped_streams = self.aggregator.get_grouped_streams()
        
        # Find stream by original name
        target_streams = grouped_streams.get(stream_name)
        if target_streams is None:
            # Try case-insensitive search
            stream_name_lower = stream_name.lower()
            for name, streams in grouped_streams.items():
                if name.lower() == stream_name_lower:
                    target_streams = streams
                    stream_name = name  # Use the correct case
                    break
            
            if target_streams is None:
                # Debug: log available streams
                available_streams = list(grouped_streams.keys())
                logger.error(f"Stream '{stream_name}' not found in sources. Available streams: {available_streams[:10]}...")  # First 10 only
                raise HTTPException(status_code=404, detail=f"Stream '{stream_name}' not found in sources")
        
        logger.info(f"Starting stream for '{stream_name}' with {len(target_streams)} available sources")
        
        # Sort streams by connection availability (sources with available connections first)
        def get_source_availability(stream):
            source_id = stream.source_id
            current_conn = self.connection_manager.source_connections.get(source_id, 0)
            max_conn = self.connection_manager.source_limits.get(source_id, 5)
            available = max_conn - current_conn
            return available
        
        # Sort by availability (highest first), capturing original indices first
        indexed_streams = [(i, stream) for i, stream in enumerate(target_streams)]
        indexed_streams.sort(key=lambda x: (-get_source_availability(x[1]), x[0]))
        target_streams = [stream for _, stream in indexed_streams]
        
        async def try_stream_source(stream_index: int) -> tuple:
            """Try to connect to a specific stream source with connection limiting"""
            if stream_index >= len(target_streams):
                return None, "No more sources available"
            
            stream = target_streams[stream_index]
            source_id = stream.source_id
            
            # Check connection availability BEFORE acquiring
            if not self.connection_manager.can_acquire_connection(source_id):
                return None, f"Connection limit reached for source {source_id} ({self.connection_manager.source_connections.get(source_id, 0)}/{self.connection_manager.source_limits.get(source_id, 5)})"
            
            # Try to acquire connection for this source
            connection_acquired = await self.connection_manager.acquire_connection(source_id)
            if not connection_acquired:
                return None, f"Failed to acquire connection for source {source_id} (concurrent limit reached)"
            
            connection_released = False
            try:
                logger.info(f"Attempting source {stream_index + 1}/{len(target_streams)}: {source_id} (conns: {self.connection_manager.source_connections.get(source_id, 0)}/{self.connection_manager.source_limits.get(source_id, 5)}) -> {stream.url}")
                
                # Test if this is an HLS playlist
                is_hls_playlist = any(ext in stream.url.lower() for ext in ['.m3u8', '.m3u'])
                
                if is_hls_playlist:
                    # Handle HLS playlist - fetch content and return immediately
                    async with self.session.get(stream.url, allow_redirects=True, timeout=30) as resp:
                        if resp.status == 200:
                            content = await resp.text()
                            logger.info(f"HLS playlist fetched successfully from {source_id}")
                            return ("hls", content, source_id, stream), None
                        else:
                            return None, f"HTTP {resp.status} from HLS playlist"
                else:
                    # Handle direct stream with shorter timeout for initial connection
                    resp = await self.session.get(
                        stream.url, 
                        allow_redirects=True,
                        timeout=aiohttp.ClientTimeout(connect=15, sock_read=30)
                    )
                    
                    if resp.status == 200:
                        logger.info(f"Stream connection established to {source_id}")
                        return ("stream", resp, source_id, stream), None
                    else:
                        resp.close()
                        return None, f"HTTP {resp.status} from stream"
                        
            except asyncio.TimeoutError:
                return None, "Connection timeout"
            except aiohttp.ClientError as e:
                return None, f"Client error: {str(e)}"
            except Exception as e:
                return None, f"Unexpected error: {str(e)}"
            finally:
                # If we return None (failure), release the connection immediately
                if not connection_released and connection_acquired:
                    await self.connection_manager.release_connection(source_id)
                    connection_released = True
        
        # Try each source in sequence (now sorted by availability)
        current_source_index = 0
        last_error = None
        successful_connection = None
        
        while current_source_index < len(target_streams):
            result, error = await try_stream_source(current_source_index)
            
            if result is not None:
                successful_connection = result
                break
            
            # This source failed, try next one
            last_error = error
            logger.warning(f"Source {current_source_index + 1} failed: {error}")
            current_source_index += 1
        
        if successful_connection is None:
            # All sources failed
            error_msg = f"All {len(target_streams)} sources failed for '{stream_name}'. Last error: {last_error}"
            
            # Include connection info in error message
            conn_info = await self.connection_manager.get_connection_info()
            source_status = []
            for stream in target_streams:
                source_id = stream.source_id
                current = conn_info["source_connections"].get(source_id, 0)
                max_conn = conn_info["source_limits"].get(source_id, 5)
                source_status.append(f"{source_id}: {current}/{max_conn}")
            
            error_msg += f". Connection status: {', '.join(source_status)}"
            logger.error(error_msg)
            raise HTTPException(status_code=503, detail=error_msg)
        
        # We have a successful connection
        stream_type, data, source_id, stream = successful_connection
        
        if stream_type == "hls":
            # HLS content is returned immediately (connection already released in try_stream_source)
            return PlainTextResponse(content=data, media_type="application/vnd.apple.mpegurl")
        
        # We have a live stream connection
        resp = data
        
        async def generate_stream_with_failover():
            nonlocal current_source_index, resp, source_id, stream
            current_chunk_count = 0
            current_source_connected = True
            connection_released = False
            
            try:
                while True:
                    try:
                        if not current_source_connected:
                            # Try to reconnect to next available source
                            next_index = current_source_index + 1
                            while next_index < len(target_streams):
                                next_stream = target_streams[next_index]
                                next_source_id = next_stream.source_id
                                
                                # Check if this source has available connections
                                if self.connection_manager.can_acquire_connection(next_source_id):
                                    result, error = await try_stream_source(next_index)
                                    if result is not None and result[0] == "stream":
                                        # Successfully failed over
                                        resp = result[1]
                                        source_id = result[2]
                                        stream = result[3]
                                        current_source_index = next_index
                                        current_source_connected = True
                                        current_chunk_count = 0
                                        logger.info(f"Failover successful to source {next_index + 1} ({source_id})")
                                        break
                                    else:
                                        logger.warning(f"Failover attempt to source {next_index + 1} failed: {error}")
                                else:
                                    logger.debug(f"Skipping source {next_index + 1} ({next_source_id}) - connection limit reached")
                                
                                next_index += 1
                            else:
                                # No more sources available
                                logger.error("No more sources available for failover")
                                break
                        
                        # Stream data from current source
                        async for chunk in resp.content.iter_chunked(8192):
                            if not chunk:  # Empty chunk indicates end of stream
                                break
                                
                            current_chunk_count += 1
                            yield chunk
                            
                            # Log progress periodically
                            if current_chunk_count % 1000 == 0:
                                # Log current connection status
                                conn_info = await self.connection_manager.get_connection_info()
                                current_conn = conn_info["source_connections"].get(source_id, 0)
                                max_conn = conn_info["source_limits"].get(source_id, 5)
                                logger.debug(f"Streamed {current_chunk_count} chunks from {source_id} (conns: {current_conn}/{max_conn})")
                        
                        # If we get here, stream ended normally
                        logger.info(f"Stream ended normally from {source_id} after {current_chunk_count} chunks")
                        break
                        
                    except (asyncio.TimeoutError, aiohttp.ClientPayloadError) as e:
                        # These are recoverable errors - try failover
                        logger.warning(f"Stream error from {source_id}: {type(e).__name__}")
                        current_source_connected = False
                        
                        # Clean up current connection
                        if not connection_released:
                            try:
                                resp.close()
                                await self.connection_manager.release_connection(source_id)
                                connection_released = True
                                logger.info(f"Released connection for {source_id} due to error")
                            except Exception as e:
                                logger.error(f"Error releasing connection: {e}")
                        
                    except (aiohttp.ClientError, ConnectionError) as e:
                        # More serious connection errors
                        logger.error(f"Connection error from {source_id}: {type(e).__name__}: {str(e)}")
                        current_source_connected = False
                        
                        # Clean up current connection
                        if not connection_released:
                            try:
                                resp.close()
                                await self.connection_manager.release_connection(source_id)
                                connection_released = True
                                logger.info(f"Released connection for {source_id} due to connection error")
                            except Exception as e:
                                logger.error(f"Error releasing connection: {e}")
                        
                    except Exception as e:
                        # Unexpected errors
                        logger.error(f"Unexpected error during streaming: {type(e).__name__}: {str(e)}")
                        break
            
            except asyncio.CancelledError:
                logger.info(f"Streaming cancelled for '{stream_name}'")
                raise
            
            finally:
                # Ensure connection is released
                if not connection_released:
                    try:
                        resp.close()
                        await self.connection_manager.release_connection(source_id)
                        logger.info(f"Released connection for {source_id} after streaming")
                    except Exception as e:
                        logger.error(f"Error releasing connection: {e}")
        
        # Determine appropriate media type
        content_type = resp.headers.get('content-type', '').lower()
        if any(ext in stream.url.lower() for ext in ['.ts', '.m2ts']):
            media_type = "video/mp2t"
        elif any(ext in stream.url.lower() for ext in ['.m3u8', '.m3u']):
            media_type = "application/vnd.apple.mpegurl"
        elif 'mp4' in content_type or stream.url.lower().endswith('.mp4'):
            media_type = "video/mp4"
        else:
            media_type = "video/mp2t"  # Default to TS
        
        # Return streaming response
        return StreamingResponse(
            generate_stream_with_failover(),
            media_type=media_type,
            headers={
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Pragma": "no-cache",
                "Expires": "0",
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Headers": "*",
                "Access-Control-Allow-Methods": "GET, HEAD",
            }
        )

# Global restreamer instance
restreamer: Optional[StreamRestreamer] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan manager"""
    global restreamer
    
    # Startup
    if restreamer:
        await restreamer.initialize()
    
    yield
    
    # Shutdown
    if restreamer:
        await restreamer.cleanup()


# FastAPI application
app = FastAPI(
    title="KPTV Restreamer",
    description="Restream HLS/TS streams from multiple sources",
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Fix route ordering - specific routes first, generic routes last
@app.get("/")
async def root():
    """Root endpoint with API information"""
    return {
        "message": "HLS Stream Restreamer API",
        "version": "1.0.0",
        "endpoints": {
            "playlist": "/playlist.m3u8",
            "status": "/status",
            "streams": "/streams",
            "stream": "/stream/{stream_id}",
            "active_streams": "/active-streams"
        }
    }

@app.get("/playlist.m3u8")
async def get_playlist():
    """Get M3U8 playlist of all streams"""
    if not restreamer:
        raise HTTPException(status_code=503, detail="Service not initialized")
    
    playlist = await restreamer.get_m3u8_playlist()
    return PlainTextResponse(content=playlist, media_type="application/vnd.apple.mpegurl")

@app.get("/status")
async def get_status():
    """Get service status"""
    if not restreamer:
        return {"status": "not_initialized"}
    
    grouped_streams = restreamer.aggregator.get_grouped_streams()
    connection_info = await restreamer.connection_manager.get_connection_info()
    
    source_status = {}
    for source_name, source in restreamer.aggregator.sources.items():
        current_connections = connection_info["source_connections"].get(source_name, 0)
        max_connections = connection_info["source_limits"].get(source_name, 5)
        
        source_status[source_name] = {
            "enabled": source.config.enabled,
            "streams": len(source.streams),
            "connections": {
                "current": current_connections,
                "max": max_connections,
                "available": max_connections - current_connections
            },
            "last_refresh": source.last_refresh.isoformat() if source.last_refresh else None
        }
    
    return {
        "status": "running",
        "total_streams": len(grouped_streams),
        "sources": len(restreamer.aggregator.sources),
        "connections": connection_info,
        "source_details": source_status
    }

@app.get("/active-streams")
async def get_active_streams():
    """Get information about currently active streams"""
    if not restreamer:
        raise HTTPException(status_code=503, detail="Service not initialized")
    
    connection_info = await restreamer.connection_manager.get_connection_info()
    active_streams = []
    
    for source_name, count in connection_info["source_connections"].items():
        if count > 0:
            active_streams.append({
                "source": source_name,
                "connections": count,
                "limit": connection_info["source_limits"].get(source_name, 5)
            })
    
    return {
        "total_active_connections": connection_info["total_connections"],
        "active_streams": active_streams
    }

@app.get("/streams")
async def get_streams():
    """Get list of all available streams with metadata"""
    if not restreamer:
        raise HTTPException(status_code=503, detail="Service not initialized")
    
    grouped_streams = restreamer.aggregator.get_grouped_streams()
    streams_info = []
    
    for name, streams in grouped_streams.items():
        primary_stream = streams[0]
        stream_id = await restreamer.name_mapper.get_stream_id(name)
        
        streams_info.append({
            "id": stream_id,
            "name": name,
            "group": primary_stream.group,
            "logo": primary_stream.logo,
            "sources": len(streams),
            "source_names": [s.source_id for s in streams],
            "url": f"{restreamer.config.public_url.rstrip('/')}/stream/{stream_id}"
        })
    
    return {"streams": streams_info}

@app.get("/stream/{stream_id}")
async def stream_stream(stream_id: str):
    """Stream a specific channel"""
    if not restreamer:
        raise HTTPException(status_code=503, detail="Service not initialized")
    
    return await restreamer.stream_content(stream_id)

@app.get("/debug/mappings")
async def debug_mappings():
    """Debug endpoint to see name mappings"""
    if not restreamer:
        raise HTTPException(status_code=503, detail="Service not initialized")
    
    return await restreamer.name_mapper.get_all_mappings()

@app.get("/debug/streams/{source_name}")
async def debug_source_streams(source_name: str):
    """Debug endpoint to see streams from a specific source"""
    if not restreamer:
        raise HTTPException(status_code=503, detail="Service not initialized")
    
    source = restreamer.aggregator.sources.get(source_name)
    if not source:
        raise HTTPException(status_code=404, detail=f"Source '{source_name}' not found")
    
    return {
        "source": source_name,
        "streams": [{"name": s.name, "url": s.url} for s in source.streams.values()]
    }

@app.get("/debug/grouped-streams")
async def debug_grouped_streams():
    """Debug endpoint to see grouped streams"""
    if not restreamer:
        raise HTTPException(status_code=503, detail="Service not initialized")
    
    grouped_streams = restreamer.aggregator.get_grouped_streams()
    
    result = {}
    for name, streams in grouped_streams.items():
        stream_id = await restreamer.name_mapper.get_stream_id(name)
        result[name] = {
            "id": stream_id,
            "sources": [s.source_id for s in streams],
            "urls": [s.url for s in streams]
        }
    
    return result


def load_config(config_path: str) -> AppConfig:
    """Load configuration from YAML file"""
    config_file = Path(config_path)
    
    if not config_file.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")
    
    with open(config_file, 'r') as f:
        config_data = yaml.safe_load(f)
    
    # Parse sources
    sources = []
    for source_data in config_data.get('sources', []):
        sources.append(SourceConfig(
            name=source_data['name'],
            type=source_data['type'],
            url=source_data['url'],
            username=source_data.get('username'),
            password=source_data.get('password'),
            max_connections=source_data.get('max_connections', 5),
            refresh_interval=source_data.get('refresh_interval', 300),
            enabled=source_data.get('enabled', True)
        ))
    
    # Parse filters
    filter_data = config_data.get('filters', {})
    filters = FilterConfig(
        include_name_patterns=filter_data.get('include_name_patterns', []),
        include_stream_patterns=filter_data.get('include_stream_patterns', []),
        exclude_name_patterns=filter_data.get('exclude_name_patterns', []),
        exclude_stream_patterns=filter_data.get('exclude_stream_patterns', [])
    )
    
    # Parse main config
    return AppConfig(
        sources=sources,
        filters=filters,
        max_total_connections=config_data.get('max_total_connections', 100),
        bind_host=config_data.get('bind_host', '0.0.0.0'),
        bind_port=config_data.get('bind_port', 8080),
        public_url=config_data.get('public_url', 'http://localhost:8080'),
        log_level=config_data.get('log_level', 'INFO')
    )


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(description="HLS Stream Restreamer")
    parser.add_argument(
        "--config", 
        default="config.yaml", 
        help="Path to configuration file (default: config.yaml)"
    )
    parser.add_argument(
        "--host",
        help="Override bind host from config"
    )
    parser.add_argument(
        "--port", 
        type=int,
        help="Override bind port from config"
    )
    
    args = parser.parse_args()
    
    try:
        # Load configuration
        config = load_config(args.config)
        
        # Apply command line overrides
        if args.host:
            config.bind_host = args.host
        if args.port:
            config.bind_port = args.port
        
        # Set log level
        logging.getLogger().setLevel(getattr(logging, config.log_level.upper()))
        
        # Create and set global restreamer instance
        global restreamer
        restreamer = StreamRestreamer(config)
        
        # Start server
        logger.info(f"Starting server on {config.bind_host}:{config.bind_port}")
        uvicorn.run(
            app,
            host=config.bind_host,
            port=config.bind_port,
            log_level=config.log_level.lower()
        )
    
    except FileNotFoundError as e:
        logger.error(f"Configuration error: {e}")
        logger.info("Create a config.yaml file or specify a different path with --config")
    except Exception as e:
        logger.error(f"Failed to start: {e}")
        raise


if __name__ == "__main__":
    main()