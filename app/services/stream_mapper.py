#!/usr/bin/env python3
"""
Stream Name Mapper Module

This module handles stream name encoding and decoding for URL safety.
It generates URL-safe identifiers from stream names and maintains bidirectional mappings.

@package KPTV Restreamer
@author Kevin Pirnie <me@kpirnie.com>
@copyright Copyright (c) 2025
"""

# setup the imports
import asyncio, re

"""
Handles stream name encoding/decoding for URL safety

Converts stream names to URL-safe alphanumeric identifiers and maintains mappings.
"""
class StreamNameMapper:
    
    """
    Initialize the StreamNameMapper
    Sets up bidirectional mapping dictionaries and async lock.

    @return None
    """
    def __init__(self):

        # setup the internals
        self.name_to_id = {}
        self.id_to_name = {}
        self._lock = asyncio.Lock()
    
    """
    Generate a URL-safe ID from stream name - alphanumeric only
    Strips non-alphanumeric characters to create clean URL identifiers.

    @param name: str Original stream name
    @return str: URL-safe identifier
    """
    def _generate_safe_id(self, name: str) -> str:
        
        # clean the name of all non alpha-numeric characters
        clean_id = re.sub(r'[^a-zA-Z0-9]', '', name)
        
        # if we still dont have a cleaned id
        if not clean_id:
            clean_id = "unknownstream"
        
        # return it
        return clean_id
    
    """
    Get URL-safe ID for stream name
    Returns existing ID or generates new unique ID for the stream name.

    @param name: str Stream name to map
    @return str: URL-safe stream identifier
    """
    async def get_stream_id(self, name: str) -> str:
        
        # if we have a lock
        async with self._lock:

            # if the name is not in id
            if name not in self.name_to_id:

                # try to generate a new one
                stream_id = self._generate_safe_id(name)

                # hold the base id and setup the counter                
                base_id = stream_id
                counter = 1

                # while we have a stream id in the id's to be named...
                while stream_id in self.id_to_name:

                    # set it and the counter
                    stream_id = f"{base_id}{counter}"
                    counter += 1
                
                # hold the streams id and it's name
                self.name_to_id[name] = stream_id
                self.id_to_name[stream_id] = name
            
            # return it
            return self.name_to_id[name]
    
    """
    Get original stream name from URL-safe ID
    Looks up the original stream name from the identifier.

    @param stream_id: str URL-safe stream identifier
    @return str: Original stream name or empty string if not found
    """
    async def get_stream_name(self, stream_id: str) -> str:
        
        # are we locked
        async with self._lock:

            # return the stream name from the id
            return self.id_to_name.get(stream_id, "")
    
    """
    Get all current mappings for debugging
    Returns copies of all mapping dictionaries and statistics.

    @return dict: Mapping information including counts and all mappings
    """
    async def get_all_mappings(self) -> dict:
        
        # are we locked
        async with self._lock:

            # return the stream/name/id mapping
            return {
                "name_to_id": self.name_to_id.copy(),
                "id_to_name": self.id_to_name.copy(),
                "total_streams": len(self.name_to_id),
                "total_unique_ids": len(self.id_to_name)
            }