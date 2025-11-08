#!/usr/bin/env python3
"""
Stream Cache Module

This module manages stream caching to ensure only one connection per stream to providers.
It buffers stream data and distributes it to multiple consumers efficiently.

@package KPTV Restreamer
@author Kevin Pirnie <me@kpirnie.com>
@copyright Copyright (c) 2025
"""

# setup the imports
import asyncio, time, logging, aiohttp
from typing import Dict, Set, Optional, AsyncGenerator
from collections import deque

# setup the logger
logger = logging.getLogger(__name__)

"""
Buffers stream data for multiple consumers

Maintains a circular buffer of stream chunks and manages consumer subscriptions.
"""
class StreamBuffer:
    
    """
    Initialize the StreamBuffer
    Sets up buffer storage and consumer tracking.

    @param max_buffer_size: int Maximum number of chunks to buffer (default 1000)
    """
    def __init__(self, max_buffer_size: int = 1000):

        # setup the internals
        self.buffer = deque(maxlen=max_buffer_size)
        self.consumers: Set[int] = set()
        self.lock = asyncio.Lock()
        self.new_data_event = asyncio.Event()
        self.buffer_position = 0
        self.is_active = True

    """ 
    Add a chunk to the buffer
    Appends a data chunk and notifies waiting consumers.

    @param chunk: bytes Stream data chunk to buffer
    @return None
    """
    async def add_chunk(self, chunk: bytes):
        
        # make sure we have a lock
        async with self.lock:

            # append the chunk to the bffer, set the buffer position and mark the event
            self.buffer.append((self.buffer_position, chunk))
            self.buffer_position += 1
            self.new_data_event.set()
    
    """
    Mark stream as ended
    Signals that no more data will be added to the buffer.

    @return None
    """
    async def end_stream(self):
        
        # check the lock
        async with self.lock:

            # end the stream and mark the event
            self.is_active = False
            self.new_data_event.set()
    
    """
    Register a new consumer
    Adds a consumer to the active consumer set.

    @param consumer_id: int Unique consumer identifier
    @return None
    """
    def register_consumer(self, consumer_id: int):
        
        # register a new consumer/client
        self.consumers.add(consumer_id)
    
    """
    Unregister a consumer
    Removes a consumer from the active consumer set.

    @param consumer_id: int Consumer identifier to remove
    @return None
    """
    def unregister_consumer(self, consumer_id: int):
        
        # register the consumer/client
        self.consumers.discard(consumer_id)
    
    """
    Check if there are any active consumers
    Returns whether the buffer has any registered consumers.

    @return bool: True if consumers exist, False otherwise
    """
    def has_consumers(self) -> bool:

        # see if we have any consumers/clients
        return len(self.consumers) > 0
    
    """
    Consume stream data from a specific position
    Yields buffered chunks starting from the specified position for a consumer.

    @param consumer_id: int Unique consumer identifier
    @param start_position: int Buffer position to start from (default 0)
    @return AsyncGenerator: Yields stream data chunks
    """
    async def consume_from(self, consumer_id: int, start_position: int = 0) -> AsyncGenerator[bytes, None]:
        
        # register the consumer/client
        self.register_consumer(consumer_id)

        # setup the current consumer/client position
        current_position = start_position
        
        # tru to consume the stream from a specific position
        try:

            # while we're looping...
            while True:

                # setup the chunks to hold
                chunks_to_yield = []
                
                # make sure we have a lock
                async with self.lock:

                    # for each chunk position in the buffer, append a new chunk to it
                    for pos, chunk in self.buffer:
                        if pos >= current_position:
                            chunks_to_yield.append((pos, chunk))
                    
                    # make sure we have a chunk to be utilized...
                    if chunks_to_yield:
                        current_position = chunks_to_yield[-1][0] + 1
                    
                    # is we're not active and have no chunks
                    if not self.is_active and not chunks_to_yield:
                        break
                
                # return each chunk if we have it
                for _, chunk in chunks_to_yield:
                    yield chunk
                
                # if we don't have anymore
                if not chunks_to_yield:

                    # clear the event
                    self.new_data_event.clear()

                    # give it a little bit if we're active still
                    try:
                        await asyncio.wait_for(self.new_data_event.wait(), timeout=30)

                    # timeout!
                    except asyncio.TimeoutError:
                        if not self.is_active:
                            break

        # end the chunking and dump the consumer/client
        finally:
            self.unregister_consumer(consumer_id)

