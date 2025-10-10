import asyncio
import logging

import aiohttp

from app.models import AppConfig
from app.services import (
    ConnectionManager,
    StreamCache,
    StreamNameMapper,
    StreamFilter,
    StreamAggregator,
    StreamService
)
from app.sources import XtreamSource, M3USource

logger = logging.getLogger(__name__)


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
        self.stream_cache = None
        self.stream_service = None
    
    async def initialize(self):
        """Initialize the application"""
        timeout = aiohttp.ClientTimeout(
            total=None,
            connect=30,
            sock_read=300
        )
        connector = aiohttp.TCPConnector(
            limit=100, 
            limit_per_host=20,
            keepalive_timeout=300,
            enable_cleanup_closed=True
        )
        self.session = aiohttp.ClientSession(timeout=timeout, connector=connector)
        
        self.stream_cache = StreamCache(self.session, self.connection_manager)
        self.stream_cache.start()
        
        self.stream_service = StreamService(
            self.config,
            self.session,
            self.connection_manager,
            self.stream_cache,
            self.name_mapper,
            self.aggregator
        )
        
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
        
        self.refresh_task = asyncio.create_task(self._refresh_loop())
        await self.aggregator.refresh_all_sources()
 
    async def cleanup(self):
        """Cleanup resources"""
        if self.stream_cache:
            await self.stream_cache.stop()
        
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
                await asyncio.sleep(60)
                await self.aggregator.refresh_all_sources()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in refresh loop: {e}")
    
    async def get_m3u8_playlist(self) -> str:
        """Generate M3U8 playlist"""
        return await self.stream_service.get_m3u8_playlist()
    
    async def stream_content(self, stream_id: str):
        """Stream content"""
        return await self.stream_service.stream_content(stream_id)