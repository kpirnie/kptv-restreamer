import asyncio
import logging
from typing import Dict, List
from app.models import StreamInfo
from app.services.stream_filter import StreamFilter

logger = logging.getLogger(__name__)


class StreamAggregator:
    """Aggregates and groups streams from multiple sources"""
    
    def __init__(self, stream_filter: StreamFilter):
        self.sources: Dict[str, any] = {}
        self.filter = stream_filter
        self.grouped_streams: Dict[str, List[StreamInfo]] = {}
        self._lock = asyncio.Lock()
    
    def add_source(self, source):
        """Add a stream source"""
        self.sources[source.config.name] = source
    
    async def refresh_all_sources(self):
        """Refresh all sources and rebuild grouped streams"""
        tasks = []
        for source in self.sources.values():
            if source.config.enabled:
                tasks.append(source.refresh_streams())
        
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        await self._rebuild_grouped_streams()
    
    async def _rebuild_grouped_streams(self):
        """Rebuild grouped streams from all sources"""
        async with self._lock:
            self.grouped_streams.clear()
            
            for source in self.sources.values():
                if not source.config.enabled:
                    continue
                
                for stream in source.streams.values():
                    if self.filter.should_include_stream(stream):
                        name = stream.name
                        if name not in self.grouped_streams:
                            self.grouped_streams[name] = []
                        self.grouped_streams[name].append(stream)
            
            logger.info(f"Grouped {len(self.grouped_streams)} unique streams")
    
    def get_grouped_streams(self) -> Dict[str, List[StreamInfo]]:
        """Get current grouped streams"""
        return self.grouped_streams.copy()