"""
Represents a cached stream with a single source connection

Manages one upstream connection and distributes data to multiple consumers.
"""
class CachedStream:

    """
    Initialize the CachedStream

    Sets up stream metadata, buffer, and tracking structures.

    @param stream_name: str Name of the stream
    @param stream_url: str Source URL for the stream
    @param source_id: str Source identifier
    """    
    def __init__(self, stream_name: str, stream_url: str, source_id: str):

        # setup the internals
        self.stream_name = stream_name
        self.stream_url = stream_url
        self.source_id = source_id
        self.buffer = StreamBuffer()
        self.source_task: Optional[asyncio.Task] = None
        self.last_access = time.time()
        self.connection_error = None
        self.is_active = True
        self._next_consumer_id = 0
        self._lock = asyncio.Lock()
    
    """
    Get unique consumer ID
    Generates and returns a unique identifier for a new consumer.

    @return int: Unique consumer identifier
    """
    def get_next_consumer_id(self) -> int:
        
        # setup the next consumer/client id
        consumer_id = self._next_consumer_id
        self._next_consumer_id += 1

        # return it
        return consumer_id
    
    """
    Update last access time
    Records current time as last access time for staleness tracking.

    @return None
    """
    def touch(self):
        
        # update the last accessed time
        self.last_access = time.time()
    
    """
    Check if stream has active consumers
    Returns whether any consumers are currently reading from this stream.

    @return bool: True if consumers exist, False otherwise
    """
    def has_consumers(self) -> bool:

        # do we have consumers/clients?
        return self.buffer.has_consumers()
    
    """
    Check if stream is stale (no consumers and timeout expired)
    Determines if stream should be cleaned up based on inactivity.

    @param timeout: int Seconds of inactivity before stream is stale (default 60)
    @return bool: True if stale, False otherwise
    """
    def is_stale(self, timeout: int = 60) -> bool:
        
        # does the stream have any consumers/clients
        if self.has_consumers():
            return False
        
        # return if we've hit the timeout
        return (time.time() - self.last_access) > timeout

    """
    Attempt to reconnect to a different source
    
    @param session: aiohttp.ClientSession HTTP session
    @param connection_manager: ConnectionManager Connection manager instance
    @param new_stream_url: str New stream URL to connect to
    @param new_source_id: str New source identifier
    @return bool: True if reconnection successful
    """
    async def attempt_reconnect(self, stream_cache_instance, new_stream_url: str, new_source_id: str):
        
        logger.info(f"Attempting reconnect for '{self.stream_name}' from {self.source_id} to {new_source_id}")
        
        # Cancel existing source task
        if self.source_task and not self.source_task.done():
            self.source_task.cancel()
            try:
                await self.source_task
            except asyncio.CancelledError:
                pass
        
        # Release old connection
        await stream_cache_instance.connection_manager.release_connection(self.source_id)
        
        # Update to new source
        self.stream_url = new_stream_url
        self.source_id = new_source_id
        self.connection_error = None
        self.is_active = True
        
        # Acquire new connection
        connection_acquired = await stream_cache_instance.connection_manager.acquire_connection(new_source_id)
        if not connection_acquired:
            self.connection_error = f"Failed to acquire connection for {new_source_id}"
            self.is_active = False
            return False
        
        # Start new source task
        self.source_task = asyncio.create_task(
            stream_cache_instance._stream_from_source(self)
        )
        
        return True

