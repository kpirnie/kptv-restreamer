import asyncio
import re


class StreamNameMapper:
    """Handles stream name encoding/decoding for URL safety"""
    
    def __init__(self):
        self.name_to_id = {}
        self.id_to_name = {}
        self._lock = asyncio.Lock()
    
    def _generate_safe_id(self, name: str) -> str:
        """Generate a URL-safe ID from stream name - alphanumeric only"""
        clean_id = re.sub(r'[^a-zA-Z0-9]', '', name)
        
        if not clean_id:
            clean_id = "unknownstream"
        
        return clean_id
    
    async def get_stream_id(self, name: str) -> str:
        """Get URL-safe ID for stream name"""
        async with self._lock:
            if name not in self.name_to_id:
                stream_id = self._generate_safe_id(name)
                
                base_id = stream_id
                counter = 1
                while stream_id in self.id_to_name:
                    stream_id = f"{base_id}{counter}"
                    counter += 1
                
                self.name_to_id[name] = stream_id
                self.id_to_name[stream_id] = name
            
            return self.name_to_id[name]
    
    async def get_stream_name(self, stream_id: str) -> str:
        """Get original stream name from URL-safe ID"""
        async with self._lock:
            return self.id_to_name.get(stream_id, "")
    
    async def get_all_mappings(self) -> dict:
        """Get all current mappings for debugging"""
        async with self._lock:
            return {
                "name_to_id": self.name_to_id.copy(),
                "id_to_name": self.id_to_name.copy(),
                "total_streams": len(self.name_to_id),
                "total_unique_ids": len(self.id_to_name)
            }