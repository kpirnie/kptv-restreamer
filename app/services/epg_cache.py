#!/usr/bin/env python3
"""
EPG Cache Service Module

This module provides caching for EPG (Electronic Program Guide) data
with configurable TTL and memory-conscious storage.

@package KPTV Restreamer
@author Kevin Pirnie <me@kpirnie.com>
@copyright Copyright (c) 2025
"""

# setup the imports
import asyncio, logging, time
import xml.etree.ElementTree as ET
from typing import Optional, List

# setup the logger
logger = logging.getLogger(__name__)

"""
Caches EPG data with TTL support

Stores fetched EPG XML in memory with automatic expiration
to reduce upstream provider requests.
"""
class EPGCache:

    """
    Initialize the EPGCache

    @param session: aiohttp.ClientSession HTTP session for fetching EPG data
    @param ttl_seconds: int Cache time-to-live in seconds (default 14400 = 4 hours)
    """
    def __init__(self, session, ttl_seconds: int = 14400):

        # setup the internals
        self.session = session
        self.ttl_seconds = ttl_seconds
        self._cached_data: Optional[str] = None
        self._cached_at: float = 0
        self._lock = asyncio.Lock()
        self._epg_sources: list = []

    """
    Set the EPG source URLs

    @param sources: list List of EPG URLs to fetch from
    @return None
    """
    def set_sources(self, sources: list):

        # hold the sources
        self._epg_sources = sources

    """
    Check if the cache is still valid

    @return bool: True if cached data exists and TTL has not expired
    """
    def is_valid(self) -> bool:

        # check if we have data and it's within the TTL
        if self._cached_data is None:
            return False

        return (time.time() - self._cached_at) < self.ttl_seconds

    """
    Get EPG data, fetching from source if cache is expired

    @return str: XMLTV formatted EPG data
    """
    async def get_epg_data(self) -> str:

        # if the cache is still valid, return it
        if self.is_valid():
            return self._cached_data

        # otherwise fetch and cache
        async with self._lock:

            # double-check after acquiring lock
            if self.is_valid():
                return self._cached_data

            # fetch fresh data
            data = await self._fetch_epg()
            self._cached_data = data
            self._cached_at = time.time()

            return self._cached_data

    """
    Warm the cache by fetching EPG data immediately

    @return None
    """
    async def warm(self):

        # force a fetch regardless of cache state
        async with self._lock:

            logger.info("Warming EPG cache...")
            data = await self._fetch_epg()
            self._cached_data = data
            self._cached_at = time.time()
            logger.info(f"EPG cache warmed ({len(data)} bytes)")

    """
    Invalidate the cache

    @return None
    """
    async def invalidate(self):

        async with self._lock:
            self._cached_data = None
            self._cached_at = 0

    """
    Fetch EPG data from configured sources

    @return str: XMLTV formatted EPG data
    """
    async def _fetch_epg(self) -> str:

        # if we have no sources, return empty
        if not self._epg_sources:
            return '<?xml version="1.0" encoding="UTF-8"?><tv></tv>'

        # fetch from all sources concurrently
        results = await self._fetch_all_sources()

        # if we only got one, return it directly
        if len(results) == 1:
            return results[0]

        # if we got multiple, merge them
        if len(results) > 1:
            return self._merge_xmltv(results)

        # all sources failed
        return '<?xml version="1.0" encoding="UTF-8"?><tv></tv>'

    """
    Fetch EPG data from all configured sources concurrently

    @return list: List of raw XMLTV strings that were successfully fetched
    """
    async def _fetch_all_sources(self) -> List[str]:

        # hold the results
        results = []

        # fetch all sources concurrently
        tasks = [self._fetch_single_source(url) for url in self._epg_sources]
        fetched = await asyncio.gather(*tasks, return_exceptions=True)

        # collect successful results
        for i, result in enumerate(fetched):
            if isinstance(result, str) and result:
                results.append(result)
            elif isinstance(result, Exception):
                logger.error(f"Failed to fetch EPG from {self._epg_sources[i]}: {result}")

        return results

    """
    Fetch EPG data from a single source

    @param source_url: str URL to fetch EPG data from
    @return str: Raw XMLTV string or empty string on failure
    """
    async def _fetch_single_source(self, source_url: str) -> str:

        try:
            async with self.session.get(source_url) as resp:
                if resp.status == 200:
                    data = await resp.text()
                    logger.info(f"Fetched EPG data from {source_url} ({len(data)} bytes)")
                    return data

        except Exception as e:
            logger.error(f"Failed to fetch EPG from {source_url}: {e}")

        return ""

    """
    Merge multiple XMLTV documents into one

    Combines channel and programme elements from all sources,
    deduplicating channels by ID.

    @param xmltv_docs: list List of XMLTV XML strings
    @return str: Merged XMLTV XML string
    """
    def _merge_xmltv(self, xmltv_docs: List[str]) -> str:

        # track seen channel IDs to deduplicate
        seen_channels = set()
        merged_channels = []
        merged_programmes = []

        for doc in xmltv_docs:

            try:
                root = ET.fromstring(doc)

                # collect channels, dedup by id
                for channel in root.findall('channel'):
                    channel_id = channel.get('id', '')
                    if channel_id and channel_id not in seen_channels:
                        seen_channels.add(channel_id)
                        merged_channels.append(channel)

                # collect all programmes
                for programme in root.findall('programme'):
                    merged_programmes.append(programme)

            except ET.ParseError as e:
                logger.error(f"Failed to parse XMLTV document for merge: {e}")
                continue

        # build merged document
        merged_root = ET.Element('tv')

        for channel in merged_channels:
            merged_root.append(channel)

        for programme in merged_programmes:
            merged_root.append(programme)

        logger.info(f"Merged EPG: {len(merged_channels)} channels, {len(merged_programmes)} programmes from {len(xmltv_docs)} sources")

        return '<?xml version="1.0" encoding="UTF-8"?>' + ET.tostring(merged_root, encoding='unicode')