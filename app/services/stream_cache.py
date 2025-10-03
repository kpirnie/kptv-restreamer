import asyncio
import time
import logging
from typing import Dict, Set, Optional, AsyncGenerator
from collections import deque
import aiohttp

logger = logging.getLogger(__name__)


class StreamBuffer:
    """Buffers stream data for multiple consumers"""
    
    def __init__(self, max_buffer_size: int = 1000):
        self.buffer = deque(maxlen=max_buffer_size)
        self.consumers: Set[int] = set()
        self.lock = asyncio.Lock()
        self.new_data_event = asyncio.Event()
        self.buffer_position = 0
        self.is_active = True
        
    async def add_chunk(self, chunk: bytes):
        """Add a chunk to the buffer"""
        async with self.lock:
            self.buffer.append((self.buffer_position, chunk))
            self.buffer_position += 1
            self.new_data_event.set()
    
    async def end_stream(self):
        """Mark stream as ended"""
        async with self.lock:
            self.is_active = False
            self.new_data_event.set()
    
    def register_consumer(self, consumer_id: int):
        """Register a new consumer"""
        self.consumers.add(consumer_id)
    
    def unregister_consumer(self, consumer_id: int):
        """Unregister a consumer"""
        self.consumers.discard(consumer_id)
    
    def has_consumers(self) -> bool:
        """Check if there are any active consumers"""
        return len(self.consumers) > 0
    
    async def consume_from(self, consumer_id: int, start_position: int = 0) -> AsyncGenerator[bytes, None]:
        """Consume stream data from a specific position"""
        self.register_consumer(consumer_id)
        current_position = start_position
        
        try:
            while True:
                chunks_to_yield = []
                
                async with self.lock:
                    for pos, chunk in self.buffer:
                        if pos >= current_position:
                            chunks_to_yield.append((pos, chunk))
                    
                    if chunks_to_yield:
                        current_position = chunks_to_yield[-1][0] + 1
                    
                    if not self.is_active and not chunks_to_yield:
                        break
                
                for _, chunk in chunks_to_yield:
                    yield chunk
                
                if not chunks_to_yield:
                    self.new_data_event.clear()
                    try:
                        await asyncio.wait_for(self.new_data_event.wait(), timeout=30)
                    except asyncio.TimeoutError:
                        if not self.is_active:
                            break
        
        finally:
            self.unregister_consumer(consumer_id)


class CachedStream:
    """Represents a cached stream with a single source connection"""
    
    def __init__(self, stream_name: str, stream_url: str, source_id: str):
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
    
    def get_next_consumer_id(self) -> int:
        """Get unique consumer ID"""
        consumer_id = self._next_consumer_id
        self._next_consumer_id += 1
        return consumer_id
    
    def touch(self):
        """Update last access time"""
        self.last_access = time.time()
    
    def has_consumers(self) -> bool:
        """Check if stream has active consumers"""
        return self.buffer.has_consumers()
    
    def is_stale(self, timeout: int = 60) -> bool:
        """Check if stream is stale (no consumers and timeout expired)"""
        if self.has_consumers():
            return False
        return (time.time() - self.last_access) > timeout


