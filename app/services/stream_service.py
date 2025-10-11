#!/usr/bin/env python3
"""
Stream Service Module

This module handles stream processing and delivery to clients.
It manages playlist generation, stream resolution, failover logic, and content streaming.

@package KPTV Restreamer
@author Kevin Pirnie <me@kpirnie.com>
@copyright Copyright (c) 2025
"""

# setup the imports
import logging, asyncio
from typing import Optional
from fastapi import HTTPException
from fastapi.responses import StreamingResponse

from app.models import AppConfig
from app.services import (
    ConnectionManager,
    StreamCache,
    StreamNameMapper,
    StreamFilter,
    StreamAggregator
)

# setup the logger
logger = logging.getLogger(__name__)

"""
Handles stream processing and delivery

Manages stream resolution, failover, caching, and delivery to clients.
"""
class StreamService:
    
    """
    Initialize the StreamService
    Sets up all service dependencies for stream processing and delivery.

    @param config: AppConfig Application configuration
    @param session: aiohttp.ClientSession HTTP session
    @param connection_manager: ConnectionManager Connection limit manager
    @param stream_cache: StreamCache Stream caching manager
    @param name_mapper: StreamNameMapper Stream ID mapper
    @param aggregator: StreamAggregator Stream aggregator
    """
    def __init__(
        self,
        config: AppConfig,
        session,
        connection_manager: ConnectionManager,
        stream_cache: StreamCache,
        name_mapper: StreamNameMapper,
        aggregator: StreamAggregator
    ):
        
        # setup the internals
        self.config = config
        self.session = session
        self.connection_manager = connection_manager
        self.stream_cache = stream_cache
        self.name_mapper = name_mapper
        self.aggregator = aggregator
    
    """
    Generate M3U8 playlist of all grouped streams
    Creates unified M3U8 playlist with all available streams and metadata.

    @return str: M3U8 playlist content
    """
    async def get_m3u8_playlist(self) -> str:
        
        # get the grouped streams
        grouped_streams = self.aggregator.get_grouped_streams()
        
        # set the first line that we need to output
        lines = ['#EXTM3U']
        
        # loop over each stream in the groups
        for name, streams in grouped_streams.items():

            # set and hold the primary stream
            primary_stream = streams[0]

            # apply prefix and suffix
            display_name = f"{self.config.stream_name_prefix}{name}{self.config.stream_name_suffix}"
            
            # start up the ext-inf string line
            extinf = f'#EXTINF:-1'
            if primary_stream.tvg_id:
                extinf += f' tvg-id="{primary_stream.tvg_id}"'
            if primary_stream.tvg_name:
                extinf += f' tvg-name="{primary_stream.tvg_name}"'
            if primary_stream.tvg_language:
                extinf += f' tvg-language="{primary_stream.tvg_language}"'
            if primary_stream.tvg_country:
                extinf += f' tvg-country="{primary_stream.tvg_country}"'
            if primary_stream.tvg_url:
                extinf += f' tvg-url="{primary_stream.tvg_url}"'
            if primary_stream.group:
                extinf += f' group-title="{primary_stream.group}"'
            if primary_stream.logo:
                extinf += f' tvg-logo="{primary_stream.logo}"'
            if primary_stream.radio:
                extinf += f' radio="{primary_stream.radio}"'
            if primary_stream.aspect_ratio:
                extinf += f' aspect-ratio="{primary_stream.aspect_ratio}"'
            if primary_stream.audio_track:
                extinf += f' audio-track="{primary_stream.audio_track}"'
            
            # now we need to append the name
            extinf += f', {display_name}'
            
            # append it to our list
            lines.append(extinf)
            
            # grab our stream id and the full url
            stream_id = await self.name_mapper.get_stream_id(name)
            full_url = f"{self.config.public_url.rstrip('/')}/stream/{stream_id}"
            
            # append the streams url line
            lines.append(full_url)
        
        # return all lines
        return '\n'.join(lines)
    
    """
    Resolve stream ID to stream name
    Looks up stream name from ID, falling back to full search if needed.

    @param stream_id: str Stream identifier to resolve
    @return str: Resolved stream name
    @throws HTTPException: 404 if stream ID not found
    """
    async def resolve_stream_name(self, stream_id: str) -> str:
        """Resolve stream ID to stream name"""
        stream_name = await self.name_mapper.get_stream_name(stream_id)
        if not stream_name:
            grouped_streams = self.aggregator.get_grouped_streams()
            for name in grouped_streams.keys():
                test_id = await self.name_mapper.get_stream_id(name)
                if test_id == stream_id:
                    stream_name = name
                    break
            
            if not stream_name:
                raise HTTPException(status_code=404, detail=f"Stream ID '{stream_id}' not found")
        
        return stream_name
    
    """
    Get target streams for a given stream name
    Retrieves all source streams for the specified stream name.

    @param stream_name: str Name of stream to retrieve
    @return tuple: (target_streams, resolved_stream_name)
    @throws HTTPException: 404 if stream not found
    """
    def get_target_streams(self, stream_name: str):
        """Get target streams for a given stream name"""
        grouped_streams = self.aggregator.get_grouped_streams()
        target_streams = grouped_streams.get(stream_name)
        
        if target_streams is None:
            stream_name_lower = stream_name.lower()
            for name, streams in grouped_streams.items():
                if name.lower() == stream_name_lower:
                    target_streams = streams
                    stream_name = name
                    break
            
            if target_streams is None:
                raise HTTPException(status_code=404, detail=f"Stream '{stream_name}' not found")
        
        return target_streams, stream_name
    
    """
    Sort streams by source availability
    Orders streams prioritizing sources with most available connections.

    @param streams: list List of StreamInfo objects to sort
    @return list: Sorted list of streams
    """
    def sort_streams_by_availability(self, streams):
        """Sort streams by source availability"""
        def get_source_availability(stream):
            source_id = stream.source_id
            return self.connection_manager.source_limits.get(source_id, 5) - \
                   self.connection_manager.source_connections.get(source_id, 0)
        
        indexed_streams = [(i, stream) for i, stream in enumerate(streams)]
        indexed_streams.sort(key=lambda x: (-get_source_availability(x[1]), x[0]))
        return [stream for _, stream in indexed_streams]
    
    """
    Stream content using cache
    Resolves stream, handles failover, and delivers cached stream to client.

    @param stream_id: str Stream identifier to stream
    @return StreamingResponse: Streaming response with content
    @throws HTTPException: 503 if all sources fail, 404 if stream not found
    """
    async def stream_content(self, stream_id: str):
        """Stream content using cache"""
        stream_name = await self.resolve_stream_name(stream_id)
        target_streams, stream_name = self.get_target_streams(stream_name)
        
        logger.info(f"Request for stream '{stream_name}' with {len(target_streams)} sources")
        
        target_streams = self.sort_streams_by_availability(target_streams)
        
        last_error = None
        for stream_idx, stream in enumerate(target_streams):
            source_id = stream.source_id
            
            if not self.connection_manager.can_acquire_connection(source_id):
                logger.debug(f"Source {source_id} at connection limit, trying next")
                continue
            
            try:
                cached_stream = await self.stream_cache.get_or_create_stream(
                    stream_name=stream_name,
                    stream_url=stream.url,
                    source_id=source_id,
                    media_type=self._get_media_type(stream.url)
                )
                
                if cached_stream.connection_error:
                    raise Exception(cached_stream.connection_error)
                
                consumer_id = cached_stream.get_next_consumer_id()
                
                logger.info(f"Serving stream '{stream_name}' from cache (consumer {consumer_id})")
                
                async def generate_from_cache():
                    try:
                        start_pos = cached_stream.buffer.buffer_position
                        
                        async for chunk in cached_stream.buffer.consume_from(
                            consumer_id, start_pos
                        ):
                            yield chunk
                            
                    except asyncio.CancelledError:
                        logger.info(f"Consumer {consumer_id} cancelled for '{stream_name}'")
                        raise
                    except Exception as e:
                        logger.error(f"Error in consumer {consumer_id}: {e}")
                        raise
                
                media_type = self._get_media_type(stream.url)
                
                return StreamingResponse(
                    generate_from_cache(),
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
            
            except Exception as e:
                last_error = str(e)
                logger.warning(f"Source {stream_idx + 1} failed: {e}")
                continue
        
        error_msg = f"All {len(target_streams)} sources failed for '{stream_name}'. Last error: {last_error}"
        logger.error(error_msg)
        raise HTTPException(status_code=503, detail=error_msg)
    
    """
    Determine media type from URL
    Examines URL extension to determine appropriate MIME type.

    @param url: str Stream URL to analyze
    @return str: MIME type for the stream
    """
    def _get_media_type(self, url: str) -> str:
        """Determine media type from URL"""
        url_lower = url.lower()
        if any(ext in url_lower for ext in ['.ts', '.m2ts']):
            return "video/mp2t"
        elif any(ext in url_lower for ext in ['.m3u8', '.m3u']):
            return "application/vnd.apple.mpegurl"
        elif '.mp4' in url_lower:
            return "video/mp4"
        else:
            return "video/mp2t"
        