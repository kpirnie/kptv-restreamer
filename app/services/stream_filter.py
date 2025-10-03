import re
import logging
from typing import List
from app.models import FilterConfig, StreamInfo

logger = logging.getLogger(__name__)


class StreamFilter:
    """Handles stream filtering based on regex patterns"""
    
    def __init__(self, config: FilterConfig):
        self.config = config
        self._compile_patterns()
    
    def _compile_patterns(self):
        """Compile regex patterns"""
        try:
            self.include_name_regex = [re.compile(p, re.IGNORECASE) 
                                      for p in self.config.include_name_patterns]
            self.include_stream_regex = [re.compile(p, re.IGNORECASE) 
                                        for p in self.config.include_stream_patterns]
            self.exclude_name_regex = [re.compile(p, re.IGNORECASE) 
                                      for p in self.config.exclude_name_patterns]
            self.exclude_stream_regex = [re.compile(p, re.IGNORECASE) 
                                        for p in self.config.exclude_stream_patterns]
        except re.error as e:
            logger.error(f"Invalid regex pattern: {e}")
            self.include_name_regex = []
            self.include_stream_regex = []
            self.exclude_name_regex = []
            self.exclude_stream_regex = []
    
    def should_include_stream(self, stream: StreamInfo) -> bool:
        """Check if stream should be included based on filters"""
        try:
            for pattern in self.exclude_name_regex:
                if pattern.search(stream.name):
                    return False
            
            for pattern in self.exclude_stream_regex:
                if pattern.search(stream.url):
                    return False
            
            if self.include_name_regex:
                name_match = any(pattern.search(stream.name) 
                               for pattern in self.include_name_regex)
                if not name_match:
                    return False
            
            if self.include_stream_regex:
                stream_match = any(pattern.search(stream.url) 
                                 for pattern in self.include_stream_regex)
                if not stream_match:
                    return False
            
            return True
        except Exception as e:
            logger.error(f"Error filtering stream {stream.name}: {e}")
            return False