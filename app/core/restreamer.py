#!/usr/bin/env python3
"""
Stream Restreamer Core Module

This module contains the main StreamRestreamer class that orchestrates the entire
restreaming application. It manages sources, connections, caching, and stream delivery.

@package KPTV Restreamer
@author Kevin Pirnie <me@kpirnie.com>
@copyright Copyright (c) 2025
"""

# setup the imports
import asyncio, logging, aiohttp
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

# setup the logger
logger = logging.getLogger(__name__)

"""
Main application orchestrator class

Coordinates all components of the restreaming system including sources,
connection management, caching, filtering, and stream delivery.
"""
class StreamRestreamer:
    """Main application class"""
    
    """
    Initialize the StreamRestreamer
    Sets up all core components and prepares the application for operation.

    @param config: AppConfig Application configuration object
    """
    def __init__(self, config: AppConfig):

        # hold our class options
        self.config = config
        self.session = None
        self.connection_manager = ConnectionManager(config.max_total_connections)
        self.stream_filter = StreamFilter(config.filters)
        self.aggregator = StreamAggregator(self.stream_filter)
        self.name_mapper = StreamNameMapper()
        self.refresh_task = None
        self.stream_cache = None
        self.stream_service = None
    
    """
    Initialize the application
    Creates HTTP session, initializes stream cache, sets up sources, and starts
    the background refresh task.

    @return None
    """
    async def initialize(self):
        
        # setup the client timeout
        timeout = aiohttp.ClientTimeout(
            total=None,
            connect=30,
            sock_read=300
        )

        # setup out TCP connector and its option
        connector = aiohttp.TCPConnector(
            limit=100, 
            limit_per_host=20,
            keepalive_timeout=300,
            enable_cleanup_closed=True
        )

        # setup the session
        self.session = aiohttp.ClientSession(timeout=timeout, connector=connector)
        
        # setup the stream cache and start it up
        self.stream_cache = StreamCache(self.session, self.connection_manager)
        self.stream_cache.start()
        
        # setup the stream service
        self.stream_service = StreamService(
            self.config,
            self.session,
            self.connection_manager,
            self.stream_cache,
            self.name_mapper,
            self.aggregator
        )
        
        # loop over the sources
        for source_config in self.config.sources:
            
            # setup the connection manager
            self.connection_manager.set_source_limit(
                source_config.name, source_config.max_connections)
            
            # if we are configured for xtreme, fire up the source for it
            if source_config.type == 'xtream':
                source = XtreamSource(source_config, self.session, self.connection_manager)

            # if we are configured for m3u, fire up the source for it
            elif source_config.type == 'm3u':
                source = M3USource(source_config, self.session, self.connection_manager)
            
            # oof... we have an invalid source
            else:
                logger.warning(f"Unknown source type: {source_config.type}")
                continue
            
            # aggregate our sources
            self.aggregator.add_source(source)
        
        # create the async task refresher loop
        self.refresh_task = asyncio.create_task(self._refresh_loop())
        await self.aggregator.refresh_all_sources()
 
    """
    Cleanup resources
    Stops stream cache, cancels background tasks, and closes HTTP session.

    @return None
    """
    async def cleanup(self):
        
        # if we have a stream cache, kill it when we can
        if self.stream_cache:
            await self.stream_cache.stop()
        
        # if this is a refresher task
        if self.refresh_task:

            # cancel it
            self.refresh_task.cancel()
            
            # try to fire it back up, and ignore the cancellation errors
            try:
                await self.refresh_task
            except asyncio.CancelledError:
                pass
        
        # if we have a session... close it
        if self.session:
            await self.session.close()
    
    """
    Background task to refresh sources
    Continuously refreshes stream sources at 60-second intervals.

    @return None
    """
    async def _refresh_loop(self):
        
        # while we're still looping...
        while True:

            # try to refresh after 60 seconds
            try:
                await asyncio.sleep(60)
                await self.aggregator.refresh_all_sources()

            # whoops, we are in a cancelation...
            except asyncio.CancelledError:
                break

            # whoopsie... there's an error in the loop
            except Exception as e:
                logger.error(f"Error in refresh loop: {e}")
    
    """
    Generate M3U8 playlist
    Creates unified M3U8 playlist from all available streams.

    @return str: M3U8 playlist content
    """
    async def get_m3u8_playlist(self) -> str:
        
        # generate and return the m3u8 playlist
        return await self.stream_service.get_m3u8_playlist()
    
    """
    Stream content
    Delivers stream content for the specified stream ID.

    @param stream_id: str Stream identifier
    @return StreamingResponse: Stream content response
    """
    async def stream_content(self, stream_id: str):
        
        # stream the content
        return await self.stream_service.stream_content(stream_id)
    