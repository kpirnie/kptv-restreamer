import logging
import asyncio
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

logger = logging.getLogger(__name__)


class StreamService:
    """Handles stream processing and delivery"""
    
    def __init__(
        self,
        config: AppConfig,
        session,
        connection_manager: ConnectionManager,
        stream_cache: StreamCache,
        name_mapper: StreamNameMapper,
        aggregator: StreamAggregator
    ):
        self.config = config
        self.session = session
        self.connection_manager = connection_manager
        self.stream_cache = stream_cache
        self.name_mapper = name_mapper
        self.aggregator = aggregator
    
    async def get_m3u8_playlist(self) -> str:
        """Generate M3U8 playlist of all grouped streams"""
        grouped_streams = self.aggregator.get_grouped_streams()
        
        lines = ['#EXTM3U']
        
        for name, streams in grouped_streams.items():
            primary_stream = streams[0]
            
            extinf = f'#EXTINF:-1'
            if primary_stream.group:
                extinf += f' group-title="{primary_stream.group}"'
            if primary_stream.logo:
                extinf += f' tvg-logo="{primary_stream.logo}"'
            extinf += f',{name}'
            
            lines.append(extinf)
            
            stream_id = await self.name_mapper.get_stream_id(name)
            full_url = f"{self.config.public_url.rstrip('/')}/stream/{stream_id}"
            lines.append(full_url)
        
        return '\n'.join(lines)
    
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
    
    def sort_streams_by_availability(self, streams):
        """Sort streams by source availability"""
        def get_source_availability(stream):
            source_id = stream.source_id
            return self.connection_manager.source_limits.get(source_id, 5) - \
                   self.connection_manager.source_connections.get(source_id, 0)
        
        indexed_streams = [(i, stream) for i, stream in enumerate(streams)]
        indexed_streams.sort(key=lambda x: (-get_source_availability(x[1]), x[0]))
        return [stream for _, stream in indexed_streams]
    
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
        