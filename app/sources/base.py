import asyncio
import logging
from datetime import datetime
from typing import Dict, List
from app.models import StreamInfo, SourceConfig
import aiohttp

logger = logging.getLogger(__name__)


class StreamSource:
    """Base class for stream sources"""
    
    def __init__(self, config: SourceConfig, session: aiohttp.ClientSession):
        self.config = config
        self.session = session
        self.streams: Dict[str, StreamInfo] = {}
        self.last_refresh = None
        self._refresh_lock = asyncio.Lock()
    
    async def should_refresh(self) -> bool:
        """Check if source needs refreshing"""
        if self.last_refresh is None:
            return True
        
        elapsed = datetime.now() - self.last_refresh
        return elapsed.total_seconds() >= self.config.refresh_interval
    
    async def refresh_streams(self) -> bool:
        """Refresh stream list from source"""
        async with self._refresh_lock:
            if not await self.should_refresh():
                return True
            
            try:
                streams = await self._fetch_streams()
                self.streams = {s.name: s for s in streams}
                self.last_refresh = datetime.now()
                logger.info(f"Refreshed {len(self.streams)} streams from {self.config.name}")
                return True
            except Exception as e:
                logger.error(f"Failed to refresh streams from {self.config.name}: {e}")
                return False
    
    async def _fetch_streams(self) -> List[StreamInfo]:
        """Fetch streams from source (implemented by subclasses)"""
        raise NotImplementedError