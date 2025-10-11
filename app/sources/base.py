#!/usr/bin/env python3
"""
Base Stream Source Module

This module defines the abstract base class for all stream sources.
It provides common functionality for refresh timing and stream management.

@package KPTV Restreamer
@author Kevin Pirnie <me@kpirnie.com>
@copyright Copyright (c) 2025
"""

# setup the imports
import asyncio, logging, aiohttp
from datetime import datetime
from typing import Dict, List
from app.models import StreamInfo, SourceConfig

# setup the logger
logger = logging.getLogger(__name__)

"""
Base class for stream sources

Provides common functionality for source management, refresh logic, and stream storage.
"""
class StreamSource:
   
    """
    Initialize the StreamSource
    Sets up source configuration, HTTP session, and stream storage.

    @param config: SourceConfig Source configuration object
    @param session: aiohttp.ClientSession HTTP session for requests
    """
    def __init__(self, config: SourceConfig, session: aiohttp.ClientSession, connection_manager=None):

        # setup the internals
        self.config = config
        self.session = session
        self.connection_manager = connection_manager
        self.streams: Dict[str, StreamInfo] = {}
        self.last_refresh = None
        self._refresh_lock = asyncio.Lock()
    
    """
    Check if source needs refreshing
    Determines if enough time has elapsed since last refresh based on refresh interval.

    @return bool: True if refresh is needed, False otherwise
    """
    async def should_refresh(self) -> bool:
        
        # if we have not refreshed yet, return true
        if self.last_refresh is None:
            return True
        
        # check the last refresh time and return the comparison
        elapsed = datetime.now() - self.last_refresh
        return elapsed.total_seconds() >= self.config.refresh_interval
    
    """
    Refresh stream list from source
    Fetches latest streams if refresh interval has elapsed, updates internal storage.

    @return bool: True if refresh successful, False on error
    """
    async def refresh_streams(self) -> bool:
        
        # do we have a look
        async with self._refresh_lock:
            if not await self.should_refresh():
                return True
            
            # Acquire connection for API/playlist fetch
            if self.connection_manager:
                
                # try to acquire a connection
                acquired = await self.connection_manager.acquire_connection(self.config.name)
                
                # if we don't have one, we've reached the limit... log it and return false
                if not acquired:
                    logger.warning(f"Cannot refresh {self.config.name}: connection limit reached")
                    return False
            
            # try to fetch the streams
            try:

                # hold the streams
                streams = await self._fetch_streams()
                self.streams = {s.name: s for s in streams}
                self.last_refresh = datetime.now()
                
                # log it and return true
                logger.info(f"Refreshed {len(self.streams)} streams from {self.config.name}")
                return True
            
            # whoops... there was an exception, and return false
            except Exception as e:
                logger.error(f"Failed to refresh streams from {self.config.name}: {e}")
                return False
            
            # when all is said and done...
            finally:

                # Release connection after fetch
                if self.connection_manager:
                    await self.connection_manager.release_connection(self.config.name)
    
    """
    Fetch streams from source (implemented by subclasses)
    Abstract method to be implemented by concrete source types.

    @return list: List of StreamInfo objects
    @throws NotImplementedError: Must be implemented by subclasses
    """
    async def _fetch_streams(self) -> List[StreamInfo]:
        """Fetch streams from source (implemented by subclasses)"""
        raise NotImplementedError