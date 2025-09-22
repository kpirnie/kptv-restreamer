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
                            url=f"{self.config.url}/series/{self.config.username}/{self.config.password}/{series_id}.m3u8",
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


class StreamNameMapper:
    """Maps stream names to short hashes for URL generation"""
    
    def __init__(self):
        self.name_to_hash: Dict[str, str] = {}
        self.hash_to_name: Dict[str, str] = {}
    
    def get_hash(self, channel_name: str) -> str:
        """Get hash for channel name, creating if needed"""
        if channel_name in self.name_to_hash:
            return self.name_to_hash[channel_name]
        
        import hashlib
        hash_obj = hashlib.sha256(channel_name.encode('utf-8'))
        hash_str = hash_obj.hexdigest()[:16]
        
        self.name_to_hash[channel_name] = hash_str
        self.hash_to_name[hash_str] = channel_name
        return hash_str
    
    def get_name(self, hash_str: str) -> Optional[str]:
        """Get channel name from hash"""
        return self.hash_to_name.get(hash_str)
    
    def clear(self):
        """Clear all mappings"""
        self.name_to_hash.clear()
        self.hash_to_name.clear()


class StreamAggregator:
    """Aggregates and groups streams from multiple sources"""
    
    def __init__(self, stream_filter: StreamFilter):
        self.sources: Dict[str, StreamSource] = {}
        self.filter = stream_filter
        self.grouped_streams: Dict[str, List[StreamInfo]] = {}
        self.name_mapper = StreamNameMapper()
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
            self.name_mapper.clear()
            
            for source in self.sources.values():
                if not source.config.enabled:
                    continue
                
                for stream in source.streams.values():
                    if self.filter.should_include_stream(stream):
                        name = stream.name
                        if name not in self.grouped_streams:
                            self.grouped_streams[name] = []
                            self.name_mapper.get_hash(name)
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
            
            # Use hash instead of normalization
            stream_hash = self.aggregator.name_mapper.get_hash(name)
            full_url = f"{self.config.public_url.rstrip('/')}/stream/{stream_hash}"
            lines.append(full_url)
        
        return '\n'.join(lines)


    def get_available_sources_for_stream(self, stream_hash: str) -> List[StreamInfo]:
        """Get available sources for a stream, ordered by connection availability"""
        # Get original name from hash
        stream_name = self.aggregator.name_mapper.get_name(stream_hash)
        if not stream_name:
            return []
        
        grouped_streams = self.aggregator.get_grouped_streams()
        target_streams = grouped_streams.get(stream_name)
        
        if not target_streams:
            return []
        
        # Sort streams by connection availability
        available_streams = []
        unavailable_streams = []
        
        for stream in target_streams:
            if self.connection_manager.can_acquire_connection(stream.source_id):
                available_streams.append(stream)
            else:
                unavailable_streams.append(stream)
        
        # Return available sources first, then unavailable ones
        return available_streams + unavailable_streams

    async def stream_content(self, stream_hash: str):
        """Stream content for a specific stream with automatic failover"""
        # Get original name from hash
        stream_name = self.aggregator.name_mapper.get_name(stream_hash)
        if not stream_name:
            raise HTTPException(status_code=404, detail="Stream not found")
        
        grouped_streams = self.aggregator.get_grouped_streams()
        target_streams = grouped_streams.get(stream_name)
        
        if target_streams is None:
            raise HTTPException(status_code=404, detail="Stream not found")
        
        # Try streams in order until one works (automatic failover)
        last_error = None
        current_stream_index = 0
        
        async def try_next_source():
            nonlocal current_stream_index, last_error
            
            while current_stream_index < len(target_streams):
                stream = target_streams[current_stream_index]
                source_id = stream.source_id
                
                # Try to acquire connection for this source
                connection_acquired = await self.connection_manager.acquire_connection(source_id)
                if not connection_acquired:
                    logger.warning(f"Connection limit reached for source {source_id}, trying next source")
                    current_stream_index += 1
                    continue
                
                try:
                    logger.info(f"Attempting to stream from source {source_id} ({current_stream_index+1}/{len(target_streams)}): {stream.url}")
                    
                    # Determine stream type by URL extension
                    is_hls_playlist = stream.url.lower().endswith('.m3u8')
                    
                    if is_hls_playlist:
                        # Handle HLS playlist - fetch content and return immediately
                        async with self.session.get(stream.url, allow_redirects=True) as resp:
                            if resp.status == 200:
                                logger.info(f"Successfully fetched HLS playlist from {stream.url}")
                                content = await resp.text()
                                await self.connection_manager.release_connection(source_id)
                                return PlainTextResponse(content=content, media_type="application/vnd.apple.mpegurl")
                            else:
                                logger.warning(f"HTTP {resp.status} from HLS playlist {stream.url}")
                                last_error = f"HTTP {resp.status}"
                                await self.connection_manager.release_connection(source_id)
                                current_stream_index += 1
                                continue
                                
                    else:
                        # Handle direct streams with automatic failover
                        resp = await self.session.get(stream.url, allow_redirects=True)
                        
                        if resp.status == 200:
                            logger.info(f"Successfully connected to stream {stream.url}")
                            return (resp, source_id, stream)
                        else:
                            logger.warning(f"HTTP {resp.status} from stream {stream.url}")
                            last_error = f"HTTP {resp.status}"
                            resp.close()
                            await self.connection_manager.release_connection(source_id)
                            current_stream_index += 1
                            continue
                                
                except Exception as e:
                    logger.error(f"Error connecting to stream from source {source_id}: {type(e).__name__}: {str(e)}")
                    last_error = f"{type(e).__name__}: {str(e)}"
                    await self.connection_manager.release_connection(source_id)
                    current_stream_index += 1
                    continue
            
            return None
        
        # Get initial stream
        result = await try_next_source()
        if result is None:
            
            # All sources failed due to connection limits - serve offline stream
            error_msg = f"All {len(target_streams)} sources failed"
            if last_error:
                error_msg += f". Last error: {last_error}"
            logger.warning(f"{error_msg}. Serving offline stream for {stream_name}")
            
            # Stream the offline video instead
            try:
                offline_url = "https://cdn.kevp.us/tv/offline.mkv"
                resp = await self.session.get(offline_url, allow_redirects=True)
                
                if resp.status == 200:
                    logger.info(f"Serving offline stream for {stream_name}")
                    
                    async def generate_offline_stream():
                        try:
                            async for chunk in resp.content.iter_chunked(8192):
                                yield chunk
                        except Exception as e:
                            logger.error(f"Error streaming offline content: {e}")
                        finally:
                            try:
                                resp.close()
                            except Exception:
                                pass
                    
                    return StreamingResponse(
                        generate_offline_stream(),
                        media_type="video/x-matroska",
                        headers={
                            "Cache-Control": "no-cache, no-store, must-revalidate",
                            "Pragma": "no-cache",
                            "Expires": "0",
                            "Connection": "keep-alive",
                            "Accept-Ranges": "bytes"
                        }
                    )
                else:
                    logger.error(f"Failed to fetch offline stream: HTTP {resp.status}")
                    resp.close()
                    raise HTTPException(status_code=503, detail=error_msg)
                    
            except Exception as e:
                logger.error(f"Error serving offline stream: {e}")
                raise HTTPException(status_code=503, detail=error_msg)
        
        # If it's an HLS playlist, it was already returned
        if isinstance(result, PlainTextResponse):
            return result
        
        # Handle streaming with automatic failover
        resp, source_id, current_stream = result
        
        async def generate_stream_with_failover():
            nonlocal current_stream_index, resp, source_id, current_stream
            connection_released = False
            chunk_count = 0
            
            try:
                while True:
                    try:
                        async for chunk in resp.content.iter_chunked(8192):
                            chunk_count += 1
                            yield chunk
                            
                            # Log progress every 1000 chunks
                            if chunk_count % 1000 == 0:
                                logger.debug(f"Streamed {chunk_count} chunks for {stream_name} from {source_id}")
                        
                        # If we reach here, the stream ended normally
                        logger.info(f"Stream ended normally for {stream_name} from {source_id} after {chunk_count} chunks")
                        break
                        
                    except (asyncio.TimeoutError, aiohttp.ClientError, ConnectionError) as e:
                        logger.warning(f"Stream error for {stream_name} from {source_id} after {chunk_count} chunks: {type(e).__name__}: {str(e)}")
                        
                        # Clean up current connection
                        try:
                            resp.close()
                            if not connection_released:
                                await self.connection_manager.release_connection(source_id)
                                connection_released = True
                        except Exception:
                            pass
                        
                        # Try next source
                        current_stream_index += 1
                        if current_stream_index >= len(target_streams):
                            logger.error(f"No more sources available for {stream_name}")
                            break
                        
                        # Get next stream
                        result = await try_next_source()
                        if result is None:
                            logger.error(f"Failed to failover to next source for {stream_name}")
                            break
                        
                        # Update current stream info
                        resp, source_id, current_stream = result
                        connection_released = False
                        logger.info(f"Failover successful for {stream_name} to source {source_id}")
                        
            except asyncio.CancelledError:
                logger.info(f"Streaming cancelled for {stream_name} from {source_id}")
                raise
            except Exception as e:
                logger.error(f"Unexpected error during streaming for {stream_name} from {source_id}: {type(e).__name__}: {str(e)}")
                raise
            finally:
                if not connection_released:
                    try:
                        resp.close()
                        await self.connection_manager.release_connection(source_id)
                        logger.info(f"Released connection for source {source_id} after streaming {chunk_count} chunks")
                    except Exception as e:
                        logger.error(f"Error releasing connection for {source_id}: {e}")
        
        # Determine media type
        content_type = resp.headers.get('content-type', '').lower()
        if current_stream.url.lower().endswith('.ts') or 'mp2t' in content_type:
            media_type = "video/mp2t"
        elif 'mpegurl' in content_type:
            media_type = "application/vnd.apple.mpegurl"
        else:
            media_type = "application/octet-stream"
        
        return StreamingResponse(
            generate_stream_with_failover(),
            media_type=media_type,
            headers={
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Pragma": "no-cache",
                "Expires": "0",
                "Connection": "keep-alive",
                "Accept-Ranges": "bytes"
            }
        )

    async def test_stream_url(self, url: str) -> bool:
        """Test if a stream URL is accessible"""
        try:
            async with self.session.head(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                return resp.status == 200
        except Exception as e:
            logger.error(f"Stream test failed for {url}: {e}")
            return False


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
    title="HLS Stream Restreamer",
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

@app.get("/playlist.m3u8")
async def get_playlist():
    """Get M3U8 playlist of all streams"""
    if not restreamer:
        raise HTTPException(status_code=503, detail="Service not initialized")
    
    playlist = await restreamer.get_m3u8_playlist()
    return PlainTextResponse(content=playlist, media_type="application/vnd.apple.mpegurl")


@app.get("/stream/{stream_hash:path}")
async def stream_channel(stream_hash: str):
    """Stream a specific channel"""
    if not restreamer:
        raise HTTPException(status_code=503, detail="Service not initialized")
    
    return await restreamer.stream_content(stream_hash)


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
    
    return {
        "active_connections": connection_info["total_connections"],
        "max_connections": connection_info["max_total"],
        "connections_by_source": connection_info["source_connections"],
        "availability_by_source": connection_info["source_availability"]
    }

@app.get("/streams")
async def list_streams():
    """List all available streams"""
    if not restreamer:
        raise HTTPException(status_code=503, detail="Service not initialized")
    
    grouped_streams = restreamer.aggregator.get_grouped_streams()
    
    streams_list = []
    for name, streams in grouped_streams.items():
        primary_stream = streams[0]
        stream_hash = restreamer.aggregator.name_mapper.get_hash(name)
        streams_list.append({
            "name": name,
            "hash": stream_hash,
            "url": f"/stream/{stream_hash}",
            "full_url": f"{restreamer.config.public_url.rstrip('/')}/stream/{stream_hash}",
            "sources": len(streams),
            "category": primary_stream.category,
            "group": primary_stream.group,
            "logo": primary_stream.logo
        })
    
    return {"streams": streams_list}

@app.get("/direct/{stream_hash:path}")
async def direct_stream_test(stream_hash: str):
    """Test direct access to first source for a stream"""
    if not restreamer:
        raise HTTPException(status_code=503, detail="Service not initialized")
    
    # Get original name from hash
    stream_name = restreamer.aggregator.name_mapper.get_name(stream_hash)
    if not stream_name:
        raise HTTPException(status_code=404, detail="Stream not found")
    
    grouped_streams = restreamer.aggregator.get_grouped_streams()
    streams = grouped_streams.get(stream_name)
    
    if streams:
        first_stream = streams[0]
        logger.info(f"Direct test access to: {first_stream.url}")
        
        return Response(
            status_code=302,
            headers={"Location": first_stream.url}
        )
    
    raise HTTPException(status_code=404, detail="Stream not found")
    
@app.get("/test")
async def test_streams():
    """Test accessibility of all streams"""
    if not restreamer:
        raise HTTPException(status_code=503, detail="Service not initialized")
    
    grouped_streams = restreamer.aggregator.get_grouped_streams()
    results = {}
    
    for name, streams in list(grouped_streams.items())[:10]:  # Test first 10 streams
        stream_hash = restreamer.aggregator.name_mapper.get_hash(name)
        test_results = []
        
        for stream in streams:
            try:
                async with restreamer.session.head(stream.url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    is_accessible = resp.status == 200
                    content_type = resp.headers.get('content-type', 'unknown')
                    
                    test_results.append({
                        "source": stream.source_id,
                        "url": stream.url,
                        "accessible": is_accessible,
                        "status_code": resp.status,
                        "content_type": content_type,
                        "stream_type": "HLS" if stream.url.endswith('.m3u8') else "TS" if stream.url.endswith('.ts') else "Unknown"
                    })
            except Exception as e:
                test_results.append({
                    "source": stream.source_id,
                    "url": stream.url,
                    "accessible": False,
                    "error": str(e),
                    "stream_type": "HLS" if stream.url.endswith('.m3u8') else "TS" if stream.url.endswith('.ts') else "Unknown"
                })
        
        results[stream_hash] = {
            "original_name": name,
            "hash": stream_hash,
            "our_stream_url": f"/stream/{stream_hash}",
            "direct_test_url": f"/direct/{stream_hash}",
            "streams": test_results
        }
    
    return results

@app.get("/debug/{stream_hash:path}")
async def debug_stream(stream_hash: str):
    """Debug stream information"""
    if not restreamer:
        raise HTTPException(status_code=503, detail="Service not initialized")
    
    # Get original name from hash
    stream_name = restreamer.aggregator.name_mapper.get_name(stream_hash)
    if not stream_name:
        raise HTTPException(status_code=404, detail="Stream not found")
    
    grouped_streams = restreamer.aggregator.get_grouped_streams()
    streams = grouped_streams.get(stream_name)
    
    if streams:
        debug_info = {
            "original_name": stream_name,
            "hash": stream_hash,
            "stream_count": len(streams),
            "streams": []
        }
        
        for i, stream in enumerate(streams):
            try:
                # Test the stream URL
                async with restreamer.session.head(stream.url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    stream_info = {
                        "index": i,
                        "source_id": stream.source_id,
                        "url": stream.url,
                        "status_code": resp.status,
                        "content_type": resp.headers.get('content-type', 'unknown'),
                        "content_length": resp.headers.get('content-length', 'unknown'),
                        "stream_type": "HLS" if stream.url.endswith('.m3u8') else "TS" if stream.url.endswith('.ts') else "Unknown",
                        "accessible": resp.status == 200
                    }
            except Exception as e:
                stream_info = {
                    "index": i,
                    "source_id": stream.source_id,
                    "url": stream.url,
                    "error": str(e),
                    "accessible": False
                }
            
            debug_info["streams"].append(stream_info)
        
        return debug_info
    
    raise HTTPException(status_code=404, detail="Stream not found")

def load_config(config_path: str) -> AppConfig:
    """Load configuration from file"""
    path = Path(config_path)
    
    if not path.exists():
        # Create default config
        default_config = {
            'sources': [
                {
                    'name': 'example_xtream',
                    'type': 'xtream',
                    'url': 'http://example.com:8080',
                    'username': 'your_username',
                    'password': 'your_password',
                    'max_connections': 5,
                    'refresh_interval': 300,
                    'enabled': False
                },
                {
                    'name': 'example_m3u',
                    'type': 'm3u',
                    'url': 'http://example.com/playlist.m3u',
                    'max_connections': 3,
                    'refresh_interval': 600,
                    'enabled': False
                }
            ],
            'filters': {
                'include_name_patterns': [],
                'include_stream_patterns': [],
                'exclude_name_patterns': ['.*test.*'],
                'exclude_stream_patterns': []
            },
            'max_total_connections': 100,
            'bind_host': '0.0.0.0',
            'bind_port': 8080,
            'public_url': 'http://localhost:8080',
            'log_level': 'INFO'
        }
        
        with open(config_path, 'w') as f:
            yaml.dump(default_config, f, default_flow_style=False)
        
        logger.info(f"Created default config at {config_path}")
        return AppConfig()
    
    with open(config_path, 'r') as f:
        if config_path.endswith('.json'):
            data = json.load(f)
        else:
            data = yaml.safe_load(f)
    
    # Convert to dataclasses
    sources = [SourceConfig(**s) for s in data.get('sources', [])]
    filters = FilterConfig(**data.get('filters', {}))
    
    return AppConfig(
        sources=sources,
        filters=filters,
        max_total_connections=data.get('max_total_connections', 100),
        bind_host=data.get('bind_host', '0.0.0.0'),
        bind_port=data.get('bind_port', 8080),
        public_url=data.get('public_url', 'http://localhost:8080'),
        log_level=data.get('log_level', 'INFO')
    )

def main():
    """Main entry point"""
    global restreamer
    
    parser = argparse.ArgumentParser(description='HLS Stream Restreamer')
    parser.add_argument('--config', '-c', default='config.yaml',
                       help='Configuration file path')
    
    args = parser.parse_args()
    
    # Load configuration
    config = load_config(args.config)
    
    # Setup logging
    logging.getLogger().setLevel(getattr(logging, config.log_level.upper()))
    
    # Create restreamer instance
    restreamer = StreamRestreamer(config)
    
    # Run server
    uvicorn.run(
        app,
        host=config.bind_host,
        port=config.bind_port,
        log_level=config.log_level.lower()
    )


if __name__ == '__main__':
    main()
    