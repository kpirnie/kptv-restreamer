#!/usr/bin/env python3
"""
Stream Aggregator Module

This module aggregates and groups streams from multiple sources into unified channels.
It handles source management, stream filtering, and grouping by stream name.

@package KPTV Restreamer
@author Kevin Pirnie <me@kpirnie.com>
@copyright Copyright (c) 2025
"""

# fire up the imports
import asyncio, logging
from typing import Dict, List
from app.models import StreamInfo
from app.services.stream_filter import StreamFilter

# setup the logger
logger = logging.getLogger(__name__)

"""
Aggregates and groups streams from multiple sources

Combines streams from different sources under unified names for failover support.
"""
class StreamAggregator:

    """
    Initialize the StreamAggregator
    Sets up source tracking, filtering, and grouped stream storage.

    @param stream_filter: StreamFilter Filter instance for stream inclusion/exclusion
    """
    def __init__(self, stream_filter: StreamFilter):

        # setup the internals
        self.sources: Dict[str, any] = {}
        self.filter = stream_filter
        self.grouped_streams: Dict[str, List[StreamInfo]] = {}
        self._lock = asyncio.Lock()

    """
    Add a stream source
    Registers a new source to be aggregated.

    @param source: StreamSource Source instance to add
    @return None
    """
    def add_source(self, source):
        
        # hold the sources
        self.sources[source.config.name] = source
    
    """
    Refresh all sources and rebuild grouped streams
    Fetches latest stream data from all enabled sources and regroups them.

    @return None
    """
    async def refresh_all_sources(self):
        
        # setup the tasks to refresh the source
        tasks = []

        # loop over each source
        for source in self.sources.values():

            # of the source is marked enable append it to the source
            if source.config.enabled:
                tasks.append(source.refresh_streams())
        
        # gather up all tasks if there are any
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

        # now rebould the grouping
        await self._rebuild_grouped_streams()
    
    """
    Rebuild grouped streams from all sources
    Aggregates streams by name from all enabled sources, applying filters.

    @return None
    """
    async def _rebuild_grouped_streams(self):
        
        # make sure we have a lock
        async with self._lock:

            # clear the initial groupings
            self.grouped_streams.clear()
            
            # for each source we have
            for source in self.sources.values():

                # make sure it's actually enabled
                if not source.config.enabled:
                    continue
                
                # loop the streams in each source
                for stream in source.streams.values():

                    # check if it needs to be filtered
                    if self.filter.should_include_stream(stream):

                        # hold the stream name
                        name = stream.name

                        # now group create the new stream grouping if it's not already in the groups
                        if name not in self.grouped_streams:
                            self.grouped_streams[name] = []

                        # append the stream to the group
                        self.grouped_streams[name].append(stream)
            
            # logging
            logger.info(f"Grouped {len(self.grouped_streams)} unique streams")
    
    """
    Get current grouped streams
    Returns a copy of the current stream groupings.

    @return dict: Dictionary mapping stream names to lists of StreamInfo objects
    """
    def get_grouped_streams(self) -> Dict[str, List[StreamInfo]]:

        # return the dict mapped groupings
        return self.grouped_streams.copy()