"""
Manages cached streams to ensure 1 connection per stream to providers

Central cache manager that creates, tracks, and cleans up cached streams.
"""
class StreamCache:
    
    """
    Initialize the StreamCache
    Sets up cache storage and connection manager reference.

    @param session: aiohttp.ClientSession HTTP session for source connections
    @param connection_manager: ConnectionManager Connection limit manager
    """
    def __init__(self, session: aiohttp.ClientSession, connection_manager):

        # hold the internals
        self.session = session
        self.connection_manager = connection_manager
        self.active_streams: Dict[str, CachedStream] = {}
        self._lock = asyncio.Lock()
        self._cleanup_task: Optional[asyncio.Task] = None
    
    """
    Start the cache cleanup task
    Begins background task for removing stale streams.

    @return None
    """
    def start(self):
        
        # hold the internal task to cleanup and start the task
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())
    
    """
    Stop the cache and cleanup
    Cancels cleanup task and closes all active streams.

    @return None
    """
    async def stop(self):
        
        # if we have a task to end/cleanup
        if self._cleanup_task:

            # cancel the task
            self._cleanup_task.cancel()

            # try to fire up the actual cleanuup
            try:
                await self._cleanup_task

            # welp... we've got an error during the cancellation, but just ignore it
            except asyncio.CancelledError:
                pass
        
        # if we have a lock...
        async with self._lock:

            # loop each cached stream
            for cached_stream in list(self.active_streams.values()):

                # close the stream
                await self._close_stream(cached_stream)

            # clear the active cache
            self.active_streams.clear()
    
    """
    Periodically clean up stale streams
    Background loop that removes inactive streams at regular intervals.

    @return None
    """
    async def _cleanup_loop(self):
        
        # while we're looping...
        while True:

            # try to...
            try:

                # sleep a few, then cleanup the stale streams
                await asyncio.sleep(10)
                await self._cleanup_stale_streams()

            # welp... there was a cancellation error, but we can ignote it...
            except asyncio.CancelledError:
                break

            # whoops... log the exception
            except Exception as e:
                logger.error(f"Error in cleanup loop: {e}")
    
    """
    Remove streams that have no consumers and are stale
    Identifies and closes streams that have been inactive beyond timeout.

    @return None
    """
    async def _cleanup_stale_streams(self):
        
        # make sure we have a lock
        async with self._lock:

            # hold the keys for the stale streams
            stale_keys = []

            # for each cached stream
            for key, cached_stream in self.active_streams.items():

                # if it's stale
                if cached_stream.is_stale():

                    # add it to the stale keys
                    stale_keys.append(key)
            
            # for each key
            for key in stale_keys:

                # hold the cached stream and log it
                cached_stream = self.active_streams[key]
                logger.info(f"Cleaning up stale stream: {cached_stream.stream_name}")

                # close the stream and clean up the stale items
                await self._close_stream(cached_stream)
                del self.active_streams[key]
    
    """
    Close a cached stream and release resources
    Cancels source task, ends buffer, and releases connection.

    @param cached_stream: CachedStream Stream to close
    @return None
    """
    async def _close_stream(self, cached_stream: CachedStream):

        # if we have a task
        if cached_stream.source_task and not cached_stream.source_task.done():
            
            # cancel the task
            cached_stream.source_task.cancel()

            # try to end the taks
            try:
                await cached_stream.source_task

            # whoops... skip it
            except asyncio.CancelledError:
                pass
        
        # end the cached stream and release the connection(s)
        await cached_stream.buffer.end_stream()
        await self.connection_manager.release_connection(cached_stream.source_id)
    
    """
    Generate cache key for a stream - key by name only
    Creates unique cache identifier for stream grouping.

    @param stream_name: str Name of the stream
    @param stream_url: str URL of the stream
    @return str: Cache key
    """
    def _get_cache_key(self, stream_name: str, stream_url: str) -> str:
        
        # just return the stream name
        return stream_name
    
    """
    Get existing cached stream or create new one
    Returns cached stream if available, otherwise creates and caches new stream.

    @param stream_name: str Name of the stream
    @param stream_url: str Source URL for the stream
    @param source_id: str Source identifier
    @param media_type: str Media type of the stream
    @return CachedStream: Cached stream instance
    """
    async def get_or_create_stream(
        self, 
        stream_name: str, 
        stream_url: str, 
        source_id: str,
        media_type: str
    ) -> CachedStream:
        
        # hold the cache key
        cache_key = self._get_cache_key(stream_name, stream_url)
        
        # if we have a lock
        async with self._lock:

            # if the cache key is an already active stream
            if cache_key in self.active_streams:
            
                # hold the stream as if it were a cached stream
                cached_stream = self.active_streams[cache_key]

                # if it's active and there's no connection error
                if cached_stream.is_active and not cached_stream.connection_error:

                    # WE GOT IT!  Log it and return it
                    cached_stream.touch()
                    logger.info(f"Reusing cached stream for '{stream_name}' from {cached_stream.source_id} (requested {source_id})")
                    return cached_stream
                
                # otherwise
                else:

                    # log it and remove it from the cache
                    logger.warning(f"Removing failed cached stream for '{stream_name}'")
                    await self._close_stream(cached_stream)
                    del self.active_streams[cache_key]
            
            # log it and create the cached the stream
            logger.info(f"Creating new cached stream for '{stream_name}' from {source_id}")
            cached_stream = CachedStream(stream_name, stream_url, source_id)
            
            # we have a connection acquired
            connection_acquired = await self.connection_manager.acquire_connection(source_id)
            if not connection_acquired:
                raise Exception(f"Failed to acquire connection for source {source_id}")
            
            # fire up a task to stream the stream
            cached_stream.source_task = asyncio.create_task(
                self._stream_from_source(cached_stream)
            )
            
            # set the active stream and return it
            self.active_streams[cache_key] = cached_stream
            return cached_stream
    
    """
    Stream data from source into buffer
    Fetches data from source URL and feeds it to the stream buffer.

    @param cached_stream: CachedStream Stream to populate with source data
    @return None
    """
    async def _stream_from_source(self, cached_stream: CachedStream):
        
        # stream from the source and grab the id
        source_url = cached_stream.stream_url
        source_id = cached_stream.source_id
        
        # try to stream
        try:

            # logging
            logger.info(f"Opening source connection: {source_id} -> {source_url}")
            
            # get the stream with out session
            async with self.session.get(
                source_url,
                allow_redirects=True,
                timeout=aiohttp.ClientTimeout(connect=15, sock_read=30)
            ) as resp:
                
                # if we have something other than a valid response code
                if resp.status not in (200, 206, 304):
                    raise Exception(f"HTTP {resp.status} from source")
                
                # setup the chunkk count
                chunk_count = 0

                # for each chunk in an 32k iteration
                async for chunk in resp.content.iter_chunked(32768):

                    # if we do not have a chunk
                    if not chunk:
                        break
                    
                    # add the chunk to our buffer cache
                    await cached_stream.buffer.add_chunk(chunk)
                    chunk_count += 1
                    
                    # log every 1000 chunks
                    if chunk_count % 1000 == 0:
                        logger.debug(f"Cached {chunk_count} chunks from {source_id} for '{cached_stream.stream_name}'")
                    
                    # if the consumer/client is low chunked, just log it and dump out
                    if not cached_stream.buffer.has_consumers() and chunk_count > 100:
                        logger.info(f"No consumers for '{cached_stream.stream_name}', stopping source stream")
                        break
                
                # log the stream has ended
                logger.info(f"Source stream ended for '{cached_stream.stream_name}' after {chunk_count} chunks")
        
        # the stream is cancelled
        except asyncio.CancelledError:
            logger.info(f"Source stream cancelled for '{cached_stream.stream_name}'")
            raise
        
        # whoops... log the exception and cache the error string
        except Exception as e:
            logger.error(f"Error streaming from source {source_id}: {e}")
            cached_stream.connection_error = str(e)
        
        # last but not least...
        finally:

            # end the srtream, mark it inactive, and release the connection
            await cached_stream.buffer.end_stream()
            cached_stream.is_active = False
            await self.connection_manager.release_connection(source_id)
            logger.info(f"Released connection for {source_id}")
