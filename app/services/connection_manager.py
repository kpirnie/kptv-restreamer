import asyncio
from typing import Dict, Any


class ConnectionManager:
    """Manages connection limits and tracking"""
    
    def __init__(self, max_total: int):
        self.max_total = max_total
        self.source_connections: Dict[str, int] = {}
        self.source_limits: Dict[str, int] = {}
        self.total_connections = 0
        self._lock = asyncio.Lock()
    
    def can_acquire_connection(self, source_id: str) -> bool:
        """Check if a connection can be acquired without actually acquiring it"""
        current_source = self.source_connections.get(source_id, 0)
        source_limit = self.source_limits.get(source_id, 5)
        
        return (current_source < source_limit and 
                self.total_connections < self.max_total)

    async def acquire_connection(self, source_id: str) -> bool:
        """Attempt to acquire a connection for a source"""
        async with self._lock:
            current_source = self.source_connections.get(source_id, 0)
            source_limit = self.source_limits.get(source_id, 5)
            
            if (current_source < source_limit and 
                self.total_connections < self.max_total):
                self.source_connections[source_id] = current_source + 1
                self.total_connections += 1
                return True
            return False
    
    async def release_connection(self, source_id: str):
        """Release a connection for a source"""
        async with self._lock:
            if source_id in self.source_connections:
                self.source_connections[source_id] = max(0, 
                    self.source_connections[source_id] - 1)
                self.total_connections = max(0, self.total_connections - 1)
    
    def set_source_limit(self, source_id: str, limit: int):
        """Set connection limit for a source"""
        self.source_limits[source_id] = limit

    async def get_connection_info(self) -> Dict[str, Any]:
        """Get detailed connection information"""
        async with self._lock:
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