class StreamCache:
    """Manages cached streams to ensure 1 connection per stream to providers"""
    
    def __init__(self, session: aiohttp.ClientSession, connection_manager):
        self.session = session
        self.connection_manager = connection_manager
        self.active_streams: Dict[str, CachedStream] = {}
        self._lock = asyncio.Lock()
        self._cleanup_task: Optional[asyncio.Task] = None
    
    def start(self):
        """Start the cache cleanup task"""
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())
    
    async def stop(self):
        """Stop the cache and cleanup"""
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
        
        async with self._lock:
            for cached_stream in list(self.active_streams.values()):
                await self._close_stream(cached_stream)
            self.active_streams.clear()
    
    async def _cleanup_loop(self):
        """Periodically clean up stale streams"""
        while True:
            try:
                await asyncio.sleep(10)
                await self._cleanup_stale_streams()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in cleanup loop: {e}")
    
    async def _cleanup_stale_streams(self):
        """Remove streams that have no consumers and are stale"""
        async with self._lock:
            stale_keys = []
            for key, cached_stream in self.active_streams.items():
                if cached_stream.is_stale():
                    stale_keys.append(key)
            
            for key in stale_keys:
                cached_stream = self.active_streams[key]
                logger.info(f"Cleaning up stale stream: {cached_stream.stream_name}")
                await self._close_stream(cached_stream)
                del self.active_streams[key]
    
    async def _close_stream(self, cached_stream: CachedStream):
        """Close a cached stream and release resources"""
        if cached_stream.source_task and not cached_stream.source_task.done():
            cached_stream.source_task.cancel()
            try:
                await cached_stream.source_task
            except asyncio.CancelledError:
                pass
        
        await cached_stream.buffer.end_stream()
        await self.connection_manager.release_connection(cached_stream.source_id)
    
    def _get_cache_key(self, stream_name: str, stream_url: str) -> str:
        """Generate cache key for a stream - key by name only"""
        return stream_name
    
    async def get_or_create_stream(
        self, 
        stream_name: str, 
        stream_url: str, 
        source_id: str,
        media_type: str
    ) -> CachedStream:
        """Get existing cached stream or create new one"""
        cache_key = self._get_cache_key(stream_name, stream_url)
        
        async with self._lock:
            if cache_key in self.active_streams:
                cached_stream = self.active_streams[cache_key]
                if cached_stream.is_active and not cached_stream.connection_error:
                    cached_stream.touch()
                    logger.info(f"Reusing cached stream for '{stream_name}' from {cached_stream.source_id} (requested {source_id})")
                    return cached_stream
                else:
                    logger.warning(f"Removing failed cached stream for '{stream_name}'")
                    await self._close_stream(cached_stream)
                    del self.active_streams[cache_key]
            
            logger.info(f"Creating new cached stream for '{stream_name}' from {source_id}")
            cached_stream = CachedStream(stream_name, stream_url, source_id)
            
            connection_acquired = await self.connection_manager.acquire_connection(source_id)
            if not connection_acquired:
                raise Exception(f"Failed to acquire connection for source {source_id}")
            
            cached_stream.source_task = asyncio.create_task(
                self._stream_from_source(cached_stream)
            )
            
            self.active_streams[cache_key] = cached_stream
            return cached_stream
    
    async def _stream_from_source(self, cached_stream: CachedStream):
        """Stream data from source into buffer"""
        source_url = cached_stream.stream_url
        source_id = cached_stream.source_id
        
        try:
            logger.info(f"Opening source connection: {source_id} -> {source_url}")
            
            async with self.session.get(
                source_url,
                allow_redirects=True,
                timeout=aiohttp.ClientTimeout(connect=15, sock_read=30)
            ) as resp:
                if resp.status != 200:
                    raise Exception(f"HTTP {resp.status} from source")
                
                chunk_count = 0
                async for chunk in resp.content.iter_chunked(8192):
                    if not chunk:
                        break
                    
                    await cached_stream.buffer.add_chunk(chunk)
                    chunk_count += 1
                    
                    if chunk_count % 1000 == 0:
                        logger.debug(f"Cached {chunk_count} chunks from {source_id} for '{cached_stream.stream_name}'")
                    
                    if not cached_stream.buffer.has_consumers() and chunk_count > 100:
                        logger.info(f"No consumers for '{cached_stream.stream_name}', stopping source stream")
                        break
                
                logger.info(f"Source stream ended for '{cached_stream.stream_name}' after {chunk_count} chunks")
        
        except asyncio.CancelledError:
            logger.info(f"Source stream cancelled for '{cached_stream.stream_name}'")
            raise
        
        except Exception as e:
            logger.error(f"Error streaming from source {source_id}: {e}")
            cached_stream.connection_error = str(e)
        
        finally:
            await cached_stream.buffer.end_stream()
            cached_stream.is_active = False
            await self.connection_manager.release_connection(source_id)
            logger.info(f"Released connection for {source_id}")