import re
import logging
from typing import List
from app.models import StreamInfo
from app.sources.base import StreamSource

logger = logging.getLogger(__name__)


class M3USource(StreamSource):
    """M3U playlist source"""
    
    async def _fetch_streams(self) -> List[StreamInfo]:
        streams = []
        
        try:
            async with self.session.get(self.config.url) as resp:
                if resp.status == 200:
                    content = await resp.text()
                    streams = self._parse_m3u(content)
        except Exception as e:
            logger.error(f"Failed to fetch M3U playlist: {e}")
        
        return streams
    
    def _parse_m3u(self, content: str) -> List[StreamInfo]:
        """Parse M3U playlist content"""
        streams = []
        lines = content.strip().split('\n')
        
        current_info = {}
        for line in lines:
            line = line.strip()
            
            if line.startswith('#EXTINF:'):
                parts = line.split(',', 1)
                if len(parts) == 2:
                    current_info['name'] = parts[1].strip()
                
                if 'group-title=' in line:
                    match = re.search(r'group-title="([^"]*)"', line)
                    if match:
                        current_info['group'] = match.group(1)
                
                if 'tvg-logo=' in line:
                    match = re.search(r'tvg-logo="([^"]*)"', line)
                    if match:
                        current_info['logo'] = match.group(1)
                
                if 'tvg-name=' in line:
                    match = re.search(r'tvg-name="([^"]*)"', line)
                    if match:
                        current_info['name'] = match.group(1)
            
            elif line and not line.startswith('#'):
                if 'name' in current_info:
                    streams.append(StreamInfo(
                        name=current_info.get('name', 'Unknown'),
                        url=line,
                        source_id=self.config.name,
                        group=current_info.get('group', ''),
                        logo=current_info.get('logo', '')
                    ))
                current_info = {}
        
        return streams