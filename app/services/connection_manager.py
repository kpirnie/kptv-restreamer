#!/usr/bin/env python3
"""
Connection Manager Module

This module manages connection limits and tracking across all stream sources.
It enforces per-source and global connection limits to prevent overloading providers.

@package KPTV Restreamer
@author Kevin Pirnie <me@kpirnie.com>
@copyright Copyright (c) 2025
"""

# setup the imports
import asyncio
from typing import Dict, Any

"""
Manages connection limits and tracking

Tracks active connections per source and globally, enforcing configured limits.
"""
class ConnectionManager:
    
    """
    Initialize the ConnectionManager
    Sets up connection tracking structures and global limit.

    @param max_total: int Maximum total connections across all sources
    """
    def __init__(self, max_total: int):

        # setup out class variables
        self.max_total = max_total
        self.source_connections: Dict[str, int] = {}
        self.source_limits: Dict[str, int] = {}
        self.api_locks: Dict[str, asyncio.Lock] = {}
        self.total_connections = 0
        self._lock = asyncio.Lock()
    
    """
    Check if a connection can be acquired without actually acquiring it
    Verifies both source-specific and global connection limits.
    Note: For atomic check-and-acquire, use try_acquire_connection() instead.

    @param source_id: str Source identifier to check
    @return bool: True if connection can be acquired, False otherwise
    """
    async def can_acquire_connection(self, source_id: str) -> bool:
        
        # acquire the lock before checking
        async with self._lock:
            return self._can_acquire_unlocked(source_id)
    
    """
    Internal unlocked version of can_acquire check
    Must only be called while holding self._lock.

    @param source_id: str Source identifier to check
    @return bool: True if connection can be acquired, False otherwise
    """
    def _can_acquire_unlocked(self, source_id: str) -> bool:
        
        # setup the current source and limits
        current_source = self.source_connections.get(source_id, 0)
        source_limit = self.source_limits.get(source_id, 5)
        
        # return if we're under those
        return (current_source < source_limit and 
                self.total_connections < self.max_total)

    """
    Atomically check and acquire a connection if available
    This is the preferred method to avoid race conditions between
    checking availability and acquiring the connection.

    @param source_id: str Source identifier requesting connection
    @return bool: True if connection acquired, False if limits reached
    """
    async def try_acquire_connection(self, source_id: str) -> bool:
        
        # if we currently have a lock
        async with self._lock:

            # check if we can acquire before attempting
            if not self._can_acquire_unlocked(source_id):
                return False

            # get the current source connection count
            current_source = self.source_connections.get(source_id, 0)
            
            # increment the connection counts
            self.source_connections[source_id] = current_source + 1
            self.total_connections += 1
            return True

    """
    Get or create an API lock for a source
    
    @param source_id: str Source identifier to check
    @return async lock: The lock necessary for the connections
    """
    def get_api_lock(self, source_id: str) -> asyncio.Lock:
        
        # if the source id is not already locked
        if source_id not in self.api_locks:

            # lock it!
            self.api_locks[source_id] = asyncio.Lock()

        # now return the lock
        return self.api_locks[source_id]

    """
    Attempt to acquire a connection for a source
    Acquires a connection slot if limits allow, updating tracking counters.
    Note: Prefer try_acquire_connection() for atomic check-and-acquire.

    @param source_id: str Source identifier requesting connection
    @return bool: True if connection acquired, False if limits reached
    """
    async def acquire_connection(self, source_id: str) -> bool:
        
        # delegate to try_acquire_connection for atomic operation
        return await self.try_acquire_connection(source_id)
    
    """
    Release a connection for a source
    Decrements connection counters for the specified source and global total.

    @param source_id: str Source identifier releasing connection
    @return None
    """
    async def release_connection(self, source_id: str):
        
        # check if we have a lock
        async with self._lock:

            # if the source is in the connections
            if source_id in self.source_connections:

                # check the number of connections
                self.source_connections[source_id] = max(0, 
                    self.source_connections[source_id] - 1)
                
                # set the total connections
                self.total_connections = max(0, self.total_connections - 1)
    
    """
    Set connection limit for a source
    Configures the maximum allowed connections for a specific source.

    @param source_id: str Source identifier
    @param limit: int Maximum connections for this source
    @return None
    """
    def set_source_limit(self, source_id: str, limit: int):
        
        # hold the 
        self.source_limits[source_id] = limit

    """
    Get detailed connection information
    Returns comprehensive connection statistics and availability.

    @return dict: Connection information including totals, limits, and availability
    """
    async def get_connection_info(self) -> Dict[str, Any]:
        
        # check if we have a lock
        async with self._lock:

            # return the connection info
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